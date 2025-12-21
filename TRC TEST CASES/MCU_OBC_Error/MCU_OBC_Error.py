import os
import sys
import json
import re
from datetime import datetime
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)
from trc_utils import fast_parse_ts, progress_by_bytes
PROGRESS_STEP = 0.5

# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

OUTPUT_ENCODING = "cp1252"

SOC_CAN_ID = 0x0109
MCU_CAP_CAN_ID = 0x0715

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


def find_last_event(events, ts_ms):
    best = None
    best_dt = None
    for item in events:
        dt = abs(item[0] - ts_ms)
        if best is None or dt < best_dt:
            best = item
            best_dt = dt
    return best

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
emit_progress = progress_by_bytes(trc_path, step=PROGRESS_STEP)

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

soc_events = []
cap_events = []

# -----------------------------------------------------
# Parse the TRC
# -----------------------------------------------------
with open(trc_path, "r", encoding="utf-8", errors="ignore") as trc:
    for line_idx, line in enumerate(trc, 1):
        emit_progress(len(line))
        m = pattern.match(line)
        if not m:
            continue

        date_str, time_str, ms_str = m.group(1), m.group(2), m.group(3)
        can_id = int(m.group(4), 16)
        dlc = int(m.group(5))
        data_bytes = m.group(6).strip().split()

        if len(data_bytes) < dlc:
            continue

        data = [int(b, 16) for b in data_bytes[:dlc]]
        dt, ts_ms, ts_str = fast_parse_ts(date_str, time_str, ms_str)

        if can_id == SOC_CAN_ID and dlc >= 5:
            raw_soc = data[0] | (data[1] << 8)
            soc = raw_soc * 0.01
            bms_state = data[4]

            vbat = None
            if dlc >= 8:
                raw_vbat = data[6] | (data[7] << 8)
                vbat = raw_vbat * 0.1  # scale 0.1 V

            soc_events.append((ts_ms, soc, bms_state, vbat))

        if can_id == MCU_CAP_CAN_ID and dlc >= 6:
            mcu_cap_volt = data[4]
            cap_events.append((ts_ms, mcu_cap_volt))

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
                        "Start_Timestamp": ts_str,
                        "End_Timestamp": ts_str,
                        "Active_Frames": 1,
                        "Start_ms": ts_ms,
                        "End_ms": ts_ms,
                    })
                else:
                    inst = st["instances"][-1]
                    inst["End_Timestamp"] = ts_str
                    inst["End_ms"] = ts_ms
                    inst["Active_Frames"] += 1

            st["last_active"] = is_active

soc_events.sort(key=lambda x: x[0])
cap_events.sort(key=lambda x: x[0])

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
        "Remark": "",
    }

    signals_result.append(entry)

# -----------------------------------------------------
# MCU UnderVolt SoC-based PASS/FAIL and remark
# -----------------------------------------------------
uv_state = error_states.get("MCU_UnderVolt", {"instances": []})
uv_instances = uv_state["instances"]
uv_any = len(uv_instances) > 0
uv_all_soc_below_2 = True if uv_any else False
uv_remark = ""

for inst in uv_instances:
    t_ms = inst.get("Start_ms")
    if t_ms is None:
        uv_all_soc_below_2 = False
        continue

    soc_ev = find_last_event(soc_events, t_ms)
    cap_ev = find_last_event(cap_events, t_ms)

    if soc_ev is None:
        uv_all_soc_below_2 = False
        continue

    # soc_ev: (ts_ms, soc_pct, bmss_state, vbat_V)
    _, soc_pct, bms_state, *rest = soc_ev
    vbat = rest[0] if rest else None

    # If BMSS == 3 at UV detection, treat as FAIL regardless of SoC.
    if int(bms_state) == 3:
        uv_all_soc_below_2 = False

    if soc_pct >= 2.0:
        uv_all_soc_below_2 = False

    if not uv_remark:
        cap_volt = cap_ev[1] if cap_ev is not None else None

        first_line = f"SoC={soc_pct:.2f}% (BMSS={int(bms_state)})"
        lines = [first_line]

        if cap_volt is not None:
            lines.append(f"MCU_CAP_Volt={cap_volt} V")
        if vbat is not None:
            lines.append(f"Vbat={vbat:.1f} V")

        uv_remark = "\n".join(lines)

for e in signals_result:
    if e["Name"] == "MCU_UnderVolt":
        e["Remark"] = uv_remark
        break

active_error_count = sum(1 for e in signals_result if e["Instance_Count"] > 0)
other_error_count = sum(
    1 for e in signals_result
    if e["Name"] != "MCU_UnderVolt" and e["Instance_Count"] > 0
)

if not uv_any:
    # No MCU_UnderVolt observed: PASS if no other errors.
    overall_result = "PASS" if other_error_count == 0 else "FAIL"
else:
    # MCU_UnderVolt present: PASS only if all UV events are at SoC < 2%,
    # BMSS != 3, and there are no other error flags.
    if uv_all_soc_below_2 and other_error_count == 0:
        overall_result = "PASS"
    else:
        overall_result = "FAIL"

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
    summary_lines.append(row("Remark", e.get("Remark", "")))
    summary_lines.append(border)

summary_path = os.path.join(folder, "MCU_OBC_Error_summary.json")
with open(summary_path, "w", encoding=OUTPUT_ENCODING) as out:
    json.dump({"Summary_Table": summary_lines}, out, indent=4, ensure_ascii=False)
print(f"Saved: {summary_path}")

# -----------------------------------------------------
# PNG TABLE
# -----------------------------------------------------
headers = ["ERROR Signal", "Status", "Instance", "Fail Timestamp(s)", "Remark"]
rows = []
line_heights = []

for e in signals_result:
    ts_lines = "\n".join(e["Fail_Timestamps"]) if e["Fail_Timestamps"] else ""
    remark = e.get("Remark", "")
    rows.append([e["Name"], e["Status"], e["Instance_Count"], ts_lines, remark])
    line_heights.append(max(get_line_count(ts_lines), get_line_count(remark)))

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
print("PROGRESS 100.0", flush=True)
print("MCU OBC Error Analysis DONE ✔")
