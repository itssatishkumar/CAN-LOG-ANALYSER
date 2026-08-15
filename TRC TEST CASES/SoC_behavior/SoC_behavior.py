import os
import sys
import re
import json
import struct
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from trc_utils import fast_parse_ts, progress_by_bytes

PROGRESS_STEP = 0.5  # percent granularity for live progress

# -----------------------------------------------------
# GET TRC FROM MAIN GUI ARGUMENT
# -----------------------------------------------------
if len(sys.argv) < 2:
    print("ERROR: No TRC file received from GUI!")
    sys.exit(1)

trc_path = sys.argv[1]

if not os.path.exists(trc_path):
    print(f"ERROR: TRC file not found: {trc_path}")
    sys.exit(1)

folder = os.path.dirname(os.path.abspath(__file__))
print(f"Using TRC file from GUI: {trc_path}")
emit_progress = progress_by_bytes(trc_path, step=PROGRESS_STEP)

# -----------------------------------------------------
# TRC regex
# -----------------------------------------------------
pattern = re.compile(
    r"\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)"
)

SOC_ID = 0x0109
CURR_ID = 0x0110
VOLT_ID = 0x012C
ODO_ID = 0x0402

timestamps_ms = []
soc_list = []
bms_state_list = []
hhmm_list = []
full_ts_list = []

# For additional signal tracking
volt_events = []  # (ts_ms, vmax_mv)
curr_events = []  # (ts_ms, current_A, bms_state)
odo_events = []   # (ts_ms, odo_km)
last_bms_state_any = None

# -----------------------------------------------------
# PARSE TRC
# -----------------------------------------------------
with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
    for line_idx, line in enumerate(f, 1):
        emit_progress(len(line))
        m = pattern.match(line)
        if not m:
            continue

        date_str = m.group(1)
        time_str = m.group(2)
        ms_str = m.group(3)
        can_id = int(m.group(4), 16)
        dlc = int(m.group(5))
        data_str = m.group(6).strip()

        # Only bother decoding payload for IDs we care about
        if can_id not in (SOC_ID, CURR_ID, VOLT_ID, ODO_ID):
            continue

        dt, ts_ms, ts_str = fast_parse_ts(date_str, time_str, ms_str)

        bytes_hex = data_str.split()
        if len(bytes_hex) < dlc:
            continue
        data = [int(b, 16) for b in bytes_hex[:dlc]]

        if can_id == SOC_ID:
            raw_soc = (data[1] << 8) | data[0]
            soc = raw_soc * 0.01
            bms_state = data[4]

            # Track latest BMS state (even if 0) for use with current frames
            last_bms_state_any = bms_state

            timestamps_ms.append(ts_ms)
            # Mark SoC as NaN if BMS state is 0
            if bms_state == 0:
                soc_list.append(float('nan'))
            else:
                soc_list.append(soc)
            bms_state_list.append(bms_state)
            hhmm_list.append(dt.strftime("%H:%M:%S"))
            full_ts_list.append(ts_str)

        elif can_id == VOLT_ID:
            # 012C: Voltage_Max (bytes 0-1), Voltage_Min (bytes 2-3), scale 0.1 mV
            if len(data) >= 4:
                vmax = (data[0] | (data[1] << 8)) * 0.1
                # Track with latest known BMS state (may be None if not yet seen)
                volt_events.append((ts_ms, vmax, last_bms_state_any))

        elif can_id == CURR_ID:
            # 0110: Pack current, bytes 4-7, signed 32-bit, scale 1e-5 A
            if len(data) >= 8 and last_bms_state_any not in (None, 0):
                raw = struct.unpack("<i", bytes(data[4:8]))[0]
                current = raw * 1e-5
                curr_events.append((ts_ms, current, last_bms_state_any))

        elif can_id == ODO_ID:
            # 0402: ODO_TRIP, ODO at bits 0..31, little-endian, scale 0.1 km
            if len(data) >= 4:
                raw_odo = (
                    data[0]
                    | (data[1] << 8)
                    | (data[2] << 16)
                    | (data[3] << 24)
                )
                odo_km = raw_odo * 0.1
                odo_events.append((ts_ms, odo_km))

# -----------------------------------------------------
# CHECK DATA
# -----------------------------------------------------
if len(soc_list) < 2:
    print("No valid SoC samples found.")
    sys.exit(1)

df = pd.DataFrame({
    "ts": timestamps_ms,
    "SoC": soc_list,
    "BMS": bms_state_list,
    "hhmm": hhmm_list,
    "full_ts": full_ts_list
})

# Remove rows where SoC is NaN for further analysis, but keep original for traceability
df_valid = df.dropna(subset=["SoC"]).reset_index(drop=True)
# Strict filter: only rows where BMS != 0 (data[4] != 0)

# Remove the first valid SoC after every BMS state 0 period
bms_full = df["BMS"].values
to_ignore = set()
for i in range(1, len(bms_full)):
    if bms_full[i-1] == 0 and bms_full[i] != 0:
        # Find the corresponding index in df_valid
        ts_val = df["ts"].iloc[i]
        idx_valid = df_valid.index[df_valid["ts"] == ts_val].tolist()
        if idx_valid:
            to_ignore.add(idx_valid[0])

if to_ignore:
    df_valid = df_valid.drop(list(to_ignore)).reset_index(drop=True)

# -----------------------------------------------------
# ROBUST ZERO SoC FILTER (GLOBAL – applies to ALL logic)
# Keep zero SoC only if >=5 continuous samples with BMS != 0
# -----------------------------------------------------
soc = df_valid["SoC"].values
bms = df_valid["BMS"].values

keep_mask = np.ones(len(df_valid), dtype=bool)

i = 0
n = len(df_valid)

while i < n:
    if soc[i] == 0 and bms[i] != 0:
        j = i
        count = 0

        while j < n and soc[j] == 0 and bms[j] != 0:
            count += 1
            j += 1

        if count < 5:
            keep_mask[i:j] = False  # remove false zero block

        i = j
    else:
        i += 1

df_valid = df_valid[keep_mask].reset_index(drop=True)

# -----------------------------------------------------
# BUILD ALL VALID SoC TRANSITIONS (dt < 3000 ms)
# -----------------------------------------------------
soc_arr = df_valid["SoC"].values
ts_arr = df_valid["ts"].values
bms_arr = df_valid["BMS"].values
full_ts_arr = df_valid["full_ts"].values

dsoc_arr = np.abs(soc_arr[1:] - soc_arr[:-1])
dt_arr = ts_arr[1:] - ts_arr[:-1]

mask = dt_arr < 3000
if not mask.any():
    print("No valid delta found!")
    sys.exit(1)

valid_indices = mask.nonzero()[0]

SPECIAL_FROM = 99.0
SPECIAL_TO = 100.0


def is_special_case(prev_soc, curr_soc):
    """99% -> 100% direct jump is an allowed/expected special case."""
    return round(prev_soc, 2) == SPECIAL_FROM and round(curr_soc, 2) == SPECIAL_TO


transitions = []
for i in valid_indices:
    p_soc = float(soc_arr[i])
    c_soc = float(soc_arr[i + 1])
    d = float(dsoc_arr[i])
    dt_val = float(dt_arr[i])
    transitions.append({
        "idx": int(i),
        "prev_soc": p_soc,
        "curr_soc": c_soc,
        "delta": d,
        "dt_ms": dt_val,
        "timestamp": full_ts_arr[i + 1],
        "ts_ms": float(ts_arr[i + 1]),
        "is_special": is_special_case(p_soc, c_soc),
        "higher_soc": max(p_soc, c_soc),
    })

# Rank by delta (desc); ties broken by the transition that happened at the
# higher SoC (desc)
transitions_sorted = sorted(
    transitions, key=lambda t: (-t["delta"], -t["higher_soc"])
)

TOP_N = 3
top_transitions = transitions_sorted[:TOP_N]

# All occurrences of the 99% -> 100% special case (always reported/plotted,
# even if not within the top-N by delta size)
special_transitions = [t for t in transitions if t["is_special"]]

# Deltas that are NOT the allowed special case — these are what determine
# PASS/FAIL against the 0.1% threshold
non_special_deltas = [t["delta"] for t in transitions if not t["is_special"]]
max_non_special_delta = max(non_special_deltas) if non_special_deltas else 0.0

# Rank-1 transition (kept for backward-compatible fields / txt summary)
top1 = top_transitions[0]
delta = top1["delta"]
dt_ms = top1["dt_ms"]
prev_soc = top1["prev_soc"]
curr_soc = top1["curr_soc"]
idx = top1["idx"]


def detect_soc_stuck_odo(df, odo_events, min_km=4.0, max_soc_delta=1.0, max_odo_gap_ms=3000):
    if len(odo_events) < 2:
        return False, None, None

    odo_sorted = sorted(odo_events, key=lambda x: x[0])
    n = len(odo_sorted)
    odo_ts = np.array([event[0] for event in odo_sorted])
    large_gap_prefix = np.concatenate((
        [0],
        np.cumsum(np.diff(odo_ts) > max_odo_gap_ms),
    ))

    df_ts = df["ts"].values
    df_soc = df["SoC"].values
    df_full_ts = df["full_ts"].values
    df_ts_sorted = np.all(df_ts[:-1] <= df_ts[1:])

    # Identify SoC indices to ignore (first valid after BMS=0)
    bms_full = df["BMS"].values
    ignore_ts = set()
    for i in range(1, len(bms_full)):
        if bms_full[i-1] == 0 and bms_full[i] != 0:
            ignore_ts.add(df_ts[i])
    ignore_mask = np.isin(df_ts, list(ignore_ts)) if ignore_ts else np.zeros(len(df_ts), dtype=bool)

    j = 0
    for i in range(n):
        t_start, odo_start = odo_sorted[i]
        if j < i:
            j = i

        while j < n and (odo_sorted[j][1] - odo_start) < min_km:
            j += 1

        if j >= n:
            break

        t_end, odo_end = odo_sorted[j]

        if large_gap_prefix[j] - large_gap_prefix[i]:
            continue

        # Remove ignored SoC samples
        if df_ts_sorted:
            left = np.searchsorted(df_ts, t_start, side="left")
            right = np.searchsorted(df_ts, t_end, side="right")
            seg_indices = np.flatnonzero(~ignore_mask[left:right]) + left
        else:
            seg_indices = np.flatnonzero(
                (df_ts >= t_start) & (df_ts <= t_end) & ~ignore_mask
            )
        if not len(seg_indices):
            continue

        # Only judge if all SoC in segment are >= 1%
        seg_soc = df_soc[seg_indices]
        if np.any(seg_soc < 1.0):
            continue

        soc_start = seg_soc[0]
        soc_range = float(np.max(seg_soc) - np.min(seg_soc))

        if soc_range <= max_soc_delta:
            first_ts_full = df_full_ts[seg_indices[0]]
            return True, round(soc_start, 2), first_ts_full

    return False, None, None


odo_soc_stuck, odo_stuck_first_soc, odo_stuck_first_ts = detect_soc_stuck_odo(df, odo_events)


def save_txt(text: str):
    from pathlib import Path

    p = Path(__file__).resolve()

    for parent in [p] + list(p.parents):
        history = parent / "History"
        if history.exists() and history.is_dir():
            file = history / "SoC.txt"
            with open(file, "w", encoding="utf-8") as f:
                f.write(text)
            return

# -----------------------------------------------------
# SUMMARY DATA
# -----------------------------------------------------
def transition_dict(t, rank=None):
    d = {
        "Rank": rank,
        "Prev_SoC": round(t["prev_soc"], 2),
        "Curr_SoC": round(t["curr_soc"], 2),
        "Delta_SoC": round(t["delta"], 2),
        "Delta_Time_ms": round(t["dt_ms"], 2),
        "Timestamp": t["timestamp"],
        "Special_Case_99_to_100": bool(t["is_special"]),
    }
    if rank is None:
        del d["Rank"]
    return d


top3_summary = [transition_dict(t, rank=r + 1) for r, t in enumerate(top_transitions)]
special_summary = [transition_dict(t) for t in special_transitions]

summary = {
    "Start_SoC": round(df["SoC"].iloc[0], 2),
    "Final_SoC": round(df["SoC"].iloc[-1], 2),
    "Max_Delta_SoC": round(delta, 2),
    "SoC_Transition": f"{round(prev_soc,2)} % to {round(curr_soc,2)} %",
    "Timestamp_of_Max_Delta": top1["timestamp"],
    "Delta_Time_ms": round(dt_ms, 2),
    "Top3_SoC_Deltas": top3_summary,
    "Special_Case_Transitions": special_summary,
    "Max_Non_Special_Delta_SoC": round(max_non_special_delta, 2),
    "ODO_SoC_Stuck": bool(odo_soc_stuck),
    "ODO_Stuck_First_SoC": odo_stuck_first_soc,
    "ODO_Stuck_First_Timestamp": odo_stuck_first_ts,
}

top3_txt_lines = []
for t in top3_summary:
    tag = " [SPECIAL 99->100, allowed]" if t["Special_Case_99_to_100"] else ""
    top3_txt_lines.append(
        f"  Rank {t['Rank']}: {t['Delta_SoC']}%  "
        f"({t['Prev_SoC']}% to {t['Curr_SoC']}%) @ {t['Timestamp']}{tag}"
    )

txt_content = (
    f"SoC Range : (Initial SoC {summary['Start_SoC']}% & Final SoC {summary['Final_SoC']}%)\n"
    f"Top 3 SoC Deltas :\n" + "\n".join(top3_txt_lines) + "\n"
    f"Any SoC stuck : "
    f"{'Yes (' + str(summary['ODO_Stuck_First_SoC']) + '%)' if summary['ODO_SoC_Stuck'] else 'No'}"
)

save_txt(txt_content)

# -----------------------------------------------------
# SAVE PASS/FAIL RESULT → SoC_results.json
# FAIL if:
#  - Max SoC jump (excluding the allowed 99%->100% special case) > 0.1 %, OR
#  - ODO-based SoC stuck is detected.
# The 99% -> 100% direct jump (delta 1%) is always reported/plotted but never
# by itself causes a FAIL.
# -----------------------------------------------------
result = "FAIL" if (max_non_special_delta > 0.1 or odo_soc_stuck) else "PASS"

result_json_path = os.path.join(folder, "SoC_results.json")

with open(result_json_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "Result": result,
            "Max_SoC_Delta": summary["Max_Delta_SoC"],
            "Max_Non_Special_Delta_SoC": summary["Max_Non_Special_Delta_SoC"],
            "Top3_SoC_Deltas": top3_summary,
            "Special_Case_Transitions": special_summary,
            "ODO_SoC_Stuck": bool(odo_soc_stuck),
            "ODO_Stuck_First_SoC": odo_stuck_first_soc,
            "ODO_Stuck_First_Timestamp": odo_stuck_first_ts,
        },
        f,
        indent=4,
        ensure_ascii=False,
    )

print(f"SoC PASS/FAIL saved: {result_json_path}")

# -----------------------------------------------------
# ASCII SUMMARY → soc_summary.json
# -----------------------------------------------------
LEFT_WIDTH = 22
RIGHT_WIDTH = 42

def make_row(label, value):
    return f"| {label.ljust(LEFT_WIDTH)} | {value.ljust(RIGHT_WIDTH)} |"

border = "+" + "-"*(LEFT_WIDTH+2) + "+" + "-"*(RIGHT_WIDTH+2) + "+"

table_lines = [
    border,
    "| " + "SoC Summary".center(LEFT_WIDTH + RIGHT_WIDTH + 3) + " |",
    border,
    make_row("Start SoC (%)", f"{summary['Start_SoC']}%"),
    make_row("Final SoC (%)", f"{summary['Final_SoC']}%"),
    make_row(
        "Max SoC Delta (%)",
        f"{summary['Max_Delta_SoC']}%  (PASS threshold is 0.1%)",
    ),
    make_row("ODO SoC Stuck", "YES" if odo_soc_stuck else "NO"),
    make_row(
        "ODO First SoC (%)",
        f"{odo_stuck_first_soc}%" if odo_soc_stuck and odo_stuck_first_soc is not None else "",
    ),
    make_row("SoC Transition", summary["SoC_Transition"]),
    make_row("Delta Timestamp", summary["Timestamp_of_Max_Delta"]),
    border,
]

for t in top3_summary:
    tag = " *" if t["Special_Case_99_to_100"] else ""
    table_lines.append(
        make_row(
            f"Rank {t['Rank']} Delta (%)",
            f"{t['Delta_SoC']}% ({t['Prev_SoC']}->{t['Curr_SoC']}){tag}",
        )
    )
table_lines.append(border)

if special_summary:
    table_lines.append(make_row("Special 99->100 Jumps", str(len(special_summary))))
    table_lines.append(border)

json_summary_path = os.path.join(folder, "soc_summary.json")

with open(json_summary_path, "w", encoding="utf-8") as f:
    json.dump({"Summary_Table": table_lines}, f, indent=4, ensure_ascii=False)

print(f"ASCII Summary saved to JSON: {json_summary_path}")

# -----------------------------------------------------
# SOC PLOT
# -----------------------------------------------------
plt.figure(figsize=(12, 5))
# Background line: all SoC values that participate in the transition set
valid_plot_indices = np.unique(np.concatenate([valid_indices, valid_indices + 1]))
ts_plot = df_valid["ts"].values[valid_plot_indices]
soc_plot = df_valid["SoC"].values[valid_plot_indices]
plt.plot(ts_plot, soc_plot, linewidth=2, label="SoC (Delta Computed)")

rank_colors = {1: "red", 2: "orange", 3: "purple"}
plotted_idx = set()

for rank_i, t in enumerate(top_transitions, start=1):
    color = rank_colors.get(rank_i, "brown")
    marker_x = df_valid.loc[t["idx"], "ts"]
    marker_y = df_valid.loc[t["idx"], "SoC"]
    label = f"Rank {rank_i} Jump ({t['delta']:.2f}%)"
    if t["is_special"]:
        label += " [special]"
    plt.scatter(marker_x, marker_y, s=90, c=color, zorder=5, label=label)
    plt.annotate(
        f"#{rank_i}: {t['delta']:.2f}% ({t['prev_soc']:.2f}% to {t['curr_soc']:.2f}%)",
        (marker_x, marker_y),
        xytext=(10, 10 + 15 * (rank_i - 1)),
        textcoords="offset points",
        fontsize=9,
        color=color,
    )
    plotted_idx.add(t["idx"])

# Always plot any 99->100 special-case jumps, even if outside the top-3
for t in special_transitions:
    if t["idx"] in plotted_idx:
        continue
    marker_x = df_valid.loc[t["idx"], "ts"]
    marker_y = df_valid.loc[t["idx"], "SoC"]
    plt.scatter(
        marker_x, marker_y, s=90, c="green", marker="*", zorder=5,
        label="Special Jump 99%->100% (allowed)",
    )
    plt.annotate(
        f"Special: {t['delta']:.2f}% ({t['prev_soc']:.2f}% to {t['curr_soc']:.2f}%)",
        (marker_x, marker_y),
        xytext=(10, -15),
        textcoords="offset points",
        fontsize=9,
        color="green",
    )
    plotted_idx.add(t["idx"])

plt.title("SoC vs Time (Top 3 Deltas + Special 99%->100% Cases)")
plt.xlabel("Time")
plt.ylabel("SoC (%)")
plt.grid(True, linestyle="--", alpha=0.4)

def fmt_time(x, pos=None):
    dt = datetime.fromtimestamp(x / 1000.0)
    return dt.strftime("%H:%M:%S")

ax = plt.gca()
ax.xaxis.set_major_locator(ticker.LinearLocator(12))
ax.xaxis.set_major_formatter(ticker.FuncFormatter(fmt_time))
plt.xticks(rotation=40)

# De-duplicate legend entries (multiple special markers would repeat the label)
handles, labels = ax.get_legend_handles_labels()
seen = {}
for h, l in zip(handles, labels):
    if l not in seen:
        seen[l] = h
plt.legend(seen.values(), seen.keys())

plt.tight_layout()

plot_path = os.path.join(folder, "soc_plot.png")
plt.savefig(plot_path, dpi=200)
plt.close()

print(f"SoC plot saved: {plot_path}")
print("PROGRESS 100.0", flush=True)
print("\nDONE :)")
