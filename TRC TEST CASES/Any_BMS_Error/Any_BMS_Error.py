import os
import sys
import json
import re
from datetime import datetime
import matplotlib.pyplot as plt

# -----------------------------------------------------
# TRC regex (same style as other scripts)
# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

OUTPUT_ENCODING = "cp1252"  # for JSON (Windows-friendly)

# -----------------------------------------------------
# Error signal mapping (CAN-level)
# -----------------------------------------------------
# Using DBC names as-is

ERROR_SIGNALS = {
    # BO_ 600 AB_Error_Codes: 8  (ID 600 -> 0x0258)
    "OCC_ERROR":            {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 0},
    "HIGH_IMBALANCE_ERROR": {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 1},
    "PCB_TEMP_ERROR":       {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 2},
    "EXT_TEMP_ERROR":       {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 3},
    "EFUSE_DISCHG_ERROR":   {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 4},
    "EFUSE_CHG_ERROR":      {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 5},
    "UV_ERROR":             {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 6},
    "OV_ERROR":             {"can_id": 0x0258, "type": "bit", "byte": 0, "bit": 7},

    "OCD_ERROR":            {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 0},
    "FLASH_WRITE_FAIL":     {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 1},
    "EEPROM_WRITE_FAIL":    {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 2},
    "EEPROM_READ_FAIL":     {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 3},
    "PERMANENT_FAIL":       {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 4},
    "PRECHARGE_FAIL":       {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 5},
    "EEPROM_CORRUPTED":     {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 6},
    "EEPROM_COMM_FAIL":     {"can_id": 0x0258, "type": "bit", "byte": 1, "bit": 7},

    # BO_ 601 Critical_Error: 8  (ID 601 -> 0x0259)
    "SCD_ERROR":            {"can_id": 0x0259, "type": "bit", "byte": 0, "bit": 7},
    "THERMAL_RUNAWAY":      {"can_id": 0x0259, "type": "bit", "byte": 0, "bit": 6},
    "StartupSanityFail":    {"can_id": 0x0259, "type": "bit", "byte": 0, "bit": 5},

    # BO_ 608 AB_Error_Codes_1: 8  (ID 608 -> 0x0260)
    "EEPROM_SHADOW_WRITE_FAIL": {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 0},
    "EEPROM_META_WRITE_FAIL":   {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 1},
    "EEPROM_SHADOW_READ_FAIL":  {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 2},
    "EEPROM_META_READ_FAIL":    {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 3},
    "CCM_FAIL":                 {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 4},
    "CMU_FAIL":                 {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 5},
    "HardFaultPresent":         {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 6},
    "Config_Update_warning":    {"can_id": 0x0260, "type": "bit", "byte": 0, "bit": 7},

    "History_ActiveErrorGroup1": {"can_id": 0x0260, "type": "byte", "byte": 1},
    "History_ActiveErrorGroup2": {"can_id": 0x0260, "type": "byte", "byte": 2},
    "SD_Power_off_Pending":      {"can_id": 0x0260, "type": "bit", "byte": 3, "bit": 0},
    "Isolation_warning":         {"can_id": 0x0260, "type": "bit", "byte": 3, "bit": 1},
    "Isolation_Failure":         {"can_id": 0x0260, "type": "bit", "byte": 3, "bit": 2},
}

INTERESTING_CAN_IDS = set(v["can_id"] for v in ERROR_SIGNALS.values())

# Additional CAN frames for UV diagnostic context
DG_VOLTAGE_CAN_ID = 0x012C  # DG_voltageData
AA_BATT_PARAM_2_CAN_ID = 0x0109  # AA_Batt_Param_2

# Display order for table (matches your sheet first, then the rest)
DISPLAY_ORDER = [
    "SCD_ERROR",
    "EEPROM_SHADOW_WRITE_FAIL",
    "EEPROM_META_WRITE_FAIL",
    "EEPROM_SHADOW_READ_FAIL",
    "EEPROM_META_READ_FAIL",
    "CCM_FAIL",
    "CMU_FAIL",
    "HardFaultPresent",
    "Isolation_Failure",
    "Isolation_warning",
    "History_ActiveErrorGroup1",
    "History_ActiveErrorGroup2",
    "OCC_ERROR",
    "HIGH_IMBALANCE_ERROR",
    "PCB_TEMP_ERROR",
    "EXT_TEMP_ERROR",
    "EFUSE_DISCHG_ERROR",
    "EFUSE_CHG_ERROR",
    "UV_ERROR",
    "OV_ERROR",
    "OCD_ERROR",
    # remaining:
    "FLASH_WRITE_FAIL",
    "EEPROM_WRITE_FAIL",
    "EEPROM_READ_FAIL",
    "PERMANENT_FAIL",
    "PRECHARGE_FAIL",
    "EEPROM_CORRUPTED",
    "EEPROM_COMM_FAIL",
    "THERMAL_RUNAWAY",
    "StartupSanityFail",
    "Config_Update_warning",
    "SD_Power_off_Pending",
]

# -----------------------------------------------------
# Helpers
# -----------------------------------------------------
def get_signal_value(defn, data, dlc):
    b = defn["byte"]
    if b >= dlc:
        return 0
    if defn["type"] == "bit":
        bit = defn["bit"]
        return (data[b] >> bit) & 0x01
    elif defn["type"] == "byte":
        return data[b]
    return 0

def get_line_count(s):
    if not s:
        return 1
    return s.count("\n") + 1

def parse_le_unsigned(data, start_bit, length):
    """
    Basic little-endian extraction for byte-aligned signals.
    start_bit is the bit index from LSB of byte0.
    """
    byte_index = start_bit // 8
    byte_len = (length + 7) // 8
    if len(data) < byte_index + byte_len:
        return None
    value = 0
    for i in range(byte_len):
        value |= data[byte_index + i] << (8 * i)
    return value

def format_number(value, decimals):
    if value is None:
        return ""
    s = f"{value:.{decimals}f}"
    s = s.rstrip("0").rstrip(".")
    return s

def build_context_value(vmin, vmax, soc):
    vmin_str = format_number(vmin, 1)
    vmax_str = format_number(vmax, 1)
    soc_str = format_number(soc, 2)
    if not vmin_str and not vmax_str and not soc_str:
        return ""
    return f"Vmin={vmin_str} mV\nVmax={vmax_str} mV\nSoC={soc_str} %"

# -----------------------------------------------------
# GET TRC FILE FROM GUI
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
# STATE PER SIGNAL
# -----------------------------------------------------
# We track instances as continuous stretches of "active"
error_states = {
    name: {
        "last_active": False,
        "instances": [],        # list of {Start_Timestamp, End_Timestamp, Active_Frames}
        "last_value": 0,
        "last_nonzero": None    # for byte-type signals
    }
    for name in ERROR_SIGNALS.keys()
}

first_ts_ms = None
last_v_samples = []  # capped FIFO with latest voltage/SoC samples
latest_soc = None
uv_context_added = False  # ensure UV context only on first UV instance
ov_context_added = False  # ensure OV context only on first OV instance

def update_voltage_samples(can_id, data, dlc, ts_string):
    global latest_soc
    if can_id == AA_BATT_PARAM_2_CAN_ID:
        raw_soc = parse_le_unsigned(data, 0, 16)
        if raw_soc is not None:
            latest_soc = raw_soc * 0.01
    elif can_id == DG_VOLTAGE_CAN_ID:
        raw_vmax = parse_le_unsigned(data, 0, 16)
        raw_vmin = parse_le_unsigned(data, 16, 16)
        if raw_vmax is None or raw_vmin is None:
            return
        v_max = raw_vmax * 0.1
        v_min = raw_vmin * 0.1
        sample = {
            "Vmin": v_min,
            "Vmax": v_max,
            "SoC": latest_soc,
            "Timestamp": ts_string
        }
        last_v_samples.append(sample)
        if len(last_v_samples) > 20:
            last_v_samples.pop(0)

def compute_uv_context():
    recent = last_v_samples[-5:]
    valid = []
    for s in recent:
        if s is None:
            continue
        vmin = s.get("Vmin")
        if vmin is None:
            continue
        if 200 <= vmin <= 6500:
            valid.append(s)
    if not valid:
        return None
    selected = min(valid, key=lambda s: s["Vmin"])
    return {
        "Selected_Vmin": selected.get("Vmin"),
        "Selected_Vmax": selected.get("Vmax"),
        "Selected_SoC": selected.get("SoC"),
        "Context_Timestamp": selected.get("Timestamp")
    }

def compute_ov_context():
    recent = last_v_samples[-5:]
    valid = []
    for s in recent:
        if s is None:
            continue
        vmin = s.get("Vmin")
        vmax = s.get("Vmax")
        if vmin is None or vmax is None:
            continue
        if 200 <= vmin <= 6500 and 200 <= vmax <= 6500:
            valid.append(s)
    if not valid:
        return None
    selected = max(valid, key=lambda s: s["Vmax"])
    return {
        "Selected_Vmin": selected.get("Vmin"),
        "Selected_Vmax": selected.get("Vmax"),
        "Selected_SoC": selected.get("SoC"),
        "Context_Timestamp": selected.get("Timestamp")
    }

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

        ts_string = f"{date_str} {time_str}.{ms_norm}"   # preserve exact TRC-style format
        dt = datetime.strptime(ts_string, "%d-%m-%Y %H:%M:%S.%f")
        ts_ms = dt.timestamp() * 1000.0

        if first_ts_ms is None:
            first_ts_ms = ts_ms

        # Update rolling voltage/SoC samples (independent of error parsing)
        update_voltage_samples(can_id, data, dlc, ts_string)

        if can_id not in INTERESTING_CAN_IDS:
            continue

        # Process each signal belonging to this CAN ID
        for name, defn in ERROR_SIGNALS.items():
            if defn["can_id"] != can_id:
                continue

            val = get_signal_value(defn, data, dlc)
            st = error_states[name]

            st["last_value"] = val
            if defn["type"] == "byte" and val > 0:
                st["last_nonzero"] = val

            # "Active" definition
            if defn["type"] == "bit":
                is_active = (val == 1)
            else:  # byte
                is_active = (val > 0)

            if is_active:
                if not st["last_active"]:
                    # Start new instance
                    new_instance = {
                        "Start_Timestamp": ts_string,
                        "End_Timestamp": ts_string,
                        "Active_Frames": 1
                    }
                    if name == "UV_ERROR" and not uv_context_added:
                        uv_ctx = compute_uv_context()
                        if uv_ctx:
                            new_instance["UV_Context"] = uv_ctx
                        uv_context_added = True
                    if name == "OV_ERROR" and not ov_context_added:
                        ov_ctx = compute_ov_context()
                        if ov_ctx:
                            new_instance["OV_Context"] = ov_ctx
                        ov_context_added = True
                    st["instances"].append(new_instance)
                else:
                    # Extend last instance
                    inst = st["instances"][-1]
                    inst["End_Timestamp"] = ts_string
                    inst["Active_Frames"] += 1

            st["last_active"] = is_active

# -----------------------------------------------------
# BUILD RESULTS STRUCTURES
# -----------------------------------------------------
signals_result = []

for name in DISPLAY_ORDER:
    st = error_states.get(name, {"instances": [], "last_nonzero": None})
    instances = st["instances"]
    instance_count = len(instances)
    status = "YES" if instance_count > 0 else "NO"

    # Fail timestamps -> first timestamp of each instance
    fail_timestamps = [inst["Start_Timestamp"] for inst in instances]

    entry = {
        "Name": name,
        "Status": status,
        "Instance_Count": instance_count,
        "Instances": instances,
        "Fail_Timestamps": fail_timestamps,
    }

    # For byte-type signals, include last non-zero value
    defn = ERROR_SIGNALS.get(name)
    if defn and defn["type"] == "byte":
        entry["Last_Nonzero_Value"] = st.get("last_nonzero")
    else:
        entry["Last_Nonzero_Value"] = None

    value_field = ""
    if name == "UV_ERROR":
        uv_ctx = instances[0].get("UV_Context") if instances else None
        if uv_ctx:
            entry["UV_Context"] = uv_ctx
            if all(uv_ctx.get(k) is not None for k in ["Selected_Vmin", "Selected_Vmax", "Selected_SoC"]):
                value_field = build_context_value(
                    uv_ctx["Selected_Vmin"],
                    uv_ctx["Selected_Vmax"],
                    uv_ctx["Selected_SoC"]
                )
    elif name == "OV_ERROR":
        ov_ctx = instances[0].get("OV_Context") if instances else None
        if ov_ctx:
            entry["OV_Context"] = ov_ctx
            if all(ov_ctx.get(k) is not None for k in ["Selected_Vmin", "Selected_Vmax", "Selected_SoC"]):
                value_field = build_context_value(
                    ov_ctx["Selected_Vmin"],
                    ov_ctx["Selected_Vmax"],
                    ov_ctx["Selected_SoC"]
                )
    elif entry["Last_Nonzero_Value"] is not None:
        value_field = entry["Last_Nonzero_Value"]

    entry["Value"] = value_field

    signals_result.append(entry)

ignore_for_judgement = {
    "History_ActiveErrorGroup1",
    "History_ActiveErrorGroup2",
    "Config_Update_warning",
    "SD_Power_off_Pending",
}

def counts_as_active(entry):
    name = entry["Name"]
    if name in ignore_for_judgement:
        return False
    if name == "UV_ERROR":
        uv_ctx = entry.get("UV_Context")
        if uv_ctx:
            soc = uv_ctx.get("Selected_SoC")
            if soc is not None and soc < 1:
                return False
    return entry["Instance_Count"] > 0

active_error_count = sum(1 for e in signals_result if counts_as_active(e))
overall_result = "FAIL" if active_error_count > 0 else "PASS"

# -----------------------------------------------------
# SAVE RESULTS JSON
# -----------------------------------------------------
results_path = os.path.join(folder, "Any_BMS_Error_results.json")
with open(results_path, "w", encoding=OUTPUT_ENCODING) as f:
    json.dump({
        "Result": overall_result,
        "Active_Error_Count": active_error_count,
        "Signals": signals_result
    }, f, indent=4, ensure_ascii=False)

print(f"Saved: {results_path}")

# -----------------------------------------------------
# SUMMARY ASCII JSON
# -----------------------------------------------------
LEFT = 22
RIGHT = 42

def row(label, value):
    return f"| {label.ljust(LEFT)} | {str(value).ljust(RIGHT)} |"

border = "+" + "-"*(LEFT+2) + "+" + "-"*(RIGHT+2) + "+"

lines = [
    border,
    "| Any BMS Error Summary".center(LEFT + RIGHT + 5) + "|",
    border,
    row("Overall_Result", overall_result),
    row("Active_Error_Count", active_error_count),
    border
]

for e in signals_result:
    # Match your Excel-style summary: one line per signal
    lines.append(row("ERROR Signal", e["Name"]))
    lines.append(row("Status", e["Status"]))
    lines.append(row("Instance", e["Instance_Count"]))
    if e["Fail_Timestamps"]:
        # Just join timestamps with comma / can also be left for PNG only
        lines.append(row("Fail Timestamp(s)", "; ".join(e["Fail_Timestamps"])))
    else:
        lines.append(row("Fail Timestamp(s)", ""))
    val = e.get("Value", "")
    lines.append(row("Value", "" if val is None else val))
    lines.append(border)

summary_path = os.path.join(folder, "Any_BMS_Error_summary.json")
with open(summary_path, "w", encoding=OUTPUT_ENCODING) as f:
    json.dump({"Summary_Table": lines}, f, indent=4, ensure_ascii=False)

print(f"Saved: {summary_path}")

# -----------------------------------------------------
# PNG TABLE (Any_BMS_Error_plot.png) – NOT A GRAPH
# -----------------------------------------------------
headers = ["ERROR Signal", "Status", "Instance", "Fail Timestamp(s)", "Value"]
rows = []
line_counts = []

for e in signals_result:
    name = e["Name"]
    status = e["Status"]
    inst_cnt = e["Instance_Count"]
    # Multi-line timestamps: one per line
    ts_text = "\n".join(e["Fail_Timestamps"]) if e["Fail_Timestamps"] else ""
    val = e.get("Value", e.get("Last_Nonzero_Value"))
    val_text = "" if val is None else str(val)

    rows.append([name, status, inst_cnt, ts_text, val_text])
    line_counts.append(max(get_line_count(ts_text), get_line_count(val_text)))

# Figure height scales with number of lines per row
fig_width = 16
fig_height = 2 + sum(0.35 * lc for lc in line_counts)

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

# Header styling
for (r, c), cell in tbl.get_celld().items():
    cell.set_edgecolor("black")
    if r == 0:
        cell.set_facecolor("#1FA37A")
        cell.set_text_props(weight="bold", color="white")

# Adjust row heights based on number of timestamp lines
if rows:
    base_height = tbl[1, 0].get_height()
    for i, lc in enumerate(line_counts):
        row_idx = i + 1  # +1 because row 0 is header
        new_height = base_height * lc
        for col in range(len(headers)):
            tbl[row_idx, col].set_height(new_height)

        # Optional: highlight rows with Status == YES
        if rows[i][1] == "YES":
            for col in range(len(headers)):
                tbl[row_idx, col].set_facecolor("#FFCCCC")

png_path = os.path.join(folder, "Any_BMS_Error_plot.png")
plt.savefig(png_path, dpi=220, bbox_inches="tight")
plt.close()

print(f"Saved: {png_path}")
print("Any BMS Error Analysis DONE ✔")
