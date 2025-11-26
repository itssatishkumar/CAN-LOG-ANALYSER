import re
import struct
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from datetime import datetime
import json

import matplotlib

matplotlib.use("Agg")  # non-GUI backend
import matplotlib.pyplot as plt
import numpy as np


def parse_trc_for_110(filepath):
    pattern_110 = re.compile(
        r"\s*\d+\)\s+([\d\-\s:\.]+)\s+(Rx|Tx)\s+0110\s+8\s+(.+)"
    )
    pattern_012a = re.compile(
        r"\s*\d+\)\s+([\d\-\s:\.]+)\s+(Rx|Tx)\s+012A\s+8\s+(.+)"
    )
    pattern_109 = re.compile(
        r"\s*\d+\)\s+([\d\-\s:\.]+)\s+(Rx|Tx)\s+0109\s+8\s+(.+)"
    )

    currents = []
    timestamps = []
    dlci_vals = []   # dynamicLimit_IN (positive)
    dlco_vals = []   # dynamicLimit_OUT (negated for discharge)
    dl_ts = []
    soc_vals = []
    soc_ts = []

    def parse_timestamp(ts_raw: str):
        ts_clean = ts_raw.strip().replace(".0", "")
        ts_clean = re.sub(
            r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}):(\d+)$",
            r"\1.\2",
            ts_clean,
        )

        if not re.search(r"\.\d+$", ts_clean):
            ts_clean = f"{ts_clean}.000"

        try:
            return datetime.strptime(ts_clean, "%d-%m-%Y %H:%M:%S.%f")
        except ValueError:
            return None

    with open(filepath, "r") as f:
        for line in f:
            match_110 = pattern_110.match(line)
            match_012a = pattern_012a.match(line)
            match_109 = pattern_109.match(line)

            if match_110:
                data_str = match_110.group(3).strip().split()
                if len(data_str) < 8:
                    continue

                b4, b5, b6, b7 = [int(x, 16) for x in data_str[4:8]]
                raw = struct.unpack("<i", bytes([b4, b5, b6, b7]))[0]
                current = raw * 1e-5

                currents.append(current)
                ts = parse_timestamp(match_110.group(1))
                timestamps.append(ts)

            if match_012a:
                data_str = match_012a.group(3).strip().split()
                if len(data_str) < 4:
                    continue

                b0, b1, b2, b3 = [int(x, 16) for x in data_str[0:4]]
                dlci_raw = struct.unpack("<H", bytes([b0, b1]))[0]
                dlco_raw = struct.unpack("<H", bytes([b2, b3]))[0]

                dlci = dlci_raw * 0.1  # A
                dlco = dlco_raw * 0.1  # A on bus, negate for discharge

                dlci_vals.append(dlci)
                dlco_vals.append(-dlco)
                ts = parse_timestamp(match_012a.group(1))
                dl_ts.append(ts)

            if match_109:
                data_str = match_109.group(3).strip().split()
                if len(data_str) < 2:
                    continue

                b0, b1 = [int(x, 16) for x in data_str[0:2]]
                soc_raw = struct.unpack("<H", bytes([b0, b1]))[0]
                soc = soc_raw * 0.01  # SoC scaling
                soc_vals.append(soc)
                ts = parse_timestamp(match_109.group(1))
                soc_ts.append(ts)

    return (timestamps, currents), (dl_ts, dlci_vals, dlco_vals), (soc_ts, soc_vals)


def filter_zero_streaks(ts_list, dcli_list, dclo_list, min_len=4):
    """Keep zero DCLI/DCLO samples only when part of a continuous streak of min_len."""
    filtered_ts = []
    filtered_dcli = []
    filtered_dclo = []

    n = len(ts_list)
    i = 0
    while i < n:
        is_zero = (dcli_list[i] == 0) or (dclo_list[i] == 0)
        if is_zero:
            j = i
            while j < n and ((dcli_list[j] == 0) or (dclo_list[j] == 0)):
                j += 1
            if (j - i) >= min_len:
                filtered_ts.extend(ts_list[i:j])
                filtered_dcli.extend(dcli_list[i:j])
                filtered_dclo.extend(dclo_list[i:j])
            i = j
        else:
            filtered_ts.append(ts_list[i])
            filtered_dcli.append(dcli_list[i])
            filtered_dclo.append(dclo_list[i])
            i += 1

    return filtered_ts, filtered_dcli, filtered_dclo


def select_trc_file():
    root = tk.Tk()
    root.withdraw()
    filepath = filedialog.askopenfilename(
        title="Select TRC File",
        filetypes=[("TRC Files", "*.trc"), ("All Files", "*.*")]
    )
    return filepath


def build_soc_axis(ax, soc_x, soc_vals, label="SoC (%)"):
    """Attach a secondary x-axis mapping plot x to SoC via interpolation."""
    if not soc_vals:
        return

    if len(soc_vals) == 1 or len(soc_x) == 1:
        fixed_soc = soc_vals[0]
        fixed_x = soc_x[0]

        def forward(x):
            return np.full_like(x, fixed_soc, dtype=float)

        def inverse(y):
            return np.full_like(y, fixed_x, dtype=float)
    else:
        # sort by x for forward mapping
        fx, fy = zip(*sorted(zip(soc_x, soc_vals)))
        # sort by soc for inverse mapping (best-effort if not strictly monotonic)
        bx, by = zip(*sorted(zip(soc_vals, soc_x)))

        def forward(x):
            return np.interp(x, fx, fy)

        def inverse(y):
            return np.interp(y, bx, by)

    sec_ax = ax.secondary_xaxis("bottom", functions=(forward, inverse))
    sec_ax.set_xlabel(label)
    return sec_ax


def main():
    trc_path = sys.argv[1] if len(sys.argv) > 1 else None

    if not trc_path:
        print("Select TRC file...")
        trc_path = select_trc_file()

    if not trc_path:
        print("No file selected.")
        return

    (timestamps, currents), (dl_ts, dlci_vals, dlco_vals), (soc_ts, soc_vals) = parse_trc_for_110(trc_path)
    dl_ts, dlci_vals, dlco_vals = filter_zero_streaks(dl_ts, dlci_vals, dlco_vals, min_len=4)

    if not currents:
        print("No 0x110 frames found.")
        return

    max_negative = min(currents)
    max_positive = max(currents)

    filtered = [c for c in currents if abs(c) >= 3.0]
    avg_current = sum(filtered) / len(filtered) if filtered else 0

    import matplotlib.dates as mdates

    out_dir = Path(__file__).resolve().parent

    fig, ax_curr = plt.subplots(figsize=(10, 4.5))

    valid_points = [(t, c) for t, c in zip(timestamps, currents) if t is not None]
    dl_valid = [(t, i, o) for t, i, o in zip(dl_ts, dlci_vals, dlco_vals) if t is not None]
    soc_valid = [(t, s) for t, s in zip(soc_ts, soc_vals) if t is not None]

    if valid_points:
        x_vals, y_vals = zip(*valid_points)
        pos = [(x, y) for x, y in zip(x_vals, y_vals) if y >= 0]
        neg = [(x, y) for x, y in zip(x_vals, y_vals) if y < 0]

        if pos:
            xp, yp = zip(*pos)
            ax_curr.vlines(xp, [0]*len(xp), yp, color="green", linewidth=0.9, label="Charge / Positive")

        if neg:
            xn, yn = zip(*neg)
            ax_curr.vlines(xn, [0]*len(xn), yn, color="red", linewidth=0.9, label="Discharge / Negative")

        if dl_valid:
            dl_x, dl_i, dl_o = zip(*dl_valid)
            ax_curr.step(dl_x, dl_i, where="post", color="blue", linewidth=1.1, label="DCLI (limit IN)")
            ax_curr.step(dl_x, dl_o, where="post", color="orange", linewidth=1.1, label="DCLO (limit OUT)")

        ax_curr.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate()

    else:
        x_vals = list(range(1, len(currents) + 1))
        pos = [(x, y) for x, y in zip(x_vals, currents) if y >= 0]
        neg = [(x, y) for x, y in zip(x_vals, currents) if y < 0]

        if pos:
            xp, yp = zip(*pos)
            ax_curr.vlines(xp, [0]*len(xp), yp, color="green", linewidth=0.9)

        if neg:
            xn, yn = zip(*neg)
            ax_curr.vlines(xn, [0]*len(xn), yn, color="red", linewidth=0.9)

        if dl_valid:
            dl_x, dl_i, dl_o = zip(*dl_valid)
            ax_curr.step(dl_x, dl_i, where="post", color="blue", linewidth=1.1, label="DCLI (limit IN)")
            ax_curr.step(dl_x, dl_o, where="post", color="orange", linewidth=1.1, label="DCLO (limit OUT, negated)")

        ax_curr.set_xlabel("Sample #")

    ax_curr.set_title("DCLI / DCLO Map - Current Profile")

    if (pos and neg) or dl_valid:
        ax_curr.legend(loc="upper right")

    ax_curr.set_ylabel("Current (A)")
    ax_curr.grid(True, linestyle="--", alpha=0.5)

    # Attach SoC as secondary bottom x-axis when available
    if soc_valid:
        soc_x, soc_y = zip(*soc_valid)
        soc_x_num = mdates.date2num(soc_x)
        build_soc_axis(ax_curr, soc_x_num, soc_y)
    elif soc_vals:
        build_soc_axis(ax_curr, list(range(1, len(soc_vals) + 1)), soc_vals)

    ax_curr.set_xlabel("Time" if valid_points else "Sample #")
    fig.tight_layout()

    plot_path = out_dir / "DCLI_DCLO_Map_plot.png"
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)

    summary_path = out_dir / "DCLI_DCLO_Map_summary.json"

    summary_table = {
        "Max Discharge (Most Negative) [A]": f"{max_negative:.2f}",
        "Max Charge/Regen (Most Positive) [A]": f"{max_positive:.2f}",
        "Average Current (|I| >= 3A) [A]": f"{avg_current:.2f}"
    }

    summary_payload = {"Summary_Table": summary_table}
    summary_path.write_text(json.dumps(summary_payload, indent=4), encoding="utf-8")

    result_path = out_dir / "DCLI_DCLO_Map_results.json"
    result_status = "PASS" if plot_path.exists() and summary_path.exists() else "FAIL"
    result_path.write_text(json.dumps({"Result": result_status}), encoding="utf-8")


if __name__ == "__main__":
    main()
