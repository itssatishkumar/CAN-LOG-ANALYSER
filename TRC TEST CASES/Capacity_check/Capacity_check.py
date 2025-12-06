import re
import struct
import sys
import tkinter as tk
from tkinter import filedialog
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


# =========================================================
#  THERM CAN MAP (per-sensor temps)
#  NOTE: Tavg remains from 0x014E as in your original logic.
# =========================================================
THERM_CAN_MAP = {
    1:  (0x0112, [0, 1, 2, 3, 4, 5]),              # Only 6 external NTCs
    2:  (0x0130, list(range(8))),
    3:  (0x0131, list(range(8))),
    4:  (0x0132, list(range(8))),
    5:  (0x0133, list(range(8))),
    6:  (0x0134, list(range(8))),
    7:  (0x0135, list(range(8))),
    8:  (0x0136, list(range(8))),
    9:  (0x0137, [0, 1]),                          # Only 2 external NTCs
    10: (0x014F, [0, 1, 2, 3])                     # 4 Master Pack NTCs
}


def build_ntc_names(total_sensors=68):
    names = []
    for idx in range(total_sensors):
        if idx < 64:
            names.append(f"ExtTherm_{idx+1}")
        else:
            names.append(f"Master_NTC_{idx-63}")
    return names


def format_sensor_names(sensor_str: str):
    """
    Collapse repeated ExtTherm_ prefixes to make lists shorter.
    Example: 'ExtTherm_1, ExtTherm_2' -> 'ExtTherm_1, 2'
    """
    if not sensor_str:
        return sensor_str

    parts = [p.strip() for p in sensor_str.split(",") if p.strip()]
    out = []
    ext_seen = False
    prefix = "ExtTherm_"

    for p in parts:
        if p.startswith(prefix):
            num = p[len(prefix):]
            if num.isdigit():
                if not ext_seen:
                    out.append(p)
                    ext_seen = True
                else:
                    out.append(num)
                continue
        out.append(p)

    return ", ".join(out)


def make_can_regex(can_hex_4: str):
    return re.compile(
        rf"\s*\d+\)\s+"
        rf"(\d{{2}}-\d{{2}}-\d{{4}}\s+\d{{2}}:\d{{2}}:\d{{2}}\.\d+)\s+(Rx|Tx)\s+{can_hex_4}\s+8\s+(.+)"
    )


# =========================================================
#  CAN ID REGEX (original)
# =========================================================
RE_110 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0110\s+8\s+(.+)"
)

RE_0109 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0109\s+8\s+(.+)"
)

RE_014E = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+014E\s+\d+\s+(.+)"
)

RE_0402 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0402\s+8\s+(.+)"
)

RE_0258 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0258\s+8\s+(.+)"
)

RE_0602 = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(Rx|Tx)\s+0602\s+\d+\s+(.+)"
)


def parse_ts(t):
    try:
        return datetime.strptime(t, "%d-%m-%Y %H:%M:%S.%f")
    except Exception:
        return None


# =========================================================
#  THERM FRAME REGEX + PARSER (per-sensor temps)
# =========================================================
THERM_RE = {can_id: make_can_regex(f"{can_id:04X}") for (_, (can_id, _)) in THERM_CAN_MAP.items()}


def decode_temp_byte(b: int) -> float:
    """
    If your temp encoding is different, adjust here.
    Currently assumes each byte is directly degrees C (0..255).
    """
    return float(b)


def parse_thermistor_frames(fp):
    """
    Returns list of (ts, temps_dict)
      temps_dict: {sensor_index: tempC}
    Indices:
      0..63  -> ExtTherm_1..64
      64..67 -> Master_NTC_1..4
    """
    can_to_group = {can_id: (g, byte_idxs) for g, (can_id, byte_idxs) in THERM_CAN_MAP.items()}

    out = []
    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = None
            can_id = None
            for cid, rx in THERM_RE.items():
                mm = rx.match(line)
                if mm:
                    m = mm
                    can_id = cid
                    break

            if not m:
                continue

            ts = parse_ts(m.group(1))
            if not ts:
                continue

            d = m.group(3).split()
            if len(d) < 8:
                continue
            payload = [int(x, 16) for x in d[:8]]

            group_key, byte_idxs = can_to_group[can_id]

            # group -> base index in your flattened 0..67 indexing
            if group_key == 1:
                base = 0
            elif 2 <= group_key <= 9:
                base = 6 + (group_key - 2) * 8
            else:  # group 10
                base = 64

            temps = {}
            for j, bidx in enumerate(byte_idxs):
                idx = base + j
                if idx >= 68:
                    continue
                temps[idx] = decode_temp_byte(payload[bidx])

            out.append((ts, temps))

    return sorted(out, key=lambda x: x[0])


def detect_active_ntc_from_therms(therm_samples, seconds=10):
    """
    Optional: detect which sensors are active in the first N seconds.
    If none detected, we fall back to using all sensors seen in the window.
    """
    if not therm_samples:
        return []

    t0 = therm_samples[0][0]
    t_end = t0 + timedelta(seconds=seconds)

    active = set()
    for ts, temps in therm_samples:
        if ts < t0:
            continue
        if ts > t_end:
            break
        for idx, v in temps.items():
            if isinstance(v, (int, float)) and v > 0:
                active.add(idx)

    return sorted(active)


def window_minmax_from_therms(therm_samples, start_ts, end_ts, ntc_names, active_ntc=None):
    """
    Returns (tmax, tmax_name, tmin, tmin_name) based on per-sensor signals.
    Does NOT affect Tavg (Tavg continues to use 0x014E logic).
    """
    active = set(active_ntc) if active_ntc is not None else None
    max_v = None
    max_ts = None
    max_idxs = set()
    min_v = None
    min_ts = None
    min_idxs = set()

    for ts, temps in therm_samples:
        if ts < start_ts:
            continue
        if ts > end_ts:
            break

        for idx, v in temps.items():
            if active is not None and idx not in active:
                continue
            if v is None or v <= 0:
                continue

            # Track max with ties only if they occur at the same timestamp
            if max_v is None or v > max_v:
                max_v = v
                max_ts = ts
                max_idxs = {idx}
            elif v == max_v and ts == max_ts:
                max_idxs.add(idx)

            # Track min with ties only if they occur at the same timestamp
            if min_v is None or v < min_v:
                min_v = v
                min_ts = ts
                min_idxs = {idx}
            elif v == min_v and ts == min_ts:
                min_idxs.add(idx)

    if max_v is None or min_v is None:
        return None, None, None, None

    try:
        raw_max = ", ".join(ntc_names[i] for i in sorted(max_idxs))
        raw_min = ", ".join(ntc_names[i] for i in sorted(min_idxs))
        max_names = format_sensor_names(raw_max)
        min_names = format_sensor_names(raw_min)
    except (IndexError, KeyError):
        return None, None, None, None

    return max_v, max_names, min_v, min_names


# =========================================================
#  SELECT TRC FILE GUI
# =========================================================
def select_trc_file():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(
        title="Select TRC File",
        filetypes=[("TRC Files", "*.trc")],
    )


# =========================================================
#  PARSE TRC FILE FOR ALL METRICS EXCEPT CHARGING
# =========================================================
def parse_trc(fp):

    soc_list = []
    current_list = []
    odo_list = []
    ntc_list = []
    uv_list = []

    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:

            # CURRENT (0x110)
            m = RE_110.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 8:
                    b4, b5, b6, b7 = [int(x, 16) for x in d[4:8]]
                    raw = struct.unpack("<i", bytes([b4, b5, b6, b7]))[0]
                    I = raw * 1e-5
                    current_list.append((ts, I))

            # SOC (0x109)  --- IGNORE if 5th byte == 0x00
            m = RE_0109.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if not ts:
                    continue

                # BMS state / validity byte is at index 4 (5th byte)
                if len(d) >= 5:
                    bms_state = int(d[4], 16)
                    if bms_state == 0:
                        continue

                if len(d) >= 2:
                    lo = int(d[0], 16)
                    hi = int(d[1], 16)
                    raw = lo | (hi << 8)
                    soc = raw * 0.01
                    soc_list.append((ts, soc))

            # TEMP (NTC) (0x14E) : (tmax, tmin) bytes
            # NOTE: We keep this logic for Tavg exactly as you already compute it.
            m = RE_014E.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 2:
                    ntc_list.append((ts, (int(d[0], 16), int(d[1], 16))))

            # ODO (0x402)
            m = RE_0402.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 4:
                    raw = (
                        int(d[0], 16)
                        | (int(d[1], 16) << 8)
                        | (int(d[2], 16) << 16)
                        | (int(d[3], 16) << 24)
                    )
                    odo_list.append((ts, raw * 0.1))

            # UV FLAG (0x258)
            m = RE_0258.match(line)
            if m:
                ts = parse_ts(m.group(1))
                d = m.group(3).split()
                if ts and len(d) >= 2:
                    raw16 = int(d[0], 16) | (int(d[1], 16) << 8)
                    uv = (raw16 >> 6) & 1
                    uv_list.append((ts, uv))

    return soc_list, current_list, odo_list, ntc_list, uv_list


# =========================================================
#  DETECT CHARGING STATE FROM CAN ID 0x0602
# =========================================================
def detect_charge_events(fp):

    events = []
    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = RE_0602.match(line)
            if not m:
                continue

            ts = parse_ts(m.group(1))
            if not ts:
                continue

            d = m.group(3).split()
            if len(d) < 8:
                continue

            last_byte = int(d[7], 16)
            state = "CHARGING" if last_byte in (0x01, 0x03) else "DRIVING"
            events.append((ts, state))

    return sorted(events, key=lambda x: x[0])


def build_charge_sessions(events, default_end=None):

    sessions = []
    state = "DRIVING"
    session_start = None

    for ts, new_state in events:
        if new_state == state:
            continue

        if new_state == "CHARGING":
            session_start = ts
        else:
            if session_start:
                sessions.append((session_start, ts))
                session_start = None
        state = new_state

    if state == "CHARGING" and session_start and default_end:
        sessions.append((session_start, default_end))

    return sessions


# =========================================================
#  LOOKUP HELPERS
# =========================================================
def lookup_before(ts, data):
    best = None
    for t, v in data:
        if t <= ts:
            best = (t, v)
        else:
            break
    return best


def lookup_after(ts, data):
    for t, v in data:
        if t >= ts:
            return (t, v)
    return None


# =========================================================
#  FIXED: EXACT/STEP SoC TIMESTAMP SELECTION (0.01% resolution)
# =========================================================
def find_soc_ts(soc_list, target, start_ts, end_ts, reverse=False, tol=0.15):
    if not soc_list:
        return None

    EPS = 1e-9
    best_ts = None
    best_soc = None

    data = reversed(soc_list) if reverse else soc_list

    # Pass 1: exact target match
    for ts, soc in data:
        if ts < start_ts or ts > end_ts:
            continue
        if abs(soc - target) <= EPS:
            return ts

    # Pass 2: nearest below target (max soc < target)
    data = reversed(soc_list) if reverse else soc_list
    for ts, soc in data:
        if ts < start_ts or ts > end_ts:
            continue
        if soc < target - EPS:
            if best_soc is None or soc > best_soc:
                best_soc = soc
                best_ts = ts

    return best_ts


# =========================================================
#  CAPACITY INTEGRATION
# =========================================================
def integrate_window(current_list, start_ts, end_ts):
    DEFAULT_DT = 0.3
    As = 0.0
    curr = sorted(current_list, key=lambda x: x[0])

    for i in range(1, len(curr)):
        t0, I = curr[i - 1]
        t1, _ = curr[i]

        if t1 <= start_ts:
            continue
        if t0 >= end_ts:
            break

        dt = (t1 - t0).total_seconds()
        if dt <= 0 or dt > 0.5:
            dt = DEFAULT_DT

        As += I * dt

    return As / 3600.0


def summarize_current(current_list):

    DEFAULT_DT = 0.3
    pos_as = 0.0
    neg_as = 0.0
    valid = 0
    default = 0

    curr = sorted(current_list, key=lambda x: x[0])
    for i in range(1, len(curr)):
        t0, I = curr[i - 1]
        t1, _ = curr[i]
        dt = (t1 - t0).total_seconds()

        if dt <= 0 or dt > 0.5:
            dt = DEFAULT_DT
            default += 1
        else:
            valid += 1

        if I >= 0:
            pos_as += I * dt
        else:
            neg_as += I * dt

    return {
        "charge_ah": pos_as / 3600.0,
        "discharge_ah": neg_as / 3600.0,
        "exchange_ah": (pos_as + neg_as) / 3600.0,
        "valid_dt_count": valid,
        "default_dt_count": default,
        "default_dt_value": DEFAULT_DT,
    }


# =========================================================
#  UV SOC SELECTION
# =========================================================
def get_uv_end_soc(soc_list, uv_ts):

    if not soc_list:
        return None

    idx = None
    for i, (t, v) in enumerate(soc_list):
        if t >= uv_ts:
            idx = i
            break

    if idx is None:
        idx = len(soc_list) - 1

    chosen_soc = soc_list[idx][1]

    if chosen_soc > 0:
        return chosen_soc

    streak = 0
    j = idx
    while j >= 0 and soc_list[j][1] == 0:
        streak += 1
        j -= 1

    if streak >= 5:
        return 0.0

    while j >= 0:
        if soc_list[j][1] > 0:
            return soc_list[j][1]
        j -= 1

    return 0.0


def window_temp_avg(temp_samples, start_ts, end_ts):
    total = 0.0
    count = 0
    for ts, sval in temp_samples:
        if ts < start_ts:
            continue
        if ts > end_ts:
            break
        total += sval
        count += 1
    if count == 0:
        return None, 0
    return total / count, count


# =========================================================
#  BUILD WINDOWS
# =========================================================
def build_windows(soc_list, current_list, odo_list, ntc_list, uv_list, therm_samples, fp):

    soc_list = sorted(soc_list, key=lambda x: x[0])
    odo_list = sorted(odo_list, key=lambda x: x[0])
    ntc_list = sorted(ntc_list, key=lambda x: x[0])
    current_list = sorted(current_list, key=lambda x: x[0])

    if not soc_list:
        return [], 0.0, None, False, False

    # Keep original Tavg computation (from 0x014E tmax/tmin)
    temp_samples = []
    zero_streak = 0
    streak_found = False
    for ts, (tmax, tmin) in ntc_list:
        if not streak_found:
            if tmax == 0 or tmin == 0:
                zero_streak += 1
                if zero_streak >= 5:
                    streak_found = True
                continue
            zero_streak = 0
            temp_samples.append((ts, (tmax + tmin) / 2.0))
        else:
            temp_samples.append((ts, (tmax + tmin) / 2.0))

    ntc_names = build_ntc_names(68)

    # Detect active NTCs once (optional filter). If empty -> we won't filter.
    active_ntc = detect_active_ntc_from_therms(therm_samples, seconds=10)
    if not active_ntc:
        active_ntc = None  # fallback: consider any sensor present

    # UV timestamp
    uv_ts = None
    for ts, flag in uv_list:
        if flag == 1:
            uv_ts = ts
            break

    uv_end_soc = None
    if uv_ts and soc_list:
        uv_end_soc = get_uv_end_soc(soc_list, uv_ts)

    ts_all = [t for t, _ in soc_list]
    t_start = ts_all[0]
    t_end = ts_all[-1]

    # Charging sessions
    charge_events = detect_charge_events(fp)
    charging_sessions = build_charge_sessions(charge_events, t_end)

    session_blocks = []
    prev_end = t_start
    for st, en in charging_sessions:
        if st > prev_end:
            session_blocks.append(("normal", prev_end, st))
        session_blocks.append(("charge", st, en))
        prev_end = en

    if prev_end < t_end:
        session_blocks.append(("normal", prev_end, t_end))

    session_blocks.sort(key=lambda x: x[1])

    # Total range
    total_range = 0.0
    if odo_list:
        total_range = max(0.0, odo_list[-1][1] - odo_list[0][1])

    final_rows = []
    odo_baseline = odo_list[0][1] if odo_list else None
    soc_baseline = soc_list[0][1] if soc_list else None

    for typ, block_start, block_end in session_blocks:

        # -----------------------------
        # CHARGE BLOCK (WITH Ah + Temp)
        # -----------------------------
        if typ == "charge":
            charge_soc_start = lookup_before(block_start, soc_list)
            charge_soc_end = lookup_before(block_end, soc_list)

            # distance during charge (optional, usually ~0)
            dist = 0.0
            if odo_list:
                odo_start = lookup_before(block_start, odo_list)
                odo_end = lookup_before(block_end, odo_list)
                if odo_start and odo_end:
                    dist = max(0.0, odo_end[1] - odo_start[1])

            cap_ah = integrate_window(current_list, block_start, block_end)

            # Keep Tavg exactly as before:
            tavg, _ = window_temp_avg(temp_samples, block_start, block_end)

            # NEW: compute min/max + signal name from per-sensor therms
            tmax_v, tmax_sig, tmin_v, tmin_sig = window_minmax_from_therms(
                therm_samples, block_start, block_end, ntc_names, active_ntc=active_ntc
            )

            if charge_soc_start and charge_soc_end:
                final_rows.append(
                    ("charge", charge_soc_start[1], charge_soc_end[1], dist, cap_ah, tavg,
                     tmax_v, tmax_sig, tmin_v, tmin_sig)
                )

            # update baselines
            charge_odo_end = lookup_before(block_end, odo_list)
            if charge_odo_end:
                odo_baseline = charge_odo_end[1]
            if charge_soc_end:
                soc_baseline = charge_soc_end[1]
            continue

        # -----------------------------
        # NORMAL (DRIVING) BLOCKS
        # -----------------------------
        if uv_ts and uv_ts <= block_start:
            continue

        if uv_ts and uv_ts < block_end:
            block_end_ts = uv_ts
            uv_in_this_block = True
        else:
            block_end_ts = block_end
            uv_in_this_block = False

        if soc_baseline is None:
            sb = lookup_before(block_start, soc_list)
            if sb:
                soc_baseline = sb[1]

        end_entry = lookup_before(block_end_ts, soc_list)
        if soc_baseline is None or not end_entry:
            continue

        current_soc = soc_baseline
        end_soc = end_entry[1]

        if uv_in_this_block and uv_end_soc is not None:
            end_soc = uv_end_soc

        # 10% windows downwards
        while current_soc - end_soc >= 10:
            next_soc = current_soc - 10

            window_start_ts = (
                find_soc_ts(soc_list, current_soc, block_start, block_end_ts)
                or block_start
            )
            window_end_ts = (
                find_soc_ts(soc_list, next_soc, block_start, block_end_ts, reverse=True)
                or block_end_ts
            )

            if odo_baseline is None:
                ob = lookup_before(window_start_ts, odo_list)
                if ob:
                    odo_baseline = ob[1]

            dist = 0.0
            odo_end = lookup_before(window_end_ts, odo_list)
            if odo_end and odo_baseline is not None:
                dist = odo_end[1] - odo_baseline
                if dist < 0:
                    dist = 0.0
                odo_baseline = odo_end[1]

            # Keep Tavg exactly as before:
            tavg, _ = window_temp_avg(temp_samples, window_start_ts, window_end_ts)

            # NEW min/max + signal:
            tmax_v, tmax_sig, tmin_v, tmin_sig = window_minmax_from_therms(
                therm_samples, window_start_ts, window_end_ts, ntc_names, active_ntc=active_ntc
            )

            cap_ah = integrate_window(current_list, window_start_ts, window_end_ts)

            final_rows.append(("normal", current_soc, next_soc, dist, cap_ah, tavg,
                               tmax_v, tmax_sig, tmin_v, tmin_sig))
            current_soc = next_soc

        # Last partial window
        if current_soc > end_soc:
            window_start_ts = (
                find_soc_ts(soc_list, current_soc, block_start, block_end_ts)
                or block_start
            )
            window_end_ts = (
                find_soc_ts(soc_list, end_soc, block_start, block_end_ts, reverse=True)
                or block_end_ts
            )

            if odo_baseline is None:
                ob = lookup_before(window_start_ts, odo_list)
                if ob:
                    odo_baseline = ob[1]

            dist = 0.0
            odo_end = lookup_before(window_end_ts, odo_list)
            if odo_end and odo_baseline is not None:
                dist = odo_end[1] - odo_baseline
                if dist < 0:
                    dist = 0.0
                odo_baseline = odo_end[1]

            # Keep Tavg exactly as before:
            tavg, _ = window_temp_avg(temp_samples, window_start_ts, window_end_ts)

            # NEW min/max + signal:
            tmax_v, tmax_sig, tmin_v, tmin_sig = window_minmax_from_therms(
                therm_samples, window_start_ts, window_end_ts, ntc_names, active_ntc=active_ntc
            )

            cap_ah = integrate_window(current_list, window_start_ts, window_end_ts)

            final_rows.append(("normal", current_soc, end_soc, dist, cap_ah, tavg,
                               tmax_v, tmax_sig, tmin_v, tmin_sig))

        soc_baseline = end_soc

        if uv_in_this_block:
            if final_rows:
                last = final_rows[-1]
                # last tuple: (typ, sv, ev, odo, cap, tavg, tmax_v, tmax_sig, tmin_v, tmin_sig)
                final_rows[-1] = ("uv",) + last[1:]
            break

    # ---------------------------------------------------------
    # Distance from SOC <= 1%
    # ---------------------------------------------------------
    uv_detected = uv_ts is not None
    low_soc_start_ts = None

    for ts, soc in soc_list:
        if soc <= 1.0:
            low_soc_start_ts = ts
            break

    low_soc_found = low_soc_start_ts is not None
    dist_after_low_soc = None

    if low_soc_found and odo_list:
        odo_at_low = lookup_before(low_soc_start_ts, odo_list)
        if odo_at_low:
            if uv_detected:
                odo_at_end = lookup_before(uv_ts, odo_list)
            else:
                odo_at_end = odo_list[-1]
            if odo_at_end:
                dist_after_low_soc = max(0.0, odo_at_end[1] - odo_at_low[1])

    return final_rows, total_range, dist_after_low_soc, uv_detected, low_soc_found


# =========================================================
#  DRAW TABLE PNG
# =========================================================
def draw_table_png(
    rows,
    output,
    total_cap_override=None,
    total_range=0.0,
    dist_after_low_soc=0.0,
    uv_detected=False,
    low_soc_found=False,
):

    cols = ["SoC Window", "Odo", "Cap Exchange", "Temp Avg", "Temp Signal"]
    col_w = [0.32, 0.12, 0.18, 0.18, 0.2]

    # a bit taller because Temp cell may have 3 lines
    fig, ax = plt.subplots(figsize=(12, 0.7 + 0.45 * (len(rows) + 3)))
    ax.axis("off")

    header_h = 0.06
    row_h = 0.075  # bigger row height for multiline temp cell

    y = 1 - header_h
    x = 0
    for i, h in enumerate(cols):
        ax.add_patch(Rectangle((x, y), col_w[i], header_h, fc="#d0d0d0", ec="black"))
        ax.text(x + col_w[i] / 2, y + header_h / 2, h, ha="center", va="center")
        x += col_w[i]
    y -= row_h

    total_cap = 0.0

    for typ, sv, ev, odo, cap, tavg, tmax_v, tmax_sig, tmin_v, tmin_sig in rows:

        tv = f"{tavg:.1f} C" if tavg is not None else ""
        t_signal_parts = []
        if tmax_v is not None:
            t_signal_parts.append(f"Max {tmax_v:.1f}C ({tmax_sig})")
        if tmin_v is not None:
            t_signal_parts.append(f"Min {tmin_v:.1f}C ({tmin_sig})")
        t_signal = "\n".join(t_signal_parts)

        # Charge row shown in columns (yellow)
        if typ == "charge":
            sw = f"CHG: {sv:.2f}% to {ev:.2f}%"
            cd = f"{odo:.2f}"
            ce = f"{cap:.2f} Ah"

            x = 0
            for val, w in zip([sw, cd, ce, tv, t_signal], col_w):
                ax.add_patch(Rectangle((x, y), w, row_h, fc="#fce88c", ec="black"))
                ax.text(x + w / 2, y + row_h / 2, val, ha="center", va="center", fontsize=9)
                x += w

            total_cap += cap
            y -= row_h
            continue

        if typ == "uv":
            sw = f"{sv:.2f}% to (UV) {ev:.2f}%"
        else:
            sw = f"{sv:.2f}% to {ev:.2f}%"

        cd = f"{odo:.2f}"
        ce = f"{cap:.2f} Ah"

        x = 0
        for val, w in zip([sw, cd, ce, tv, t_signal], col_w):
            ax.add_patch(Rectangle((x, y), w, row_h, fc="white", ec="black"))
            ax.text(x + w / 2, y + row_h / 2, val, ha="center", va="center", fontsize=9)
            x += w

        total_cap += cap
        y -= row_h

    # Extra row for Distance after SoC <= 1%
    if not low_soc_found:
        msg = "Distance Covered SoC<=1% = N/A"
    elif uv_detected and dist_after_low_soc is not None:
        msg = f"Distance Covered SoC<=1% to UV = {dist_after_low_soc:.1f} km"
    elif dist_after_low_soc is not None:
        msg = f"Distance Covered SoC<=1% = {dist_after_low_soc:.1f} km (UV Not detected)"
    else:
        msg = "Distance Covered SoC<=1% = N/A"

    ax.add_patch(Rectangle((0, y), 1, row_h, fc="white", ec="black"))
    ax.text(
        0.5,
        y + row_h / 2,
        msg,
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color="red",
    )
    y -= row_h

    # Totals row
    ax.add_patch(Rectangle((0, y), col_w[0], row_h, fc="white", ec="black"))

    ax.add_patch(Rectangle((col_w[0], y), col_w[1], row_h, fc="#a0d0ff", ec="black"))
    ax.text(
        col_w[0] + col_w[1] / 2,
        y + row_h / 2,
        f"Range = {total_range:.1f} km",
        ha="center",
        va="center",
    )

    display_cap = total_cap_override if total_cap_override is not None else total_cap

    ax.add_patch(
        Rectangle((col_w[0] + col_w[1], y), col_w[2], row_h, fc="#a0d0ff", ec="black")
    )
    ax.text(
        col_w[0] + col_w[1] + col_w[2] / 2,
        y + row_h / 2,
        f"Total CAP exc = {display_cap:.2f} Ah",
        ha="center",
        va="center",
    )

    x = col_w[0] + col_w[1] + col_w[2]
    for w in col_w[3:]:
        ax.add_patch(Rectangle((x, y), w, row_h, fc="white", ec="black"))
        x += w

    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches="tight")
    plt.close()


# =========================================================
#  MAIN
# =========================================================
def main():

    trc_env = os.environ.get("TRC_FILE")
    trc_saved = Path(__file__).resolve().parent / "selected_trc.txt"

    if len(sys.argv) > 1:
        trc = sys.argv[1]
    elif trc_env:
        trc = trc_env
    elif trc_saved.exists():
        trc = trc_saved.read_text().strip()
    else:
        trc = select_trc_file()

    soc_list, current_list, odo_list, ntc_list, uv_list = parse_trc(trc)

    # NEW: parse per-sensor therm signals (for min/max + signal name in table only)
    therm_samples = parse_thermistor_frames(trc)

    (
        rows,
        total_range,
        dist_after_low_soc,
        uv_detected,
        low_soc_found,
    ) = build_windows(soc_list, current_list, odo_list, ntc_list, uv_list, therm_samples, trc)

    out = Path(__file__).resolve().parent

    # keep summary json as-is (raw current integration totals)
    stats = summarize_current(current_list)
    summary = {
        "Capacity_Summary": {
            "Charge_Ah": f"{stats['charge_ah']:.4f}",
            "Discharge_Ah": f"{stats['discharge_ah']:.4f}",
            "Capacity_Exchange_Ah": f"{stats['exchange_ah']:.4f}",
            "Valid_dt_Count": stats["valid_dt_count"],
            "Default_dt_Count": stats["default_dt_count"],
            "Default_dt_Value_s": stats["default_dt_value"],
        }
    }

    (out / "Capacity_check_summary.json").write_text(json.dumps(summary, indent=4))
    (out / "Capacity_check_results.json").write_text(
        json.dumps({"Result": "PASS"}, indent=4)
    )

    # IMPORTANT: do NOT override total cap; table total includes charging rows now
    draw_table_png(
        rows,
        out / "Capacity_check_plot.png",
        total_cap_override=None,
        total_range=total_range,
        dist_after_low_soc=dist_after_low_soc,
        uv_detected=uv_detected,
        low_soc_found=low_soc_found,
    )


if __name__ == "__main__":
    main()
