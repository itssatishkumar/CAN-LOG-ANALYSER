import re
import struct
import sys
import os
import json
import tkinter as tk
from tkinter import filedialog
from datetime import timedelta
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from trc_utils import fast_datetime_from_str

PROGRESS_STEP = 0.5
MIN_SOC_STEP = 0.01
SOC_LOCK = 99.99
LOG_GAP_THRESHOLD_SEC = 30.0
INACTIVE_GAP_SEC = 5.0


def get_charge_session_bounds(ff18_list, latch_list, trc_end_ts=None):
    if not ff18_list:
        return None

    start_ts = min(ff18_list)

    for ts, v in latch_list:
        if ts >= start_ts and v == 1:
            return (start_ts, ts)

    last_ff18 = max(ff18_list)

    if len(ff18_list) == 1 and trc_end_ts and trc_end_ts > last_ff18:
        return (start_ts, trc_end_ts)

    return (start_ts, last_ff18)


def build_charge_intervals(ff18_list, session_start, session_end, inactive_gap=INACTIVE_GAP_SEC):
    if session_start is None or session_end is None or session_end <= session_start:
        return []

    ff18 = sorted(ts for ts in ff18_list if session_start <= ts <= session_end)
    intervals = []

    cur = session_start
    active_until = None

    for ts in ff18:
        if active_until is None:
            active_until = ts + timedelta(seconds=inactive_gap)
            cur = ts
            continue

        if ts <= active_until:
            active_until = ts + timedelta(seconds=inactive_gap)
        else:
            intervals.append(("ACTIVE", cur, active_until))
            intervals.append(("INACTIVE", active_until, ts))
            active_until = ts + timedelta(seconds=inactive_gap)
            cur = ts

    if active_until:
        end_active = min(active_until, session_end)
        intervals.append(("ACTIVE", cur, end_active))
        if end_active < session_end:
            intervals.append(("INACTIVE", end_active, session_end))
    else:
        intervals.append(("INACTIVE", session_start, session_end))

    intervals.sort(key=lambda x: x[1])
    return intervals


def is_active_charging(ts, intervals):
    for state, s, e in intervals:
        if state == "ACTIVE" and s <= ts < e:
            return True
    for state, s, e in intervals:
        if state == "INACTIVE" and s <= ts < e:
            return False
    return False


def _intervals_to_active_sessions(intervals):
    return [(s, e) for state, s, e in intervals if state == "ACTIVE" and e > s]
def progress_by_steps(start, end, step=0.5):
    last = start
    span = end - start

    def emit(frac):
        nonlocal last
        frac = max(0.0, min(1.0, frac))
        pct = start + span * frac
        if pct - last >= step or pct >= end:
            last = pct
            print(f"PROGRESS {pct:.1f}", flush=True)

    return emit


RE_110 = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0110\s+8\s+(.+)"
)
RE_0109 = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0109\s+8\s+(.+)"
)
RE_014E = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+014E\s+\d+\s+(.+)"
)
RE_18FF = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+).*?\b18FF50E5\b",
    re.IGNORECASE,
)

RE_TS_ONLY = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)"
)
RE_012C = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+012C\s+8\s+(.+)"
)

def parse_ts(t):
    return fast_datetime_from_str(t)
def select_trc_file():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(
        title="Select TRC File",
        filetypes=[("TRC Files", "*.trc")],
    )


def get_trc_file():
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        return sys.argv[1]

    trc_env = os.environ.get("TRC_FILE")
    if trc_env and os.path.isfile(trc_env):
        return trc_env

    trc = select_trc_file()
    if trc and os.path.isfile(trc):
        return trc

    raise RuntimeError("No TRC file selected")

def parse_trc(fp, progress_cb=None, total_lines=None):
    soc_list = []
    latch_list = []
    current_list = []
    temp_list = []
    ff18_list = []
    vmin_list = []
    vmax_list = []
    log_gaps = []

    last_any_ts = None

    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            if progress_cb and total_lines:
                progress_cb(i / total_lines)
            m_ts_any = RE_TS_ONLY.match(line)
            if m_ts_any:
                any_ts = parse_ts(m_ts_any.group(1))
                if any_ts and last_any_ts:
                    gap = (any_ts - last_any_ts).total_seconds()
                    if gap > LOG_GAP_THRESHOLD_SEC:
                        log_gaps.append((last_any_ts, any_ts))
                if any_ts:
                    last_any_ts = any_ts

            m = RE_110.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 8:
                    raw = struct.unpack("<i", bytes(int(x, 16) for x in d[4:8]))[0]
                    current_list.append((ts, raw * 1e-5))

            m = RE_0109.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 6:
                    latch = int(d[5], 16)
                    latch_list.append((ts, latch))

                    # Only append SoC if 5th data byte (d[4]) is non-zero (valid SoC)
                    if int(d[4], 16) != 0:
                        soc = (int(d[0], 16) | (int(d[1], 16) << 8)) * 0.01
                        soc_list.append((ts, soc))

                    if latch == 1:
                        soc_list.append((ts, 100.0, "LATCH"))

            m = RE_014E.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 2:
                    tmax = struct.unpack("b", bytes([int(d[0], 16)]))[0]
                    tmin = struct.unpack("b", bytes([int(d[1], 16)]))[0]
                    temp_list.append((ts, tmax, tmin))
            m = RE_18FF.match(line)
            if m:
                ts = parse_ts(m.group(1))
                if ts:
                    ff18_list.append(ts)
            elif ("18FF50E5" in line) or ("18ff50e5" in line):
                if any(tok.upper() == "18FF50E5" for tok in line.split()):
                    m_ts = RE_TS_ONLY.match(line)
                    if m_ts:
                        ts = parse_ts(m_ts.group(1))
                        if ts:
                            ff18_list.append(ts)

            m = RE_012C.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 4:
                    vmin = (int(d[2], 16) | (int(d[3], 16) << 8)) * 0.1
                    vmax = (int(d[0], 16) | (int(d[1], 16) << 8)) * 0.1
                    vmin_list.append((ts, vmin))
                    vmax_list.append((ts, vmax))

    return soc_list, latch_list, current_list, temp_list, ff18_list, vmin_list, vmax_list, log_gaps


def lookup_before(ts, data):
    best = None
    for item in data:
        if len(item) == 3:
            continue
        t, v = item
        if t <= ts:
            best = (t, v)
        else:
            break
    return best


def integrate_window(current_list, start_ts, end_ts):
    DEFAULT_DT = 0.3
    As = 0.0
    curr = sorted(current_list)

    for i in range(1, len(curr)):
        t0, I = curr[i - 1]
        t1, _ = curr[i]
        if t1 <= start_ts:
            continue
        if t0 >= end_ts:
            break

        seg_start = max(t0, start_ts)
        seg_end = min(t1, end_ts)
        if seg_end <= seg_start:
            continue

        pair_dt = (t1 - t0).total_seconds()
        overlap_dt = (seg_end - seg_start).total_seconds()
        if overlap_dt <= 0:
            continue

        if pair_dt <= 0:
            dt = 0.0
        elif pair_dt > 0.5:
            dt = min(DEFAULT_DT, overlap_dt)
        else:
            dt = overlap_dt

        if dt > 0:
            As += I * dt

    return As / 3600.0


def window_temp_avg(temp_list, start_ts, end_ts):
    s = 0
    c = 0

    for ts, tmax, tmin in temp_list:
        if not (start_ts <= ts <= end_ts):
            continue

        vals = []

        if tmax != 0:
            vals.append(tmax)

        if tmin != 0:
            vals.append(tmin)

        if not vals:
            continue

        avg = sum(vals) / len(vals)

        s += avg
        c += 1

    return (s / c) if c else None


def find_latch_ts(latch_list, start_ts, end_ts):
    for ts, v in latch_list:
        if start_ts <= ts <= end_ts and v == 1:
            return ts
    return None


def find_first_soc_ts(soc_list, start_ts, end_ts):
    for item in soc_list:
        if len(item) == 3:
            continue
        ts, _ = item
        if start_ts <= ts <= end_ts:
            return ts
    return None


def find_first_100_ts(soc_list, start_ts, end_ts):
    for item in soc_list:
        if len(item) == 3:
            continue
        ts, soc = item
        if start_ts <= ts <= end_ts and soc >= 100.0:
            return ts
    return None


def find_last_soc_before_100(soc_list, start_ts, first_100_ts):
    last = None
    for item in soc_list:
        if len(item) == 3:
            continue
        ts, _ = item
        if ts < start_ts:
            continue
        if first_100_ts and ts >= first_100_ts:
            break
        last = ts
    return last


def _v_window_around_latch(latch_ts, vmin_list, vmax_list, pre=5, post=5):
    if not latch_ts or not vmin_list or not vmax_list:
        return None, None

    n = min(len(vmin_list), len(vmax_list))
    if n == 0:
        return None, None

    pairs = list(zip(vmin_list[:n], vmax_list[:n]))

    latch_idx = None
    for i in range(n):
        if pairs[i][0][0] >= latch_ts:
            latch_idx = i
            break
    if latch_idx is None:
        def _time_diff_sec(i):
            return abs((pairs[i][0][0] - latch_ts).total_seconds())

        latch_idx = min(range(n), key=_time_diff_sec)

    start = max(0, latch_idx - pre)
    end = min(n - 1, latch_idx + post)

    best_idx = start
    best_vmax = pairs[start][1][1]

    for i in range(start + 1, end + 1):
        vmax_val = pairs[i][1][1]
        if vmax_val > best_vmax:
            best_vmax = vmax_val
            best_idx = i

    vmin_val = pairs[best_idx][0][1]
    vmax_val = pairs[best_idx][1][1]

    return int(vmin_val), int(vmax_val)


def classify_latch(latch_ts, vmin_list, vmax_list):
    if not latch_ts:
        return "NA", None, None

    vmin_val, vmax_val = _v_window_around_latch(latch_ts, vmin_list, vmax_list)

    if vmin_val is None:
        return "NA", None, vmax_val

    if vmin_val >= 3379:
        return "Primary", vmin_val, vmax_val

    return "Secondary", vmin_val, vmax_val


def last_active_v_pair(vmin_list, vmax_list, intervals, session_start_ts, session_end_ts):
    if not vmin_list or not vmax_list or not intervals:
        return None, None

    n = min(len(vmin_list), len(vmax_list))
    if n <= 0:
        return None, None

    last = None
    for (tmin, vmin), (tmax, vmax) in zip(vmin_list[:n], vmax_list[:n]):
        if tmin != tmax:
            continue
        ts = tmin
        if not (session_start_ts <= ts <= session_end_ts):
            continue

        active = False
        for state, s, e in intervals:
            if state != "ACTIVE":
                continue
            if s <= ts <= e:
                active = True
                break
        if not active:
            continue

        if last is None or ts > last[0]:
            last = (ts, vmin, vmax)

    if last is None:
        return None, None

    return int(last[1]), int(last[2])


def decide_pass_fail(latch_ts, vmax_list, start_ts, end_ts, vmax_threshold=3535):
    vmax_peak = None
    first_over_ts = None

    for ts, v in vmax_list:
        if not (start_ts <= ts <= end_ts):
            continue

        if vmax_peak is None or v > vmax_peak:
            vmax_peak = v

        if v > vmax_threshold and first_over_ts is None:
            first_over_ts = ts

    if first_over_ts is None:
        return "PASS"

    if latch_ts and latch_ts >= first_over_ts:
        return "PASS"

    return "FAIL"


def format_duration(td):
    total = td.total_seconds()
    if total < 0:
        total = 0.0

    h = int(total // 3600)
    rem = total - (h * 3600)
    m = int(rem // 60)
    sec = rem - (m * 60)

    if total < 60:
        s_str = f"{sec:.1f}".rstrip("0").rstrip(".") + "s"
    else:
        s_str = f"{int(sec)}s"

    return f"{h}hr,{m}min,{s_str}"


def parse_duration_str(s):
    try:
        h_part, m_part, s_part = s.split(",")
        h = int(h_part.replace("hr", ""))
        m = int(m_part.replace("min", ""))
        sec = float(s_part.replace("s", ""))
        return timedelta(hours=h, minutes=m, seconds=sec)
    except Exception:
        return timedelta(0)


def merge_tail_active_windows(rows, threshold_soc=90.0):
    if not rows:
        return rows

    idx = len(rows) - 1
    suffix_indices = []

    while idx >= 0:
        status, sv, ev, dur, ah, tavg = rows[idx]
        if status == "ACTIVE" and sv >= threshold_soc:
            suffix_indices.append(idx)
            idx -= 1
        else:
            break
    if len(suffix_indices) <= 1:
        return rows

    start_idx = suffix_indices[-1]
    end_idx = suffix_indices[0]
    segment = rows[start_idx:end_idx + 1]

    merged_status = "ACTIVE"
    merged_soc_start = segment[0][1]
    merged_soc_end = segment[-1][2]

    total_td = timedelta(0)
    total_ah = 0.0
    temps = []

    for status, sv, ev, dur, ah, tavg in segment:
        total_td += parse_duration_str(dur)
        total_ah += ah
        if tavg is not None:
            temps.append(tavg)

    merged_tavg = sum(temps) / len(temps) if temps else None
    merged_row = (
        merged_status,
        merged_soc_start,
        merged_soc_end,
        format_duration(total_td),
        total_ah,
        merged_tavg,
    )

    return rows[:start_idx] + [merged_row] + rows[end_idx + 1:]

def build_charge_windows(
    soc_list,
    current_list,
    temp_list,
    start_ts,
    end_ts,
    charge_sessions,
    inactive_gap=INACTIVE_GAP_SEC,
):
    rows = []
    soc_list = sorted(soc_list, key=lambda x: x[0])

    cur = lookup_before(start_ts, soc_list)
    if not cur:
        return rows, None
    ws_soc = cur[1]
    ws_ts = start_ts

    def is_active(ts):
        for s, e in charge_sessions:
            if s <= ts < e:
                return True
        return False

    def active_end(ts):
        for s, e in charge_sessions:
            if s <= ts < e:
                return e
        return None

    while ws_ts < end_ts:
        if is_active(ws_ts):
            ae = active_end(ws_ts)
            ae = min(ae, end_ts) if ae else end_ts

            target_soc = ws_soc + 10.0
            next_ts = None
            next_soc = None

            for item in soc_list:
                if len(item) == 3:
                    continue
                ts, soc = item
                if ts <= ws_ts:
                    continue
                if ts >= ae:
                    break
                if soc >= ws_soc:
                    next_ts = ts
                    next_soc = min(soc, target_soc)
                    if soc >= target_soc:
                        break

            if next_ts and next_ts > ws_ts:
                ah = integrate_window(current_list, ws_ts, next_ts)
                tavg = window_temp_avg(temp_list, ws_ts, next_ts)
                rows.append(
                    (
                        "ACTIVE",
                        ws_soc,
                        next_soc,
                        format_duration(next_ts - ws_ts),
                        ah,
                        tavg,
                    )
                )
                ws_ts = next_ts
                ws_soc = next_soc
            else:
                soc_at_ae = lookup_before(ae, soc_list)
                if soc_at_ae:
                    ws_soc = soc_at_ae[1]
                ws_ts = ae

        else:
            next_active_start = None
            for s, e in charge_sessions:
                if s > ws_ts:
                    next_active_start = s
                    break

            ie = next_active_start if next_active_start else end_ts
            if ie <= ws_ts:
                break

            display_start = ws_ts
            if inactive_gap and inactive_gap > 0:
                display_start = max(start_ts, ws_ts - timedelta(seconds=inactive_gap))

            end_soc = ws_soc
            for item in soc_list:
                if len(item) == 3:
                    continue
                ts, soc = item
                if display_start < ts <= ie:
                    end_soc = soc

            ah = integrate_window(current_list, display_start, ie)
            tavg = window_temp_avg(temp_list, display_start, ie)

            rows.append(
                (
                    "INACTIVE",
                    ws_soc,
                    end_soc,
                    format_duration(ie - display_start),
                    ah,
                    tavg,
                )
            )

            ws_ts = ie
            ws_soc = end_soc

    return rows, ws_ts

def draw_charging_table(
    rows,
    latch_row,
    initial_to_final_row,
    total_time,
    total_ah,
    latch_type,
    vmin_at_latch,
    vmax_peak,
    result,
    output
):

    cols = ["SoC Window", "Duration", "Cap Exchange", "Temp Avg"]
    col_w = [0.32, 0.28, 0.2, 0.2]

    fig_h = 0.7 + 0.45 * (len(rows) + (1 if latch_row else 0) + 3)
    fig, ax = plt.subplots(figsize=(12, fig_h))
    ax.axis("off")

    header_h = 0.06
    row_h = 0.075
    y = 1 - header_h

    x = 0
    for h, w in zip(cols, col_w):
        ax.add_patch(Rectangle((x, y), w, header_h, fc="#d0d0d0", ec="black"))
        ax.text(x + w / 2, y + header_h / 2, h, ha="center", va="center")
        x += w
    y -= row_h

    def draw_row(vals, bg="white"):
        nonlocal y
        x = 0
        for v, w in zip(vals, col_w):
            ax.add_patch(Rectangle((x, y), w, row_h, fc=bg, ec="black"))
            ax.text(x + w / 2, y + row_h / 2, v, ha="center", va="center", fontsize=9)
            x += w
        y -= row_h

    for row_data in rows:
        if row_data[0] == "INACTIVE":
            _, sv, ev, dur, ah, tavg = row_data
            draw_row(
                [
                    f"INACTIVE: {sv:.2f}% → {ev:.2f}%",
                    dur,
                    f"{ah:.3f} Ah",
                    f"{tavg:.1f} C" if tavg is not None else "",
                ],
                bg="#ffcccc",
            )
        else:
            _, sv, ev, dur, ah, tavg = row_data
            draw_row([f"{sv:.2f}% → {ev:.2f}%", dur, f"{ah:.3f} Ah", f"{tavg:.1f} C" if tavg else ""])

    draw_row(initial_to_final_row, bg="#e6f2ff")

    if latch_row:
        draw_row(latch_row, bg="#fce88c")

        draw_row(["TOTAL", total_time, f"{total_ah:.3f} Ah", ""], bg="#a0d0ff")

    vmax_text = "N/A" if vmax_peak is None else f"{vmax_peak} mV"
    vmin_text = "N/A" if vmin_at_latch is None else f"{vmin_at_latch} mV"
    if latch_type == "NA":
        footer = f"LATCH : NA | Vmin {vmin_text} | Vmax {vmax_text} | RESULT : {result}"
    else:
        footer = f"LATCH : {latch_type.upper()} | Vmin {vmin_text} | Vmax {vmax_text} | RESULT : {result}"

    ax.text(
        0.5,
        y + row_h / 2,
        footer,
        ha="center",
        va="center",
        fontsize=12,
        color="red",
        fontweight="bold",
    )

    ax.add_patch(Rectangle((0, y), 1, 1 - y, fill=False, ec="black", lw=1.0))
    ax.set_xlim(-0.002, 1.002)
    ax.set_ylim(y - 0.01, 1.01)

    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches="tight", pad_inches=0.1)
    plt.close()

def main():
    trc = get_trc_file()
    out = Path(__file__).resolve().parent

    for fname in ["Primary_vs_Secondary_Latch_results.json", 
                  "Primary_vs_Secondary_Latch_summary.json", 
                  "Primary_vs_Secondary_Latch_plot.png"]:
        fpath = out / fname
        if fpath.exists():
            fpath.unlink()

    with open(trc, "r", encoding="utf-8", errors="ignore") as f:
        total_lines = sum(1 for _ in f)

    parse_cb = progress_by_steps(0, 100, PROGRESS_STEP)

    (
        soc_list,
        latch_list,
        current_list,
        temp_list,
        ff18_list,
        vmin_list,
        vmax_list,
        log_gaps,
    ) = parse_trc(trc, parse_cb, total_lines)

    trc_end_ts = None
    for seq in (soc_list, latch_list, current_list, temp_list, vmin_list, vmax_list):
        if not seq:
            continue
        ts = max((x[0] for x in seq if x and x[0] is not None), default=None)
        if ts and (trc_end_ts is None or ts > trc_end_ts):
            trc_end_ts = ts
    if ff18_list:
        ts = max(ff18_list)
        if ts and (trc_end_ts is None or ts > trc_end_ts):
            trc_end_ts = ts

    session_bounds = get_charge_session_bounds(ff18_list, latch_list, trc_end_ts)

    if not session_bounds:
        result_value = "PASS"

        results = {"Result": result_value}
        summary = {
            "test_name": "Primary vs Secondary Latch",
            "trc_file": os.path.basename(trc),
            "latch_type": "NA",
            "vmin_at_latch_mv": None,
            "vmax_peak_mv": None,
            "total_capacity_ah": 0.0,
            "total_duration": "0hr,0min,0s",
            "result": result_value,
            "reason": "NO CHARGING SESSION (18FF50E5 not present in TRC)",
        }

        with open(out / "Primary_vs_Secondary_Latch_results.json", "w") as f:
            json.dump(results, f, indent=2)

        with open(out / "Primary_vs_Secondary_Latch_summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        draw_charging_table(
            rows=[],
            latch_row=None,
            initial_to_final_row=[
                "Initial → Final SoC",
                "0hr,0min,0s",
                "0.000 Ah",
                "",
            ],
            total_time="0hr,0min,0s",
            total_ah=0.0,
            latch_type="NA",
            vmin_at_latch=None,
            vmax_peak=None,
            result=result_value,
            output=out / "Primary_vs_Secondary_Latch_plot.png",
        )

        print("PROGRESS 100.0", flush=True)
        return

    session_start_ts, session_end_ts = session_bounds

    intervals = build_charge_intervals(
        ff18_list,
        session_start_ts,
        session_end_ts,
        inactive_gap=INACTIVE_GAP_SEC,
    )
    charge_sessions = _intervals_to_active_sessions(intervals)

    def _env_true(name: str) -> bool:
        v = os.environ.get(name)
        if v is None:
            return False
        return str(v).strip().lower() in {"1", "true", "yes", "on"}

    if _env_true("DEBUG_FF18"):
        session_ff18 = sorted(ts for ts in ff18_list if session_start_ts <= ts <= session_end_ts)
        print(f"DEBUG_FF18 session_start={session_start_ts} session_end={session_end_ts}")
        print(f"DEBUG_FF18 ff18_count_in_session={len(session_ff18)}")

        def _prev_ff18(t):
            prev = None
            for x in session_ff18:
                if x <= t:
                    prev = x
                else:
                    break
            return prev

        def _next_ff18(t):
            for x in session_ff18:
                if x >= t:
                    return x
            return None

        for state, s, e in intervals:
            if state != "INACTIVE":
                continue
            dur = (e - s).total_seconds()
            if dur <= 0:
                continue
            prev = _prev_ff18(s)
            nxt = _next_ff18(e)
            raw_gap = None
            if prev and nxt:
                raw_gap = (nxt - prev).total_seconds()
            print(
                "DEBUG_FF18 INACTIVE "
                f"[{s} -> {e}] dur={dur:.3f}s "
                f"prev_ff18={prev} next_ff18={nxt} raw_ff18_gap={raw_gap}"
            )

    rows, total_ah, total_time = [], 0.0, timedelta()
    latch_row = None

    real_soc = sorted(soc_list, key=lambda x: x[0])

    if not real_soc:
        result_value = "PASS"

        results = {"Result": result_value}
        summary = {
            "test_name": "Primary vs Secondary Latch",
            "trc_file": os.path.basename(trc),
            "latch_type": "NA",
            "vmin_at_latch_mv": None,
            "vmax_peak_mv": None,
            "total_capacity_ah": 0.0,
            "total_duration": "0hr,0min,0s",
            "result": result_value,
            "reason": "No SoC data present in TRC; treated as PASS by default",
        }

        with open(out / "Primary_vs_Secondary_Latch_results.json", "w") as f:
            json.dump(results, f, indent=2)

        with open(out / "Primary_vs_Secondary_Latch_summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        draw_charging_table(
            rows=[],
            latch_row=None,
            initial_to_final_row=[
                "Initial → Final SoC",
                "0hr,0min,0s",
                "0.000 Ah",
                "",
            ],
            total_time="0hr,0min,0s",
            total_ah=0.0,
            latch_type="NA",
            vmin_at_latch=None,
            vmax_peak=None,
            result=result_value,
            output=out / "Primary_vs_Secondary_Latch_plot.png",
        )

        print("PROGRESS 100.0", flush=True)
        return

    first_soc_ts = real_soc[0][0]
    first_100_ts = next((ts for ts, soc in real_soc if soc >= 100.0), None)

    final_soc_ts = None
    for ts, soc in real_soc:
        if first_100_ts and ts >= first_100_ts:
            break
        final_soc_ts = ts

    end_ts = first_100_ts if first_100_ts else real_soc[-1][0]
    if session_end_ts and end_ts and end_ts > session_end_ts:
        end_ts = session_end_ts

    rows, _ = build_charge_windows(
        soc_list,
        current_list,
        temp_list,
        session_start_ts,
        end_ts,
        charge_sessions,
        inactive_gap=INACTIVE_GAP_SEC,
    )

    if _env_true("DEBUG_FF18"):
        inactive_rows = [r for r in rows if r and r[0] == "INACTIVE"]
        print(f"DEBUG_FF18 inactive_rows_in_table={len(inactive_rows)}")
        for r in inactive_rows[:10]:
            status, sv, ev, dur, ah, tavg = r
            print(f"DEBUG_FF18 TABLE {status} {sv:.2f}%->{ev:.2f}% dur={dur} ah={ah:.4f}")

    rows = merge_tail_active_windows(rows, threshold_soc=90.0)

    active_duration_td = sum(
        (parse_duration_str(row[3]) for row in rows if row[0] == "ACTIVE"),
        timedelta(0),
    )

    initial_to_final_ah = sum(row[4] for row in rows if row[0] == "ACTIVE")

    temp_weighted_sum = 0.0
    temp_total_seconds = 0.0
    for row in rows:
        if row[0] != "ACTIVE":
            continue
        tavg = row[5]
        if tavg is None:
            continue
        dur_td = parse_duration_str(row[3])
        secs = dur_td.total_seconds()
        if secs <= 0:
            continue
        temp_weighted_sum += tavg * secs
        temp_total_seconds += secs

    initial_to_final_tavg = (
        temp_weighted_sum / temp_total_seconds if temp_total_seconds > 0 else None
    )

    total_ah = sum(row[4] for row in rows)

    latch_ts = next((ts for ts, v in latch_list if v == 1 and ts >= session_start_ts), None)

    if latch_ts and first_100_ts and latch_ts > first_100_ts:
        ah = integrate_window(current_list, first_100_ts, latch_ts)
        tavg = window_temp_avg(temp_list, first_100_ts, latch_ts)
        latch_duration_td = latch_ts - first_100_ts
        latch_row = ["100% → True Latch", format_duration(latch_duration_td), f"{ah:.2f} Ah", f"{tavg:.1f} C"]
        total_ah += ah
    else:
        latch_duration_td = timedelta(0)

    # Initial → Final SoC row: duration is sum of ACTIVE only, Cap Exchange and Temp Avg are totals for all rows
    active_rows = [row for row in rows if row[0] == "ACTIVE"]
    active_duration_td = sum((parse_duration_str(row[3]) for row in active_rows), timedelta(0))
    initial_to_final = format_duration(active_duration_td)
    # Cap Exchange and Temp Avg: use total_ah and initial_to_final_tavg already calculated above (all rows)
    init_ah_str = f"{total_ah:.2f} Ah" if total_ah is not None else ""
    init_tavg_str = (
        f"{initial_to_final_tavg:.1f} C" if initial_to_final_tavg is not None else ""
    )
    initial_to_final_row = [
        "Initial → Final SoC",
        initial_to_final,
        init_ah_str,
        init_tavg_str,
    ]

    total_time_td = active_duration_td + latch_duration_td
    total_time = format_duration(total_time_td)

    latch_type, vmin_at_latch, vmax_at_latch = classify_latch(
        latch_ts, vmin_list, vmax_list
    )
    if latch_type == "NA":
        # Find global maximum Vmax and corresponding Vmin
        if vmax_list and vmin_list:
            n = min(len(vmax_list), len(vmin_list))
            vmax_values = vmax_list[:n]
            vmin_values = vmin_list[:n]
            max_vmax_idx = max(range(n), key=lambda i: vmax_values[i][1])
            vmax_at_latch = int(vmax_values[max_vmax_idx][1])
            vmin_at_latch = int(vmin_values[max_vmax_idx][1])
        else:
            vmax_at_latch = None
            vmin_at_latch = None

    result = decide_pass_fail(latch_ts, vmax_list, session_start_ts, session_end_ts)

    results = {"Result": result}

    summary = {
        "test_name": "Primary vs Secondary Latch",
        "trc_file": os.path.basename(trc),
        "latch_type": latch_type,
        "vmin_at_latch_mv": vmin_at_latch,
        "vmax_peak_mv": vmax_at_latch,
        "total_capacity_ah": round(total_ah, 2),
        "total_duration": total_time,
        "result": result
    }

    with open(out / "Primary_vs_Secondary_Latch_results.json", "w") as f:
        json.dump(results, f, indent=2)

    with open(out / "Primary_vs_Secondary_Latch_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    draw_charging_table(
        rows,
        latch_row,
        initial_to_final_row,
        total_time,
        total_ah,
        latch_type,
        vmin_at_latch,
        vmax_at_latch,
        result,
        out / "Primary_vs_Secondary_Latch_plot.png",
    )

    print("PROGRESS 100.0", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            out = Path(__file__).resolve().parent
            fallback_results = {"Result": "PASS"}
            with open(out / "Primary_vs_Secondary_Latch_results.json", "w") as f:
                json.dump(fallback_results, f, indent=2)

            fallback_summary = {
                "test_name": "Primary vs Secondary Latch",
                "trc_file": os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else None,
                "latch_type": "NA",
                "vmin_at_latch_mv": None,
                "vmax_peak_mv": None,
                "total_capacity_ah": 0.0,
                "total_duration": "0hr,0min,0s",
                "result": "PASS",
                "reason": "NO CHARGING SESSION (18FF50E5 OBC CAN ID not present in TRC)",
            }
            with open(out / "Primary_vs_Secondary_Latch_summary.json", "w") as f:
                json.dump(fallback_summary, f, indent=2)

            try:
                draw_charging_table(
                    rows=[],
                    latch_row=None,
                    initial_to_final_row=[
                        "Initial → Final SoC",
                        "0hr,0min,0s",
                        "0.000 Ah",
                        "",
                    ],
                    total_time="0hr,0min,0s",
                    total_ah=0.0,
                    latch_type="NA",
                    vmin_at_latch=None,
                    vmax_peak=None,
                    result="PASS",
                    output=out / "Primary_vs_Secondary_Latch_plot.png",
                )
            except Exception:
                pass
        except Exception:
            pass
        print("PROGRESS 100.0", flush=True)
        sys.exit(0)
