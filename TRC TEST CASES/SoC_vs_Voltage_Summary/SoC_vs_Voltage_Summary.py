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
        # SoC: bytes 0-1 Intel, sf=0.01
        soc = u16_le(data[0], data[1]) * 0.01
        # BMS_State: byte 4
        bms_state = data[4]
        return {"SoC": soc, "BMS_State": bms_state}

    if canid == 0x0602:
        # Charging_Info: startbit 48 len 8 => byte 6 (second-last byte)
        charging_info = data[6]
        return {"Charging_Info": charging_info}

    if canid == 0x012C:
        # Voltage_Delta: 32|16 Intel => bytes 4-5, sf=0.1
        vdelta = u16_le(data[4], data[5]) * 0.1
        return {"Voltage_Delta": vdelta}

    return {}


# =====================================================
# TRC -> DataFrame (merged by timestamp)
# =====================================================
def trc_to_timeseries_df(trc_path: str, progress_cb=None) -> pd.DataFrame:
    needed_ids = {0x0109, 0x0602, 0x012C}
    columns = ("SoC", "BMS_State", "Charging_Info", "Voltage_Delta")
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
                    last_row = row
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
        return pd.DataFrame(columns=["Timestamp", "SoC", "BMS_State", "Charging_Info", "Voltage_Delta"])

    df = pd.DataFrame(rows)

    # If BMS_State is 0, invalidate SoC (set to NA)
    df.loc[df["BMS_State"] == 0, "SoC"] = pd.NA

    return df


# =====================================================
# SUMMARY COMPUTATION (your function + small safety)
# =====================================================
def compute_imbalance_summary(df: pd.DataFrame):
    required = {"SoC", "Charging_Info", "Voltage_Delta", "BMS_State"}
    missing = required - set(df.columns)
    if missing:
        return pd.DataFrame(), f"Skipped - Required columns missing: {sorted(missing)}"

    d = df.loc[df["BMS_State"] == 3, ["SoC", "Charging_Info", "Voltage_Delta"]].copy()
    d = d.dropna(subset=["SoC", "Charging_Info", "Voltage_Delta"])

    if d.empty:
        return pd.DataFrame(), "Skipped - No valid BMS_State == 3 entries"

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


# =====================================================
# TABLE PNG (graph output)
# =====================================================
def save_soc_voltage_summary_table_png(summary_df: pd.DataFrame, mode: str, out_path: str):
    df = summary_df.copy()

    # Format display
    if "Voltage_Delta" in df.columns:
        df["Voltage_Delta"] = df["Voltage_Delta"].apply(
            lambda x: "" if x == "" or pd.isna(x) else f"{float(x):.0f}"
        )
    if "Failed_Count" in df.columns:
        df["Failed_Count"] = df["Failed_Count"].apply(
            lambda x: "" if x == "" or pd.isna(x) else str(int(x))
        )

    col_labels = df.columns.tolist()
    cell_text = df.values.tolist()

    fig_w = max(10, 1.3 * len(col_labels))
    fig_h = max(2.8, 0.6 + 0.45 * (len(df) + 1))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")

    title = f"SoC vs Voltage Summary (Mode: {mode})"

    table = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        cellLoc="center",
        colLoc="center",
        loc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 1.6)

    header_color = "#d9e1f2"
    status_ok = "#d8f3dc"
    highlight_color = "#ffe699"
    title_bar_color = "#00b050"

    # Header styling + borders
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#bfbfbf")
        cell.set_linewidth(0.8)
        if r == 0:
            cell.set_facecolor(header_color)
            cell.set_text_props(fontweight="bold")

    # Highlight the column for the active mode if present
    highlight_col = mode if mode in df.columns else None
    if highlight_col:
        hc = df.columns.get_loc(highlight_col)
        for r in range(1, len(df) + 1):
            table[(r, hc)].set_facecolor(highlight_color)

    # Green status cells for PASS
    if "Status" in df.columns:
        sc = df.columns.get_loc("Status")
        for r in range(1, len(df) + 1):
            val = str(df.iloc[r - 1, sc]).strip().upper()
            if val == "PASS":
                table[(r, sc)].set_facecolor(status_ok)

    # Title bar
    ax.add_patch(
        plt.Rectangle((0, 1.02), 1, 0.12, transform=ax.transAxes, clip_on=False, linewidth=0, facecolor=title_bar_color)
    )
    ax.text(0.5, 1.08, title, transform=ax.transAxes, ha="center", va="center",
            fontsize=14, fontweight="bold", color="white")

    plt.tight_layout()
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


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


def save_outputs(summary_df: pd.DataFrame, mode: str):
    cfg = OUTPUTS["SoC VS VOLTAGE SUMMARY"]

    graph_path = SCRIPT_DIR / cfg["graph"]
    summary_path = SCRIPT_DIR / cfg["summary"]
    result_path = SCRIPT_DIR / cfg["result"]

    res = overall_result(summary_df)

    # graph/table
    save_soc_voltage_summary_table_png(summary_df, mode, str(graph_path))

    # summary json (row-wise + combined text)
    summary_lines = make_summary_lines(summary_df, mode, res)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"Summary": summary_lines}, f, indent=2)

    # result json (PASS/FAIL)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"Result": res}, f, indent=2)

    return str(result_path), str(summary_path), str(graph_path)


# =====================================================
# MAIN
# =====================================================
def main():
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

    print(f"Using TRC file from GUI: {trc_path}")
    print(f"Outputs will be saved next to script: {SCRIPT_DIR}")

    progress_cb = progress_by_bytes(trc_path, step=PROGRESS_STEP)

    # Parse + decode + merge
    df = trc_to_timeseries_df(trc_path, progress_cb=progress_cb)

    # Compute summary
    summary_df, mode = compute_imbalance_summary(df)

    # If compute_imbalance_summary returns "Skipped - ..." in mode, handle gracefully
    if isinstance(mode, str) and mode.startswith("Skipped"):
        # save minimal outputs anyway
        empty = pd.DataFrame(columns=["SoC (%)","OBC Charging","Fast Charging","Discharging","Voltage_Delta","Failed_Count","Status"])
        result_path, summary_path, graph_path = save_outputs(empty, mode)
        print("Skipped:", mode)
        print("Saved:", result_path, summary_path, graph_path)
        return

    result_path, summary_path, graph_path = save_outputs(summary_df, mode)

    print("Done.")
    print("Result JSON :", result_path)
    print("Summary JSON:", summary_path)
    print("Graph PNG   :", graph_path)
    print("PROGRESS 100.0", flush=True)


if __name__ == "__main__":
    main()
