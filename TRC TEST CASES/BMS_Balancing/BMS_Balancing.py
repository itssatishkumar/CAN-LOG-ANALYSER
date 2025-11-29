import os
import re
from datetime import datetime
import cantools
import pandas as pd
from tqdm import tqdm
from tkinter import Tk, filedialog

# -------------------------------------------
# CONFIG
# -------------------------------------------
TEMP_LIMIT = 95          # degC above which balancing is blocked
PENDING_TIME_SEC = 0.4   # 0.4 s window for activation / mismatch checks

# Time-based loose limits (instead of "counts")
ODD_EVEN_MAX_ON_SEC = 0.9      # ~3 counts * 300 ms
REST_COMBINED_MAX_SEC = 0.6    # ~2 counts * 300 ms
REST_NORMAL_MAX_SEC = 1.25      # ~4 counts * 300 ms

DISCHARGE_LIMIT_TABLE = [
    (0, 5, 61),
    (5, 10, 26),
    (10, 90, 16),
    (90, 95, 26),
    (95, 97, 31),
    (97, 100, 51),
]

TRC_LINE_RE = re.compile(
    r"^\s*\d+\)\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})\.(\d{3,4})(?:\.\d+)?\s+\w+\s+([0-9A-Fa-f]+)\s+(\d+)\s+(.*)$"
)


# -------------------------------------------
# Helpers
# -------------------------------------------
def is_odd(cell):
    try:
        return (int(cell) % 2) == 1
    except Exception:
        return False


def is_even(cell):
    try:
        return (int(cell) % 2) == 0
    except Exception:
        return False


# -------------------------------------------
# TRC → frames
# -------------------------------------------
def parse_trc(path):
    frames = []
    base = None

    with open(path, "r", encoding="utf8", errors="ignore") as f:
        for line in f:
            m = TRC_LINE_RE.match(line.strip())
            if not m:
                continue

            date_part = m.group(1)
            time_part = m.group(2)
            ms_part = m.group(3)
            ts_raw = f"{date_part} {time_part}.{ms_part}"
            ms_norm = ms_part if len(ms_part) == 4 else ms_part + "0" if len(ms_part) == 3 else ms_part
            ts = f"{date_part} {time_part}.{ms_norm}"

            dt = datetime.strptime(ts, "%d-%m-%Y %H:%M:%S.%f")
            if base is None:
                base = dt

            t = (dt - base).total_seconds()

            can_id = int(m.group(4), 16)
            dlc = int(m.group(5))
            data = bytes(int(x, 16) for x in m.group(6).split()[:dlc])

            frames.append((ts_raw, t, can_id, data))

    if not frames:
        raise ValueError("❌ No CAN frames detected. Check TRC format.")

    print(f"✔ Parsed {len(frames)} frames")
    return frames


# -------------------------------------------
# DBC decode (last-known; safe, per-message update)
# -------------------------------------------
def decode(frames, dbc):
    """
    Decode frames with DBC; carry forward last-known values.

    Rules:
      - One output row per TRC frame.
      - Only update signals that belong to the decoded message.
      - Never touch other signals if this message doesn't contain them.
      - Never force any signal to 0 unless DBC decode returns 0.
    """
    last = {}
    rows = []

    for ts_raw, t, cid, data in tqdm(frames, desc="Decoding"):
        # 1) Try to get message by frame-id
        try:
            msg = dbc.get_message_by_frame_id(cid)
        except KeyError:
            msg = None

        # 2) If message exists, decode it
        if msg is not None:
            try:
                decoded = msg.decode(data)
            except Exception:
                decoded = {}

            # Update ONLY signals that belong to this message
            for sig in msg.signals:
                name = sig.name
                if name in decoded:
                    last[name] = decoded[name]
                # if name not in decoded: keep previous last[name] as-is

        # 3) Always update time
        last["TimeStr"] = ts_raw
        last["Time"] = t

        # 4) Append snapshot of full state
        rows.append(last.copy())

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("❌ DBC decode produced no rows. Check DBC & TRC.")
    return df


# -------------------------------------------
# Detect cells
# -------------------------------------------
def detect_cells(df):
    cells = sorted(
        int(c.split("_")[1]) for c in df.columns if c.startswith("CellVoltage_")
    )
    print("Cells:", cells)
    return cells


# -------------------------------------------
# Dead cells (median < 5mV)
# -------------------------------------------
def find_dead_cells(df, cells):
    dead = []
    for c in cells:
        col = f"CellVoltage_{c}"
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").fillna(0)
        med = series.median()
        if med < 5:
            dead.append(c)
    print("Dead cells:", dead)
    return set(dead)


# -------------------------------------------
# Dead thermistors (IntTherm_x ≈ 0°C entire log)
# -------------------------------------------
def find_dead_therms(df, zero_threshold=0.1):
    dead = set()
    for col in df.columns:
        if col.startswith("IntTherm_"):
            series = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if series.median() <= zero_threshold:
                try:
                    idx = int(col.split("_")[1])
                    dead.add(idx)
                except Exception:
                    pass
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
        soc = float(soc)
    except Exception:
        return None
    for lo, hi, val in DISCHARGE_LIMIT_TABLE:
        if lo <= soc < hi:
            return val
    return None


# -------------------------------------------
# Decode masks
# -------------------------------------------
def mask_decode(m0, m1):
    try:
        m0 = int(m0)
    except Exception:
        m0 = 0
    try:
        m1 = int(m1)
    except Exception:
        m1 = 0

    act = []
    for i in range(64):
        if (m0 >> i) & 1:
            act.append(i + 1)
    for i in range(64):
        if (m1 >> i) & 1:
            act.append(65 + i)
    return act


# -------------------------------------------
# Analyze one row (static analysis, no timing)
# -------------------------------------------
def analyze(row, cells, dead_cells, dead_therms):
    res = {}

    # Raw carry-over fields (as-is from decode)
    res["TimeStr"] = row.get("TimeStr")
    res["Time"] = row.get("Time")
    res["SoC"] = row.get("SoC")
    res["Pack_Current"] = row.get("Pack_Current")
    res["Charging_Info"] = row.get("Charging_Info")
    res["Flag_Balancing_Active"] = row.get("Flag_Balancing_Active")   # AS-IS
    res["Balancing_Limit"] = row.get("Balancing_Limit")
    res["Voltage_Min"] = row.get("Voltage_Min")
    res["Voltage_Max"] = row.get("Voltage_Max")
    res["Voltage_Delta"] = row.get("Voltage_Delta")
    res["BalancingMask0"] = row.get("BalancingMask0")
    res["BalancingMask1"] = row.get("BalancingMask1")

    vmin = row.get("Voltage_Min")
    vmax = row.get("Voltage_Max")
    limit = row.get("Balancing_Limit")

    # Determine mode from Charging_Info
    ci = row.get("Charging_Info")
    try:
        ci_int = int(float(ci))
        if ci_int in (1, 17, 33):
            mode = "Charging"
        elif ci_int == 0:
            mode = "Discharging"
        else:
            mode = "Ready"
    except Exception:
        ci_int = None
        mode = "Unknown"

    res["Mode"] = mode

    # Threshold
    threshold = get_threshold(mode, res["SoC"])
    res["Threshold"] = threshold

    # Temp block (using only LIVE IntTherm_x, skipping dead therms)
    temps = []
    for col in row.index:
        if col.startswith("IntTherm_"):
            try:
                idx = int(col.split("_")[1])
            except Exception:
                continue
            if idx in dead_therms:
                continue
            try:
                val = float(row[col])
                temps.append(val)
            except Exception:
                pass

    temp_block = any(t > TEMP_LIMIT for t in temps)
    res["Temp_Block"] = temp_block
    res["PCB_Temp_Min"] = min(temps) if temps else None
    res["PCB_Temp_Max"] = max(temps) if temps else None

    # Balancing required?
    required = False
    try:
        if (
            vmin is not None
            and vmax is not None
            and limit is not None
            and threshold is not None
            and not temp_block
        ):
            if float(vmin) >= float(limit) and (float(vmax) - float(vmin)) >= threshold:
                required = True
    except Exception:
        pass

    res["Balancing_Required"] = "YES" if required else "NO"

    # Required cells
    req = []
    if required and vmin is not None and threshold is not None:
        for c in cells:
            if c in dead_cells:
                continue
            col = f"CellVoltage_{c}"
            if col in row.index:
                try:
                    if float(row[col]) >= float(vmin) + threshold:
                        req.append(c)
                except Exception:
                    pass
    res["Required_Cells"] = req

    # Active cells from masks
    act = mask_decode(row.get("BalancingMask0"), row.get("BalancingMask1"))
    res["Active_Cells"] = act

    res["Missing"] = sorted(set(req) - set(act))
    res["Extra"] = sorted(set(act) - set(req))

    # Dead info
    res["Dead_Cells"] = sorted(list(dead_cells))
    res["Dead_Therms"] = sorted(list(dead_therms))

    # Attach live cell voltages (except dead)
    for c in cells:
        if c not in dead_cells:
            col = f"CellVoltage_{c}"
            if col in row.index:
                res[col] = row.get(col)

    # Attach live thermistors (exclude dead ones)
    for col in sorted([c for c in row.index if c.startswith("IntTherm_")]):
        try:
            idx = int(col.split("_")[1])
        except Exception:
            continue
        if idx in dead_therms:
            continue
        res[col] = row.get(col)

    return res


# -------------------------------------------
# PASS/FAIL timing & logic (row-wise, with state)
# -------------------------------------------
def add_pass_fail(df):
    """
    Adds two columns:
      - PassFail: "PASS"/"FAIL"
      - Remark:   explanation

    Using:
      * 0.4 s limit for activation + cell mismatch
      * ODD/EVEN ON max ~0.9 s
      * REST (combined) max ~0.6 s
      * REST (normal)   max ~1.25 s
    All based on REAL TRC time differences, not row counts.
    """
    if df.empty:
        return df

    df = df.sort_values("Time").reset_index(drop=True)
    df["PassFail"] = "PASS"
    df["Remark"] = "OK"

    def mark_fail(idx, reason):
        if idx is None or idx < 0 or idx >= len(df):
            return
        if df.at[idx, "PassFail"] == "PASS":
            df.at[idx, "PassFail"] = "FAIL"
            df.at[idx, "Remark"] = reason
        else:
            existing = df.at[idx, "Remark"]
            if reason not in str(existing):
                df.at[idx, "Remark"] = f"{existing} | {reason}"

    # ---- 1) Activation timing: required -> Flag_Balancing_Active within 0.4 s
    pending_activation_start_time = None

    # ---- 2) Missing/Extra cells timing: mismatch must not persist >0.4 s
    mismatch_start_time = None
    mismatch_active = False
    mismatch_reason_cached = ""

    # ---- 3) ODD/EVEN/REST segment timing (time-based)
    current_seg_state = None   # "ODD", "EVEN", "REST"
    current_seg_start_idx = None
    current_seg_start_time = None
    seg_req_odd = False
    seg_req_even = False

    def finalize_segment(end_idx):
        nonlocal current_seg_state, current_seg_start_idx, current_seg_start_time
        nonlocal seg_req_odd, seg_req_even

        if current_seg_state is None or current_seg_start_idx is None:
            return

        if end_idx < current_seg_start_idx:
            return

        start_t = current_seg_start_time
        end_t = df.at[end_idx, "Time"] if 0 <= end_idx < len(df) else start_t
        duration = max(0.0, end_t - start_t)

        state = current_seg_state
        has_req_odd = seg_req_odd
        has_req_even = seg_req_even

        if state == "ODD":
            if duration > ODD_EVEN_MAX_ON_SEC:
                mark_fail(end_idx, f"ODD balancing ON too long: {duration:.3f}s")
        elif state == "EVEN":
            if duration > ODD_EVEN_MAX_ON_SEC:
                mark_fail(end_idx, f"EVEN balancing ON too long: {duration:.3f}s")
        elif state == "REST":
            if has_req_odd and has_req_even:
                if duration > REST_COMBINED_MAX_SEC:
                    mark_fail(end_idx, f"REST (combined) too long: {duration:.3f}s")
            else:
                if duration > REST_NORMAL_MAX_SEC:
                    mark_fail(end_idx, f"REST (normal) too long: {duration:.3f}s")

        current_seg_state = None
        current_seg_start_idx = None
        current_seg_start_time = None
        seg_req_odd = False
        seg_req_even = False

    # ---- iterate rows
    for i, row in df.iterrows():
        t = row.get("Time", 0.0)
        required = (row.get("Balancing_Required") == "YES")

        # Handle flag as text or numeric: "Active"/"InActive"/1/0/True/False
        flag_raw = row.get("Flag_Balancing_Active")
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

        req_cells = row.get("Required_Cells") or []
        active_cells = row.get("Active_Cells") or []
        missing = row.get("Missing") or []
        extra = row.get("Extra") or []

        # 1) Activation timing check
        if required and not flag_active:
            if pending_activation_start_time is None:
                pending_activation_start_time = t
            else:
                if t - pending_activation_start_time > PENDING_TIME_SEC:
                    mark_fail(i, "Balancing active flag not set within 0.4s of requirement")
        else:
            pending_activation_start_time = None

        # 2) Missing / Extra cell timing check
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
                if t - mismatch_start_time > PENDING_TIME_SEC:
                    mark_fail(i, "Cell mismatch >0.4s: " + mismatch_reason_cached)
        else:
            mismatch_active = False
            mismatch_start_time = None
            mismatch_reason_cached = ""

        # 3) ODD / EVEN / REST segment detection (only when flag is active and balancing required)
        if required and flag_active:
            has_odd_act = any(is_odd(c) for c in active_cells)
            has_even_act = any(is_even(c) for c in active_cells)

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

        has_req_odd_row = any(is_odd(c) for c in req_cells)
        has_req_even_row = any(is_even(c) for c in req_cells)

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

    return df


# -------------------------------------------
# Run full analysis
# -------------------------------------------
def run(df, path):
    cells = detect_cells(df)
    dead_cells = find_dead_cells(df, cells)
    dead_therms = find_dead_therms(df)

    out_rows = []
    for _, row in df.iterrows():
        out_rows.append(analyze(row, cells, dead_cells, dead_therms))

    out = pd.DataFrame(out_rows)

    out = add_pass_fail(out)

    out_xlsx = os.path.join(os.path.dirname(path), "balancing_summary.xlsx")
    out.to_excel(out_xlsx, index=False)
    print("✔ Saved:", out_xlsx)


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

    frames = parse_trc(trc)
    df = decode(frames, dbc)

    run(df, trc)


if __name__ == "__main__":
    main()
