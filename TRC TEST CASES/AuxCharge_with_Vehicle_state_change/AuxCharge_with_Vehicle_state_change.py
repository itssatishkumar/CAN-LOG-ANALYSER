#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# avoid writing __pycache__ when running the script
sys.dont_write_bytecode = True
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))
from trc_utils import progress_by_bytes


# =====================================================
# OUTPUT CONFIGURATION
# =====================================================
SCRIPT_DIR = Path(__file__).resolve().parent

OUTPUTS = {
    "AUXCHARGE WITH VEHICLE STATE CHANGE": {
        "result": "AuxCharge_with_Vehicle_state_change_results.json",
        "summary": "AuxCharge_with_Vehicle_state_change_summary.json",
        "graph": "AuxCharge_with_Vehicle_state_change_plot.png",
    }
}

# Plot downsampling (every Nth 0x0109 frame). Set to 1 for full resolution (slower).
PLOT_SAMPLE_EVERY = 20
PROGRESS_STEP = 0.5  # report every 0.5%

# =====================================================
# THRESHOLDS
# =====================================================
THRESH_BETWEEN_3_TO_3 = 12.5   # PASS CONDITION 12.5V (between 0109(3->3) intervals)
THRESH_OVERALL = 11.0         # PASS condition 11.0 (lowest aux overall)

# =====================================================
# CAN / SIGNAL DEFINITIONS 
# =====================================================
BMS_CAN_ID = 0x0109
SOC_SF = 0.01                     # SoC bytes 0-1 Intel, sf 0.01
BMS_STATE_BYTE = 4                # byte 4

AUXV_CAN_ID = 0x0606
AUXV_SF = 0.01                    # AuxVoltage (0.01,0)
AUXV_MSB_IDX = 1                  # AuxVoltage MSB at byte 1 (bytes 1-2 big-endian)
MIN_VALID_AUX = 1.0               # ignore Aux readings below this unless BMS state is 3

# =====================================================
# TRC REGEX
# =====================================================
TRC_PATTERN = re.compile(
    r"^\s*\d+\)\s+"
    r"(?P<date>\d{2}-\d{2}-\d{4})\s+"
    r"(?P<hms>\d{2}:\d{2}:\d{2})\.(?P<frac>\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"(?P<canid>[0-9A-Fa-f]+)\s+(?P<dlc>\d+)\s+(?P<data>(?:[0-9A-Fa-f]{2}\s*)+)$"
)


def u16_le(b0: int, b1: int) -> int:
    return b0 | (b1 << 8)


def parse_trc_line(line: str):
    """
    Returns: (timestamp: datetime, canid_int: int, dlc: int, data_bytes: list[int]) or None
    Time frac:
      - 3 digits => ms
      - 4 digits => 0.1ms ticks
    """
    m = TRC_PATTERN.match(line)
    if not m:
        return None

    date = m.group("date")  # DD-MM-YYYY
    hms = m.group("hms")
    frac = m.group("frac")

    canid = int(m.group("canid"), 16)
    dlc = int(m.group("dlc"))

    micro = int(frac) * (1000 if len(frac) == 3 else 100)
    ts = datetime.strptime(f"{date} {hms}", "%d-%m-%Y %H:%M:%S").replace(microsecond=micro)

    data = [int(x, 16) for x in m.group("data").split()]
    if len(data) < dlc:
        return None
    return ts, canid, dlc, data[:dlc]


def decode_0606_auxv(data: list[int]) -> float:
    # bytes 1..2 big-endian, scaled 0.01
    raw = (data[AUXV_MSB_IDX] << 8) | data[AUXV_MSB_IDX + 1]
    return raw * AUXV_SF


# =====================================================
# TRC PICKER: GUI ARG or Tkinter browse fallback
# =====================================================
def get_trc_path_from_gui_or_browse() -> str:
    # GUI arg
    if len(sys.argv) >= 2 and sys.argv[1] and os.path.exists(sys.argv[1]):
        return sys.argv[1]

    # Tkinter browse
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        print("ERROR: No TRC argument provided and tkinter is not available.")
        print("Reason:", e)
        sys.exit(1)

    root = tk.Tk()
    root.withdraw()
    root.update()

    path = filedialog.askopenfilename(
        title="Select TRC file",
        filetypes=[("TRC files", "*.trc"), ("All files", "*.*")]
    )

    root.update()
    root.destroy()

    if not path:
        print("ERROR: No TRC file selected.")
        sys.exit(1)
    if not os.path.exists(path):
        print(f"ERROR: TRC file not found: {path}")
        sys.exit(1)

    return path


# =====================================================
# SINGLE-PASS PROCESSING WITH LIGHTWEIGHT PLOT DATA
# =====================================================
def process_trc(
    trc_path: str,
    plot_sample_every: int = PLOT_SAMPLE_EVERY,
    progress_cb: Optional[Callable[[int], None]] = None,
):
    """
    Single pass over the TRC to compute:
      - min Aux between consecutive 0109 state 3 -> 3
      - min Aux overall
      - downsampled rows for plotting (SoC, BMS state, pack V, last Aux)
    """
    best_between_val = None
    best_between_ts = None
    best_all_val = None
    best_all_ts = None

    prev_0109_ts = None
    prev_bms_state = None
    aux_between = []
    last_aux = None

    bms_plot_rows = []
    bms_seen = 0

    with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
        for line_idx, line in enumerate(f, 1):
            p = parse_trc_line(line)
            if not p:
                continue
            ts, canid, dlc, data = p
            if progress_cb:
                progress_cb(len(line))

            if canid == AUXV_CAN_ID and dlc >= AUXV_MSB_IDX + 2:
                aux_v = decode_0606_auxv(data)
                # discard Aux <1V unless current BMS state is known to be 3
                is_valid_aux = (aux_v >= MIN_VALID_AUX) or (prev_bms_state == 3)
                if not is_valid_aux:
                    continue

                last_aux = aux_v

                if best_all_val is None or aux_v < best_all_val:
                    best_all_val, best_all_ts = aux_v, ts

                if prev_0109_ts is not None:
                    aux_between.append((ts, aux_v))
                continue

            if canid == BMS_CAN_ID and dlc >= 8:
                soc = u16_le(data[0], data[1]) * SOC_SF
                bms_state = int(data[BMS_STATE_BYTE])

                if prev_0109_ts is not None and prev_bms_state == 3 and bms_state == 3:
                    if aux_between:
                        tmin, vmin = min(aux_between, key=lambda tv: tv[1])
                        if best_between_val is None or vmin < best_between_val:
                            best_between_val, best_between_ts = vmin, tmin

                aux_between = []
                prev_0109_ts = ts
                prev_bms_state = bms_state

                if plot_sample_every > 0 and bms_seen % plot_sample_every == 0:
                    bms_plot_rows.append({
                        "SoC": soc,
                        "BMS_State": bms_state,
                        "AuxVoltage_V": last_aux,
                    })

                bms_seen += 1

    return (best_between_val, best_between_ts), (best_all_val, best_all_ts), bms_plot_rows, best_all_val


def build_plot_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["SoC", "BMS_State", "AuxVoltage_V"])

    df = pd.DataFrame(rows)
    df["SoC"] = pd.to_numeric(df.get("SoC"), errors="coerce")
    df["BMS_State"] = pd.to_numeric(df.get("BMS_State"), errors="coerce")
    df["AuxVoltage_V"] = pd.to_numeric(df.get("AuxVoltage_V"), errors="coerce")

    # keep TRC/frame order (already in time order from build_plot_df)
    df = df.dropna(subset=["SoC"]).reset_index(drop=True)
    return df


# =====================================================
# PLOT: single LEFT axis split into bottom(BMS 0..5) and top(Aux 0..15)
# PackVoltage drawn in TOP band (scaled to fit that band for display).
# =====================================================
def save_plot_split_left_axis(df: pd.DataFrame, out_path: str):
    if df.empty:
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.axis("off")
        ax.text(0.5, 0.5, "No data to plot", ha="center", va="center")
        plt.savefig(out_path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        return

    d = df.copy()
    d["SoC"] = pd.to_numeric(d.get("SoC"), errors="coerce")
    d["BMS_State"] = pd.to_numeric(d.get("BMS_State"), errors="coerce")
    d["AuxVoltage_V"] = pd.to_numeric(d.get("AuxVoltage_V"), errors="coerce")

    # keep TRC/frame order (already time ordered from build_plot_df)
    d = d.dropna(subset=["SoC"]).reset_index(drop=True)
    x = np.arange(len(d))  # frame order
    soc_vals = d["SoC"].to_numpy()

    aux = d["AuxVoltage_V"]
    bms = d["BMS_State"].clip(lower=0, upper=5)
    aux_valid = aux.dropna()

    # Focus display range: default 8-15V, tighten to +/-1V around flat data
    aux_lo_val, aux_hi_val = 8.0, 15.0
    if not aux_valid.empty:
        data_min = float(aux_valid.min())
        data_max = float(aux_valid.max())
        if data_max - data_min < 2.0:
            center = 0.5 * (data_min + data_max)
            aux_lo_val = max(8.0, center - 1.0)
            aux_hi_val = min(15.0, center + 1.0)
        else:
            aux_lo_val = max(8.0, data_min)
            aux_hi_val = min(15.0, data_max)

        if aux_hi_val - aux_lo_val < 0.5:  # avoid zero/near-zero span
            aux_hi_val = aux_lo_val + 0.5

    # bands on a single axis 0..1
    bms_lo, bms_hi = 0.00, 0.35
    aux_lo, aux_hi = 0.55, 1.00

    # Map BMS 0..5 to bottom band
    bms_y = bms_lo + (bms / 5.0) * (bms_hi - bms_lo)

    # Map Aux scaled into top band using focused range
    aux_span = aux_hi_val - aux_lo_val
    aux_clipped = aux.clip(lower=aux_lo_val, upper=aux_hi_val)
    aux_y = np.where(
        aux.notna(),
        aux_lo + ((aux_clipped - aux_lo_val) / aux_span) * (aux_hi - aux_lo),
        np.nan,
    )

    fig, ax = plt.subplots(figsize=(14, 6))

    ax.plot(x, aux_y, linewidth=1.4, label="Aux Voltage V", color="#1f77b4")
    ax.step(x, bms_y, where="post", linewidth=1.2, label="BMS State", color="#ff7f0e")

    # X ticks show SoC values in frame order (categorical-like)
    if len(x) > 0:
        tick_idx = np.linspace(0, len(x) - 1, num=min(20, len(x)), dtype=int)
        ax.set_xticks(tick_idx)
        ax.set_xticklabels([f"{soc_vals[i]:.2f}" for i in tick_idx], rotation=45, ha="right")

    ax.set_xlabel("State of Charge, SoC (%)")
    ax.set_ylim(0, 1)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)

    # Separation line between bands (visual)
    ax.axhline((bms_hi + aux_lo) / 2.0, linewidth=1.0, color="gray", alpha=0.7)

    # Ticks: bottom band 0..5, top band scaled to aux range
    bms_ticks = list(range(0, 6))
    bms_tick_pos = [bms_lo + (t / 5.0) * (bms_hi - bms_lo) for t in bms_ticks]

    aux_ticks = [aux_lo_val, (aux_lo_val + aux_hi_val) / 2.0, aux_hi_val]
    aux_tick_pos = [
        aux_lo + ((t - aux_lo_val) / aux_span) * (aux_hi - aux_lo)
        for t in aux_ticks
    ]

    ax.set_yticks(bms_tick_pos + aux_tick_pos)
    ax.set_yticklabels([str(t) for t in bms_ticks] + [f"{t:.2f}" for t in aux_ticks])

    # Band labels on left side
    ax.text(0.01, (bms_lo + bms_hi) / 2.0, "BMS", transform=ax.transAxes, va="center")
    ax.text(0.01, (aux_lo + aux_hi) / 2.0, "AUX", transform=ax.transAxes, va="center")

    ax.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def overall_result(min_between, min_all) -> str:
    # PASS only if both conditions pass; if any missing -> FAIL (no extra rule added)
    if min_between is None or min_all is None:
        return "FAIL"
    if (min_between >= THRESH_BETWEEN_3_TO_3) and (min_all >= THRESH_OVERALL):
        return "PASS"
    return "FAIL"


def save_outputs(result: str, summary_text: str, plot_df: pd.DataFrame):
    cfg = OUTPUTS["AUXCHARGE WITH VEHICLE STATE CHANGE"]
    result_path = SCRIPT_DIR / cfg["result"]
    summary_path = SCRIPT_DIR / cfg["summary"]
    graph_path = SCRIPT_DIR / cfg["graph"]

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"Result": result}, f, indent=2)

    # store summary as list for readable multi-line JSON
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"Summary": summary_text.split("\n")}, f, indent=2)

    save_plot_split_left_axis(plot_df, str(graph_path))

    return str(result_path), str(summary_path), str(graph_path)

def main():
    trc_path = get_trc_path_from_gui_or_browse()
    print(f"Using TRC file: {trc_path}")
    print(f"Outputs will be saved next to script: {SCRIPT_DIR}")

    progress_cb = progress_by_bytes(trc_path, step=PROGRESS_STEP)

    (min_between, ts_between), (min_all, ts_all), plot_rows, _ = process_trc(
        trc_path,
        PLOT_SAMPLE_EVERY,
        progress_cb=progress_cb,
    )
    plot_df = build_plot_df(plot_rows)

    # ===== Aux Voltage TXT OUTPUT =====
    p = Path(__file__).resolve()

    for parent in [p] + list(p.parents):
        history = parent / "History"
        if history.exists() and history.is_dir():

            aux_series = plot_df["AuxVoltage_V"].dropna()
            aux_max = aux_series.max() if not aux_series.empty else 0

            # Use true minimum
            if min_all is not None and min_all > 0:
                aux_min = min_all
            else:
                aux_min = 0

            # Correct count from FULL data
            count = 0
            if min_all is not None and min_all > 0:
                with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        p_line = parse_trc_line(line)
                        if not p_line:
                            continue
                        _, canid, dlc, data = p_line
                        if canid == AUXV_CAN_ID and dlc >= AUXV_MSB_IDX + 2:
                            v = decode_0606_auxv(data)
                            if v > 0 and round(v, 2) == round(min_all, 2):
                                count += 1

            if min_all is not None:
                text = (
                    f"Aux Voltage Range : {aux_min:.2f}V to {aux_max:.2f}V\n"
                    f"Lowest Aux Voltage : {min_all:.2f}V ({count} count)"
                )
            else:
                text = "Aux Voltage Range : N/A\nLowest Aux Voltage : N/A"

            file = history / "Aux_voltage.txt"
            with open(file, "w", encoding="utf-8") as f:
                f.write(text)
            break

    if min_between is None:
        line1 = f"Min AuxVoltage between 0109(3->3) is N/A, Timestamp: N/A (PASS CONDITION {THRESH_BETWEEN_3_TO_3}V)"
    else:
        line1 = f"Min AuxVoltage between 0109(3->3) is {min_between:.2f}V, Timestamp: {ts_between} (PASS CONDITION {THRESH_BETWEEN_3_TO_3}V)"

    if min_all is None:
        line2 = f"Lowest Aux voltage of all record: N/A V, Timestamp: N/A (PASS condition {THRESH_OVERALL})"
    else:
        line2 = f"Lowest Aux voltage of all record: {min_all:.2f} V, Timestamp: {ts_all} (PASS condition {THRESH_OVERALL})"

    summary_text = line1 + "\n\n" + line2
    result = overall_result(min_between, min_all)

    result_path, summary_path, graph_path = save_outputs(result, summary_text, plot_df)
    print("PROGRESS 100.0", flush=True)

    print("Done.")
    print("Result JSON :", result_path)
    print("Summary JSON:", summary_path)
    print("Graph PNG   :", graph_path)
    print("\n--- Summary ---\n" + summary_text)


if __name__ == "__main__":
    main()
