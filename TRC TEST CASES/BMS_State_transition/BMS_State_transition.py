import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import re
from datetime import datetime
import json

# -----------------------------------------------------
# CONFIG (YOUR BMS CONFIG)
# -----------------------------------------------------
BMS_STATE_ID = 0x0109               # CAN ID for BMS_State
BMS_STATE_BYTE_INDEX = 4            # 5th byte (0-based indexing)

STATE_NAMES = {
    0: "INIT",
    1: "READY",
    2: "PRECHARGE",
    3: "ACTIVE",
    4: "ERROR"
}

# Invalid transitions per your final table
INVALID_TRANSITIONS = {
    (0, 3),
    (1, 3),
    (3, 2),
    (4, 3)
}

# -----------------------------------------------------
# GET TRC FROM GUI
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
# TRC regex (same as precharge parser)
# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

timestamps = []
states = []
full_ts_list = []

# -----------------------------------------------------
# PARSE TRC — EXTRACT BMS_State
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

        if can_id != BMS_STATE_ID:
            continue
        if BMS_STATE_BYTE_INDEX >= dlc:
            continue

        bms_state = data[BMS_STATE_BYTE_INDEX]

        ts_str = f"{date_str} {time_str}.{ms_norm}"
        dt = datetime.strptime(ts_str, "%d-%m-%Y %H:%M:%S.%f")
        ts_ms = dt.timestamp() * 1000.0

        timestamps.append(ts_ms)
        states.append(bms_state)
        full_ts_list.append(ts_str)

# -----------------------------------------------------
# BUILD DATAFRAME
# -----------------------------------------------------
df = pd.DataFrame({
    "ts": timestamps,
    "state": states,
    "full_ts": full_ts_list
})

if df.empty:
    print("No BMS_State frames found! Check CAN ID / byte index.")
    sys.exit(1)

df = df.sort_values("ts").reset_index(drop=True)

# -----------------------------------------------------
# STATE NAME HELPER
# -----------------------------------------------------
def sname(v):
    return STATE_NAMES.get(v, f"STATE_{v}")

# -----------------------------------------------------
# DETECT TRANSITIONS
# -----------------------------------------------------
transitions = []
invalid_events = []

for i in range(1, len(df)):
    prev = df.iloc[i - 1]
    curr = df.iloc[i]

    prev_state = int(prev.state)
    curr_state = int(curr.state)

    # -----------------------------------------------------
    # NEW RULE: Ignore transitions if timestamp gap >= 2 seconds
    # -----------------------------------------------------
    delta_t = curr.ts - prev.ts
    if delta_t >= 2000:   # 2000 ms = 2 seconds
        continue

    # Ignore same state (self transitions)
    if prev_state == curr_state:
        continue

    is_invalid = (prev_state, curr_state) in INVALID_TRANSITIONS

    ev = {
        "Prev_State": prev_state,
        "Prev_State_Name": sname(prev_state),
        "New_State": curr_state,
        "New_State_Name": sname(curr_state),
        "Transition": f"{prev_state} -> {curr_state}",
        "Transition_Name": f"{sname(prev_state)} -> {sname(curr_state)}",
        "Full_Timestamp": curr.full_ts,
        "Timestamp_ms": curr.ts,
        "Valid": not is_invalid
    }

    transitions.append(ev)
    if is_invalid:
        invalid_events.append(ev)

overall_result = "PASS" if len(invalid_events) == 0 else "FAIL"

# -----------------------------------------------------
# SAVE JSON RESULTS
# -----------------------------------------------------
results_path = os.path.join(folder, "BMS_State_transition_results.json")
with open(results_path, "w", encoding="utf-8") as f:
    json.dump({
        "Result": overall_result,
        "Transitions": transitions,
        "Invalid_Transitions": invalid_events
    }, f, indent=4)

print(f"Saved results JSON: {results_path}")

# -----------------------------------------------------
# ASCII TABLE SUMMARY (JSON)
# -----------------------------------------------------
LEFT = 22
RIGHT = 42

def row(label, value):
    return f"| {label.ljust(LEFT)} | {value.ljust(RIGHT)} |"

border = "+" + "-"*(LEFT+2) + "+" + "-"*(RIGHT+2) + "+"

table_lines = [
    border,
    "| BMS State Transition Summary".center(LEFT + RIGHT + 5) + "|",
    border,
    row("Overall_Result", overall_result),
    border
]

if invalid_events:
    for e in invalid_events:
        table_lines.append(row("Transition", e["Transition_Name"]))
        table_lines.append(row("Numeric", e["Transition"]))
        table_lines.append(row("Full_Timestamp", e["Full_Timestamp"]))
        table_lines.append(row("Timestamp_ms", f"{e['Timestamp_ms']:.3f}"))
        table_lines.append(row("Valid", str(e["Valid"])))
        table_lines.append(border)
else:
    table_lines.append(row("Info", "No invalid transitions found"))
    table_lines.append(border)

summary_path = os.path.join(folder, "BMS_State_transition_summary.json")
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump({"Summary_Table": table_lines}, f, indent=4)

print(f"Saved summary JSON: {summary_path}")

# -----------------------------------------------------
# PNG PLOT
#   - If invalid transitions exist → plot invalid transitions
#   - If no invalid transitions → plot ALL transitions
# -----------------------------------------------------
if invalid_events:
    plot_list = invalid_events
    headers = [
        "Prev_State", "Prev_State_Name",
        "New_State", "New_State_Name",
        "Full_Timestamp", "Transition"
    ]
else:
    plot_list = transitions
    headers = [
        "Prev_State", "Prev_State_Name",
        "New_State", "New_State_Name",
        "Full_Timestamp", "Transition"
    ]

rows = []
for e in plot_list:
    rows.append([
        e["Prev_State"],
        e["Prev_State_Name"],
        e["New_State"],
        e["New_State_Name"],
        e["Full_Timestamp"],
        e["Transition_Name"]
    ])

# dynamic height
fig_height = 2 + 0.40 * len(rows)
fig_width = 16

fig, ax = plt.subplots(figsize=(fig_width, fig_height))
ax.axis("off")

tbl = ax.table(
    cellText=rows,
    colLabels=headers,
    loc="center",
    cellLoc="left"
)

tbl.auto_set_font_size(False)
tbl.set_fontsize(9)
tbl.scale(1.0, 1.2)

# Header coloring: red if invalids, blue otherwise
for (r, c), cell in tbl.get_celld().items():
    cell.set_edgecolor("black")
    if r == 0:
        cell.set_facecolor("#C0392B" if invalid_events else "#1F618D")
        cell.set_text_props(weight="bold", color="white")

png_path = os.path.join(folder, "BMS_State_transition_plot.png")
plt.savefig(png_path, dpi=220, bbox_inches="tight")
plt.close()

print(f"Saved PNG plot: {png_path}")
print("BMS State Transition Check DONE")
