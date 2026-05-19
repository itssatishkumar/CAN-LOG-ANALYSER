import json
import os
import re
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from trc_utils import progress_by_bytes

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


RESULT_FILE = "Equivalent_cycle_count_results.json"
SUMMARY_FILE = "Equivalent_cycle_count_summary.json"
PLOT_FILE = "Equivalent_cycle_count_plot.png"
PROGRESS_STEP = 0.5


class CycleCounter:

    def __init__(self, consecutive_required: int = 10):
        self.consecutive_required = consecutive_required
        self.last_valid = None
        self.drop_candidate = None
        self.drop_count = 0

    def process(self, raw_value: int):

        if self.last_valid is None:
            self.last_valid = raw_value
            return self.last_valid

        if raw_value >= self.last_valid:
            self.last_valid = raw_value
            self.drop_candidate = None
            self.drop_count = 0
            return self.last_valid

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


def parse_trc_cycles(trc_path: str, progress_cb=None):

    pattern_0109 = re.compile(
        r"\s*\d+\)\s+[\d\-:\. ]+\s+(Rx|Tx)\s+0109\s+8\s+(.+)"
    )

    pattern_012b = re.compile(
        r"\s*\d+\)\s+[\d\-:\. ]+\s+(Rx|Tx)\s+012B\s+8\s+(.+)"
    )

    cycles = []
    bms_state = None

    with open(trc_path, "r", errors="ignore") as f:

        for line in f:

            if progress_cb:
                progress_cb(len(line))

            # ---- BMS STATE FRAME (0109) ----
            match_0109 = pattern_0109.match(line)

            if match_0109:

                data_str = match_0109.group(2).strip().split()

                if len(data_str) >= 5:
                    try:
                        bytes_ = [int(x, 16) for x in data_str[:8]]

                        # SG_ BMS_State : 32|8 → byte index 4
                        bms_state = bytes_[4]

                    except ValueError:
                        pass

                continue

            # ---- CYCLE COUNT FRAME (012B) ----
            match_012b = pattern_012b.match(line)

            if not match_012b:
                continue

            data_str = match_012b.group(2).strip().split()

            if len(data_str) < 8:
                continue

            try:
                bytes_ = [int(x, 16) for x in data_str[:8]]
            except ValueError:
                continue

            cycle = bytes_[6] + (bytes_[7] << 8)

            # Accept cycle only when BMS_State != 0
            if bms_state is not None and bms_state != 0:
                cycles.append(cycle)

    return cycles


def run_cycle_logic(raw_cycles):

    cc = CycleCounter(consecutive_required=10)

    results = []
    valid_series = []

    for raw in raw_cycles:

        valid = cc.process(raw)

        valid_series.append(valid)

        results.append({
            "raw_value": raw,
            "valid_value": valid
        })

    return results, valid_series


def save_results_json(verdict):

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
            "Result": "FAIL"
        }

    initial = valid_series[0]
    final = valid_series[-1]

    verdict = "PASS"

    for i in range(1, len(valid_series)):

        delta = valid_series[i] - valid_series[i - 1]

        if delta > 1:
            verdict = "FAIL"
            break

    return {
        "initial_cycle": initial,
        "final_cycle": final,
        "difference": final - initial,
        "verdict": verdict,
        "Result": verdict
    }


def save_summary_json(summary):

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)

def save_txt(cycle_count):

    p = Path(__file__).resolve()

    for parent in [p] + list(p.parents):

        history = parent / "History"

        if history.exists() and history.is_dir():

            file = history / "cycle_count.txt"

            with open(file, "w", encoding="utf-8") as f:
                f.write(f"Cycle Count: {cycle_count}")

            return        


def make_plot(valid_series):

    if not valid_series:
        return

    x_vals = list(range(1, len(valid_series) + 1))

    plt.figure(figsize=(9, 4))

    plt.plot(
        x_vals,
        valid_series,
        color="blue",
        linewidth=1.4,
        label="Valid Cycle Count"
    )

    plt.xlabel("Sample Index")
    plt.ylabel("Cycle Count")
    plt.title("Equivalent Cycle Count (Filtered)")

    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(loc="best")

    plt.tight_layout()
    plt.savefig(PLOT_FILE, dpi=150)

    plt.close()


def main():

    script_dir = Path(__file__).resolve().parent
    os.chdir(script_dir)

    trc_path = sys.argv[1] if len(sys.argv) > 1 else None

    if not trc_path:

        root = tk.Tk()
        root.withdraw()

        trc_path = filedialog.askopenfilename(
            title="Select TRC File",
            filetypes=[("TRC Files", "*.trc"), ("All Files", "*.*")]
        )

    if not trc_path:
        print("ERROR: No TRC file selected.")
        sys.exit(1)

    if not os.path.exists(trc_path):
        print(f"ERROR: TRC file not found: {trc_path}")
        sys.exit(1)

    progress_cb = progress_by_bytes(trc_path, step=PROGRESS_STEP)

    raw_cycles = parse_trc_cycles(trc_path, progress_cb=progress_cb)

    if not raw_cycles:
        print("ERROR: No valid 0x012B frames found in TRC.")
        sys.exit(1)

    print(f"Parsed {len(raw_cycles)} valid cycle readings.")

    results, valid_series = run_cycle_logic(raw_cycles)

    summary = build_summary(valid_series)

    save_results_json(summary["Result"])
    save_summary_json(summary)
    save_txt(summary["final_cycle"])

    make_plot(valid_series)

    print(f"Done. Summary: {summary}")
    print(f"Outputs: {RESULT_FILE}, {SUMMARY_FILE}, {PLOT_FILE}")
    print("PROGRESS 100.0", flush=True)


if __name__ == "__main__":
    main()
