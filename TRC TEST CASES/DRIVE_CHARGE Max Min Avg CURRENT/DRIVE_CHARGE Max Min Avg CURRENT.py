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


def parse_trc_for_110(filepath):
    pattern = re.compile(
        r"\s*\d+\)\s+([\d\-\s:\.]+)\s+(Rx|Tx)\s+0110\s+8\s+(.+)"
    )

    currents = []
    timestamps = []

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
            match = pattern.match(line)
            if match:
                data_str = match.group(3).strip().split()
                if len(data_str) < 8:
                    continue

                b4, b5, b6, b7 = [int(x, 16) for x in data_str[4:8]]
                raw = struct.unpack("<i", bytes([b4, b5, b6, b7]))[0]
                current = raw * 1e-5

                currents.append(current)
                ts = parse_timestamp(match.group(1))
                timestamps.append(ts)

    return timestamps, currents


def select_trc_file():
    root = tk.Tk()
    root.withdraw()
    filepath = filedialog.askopenfilename(
        title="Select TRC File",
        filetypes=[("TRC Files", "*.trc"), ("All Files", "*.*")]
    )
    return filepath


def main():
    trc_path = sys.argv[1] if len(sys.argv) > 1 else None

    if not trc_path:
        print("Select TRC file...")
        trc_path = select_trc_file()

    if not trc_path:
        print("No file selected.")
        return

    timestamps, currents = parse_trc_for_110(trc_path)

    if not currents:
        print("No 0x110 frames found.")
        return

    max_negative = min(currents)
    max_positive = max(currents)

    filtered = [c for c in currents if abs(c) >= 3.0]
    avg_current = sum(filtered) / len(filtered) if filtered else 0

    import matplotlib.dates as mdates

    out_dir = Path(__file__).resolve().parent

    plt.figure(figsize=(10, 4))
    valid_points = [(t, c) for t, c in zip(timestamps, currents) if t is not None]

    if valid_points:
        x_vals, y_vals = zip(*valid_points)
        pos = [(x, y) for x, y in zip(x_vals, y_vals) if y >= 0]
        neg = [(x, y) for x, y in zip(x_vals, y_vals) if y < 0]

        if pos:
            xp, yp = zip(*pos)
            plt.vlines(xp, [0]*len(xp), yp, color="green", linewidth=0.9, label="Charge / Positive")

        if neg:
            xn, yn = zip(*neg)
            plt.vlines(xn, [0]*len(xn), yn, color="red", linewidth=0.9, label="Discharge / Negative")

        plt.xlabel("Time")
        ax = plt.gca()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        plt.gcf().autofmt_xdate()

    else:
        x_vals = list(range(1, len(currents) + 1))
        pos = [(x, y) for x, y in zip(x_vals, currents) if y >= 0]
        neg = [(x, y) for x, y in zip(x_vals, currents) if y < 0]

        if pos:
            xp, yp = zip(*pos)
            plt.vlines(xp, [0]*len(xp), yp, color="green", linewidth=0.9)

        if neg:
            xn, yn = zip(*neg)
            plt.vlines(xn, [0]*len(xn), yn, color="red", linewidth=0.9)

        plt.xlabel("Sample #")

    plt.title("Current Profile")

    if pos and neg:
        plt.legend(loc="best")

    plt.ylabel("Current (A)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()

    plot_path = out_dir / "Drive_Charge_Max_Min_Avg_Current_plot.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()

    summary_path = out_dir / "Drive_Charge_Max_Min_Avg_Current_summary.json"

    summary_table = {
        "Max Discharge (Most Negative) [A]": f"{max_negative:.2f}",
        "Max Charge/Regen (Most Positive) [A]": f"{max_positive:.2f}",
        "Average Current (|I| >= 3A) [A]": f"{avg_current:.2f}"
    }

    summary_payload = {"Summary_Table": summary_table}
    summary_path.write_text(json.dumps(summary_payload, indent=4), encoding="utf-8")

    result_path = out_dir / "Drive_Charge_Max_Min_Avg_Current_results.json"
    result_status = "PASS" if plot_path.exists() and summary_path.exists() else "FAIL"
    result_path.write_text(json.dumps({"Result": result_status}), encoding="utf-8")


if __name__ == "__main__":
    main()
