import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import re
from datetime import datetime
import json

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

PRECHARGE_ID = 0x0110
FAIL_FLAG_ID = 0x0258
TERMINAL_V_CAN_IDS = (0x0156, 0x0342)  # BO_ 342 (342 decimal = 0x0156, 342 hex = 0x0342)
PACK_V_CAN_IDS = (0x0109, 0x0265)      # BO_ 265 (265 decimal = 0x0109, 265 hex = 0x0265)

timestamps = []
flags = []
currents = []
full_ts_list = []
precharge_fail_samples = []
terminal_v_samples = []
pack_v_samples = []


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

        bytes_hex = data_str.split()
        if len(bytes_hex) < dlc:
            continue

        data = [int(b, 16) for b in bytes_hex[:dlc]]

        dt, ts_ms, ts_str = fast_parse_ts(date_str, time_str, ms_str)

        # -------- PRECHARGE FAIL FLAG --------
        if can_id == FAIL_FLAG_ID:
            fail = (data[1] >> 5) & 0x01
            precharge_fail_samples.append((ts_ms, fail))

        # -------- TERMINAL SENSING VOLTAGE --------
        # BO_ 342 BC_Dynamic_inst SG_ Terminal_Sensing_V : 32|16@1+ (0.1,0)
        if can_id in TERMINAL_V_CAN_IDS and len(data) >= 6:
            raw_term = data[4] | (data[5] << 8)
            term_v = raw_term * 0.1
            terminal_v_samples.append((ts_ms, term_v))

        # -------- PACK VOLTAGE --------
        # BO_ 265 AA_Batt_Param_2 SG_ Pack_Voltage : 48|16@1+ (0.1,0)
        if can_id in PACK_V_CAN_IDS and len(data) >= 8:
            raw_pack = data[6] | (data[7] << 8)
            pack_v = raw_pack * 0.1
            pack_v_samples.append((ts_ms, pack_v))

        # -------- PRECHARGE FRAME --------
        if can_id == PRECHARGE_ID and len(data) >= 8:

            flag = data[2]   # byte 3

            raw = (
                data[4] |
                (data[5] << 8) |
                (data[6] << 16) |
                (data[7] << 24)
            )
            if raw & 0x80000000:
                raw -= 0x100000000

            current = raw * 1e-5

            timestamps.append(ts_ms)
            flags.append(flag)
            currents.append(current)
            full_ts_list.append(ts_str)


# -----------------------------------------------------
# BUILD DATAFRAME
# -----------------------------------------------------
df = pd.DataFrame({
    "ts": timestamps,
    "flag": flags,
    "current": currents,
    "full_ts": full_ts_list
})

if df.empty:
    print("No precharge frames found!")
    sys.exit(1)


# -----------------------------------------------------
# Helper: format current/voltage values two per line
# -----------------------------------------------------
def format_currents_multiline(curr_list):
    lines = []
    for i in range(0, len(curr_list), 2):
        pair = curr_list[i:i+2]
        lines.append(", ".join(f"{v:.6f}" for v in pair))
    return "\n".join(lines)


def format_voltages_multiline(v_list):
    if not v_list:
        return "N/A"
    lines = []
    for i in range(0, len(v_list), 2):
        pair = v_list[i:i+2]
        lines.append(", ".join(f"{v:.2f}V" for v in pair))
    return "\n".join(lines)


def get_line_count(multiline_str):
    return multiline_str.count("\n") + 1


# -----------------------------------------------------
# PRECHARGE EVENTS: duration = 0→1→0, FAIL-check = 1→next 1
# -----------------------------------------------------
events = []
in_precharge = False
start_idx = None

for i in range(1, len(df)):
    prev = df.iloc[i - 1]
    curr = df.iloc[i]

    # Start duration window: 0 → 1
    if (not in_precharge) and prev.flag == 0 and curr.flag == 1:
        in_precharge = True
        start_idx = i

    # End duration window: 1 → 0
    if in_precharge and prev.flag == 1 and curr.flag == 0:
        end_idx = i - 1
        block = df.iloc[start_idx:end_idx + 1]

        ts_start = block.iloc[0].ts
        ts_end   = block.iloc[-1].ts
        dur_s    = (ts_end - ts_start) / 1000.0

        curr_values = block["current"].values
        max_curr = block["current"].abs().max()
        end_curr = block["current"].iloc[-1]

        # -----------------------------------------------------
        # Terminal Sensing Voltage & Pack Voltage during precharge
        # -----------------------------------------------------
        v_in_block = [v for t_v, v in terminal_v_samples if ts_start <= t_v <= ts_end]
        if not v_in_block:
            last_v = [v for t_v, v in terminal_v_samples if t_v <= ts_end]
            v_in_block = [last_v[-1]] if last_v else []

        v_multiline = format_voltages_multiline(v_in_block)

        # Final Terminal Sensing Voltage
        final_term_v = v_in_block[-1] if v_in_block else None

        # Pack Voltage in block
        pack_v_in_block = [v for t_v, v in pack_v_samples if ts_start <= t_v <= ts_end]
        if not pack_v_in_block:
            last_p = [v for t_v, v in pack_v_samples if t_v <= ts_end]
            pack_v_in_block = [last_p[-1]] if last_p else []

        max_pack_v = max(pack_v_in_block) if pack_v_in_block else None
        delta_v = (max_pack_v - final_term_v) if (max_pack_v is not None and final_term_v is not None) else None

        if max_pack_v is not None and delta_v is not None:
            pack_v_delta_multiline = (
                f"Max Pack Voltage : {max_pack_v:.2f}V\n"
                f"Delta During Precharge : {delta_v:.2f}V"
            )
        elif max_pack_v is not None:
            pack_v_delta_multiline = f"Max Pack Voltage : {max_pack_v:.2f}V\nDelta During Precharge : N/A"
        else:
            pack_v_delta_multiline = "Max Pack Voltage : N/A\nDelta During Precharge : N/A"

        # -----------------------------------------------------
        # PASS logic: ANY 2 consecutive samples <= 0.25A
        # -----------------------------------------------------
        status = "FAIL"
        for k in range(len(curr_values) - 1):
            if (abs(curr_values[k]) <= 0.25 and
                abs(curr_values[k+1]) <= 0.25):
                status = "PASS"
                break

        # -----------------------------------------------------
        # CORRECT PRECHARGE_FAIL CHECK (checker window)
        # checker window: from ts_start until next FLAG=1
        # -----------------------------------------------------
        next_flag_time = None
        for j in range(i + 1, len(df)):
            if df.iloc[j].flag == 1:
                next_flag_time = df.iloc[j].ts
                break

        # If no next FLAG=1, checker continues to end of log
        if next_flag_time is None:
            next_flag_time = df["ts"].iloc[-1] + 1

        fail_flag = "NO"
        for t_f, f_f in precharge_fail_samples:
            if ts_start <= t_f < next_flag_time and f_f == 1:
                fail_flag = "YES"
                break

        multiline = format_currents_multiline(curr_values.tolist())
        timestamps_multiline = f"Start: {block.iloc[0].full_ts}\nEnd: {block.iloc[-1].full_ts}"

        events.append({
            "Start_Timestamp": block.iloc[0].full_ts,
            "End_Timestamp": block.iloc[-1].full_ts,
            "Timestamps_Multiline": timestamps_multiline,
            "Duration (s)": round(dur_s, 3),
            "Max_Current (A)": round(max_curr, 6),
            "End_Current (A)": round(end_curr, 6),
            "Currents_Multiline": multiline,
            "Terminal_Sensing_V_Multiline": v_multiline,
            "Max_Pack_Voltage (V)": round(max_pack_v, 2) if max_pack_v is not None else None,
            "Final_Terminal_Sensing_V (V)": round(final_term_v, 2) if final_term_v is not None else None,
            "Precharge_Delta_V (V)": round(delta_v, 2) if delta_v is not None else None,
            "Pack_V_&_Delta_Multiline": pack_v_delta_multiline,
            "Status": status,
            "Precharge_Fail_Flag": fail_flag
        })

        in_precharge = False

# -----------------------------------------------------
# SAVE RESULTS JSON
# -----------------------------------------------------
if not events:
    overall = "PASS"
else:
    any_status_fail = any(e["Status"] == "FAIL" for e in events)
    any_flag_fail = any(e["Precharge_Fail_Flag"] == "YES" for e in events)
    if (not any_status_fail) and (not any_flag_fail):
        overall = "PASS"
    elif any_status_fail and (not any_flag_fail):
        overall = "WARNING"
    else:
        overall = "FAIL"

with open(os.path.join(folder, "Precharge_Process_results.json"), "w", encoding="utf-8") as f:
    json.dump({"Result": overall, "Events": events}, f, indent=4)

# ===== PRECHARGE TXT OUTPUT =====
from pathlib import Path

p = Path(__file__).resolve()

for parent in [p] + list(p.parents):
    history = parent / "History"
    if history.exists() and history.is_dir():

        if not events:
            text = "No precharge session"

        else:
            if overall == "FAIL":
                max_event = max(events, key=lambda e: e["Duration (s)"])
                max_time = max_event["Duration (s)"]

                text = (
                    f"FAIL\n"
                    f"Max Precharge Process Time : {max_time:.2f}s"
                )

            elif overall == "WARNING":
                max_event = max(events, key=lambda e: e["Duration (s)"])
                max_time = max_event["Duration (s)"]

                text = (
                    f"WARNING\n"
                    f"Max Precharge Process Time : {max_time:.2f}s"
                )

            else:  # PASS
                max_event = max(events, key=lambda e: e["Duration (s)"])
                max_time = max_event["Duration (s)"]
                max_current = max_event["Max_Current (A)"]

                text = (
                    f"Precharge Process check : PASS, {max_current:.2f}A\n"
                    f"Max Precharge Process Time : {max_time:.2f}s"
                )

        file = history / "Precharge.txt"
        with open(file, "w", encoding="utf-8") as f:
            f.write(text)
        break

# -----------------------------------------------------
# ASCII SUMMARY JSON
# -----------------------------------------------------
LEFT = 22
RIGHT = 42

def row(label, value):
    return f"| {label.ljust(LEFT)} | {value.ljust(RIGHT)} |"

border = "+" + "-"*(LEFT+2) + "+" + "-"*(RIGHT+2) + "+"

table_lines = [
    border,
    "| Precharge Summary".center(LEFT + RIGHT + 5) + "|",
    border,
]

for e in events:
    for line in e["Timestamps_Multiline"].split("\n"):
        table_lines.append(row("Timestamps", line))

    table_lines.append(row("Duration (s)", str(e["Duration (s)"])))
    table_lines.append(row("Max_Current (A)", str(e["Max_Current (A)"])))

    for line in e["Currents_Multiline"].split("\n"):
        table_lines.append(row("Currents (A)", line))

    for line in e["Terminal_Sensing_V_Multiline"].split("\n"):
        table_lines.append(row("Terminal_Sensing_V (V)", line))

    for line in e["Pack_V_&_Delta_Multiline"].split("\n"):
        table_lines.append(row("Pack_V_&_Delta", line))

    table_lines.append(row("Status", e["Status"]))
    table_lines.append(row("Precharge_Fail_Flag", e["Precharge_Fail_Flag"]))
    table_lines.append(border)

with open(os.path.join(folder, "Precharge_Process_summary.json"), "w", encoding="utf-8") as f:
    json.dump({"Summary_Table": table_lines}, f, indent=4)

# -----------------------------------------------------
# PNG TABLE (dynamic height)
# -----------------------------------------------------
if events:

    headers = [
        "Timestamps\n(Start / End)",
        "Duration (s)",
        "Max_Current (A)",
        "Currents (A)",
        "Terminal_Sensing_V (V)",
        "Max_Pack_V_&_Delta",
        "Status",
        "Precharge_Fail_Flag"
    ]

    rows = []
    line_counts = []

    for e in events:
        rows.append([
            e["Timestamps_Multiline"],
            e["Duration (s)"],
            e["Max_Current (A)"],
            e["Currents_Multiline"],
            e["Terminal_Sensing_V_Multiline"],
            e["Pack_V_&_Delta_Multiline"],
            e["Status"],
            e["Precharge_Fail_Flag"]
        ])
        lc = max(
            get_line_count(e["Timestamps_Multiline"]),
            get_line_count(e["Currents_Multiline"]),
            get_line_count(e["Terminal_Sensing_V_Multiline"]),
            get_line_count(e["Pack_V_&_Delta_Multiline"])
        )
        line_counts.append(lc)

    fig_height = 2.5 + sum(0.40 * lc for lc in line_counts)
    fig_width = 22

    col_widths = [0.15, 0.07, 0.08, 0.17, 0.17, 0.22, 0.06, 0.08]

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")

    tbl = ax.table(
        cellText=rows,
        colLabels=headers,
        colWidths=col_widths,
        loc="center",
        cellLoc="left"
    )

    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.0, 1.2)

    # Double header row height so header text is never cut off
    for col in range(len(headers)):
        tbl[0, col].set_height(tbl[0, col].get_height() * 2.2)

    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("black")
        if r == 0:
            cell.set_facecolor("#1FA37A")
            cell.set_text_props(weight="bold", color="white")

    # Set data row height based on line count
    for i, lc in enumerate(line_counts):
        row_idx = i + 1
        base_height = tbl[row_idx, 0].get_height()
        new_height = base_height * lc
        for col in range(len(headers)):
            tbl[row_idx, col].set_height(new_height)

    png_path = os.path.join(folder, "Precharge_Process_plot.png")
    plt.savefig(png_path, dpi=220, bbox_inches="tight")
    plt.close()

print("PROGRESS 100.0", flush=True)
print("DONE :)")
