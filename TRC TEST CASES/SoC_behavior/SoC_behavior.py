import os
import sys
import re
import json
import struct
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from trc_utils import fast_parse_ts, progress_by_bytes

PROGRESS_STEP = 0.5  # percent granularity for live progress

# -----------------------------------------------------
# GET TRC FROM MAIN GUI ARGUMENT
# -----------------------------------------------------
if len(sys.argv) < 2:
    print("ERROR: No TRC file received from GUI!")
    sys.exit(1)

trc_path = sys.argv[1]

if not os.path.exists(trc_path):
    print(f"ERROR: TRC file not found: {trc_path}")
    sys.exit(1)

folder = os.path.dirname(os.path.abspath(__file__))
print(f"Using TRC file from GUI: {trc_path}")
emit_progress = progress_by_bytes(trc_path, step=PROGRESS_STEP)

# -----------------------------------------------------
# TRC regex
# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

SOC_ID = 0x0109
CURR_ID = 0x0110
VOLT_ID = 0x012C
ODO_ID = 0x0402

timestamps_ms = []
soc_list = []
bms_state_list = []
hhmm_list = []
full_ts_list = []

# For additional signal tracking
volt_events = []  # (ts_ms, vmax_mv)
curr_events = []  # (ts_ms, current_A, bms_state)
odo_events = []   # (ts_ms, odo_km)
last_bms_state_any = None

# -----------------------------------------------------
# PARSE TRC
# -----------------------------------------------------
with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
    for line_idx, line in enumerate(f, 1):
        emit_progress(len(line))
        m = pattern.match(line)
        if not m:
            continue

        date_str = m.group(1)
        time_str = m.group(2)
        ms_str = m.group(3)
        can_id = int(m.group(4), 16)
        dlc = int(m.group(5))
        data_str = m.group(6).strip()

        # Only bother decoding payload for IDs we care about
        if can_id not in (SOC_ID, CURR_ID, VOLT_ID, ODO_ID):
            continue

        dt, ts_ms, ts_str = fast_parse_ts(date_str, time_str, ms_str)

        bytes_hex = data_str.split()
        if len(bytes_hex) < dlc:
            continue
        data = [int(b, 16) for b in bytes_hex[:dlc]]

        if can_id == SOC_ID:
            raw_soc = (data[1] << 8) | data[0]
            soc = raw_soc * 0.01
            bms_state = data[4]

            # Track latest BMS state (even if 0) for use with current frames
            last_bms_state_any = bms_state

            # ignore only BMS state = 0 for SoC analysis
            if bms_state == 0:
                continue

            timestamps_ms.append(ts_ms)
            soc_list.append(soc)
            bms_state_list.append(bms_state)
            hhmm_list.append(dt.strftime("%H:%M:%S"))
            full_ts_list.append(ts_str)

        elif can_id == VOLT_ID:
            # 012C: Voltage_Max (bytes 0-1), Voltage_Min (bytes 2-3), scale 0.1 mV
            if len(data) >= 4:
                vmax = (data[0] | (data[1] << 8)) * 0.1
                # Track with latest known BMS state (may be None if not yet seen)
                volt_events.append((ts_ms, vmax, last_bms_state_any))

        elif can_id == CURR_ID:
            # 0110: Pack current, bytes 4-7, signed 32-bit, scale 1e-5 A
            if len(data) >= 8 and last_bms_state_any not in (None, 0):
                raw = struct.unpack("<i", bytes(data[4:8]))[0]
                current = raw * 1e-5
                curr_events.append((ts_ms, current, last_bms_state_any))

        elif can_id == ODO_ID:
            # 0402: ODO_TRIP, ODO at bits 0..31, little-endian, scale 0.1 km
            if len(data) >= 4:
                raw_odo = (
                    data[0]
                    | (data[1] << 8)
                    | (data[2] << 16)
                    | (data[3] << 24)
                )
                odo_km = raw_odo * 0.1
                odo_events.append((ts_ms, odo_km))

# -----------------------------------------------------
# CHECK DATA
# -----------------------------------------------------
if len(soc_list) < 2:
    print("No valid SoC samples found.")
    sys.exit(1)

df = pd.DataFrame({
    "ts": timestamps_ms,
    "SoC": soc_list,
    "BMS": bms_state_list,
    "hhmm": hhmm_list,
    "full_ts": full_ts_list
})


def detect_soc_stuck_odo(df, odo_events, min_km=3.0, max_soc_delta=1.0, max_odo_gap_ms=3000):
    if len(odo_events) < 2:
        return False, None, None

    odo_sorted = sorted(odo_events, key=lambda x: x[0])
    n = len(odo_sorted)

    j = 0
    for i in range(n):
        t_start, odo_start = odo_sorted[i]
        if j < i:
            j = i

        while j < n and (odo_sorted[j][1] - odo_start) < min_km:
            j += 1

        if j >= n:
            break

        t_end, odo_end = odo_sorted[j]

        has_large_gap = False
        for k in range(i, j):
            if (odo_sorted[k + 1][0] - odo_sorted[k][0]) > max_odo_gap_ms:
                has_large_gap = True
                break
        if has_large_gap:
            continue

        seg = df[(df["ts"] >= t_start) & (df["ts"] <= t_end)]
        if seg.empty:
            continue

        soc_start = seg["SoC"].iloc[0]
        soc_range = float(seg["SoC"].max() - seg["SoC"].min())

        if soc_range <= max_soc_delta:
            first_ts_full = seg["full_ts"].iloc[0]
            return True, round(soc_start, 2), first_ts_full

    return False, None, None


odo_soc_stuck, odo_stuck_first_soc, odo_stuck_first_ts = detect_soc_stuck_odo(df, odo_events)

# -----------------------------------------------------
# FIND VALID DELTAS  (CORRECT LOGIC)
# -----------------------------------------------------
valid = []

for i in range(1, len(df)):
    prev = df.iloc[i - 1]
    curr = df.iloc[i]

    dsoc = abs(curr.SoC - prev.SoC)
    dt_ms = curr.ts - prev.ts

    if dt_ms >= 3000:
        continue
    if curr.BMS == 0:
        continue

    valid.append((i, dsoc, dt_ms))

if not valid:
    print("No valid delta found!")
    sys.exit(1)

valid.sort(key=lambda x: x[1], reverse=True)

idx, delta, dt_ms = valid[0]
prev_soc = df.loc[idx - 1, "SoC"]
curr_soc = df.loc[idx, "SoC"]

# -----------------------------------------------------
# SUMMARY DATA
summary = {
    "Start_SoC": round(df["SoC"].iloc[0], 2),
    "Final_SoC": round(df["SoC"].iloc[-1], 2),
    "Max_Delta_SoC": round(delta, 2),
    "SoC_Transition": f"{round(prev_soc,2)} % to {round(curr_soc,2)} %",
    "Timestamp_of_Max_Delta": df.loc[idx, "full_ts"],
    "Delta_Time_ms": round(dt_ms, 2),
    "ODO_SoC_Stuck": bool(odo_soc_stuck),
    "ODO_Stuck_First_SoC": odo_stuck_first_soc,
    "ODO_Stuck_First_Timestamp": odo_stuck_first_ts,
}

# -----------------------------------------------------
# SAVE PASS/FAIL RESULT → SoC_results.json
# FAIL if:
#  - Max SoC jump > 0.1 %, OR
#  - ODO-based SoC stuck is detected.
# -----------------------------------------------------
result = "FAIL" if (summary["Max_Delta_SoC"] > 0.1 or odo_soc_stuck) else "PASS"

result_json_path = os.path.join(folder, "SoC_results.json")

with open(result_json_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "Result": result,
            "Max_SoC_Delta": summary["Max_Delta_SoC"],
            "ODO_SoC_Stuck": bool(odo_soc_stuck),
            "ODO_Stuck_First_SoC": odo_stuck_first_soc,
            "ODO_Stuck_First_Timestamp": odo_stuck_first_ts,
        },
        f,
        indent=4,
        ensure_ascii=False,
    )

print(f"SoC PASS/FAIL saved: {result_json_path}")

# -----------------------------------------------------
# ASCII SUMMARY → soc_summary.json
# -----------------------------------------------------
LEFT_WIDTH = 22
RIGHT_WIDTH = 42

def make_row(label, value):
    return f"| {label.ljust(LEFT_WIDTH)} | {value.ljust(RIGHT_WIDTH)} |"

border = "+" + "-"*(LEFT_WIDTH+2) + "+" + "-"*(RIGHT_WIDTH+2) + "+"

table_lines = [
    border,
    "| " + "SoC Summary".center(LEFT_WIDTH + RIGHT_WIDTH + 3) + " |",
    border,
    make_row("Start SoC (%)", f"{summary['Start_SoC']}%"),
    make_row("Final SoC (%)", f"{summary['Final_SoC']}%"),
    make_row(
        "Max SoC Delta (%)",
        f"{summary['Max_Delta_SoC']}%  (PASS threshold is 0.1%)",
    ),
    make_row("ODO SoC Stuck", "YES" if odo_soc_stuck else "NO"),
    make_row(
        "ODO First SoC (%)",
        f"{odo_stuck_first_soc}%" if odo_soc_stuck and odo_stuck_first_soc is not None else "",
    ),
    make_row("SoC Transition", summary["SoC_Transition"]),
    make_row("Delta Timestamp", summary["Timestamp_of_Max_Delta"]),
    border
]

json_summary_path = os.path.join(folder, "soc_summary.json")

with open(json_summary_path, "w", encoding="utf-8") as f:
    json.dump({"Summary_Table": table_lines}, f, indent=4, ensure_ascii=False)

print(f"ASCII Summary saved to JSON: {json_summary_path}")

# -----------------------------------------------------
# SOC PLOT
# -----------------------------------------------------
plt.figure(figsize=(12, 5))
plt.plot(df["ts"], df["SoC"], linewidth=2, label="SoC (%)")
plt.scatter(df.loc[idx, "ts"], df.loc[idx, "SoC"], s=90, c="red", zorder=5, label="Max SoC Jump")

plt.title("SoC vs Time")
plt.xlabel("Time")
plt.ylabel("SoC (%)")
plt.grid(True, linestyle="--", alpha=0.4)

def fmt_time(x, pos=None):
    dt = datetime.fromtimestamp(x / 1000.0)
    return dt.strftime("%H:%M:%S")

ax = plt.gca()
ax.xaxis.set_major_locator(ticker.LinearLocator(12))
ax.xaxis.set_major_formatter(ticker.FuncFormatter(fmt_time))
plt.xticks(rotation=40)

plt.legend()
plt.tight_layout()

plot_path = os.path.join(folder, "soc_plot.png")
plt.savefig(plot_path, dpi=200)
plt.close()

print(f"SoC plot saved: {plot_path}")
print("PROGRESS 100.0", flush=True)
print("\nDONE :)")
