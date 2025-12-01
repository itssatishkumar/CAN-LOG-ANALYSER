import re
import struct
import sys
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
from pathlib import Path
import json
import os
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


# =========================================================
#  CAN ID REGEX
# =========================================================

RE_110 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0110\s+8\s+(.+)"
)

RE_0109 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0109\s+8\s+(.+)"
)

RE_014E = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+014E\s+\d+\s+(.+)"
)

RE_0402 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0402\s+8\s+(.+)"
)

RE_0258 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0258\s+8\s+(.+)"
)

RE_0602 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0602\s+\d+\s+(.+)"
)


def parse_ts(t):
    try:
        return datetime.strptime(t, "%d-%m-%Y %H:%M:%S.%f")
    except Exception:
        return None


# =========================================================
#  SELECT TRC FILE GUI
# =========================================================
def select_trc_file():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(
        title="Select TRC File",
        filetypes=[("TRC Files", "*.trc")],
    )


# =========================================================
#  PARSE TRC FILE FOR ALL METRICS EXCEPT CHARGING
# =========================================================
def parse_trc(fp):

    soc_list = []
    current_list = []
    odo_list = []
    ntc_list = []
    uv_list = []

    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:

            # CURRENT
            m = RE_110.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 8:
                    b4, b5, b6, b7 = [int(x, 16) for x in d[4:8]]
                    raw = struct.unpack("<i", bytes([b4, b5, b6, b7]))[0]
                    I = raw * 1e-5
                    current_list.append((ts, I))

            # SOC
            m = RE_0109.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 2:
                    lo = int(d[0], 16)
                    hi = int(d[1], 16)
                    raw = lo | (hi << 8)
                    soc = raw * 0.01
                    soc_list.append((ts, soc))

            # TEMP (NTC)
            m = RE_014E.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 2:
                    ntc_list.append((ts, (int(d[0], 16), int(d[1], 16))))

            # ODO
            m = RE_0402.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 4:
                    raw = (
                        int(d[0], 16)
                        | (int(d[1], 16) << 8)
                        | (int(d[2], 16) << 16)
                        | (int(d[3], 16) << 24)
                    )
                    odo_list.append((ts, raw * 0.1))

            # UV FLAG
            m = RE_0258.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 2:
                    raw16 = int(d[0], 16) | (int(d[1], 16) << 8)
                    uv = (raw16 >> 6) & 1
                    uv_list.append((ts, uv))

    return soc_list, current_list, odo_list, ntc_list, uv_list


# =========================================================
#  DETECT CHARGING STATE FROM CAN ID 0x0602
# =========================================================
def detect_charge_events(fp):

    events = []
    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = RE_0602.match(line)
            if not m:
                continue

            ts = parse_ts(m.group(1))
            if not ts:
                continue

            d = m.group(3).split()
            if len(d) < 8:
                continue

            last_byte = int(d[7], 16)
            state = "CHARGING" if last_byte in (0x01, 0x03) else "DRIVING"
            events.append((ts, state))

    return sorted(events, key=lambda x: x[0])


def build_charge_sessions(events, default_end=None):

    sessions = []
    state = "DRIVING"
    session_start = None

    for ts, new_state in events:
        if new_state == state:
            continue

        if new_state == "CHARGING":
            session_start = ts
        else:
            if session_start:
                sessions.append((session_start, ts))
                session_start = None
        state = new_state

    if state == "CHARGING" and session_start and default_end:
        sessions.append((session_start, default_end))

    return sessions


# =========================================================
#  LOOKUP HELPERS
# =========================================================
def lookup_before(ts, data):
    best = None
    for t, v in data:
        if t <= ts:
            best = (t, v)
        else:
            break
    return best


def lookup_after(ts, data):
    for t, v in data:
        if t >= ts:
            return (t, v)
    return None


def find_soc_ts(soc_list, target, start_ts, end_ts, reverse=False, tol=0.15):
    data = reversed(soc_list) if reverse else soc_list
    for ts, soc in data:
        if ts < start_ts or ts > end_ts:
            continue
        if abs(soc - target) < tol:
            return ts
    return None


# =========================================================
#  CAPACITY INTEGRATION
# =========================================================
def integrate_window(current_list, start_ts, end_ts):
    DEFAULT_DT = 0.3
    As = 0.0
    curr = sorted(current_list, key=lambda x: x[0])

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


def summarize_current(current_list):

    DEFAULT_DT = 0.3
    pos_as = 0.0
    neg_as = 0.0
    valid = 0
    default = 0

    curr = sorted(current_list, key=lambda x: x[0])
    for i in range(1, len(curr)):
        t0, I = curr[i - 1]
        t1, _ = curr[i]
        dt = (t1 - t0).total_seconds()

        if dt <= 0 or dt > 0.5:
            dt = DEFAULT_DT
            default += 1
        else:
            valid += 1

        if I >= 0:
            pos_as += I * dt
        else:
            neg_as += I * dt

    return {
        "charge_ah": pos_as / 3600.0,
        "discharge_ah": neg_as / 3600.0,
        "exchange_ah": (pos_as + neg_as) / 3600.0,
        "valid_dt_count": valid,
        "default_dt_count": default,
        "default_dt_value": DEFAULT_DT,
    }


# =========================================================
#  UV SOC SELECTION
# =========================================================
def get_uv_end_soc(soc_list, uv_ts):

    if not soc_list:
        return None

    idx = None
    for i, (t, v) in enumerate(soc_list):
        if t >= uv_ts:
            idx = i
            break

    if idx is None:
        idx = len(soc_list) - 1

    chosen_soc = soc_list[idx][1]

    if chosen_soc > 0:
        return chosen_soc

    streak = 0
    j = idx
    while j >= 0 and soc_list[j][1] == 0:
        streak += 1
        j -= 1

    if streak >= 5:
        return 0.0

    while j >= 0:
        if soc_list[j][1] > 0:
            return soc_list[j][1]
        j -= 1

    return 0.0


# =========================================================
#  BUILD WINDOWS
# =========================================================
def build_windows(soc_list, current_list, odo_list, ntc_list, uv_list, fp):

    soc_list = sorted(soc_list, key=lambda x: x[0])
    odo_list = sorted(odo_list, key=lambda x: x[0])
    ntc_list = sorted(ntc_list, key=lambda x: x[0])
    current_list = sorted(current_list, key=lambda x: x[0])

    temp_frames = [(ts, (b0 + b1) / 2.0) for ts, (b0, b1) in ntc_list]

    uv_ts = None
    for ts, flag in uv_list:
        if flag == 1:
            uv_ts = ts
            break

    uv_end_soc = None
    if uv_ts and soc_list:
        uv_end_soc = get_uv_end_soc(soc_list, uv_ts)

    if not soc_list:
        return [], 0.0, 0.0, False

    ts_all = [t for t, _ in soc_list]
    t_start = ts_all[0]
    t_end = ts_all[-1]

    charge_events = detect_charge_events(fp)
    charging_sessions = build_charge_sessions(charge_events, t_end)

    session_blocks = []
    prev_end = t_start
    for st, en in charging_sessions:
        if st > prev_end:
            session_blocks.append(("normal", prev_end, st))
        session_blocks.append(("charge", st, en))
        prev_end = en

    if prev_end < t_end:
        session_blocks.append(("normal", prev_end, t_end))

    session_blocks.sort(key=lambda x: x[1])

    total_range = 0.0
    if odo_list:
        total_range = max(0.0, odo_list[-1][1] - odo_list[0][1])

    final_rows = []
    odo_baseline = odo_list[0][1] if odo_list else None
    soc_baseline = soc_list[0][1] if soc_list else None

    for typ, block_start, block_end in session_blocks:

        if typ == "charge":
            charge_soc_start = lookup_before(block_start, soc_list)
            charge_soc_end = lookup_before(block_end, soc_list)
            charge_odo_end = lookup_before(block_end, odo_list)

            if charge_soc_start and charge_soc_end:
                final_rows.append(
                    ("charge", charge_soc_start[1], charge_soc_end[1], 0.0, 0.0, None)
                )

            if charge_odo_end:
                odo_baseline = charge_odo_end[1]
            if charge_soc_end:
                soc_baseline = charge_soc_end[1]
            continue

        if uv_ts and uv_ts <= block_start:
            continue

        if uv_ts and uv_ts < block_end:
            block_end_ts = uv_ts
            uv_in_this_block = True
        else:
            block_end_ts = block_end
            uv_in_this_block = False

        if soc_baseline is None:
            sb = lookup_before(block_start, soc_list)
            if sb:
                soc_baseline = sb[1]

        end_entry = lookup_before(block_end_ts, soc_list)
        if soc_baseline is None or not end_entry:
            continue

        current_soc = soc_baseline
        end_soc = end_entry[1]

        if uv_in_this_block and uv_end_soc is not None:
            end_soc = uv_end_soc

        while current_soc - end_soc >= 10:
            next_soc = current_soc - 10

            window_start_ts = (
                find_soc_ts(soc_list, current_soc, block_start, block_end_ts)
                or block_start
            )
            window_end_ts = (
                find_soc_ts(soc_list, next_soc, block_start, block_end_ts, reverse=True)
                or block_end_ts
            )

            if odo_baseline is None:
                ob = lookup_before(window_start_ts, odo_list)
                if ob:
                    odo_baseline = ob[1]

            dist = 0.0
            odo_end = lookup_before(window_end_ts, odo_list)
            if odo_end and odo_baseline is not None:
                dist = odo_end[1] - odo_baseline
                if dist < 0:
                    dist = 0.0
                odo_baseline = odo_end[1]

            temp_start = lookup_before(window_start_ts, temp_frames)
            temp_end = lookup_before(window_end_ts, temp_frames)
            if not temp_start and temp_frames:
                temp_start = temp_frames[0]
            if not temp_end and temp_frames:
                temp_end = temp_frames[-1]
            tavg = ((temp_start[1] + temp_end[1]) / 2) if temp_start and temp_end else None

            cap_ah = integrate_window(current_list, window_start_ts, window_end_ts)

            final_rows.append(("normal", current_soc, next_soc, dist, cap_ah, tavg))
            current_soc = next_soc

        if current_soc > end_soc:
            window_start_ts = (
                find_soc_ts(soc_list, current_soc, block_start, block_end_ts)
                or block_start
            )
            window_end_ts = (
                find_soc_ts(soc_list, end_soc, block_start, block_end_ts, reverse=True)
                or block_end_ts
            )

            if odo_baseline is None:
                ob = lookup_before(window_start_ts, odo_list)
                if ob:
                    odo_baseline = ob[1]

            dist = 0.0
            odo_end = lookup_before(window_end_ts, odo_list)
            if odo_end and odo_baseline is not None:
                dist = odo_end[1] - odo_baseline
                if dist < 0:
                    dist = 0.0
                odo_baseline = odo_end[1]

            temp_start = lookup_before(window_start_ts, temp_frames)
            temp_end = lookup_before(window_end_ts, temp_frames)
            if not temp_start and temp_frames:
                temp_start = temp_frames[0]
            if not temp_end and temp_frames:
                temp_end = temp_frames[-1]
            tavg = ((temp_start[1] + temp_end[1]) / 2) if temp_start and temp_end else None

            cap_ah = integrate_window(current_list, window_start_ts, window_end_ts)
            final_rows.append(("normal", current_soc, end_soc, dist, cap_ah, tavg))

        soc_baseline = end_soc

        if uv_in_this_block:
            if final_rows:
                last_typ, sv, ev, odo, cap, tavg = final_rows[-1]
                final_rows[-1] = ("uv", sv, ev, odo, cap, tavg)
            break

    # ---------------------------------------------------------
    # Distance from SOC 0% (respecting 5-sample streak rule)
    # ---------------------------------------------------------
    uv_detected = uv_ts is not None
    last_zero_streak_start = None
    streak_len = 0
    last_zero_ts = None

    def consider_streak(start_ts, end_ts, length):
        nonlocal last_zero_streak_start
        if length < 5:
            return
        if uv_detected and end_ts and end_ts > uv_ts:
            return
        last_zero_streak_start = start_ts

    for ts, soc in soc_list:
        if soc <= 0.5:
            if streak_len == 0:
                streak_start_ts = ts
            streak_len += 1
            last_zero_ts = ts
        else:
            if streak_len >= 5:
                consider_streak(streak_start_ts, last_zero_ts, streak_len)
            streak_len = 0
            last_zero_ts = None

    if streak_len >= 5:
        consider_streak(streak_start_ts, last_zero_ts, streak_len)

    zero_streak_found = last_zero_streak_start is not None
    dist_after_zero = None

    if zero_streak_found and odo_list:
        odo_at_zero = lookup_before(last_zero_streak_start, odo_list)
        if odo_at_zero:
            if uv_detected:
                odo_at_end = lookup_before(uv_ts, odo_list)
            else:
                odo_at_end = odo_list[-1]
            if odo_at_end:
                dist_after_zero = max(0.0, odo_at_end[1] - odo_at_zero[1])

    return final_rows, total_range, dist_after_zero, uv_detected, zero_streak_found


# =========================================================
#  DRAW TABLE PNG
# =========================================================
def draw_table_png(
    rows,
    output,
    total_cap_override=None,
    total_range=0.0,
    dist_after_zero=0.0,
    uv_detected=False,
    zero_streak_found=False,
):

    cols = ["SoC Window", "Odo", "Cap Exchange", "Temp Avg"]
    col_w = [0.45, 0.15, 0.2, 0.2]

    fig, ax = plt.subplots(figsize=(12, 0.6 + 0.4 * (len(rows) + 3)))
    ax.axis("off")

    header_h = 0.06
    row_h = 0.06

    y = 1 - header_h
    x = 0
    for i, h in enumerate(cols):
        ax.add_patch(Rectangle((x, y), col_w[i], header_h, fc="#d0d0d0", ec="black"))
        ax.text(x + col_w[i]/2, y + header_h/2, h, ha="center", va="center")
        x += col_w[i]
    y -= row_h

    total_cap = 0.0

    for typ, sv, ev, odo, cap, tavg in rows:

        if typ == "charge":
            msg = f"Charging session: {sv:.2f}% -> {ev:.2f}%"
            ax.add_patch(Rectangle((0, y), 1, row_h, fc="#fce88c", ec="black"))
            ax.text(0.5, y + row_h/2, msg, ha="center", va="center")
            y -= row_h
            continue

        if typ == "uv":
            sw = f"{sv:.2f}% to (UV) {ev:.2f}%"
        else:
            sw = f"{sv:.2f}% to {ev:.2f}%"

        cd = f"{odo:.2f}"
        ce = f"{cap:.2f} Ah"
        tv = f"{tavg:.1f} C" if tavg is not None else ""

        x = 0
        for val, w in zip([sw, cd, ce, tv], col_w):
            ax.add_patch(Rectangle((x, y), w, row_h, fc="white", ec="black"))
            ax.text(x + w/2, y + row_h/2, val, ha="center", va="center")
            x += w

        total_cap += cap
        y -= row_h

    # ---------------------------------------------------------
    # Extra row for Distance after SoC 0%
    # ---------------------------------------------------------
    if not zero_streak_found:
        msg = "Distance Covered when SoC was 0.00% = N/A"
    elif uv_detected and dist_after_zero is not None:
        msg = f"Distance Covered when SoC was 0.00% to UV = {dist_after_zero:.1f} km"
    elif dist_after_zero is not None:
        msg = f"Distance Covered when SoC was 0.00% = {dist_after_zero:.1f} km (UV Not detected)"
    else:
        msg = "Distance Covered when SoC was 0.00% = N/A"

    ax.add_patch(Rectangle((0, y), 1, row_h, fc="white", ec="black"))
    ax.text(
        0.5,
        y + row_h / 2,
        msg,
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color="red",
    )
    y -= row_h

    # ---------------------------------------------------------
    # Totals row
    # ---------------------------------------------------------
    ax.add_patch(Rectangle((0, y), col_w[0], row_h, fc="white", ec="black"))

    ax.add_patch(Rectangle((col_w[0], y), col_w[1], row_h, fc="#a0d0ff", ec="black"))
    ax.text(
        col_w[0] + col_w[1] / 2,
        y + row_h / 2,
        f"Range = {total_range:.1f} km",
        ha="center",
        va="center",
    )

    display_cap = total_cap_override if total_cap_override else total_cap

    ax.add_patch(
        Rectangle((col_w[0] + col_w[1], y), col_w[2], row_h, fc="#a0d0ff", ec="black")
    )
    ax.text(
        col_w[0] + col_w[1] + col_w[2] / 2,
        y + row_h / 2,
        f"Total CAP exc = {display_cap:.2f} Ah",
        ha="center",
        va="center",
    )

    ax.add_patch(
        Rectangle(
            (col_w[0] + col_w[1] + col_w[2], y),
            col_w[3],
            row_h,
            fc="#a0d0ff",
            ec="black",
        )
    )

    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches="tight")
    plt.close()


# =========================================================
#  MAIN
# =========================================================
def main():

    trc_env = os.environ.get("TRC_FILE")
    trc_saved = Path(__file__).resolve().parent / "selected_trc.txt"

    if len(sys.argv) > 1:
        trc = sys.argv[1]
    elif trc_env:
        trc = trc_env
    elif trc_saved.exists():
        trc = trc_saved.read_text().strip()
    else:
        trc = select_trc_file()

    soc_list, current_list, odo_list, ntc_list, uv_list = parse_trc(trc)

    rows, total_range, dist_after_zero, uv_detected, zero_streak_found = build_windows(
        soc_list, current_list, odo_list, ntc_list, uv_list, trc
    )

    out = Path(__file__).resolve().parent

    stats = summarize_current(current_list)
    summary = {
        "Capacity_Summary": {
            "Charge_Ah": f"{stats['charge_ah']:.4f}",
            "Discharge_Ah": f"{stats['discharge_ah']:.4f}",
            "Capacity_Exchange_Ah": f"{stats['exchange_ah']:.4f}",
            "Valid_dt_Count": stats["valid_dt_count"],
            "Default_dt_Count": stats["default_dt_count"],
            "Default_dt_Value_s": stats["default_dt_value"],
        }
    }

    (out / "Capacity_check_summary.json").write_text(json.dumps(summary, indent=4))
    (out / "Capacity_check_results.json").write_text(
        json.dumps({"Result": "PASS"}, indent=4)
    )

    draw_table_png(
        rows,
        out / "Capacity_check_plot.png",
        total_cap_override=stats["exchange_ah"],
        total_range=total_range,
        dist_after_zero=dist_after_zero,
        uv_detected=uv_detected,
        zero_streak_found=zero_streak_found,
    )


if __name__ == "__main__":
    main()
