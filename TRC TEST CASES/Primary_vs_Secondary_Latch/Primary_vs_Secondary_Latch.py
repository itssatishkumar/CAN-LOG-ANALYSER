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

# =========================================================
# FORCE LIVE STDOUT
# =========================================================
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# =========================================================
# PATH SETUP (same as Script-1)
# =========================================================
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from trc_utils import fast_datetime_from_str

PROGRESS_STEP = 0.5
MIN_SOC_STEP = 0.1


# =========================================================
# STEP-BASED PROGRESS
# =========================================================
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


# =========================================================
# CAN REGEX
# =========================================================
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


def parse_ts(t):
    return fast_datetime_from_str(t)


# =========================================================
# FILE SELECT (UNCHANGED)
# =========================================================
def select_trc_file():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(
        title="Select TRC File",
        filetypes=[("TRC Files", "*.trc")],
    )


# =========================================================
# TRC PICKING FIX (ONLY ADDITION)
# =========================================================
def get_trc_file_once():
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        return sys.argv[1]

    trc_env = os.environ.get("TRC_FILE")
    if trc_env and os.path.isfile(trc_env):
        return trc_env

    saved = Path(__file__).resolve().parent / "selected_trc.txt"
    if saved.exists():
        p = saved.read_text().strip()
        if os.path.isfile(p):
            return p

    trc = select_trc_file()
    if trc and os.path.isfile(trc):
        saved.write_text(trc)
        return trc

    raise RuntimeError("No TRC file selected")


# =========================================================
# PARSE TRC (UNCHANGED)
# =========================================================
def parse_trc(fp, progress_cb=None, total_lines=None):
    soc_list = []
    latch_list = []
    current_list = []
    temp_list = []
    ff18_list = []

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
                    soc = (int(d[0], 16) | (int(d[1], 16) << 8)) * 0.01
                    latch = int(d[4], 16)
                    soc_list.append((ts, soc))
                    latch_list.append((ts, latch))

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

    return soc_list, latch_list, current_list, temp_list, ff18_list


# =========================================================
# CHARGE SESSION DETECTION (UNCHANGED)
# =========================================================
def detect_charge_sessions(ff18_list, timeout_sec=3.0):
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


# =========================================================
# HELPERS (UNCHANGED)
# =========================================================
def lookup_before(ts, data):
    best = None
    for t, v in data:
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


def format_duration(td):
    s = int(td.total_seconds())
    return f"{s//3600}hr,{(s%3600)//60}min,{s%60}s"


# =========================================================
# BUILD CHARGE WINDOWS (UNCHANGED)
# =========================================================
def build_charge_windows(soc_list, current_list, temp_list, start_ts, end_ts):
    rows = []

    soc_start = lookup_before(start_ts, soc_list)
    soc_end = lookup_before(end_ts, soc_list)
    if not soc_start or not soc_end:
        return rows, None

    cur_soc = soc_start[1]
    ws = soc_start[0]

    for ts, soc in soc_list:
        if ts <= ws:
            continue
        if soc - cur_soc >= 10 - 1e-6:
            we = ts
            ah = integrate_window(current_list, ws, we)
            tavg = window_temp_avg(temp_list, ws, we)
            rows.append((cur_soc, cur_soc + 10, format_duration(we - ws), ah, tavg))
            cur_soc += 10
            ws = we
        if ts >= end_ts:
            break

    if soc_end[1] - cur_soc >= MIN_SOC_STEP:
        we = end_ts
        ah = integrate_window(current_list, ws, we)
        tavg = window_temp_avg(temp_list, ws, we)
        rows.append((cur_soc, soc_end[1], format_duration(we - ws), ah, tavg))

    return rows, ws


# =========================================================
# DRAW TABLE (UNCHANGED)
# =========================================================
def draw_charging_table(rows, latch_row, total_time, total_ah, output):
    cols = ["SoC Window", "Duration", "Cap Exchange", "Temp Avg"]
    col_w = [0.32, 0.28, 0.2, 0.2]

    fig_h = 0.7 + 0.45 * (len(rows) + (1 if latch_row else 0) + 2)
    fig, ax = plt.subplots(figsize=(12, fig_h))
    ax.axis("off")

    header_h = 0.06
    row_h = 0.075
    y = 1 - header_h

    x = 0
    for h, w in zip(cols, col_w):
        ax.add_patch(Rectangle((x, y), w, header_h, fc="#d0d0d0", ec="black"))
        ax.text(x + w/2, y + header_h/2, h, ha="center", va="center")
        x += w
    y -= row_h

    def draw_row(vals, bg="white"):
        nonlocal y
        x = 0
        for v, w in zip(vals, col_w):
            ax.add_patch(Rectangle((x, y), w, row_h, fc=bg, ec="black"))
            ax.text(x + w/2, y + row_h/2, v, ha="center", va="center", fontsize=9)
            x += w
        y -= row_h

    for sv, ev, dur, ah, tavg in rows:
        draw_row([
            f"{sv:.2f}% → {ev:.2f}%",
            dur,
            f"{ah:.2f} Ah",
            f"{tavg:.1f} C" if tavg else ""
        ])

    if latch_row:
        draw_row(latch_row, bg="#fce88c")

    draw_row([
        "TOTAL",
        total_time,
        f"{total_ah:.2f} Ah",
        ""
    ], bg="#a0d0ff")

    ax.add_patch(Rectangle((0, y), 1, 1 - y, fill=False, ec="black", lw=1.0))
    ax.set_xlim(-0.002, 1.002)
    ax.set_ylim(y - 0.01, 1.01)

    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches="tight", pad_inches=0.1)
    plt.close()


# =========================================================
# MAIN
# =========================================================
def main():
    trc = get_trc_file_once()
    out = Path(__file__).resolve().parent

    with open(trc, "r", encoding="utf-8", errors="ignore") as f:
        total_lines = sum(1 for _ in f)

    parse_cb   = progress_by_steps(0, 70, PROGRESS_STEP)
    session_cb = progress_by_steps(70, 90, PROGRESS_STEP)
    final_cb   = progress_by_steps(90, 100, PROGRESS_STEP)

    soc_list, latch_list, current_list, temp_list, ff18_list = parse_trc(
        trc, parse_cb, total_lines
    )

    sessions = detect_charge_sessions(ff18_list)

    rows = []
    latch_row = None
    total_ah = 0.0
    total_time = timedelta()

    for i, (st, en) in enumerate(sessions, 1):
        session_cb(i / max(1, len(sessions)))

        latch_ts = find_latch_ts(latch_list, st, en)
        if latch_ts:
            en = latch_ts

        r, last_ws = build_charge_windows(soc_list, current_list, temp_list, st, en)
        for x in r:
            rows.append(x)
            total_ah += x[3]

        if latch_ts and last_ws:
            ah = integrate_window(current_list, last_ws, latch_ts)
            tavg = window_temp_avg(temp_list, last_ws, latch_ts)
            dur = format_duration(latch_ts - last_ws)
            latch_row = [
                "100% → True Latch",
                dur,
                f"{ah:.2f} Ah",
                f"{tavg:.1f} C" if tavg else ""
            ]
            total_ah += ah

        total_time += (en - st)
        if latch_ts:
            break

    final_cb(0.7)

    draw_charging_table(
        rows,
        latch_row,
        format_duration(total_time),
        total_ah,
        out / "Primary_vs_Secondary_Latch_plot.png",
    )

    final_cb(1.0)

    (out / "Primary_vs_Secondary_Latch_results.json").write_text(
        json.dumps({"Result": "PASS"}, indent=4)
    )

    (out / "Primary_vs_Secondary_Latch_summary.json").write_text(
        json.dumps({
            "Latch_Detected": latch_row is not None,
            "Latch_Type": "Primary" if latch_row else "Secondary",
            "Charging_End_Reason": "True_Latch" if latch_row else "18FF50E5 Timeout",
            "Total_Charging_Time": format_duration(total_time),
            "Total_Capacity_Ah": f"{total_ah:.2f}"
        }, indent=4)
    )

    print("PROGRESS 100.0", flush=True)


if __name__ == "__main__":
    main()
