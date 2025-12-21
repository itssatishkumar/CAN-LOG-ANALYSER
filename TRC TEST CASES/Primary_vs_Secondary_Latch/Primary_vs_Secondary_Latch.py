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

# =========================================================
# PATH SETUP
# =========================================================
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from trc_utils import fast_datetime_from_str

PROGRESS_STEP = 0.5
MIN_SOC_STEP = 0.01
SOC_LOCK = 99.99
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
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+18FF50E5\s+8\s+(.+)"
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

    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            if progress_cb and total_lines:
                progress_cb(i / total_lines)

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
                if ts and len(d) >= 5:
                    latch = int(d[4], 16)
                    latch_list.append((ts, latch))

                    if latch != 0:
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
                    temp_list.append((ts, (tmax + tmin) / 2))

            m = RE_18FF.match(line)
            if m:
                ts = parse_ts(m.group(1))
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

    return soc_list, latch_list, current_list, temp_list, ff18_list, vmin_list, vmax_list

def detect_charge_sessions(ff18_list, timeout_sec=3.0):
    """Charging is inactive if 18FF50E5 is not seen for at least 3s"""
    if not ff18_list:
        return []

    ff18_list = sorted(ff18_list)
    sessions = []
    start = ff18_list[0]
    last = start

    for ts in ff18_list[1:]:
        if (ts - last).total_seconds() > timeout_sec:
            sessions.append((start, last))
            start = ts
        last = ts

    sessions.append((start, last))
    return sessions

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
        dt = (t1 - t0).total_seconds()
        if dt <= 0 or dt > 0.5:
            dt = DEFAULT_DT
        As += I * dt

    return As / 3600.0


def window_temp_avg(temp_list, start_ts, end_ts):
    s = c = 0
    for ts, v in temp_list:
        if start_ts <= ts <= end_ts:
            s += v
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


def classify_latch(latch_ts, vmin_list):
    if not latch_ts:
        return "NA", None

    vmin = lookup_before(latch_ts, vmin_list)
    if vmin and vmin[1] >= 3379:
        return "Primary", int(vmin[1])

    return "Secondary", int(vmin[1]) if vmin else None


def decide_pass_fail(latch_ts, vmax_list, start_ts, end_ts, vmax_threshold=3535):
    """Determine PASS/FAIL based on Vmax and latch timing.

    Rule: If Vmax exceeds vmax_threshold and no latch flag is seen *after*
    that event, then FAIL. Otherwise, PASS.
    """

    vmax_peak = None
    first_over_ts = None

    for ts, v in vmax_list:
        if not (start_ts <= ts <= end_ts):
            continue

        if vmax_peak is None or v > vmax_peak:
            vmax_peak = v

        if v > vmax_threshold and first_over_ts is None:
            first_over_ts = ts

    # If we never crossed the threshold, it's a PASS regardless of latch
    if first_over_ts is None:
        return "PASS", int(vmax_peak) if vmax_peak is not None else None

    # We crossed the threshold; require a latch at or after that time
    if latch_ts and latch_ts >= first_over_ts:
        return "PASS", int(vmax_peak) if vmax_peak is not None else None

    return "FAIL", int(vmax_peak) if vmax_peak is not None else None


def format_duration(td):
    s = int(td.total_seconds())
    return f"{s//3600}hr,{(s%3600)//60}min,{s%60}s"


def parse_duration_str(s):
    """Parse duration like '4hr,47min,36s' into timedelta"""
    try:
        h_part, m_part, s_part = s.split(",")
        h = int(h_part.replace("hr", ""))
        m = int(m_part.replace("min", ""))
        sec = int(s_part.replace("s", ""))
        return timedelta(hours=h, minutes=m, seconds=sec)
    except Exception:
        return timedelta(0)


def merge_tail_active_windows(rows, threshold_soc=90.0):
    """Merge final consecutive ACTIVE windows above threshold_soc into one.

    Example: ACTIVE 81.8→91.8, ACTIVE 91.8→99.9, ACTIVE 99.9→100
    becomes ACTIVE 81.8→91.8, ACTIVE 91.8→100.
    """
    if not rows:
        return rows

    # Find suffix of rows that are ACTIVE and start above threshold_soc
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

    # Determine range to merge
    start_idx = suffix_indices[-1]
    end_idx = suffix_indices[0]
    segment = rows[start_idx:end_idx + 1]

    # Aggregate
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

def build_charge_windows(soc_list, current_list, temp_list, start_ts, end_ts, charge_sessions):
    rows = []
    soc_list = sorted(soc_list, key=lambda x: x[0])

    cur = lookup_before(start_ts, soc_list)
    if not cur:
        return rows, None

    ws_ts, ws_soc = cur

    def is_in_charge_session(ts):
        for cs_start, cs_end in charge_sessions:
            if cs_start <= ts <= cs_end:
                return True
        return False

    def find_next_charge_session(after_ts):
        """Find the next charge session starting after given timestamp"""
        for cs_start, cs_end in charge_sessions:
            if cs_start > after_ts:
                return cs_start, cs_end
        return None, None

    # Per requirement: charging session becomes ACTIVE only when
    # 18FF50E5 is first seen. Do not treat any time before that as
    # an "inactive charge" period.
    if charge_sessions:
        first_cs_start = charge_sessions[0][0]
        if ws_ts < first_cs_start:
            soc_at_first = lookup_before(first_cs_start, soc_list)
            if soc_at_first:
                ws_soc = soc_at_first[1]
            ws_ts = first_cs_start

    while ws_ts < end_ts:
        # Check if we're currently in a charge session
        in_session = is_in_charge_session(ws_ts)
        
        if in_session:
            # Active charging - build 10% window
            target_soc = ws_soc + 10.0
            next_ts = None
            next_soc = None
            left_session_ts = None
            left_session_soc = None

            for item in soc_list:
                if len(item) == 3:
                    continue
                ts, soc = item
                if ts <= ws_ts:
                    continue
                if ts > end_ts:
                    break

                # Only advance window if we're in a charge session AND SoC is increasing
                if is_in_charge_session(ts) and soc >= ws_soc:
                    if soc >= target_soc:
                        next_ts = ts
                        next_soc = target_soc
                        break
                    next_ts = ts
                    next_soc = soc
                # If we left the charge session, remember where and stop
                elif not is_in_charge_session(ts):
                    left_session_ts = ts
                    left_session_soc = soc
                    break

            if next_ts and next_soc > ws_soc:
                # We managed to form an active window within this session
                ah = integrate_window(current_list, ws_ts, next_ts)
                tavg = window_temp_avg(temp_list, ws_ts, next_ts)

                if (next_ts - ws_ts).total_seconds() >= 3 and ah > 0:
                    rows.append(("ACTIVE", ws_soc, next_soc, format_duration(next_ts - ws_ts), ah, tavg))

                ws_ts = next_ts
                ws_soc = next_soc
            elif left_session_ts is not None:
                # Session ended before next 10% window; switch to INACTIVE starting
                # from the first timestamp outside the session
                ws_ts = left_session_ts
                ws_soc = left_session_soc if left_session_soc is not None else ws_soc
                continue
            else:
                # No more usable data
                break
        else:
            # Inactive period - find next session
            next_session_start, next_session_end = find_next_charge_session(ws_ts)
            
            inactive_period_end = None

            if not next_session_start or next_session_start >= end_ts:
                # No further charge session; inactive until end_ts
                inactive_period_end = end_ts
            else:
                inactive_period_end = next_session_start

            # Get SoC at end of inactive period
            inactive_end_soc = ws_soc
            for item in soc_list:
                if len(item) == 3:
                    continue
                ts, soc = item
                if ws_ts < ts <= inactive_period_end:
                    inactive_end_soc = soc

            # Add inactive row with true capacity exchange over this period
            inactive_duration = inactive_period_end - ws_ts
            if inactive_duration.total_seconds() >= 3:
                inactive_ah = integrate_window(current_list, ws_ts, inactive_period_end)
                tavg_inactive = window_temp_avg(temp_list, ws_ts, inactive_period_end)
                rows.append(("INACTIVE", ws_soc, inactive_end_soc,
                             format_duration(inactive_duration), inactive_ah, tavg_inactive))

            if not next_session_start or next_session_start >= end_ts:
                break

            ws_ts = next_session_start
            ws_soc = inactive_end_soc

    return rows, ws_ts

def draw_charging_table(
    rows,
    latch_row,
    initial_to_final,
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
            # Show true capacity exchange and average temperature for inactive periods
            draw_row(
                [
                    f"INACTIVE: {sv:.2f}% → {ev:.2f}%",
                    dur,
                    f"{ah:.2f} Ah",
                    f"{tavg:.1f} C" if tavg is not None else "",
                ],
                bg="#ffcccc",
            )
        else:  # ACTIVE
            _, sv, ev, dur, ah, tavg = row_data
            draw_row([f"{sv:.2f}% → {ev:.2f}%", dur, f"{ah:.2f} Ah", f"{tavg:.1f} C" if tavg else ""])

    draw_row(["Initial → Final SoC", initial_to_final, "", ""], bg="#e6f2ff")

    if latch_row:
        draw_row(latch_row, bg="#fce88c")

    draw_row(["TOTAL", total_time, f"{total_ah:.2f} Ah", ""], bg="#a0d0ff")

    if latch_type == "NA":
        footer = f"LATCH : NA | Vmax {vmax_peak} mV | RESULT : {result}"
    else:
        footer = f"LATCH : {latch_type.upper()} | Vmin {vmin_at_latch} mV | Vmax {vmax_peak} mV | RESULT : {result}"

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

    # Delete old output files
    for fname in ["Primary_vs_Secondary_Latch_results.json", 
                  "Primary_vs_Secondary_Latch_summary.json", 
                  "Primary_vs_Secondary_Latch_plot.png"]:
        fpath = out / fname
        if fpath.exists():
            fpath.unlink()

    with open(trc, "r", encoding="utf-8", errors="ignore") as f:
        total_lines = sum(1 for _ in f)

    parse_cb = progress_by_steps(0, 100, PROGRESS_STEP)

    soc_list, latch_list, current_list, temp_list, ff18_list, vmin_list, vmax_list = parse_trc(
        trc, parse_cb, total_lines
    )

    # Detect charge sessions - inactive if 18FF50E5 not seen for 3s
    charge_sessions = detect_charge_sessions(ff18_list)

    rows, total_ah, total_time = [], 0.0, timedelta()
    latch_row = None

    real_soc = sorted(soc_list, key=lambda x: x[0])
    first_soc_ts = real_soc[0][0]
    first_100_ts = next((ts for ts, soc in real_soc if soc >= 100.0), None)

    final_soc_ts = None
    for ts, soc in real_soc:
        if first_100_ts and ts >= first_100_ts:
            break
        final_soc_ts = ts

    # Build 10% SoC windows
    end_ts = first_100_ts if first_100_ts else real_soc[-1][0]
    rows, _ = build_charge_windows(soc_list, current_list, temp_list, first_soc_ts, end_ts, charge_sessions)

    # Merge final ACTIVE windows above 90% SoC into a single window
    rows = merge_tail_active_windows(rows, threshold_soc=90.0)

    # Duration considering only ACTIVE charging windows (exclude INACTIVE)
    active_duration_td = sum(
        (parse_duration_str(row[3]) for row in rows if row[0] == "ACTIVE"),
        timedelta(0),
    )

    # Total Ah = sum of capacity exchange from both ACTIVE and INACTIVE windows
    total_ah = sum(row[4] for row in rows)

    latch_ts = next((ts for ts, v in latch_list if v == 1), None)

    if latch_ts and first_100_ts and latch_ts > first_100_ts:
        ah = integrate_window(current_list, first_100_ts, latch_ts)
        tavg = window_temp_avg(temp_list, first_100_ts, latch_ts)
        latch_duration_td = latch_ts - first_100_ts
        latch_row = ["100% → True Latch", format_duration(latch_duration_td), f"{ah:.2f} Ah", f"{tavg:.1f} C"]
        total_ah += ah
    else:
        latch_duration_td = timedelta(0)

    # Initial→Final SoC duration excludes INACTIVE sessions
    initial_to_final = format_duration(active_duration_td)

    # TOTAL duration = active charging duration + 100%→True Latch duration (if any)
    total_time_td = active_duration_td + latch_duration_td
    total_time = format_duration(total_time_td)

    latch_type, vmin_at_latch = classify_latch(latch_ts, vmin_list)
    result, vmax_peak = decide_pass_fail(latch_ts, vmax_list, first_soc_ts, final_soc_ts)

    # Minimal results JSON: only PASS/FAIL
    results = {"Result": result}

    summary = {
        "test_name": "Primary vs Secondary Latch",
        "trc_file": os.path.basename(trc),
        "latch_type": latch_type,
        "vmin_at_latch_mv": vmin_at_latch,
        "vmax_peak_mv": vmax_peak,
        "total_capacity_ah": round(total_ah, 2),
        "total_duration": total_time,
        "result": result
    }

    # Write JSON files
    with open(out / "Primary_vs_Secondary_Latch_results.json", "w") as f:
        json.dump(results, f, indent=2)

    with open(out / "Primary_vs_Secondary_Latch_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    draw_charging_table(
        rows, latch_row, initial_to_final,
        total_time, total_ah,
        latch_type, vmin_at_latch, vmax_peak,
        result, out / "Primary_vs_Secondary_Latch_plot.png"
    )

    print("PROGRESS 100.0", flush=True)

if __name__ == "__main__":
    main()
