"""
Equivalent Cycle Count evaluator for CAN ID 0x012B.

Rules:
- Cycle value = data[6] + (data[7] << 8) (little-endian, last two bytes).
- If a new value is >= previous valid, accept immediately.
- If a new value is lower, accept only after it appears in at least 10 consecutive readings.
- Outputs:
    * Equivalent_cycle_count_results.json  (raw + valid per sample)
    * Equivalent_cycle_count_summary.json  (initial, final, difference, verdict)
    * Equivalent_cycle_count_plot.png      (valid cycle count vs sample index)

Run with a TRC file path (preferred) or without arguments to use a built-in demo list.
Only standard Python + matplotlib + json are used.
"""

import json
import os
import re
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import matplotlib

matplotlib.use("Agg")  # non-GUI backend
import matplotlib.pyplot as plt


RESULT_FILE = "Equivalent_cycle_count_results.json"
SUMMARY_FILE = "Equivalent_cycle_count_summary.json"
PLOT_FILE = "Equivalent_cycle_count_plot.png"


class CycleCounter:
    """Manages cycle count filtering with drop validation."""

    def __init__(self, consecutive_required: int = 10):
        self.consecutive_required = consecutive_required
        self.last_valid = None
        self.drop_candidate = None
        self.drop_count = 0

    def process(self, raw_value: int) -> int:
        """
        Process a raw cycle value and return the current valid value after applying rules.
        - Accept increases or equal values immediately.
        - For decreases, require the lower value to repeat consecutively before accepting.
        """
        if self.last_valid is None:
            self.last_valid = raw_value
            self.drop_candidate = None
            self.drop_count = 0
            return self.last_valid

        # Non-decreasing path: accept immediately and reset any pending drop
        if raw_value >= self.last_valid:
            self.last_valid = raw_value
            self.drop_candidate = None
            self.drop_count = 0
            return self.last_valid

        # Decreasing path: track consecutive lower readings
        if self.drop_candidate is None or raw_value != self.drop_candidate:
            self.drop_candidate = raw_value
            self.drop_count = 1
        else:
            self.drop_count += 1

        if self.drop_count >= self.consecutive_required:
            self.last_valid = self.drop_candidate
            self.drop_candidate = None
            self.drop_count = 0

        return self.last_valid


def parse_trc_cycles(trc_path: str):
    """
    Parse TRC file for CAN ID 0x012B and extract raw cycle counts (last two bytes, little-endian).
    Returns a list of integers in the order they appear.
    """
    pattern_012b = re.compile(
        r"\s*\d+\)\s+[\d\-\s:\.]+\s+(Rx|Tx)\s+012B\s+8\s+(.+)"
    )

    cycles = []

    with open(trc_path, "r", errors="ignore") as f:
        for line in f:
            match = pattern_012b.match(line)
            if not match:
                continue

            data_str = match.group(2).strip().split()
            if len(data_str) < 8:
                continue

            try:
                bytes_ = [int(x, 16) for x in data_str[:8]]
            except ValueError:
                continue

            cycle = bytes_[6] + (bytes_[7] << 8)
            cycles.append(cycle)

    return cycles


def run_cycle_logic(raw_cycles):
    """Apply filtering rules to raw cycles and return result records and valid series."""
    cc = CycleCounter(consecutive_required=10)
    results = []
    valid_series = []

    for raw in raw_cycles:
        valid = cc.process(raw)
        valid_series.append(valid)
        results.append({"raw_value": raw, "valid_value": valid})

    return results, valid_series


def save_results_json(verdict):
    """Persist only the overall verdict for this check (GUI expects 'Result')."""
    output = {"Result": verdict}
    with open(RESULT_FILE, "w") as f:
        json.dump(output, f, indent=2)


def build_summary(valid_series):
    if not valid_series:
        return {
            "initial_cycle": None,
            "final_cycle": None,
            "difference": None,
            "verdict": "FAIL",
            "RESULT": "FAIL",
        }

    initial = valid_series[0]
    final = valid_series[-1]
    diff = final - initial
    verdict = "PASS" if final >= initial else "FAIL"
    return {
        "initial_cycle": initial,
        "final_cycle": final,
        "difference": diff,
        "verdict": verdict,
        "Result": verdict,
    }


def save_summary_json(summary):
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)


def make_plot(valid_series):
    if not valid_series:
        return

    x_vals = list(range(1, len(valid_series) + 1))

    plt.figure(figsize=(9, 4))
    plt.plot(x_vals, valid_series, color="blue", linewidth=1.4, label="Valid Cycle Count")
    plt.xlabel("Sample Index")
    plt.ylabel("Cycle Count")
    plt.title("Equivalent Cycle Count (Filtered)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(PLOT_FILE, dpi=150)
    plt.close()


def demo_values():
    """
    Provide a demo sequence showing increases and a drop that only becomes valid
    after 10 consecutive lower readings.
    """
    return [
        100, 101, 102, 103, 104, 105, 106,  # increasing
        90, 90, 90, 90, 90, 90, 90, 90, 90, 90,  # 10 consecutive lower -> accept
        91, 92, 92, 91, 91, 91, 91, 91, 91, 91, 91, 91, 91,  # lower than 92; 10x at 91 to accept
        93, 94, 95,
    ]


def main():
    """
    If a TRC path is provided, parse 0x012B frames; otherwise run on demo data.
    Generates JSON outputs and a plot in the current folder.
    """
    script_dir = Path(__file__).resolve().parent
    os.chdir(script_dir)  # ensure outputs land alongside the script

    trc_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not trc_path:
        # GUI browse fallback to align with other TRC scripts
        root = tk.Tk()
        root.withdraw()
        trc_path = filedialog.askopenfilename(
            title="Select TRC File",
            filetypes=[("TRC Files", "*.trc"), ("All Files", "*.*")],
        )

    if trc_path:
        if not os.path.exists(trc_path):
            print(f"ERROR: TRC file not found: {trc_path}")
            sys.exit(1)
        raw_cycles = parse_trc_cycles(trc_path)
        if not raw_cycles:
            print("ERROR: No 0x012B frames found in TRC.")
            sys.exit(1)
        print(f"Parsed {len(raw_cycles)} cycle readings from TRC.")
    else:
        raw_cycles = demo_values()
        print("No TRC provided/selected. Running demo sequence.")

    results, valid_series = run_cycle_logic(raw_cycles)
    summary = build_summary(valid_series)
    save_results_json(summary["Result"])
    save_summary_json(summary)
    make_plot(valid_series)

    summary = {
        "initial": valid_series[0] if valid_series else None,
        "final": valid_series[-1] if valid_series else None,
        "difference": (valid_series[-1] - valid_series[0]) if len(valid_series) >= 1 else None,
    }
    print(f"Done. Summary: {summary}")
    print(f"Outputs: {RESULT_FILE}, {SUMMARY_FILE}, {PLOT_FILE}")


if __name__ == "__main__":
    main()
