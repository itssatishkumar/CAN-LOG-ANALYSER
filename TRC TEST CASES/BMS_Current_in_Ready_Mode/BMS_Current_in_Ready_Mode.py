#!/usr/bin/env python3
import sys, os, re, json
from datetime import datetime
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)
from trc_utils import fast_parse_ts, progress_by_bytes
PROGRESS_STEP = 0.5  # percent granularity for live progress

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
emit_progress = progress_by_bytes(trc_path, step=PROGRESS_STEP)

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
BMS_ALLOWED_VALUES = {0x01, 0x04}
SCALE_FACTOR     = 1e-5
THRESHOLD_A      = 0.2

# ---------------------------------------------------------------------
# TRC PARSER REGEX
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
pending_records = []

# ---------------------------------------------------------------------
# PARSE TRC FILE
# ---------------------------------------------------------------------
with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
    for line_idx, line in enumerate(f, 1):
        emit_progress(len(line))
        m = pattern.match(line)
        if not m:
            continue

        date_str = m.group(1)
        time_str = m.group(2)
        ms_str   = m.group(3)
        can_id   = int(m.group(4), 16)
        dlc      = int(m.group(5))
        data_str = m.group(6).strip()

        bytes_hex = data_str.split()
        if len(bytes_hex) < dlc:
            continue

        data = [int(b, 16) for b in bytes_hex[:dlc]]

        dt, _, timestamp = fast_parse_ts(date_str, time_str, ms_str)

        # ---------------------------------------------------------
        # 0109 → BMS STATE
        # ---------------------------------------------------------
        if can_id == BMS_STATE_ID:
            if len(data) >= 5:
                next_bms_state = data[4]

                if pending_records:
                    if next_bms_state in BMS_ALLOWED_VALUES:
                        ready_records.extend(pending_records)
                    pending_records.clear()

                current_bms_state = next_bms_state

        # ---------------------------------------------------------
        # 0110 → PACK CURRENT
        # ---------------------------------------------------------
        if can_id == PACK_CURRENT_ID and current_bms_state in BMS_ALLOWED_VALUES:

            if len(data) < 8:
                continue

            raw = (
                data[4] |
                (data[5] << 8) |
                (data[6] << 16) |
                (data[7] << 24)
            )

            if raw & 0x80000000:
                raw -= 0x100000000

            current_A = raw * SCALE_FACTOR

            pending_records.append({
                "timestamp": timestamp,
                "raw_bytes": " ".join(f"{b:02X}" for b in data[4:8]),
                "signed_value": raw,
                "current_A": round(current_A, 5)
            })

pending_records.clear()

# ---------------------------------------------------------------------
# FIND MAX CURRENT
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
# FAILURE COUNT (ADDED)
# ---------------------------------------------------------------------
fail_count = sum(1 for r in ready_records if abs(r["current_A"]) > THRESHOLD_A)

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
# CLEAN PLOT
# ---------------------------------------------------------------------
plt.figure(figsize=(10,6))
plt.title("BMS Current in READY Mode")

if ready_records:

    plt.scatter(1, summary_data["max_current_A"], color="red", s=80)
    plt.xticks([1], ["Max Current"])
    plt.ylabel("Pack Current (A)")

    # RESULT BOX (unchanged)
    plt.text(
        0.5, 0.9,
        f"Result: {result_str} (Max |I| = {abs(summary_data['max_current_A']):.5f} A)",
        ha="center", transform=plt.gca().transAxes,
        fontsize=12, bbox=dict(boxstyle="round", facecolor="white", alpha=0.6)
    )

    # FAILURE COUNT BOX (only addition)
    plt.text(
        0.5, 0.83,
        f"FAILURE COUNT : {fail_count}",
        ha="center", transform=plt.gca().transAxes,
        fontsize=12, bbox=dict(boxstyle="round", facecolor="white", alpha=0.6)
    )

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
print("PROGRESS 100.0", flush=True)
