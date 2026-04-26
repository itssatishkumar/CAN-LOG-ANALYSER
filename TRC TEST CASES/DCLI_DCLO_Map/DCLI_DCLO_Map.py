import re
import struct
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from datetime import datetime
import json

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))
from trc_utils import fast_datetime_from_str, progress_by_bytes

import matplotlib

matplotlib.use("Agg")  # non-GUI backend
import matplotlib.pyplot as plt
import numpy as np

PROGRESS_STEP = 0.5  # percent granularity for live progress

def parse_trc_for_110(filepath, progress_cb=None):
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

        return fast_datetime_from_str(ts_clean)

    with open(filepath, "r") as f:
        for line_idx, line in enumerate(f, 1):
            if progress_cb:
                progress_cb(len(line))
            match_110 = pattern_110.match(line)
            match_012a = pattern_012a.match(line)
            match_109 = pattern_109.match(line)

            if match_110:
                data_str = match_110.group(3).strip().split()
                if len(data_str) < 8:
                    continue

                b4, b5, b6, b7 = [int(x, 16) for x in data_str[4:8]]
                raw = struct.unpack("<i", bytes([b4, b5, b6, b7]))[0]
                current = raw * 1e-5  # A

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
                dlco_vals.append(-dlco)  # discharge limit (negative)
                ts = parse_timestamp(match_012a.group(1))
                dl_ts.append(ts)

            if match_109:
                data_str = match_109.group(3).strip().split()
                if len(data_str) < 2:
                    continue

                b0, b1 = [int(x, 16) for x in data_str[0:2]]
                soc_raw = struct.unpack("<H", bytes([b0, b1]))[0]
                soc = soc_raw * 0.01  # SoC %
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


def format_duration(seconds: float) -> str:
    if seconds <= 0 or seconds != seconds:  # NaN check
        return ""
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def save_txt(text: str):
    p = Path(__file__).resolve()

    for parent in [p] + list(p.parents):
        history = parent / "History"
        if history.exists() and history.is_dir():
            file = history / "Current_Profile.txt"
            with open(file, "w", encoding="utf-8") as f:
                f.write(text)
            return

def compute_overcurrent_instances(
    timestamps, currents, dl_ts, dlco_vals, soc_ts, soc_vals
):
    """
    Find sessions where pack current is more negative than DCLO:
        current < DCLO (both negative)
    Returns list of dicts with duration, avg DCLO, avg current, SoC at start.
    """
    # Filter valid data
    cur_samples = [(t, c) for t, c in zip(timestamps, currents) if t is not None]
    dl_samples = [(t, d) for t, d in zip(dl_ts, dlco_vals) if t is not None]
    soc_samples = [(t, s) for t, s in zip(soc_ts, soc_vals) if t is not None]

    if not cur_samples or not dl_samples:
        return []

    cur_samples.sort(key=lambda x: x[0])
    dl_samples.sort(key=lambda x: x[0])
    soc_samples.sort(key=lambda x: x[0])

    dl_idx = 0
    soc_idx = 0
    last_dl = None
    last_soc = None

    instances = []
    in_session = False
    sess_start_time = None
    sess_end_time = None
    sum_dl = 0.0
    sum_i = 0.0
    count = 0
    soc_at_start = None

    for t, i_val in cur_samples:
        # update DCLO & SoC to "latest at or before t"
        while dl_idx < len(dl_samples) and dl_samples[dl_idx][0] <= t:
            last_dl = dl_samples[dl_idx][1]
            dl_idx += 1
        while soc_idx < len(soc_samples) and soc_samples[soc_idx][0] <= t:
            last_soc = soc_samples[soc_idx][1]
            soc_idx += 1

        if last_dl is None:
            continue

        # We only care where DCLO is negative (discharge limit)
        over = (last_dl < 0) and (i_val < last_dl)

        if over:
            if not in_session:
                # start new session
                in_session = True
                sess_start_time = t
                soc_at_start = last_soc
                sum_dl = 0.0
                sum_i = 0.0
                count = 0
            sess_end_time = t
            sum_dl += last_dl
            sum_i += i_val
            count += 1
        else:
            if in_session and count > 0:
                duration = (sess_end_time - sess_start_time).total_seconds()
                instances.append(
                    {
                        "start_time": sess_start_time,
                        "end_time": sess_end_time,
                        "duration_sec": duration,
                        "avg_dclo": sum_dl / count,
                        "avg_current": sum_i / count,
                        "soc_start": soc_at_start,
                    }
                )
            in_session = False

    # flush if still open at end
    if in_session and count > 0:
        duration = (sess_end_time - sess_start_time).total_seconds()
        instances.append(
            {
                "start_time": sess_start_time,
                "end_time": sess_end_time,
                "duration_sec": duration,
                "avg_dclo": sum_dl / count,
                "avg_current": sum_i / count,
                "soc_start": soc_at_start,
            }
        )

    return instances


def main():
    trc_path = sys.argv[1] if len(sys.argv) > 1 else None

    if not trc_path:
        print("Select TRC file...")
        trc_path = select_trc_file()

    if not trc_path:
        print("No file selected.")
        return

    progress_cb = progress_by_bytes(trc_path, step=PROGRESS_STEP)

    (timestamps, currents), (dl_ts, dlci_vals, dlco_vals), (soc_ts, soc_vals) = parse_trc_for_110(
        trc_path,
        progress_cb=progress_cb
    )
    dl_ts, dlci_vals, dlco_vals = filter_zero_streaks(dl_ts, dlci_vals, dlco_vals, min_len=4)

    if not currents:
        print("No 0x110 frames found.")
        return

    max_negative = min(currents)
    max_positive = max(currents)

    filtered = [c for c in currents if abs(c) >= 3.0]
    avg_current = sum(filtered) / len(filtered) if filtered else 0

    # ----- compute overcurrent instances (current more negative than DCLO) -----
    instances = compute_overcurrent_instances(
        timestamps, currents, dl_ts, dlco_vals, soc_ts, soc_vals
    )
    # sort by duration and take top 3
    instances_sorted = sorted(
        instances, key=lambda x: x["duration_sec"], reverse=True
    )[:3]

    import matplotlib.dates as mdates

    out_dir = Path(__file__).resolve().parent

    fig, ax_curr = plt.subplots(figsize=(10, 4.5))

    valid_points = [(t, c) for t, c in zip(timestamps, currents) if t is not None]
    dl_valid = [(t, i, o) for t, i, o in zip(dl_ts, dlci_vals, dlco_vals) if t is not None]
    soc_valid = [(t, s) for t, s in zip(soc_ts, soc_vals) if t is not None]

    use_datetime_x = False

    if valid_points:
        x_vals, y_vals = zip(*valid_points)
        use_datetime_x = True
        pos = [(x, y) for x, y in zip(x_vals, y_vals) if y >= 0]
        neg = [(x, y) for x, y in zip(x_vals, y_vals) if y < 0]

        if pos:
            xp, yp = zip(*pos)
            ax_curr.vlines(xp, [0] * len(xp), yp, color="green", linewidth=0.9, label="Charge / Positive")

        if neg:
            xn, yn = zip(*neg)
            ax_curr.vlines(xn, [0] * len(xn), yn, color="red", linewidth=0.9, label="Discharge / Negative")

        if dl_valid:
            dl_x, dl_i, dl_o = zip(*dl_valid)
            ax_curr.step(dl_x, dl_i, where="post", color="blue", linewidth=1.1, label="DCLI (limit IN)")
            ax_curr.step(dl_x, dl_o, where="post", color="orange", linewidth=1.1, label="DCLO (limit OUT)")

    else:
        x_vals = list(range(1, len(currents) + 1))
        pos = [(x, y) for x, y in zip(x_vals, currents) if y >= 0]
        neg = [(x, y) for x, y in zip(x_vals, currents) if y < 0]

        if pos:
            xp, yp = zip(*pos)
            ax_curr.vlines(xp, [0] * len(xp), yp, color="green", linewidth=0.9)

        if neg:
            xn, yn = zip(*neg)
            ax_curr.vlines(xn, [0] * len(xn), yn, color="red", linewidth=0.9)

        if dl_valid:
            dl_x, dl_i, dl_o = zip(*dl_valid)
            ax_curr.step(dl_x, dl_i, where="post", color="blue", linewidth=1.1, label="DCLI (limit IN)")
            ax_curr.step(dl_x, dl_o, where="post", color="orange", linewidth=1.1, label="DCLO (limit OUT, negated)")

    ax_curr.set_title("DCLI / DCLO Map - Current Profile")

    if (valid_points and (pos or neg)) or dl_valid:
        ax_curr.legend(loc="upper right")

    ax_curr.set_ylabel("Current (A)")
    ax_curr.grid(True, linestyle="--", alpha=0.5)

    if soc_valid:
        soc_x, soc_y = zip(*soc_valid)
        soc_x_num = mdates.date2num(soc_x)
        soc_vals_arr = np.array(soc_y, dtype=float)

        # X positions corresponding to the main plot
        if use_datetime_x:
            main_x_num = mdates.date2num(np.array(x_vals))
        else:
            main_x_num = np.asarray(x_vals, dtype=float)

        if len(main_x_num) > 0:
            tick_idx = np.linspace(0, len(main_x_num) - 1, num=min(20, len(main_x_num)), dtype=int)
            tick_pos = main_x_num[tick_idx]
            soc_at_ticks = np.interp(tick_pos, soc_x_num, soc_vals_arr)

            ax_curr.set_xticks(tick_pos)
            ax_curr.set_xticklabels([f"{v:.2f}" for v in soc_at_ticks], rotation=45, ha="right")
            ax_curr.set_xlabel("State of Charge, SoC (%)")
    elif soc_vals:
        # Fallback: use SoC samples directly, similar to AuxCharge plot logic.
        soc_vals_arr = np.array(soc_vals, dtype=float)
        x_idx = np.arange(len(soc_vals_arr))
        if len(x_idx) > 0:
            tick_idx = np.linspace(0, len(x_idx) - 1, num=min(20, len(x_idx)), dtype=int)
            tick_pos = x_idx[tick_idx]
            ax_curr.set_xticks(tick_pos)
            ax_curr.set_xticklabels([f"{soc_vals_arr[i]:.2f}" for i in tick_idx], rotation=45, ha="right")
            ax_curr.set_xlabel("State of Charge, SoC (%)")
    else:
        # No SoC available – fall back to time or sample index.
        if use_datetime_x:
            ax_curr.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            fig.autofmt_xdate()
            ax_curr.set_xlabel("Time")
        else:
            ax_curr.set_xlabel("Sample #")

    fig.tight_layout()

    plot_path = out_dir / "DCLI_DCLO_Map_plot.png"
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)

        # ---------- SUMMARY JSON WITH OVER-CURRENT INSTANCES ----------
    summary_path = out_dir / "DCLI_DCLO_Map_summary.json"

    overall_summary = {
        "Max Discharge (Most Negative) [A]": f"{max_negative:.2f}",
        "Max Charge/Regen (Most Positive) [A]": f"{max_positive:.2f}",
        "Average Current (|I| >= 3A) [A]": f"{avg_current:.2f}",
    }

    instance_rows = []
    for idx, inst in enumerate(instances_sorted, start=1):
        dur_str = format_duration(inst["duration_sec"])
        dclo_str = f"{inst['avg_dclo']:.0f}A"
        avg_i_str = f"{inst['avg_current']:.0f}A"
        if inst["soc_start"] is None:
            soc_str = ""
        else:
            soc_str = f"{inst['soc_start']:.2f}%"

        instance_rows.append(
            {
                "Instance": idx,
                "Duration": dur_str,
                "DCLO": dclo_str,
                "PackCurrentAverage": avg_i_str,
                "SoC": soc_str,
            }
        )

    summary_payload = {
        "Summary_Table": {
            "Overall": overall_summary,
            "Over_Current_Instances": instance_rows,
        }
    }
    summary_path.write_text(json.dumps(summary_payload, indent=4), encoding="utf-8")

    # ---- BUILD TXT CONTENT ----
    neg_currents = [c for c in currents if c < 0]
    avg_discharge = sum(neg_currents) / len(neg_currents) if neg_currents else 0

    txt_lines = []
    txt_lines.append(f"Average Discharge Current : {avg_discharge:.0f}A\n")
    txt_lines.append(f"Peak Discharge current : {min(currents):.0f}A\n")

    txt_lines.append("\nPeak Discharge current :")
    for inst in instance_rows:
        txt_lines.append(
            f'"Instance": {inst["Instance"]}, "Duration": "{inst["Duration"]}",'
            f'"DCLO": "{inst["DCLO"]}","PackCurrentAverage": "{inst["PackCurrentAverage"]}",'
            f'"SoC": "{inst["SoC"]}"'
        )

    # ---- REGEN FROM RAW POSITIVE CURRENT ----
    pos_samples = [(t, c) for t, c in zip(timestamps, currents) if t is not None and c > 0]
    soc_samples = [(t, s) for t, s in zip(soc_ts, soc_vals) if t is not None]
    soc_samples.sort(key=lambda x: x[0])
    soc_idx = 0
    last_soc = None
    dl_samples = [(t, d) for t, d in zip(dl_ts, dlci_vals) if t is not None]
    dl_samples.sort(key=lambda x: x[0])
    dl_idx = 0
    last_dcli = None

    regen_events = []
    i = 0
    n = len(pos_samples)

    while i < n:
        start_t, _ = pos_samples[i]

        while dl_idx < len(dl_samples) and dl_samples[dl_idx][0] <= start_t:
            last_dcli = dl_samples[dl_idx][1]
            dl_idx += 1
        sum_i = 0.0
        count = 0

        j = i
        while j < n and (pos_samples[j][0] - pos_samples[i][0]).total_seconds() <= 1:
            sum_i += pos_samples[j][1]
            count += 1
            j += 1

        end_t = pos_samples[j - 1][0]
        duration = (end_t - start_t).total_seconds()

        regen_events.append({
            "duration_sec": duration,
            "avg_current": sum_i / count if count else 0,
            "soc_start": last_soc,
            "dcli": last_dcli
    })

        i = j

    regen_sorted = sorted(regen_events, key=lambda x: x["avg_current"], reverse=True)[:3]

    txt_lines.append("\n\nPeak Regen Current and Duration")

    for idx, inst in enumerate(regen_sorted, start=1):
        txt_lines.append(
            f'"Instance": {idx}, "Duration": "{format_duration(inst["duration_sec"])}",'
            f'"Instance": {idx}, "Duration": "{format_duration(inst["duration_sec"])}","DCLI": "{(f"{inst["dcli"]:.0f}") if inst["dcli"] is not None else ""}","PackCurrentAverage": "{inst["avg_current"]:.0f}A","SoC": "{(f"{inst["soc_start"]:.2f}%") if inst["soc_start"] is not None else ""}"'
        )

    txt_content = "\n".join(txt_lines)
    save_txt(txt_content)

    # Result JSON just indicates script run success
    result_path = out_dir / "DCLI_DCLO_Map_results.json"
    result_status = "PASS" if plot_path.exists() and summary_path.exists() else "FAIL"
    result_path.write_text(json.dumps({"Result": result_status}), encoding="utf-8")
    print("PROGRESS 100.0", flush=True)


if __name__ == "__main__":
    main()
