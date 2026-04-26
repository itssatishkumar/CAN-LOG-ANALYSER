import os
import sys
import re
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt

PROGRESS_STEP = 0.5  # percent granularity for live progress
# =====================================================
# OUTPUT CONFIG (saved next to script)
# =====================================================
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))
from trc_utils import progress_by_bytes

OUTPUTS = {
    "SoC VS VOLTAGE SUMMARY": {
        "result": "SoC_vs_Voltage_Summary_results.json",
        "summary": "SoC_vs_Voltage_Summary_summary.json",
        "graph": "SoC_vs_Voltage_Summary_plot.png",
    }
}

# =====================================================
# TRC REGEX (matches your sample)
# =====================================================
TRC_PATTERN = re.compile(
    r"^\s*\d+\)\s+"
    r"(?P<date>\d{2}-\d{2}-\d{4})\s+"
    r"(?P<hms>\d{2}:\d{2}:\d{2})\.(?P<frac>\d{3,4})(?:\.\d+)?\s+"
    r"\w+\s+"
    r"(?P<canid>[0-9A-Fa-f]+)\s+"
    r"(?P<dlc>\d+)\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s*)+)$"
)


# =====================================================
# CAN DECODE HELPERS
# =====================================================
def u16_le(b0: int, b1: int) -> int:
    return b0 | (b1 << 8)


def parse_trc_line(line: str):
    # Fast-path parser keeps same regex validation but avoids strptime overhead.
    m = TRC_PATTERN.match(line)
    if not m:
        return None

    date = m.group("date")  # DD-MM-YYYY
    hms = m.group("hms")
    frac = m.group("frac")

    canid = int(m.group("canid"), 16)
    dlc = int(m.group("dlc"))

    micro = int(frac) * (1000 if len(frac) == 3 else 100)

    # Manual datetime construction is ~3-4x faster than strptime here.
    ts = datetime(
        int(date[6:10]),  # year
        int(date[3:5]),   # month
        int(date[0:2]),   # day
        int(hms[0:2]),    # hour
        int(hms[3:5]),    # minute
        int(hms[6:8]),    # second
        micro,
    )

    data_bytes = m.group("data").split()
    if len(data_bytes) < dlc:
        return None
    data_bytes = [int(x, 16) for x in data_bytes[:dlc]]

    return ts, canid, dlc, data_bytes

def decode_frame(canid: int, data: list[int]) -> dict:
    if canid == 0x0109:
        soc = u16_le(data[0], data[1]) * 0.01
        bms_state = data[4]
        return {"SoC": soc, "BMS_State": bms_state}

    if canid == 0x0602:
        charging_info = data[6]
        vehicle_state_raw = data[7]

        state_map = {
            0: "OFF",
            1: "Charge",
            2: "Drive",
            3: "FullCharge"
        }

        return {
            "Charging_Info": charging_info,
            "Vehicle_State": state_map.get(vehicle_state_raw, f"Unknown({vehicle_state_raw})")
        }

    if canid == 0x0110:
        raw = int.from_bytes(bytes(data[4:8]), byteorder="little", signed=True)
        current = raw * 1e-5
        return {"Pack_Current": current}

    if canid == 0x012C:
        vdelta = u16_le(data[4], data[5]) * 0.1
        vmin = u16_le(data[2], data[3]) * 0.1
        vmax = u16_le(data[0], data[1]) * 0.1
        return {
            "Voltage_Delta": vdelta,
            "Voltage_Min": vmin,
            "Voltage_Max": vmax,
        }

    return {}


# =====================================================
# TRC -> DataFrame (merged by timestamp)
# =====================================================
def trc_to_timeseries_df(trc_path: str, progress_cb=None) -> pd.DataFrame:
    needed_ids = {0x0109, 0x0602, 0x0110, 0x012C}
    columns = ("SoC", "BMS_State", "Charging_Info", "Vehicle_State", "Voltage_Delta", "Voltage_Min", "Voltage_Max", "Pack_Current")
    rows = []

    last_row = {c: pd.NA for c in columns}
    current_ts = None
    current_values = {c: pd.NA for c in columns}

    with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f, 1):
            if progress_cb:
                progress_cb(len(line))
            parsed = parse_trc_line(line)
            if not parsed:
                continue
            ts, canid, _, data = parsed
            if canid not in needed_ids:
                continue
            decoded = decode_frame(canid, data)
            if not decoded:
                continue

            if ts != current_ts:
                # Finalize previous timestamp before moving on.
                if current_ts is not None:
                    row = {"Timestamp": current_ts}
                    for col in columns:
                        val = current_values[col]
                        row[col] = val if not pd.isna(val) else last_row[col]
                    rows.append(row)
                    last_row = row.copy()
                current_ts = ts
                current_values = {c: pd.NA for c in columns}

            for key, val in decoded.items():
                if key in current_values:
                    current_values[key] = val

    # Flush the final timestamp
    if current_ts is not None:
        row = {"Timestamp": current_ts}
        for col in columns:
            val = current_values[col]
            row[col] = val if not pd.isna(val) else last_row[col]
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["Timestamp", "SoC", "BMS_State", "Charging_Info", "Voltage_Delta", "Voltage_Min", "Voltage_Max", "Pack_Current"])

    df = pd.DataFrame(rows)

    return df


# =====================================================
# SUMMARY COMPUTATION (your function + small safety)
# =====================================================
def compute_imbalance_summary(df: pd.DataFrame):
    required = {"SoC", "Charging_Info", "Voltage_Delta", "BMS_State"}
    missing = required - set(df.columns)
    if missing:
        return pd.DataFrame(), f"Skipped - Required columns missing: {sorted(missing)}"

    d = df.loc[df["BMS_State"] != 0, ["SoC", "Charging_Info", "Voltage_Delta"]].copy()
    d = d.dropna(subset=["SoC", "Charging_Info", "Voltage_Delta"])

    if d.empty:
        return pd.DataFrame(), "Skipped - No valid BMS_State != 0 entries"

    mode_map = {0: "Discharging", 1: "OBC Charging", 17: "Fast Charging", 33: "Fast Charging"}
    counts = d["Charging_Info"].value_counts()
    max_count = counts.max()
    tied_codes = counts[counts == max_count].index.tolist()
    priority = [17, 33, 1, 0]
    dominant_code = next((code for code in priority if code in tied_codes), tied_codes[0])
    mode = mode_map.get(dominant_code, f"Unknown({dominant_code})")

    limits = [
        {"min": 0,  "max": 5,   "OBC Charging": 50,  "Fast Charging": 50,  "Discharging": 60},
        {"min": 5,  "max": 10,  "OBC Charging": 25,  "Fast Charging": 35,  "Discharging": 50},
        {"min": 10, "max": 90,  "OBC Charging": 20,  "Fast Charging": 35,  "Discharging": 50},
        {"min": 90, "max": 95,  "OBC Charging": 25,  "Fast Charging": 35,  "Discharging": 50},
        {"min": 95, "max": 97,  "OBC Charging": 30,  "Fast Charging": 40,  "Discharging": 70},
        {"min": 97, "max": 100, "OBC Charging": 200, "Fast Charging": 200, "Discharging": 200},
    ]

    fallback_limit = 200  # for Unknown(...)
    results = []

    for band in limits:
        band_df = d[(d["SoC"] >= band["min"]) & (d["SoC"] < band["max"])]
        voltages = band_df["Voltage_Delta"]

        limit = band.get(mode, fallback_limit)
        failed_count = int((voltages > limit).sum())

        # Keeping your original overall logic: PASS if failed_count <= 200
        status = "PASS" if failed_count <= 200 else "FAIL"

        results.append({
            "SoC (%)": f"{band['min']} to {band['max']}",
            "OBC Charging": band["OBC Charging"],
            "Fast Charging": band["Fast Charging"],
            "Discharging": band["Discharging"],
            "Voltage_Delta": (float(voltages.max()) if not voltages.empty else ""),
            "Failed_Count": failed_count,
            "Status": status,
        })

    return pd.DataFrame(results), mode

def compute_imbalance(df: pd.DataFrame):
    d = df.dropna(subset=["SoC", "Voltage_Delta", "Voltage_Min", "Voltage_Max"])
    if d.empty:
        return "", ""

    idx = d["Voltage_Delta"].idxmax()
    peak = d.loc[idx]
    peak_str = f"Peak Imbalance : {peak['Voltage_Delta']:.0f}mV (Vmax: {peak['Voltage_Max']:.0f}mV, Vmin: {peak['Voltage_Min']:.0f}mV, SoC {peak['SoC']:.2f}%)"
    avg = d["Voltage_Delta"].mean()
    avg_str = f"Average Imbalance : {avg:.0f}mV"
    return peak_str, avg_str

def save_txt(text: str):
    p = Path(__file__).resolve()

    for parent in [p] + list(p.parents):
        history = parent / "History"
        if history.exists() and history.is_dir():
            file = history / "imbalance.txt"
            with open(file, "w", encoding="utf-8") as f:
                f.write(text)
            return

    raise FileNotFoundError("History folder not found")

# =====================================================
# GRAPH PLOTTING 
# =====================================================
def plot_graph(df: pd.DataFrame, out_path: str):
    x = range(len(df))
    soc = pd.to_numeric(df["SoC"], errors="coerce")
    vmax = pd.to_numeric(df["Voltage_Max"], errors="coerce")
    vmin = pd.to_numeric(df["Voltage_Min"], errors="coerce")
    vdelta = pd.to_numeric(df["Voltage_Delta"], errors="coerce")
    current = pd.to_numeric(df["Pack_Current"], errors="coerce")

    mask = soc.notna() & vmax.notna() & vmin.notna() & vdelta.notna() & current.notna()
    x = pd.Series(x)[mask]
    soc, vmax, vmin, vdelta, current = soc[mask], vmax[mask], vmin[mask], vdelta[mask], current[mask]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    ax1.plot(x, vmax, color="blue", label="Voltage_Max")
    ax1.plot(x, vmin, color="green", label="Voltage_Min")
    ax1.set_ylabel("Voltage")
    ax1.grid()

    ax1b = ax1.twinx()
    ax1b.plot(x, vdelta, color="red", label="Voltage_Delta")
    ax1b.set_ylabel("Voltage_Delta")

    ax1.legend(loc="upper left")
    ax1b.legend(loc="upper right")

    pos_mask = current >= 0
    neg_mask = current < 0
    ax2.vlines(x[pos_mask], [0]*len(x[pos_mask]), current[pos_mask], color="green", linewidth=0.8, label="Charge (+)")
    ax2.vlines(x[neg_mask], [0]*len(x[neg_mask]), current[neg_mask], color="red", linewidth=0.8, label="Discharge (-)")

    ax2.set_xlabel("SoC (%)")
    ax2.set_ylabel("Current (A)")
    ax2.grid()
    ax2.legend()

    # SoC labels on x-axis (both plots)
    step = max(1, len(x) // 10)
    ticks = x.iloc[::step]
    labels = soc.iloc[::step].round(1)
    ax2.set_xticks(ticks)
    ax2.set_xticklabels(labels)
    ax1.set_xticks(ticks)
    ax1.set_xticklabels(labels)

    fig.suptitle("Max/Min Cell Voltages, Imbalance, and Pack Current vs SoC")

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
# =====================================================
# RESULT + SUMMARY JSON
# =====================================================
def overall_result(summary_df: pd.DataFrame) -> str:
    if summary_df.empty or "Status" not in summary_df.columns:
        return "FAIL"
    s = summary_df["Status"].astype(str).str.upper().str.strip()
    return "PASS" if (s == "PASS").all() else "FAIL"


def make_summary_lines(summary_df: pd.DataFrame, mode: str, result: str) -> list[str]:
    if summary_df.empty:
        return [f"SoC vs Voltage Summary (Mode: {mode})", f"Overall Result: {result}", "No valid data."]

    def _fmt(val):
        if pd.isna(val) or val == "":
            return "-"
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        if isinstance(val, float):
            return f"{val:.2f}".rstrip("0").rstrip(".")
        return str(val)

    max_vdelta = pd.to_numeric(summary_df["Voltage_Delta"], errors="coerce").max()
    lines = [
        f"SoC vs Voltage Summary (Mode: {mode})",
        f"Overall Result: {result}",
    ]
    if pd.notna(max_vdelta):
        lines.append(f"Max Voltage_Delta: {_fmt(max_vdelta)}")

    lines.append("Per-band details:")
    cols = ["SoC (%)", "OBC Charging", "Fast Charging", "Discharging", "Voltage_Delta", "Failed_Count", "Status"]
    for _, row in summary_df.iterrows():
        parts = [f"{col} {_fmt(row.get(col, ''))}" for col in cols if col in summary_df.columns]
        lines.append(" | ".join(parts))

    return lines


def save_outputs(summary_df: pd.DataFrame, mode: str, df: pd.DataFrame):
    cfg = OUTPUTS["SoC VS VOLTAGE SUMMARY"]

    graph_path = SCRIPT_DIR / cfg["graph"]
    summary_path = SCRIPT_DIR / cfg["summary"]
    result_path = SCRIPT_DIR / cfg["result"]

    res = overall_result(summary_df)

    # graph
    plot_graph(df, str(graph_path))

    # summary json
    summary_lines = make_summary_lines(summary_df, mode, res)
    peak_str, avg_str = compute_imbalance(df)
    vmax_raw = pd.to_numeric(df["Voltage_Max"], errors="coerce")
    max_spike = vmax_raw.max()
    state_series = df.get("Vehicle_State", None)
    mode_str = "NA"
    if state_series is not None:
        clean = state_series.dropna()
        total = len(clean)

        if total > 0:
            counts = {}
            for v in clean:
                counts[v] = counts.get(v, 0) + 1

            percent = {k: p for k, v in counts.items() if (p := round((v / total) * 100)) > 0}
            mode_str = ", ".join(
                f"{k} {v}%"
                for k, v in sorted(percent.items(), key=lambda x: x[1], reverse=True)
            )
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"Summary": summary_lines, "Peak Imbalance": peak_str, "Average Imbalance": avg_str}, f, indent=2)

    # save txt in History
    txt = (
        f"{peak_str}\n"
        f"{avg_str}\n"
        f"Max Voltage Spike: {max_spike:.0f}mV\n"
        f"Vehicle Mode: ({mode_str})"
    )
    save_txt(txt)

    # result json
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"Result": res}, f, indent=2)

    return str(result_path), str(summary_path), str(graph_path)

# =====================================================
# MAIN
# =====================================================
def main():
    # -----------------------------------------------------
    # GET TRC FROM MAIN GUI ARGUMENT / TKINTER
    # -----------------------------------------------------
    if len(sys.argv) < 2:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        trc_path = filedialog.askopenfilename(filetypes=[("TRC files", "*.trc"), ("All files", "*.*")])

        if not trc_path:
            print("ERROR: No TRC file selected!")
            sys.exit(1)
    else:
        trc_path = sys.argv[1]

    if not os.path.exists(trc_path):
        print(f"ERROR: TRC file not found: {trc_path}")
        sys.exit(1)

    print(f"Using TRC file: {trc_path}")
    print(f"Outputs will be saved next to script: {SCRIPT_DIR}")

    progress_cb = progress_by_bytes(trc_path, step=PROGRESS_STEP)

    # Parse + decode + merge
    df = trc_to_timeseries_df(trc_path, progress_cb=progress_cb)

    # Compute summary
    summary_df, mode = compute_imbalance_summary(df)

    # If compute_imbalance_summary returns "Skipped - ..." in mode, handle gracefully
    if isinstance(mode, str) and mode.startswith("Skipped"):
        empty = pd.DataFrame(columns=["SoC (%)","OBC Charging","Fast Charging","Discharging","Voltage_Delta","Failed_Count","Status"])
        result_path, summary_path, graph_path = save_outputs(empty, mode, df)
        print("Skipped:", mode)
        print("Saved:", result_path, summary_path, graph_path)
        return

    result_path, summary_path, graph_path = save_outputs(summary_df, mode, df)

    print("Done.")
    print("Result JSON :", result_path)
    print("Summary JSON:", summary_path)
    print("Graph PNG   :", graph_path)
    print("PROGRESS 100.0", flush=True)


if __name__ == "__main__":
    main()
