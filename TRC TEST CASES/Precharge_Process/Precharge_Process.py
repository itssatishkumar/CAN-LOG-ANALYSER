import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import re
from datetime import datetime
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

PRECHARGE_ID = 0x0110
FAIL_FLAG_ID = 0x0258

timestamps = []
flags = []
currents = []
full_ts_list = []
precharge_fail_samples = []


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

        bytes_hex = data_str.split()
        if len(bytes_hex) < dlc:
            continue

        data = [int(b, 16) for b in bytes_hex[:dlc]]

        ts_str = f"{date_str} {time_str}.{ms_str}"
        dt = datetime.strptime(ts_str, "%d-%m-%Y %H:%M:%S.%f")
        ts_ms = dt.timestamp() * 1000.0

        # -------- PRECHARGE FAIL FLAG --------
        if can_id == FAIL_FLAG_ID:
            fail = (data[1] >> 5) & 0x01
            precharge_fail_samples.append((ts_ms, fail))

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
# Helper: format current values two per line
# -----------------------------------------------------
def format_currents_multiline(curr_list):
    lines = []
    for i in range(0, len(curr_list), 2):
        pair = curr_list[i:i+2]
        lines.append(", ".join(f"{v:.6f}" for v in pair))
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

        events.append({
            "Start_Timestamp": block.iloc[0].full_ts,
            "End_Timestamp": block.iloc[-1].full_ts,
            "Duration (s)": round(dur_s, 3),
            "Max_Current (A)": round(max_curr, 6),
            "End_Current (A)": round(end_curr, 6),
            "Currents_Multiline": multiline,
            "Status": status,
            "Precharge_Fail_Flag": fail_flag
        })

        in_precharge = False


# -----------------------------------------------------
# SAVE RESULTS JSON
# -----------------------------------------------------
overall = "PASS" if events and all(e["Status"] == "PASS" for e in events) else "FAIL"

with open(os.path.join(folder, "Precharge_Process_results.json"), "w", encoding="utf-8") as f:
    json.dump({"Result": overall, "Events": events}, f, indent=4)


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
    table_lines.append(row("Start_Timestamp", e["Start_Timestamp"]))
    table_lines.append(row("End_Timestamp", e["End_Timestamp"]))
    table_lines.append(row("Duration (s)", str(e["Duration (s)"])))
    table_lines.append(row("Max_Current (A)", str(e["Max_Current (A)"])))

    for line in e["Currents_Multiline"].split("\n"):
        table_lines.append(row("Currents (A)", line))

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
        "Start_Timestamp",
        "End_Timestamp",
        "Duration (s)",
        "Max_Current (A)",
        "Currents (A)",
        "Status",
        "Precharge_Fail_Flag"
    ]

    rows = []
    line_counts = []

    for e in events:
        rows.append([
            e["Start_Timestamp"],
            e["End_Timestamp"],
            e["Duration (s)"],
            e["Max_Current (A)"],
            e["Currents_Multiline"],
            e["Status"],
            e["Precharge_Fail_Flag"]
        ])
        line_counts.append(get_line_count(e["Currents_Multiline"]))

    fig_height = 2 + sum(0.40 * lc for lc in line_counts)
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

    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("black")
        if r == 0:
            cell.set_facecolor("#1FA37A")
            cell.set_text_props(weight="bold", color="white")

    # Set row height based on line count
    for i, lc in enumerate(line_counts):
        row_idx = i + 1
        base_height = tbl[row_idx, 0].get_height()
        new_height = base_height * lc
        for col in range(len(headers)):
            tbl[row_idx, col].set_height(new_height)

    png_path = os.path.join(folder, "Precharge_Process_plot.png")
    plt.savefig(png_path, dpi=220, bbox_inches="tight")
    plt.close()

print("DONE :)")
