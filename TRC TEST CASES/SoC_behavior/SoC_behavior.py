import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import re
from datetime import datetime
import matplotlib.ticker as ticker
import json

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

# -----------------------------------------------------
# TRC regex
# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d+)\.\d+\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

SOC_ID = 0x0109

timestamps_ms = []
soc_list = []
bms_state_list = []
hhmm_list = []
full_ts_list = []

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
        ms_str = m.group(3)
        can_id = int(m.group(4), 16)
        dlc = int(m.group(5))
        data_str = m.group(6).strip()

        if can_id != SOC_ID:
            continue

        ts_str = f"{date_str} {time_str}.{ms_str}"
        dt = datetime.strptime(ts_str, "%d-%m-%Y %H:%M:%S.%f")
        ts_ms = dt.timestamp() * 1000.0

        bytes_hex = data_str.split()
        if len(bytes_hex) < dlc:
            continue

        data = [int(b, 16) for b in bytes_hex[:dlc]]

        raw_soc = (data[1] << 8) | data[0]
        soc = raw_soc * 0.01
        if soc < 1:
            continue

        bms_state = data[4]
        if bms_state == 0:
            continue

        timestamps_ms.append(ts_ms)
        soc_list.append(soc)
        bms_state_list.append(bms_state)
        hhmm_list.append(dt.strftime("%H:%M:%S"))
        full_ts_list.append(ts_str)

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

# -----------------------------------------------------
# FIND VALID DELTAS
# -----------------------------------------------------
valid = []
for i in range(1, len(df)):
    prev = df.iloc[i - 1]
    curr = df.iloc[i]

    dsoc = abs(curr.SoC - prev.SoC)
    dt_ms = curr.ts - prev.ts

    if dt_ms > 3000:
        continue
    if dsoc > 5:
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
# -----------------------------------------------------
summary = {
    "Start_SoC": round(df["SoC"].iloc[0], 2),
    "Final_SoC": round(df["SoC"].iloc[-1], 2),
    "Max_Delta_SoC": round(delta, 2),
    "SoC_Transition": f"{round(prev_soc,2)} % to {round(curr_soc,2)} %",
    "Timestamp_of_Max_Delta": df.loc[idx, "full_ts"],
    "Delta_Time_ms": round(dt_ms, 2)
}

# -----------------------------------------------------
# SAVE PASS/FAIL RESULT â†’ SoC_results.json
# -----------------------------------------------------
result = "FAIL" if summary["Max_Delta_SoC"] > 0.1 else "PASS"

result_json_path = os.path.join(folder, "SoC_results.json")

with open(result_json_path, "w", encoding="utf-8") as f:
    json.dump(
        {"Result": result, "Max_SoC_Delta": summary["Max_Delta_SoC"]},
        f, indent=4, ensure_ascii=False
    )

print(f"SoC PASS/FAIL saved: {result_json_path}")

# -----------------------------------------------------
# CLEAN, ALIGNED ASCII TABLE â†’ soc_summary.json
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
    make_row("Max SoC Delta (%)", f"{summary['Max_Delta_SoC']}%"),
    make_row("SoC Transition", summary["SoC_Transition"]),
    make_row("Delta Timestamp", summary["Timestamp_of_Max_Delta"]),
    border
]

json_summary_path = os.path.join(folder, "soc_summary.json")

with open(json_summary_path, "w", encoding="utf-8") as f:
    json.dump({"Summary_Table": table_lines}, f, indent=4, ensure_ascii=False)

print(f"ASCII Summary saved to JSON: {json_summary_path}")

# -----------------------------------------------------
# SOÃ‡ PLOT
# -----------------------------------------------------
plt.figure(figsize=(12, 5))
plt.plot(df["ts"], df["SoC"], linewidth=2, color="blue", label="SoC (%)")
plt.scatter(df.loc[idx, "ts"], df.loc[idx, "SoC"], s=70, color="red", label="Max SoC")

plt.title("SoC vs Time")
plt.xlabel("Time (HH:MM:SS)")
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
print("\nDONE :)")


