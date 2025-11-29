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
            r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}):(\d{3,4})$",
            r"\1.\2",
            ts_clean,
        )

        if not re.search(r"\.\d+$", ts_clean):
            ts_clean = f"{ts_clean}.000"

        if re.search(r"\.(\d+)$", ts_clean):
            base, ms = ts_clean.rsplit(".", 1)
            if len(ms) == 3:
                ts_clean = f"{base}.{ms}0"
            elif len(ms) > 4:
                ts_clean = f"{base}.{ms[:4]}"

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
    stem_primary = "Drive_Charge_Max_Min_Avg_Current"  # matches file_name.json entries
    stem_launcher = Path(__file__).stem  # current script stem (with underscores)
    stem_with_spaces = "DRIVE_CHARGE Max Min Avg CURRENT"  # legacy spaced naming

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

    plot_path = out_dir / f"{stem_primary}_plot.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()

    summary_path = out_dir / f"{stem_primary}_summary.json"

    # GUI expects numeric values, not strings
    summary_table = {
        "Max Discharge (Most Negative) [A]": round(max_negative, 2),
        "Max Charge/Regen (Most Positive) [A]": round(max_positive, 2),
        "Average Current (|I| >= 3A) [A]": round(avg_current, 2)
    }

    summary_payload = {"Summary_Table": summary_table}
    summary_text = json.dumps(summary_payload, indent=4)
    summary_path.write_text(summary_text, encoding="utf-8")

    result_path = out_dir / f"{stem_primary}_results.json"
    result_status = "PASS" if plot_path.exists() and summary_path.exists() else "FAIL"
    result_text = json.dumps({"Result": result_status})
    result_path.write_text(result_text, encoding="utf-8")

    # Also produce copies that match the script stem (launcher defaults) and the legacy spaced names.
    fallback_plot = out_dir / f"{stem_launcher}_plot.png"
    fallback_summary = out_dir / f"{stem_launcher}_summary.json"
    fallback_result = out_dir / f"{stem_launcher}_results.json"
    legacy_plot = out_dir / f"{stem_with_spaces}_plot.png"
    legacy_summary = out_dir / f"{stem_with_spaces}_summary.json"
    legacy_result = out_dir / f"{stem_with_spaces}_results.json"

    for target, writer in [
        (fallback_plot, lambda: fallback_plot.write_bytes(plot_path.read_bytes())),
        (fallback_summary, lambda: fallback_summary.write_text(summary_text, encoding="utf-8")),
        (fallback_result, lambda: fallback_result.write_text(result_text, encoding="utf-8")),
        (legacy_plot, lambda: legacy_plot.write_bytes(plot_path.read_bytes())),
        (legacy_summary, lambda: legacy_summary.write_text(summary_text, encoding="utf-8")),
        (legacy_result, lambda: legacy_result.write_text(result_text, encoding="utf-8")),
    ]:
        if target != plot_path and target != summary_path and target != result_path:
            try:
                writer()
            except Exception:
                pass

    if fallback_summary != summary_path:
        try:
            fallback_summary.write_text(summary_text, encoding="utf-8")
        except Exception:
            pass

    if fallback_result != result_path:
        try:
            fallback_result.write_text(result_text, encoding="utf-8")
        except Exception:
            pass



if __name__ == "__main__":
    main()
