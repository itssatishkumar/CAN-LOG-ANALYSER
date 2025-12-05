#!/usr/bin/env python3
"""
FINAL VERSION – NEXT FRAME LOGIC (Vmax evaluated using prev5+next5 window around DROP frame)
+ Transition-only Plot (frame-by-frame) with X-axis tick labels = SoC (%)

Rules:
When FFC = 1 → 0 (detected on a 0x0109 frame = DROP frame):
    Use NEXT 0x0109 frame values for:
        - SoC_At_Transition
        - Vmax_At_Transition_mV (latest known at that NEXT 0x0109)
        - Timestamp
        - Judgment (PASS/FAIL)

VALID transition if:
    SoC_next ≤ 99.45 OR (ANY Vmax in window < 3300)

INVALID transition if:
    SoC_next > 99.45 AND (ALL Vmax in window ≥ 3300)

Vmax window definition:
    Around the 0x0109 DROP frame (FFC 1->0):
        - Previous 5 Vmax samples (0x012C) seen before the drop-frame
        - Next 5 Vmax samples (0x012C) seen after the drop-frame
    If ANY of these 10 values is < 3300 mV, the Vmax condition is satisfied.

Plot requirement:
- Frame-by-frame plot (equal spacing in time/order)
- X-axis displays SoC (%) values as tick labels (99.84, 99.83, ...)
- If transition found: show only a window of frames around the decision (NEXT 0x0109)
- If no transition: still plot something useful (last N frames)
- IMPORTANT: Do NOT invert x-axis (prevents SoC appearing reversed)

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
    return 1 if data[5] != 0 else 0

def extract_vmax(data):
    raw = u16_le(data[0], data[1])
    return raw * 0.1  # mV


# ------------------------------------------------------------
# TRC Processing
# ------------------------------------------------------------
def process_trc(trc_path):
    history = []

    vmax_latest = None
    vmax_hist = []   # all decoded Vmax samples (mV), in arrival order

    prev_ffc = None

    # drop window around DROP 0x0109 (ffc 1->0)
    drop_window = None  # {"drop_ts":..., "prev5":[...], "next5":[...]}
    next_0109_pending = False

    # NEXT 0x0109 snapshot captured here (for final PASS/FAIL reporting)
    pending_next_0109_snapshot = None  # {"timestamp":..., "soc":..., "vmax_now":...}

    valid_event = None
    invalid_event = None

    def get_window(dw):
        if not dw:
            return None
        prev5 = dw["prev5"][-5:]
        next5 = dw["next5"][:5]
        w = prev5 + next5
        return w if len(next5) == 5 else None

    def finalize_if_ready():
        nonlocal valid_event, invalid_event, next_0109_pending, pending_next_0109_snapshot, drop_window

        if valid_event or invalid_event:
            return
        if pending_next_0109_snapshot is None:
            return

        w = get_window(drop_window)
        if w is None:
            return  # wait until next5 is available

        ts = pending_next_0109_snapshot["timestamp"]
        soc_next = pending_next_0109_snapshot["soc"]
        vmax_next = pending_next_0109_snapshot["vmax_now"]

        soc_cond = soc_next <= 99.45
        vmax_cond = any(v < 3300 for v in w)

        if soc_cond or vmax_cond:
            if soc_cond and vmax_cond:
                reason = "Both"
            elif soc_cond:
                reason = "SoC"
            else:
                reason = "Vmax(window)"

            valid_event = {
                "Timestamp": ts,
                "SoC_At_Transition": soc_next,
                "Vmax_At_Transition_mV": vmax_next,
                "DropFrame_Timestamp": drop_window["drop_ts"] if drop_window else None,
                "Vmax_Window_mV": w,
                "Vmin_Window_mV": min(w) if w else None,
                "Reason": reason
            }
        else:
            invalid_event = {
                "Timestamp": ts,
                "SoC_At_InvalidDrop": soc_next,
                "Vmax_At_InvalidDrop_mV": vmax_next,
                "DropFrame_Timestamp": drop_window["drop_ts"] if drop_window else None,
                "Vmax_Window_mV": w,
                "Vmin_Window_mV": min(w) if w else None,
                "Reason": "FFC dropped while thresholds were NOT crossed (NEXT 0x0109, Vmax window)"
            }

        # clear pending after decision
        next_0109_pending = False
        pending_next_0109_snapshot = None
        drop_window = None

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
                index = int(idx_str[:-1]) if idx_str.endswith(")") else int(idx_str)

                timestamp = parts[1] + " " + parts[2]
                can_id = int(parts[4], 16)
                dlc = int(parts[5])
                data = [int(x, 16) for x in parts[6:6 + dlc]]
            except:
                continue

            # 0x012C - Vmax update
            if can_id == 0x012C and len(data) >= 2:
                vmax_latest = extract_vmax(data)
                vmax_hist.append(vmax_latest)

                if drop_window is not None and len(drop_window["next5"]) < 5:
                    drop_window["next5"].append(vmax_latest)
                    finalize_if_ready()
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

                # Detect DROP frame (FFC 1->0)
                if prev_ffc == 1 and ffc == 0 and drop_window is None and not (valid_event or invalid_event):
                    prev5 = vmax_hist[-5:] if len(vmax_hist) >= 5 else vmax_hist[:]
                    drop_window = {"drop_ts": timestamp, "prev5": prev5, "next5": []}
                    next_0109_pending = True
                    pending_next_0109_snapshot = None

                # Capture NEXT 0x0109 after drop
                elif next_0109_pending and pending_next_0109_snapshot is None and not (valid_event or invalid_event):
                    pending_next_0109_snapshot = {
                        "timestamp": timestamp,
                        "soc": soc,
                        "vmax_now": vmax_now
                    }
                    finalize_if_ready()

                prev_ffc = ffc

    # If NEXT 0x0109 happened but next5 Vmax never arrived => FAIL (safe)
    if (valid_event is None and invalid_event is None and pending_next_0109_snapshot is not None):
        invalid_event = {
            "Timestamp": pending_next_0109_snapshot["timestamp"],
            "SoC_At_InvalidDrop": pending_next_0109_snapshot["soc"],
            "Vmax_At_InvalidDrop_mV": pending_next_0109_snapshot["vmax_now"],
            "DropFrame_Timestamp": drop_window["drop_ts"] if drop_window else None,
            "Reason": "Insufficient Vmax samples: did not capture NEXT 5 Vmax after drop-frame"
        }

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
        summary = {"Result": "FAIL", "ValidTransition": False, **invalid_event}
    elif valid_event:
        summary = {"Result": "PASS", "ValidTransition": True, **valid_event}
    else:
        summary = {"Result": "PASS", "ValidTransition": False, "Message": "No FFC drop detected"}

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)


# ------------------------------------------------------------
# Plot (frame-by-frame; x-ticks labeled with SoC)
# ------------------------------------------------------------
def make_plot(history, valid_event, invalid_event):
    # ---- config ----
    FRAMES_BEFORE = 10          # frames before decision point to show
    FRAMES_AFTER = 40           # frames after decision point to show
    FALLBACK_MAX_FRAMES = 200   # if no event, plot last N frames
    MAX_X_TICKS = 18            # reduce label clutter
    # ----------------

    if not history:
        plt.figure(figsize=(10, 5))
        plt.title("SoC vs Vmax & FFC (Frame-by-frame window)")
        plt.xlabel("SoC (%)")
        plt.ylabel("FFC")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(PLOT_FILE)
        plt.close()
        return

    # Find decision frame index (NEXT 0x0109) if exists
    event = valid_event if valid_event else invalid_event
    event_i = None
    if event and "Timestamp" in event:
        ts = event["Timestamp"]
        for i, h in enumerate(history):
            if h["timestamp"] == ts:
                event_i = i
                break

    # Choose window by frame indices
    if event_i is not None:
        i0 = max(0, event_i - FRAMES_BEFORE)
        i1 = min(len(history), event_i + FRAMES_AFTER + 1)
        cropped = history[i0:i1]
        decision_i_local = event_i - i0
    else:
        cropped = history[-FALLBACK_MAX_FRAMES:] if len(history) > FALLBACK_MAX_FRAMES else history[:]
        decision_i_local = None

    # Frame-by-frame x positions
    x = list(range(len(cropped)))
    soc = [h["soc"] for h in cropped]
    vmax = [float("nan") if h["vmax"] is None else h["vmax"] for h in cropped]
    ffc = [h["ffc"] for h in cropped]

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.set_title("SoC vs Vmax & FFC (Frame-by-frame window)")
    ax1.set_ylabel("FFC")
    ax1.set_ylim(-0.05, 1.2)
    ax1.grid(True)

    # FFC in RED
    ax1.step(x, ffc, where="mid", label="FFC", color="tab:red", linewidth=2)

    # Vmax on right axis in BLUE
    ax2 = ax1.twinx()
    ax2.set_ylabel("Vmax (mV)")
    ax2.plot(x, vmax, label="Vmax", color="tab:blue", linewidth=2)

    # Threshold line
    ax2.axhline(3300, linestyle="--", linewidth=1.5, color="tab:gray")

    # Decision marker
    if decision_i_local is not None:
        ax1.axvline(decision_i_local, linestyle=":", linewidth=2, color="tab:green")

    # X-axis displays SoC values as tick labels
    n = len(x)
    if n <= MAX_X_TICKS:
        tick_positions = list(range(n))
    else:
        step = max(1, n // MAX_X_TICKS)
        tick_positions = list(range(0, n, step))
        if tick_positions[-1] != n - 1:
            tick_positions.append(n - 1)

    tick_labels = [f"{soc[i]:.2f}" for i in tick_positions]
    ax1.set_xticks(tick_positions)
    ax1.set_xticklabels(tick_labels, rotation=45, ha="right")
    ax1.set_xlabel("SoC (%)")

    # IMPORTANT: do NOT invert the x-axis (prevents SoC appearing reversed)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

    fig.tight_layout()
    fig.savefig(PLOT_FILE)
    plt.close(fig)


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
