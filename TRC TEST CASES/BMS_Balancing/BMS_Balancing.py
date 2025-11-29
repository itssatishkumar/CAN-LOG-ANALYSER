import os
import re
import math
from datetime import datetime
from collections import defaultdict

import numpy as np
import pandas as pd
import cantools
# Lazy import for fast decoder (not available in all cantools versions)
try:
    from cantools.database.can import decoder as cantools_decoder  # type: ignore
except Exception:
    cantools_decoder = None
from tqdm import tqdm
from tkinter import Tk, filedialog

# -------------------------------------------
# CONFIG
# -------------------------------------------
TEMP_LIMIT = 95          # degC above which balancing is blocked
PENDING_TIME_SEC = 0.4   # 0.4 s window for activation / mismatch checks
# When odd/even alternate under mixed requirement, allow longer mismatch grace.
MIXED_SEQUENCE_GRACE_SEC = 1.0

# Time-based loose limits (instead of "counts")
ODD_EVEN_MAX_ON_SEC = 0.9      # ~3 counts * 300 ms
# BMS balances odd -> even (or vice-versa) sequentially, so allow a longer REST
# when both odd and even are required.
REST_COMBINED_MAX_SEC = 1.25   # sequential odd/even transition window
REST_NORMAL_MAX_SEC = 1.25     # ~4 counts * 300 ms
TIME_GAP_RESET_SEC = 5.0       # gap that resets timing state

DISCHARGE_LIMIT_TABLE = [
    (0, 5, 61),
    (5, 10, 26),
    (10, 90, 16),
    (90, 95, 26),
    (95, 97, 31),
    (97, 100, 51),
]

# Precompiled once for speed
TRC_LINE_RE = re.compile(
    r"^\s*\d+\)\s+(\d{2})-(\d{2})-(\d{4})\s+"
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+"
    r"([0-9A-Fa-f]+)\s+(\d+)\s+(.*)$"
)


# -------------------------------------------
# Helpers (vectorized-friendly)
# -------------------------------------------
def is_odd_fast(arr):
    return (np.asarray(arr, dtype=np.int64) & 1) == 1


def is_even_fast(arr):
    return (np.asarray(arr, dtype=np.int64) & 1) == 0


# -------------------------------------------
# Fast TRC -> frames
# -------------------------------------------
def parse_trc_fast(path):
    """
    High-throughput TRC parsing:
      - precompiled regex
      - manual int parsing (no strptime in loop)
      - only 1 datetime per row (constructor, not strptime)
    """
    frames = []
    base_dt = None

    with open(path, "r", encoding="utf8", errors="ignore") as f:
        for line in f:
            m = TRC_LINE_RE.match(line)
            if not m:
                continue

            # Parse ints directly from regex groups
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3))
            hour = int(m.group(4))
            minute = int(m.group(5))
            second = int(m.group(6))
            ms_str = m.group(7)
            # Interpret captured fraction as microseconds (matches original strptime behavior).
            # len 3 -> "123" -> 123000 µs; len 4 -> "1234" -> 123400 µs
            micro = int(ms_str.ljust(6, "0")[:6])

            ts_raw = f"{day:02d}-{month:02d}-{year:04d} {hour:02d}:{minute:02d}:{second:02d}.{ms_str}"

            dt = datetime(year, month, day, hour, minute, second, micro)
            if base_dt is None:
                base_dt = dt
            t = (dt - base_dt).total_seconds()

            can_id = int(m.group(8), 16)
            dlc = int(m.group(9))
            data = bytes(int(x, 16) for x in m.group(10).split()[:dlc])

            frames.append((ts_raw, t, can_id, data))

    if not frames:
        raise ValueError("❌ No CAN frames detected. Check TRC format.")

    print(f"✔ Parsed {len(frames)} frames")
    return frames


# -------------------------------------------
# Fast DBC decode -> column-first DataFrame
# -------------------------------------------
def decode_frames_fast(frames, dbc):
    """
    High-speed decode:
      - cantools Decoder (Cython) if available
      - frame_id -> message dict lookup (no repeated get)
      - column-first build via (indices, values) sparse fill to avoid per-row None work
    """
    total = len(frames)
    if total == 0:
        raise ValueError("No frames to decode.")

    # Prepare decoder and lookup
    msg_by_id = {msg.frame_id: msg for msg in dbc.messages}
    try:
        fast_decoder = cantools_decoder.Decoder(dbc) if cantools_decoder else None
    except Exception:
        fast_decoder = None

    # Sparse column storage: col -> (idx list, val list)
    idx_store = defaultdict(list)
    val_store = defaultdict(list)

    # Always-present columns
    idx_store["TimeStr"]
    val_store["TimeStr"]
    idx_store["Time"]
    val_store["Time"]
    idx_store["can_id"]
    val_store["can_id"]

    for row_idx, (ts_raw, t, cid, data) in enumerate(tqdm(frames, desc="Decoding", unit="frame")):
        # Base columns
        idx_store["TimeStr"].append(row_idx)
        val_store["TimeStr"].append(ts_raw)
        idx_store["Time"].append(row_idx)
        val_store["Time"].append(t)
        idx_store["can_id"].append(row_idx)
        val_store["can_id"].append(cid)

        msg = msg_by_id.get(cid)
        if msg is None:
            continue

        try:
            decoded = fast_decoder.decode_message(cid, data) if fast_decoder else msg.decode(data)
        except Exception:
            continue  # skip errors without exceptions per field

        for k, v in decoded.items():
            idx_store[k].append(row_idx)
            val_store[k].append(v)

    # Materialize columns; sparse reindex avoids per-row fill in the hot loop
    columns = {}
    row_index = pd.RangeIndex(total)
    for col, idxs in idx_store.items():
        vals = val_store[col]
        series = pd.Series(vals, index=idxs, dtype=object)
        columns[col] = series.reindex(row_index)

    df = pd.DataFrame(columns)
    if df.empty:
        raise ValueError("❌ DBC decode produced no rows. Check DBC & TRC.")
    return df


# -------------------------------------------
# Detect cells
# -------------------------------------------
def detect_cells(df):
    cells = sorted(int(c.split("_")[1]) for c in df.columns if c.startswith("CellVoltage_"))
    print("Cells:", cells)
    return cells


# -------------------------------------------
# Forward-fill signals (publish last known value)
# -------------------------------------------
def forward_fill_signals(df):
    if df.empty:
        return df

    # Keep base columns intact; fill the rest
    base_cols = {"TimeStr", "Time", "can_id"}
    fill_cols = [c for c in df.columns if c not in base_cols]

    # Ensure time ordering before filling
    if "Time" in df.columns:
        df = df.sort_values("Time").reset_index(drop=True)

    df[fill_cols] = df[fill_cols].ffill()
    return df


# -------------------------------------------
# Dead cells / thermistors (vectorized)
# -------------------------------------------
def find_dead_cells(df, cells):
    dead_mask = []
    for c in cells:
        col = f"CellVoltage_{c}"
        if col not in df.columns:
            continue
        med = pd.to_numeric(df[col], errors="coerce").fillna(0).median()
        dead_mask.append((c, med < 5))
    dead = {c for c, is_dead in dead_mask if is_dead}
    print("Dead cells:", sorted(dead))
    return dead


def find_dead_therms(df, zero_threshold=0.1):
    dead = set()
    for col in df.columns:
        if col.startswith("IntTherm_"):
            med = pd.to_numeric(df[col], errors="coerce").fillna(0).median()
            if med <= zero_threshold:
                idx = int(col.split("_")[1])
                dead.add(idx)
    if dead:
        print("Dead thermistors:", sorted(dead))
    return dead


# -------------------------------------------
# Balancing threshold (SoC / mode)
# -------------------------------------------
def get_threshold(mode, soc):
    if mode == "Charging":
        return 11
    try:
        soc_val = float(soc)
    except Exception:
        return None
    for lo, hi, val in DISCHARGE_LIMIT_TABLE:
        if lo <= soc_val < hi:
            return val
    return None


# -------------------------------------------
# Decode masks (no try/except in hot path)
# -------------------------------------------
def mask_decode(m0, m1):
    try:
        m0i = int(m0)
    except Exception:
        m0i = 0
    try:
        m1i = int(m1)
    except Exception:
        m1i = 0

    act = []
    # unroll in two loops (fast bit checks)
    for i in range(64):
        if (m0i >> i) & 1:
            act.append(i + 1)
    for i in range(64):
        if (m1i >> i) & 1:
            act.append(65 + i)
    return act


# -------------------------------------------
# Analyze rows (itertuples, column-first output)
# -------------------------------------------
def analyze_fast(df, cells, dead_cells, dead_therms):
    # Precompute helpers
    live_cells = [c for c in cells if c not in dead_cells]
    therm_cols = [c for c in df.columns if c.startswith("IntTherm_")]
    live_therm_idxs = [int(c.split("_")[1]) for c in therm_cols if int(c.split("_")[1]) not in dead_therms]

    # Output column stores
    out = {
        "TimeStr": [], "Time": [], "SoC": [], "Pack_Current": [], "Charging_Info": [],
        "Flag_Balancing_Active": [], "Balancing_Limit": [], "Voltage_Min": [],
        "Voltage_Max": [], "Voltage_Delta": [], "BalancingMask0": [], "BalancingMask1": [],
        "Mode": [], "Threshold": [], "Temp_Block": [], "PCB_Temp_Min": [], "PCB_Temp_Max": [],
        "Balancing_Required": [], "Required_Cells": [], "Active_Cells": [],
        "Missing": [], "Extra": [], "Dead_Cells": [], "Dead_Therms": []
    }

    # Dynamic cell/therm columns
    cell_cols = {c: [] for c in live_cells}
    therm_cols_live = {c: [] for c in live_therm_idxs}

    # Process rows using itertuples (fast attribute access)
    # Build positional mapping once for tuple lookups
    columns = list(df.columns)
    col_idx = {c: i for i, c in enumerate(columns)}
    get = lambda r, name, default=None: r[col_idx[name]] if name in col_idx else default

    for r in df.itertuples(index=False, name=None):
        time_str = get(r, "TimeStr")
        time_val = get(r, "Time", 0.0)
        soc = get(r, "SoC")
        pack_current = get(r, "Pack_Current")
        charging_info = get(r, "Charging_Info")
        flag_bal = get(r, "Flag_Balancing_Active")
        bal_limit = get(r, "Balancing_Limit")
        vmin = get(r, "Voltage_Min")
        vmax = get(r, "Voltage_Max")
        vdelta = get(r, "Voltage_Delta")
        bm0 = get(r, "BalancingMask0")
        bm1 = get(r, "BalancingMask1")

        # Mode
        mode = "Unknown"
        try:
            ci_int = int(float(charging_info))
            if ci_int in (1, 17, 33):
                mode = "Charging"
            elif ci_int == 0:
                mode = "Discharging"
            else:
                mode = "Ready"
        except Exception:
            pass

        threshold = get_threshold(mode, soc)

        # Temps (live only)
        temps = []
        for col, idx in zip([c for c in therm_cols if int(c.split("_")[1]) in live_therm_idxs], live_therm_idxs):
            try:
                temps.append(float(get(r, col)))
            except Exception:
                pass
        temp_block = any(t > TEMP_LIMIT for t in temps)
        pcb_min = min(temps) if temps else None
        pcb_max = max(temps) if temps else None

        # Required?
        required = False
        try:
            if vmin is not None and vmax is not None and bal_limit is not None and threshold is not None and not temp_block:
                if float(vmin) >= float(bal_limit) and (float(vmax) - float(vmin)) >= threshold:
                    required = True
        except Exception:
            pass

        # Required cells
        req_cells = []
        if required and vmin is not None and threshold is not None:
            vmin_f = float(vmin)
            thr_f = float(threshold)
            for c in live_cells:
                col = f"CellVoltage_{c}"
                val = get(r, col)
                if val is not None:
                    try:
                        if float(val) >= vmin_f + thr_f:
                            req_cells.append(c)
                    except Exception:
                        pass

        # Active from masks
        active_cells = mask_decode(bm0, bm1)
        missing = sorted(set(req_cells) - set(active_cells))
        extra = sorted(set(active_cells) - set(req_cells))

        # Store outputs
        out["TimeStr"].append(time_str)
        out["Time"].append(time_val)
        out["SoC"].append(soc)
        out["Pack_Current"].append(pack_current)
        out["Charging_Info"].append(charging_info)
        out["Flag_Balancing_Active"].append(flag_bal)
        out["Balancing_Limit"].append(bal_limit)
        out["Voltage_Min"].append(vmin)
        out["Voltage_Max"].append(vmax)
        out["Voltage_Delta"].append(vdelta)
        out["BalancingMask0"].append(bm0)
        out["BalancingMask1"].append(bm1)
        out["Mode"].append(mode)
        out["Threshold"].append(threshold)
        out["Temp_Block"].append(temp_block)
        out["PCB_Temp_Min"].append(pcb_min)
        out["PCB_Temp_Max"].append(pcb_max)
        out["Balancing_Required"].append("YES" if required else "NO")
        out["Required_Cells"].append(req_cells)
        out["Active_Cells"].append(active_cells)
        out["Missing"].append(missing)
        out["Extra"].append(extra)
        out["Dead_Cells"].append(sorted(dead_cells))
        out["Dead_Therms"].append(sorted(dead_therms))

        # Live cell voltages
        for c in live_cells:
            col = f"CellVoltage_{c}"
            cell_cols[c].append(get(r, col))

        # Live therms
        for idx in live_therm_idxs:
            col = f"IntTherm_{idx}"
            therm_cols_live[idx].append(get(r, col))

    # Merge all outputs
    out_df = pd.DataFrame(out)
    for c, vals in cell_cols.items():
        out_df[f"CellVoltage_{c}"] = vals
    for idx, vals in therm_cols_live.items():
        out_df[f"IntTherm_{idx}"] = vals

    return out_df


# -------------------------------------------
# PASS/FAIL timing (itertuples)
# -------------------------------------------
def add_pass_fail_fast(df):
    if df.empty:
        return df

    df = df.sort_values("Time").reset_index(drop=True)
    passfail = ["PASS"] * len(df)
    remark = ["OK"] * len(df)

    def mark_fail(i, reason):
        if i < 0 or i >= len(df):
            return
        if passfail[i] == "PASS":
            passfail[i] = "FAIL"
            remark[i] = reason
        else:
            if reason not in remark[i]:
                remark[i] = f"{remark[i]} | {reason}"

    pending_activation_start_time = None
    mismatch_start_time = None
    mismatch_active = False
    mismatch_reason_cached = ""

    current_seg_state = None
    current_seg_start_idx = None
    current_seg_start_time = None
    seg_req_odd = False
    seg_req_even = False

    def finalize_segment(end_idx):
        nonlocal current_seg_state, current_seg_start_idx, current_seg_start_time, seg_req_odd, seg_req_even
        if current_seg_state is None or current_seg_start_idx is None:
            return
        if end_idx < current_seg_start_idx:
            return
        start_t = current_seg_start_time
        end_t = df.at[end_idx, "Time"] if 0 <= end_idx < len(df) else start_t
        duration = max(0.0, end_t - start_t)
        state = current_seg_state
        if state == "ODD" and duration > ODD_EVEN_MAX_ON_SEC:
            mark_fail(end_idx, f"ODD balancing ON too long: {duration:.3f}s")
        elif state == "EVEN" and duration > ODD_EVEN_MAX_ON_SEC:
            mark_fail(end_idx, f"EVEN balancing ON too long: {duration:.3f}s")
        elif state == "REST":
            if seg_req_odd and seg_req_even:
                if duration > REST_COMBINED_MAX_SEC:
                    mark_fail(end_idx, f"REST (odd/even sequence) too long: {duration:.3f}s")
            else:
                if duration > REST_NORMAL_MAX_SEC:
                    mark_fail(end_idx, f"REST (normal) too long: {duration:.3f}s")
        current_seg_state = None
        current_seg_start_idx = None
        current_seg_start_time = None
        seg_req_odd = False
        seg_req_even = False

    prev_t = None

    for i, row in enumerate(df.itertuples(index=False)):
        t = row.Time if row.Time is not None else 0.0
        required = (row.Balancing_Required == "YES")

        flag_raw = row.Flag_Balancing_Active
        flag_txt = str(flag_raw).strip().lower()
        if flag_txt in ("active", "1", "true", "yes"):
            flag_active = True
        elif flag_txt in ("inactive", "0", "false", "no"):
            flag_active = False
        else:
            try:
                flag_active = float(flag_raw) != 0
            except Exception:
                flag_active = False

        req_cells = row.Required_Cells or []
        active_cells = row.Active_Cells or []
        missing = row.Missing or []
        extra = row.Extra or []
        has_req_odd_row = any((c & 1) == 1 for c in req_cells)
        has_req_even_row = any((c & 1) == 0 for c in req_cells)
        has_odd_act = any((c & 1) == 1 for c in active_cells)
        has_even_act = any((c & 1) == 0 for c in active_cells)

        # Gap reset
        if prev_t is not None:
            gap = t - prev_t
            if gap > TIME_GAP_RESET_SEC:
                finalize_segment(i - 1)
                pending_activation_start_time = None
                mismatch_start_time = None
                mismatch_active = False
                mismatch_reason_cached = ""
                current_seg_state = None
                current_seg_start_idx = None
                current_seg_start_time = None
                seg_req_odd = False
                seg_req_even = False
        prev_t = t

        # 1) Activation timing
        if required and not flag_active:
            if pending_activation_start_time is None:
                pending_activation_start_time = t
            else:
                if t - pending_activation_start_time > PENDING_TIME_SEC:
                    mark_fail(i, "Balancing active flag not set within 0.4s of requirement")
        else:
            pending_activation_start_time = None

        # 2) Missing / extra timing
        mismatch_now = False
        reasons = []
        if required and flag_active:
            if active_cells:
                if missing:
                    mismatch_now = True
                    reasons.append(f"Missing cells: {missing}")
                if extra:
                    mismatch_now = True
                    reasons.append(f"Extra cells: {extra}")
        else:
            if active_cells:
                mismatch_now = True
                reasons.append(f"Unexpected active cells when balancing not required: {active_cells}")

        if mismatch_now:
            if not mismatch_active:
                mismatch_active = True
                mismatch_start_time = t
                mismatch_reason_cached = ", ".join(reasons)
            else:
                # If the mismatch type changes (e.g., different missing/extra set), restart the timer
                current_reason = ", ".join(reasons)
                if current_reason != mismatch_reason_cached:
                    mismatch_start_time = t
                    mismatch_reason_cached = current_reason
                grace = PENDING_TIME_SEC
                if required and flag_active and has_req_odd_row and has_req_even_row:
                    # allow more time when alternating parity under mixed requirement
                    if has_odd_act ^ has_even_act:
                        grace = MIXED_SEQUENCE_GRACE_SEC
                if t - mismatch_start_time > grace:
                    mark_fail(i, f"Cell mismatch >{grace:.1f}s: " + mismatch_reason_cached)
        else:
            mismatch_active = False
            mismatch_start_time = None
            mismatch_reason_cached = ""

        # 3) ODD/EVEN/REST segments
        if required and flag_active:
            # When both odd and even are required, active set must not mix parities at once.
            if has_req_odd_row and has_req_even_row and has_odd_act and has_even_act:
                mark_fail(i, "Active cells include both odd and even while mixed requirement should alternate")
            if not active_cells:
                state = "REST"
            elif has_odd_act and not has_even_act:
                state = "ODD"
            elif has_even_act and not has_odd_act:
                state = "EVEN"
            else:
                state = None
        else:
            state = None

        if state is None:
            finalize_segment(i - 1)
        else:
            if current_seg_state is None:
                current_seg_state = state
                current_seg_start_idx = i
                current_seg_start_time = t
                seg_req_odd = has_req_odd_row
                seg_req_even = has_req_even_row
            else:
                if state == current_seg_state:
                    seg_req_odd = seg_req_odd or has_req_odd_row
                    seg_req_even = seg_req_even or has_req_even_row
                else:
                    finalize_segment(i - 1)
                    current_seg_state = state
                    current_seg_start_idx = i
                    current_seg_start_time = t
                    seg_req_odd = has_req_odd_row
                    seg_req_even = has_req_even_row

    finalize_segment(len(df) - 1)
    df["PassFail"] = passfail
    df["Remark"] = remark
    return df


# -------------------------------------------
# Split and save CSV (chunked, pyarrow if available)
# -------------------------------------------
def split_and_save_csv(df, trc_path, max_rows=1_000_000, chunksize=250_000):
    """
    Writes CSV in parts of <= max_rows rows each.
    Uses pyarrow csv writer if available; else pandas.to_csv with chunksize.
    """
    base_dir = os.path.dirname(trc_path)
    trc_name = os.path.splitext(os.path.basename(trc_path))[0]

    total_rows = len(df)
    if total_rows == 0:
        return

    use_pyarrow = False
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.csv as pacsv  # type: ignore
        use_pyarrow = True
    except Exception:
        use_pyarrow = False

    num_parts = (total_rows + max_rows - 1) // max_rows
    for part in range(num_parts):
        start = part * max_rows
        end = min(start + max_rows, total_rows)
        chunk = df.iloc[start:end]
        out_csv = os.path.join(base_dir, f"{trc_name}_balancing_summary_part{part + 1}.csv")

        if use_pyarrow:
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            pacsv.write_csv(table, out_csv)
        else:
            chunk.to_csv(out_csv, index=False, chunksize=chunksize)
        print(f"✔ Saved: {out_csv}  ({len(chunk)} rows)")


# -------------------------------------------
# Run full analysis
# -------------------------------------------
def run(df, path):
    cells = detect_cells(df)
    dead_cells = find_dead_cells(df, cells)
    dead_therms = find_dead_therms(df)

    analyzed = analyze_fast(df, cells, dead_cells, dead_therms)
    analyzed = add_pass_fail_fast(analyzed)

    # ---- Save CSV with auto-splitting (10 lakh rows per file) ----
    split_and_save_csv(analyzed, path, max_rows=1_000_000)


# -------------------------------------------
# MAIN
# -------------------------------------------
def main():
    Tk().withdraw()

    print("📂 Select TRC")
    trc = filedialog.askopenfilename(filetypes=[("TRC files", "*.trc")])
    if not trc:
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    dbc_path = os.path.join(script_dir, "balancing.dbc")

    if not os.path.isfile(dbc_path):
        print(f"❌ balancing.dbc not found at {dbc_path}")
        return

    dbc = cantools.database.load_file(dbc_path)

    frames = parse_trc_fast(trc)
    df = decode_frames_fast(frames, dbc)
    df = forward_fill_signals(df)
    run(df, trc)


if __name__ == "__main__":
    main()
