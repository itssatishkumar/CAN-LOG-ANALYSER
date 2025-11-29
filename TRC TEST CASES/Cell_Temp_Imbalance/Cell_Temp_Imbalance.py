import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import re
from datetime import datetime
import json

# -----------------------------------------------------
# CAN IDs and thermistor byte mapping (final)
# -----------------------------------------------------
THERM_CAN_MAP = {
    1: (0x0112, [0, 1, 2, 3, 4, 5]),              # Only 6 external NTCs
    2: (0x0130, list(range(8))),
    3: (0x0131, list(range(8))),
    4: (0x0132, list(range(8))),
    5: (0x0133, list(range(8))),
    6: (0x0134, list(range(8))),
    7: (0x0135, list(range(8))),
    8: (0x0136, list(range(8))),
    9: (0x0137, [0, 1]),                          # Only 2 external NTCs
    10: (0x014F, [0, 1, 2, 3])                    # 4 Master Pack NTCs
}

IMBALANCE_WARNING = 5.0   # °C
IMBALANCE_FAIL = 10.0     # °C
MAX_TIME_GAP_MS = 2000    # 2 seconds

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
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

timestamps = []
temps_list = []
full_ts_list = []
raw_first_10s = []

first_ts = None

# -----------------------------------------------------
# Additional CAN ID 0x014E parameters
# -----------------------------------------------------
reported_max = None
reported_min = None
reported_delta = None

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
        ms_norm = ms_str if len(ms_str) == 4 else ms_str + "0" if len(ms_str) == 3 else ms_str
        can_id   = int(m.group(4), 16)
        dlc      = int(m.group(5))
        data_str = m.group(6).strip()
        bytes_hex = data_str.split()

        if len(bytes_hex) < dlc:
            continue

        data = [int(b, 16) for b in bytes_hex[:dlc]]

        ts_string = f"{date_str} {time_str}.{ms_norm}"
        dt = datetime.strptime(ts_string, "%d-%m-%Y %H:%M:%S.%f")
        ts_ms = dt.timestamp() * 1000.0

        if first_ts is None:
            first_ts = ts_ms

        # -----------------------------------------------------
        # CAN ID 0x014E - Reported delta/min/max from BMS
        # -----------------------------------------------------
        if can_id == 0x014E and dlc >= 3:
            reported_max = data[0]
            reported_min = data[1]
            reported_delta = data[2]

        # -----------------------------------------------------
        # Temperature CAN frames
        # -----------------------------------------------------
        found = False
        for group_id, (msg_id, byte_idxs) in THERM_CAN_MAP.items():
            if can_id == msg_id:

                found = True
                temp_arr = [None] * 68     # 64 external + 4 master

                # Base index mapping
                if group_id == 10:
                    base = 64  # Master NTCs
                else:
                    base = (group_id - 1) * 8

                for i, bidx in enumerate(byte_idxs):
                    idx = base + i
                    if bidx < dlc and idx < 68:
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
# ACTIVE NTC DETECTION
# -----------------------------------------------------
active_ntc = set()
for arr in raw_first_10s:
    for i, v in enumerate(arr):
        if isinstance(v, int) and v > 0:
            active_ntc.add(i)

active_ntc = sorted(list(active_ntc))

if not active_ntc:
    print("ERROR: No active NTC detected in first 10 seconds!")
    sys.exit(1)

active_ntc_names = []
for idx in active_ntc:
    if idx < 64:
        active_ntc_names.append(f"ExtTherm_{idx+1}")
    else:
        active_ntc_names.append(f"Master_NTC_{idx-63}")

# -----------------------------------------------------
# BUILD DF
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

    if curr.ts - prev.ts >= MAX_TIME_GAP_MS:
        continue

    arr = curr.temps
    temps_valid = True
    active_vals = []

    # Zero streak rule
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

    if imbalance > max_imbalance_seen:
        max_imbalance_seen = imbalance
        max_imbalance_ts = curr.full_ts

    # Outlier detection
    median_val = sorted(active_vals)[len(active_vals)//2]
    deviations = [abs(v - median_val) for v in active_vals]
    max_dev_index = deviations.index(max(deviations))
    outlier_idx = active_ntc[max_dev_index]

    outlier_name = (
        f"ExtTherm_{outlier_idx+1}" if outlier_idx < 64
        else f"Master_NTC_{outlier_idx-63}"
    )

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
# OVERALL RESULT
# -----------------------------------------------------
overall_result = "FAIL" if fails else "PASS"

# -----------------------------------------------------
# RESULTS JSON
# -----------------------------------------------------
results_path = os.path.join(folder, "Cell_Temp_Imbalance_results.json")
OUTPUT_ENCODING = "cp1252"  # Match Windows default to avoid mojibake in viewers
with open(results_path, "w", encoding=OUTPUT_ENCODING) as f:
    json.dump({
        "Result": overall_result,
        "Active_NTC_Count": len(active_ntc),
        "Active_NTC_List": active_ntc_names,
        "Max_Imbalance_Observed": max_imbalance_seen,
        "Max_Imbalance_Timestamp": max_imbalance_ts,

        # Reported by CAN ID 0x014E
        "Reported_Ext_Temp_Delta": reported_delta,
        "Reported_Ext_Temp_Min": reported_min,
        "Reported_Ext_Temp_Max": reported_max,

        "Fails": fails,
        "Warnings": warnings

    }, f, indent=4, ensure_ascii=False)

print(f"Saved: {results_path}")

# -----------------------------------------------------
# SUMMARY JSON
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
    "| Cell Temp Imbalance Summary".center(LEFT + RIGHT + 5) + "|",
    border,
    row("Overall_Result", overall_result),
    row("Active_NTC_Count", f"{len(active_ntc)} ({active_list_str})"),
    row("Max_Imbalance_Observed", imb_str),

    # New CAN-reported fields
    row("Reported_Ext_Temp_Delta", f"{reported_delta} °C"),
    row("Reported_Ext_Temp_Min", f"{reported_min} °C"),
    row("Reported_Ext_Temp_Max", f"{reported_max} °C"),

    border
]

if fails:
    for f in fails:
        lines.append(row("Timestamp", f["Timestamp"]))
        lines.append(row("Outlier_NTC", f["Outlier_NTC"]))
        lines.append(row("Outlier_Temp", f"{f['Outlier_Temp']} °C"))
        lines.append(row("Imbalance", f"{f['Imbalance']} °C"))
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

summary_path = os.path.join(folder, "Cell_Temp_Imbalance_summary.json")
with open(summary_path, "w", encoding=OUTPUT_ENCODING) as f:
    json.dump({"Summary_Table": lines}, f, indent=4, ensure_ascii=False)

print(f"Saved: {summary_path}")

# -----------------------------------------------------
# SIMPLE TIMESERIES GRAPH
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

    if ntc_idx < 64:
        label = f"ExtTherm_{ntc_idx+1}"
    else:
        label = f"Master_NTC_{ntc_idx-63}"

    plt.plot(times, ntc_series[ntc_idx], label=label, linewidth=1.3)

# X axis formatting
time_labels = df["full_ts"].tolist()
if time_labels:
    step = max(1, len(time_labels) // 8)
    tick_idx = list(range(0, len(time_labels), step))
    if tick_idx[-1] != len(time_labels)-1:
        tick_idx.append(len(time_labels)-1)

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
plt.title("External + Master NTC Temperature Timeseries (Active NTCs)")
plt.grid(True, alpha=0.3)
plt.legend(loc="upper left", ncol=2, fontsize=9)

timeseries_path = os.path.join(folder, "Cell_Temp_Imbalance_plot.png")
plt.savefig(timeseries_path, dpi=200, bbox_inches="tight")
plt.close()

print(f"Saved: {timeseries_path}")
print("Cell Temperature Imbalance Analysis DONE :)")
