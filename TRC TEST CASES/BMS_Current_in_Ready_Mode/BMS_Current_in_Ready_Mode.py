#!/usr/bin/env python3
import sys, os, re, json
from datetime import datetime
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------
# GET TRC FILE FROM GUI ARGUMENT
# ---------------------------------------------------------------------
if len(sys.argv) < 2:
    print("ERROR: No TRC file received from GUI!")
    sys.exit(1)

trc_path = sys.argv[1]

if not os.path.exists(trc_path):
    print(f"ERROR: TRC file not found: {trc_path}")
    sys.exit(1)

print(f"Using TRC file: {trc_path}")

# ---------------------------------------------------------------------
# OUTPUT FILES
# ---------------------------------------------------------------------
SUMMARY_FILE = "BMS_Current_in_Ready_Mode_summary.json"
RESULT_FILE  = "BMS_Current_in_Ready_Mode_results.json"
PLOT_FILE    = "BMS_Current_in_Ready_Mode_plot.png"

# ---------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------
BMS_STATE_ID     = 0x0109
PACK_CURRENT_ID  = 0x0110
BMS_READY_VALUE  = 0x01
SCALE_FACTOR     = 1e-5
THRESHOLD_A      = 0.2   # PASS if |max_current| <= 0.2A

# ---------------------------------------------------------------------
# FIXED TRC PARSER REGEX (WORKS FOR YOUR REAL FILE)
# ---------------------------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+"
    r"(?:Rx|Tx)\s+"
    r"([0-9A-Fa-f]{3,8})\s+"
    r"(\d+)\s+"
    r"(.+)"
)

# ---------------------------------------------------------------------
# STORAGE
# ---------------------------------------------------------------------
ready_records = []
current_bms_state = None

# ---------------------------------------------------------------------
# PARSE TRC FILE
# ---------------------------------------------------------------------
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

        # timestamp
        timestamp = f"{date_str} {time_str}.{ms_norm}"
        dt = datetime.strptime(timestamp, "%d-%m-%Y %H:%M:%S.%f")

        # ---------------------------------------------------------
        # 0109 → BMS READY STATE
        # ---------------------------------------------------------
        if can_id == BMS_STATE_ID:
            if len(data) >= 5:
                current_bms_state = data[4]    # BYTE-5 EXACT

        # ---------------------------------------------------------
        # 0110 → PACK CURRENT IF READY
        # ---------------------------------------------------------
        if can_id == PACK_CURRENT_ID and current_bms_state == BMS_READY_VALUE:

            if len(data) < 8:
                continue

            # last 4 bytes little endian signed 32-bit
            raw = (
                data[4] |
                (data[5] << 8) |
                (data[6] << 16) |
                (data[7] << 24)
            )
            if raw & 0x80000000:
                raw -= 0x100000000

            current_A = raw * SCALE_FACTOR

            ready_records.append({
                "timestamp": timestamp,
                "raw_bytes": " ".join(f"{b:02X}" for b in data[4:8]),
                "signed_value": raw,
                "current_A": round(current_A, 5)
            })

# ---------------------------------------------------------------------
# FIND ONLY MAX CURRENT FOR SUMMARY
# ---------------------------------------------------------------------
if ready_records:
    max_rec = max(ready_records, key=lambda r: abs(r["current_A"]))
    summary_data = {
        "max_current_A": max_rec["current_A"],
        "timestamp": max_rec["timestamp"]
    }
else:
    summary_data = {
        "max_current_A": 0,
        "timestamp": None
    }

with open(SUMMARY_FILE, "w") as f:
    json.dump(summary_data, f, indent=2)

# ---------------------------------------------------------------------
# PASS / FAIL LOGIC
# ---------------------------------------------------------------------
if ready_records:
    max_mag = abs(summary_data["max_current_A"])
    result_str = "PASS" if max_mag <= THRESHOLD_A else "FAIL"
else:
    result_str = "PASS"

with open(RESULT_FILE, "w") as f:
    json.dump({"Result": result_str}, f)

# ---------------------------------------------------------------------
# CLEAN, SIMPLE PLOT WITH ONLY MAX POINT
# ---------------------------------------------------------------------
plt.figure(figsize=(10,6))
plt.title("BMS Current in READY Mode")

if ready_records:
    # Only one point: max
    plt.scatter(1, summary_data["max_current_A"], color="red", s=80)
    plt.xticks([1], ["Max Current"])
    plt.ylabel("Pack Current (A)")

    # Annotate PASS/FAIL
    plt.text(
        0.5, 0.9,
        f"Result: {result_str} (Max |I| = {abs(summary_data['max_current_A']):.5f} A)",
        ha="center", transform=plt.gca().transAxes,
        fontsize=12, bbox=dict(boxstyle="round", facecolor="white", alpha=0.6)
    )

    # Table for only ONE record
    table_data = [
        [summary_data["timestamp"], f"{summary_data['max_current_A']:.5f}"]
    ]

    plt.table(
        cellText=table_data,
        colLabels=["Timestamp", "Max Current (A)"],
        loc='bottom',
        cellLoc='center'
    )
    plt.subplots_adjust(bottom=0.25)
else:
    plt.text(0.5, 0.5, "No READY Mode samples found", ha='center', va='center')
    plt.axis('off')

plt.savefig(PLOT_FILE, dpi=150)
plt.close()

print("DONE.")
print(f"Summary : {SUMMARY_FILE}")
print(f"Result  : {RESULT_FILE}")
print(f"Plot    : {PLOT_FILE}")
