

import os
import sys
import json
import re
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

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

OUTPUT_ENCODING = "utf-8"

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

# --- TRC file selection logic ---
trc_path = None
if len(sys.argv) >= 2:
    trc_path = sys.argv[1]
    if not os.path.exists(trc_path):
        print(f"ERROR: File not found: {trc_path}")
        trc_path = None

if trc_path is None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        trc_path = filedialog.askopenfilename(
            title="Select TRC file",
            filetypes=[("TRC files", "*.trc"), ("All files", "*.*")]
        )
        root.destroy()
    except Exception as e:
        print("ERROR: No TRC file provided and failed to open file dialog.")
        print(f"Details: {e}")
        sys.exit(1)

if not trc_path:
    print("ERROR: No TRC file provided!")
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
# Helper for BMS state before/after (must be above all uses)
def get_bms_state_before_after(events, t_ms):
    before = None
    after = None
    for i, ev in enumerate(events):
        if ev[0] < t_ms:
            before = ev
        elif ev[0] > t_ms:
            after = ev
            break
    return before, after

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


# -----------------------------------------------------
# MCU LowTemp remark table generation (like UnderVolt)
# -----------------------------------------------------
lt_state = error_states.get("MCU_LowTemp", {"instances": []})
lt_instances = lt_state["instances"]
TEMP_CAN_ID = 0x0705
temp_events = []
with open(trc_path, "r", encoding="utf-8", errors="ignore") as trc:
    for line_idx, line in enumerate(trc, 1):
        m = pattern.match(line)
        if not m:
            continue
        can_id = int(m.group(4), 16)
        dlc = int(m.group(5))
        data_bytes = m.group(6).strip().split()
        if can_id == TEMP_CAN_ID and dlc >= 1 and len(data_bytes) >= 1:
            data = [int(b, 16) for b in data_bytes[:dlc]]
            temp_raw = data[0]
            temp = temp_raw - 256 if temp_raw > 127 else temp_raw
            date_str, time_str, ms_str = m.group(1), m.group(2), m.group(3)
            _, ts_ms, _ = fast_parse_ts(date_str, time_str, ms_str)
            temp_events.append((ts_ms, temp))

if len(lt_instances) > 0 and len(temp_events) > 0:
    def get_temp_window(ts_ms, temp_events, window=5):
        idx = None
        for i, (t, _) in enumerate(temp_events):
            if t >= ts_ms:
                idx = i
                break
        if idx is None:
            idx = len(temp_events)
        start = max(0, idx - window)
        end = min(len(temp_events), idx + window + 1)
        window_vals = [v for _, v in temp_events[start:end]]
        return min(window_vals) if window_vals else ""

    table_header = ["No.", "SoC", "BMSS", "Vmcu", "Vbat", "Temp(-38°C)"]
    table_rows = []
    for idx, inst in enumerate(lt_instances, 1):
        t_ms = inst.get("Start_ms")
        if t_ms is None:
            soc_pct = bms_state = cap_volt = vbat = temp_val = None
            bms_transition = "N/A"
        else:
            before_ev, after_ev = get_bms_state_before_after(soc_events, t_ms)
            cap_ev = find_last_event(cap_events, t_ms)
            soc_ev = find_last_event(soc_events, t_ms)
            _, soc_pct, bms_state, *rest = soc_ev if soc_ev else (None, None, None, None)
            vbat = rest[0] if rest else None
            before_bms = int(before_ev[2]) if before_ev else None
            after_bms = int(after_ev[2]) if after_ev else None
            bms_transition = f"{before_bms}->{after_bms}" if before_bms is not None and after_bms is not None else "N/A"
            cap_volt = cap_ev[1] if cap_ev is not None else None
            temp_val = get_temp_window(t_ms, temp_events)

        table_rows.append([
            str(idx),
            f"{soc_pct:.2f}" if soc_pct is not None else "",
            bms_transition,
            f"{cap_volt}" if cap_volt is not None else "",
            f"{vbat:.1f}" if vbat is not None else "",
            f"{temp_val}" if temp_val != "" else ""
        ])

    col_widths = [max(len(str(row[i])) for row in ([table_header] + table_rows)) for i in range(len(table_header))]
    col_widths[0] = max(2, col_widths[0] // 2)
    def fmt_row(row):
        return " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
    sep_line = "-+-".join("-" * w for w in col_widths)
    table_str = fmt_row(table_header) + "\n" + sep_line + "\n" + "\n".join(fmt_row(row) for row in table_rows)
    lt_remark = table_str

    for e in signals_result:
        if e["Name"] == "MCU_LowTemp":
            e["Remark"] = lt_remark
            break



# Helper for BMS state before/after (must be above first use)




# Build table for all MCU_UnderVolt instances, now with Vmin
if uv_any:
    VMIN_CAN_ID = 0x012C
    vmin_events = []
    # Parse Vmin from TRC file (already parsed above, so let's do it here for all lines)
    with open(trc_path, "r", encoding="utf-8", errors="ignore") as trc:
        for line_idx, line in enumerate(trc, 1):
            m = pattern.match(line)
            if not m:
                continue
            can_id = int(m.group(4), 16)
            dlc = int(m.group(5))
            data_bytes = m.group(6).strip().split()
            if can_id == VMIN_CAN_ID and dlc >= 4 and len(data_bytes) >= 4:
                data = [int(b, 16) for b in data_bytes[:dlc]]
                # Voltage_Min : 16|16@1+ (0.1,0) [0|0] "mV" => bytes 2,3 (index 2,3), little endian
                vmin_raw = data[2] | (data[3] << 8)
                vmin = vmin_raw * 0.1  # mV to V
                # Timestamp
                date_str, time_str, ms_str = m.group(1), m.group(2), m.group(3)
                _, ts_ms, _ = fast_parse_ts(date_str, time_str, ms_str)
                vmin_events.append((ts_ms, vmin))

    def get_vmin_window(ts_ms, vmin_events, window=5):
        # Find index of closest event
        idx = None
        for i, (t, _) in enumerate(vmin_events):
            if t >= ts_ms:
                idx = i
                break
        if idx is None:
            idx = len(vmin_events)
        # Get 5 before, 1 at, 5 after
        start = max(0, idx - 5)
        end = min(len(vmin_events), idx + 6)
        window_vals = [v for _, v in vmin_events[start:end]]
        return min(window_vals) if window_vals else ""

    table_header = ["No.", "SoC", "BMSS", "Vmcu", "Vbat", "Vmin"]
    table_rows = []
    for idx, inst in enumerate(uv_instances, 1):
        t_ms = inst.get("Start_ms")
        if t_ms is None:
            soc_pct = bms_state = cap_volt = vbat = vmin_val = None
            bms_transition = "N/A"
        else:
            before_ev, after_ev = get_bms_state_before_after(soc_events, t_ms)
            cap_ev = find_last_event(cap_events, t_ms)
            soc_ev = find_last_event(soc_events, t_ms)
            _, soc_pct, bms_state, *rest = soc_ev if soc_ev else (None, None, None, None)
            vbat = rest[0] if rest else None
            before_bms = int(before_ev[2]) if before_ev else None
            after_bms = int(after_ev[2]) if after_ev else None
            bms_transition = f"{before_bms}->{after_bms}" if before_bms is not None and after_bms is not None else "N/A"

            # Only FAIL if both before and after BMS state are 3
            if before_bms == 3 and after_bms == 3:
                uv_all_soc_below_2 = False
            if soc_pct is not None and soc_pct >= 2.0:
                uv_all_soc_below_2 = False
            cap_volt = cap_ev[1] if cap_ev is not None else None
            vmin_val = get_vmin_window(t_ms, vmin_events)

        table_rows.append([
            str(idx),
            f"{soc_pct:.2f}" if soc_pct is not None else "",
            bms_transition,
            f"{cap_volt}" if cap_volt is not None else "",
            f"{vbat:.1f}" if vbat is not None else "",
            f"{vmin_val:.2f}" if isinstance(vmin_val, float) else ""
        ])

    # Format as a markdown-like table for the remark
    col_widths = [max(len(str(row[i])) for row in ([table_header] + table_rows)) for i in range(len(table_header))]
    col_widths[0] = max(2, col_widths[0] // 2)
    def fmt_row(row):
        return " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
    sep_line = "-+-".join("-" * w for w in col_widths)
    table_str = fmt_row(table_header) + "\n" + sep_line + "\n" + "\n".join(fmt_row(row) for row in table_rows)
    uv_remark = table_str

for e in signals_result:
    if e["Name"] == "MCU_UnderVolt":
        e["Remark"] = uv_remark
        break


def build_mcu_remark(t_ms):
    if t_ms is None:
        return ""
    soc_ev = find_last_event(soc_events, t_ms)
    cap_ev = find_last_event(cap_events, t_ms)
    if soc_ev is None:
        return ""

    _, soc_pct, bms_state, *rest = soc_ev
    vbat = rest[0] if rest else None
    cap_volt = cap_ev[1] if cap_ev is not None else None

    lines = [f"SoC={soc_pct:.2f}% (BMSS={int(bms_state)})"]
    if cap_volt is not None:
        lines.append(f"MCU_CAP_Volt={cap_volt} V")
    if vbat is not None:
        lines.append(f"Vbat={vbat:.1f} V")
    return "\n".join(lines)


for e in signals_result:
    if not e["Name"].startswith("MCU_"):
        continue
    if e["Name"] in ("MCU_LowTemp", "MCU_UnderVolt"):
        continue
    if e.get("Remark"):
        continue
    if e.get("Instance_Count", 0) <= 0:
        continue
    first_inst = e["Instances"][0] if e.get("Instances") else None
    t_ms = first_inst.get("Start_ms") if isinstance(first_inst, dict) else None
    e["Remark"] = build_mcu_remark(t_ms)

# -----------------------------------------------------
# OBC error severity (WARNING / FAIL based on BMSS)
# -----------------------------------------------------
obc_warning = False
obc_fail = False

for name, st in error_states.items():
    if not name.startswith("OBC_"):
        continue
    for inst in st["instances"]:
        t_ms = inst.get("Start_ms")
        if t_ms is None:
            continue
        soc_ev = find_last_event(soc_events, t_ms)
        if soc_ev is None:
            # No BMSS info: treat as warning rather than hard fail
            obc_warning = True
            continue
        _, _soc, bms_state, _vbat = soc_ev
        if int(bms_state) == 3:
            obc_fail = True
        else:
            obc_warning = True

# For each OBC flag, add remark with first instance SoC and BMS State
for e in signals_result:
    if not e["Name"].startswith("OBC_"):
        continue
    if e["Instance_Count"] <= 0 or e.get("Remark"):
        continue

    first_inst = e["Instances"][0]
    t_ms = first_inst.get("Start_ms")
    if t_ms is None:
        continue
    soc_ev = find_last_event(soc_events, t_ms)
    if soc_ev is None:
        continue
    _, soc_pct, bms_state, _vbat = soc_ev
    e["Remark"] = f"SoC={soc_pct:.2f}%\nBMS State={int(bms_state)}"

active_error_count = sum(1 for e in signals_result if e["Instance_Count"] > 0)
other_mcu_error_count = sum(
    1 for e in signals_result
    if e["Name"].startswith("MCU_") and e["Name"] != "MCU_UnderVolt" and e["Instance_Count"] > 0
)

# Determine overall result with PASS / WARNING / FAIL
if other_mcu_error_count > 0 or obc_fail or (uv_any and not uv_all_soc_below_2):
    overall_result = "FAIL"
else:
    if obc_warning:
        overall_result = "WARNING"
    else:
        overall_result = "PASS"

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


# Adjust column widths: shrink 'Instance' by half, add to 'Remark'
if rows:
    base_w_error = tbl[0, 0].get_width()
    base_w_status = tbl[0, 1].get_width()
    base_w_instance = tbl[0, 2].get_width()
    base_w_failts = tbl[0, 3].get_width()
    base_w_remark = tbl[0, 4].get_width()
    for r in range(len(rows) + 1):  # +1 for header row
        tbl[r, 0].set_width(base_w_error * 1.5)
        tbl[r, 1].set_width(base_w_status * 0.5)
        tbl[r, 2].set_width(base_w_instance * 0.5)
        tbl[r, 3].set_width(base_w_failts)
        tbl[r, 4].set_width(base_w_remark + base_w_instance * 0.5)

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
