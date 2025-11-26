#!/usr/bin/env python3
"""
FINAL VERSION – NEXT FRAME LOGIC

Rules:
When FFC = 1 → 0:
    Use NEXT frame values for:
        - SoC_At_Transition
        - Vmax_At_Transition_mV
        - Timestamp
        - Judgment (PASS/FAIL)

VALID transition if:
    SoC_next ≤ 99.45 OR Vmax_next < 3300

INVALID transition if:
    SoC_next > 99.45 AND Vmax_next ≥ 3300

0x0109:
    Byte0 = SoC LSB
    Byte1 = SoC MSB
    Byte5 = FFC (0 or 1)
    SF SoC = 0.01

0x012C:
    Byte0 = Vmax LSB
    Byte1 = Vmax MSB
    SF Vmax = 0.1 mV
"""

import sys
import os
import json
import matplotlib.pyplot as plt

RESULT_FILE = "Flag_Full_Charge_Disable_results.json"
SUMMARY_FILE = "Flag_Full_Charge_Disable_summary.json"
PLOT_FILE = "Flag_Full_Charge_Disable_plot.png"

# ------------------------------------------------------------
# Decode helpers
# ------------------------------------------------------------
def u16_le(b0, b1):
    return b0 | (b1 << 8)

def extract_soc(data):
    raw = u16_le(data[0], data[1])
    return raw * 0.01

def extract_ffc(data):
    return 1 if data[5] != 0 else 0   # Correct byte for FFC

def extract_vmax(data):
    raw = u16_le(data[0], data[1])
    return raw * 0.1

# ------------------------------------------------------------
# TRC Processing (NEXT FRAME LOGIC)
# ------------------------------------------------------------
def process_trc(trc_path):
    history = []
    
    vmax_latest = None
    prev_ffc = None
    pending_drop = False

    valid_event = None
    invalid_event = None

    with open(trc_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("---"):
                continue

            parts = line.split()
            if len(parts) < 7:
                continue

            try:
                idx_str = parts[0]
                if idx_str.endswith(")"):
                    index = int(idx_str[:-1])
                else:
                    index = int(idx_str)

                timestamp = parts[1] + " " + parts[2]
                can_id = int(parts[4], 16)
                dlc = int(parts[5])
                data = [int(x, 16) for x in parts[6:6+dlc]]
            except:
                continue

            # 0x012C - Vmax update
            if can_id == 0x012C and len(data) >= 2:
                vmax_latest = extract_vmax(data)
                continue

            # 0x0109 - SoC + FFC frame
            if can_id == 0x0109 and len(data) >= 6:
                soc = extract_soc(data)
                ffc = extract_ffc(data)
                vmax_now = vmax_latest

                history.append({
                    "index": index,
                    "timestamp": timestamp,
                    "soc": soc,
                    "vmax": vmax_now,
                    "ffc": ffc
                })

                # ----------- NEXT FRAME LOGIC --------------
                if pending_drop and not (valid_event or invalid_event):
                    # Evaluate the first SoC+FFC frame after the drop
                    soc_cond = soc <= 99.45
                    vmax_cond = (vmax_now is not None) and (vmax_now < 3300)

                    if soc_cond or vmax_cond:
                        reason = "Both" if (soc_cond and vmax_cond) else ("SoC" if soc_cond else "Vmax")
                        valid_event = {
                            "Timestamp": timestamp,
                            "SoC_At_Transition": soc,
                            "Vmax_At_Transition_mV": vmax_now,
                            "Reason": reason
                        }
                    else:
                        invalid_event = {
                            "Timestamp": timestamp,
                            "SoC_At_InvalidDrop": soc,
                            "Vmax_At_InvalidDrop_mV": vmax_now,
                            "Reason": "FFC dropped while thresholds were NOT crossed (NEXT frame)"
                        }

                    pending_drop = False

                if prev_ffc == 1 and ffc == 0 and not (valid_event or invalid_event):
                    # Flag the next frame to be used for PASS/FAIL
                    pending_drop = True

                prev_ffc = ffc

    return history, valid_event, invalid_event

# ------------------------------------------------------------
# JSON
# ------------------------------------------------------------
def save_result_json(valid_event, invalid_event):
    result = "FAIL" if invalid_event else "PASS"
    
    with open(RESULT_FILE, "w") as f:
        json.dump({"Result": result}, f, indent=2)

def save_summary_json(valid_event, invalid_event):
    if invalid_event:
        summary = {
            "Result": "FAIL",
            "ValidTransition": False,
            **invalid_event
        }
    elif valid_event:
        summary = {
            "Result": "PASS",
            "ValidTransition": True,
            **valid_event
        }
    else:
        summary = {
            "Result": "PASS",
            "ValidTransition": False,
            "Message": "No FFC drop detected"
        }

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)

# ------------------------------------------------------------
# Plot
# ------------------------------------------------------------
def make_plot(history, valid_event, invalid_event):
    if not history:
        return
    
    x = list(range(len(history)))
    soc = [h["soc"] for h in history]
    vmax = [h["vmax"] for h in history]
    ffc = [h["ffc"] for h in history]

    plt.figure(figsize=(10,5))
    plt.title("SoC, Vmax, FFC (NEXT FRAME LOGIC)")

    plt.plot(x, soc, label="SoC (%)")
    plt.plot(x, vmax, label="Vmax (mV)")
    plt.step(x, ffc, where="mid", label="FFC")

    # highlight transition
    event = valid_event if valid_event else invalid_event
    if event:
        ts = event["Timestamp"]
        for i, h in enumerate(history):
            if h["timestamp"] == ts:
                color = "green" if valid_event else "red"
                plt.scatter(i, h["soc"], s=80, color=color)
                plt.scatter(i, h["vmax"], s=80, color=color)
                break

    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(PLOT_FILE)
    plt.close()

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("ERROR: TRC file missing!")
        sys.exit(1)

    trc_path = sys.argv[1]

    if not os.path.exists(trc_path):
        print(f"ERROR: TRC file not found: {trc_path}")
        sys.exit(1)

    history, valid_event, invalid_event = process_trc(trc_path)

    save_result_json(valid_event, invalid_event)
    save_summary_json(valid_event, invalid_event)
    make_plot(history, valid_event, invalid_event)

    if invalid_event:
        print("FAIL: Illegal FFC drop detected.")
    elif valid_event:
        print("PASS: Valid transition detected.")
    else:
        print("PASS: No transition occurred.")

if __name__ == "__main__":
    main()
