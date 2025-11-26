import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import re
from datetime import datetime
import json

# -----------------------------------------------------
# CAN IDs and internal thermistor byte mapping
# -----------------------------------------------------
# BO_ 301 IntTherm_Group_1 -> 0x012D
# BO_ 320 IntTherm_Group_2 -> 0x0140
THERM_CAN_MAP = {
    1: (0x012D, list(range(8))),   # IntTherm_1 .. IntTherm_8
    2: (0x0140, list(range(8)))    # IntTherm_9 .. IntTherm_16
}

IMBALANCE_WARNING = 5.0   # °C
IMBALANCE_FAIL = 10.0     # °C
MAX_TIME_GAP_MS = 2000    # 2 seconds

OUTPUT_ENCODING = "cp1252"  # for JSON files (Windows-friendly)

# -----------------------------------------------------
# GET TRC FILE
# -----------------------------------------------------
if len(sys.argv) < 2:
    print("ERROR: No TRC file passed from GUI!")
    sys.exit(1)

trc_path = sys.argv[1]
if not os.path.exists(trc_path):
    print(f"ERROR: TRC file not found: {trc_path}")
    sys.exit(1)

folder = os.path.dirname(os.path.abspath(__file__))
print(f"Using TRC file: {trc_path}")

# -----------------------------------------------------
# TRC REGEX
# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d+)\.\d+\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

timestamps = []
temps_list = []
full_ts_list = []
raw_first_10s = []

first_ts = None

# -----------------------------------------------------
# CAN ID 0x014E internal temperature delta/min/max
# -----------------------------------------------------
# BO_ 334 NTC_Delta: 6
#  SG_ Int_Temp_Delta : 40|8@1- -> byte 5
#  SG_ Int_Temp_Min   : 32|8@1- -> byte 4
#  SG_ Int_Temp_Max   : 24|8@1- -> byte 3
reported_int_max = None
reported_int_min = None
reported_int_delta = None

# -----------------------------------------------------
# PARSE TRC
# -----------------------------------------------------
with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:

        m = pattern.match(line)
        if not m:
            continue

        date_str = m.group(1)
        time_str = m.group(2)
        ms_str   = m.group(3)
        can_id   = int(m.group(4), 16)
        dlc      = int(m.group(5))
        data_str = m.group(6).strip()
        bytes_hex = data_str.split()

        if len(bytes_hex) < dlc:
            continue

        data = [int(b, 16) for b in bytes_hex[:dlc]]

        ts_string = f"{date_str} {time_str}.{ms_str}"
        dt = datetime.strptime(ts_string, "%d-%m-%Y %H:%M:%S.%f")
        ts_ms = dt.timestamp() * 1000.0

        if first_ts is None:
            first_ts = ts_ms

        # -----------------------------------------------------
        # CAN ID 0x014E - Internal temp Delta / Min / Max
        # -----------------------------------------------------
        if can_id == 0x014E and dlc >= 6:
            reported_int_max = data[3]   # Int_Temp_Max
            reported_int_min = data[4]   # Int_Temp_Min
            reported_int_delta = data[5] # Int_Temp_Delta

        # -----------------------------------------------------
        # Temperature CAN frames (internal thermistors)
        # -----------------------------------------------------
        found = False
        for group_id, (msg_id, byte_idxs) in THERM_CAN_MAP.items():
            if can_id == msg_id:

                found = True
                # 16 internal thermistors total
                temp_arr = [None] * 16

                base = (group_id - 1) * 8  # 0 for group 1, 8 for group 2

                for i, bidx in enumerate(byte_idxs):
                    idx = base + i
                    if bidx < dlc and idx < 16:
                        temp_arr[idx] = data[bidx]

                break

        if not found:
            continue

        timestamps.append(ts_ms)
        temps_list.append(temp_arr)
        full_ts_list.append(ts_string)

        if ts_ms - first_ts <= 10000:
            raw_first_10s.append(temp_arr)

# -----------------------------------------------------
# ACTIVE INT THERM DETECTION (first 10s)
# -----------------------------------------------------
active_ntc = set()
for arr in raw_first_10s:
    for i, v in enumerate(arr):
        if isinstance(v, int) and v > 0:
            active_ntc.add(i)

active_ntc = sorted(list(active_ntc))

if not active_ntc:
    print("ERROR: No active internal NTC detected in first 10 seconds!")
    sys.exit(1)

active_ntc_names = [f"IntTherm_{idx+1}" for idx in active_ntc]

# -----------------------------------------------------
# BUILD DATAFRAME
# -----------------------------------------------------
df = pd.DataFrame({
    "ts": timestamps,
    "temps": temps_list,
    "full_ts": full_ts_list
}).sort_values("ts").reset_index(drop=True)

# -----------------------------------------------------
# MAIN IMBALANCE ANALYSIS
# -----------------------------------------------------
fails = []
warnings = []

zero_streak = {ntc: 0 for ntc in active_ntc}

max_imbalance_seen = 0.0
max_imbalance_ts = "-"

for i in range(1, len(df)):

    prev = df.iloc[i - 1]
    curr = df.iloc[i]

    # ignore big time gaps
    if curr.ts - prev.ts >= MAX_TIME_GAP_MS:
        continue

    arr = curr.temps
    temps_valid = True
    active_vals = []

    # Zero-streak rule for internal thermistors
    for ntc_idx in active_ntc:
        val = arr[ntc_idx]
        if val is None:
            continue

        if val == 0:
            zero_streak[ntc_idx] += 1
            if zero_streak[ntc_idx] < 3:
                temps_valid = False
        else:
            zero_streak[ntc_idx] = 0

        active_vals.append(val)

    if not temps_valid or not active_vals:
        continue

    tmax = max(active_vals)
    tmin = min(active_vals)
    imbalance = tmax - tmin

    # Track max imbalance
    if imbalance > max_imbalance_seen:
        max_imbalance_seen = imbalance
        max_imbalance_ts = curr.full_ts

    # Outlier detection (internal therm)
    median_val = sorted(active_vals)[len(active_vals)//2]
    deviations = [abs(v - median_val) for v in active_vals]
    max_dev_index = deviations.index(max(deviations))
    outlier_idx = active_ntc[max_dev_index]

    outlier_name = f"IntTherm_{outlier_idx+1}"

    if imbalance > IMBALANCE_FAIL:
        fails.append({
            "Timestamp": curr.full_ts,
            "Outlier_NTC": outlier_name,
            "Outlier_Temp": active_vals[max_dev_index],
            "Imbalance": round(imbalance, 3)
        })
    elif imbalance > IMBALANCE_WARNING:
        warnings.append({
            "Timestamp": curr.full_ts,
            "Imbalance": round(imbalance, 3)
        })

# -----------------------------------------------------
# OVERALL RESULT (WARNING treated as PASS)
# -----------------------------------------------------
overall_result = "FAIL" if fails else "PASS"

# -----------------------------------------------------
# RESULTS JSON (BMS_PCB_Temp_results.json)
# -----------------------------------------------------
results_path = os.path.join(folder, "BMS_PCB_Temp_results.json")
with open(results_path, "w", encoding=OUTPUT_ENCODING) as f:
    json.dump({
        "Result": overall_result,
        "Active_NTC_Count": len(active_ntc),
        "Active_NTC_List": active_ntc_names,
        "Max_Imbalance_Observed": round(max_imbalance_seen, 3),
        "Max_Imbalance_Timestamp": max_imbalance_ts,

        # Reported by CAN ID 0x014E
        "Reported_Int_Temp_Delta": reported_int_delta,
        "Reported_Int_Temp_Min": reported_int_min,
        "Reported_Int_Temp_Max": reported_int_max,

        "Fails": fails,
        "Warnings": warnings

    }, f, indent=4, ensure_ascii=False)

print(f"Saved: {results_path}")

# -----------------------------------------------------
# SUMMARY JSON (BMS_PCB_Temp_summary.json)
# -----------------------------------------------------
LEFT = 22
RIGHT = 42

def row(l, v):
    return f"| {l.ljust(LEFT)} | {str(v).ljust(RIGHT)} |"

border = "+" + "-"*(LEFT+2) + "+" + "-"*(RIGHT+2) + "+"

imb_str = f"{round(max_imbalance_seen,3)} °C ({max_imbalance_ts})"
active_list_str = ", ".join(active_ntc_names)

lines = [
    border,
    "| PCB Internal Temp Imbalance Summary".center(LEFT + RIGHT + 5) + "|",
    border,
    row("Overall_Result", overall_result),
    row("Active_NTC_Count", f"{len(active_ntc)} ({active_list_str})"),
    row("Max_Imbalance_Observed", imb_str),
    row("Reported_Int_Temp_Delta", f"{reported_int_delta} °C"),
    row("Reported_Int_Temp_Min", f"{reported_int_min} °C"),
    row("Reported_Int_Temp_Max", f"{reported_int_max} °C"),
    border
]

if fails:
    for fobj in fails:
        lines.append(row("Timestamp", fobj["Timestamp"]))
        lines.append(row("Outlier_NTC", fobj["Outlier_NTC"]))
        lines.append(row("Outlier_Temp", f"{fobj['Outlier_Temp']} °C"))
        lines.append(row("Imbalance", f"{fobj['Imbalance']} °C"))
        lines.append(row("Status", "FAIL"))
        lines.append(border)
elif warnings:
    for w in warnings:
        lines.append(row("Timestamp", w["Timestamp"]))
        lines.append(row("Imbalance", f"{w['Imbalance']} °C"))
        lines.append(row("Status", "WARNING"))
        lines.append(border)
else:
    lines.append(row("Info", "No warnings or failures"))
    lines.append(border)

summary_path = os.path.join(folder, "BMS_PCB_Temp_summary.json")
with open(summary_path, "w", encoding=OUTPUT_ENCODING) as f:
    json.dump({"Summary_Table": lines}, f, indent=4, ensure_ascii=False)

print(f"Saved: {summary_path}")

# -----------------------------------------------------
# TIMESERIES GRAPH (BMS_PCB_Temp_plot.png)
# -----------------------------------------------------
times = [ts/1000.0 for ts in df["ts"]]
ntc_series = {ntc: [] for ntc in active_ntc}
plot_zero_streak = {ntc: 0 for ntc in active_ntc}

for arr in df["temps"]:
    for ntc_idx in active_ntc:
        val = arr[ntc_idx]

        if not isinstance(val, int):
            plot_value = None
        elif val == 0:
            plot_zero_streak[ntc_idx] += 1
            plot_value = 0 if plot_zero_streak[ntc_idx] >= 3 else None
        else:
            plot_zero_streak[ntc_idx] = 0
            plot_value = val

        ntc_series[ntc_idx].append(plot_value)

plt.figure(figsize=(18, 8))

for ntc_idx in active_ntc:
    label = f"IntTherm_{ntc_idx+1}"
    plt.plot(times, ntc_series[ntc_idx], label=label, linewidth=1.3)

# X-axis formatting with HH:MM:SS from full_ts
time_labels = df["full_ts"].tolist()
if time_labels:
    step = max(1, len(time_labels) // 8)
    tick_idx = list(range(0, len(time_labels), step))
    if tick_idx[-1] != len(time_labels) - 1:
        tick_idx.append(len(time_labels) - 1)

    fmt_labels = []
    for lbl in time_labels:
        try:
            dt_obj = datetime.strptime(lbl, "%d-%m-%Y %H:%M:%S.%f")
            fmt_labels.append(dt_obj.strftime("%H:%M:%S"))
        except:
            fmt_labels.append(lbl)

    plt.xticks(
        [times[i] for i in tick_idx],
        [fmt_labels[i] for i in tick_idx],
        rotation=25,
        ha="right",
        fontsize=8
    )

plt.xlabel("Timestamp")
plt.ylabel("Temperature (°C)")
plt.title("Internal PCB Temperature Timeseries (Active IntTherm)")
plt.grid(True, alpha=0.3)
plt.legend(loc="upper left", ncol=2, fontsize=9)

plot_path = os.path.join(folder, "BMS_PCB_Temp_plot.png")
plt.savefig(plot_path, dpi=200, bbox_inches="tight")
plt.close()

print(f"Saved: {plot_path}")
print("PCB Internal Temperature Imbalance Analysis DONE :)")
