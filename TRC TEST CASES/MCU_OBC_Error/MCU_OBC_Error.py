import os
import sys
import json
import re
from datetime import datetime
import matplotlib.pyplot as plt

# -----------------------------------------------------
# TRC regex (same as your existing BMS script)
# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

OUTPUT_ENCODING = "cp1252"  # JSON-compatible for Windows GUI

# -----------------------------------------------------
# ERROR SIGNAL MAP
# -----------------------------------------------------

ERROR_SIGNALS = {

    # ================================================================
    # MCU ERROR FRAME  (BO_ 1798)  CAN ID = 1798 decimal = 0x0706
    # ================================================================
    "MCU_SpeedLimit":      {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 7},
    "MCU_LowTemp":         {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 6},
    "MCU_UnderVolt":       {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 5},
    "MCU_OverVolt":        {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 4},
    "MCU_Motor_OverHeat":  {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 3},
    "MCU_Motor_OverLoad":  {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 2},
    "MCU_Motor_OverSpeed": {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 1},
    "MCU_Encoder_Fault":   {"can_id": 0x0706, "type": "bit", "byte": 3, "bit": 0},

    # ================================================================
    # OBC ERROR FRAME (BO_ ... ) CAN ID = 0x18FF50E5 (J1939 extended)
    # ================================================================
    "OBC_HW_FAIL":                       {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 0},
    "OBC_OVER_TEMP_PROTECTION":          {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 1},
    "OBC_AC_OVERVOLT_PROTECTION":        {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 2},
    "OBC_BATTERY_REVERSE_PROTECTION":    {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 3},
    "OBC_COMMUNICATION_TIMEOUT_FAILURE": {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 4},
    "OBC_VCC_OUTPUT_FAILURE":            {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 5},
    "OBC_FAN_FAULT":                     {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 6},
    "OBC_TOO_HIGH_BATT_VOLTAGE":         {"can_id": 0x18FF50E5, "type": "bit", "byte": 4, "bit": 7},
}

INTERESTING_CAN_IDS = set(v["can_id"] for v in ERROR_SIGNALS.values())

# Display order (MCU then OBC)
DISPLAY_ORDER = list(ERROR_SIGNALS.keys())

# -----------------------------------------------------
# Helpers
# -----------------------------------------------------
def get_signal_value(defn, data, dlc):
    b = defn["byte"]
    if b >= dlc:
        return 0
    if defn["type"] == "bit":
        return (data[b] >> defn["bit"]) & 0x01
    else:
        return data[b]

def get_line_count(text):
    return text.count("\n") + 1 if text else 1

# -----------------------------------------------------
# Load TRC input
# -----------------------------------------------------
if len(sys.argv) < 2:
    print("ERROR: No TRC file provided!")
    sys.exit(1)

trc_path = sys.argv[1]
if not os.path.exists(trc_path):
    print(f"ERROR: File not found: {trc_path}")
    sys.exit(1)

folder = os.path.dirname(os.path.abspath(__file__))
print(f"Using TRC file: {trc_path}")

# -----------------------------------------------------
# State Machine for all MCU/OBC error signals
# -----------------------------------------------------
error_states = {}
for name in ERROR_SIGNALS:
    error_states[name] = {
        "last_active": False,
        "instances": [],
        "last_value": 0,
        "last_nonzero": None,
    }

# -----------------------------------------------------
# Parse the TRC
# -----------------------------------------------------
with open(trc_path, "r", encoding="utf-8", errors="ignore") as trc:
    for line in trc:
        m = pattern.match(line)
        if not m:
            continue

        date_str, time_str, ms_str = m.group(1), m.group(2), m.group(3)
        ms_norm = ms_str if len(ms_str) == 4 else ms_str + "0"
        can_id = int(m.group(4), 16)
        dlc = int(m.group(5))
        data_bytes = m.group(6).strip().split()

        if len(data_bytes) < dlc:
            continue

        data = [int(b, 16) for b in data_bytes[:dlc]]
        ts = f"{date_str} {time_str}.{ms_norm}"

        if can_id not in INTERESTING_CAN_IDS:
            continue

        for name, defn in ERROR_SIGNALS.items():
            if defn["can_id"] != can_id:
                continue

            val = get_signal_value(defn, data, dlc)
            st = error_states[name]

            st["last_value"] = val
            is_active = (val == 1) if defn["type"] == "bit" else (val > 0)

            if is_active:
                if not st["last_active"]:
                    st["instances"].append({
                        "Start_Timestamp": ts,
                        "End_Timestamp": ts,
                        "Active_Frames": 1
                    })
                else:
                    inst = st["instances"][-1]
                    inst["End_Timestamp"] = ts
                    inst["Active_Frames"] += 1

            st["last_active"] = is_active

# -----------------------------------------------------
# Build Results Structure
# -----------------------------------------------------
signals_result = []
for name in DISPLAY_ORDER:
    st = error_states[name]
    instances = st["instances"]
    status = "YES" if len(instances) > 0 else "NO"

    entry = {
        "Name": name,
        "Status": status,
        "Instance_Count": len(instances),
        "Instances": instances,
        "Fail_Timestamps": [inst["Start_Timestamp"] for inst in instances],
        "Last_Nonzero_Value": st["last_nonzero"],
        "Value": st["last_nonzero"] if st["last_nonzero"] else "",
    }

    signals_result.append(entry)

active_error_count = sum(1 for e in signals_result if e["Instance_Count"] > 0)
overall_result = "FAIL" if active_error_count > 0 else "PASS"

# -----------------------------------------------------
# SAVE RESULTS JSON
# -----------------------------------------------------
results_path = os.path.join(folder, "MCU_OBC_Error_results.json")
with open(results_path, "w", encoding=OUTPUT_ENCODING) as out:
    json.dump({
        "Result": overall_result,
        "Active_Error_Count": active_error_count,
        "Signals": signals_result
    }, out, indent=4, ensure_ascii=False)
print(f"Saved: {results_path}")

# -----------------------------------------------------
# SAVE SUMMARY JSON
# -----------------------------------------------------
LEFT = 22
RIGHT = 42

def row(label, value):
    return f"| {label.ljust(LEFT)} | {str(value).ljust(RIGHT)} |"

border = "+" + "-"*(LEFT+2) + "+" + "-"*(RIGHT+2) + "+"

summary_lines = [
    border,
    "| MCU OBC Error Summary".center(LEFT + RIGHT + 5) + "|",
    border,
    row("Overall_Result", overall_result),
    row("Active_Error_Count", active_error_count),
    border
]

for e in signals_result:
    summary_lines.append(row("ERROR Signal", e["Name"]))
    summary_lines.append(row("Status", e["Status"]))
    summary_lines.append(row("Instance", e["Instance_Count"]))
    summary_lines.append(row("Fail Timestamp(s)", "; ".join(e["Fail_Timestamps"])))
    summary_lines.append(row("Value", e["Value"] or ""))
    summary_lines.append(border)

summary_path = os.path.join(folder, "MCU_OBC_Error_summary.json")
with open(summary_path, "w", encoding=OUTPUT_ENCODING) as out:
    json.dump({"Summary_Table": summary_lines}, out, indent=4, ensure_ascii=False)
print(f"Saved: {summary_path}")

# -----------------------------------------------------
# PNG TABLE
# -----------------------------------------------------
headers = ["ERROR Signal", "Status", "Instance", "Fail Timestamp(s)", "Value"]
rows = []
line_heights = []

for e in signals_result:
    ts_lines = "\n".join(e["Fail_Timestamps"]) if e["Fail_Timestamps"] else ""
    val = e["Value"] if e["Value"] else ""
    rows.append([e["Name"], e["Status"], e["Instance_Count"], ts_lines, val])
    line_heights.append(max(get_line_count(ts_lines), get_line_count(val)))

fig_width = 16
fig_height = 2 + sum(0.35 * h for h in line_heights)

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
tbl.scale(1, 1.2)

# Color + formatting
for (r, c), cell in tbl.get_celld().items():
    cell.set_edgecolor("black")
    if r == 0:
        cell.set_facecolor("#1FA37A")
        cell.set_text_props(weight="bold", color="white")

base_h = tbl[1, 0].get_height() if rows else 0.3

for i, h in enumerate(line_heights):
    row_idx = i + 1
    for c in range(len(headers)):
        tbl[row_idx, c].set_height(base_h * h)
        if rows[i][1] == "YES":
            tbl[row_idx, c].set_facecolor("#FFCCCC")

png_path = os.path.join(folder, "MCU_OBC_Error_plot.png")
plt.savefig(png_path, dpi=220, bbox_inches="tight")
plt.close()

print(f"Saved: {png_path}")
print("MCU OBC Error Analysis DONE ✔")
