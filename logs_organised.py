#!/usr/bin/env python3
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

def _excel_serial_to_datetime(serial: float) -> datetime:
    excel_epoch = datetime(1899, 12, 30)
    return excel_epoch + timedelta(days=serial)

RE_STARTTIME_SEC = re.compile(r"^\s*;\$STARTTIME\s*=\s*([0-9.]+)")
RE_STARTTIME_STR = re.compile(r"Start time:\s*(.+)")
RE_FRAME = re.compile(
    r"^\s*(\d+)\)?\s+([\d.]+)\s+([A-Za-z]+)\s+([0-9A-Fa-f]+)\s+(\d+)\s*(.*)$"
)

MONTHS = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"
}

MODE_PATTERNS = [
    ("Thunder City Max", re.compile(r"\bTHUNDER\s+CITY\s+MAX\b", re.IGNORECASE)),
    ("Thunder City",     re.compile(r"\bTHUNDER\s+CITY\b", re.IGNORECASE)),
    ("Thunder Mode",     re.compile(r"\bTHUNDER\s+MODE\b", re.IGNORECASE)),
    ("Thunder",          re.compile(r"\bTHUNDER\b", re.IGNORECASE)),
    ("Rhino Mode",       re.compile(r"\bRHINO\s+MODE\b", re.IGNORECASE)),
    ("Rhino",            re.compile(r"\bRHINO\b", re.IGNORECASE)),
    ("Eco Mode",         re.compile(r"\bECO\s+MODE\b", re.IGNORECASE)),
    ("Eco",              re.compile(r"\bECO\b", re.IGNORECASE)),
]

STOP_WORDS = {
    "MBMS", "HC", "LFP", "MARVEL", "DISCHARGING", "CHARGING",
    "LOG", "TRC", "CSV", "DECODED", "DECODE", "FILE", "FINAL", "MERGED"
}

# -------------------------------------------------
# 409 (Motorola 0.01) → 402 (Intel 0.1) conversion
# -------------------------------------------------
def convert_409_to_402(canid: str, data: str):
    if canid.upper().lstrip("0") != "409":
        return canid, data

    try:
        data_bytes = bytes(int(x, 16) for x in data.strip().split())
        if len(data_bytes) != 8:
            return canid, data

        # Decode Motorola (big-endian)
        raw1 = int.from_bytes(data_bytes[0:4], byteorder="big")
        raw2 = int.from_bytes(data_bytes[4:8], byteorder="big")

        # 409 scaling = 0.01
        physical1 = raw1 * 0.01
        physical2 = raw2 * 0.01

        # Convert to 402 scaling = 0.1
        raw1_402 = int(round(physical1 / 0.1))
        raw2_402 = int(round(physical2 / 0.1))

        # Clamp to 32-bit unsigned
        raw1_402 = max(0, min(raw1_402, 0xFFFFFFFF))
        raw2_402 = max(0, min(raw2_402, 0xFFFFFFFF))

        # Encode Intel (little-endian)
        new_bytes = (
            raw1_402.to_bytes(4, byteorder="little") +
            raw2_402.to_bytes(4, byteorder="little")
        )

        new_data = " ".join(f"{b:02X}" for b in new_bytes)

        return "402", new_data

    except Exception:
        return canid, data

def _parse_start_datetime(text: str) -> datetime:
    cleaned = text.strip().replace(".0", "")

    candidates = [cleaned]
    try:
        date_part, time_part = cleaned.split()
        if ":" in time_part:
            hh, mm, sec = time_part.split(":")
            if len(sec) > 2 and not sec.count("."):
                if len(sec) == 4:
                    sec = sec[:-2] + "." + sec[-2:]
                elif len(sec) == 3:
                    sec = sec[:-2] + "." + sec[-2:]
                elif len(sec) > 4:
                    sec = sec[:-3] + "." + sec[-3:]
            candidates.append(f"{date_part} {hh}:{mm}:{sec}")
    except Exception:
        pass

    date_formats = [
        "%d-%m-%Y %H:%M:%S.%f",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S.%f",
        "%m/%d/%Y %H:%M:%S",
        "%m-%d-%Y %H:%M:%S.%f",
        "%m-%d-%Y %H:%M:%S",
    ]

    for candidate in candidates:
        for fmt in date_formats:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue

    raise ValueError(f"Unparseable start time '{text}': tried formats {date_formats}")


def _format_timestamp(ts: datetime) -> str:
    base = ts.strftime("%d-%m-%Y %H:%M:%S")
    total_us = ts.microsecond
    ms = total_us // 1000
    tenth_ms = (total_us % 1000) // 100
    return f"{base}.{ms:03d}{tenth_ms}"


def _date_tag(dt: datetime) -> str:
    return f"{dt.day}{MONTHS[dt.month]}{dt.year}"


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', ' ', name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180]


def _normalize_filename(s: str) -> str:
    # normalize separators/spaces for robust matching
    s = Path(s).stem
    s = re.sub(r"[_\-,]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_mode_anywhere(clean_name: str) -> str | None:
    """
    Detect modes even if words appear anywhere.
    Handles 'THUNDER MODE' and also just 'THUNDER'.
    Case-insensitive.
    """
    for label, pat in MODE_PATTERNS:
        if pat.search(clean_name):
            # normalize label output (e.g. "Thunder Mode" vs "Thunder")
            return label
    return None


def extract_vehicle_weight_mode_from_name(filename: str) -> tuple[str | None, str | None, str | None]:
    clean = _normalize_filename(filename)
    tokens = clean.split()

    # Vehicle: first token
    vehicle = tokens[0] if tokens else None

    # Weight: 550KG / 550 kg / 550kg
    w_match = re.search(r"\b(\d{2,5})\s*(kg)\b", clean, flags=re.IGNORECASE)
    weight = f"{int(w_match.group(1))}kg" if w_match else None

    # Mode: robust search anywhere (case-insensitive)
    mode = find_mode_anywhere(clean)

    # Heuristic fallback: if still no mode, try to capture after an anchor like THUNDER/RHINO/ECO
    if mode is None:
        upper = [t.upper() for t in tokens]
        for anchor in ("THUNDER", "RHINO", "ECO"):
            if anchor in upper:
                i = upper.index(anchor)
                chunk = tokens[i:i + 5]  # anchor + next up to 4 words
                cleaned = []
                for w in chunk:
                    if w.upper() in STOP_WORDS:
                        break
                    # stop at obvious non-mode tokens like IDs and weights
                    if re.fullmatch(r"L[-_]?\d+", w, flags=re.IGNORECASE):
                        break
                    if re.fullmatch(r"\d{2,5}KG", w, flags=re.IGNORECASE):
                        break
                    cleaned.append(w)
                if cleaned:
                    mode = " ".join(cleaned).title()
                    break

    return vehicle, weight, mode


def build_output_name_from_trc(start_dt: datetime, filepaths: list[str]) -> str:
    date_part = _date_tag(start_dt)

    v, w, m = extract_vehicle_weight_mode_from_name(Path(filepaths[0]).name)
    if v is None or w is None or m is None:
        for fp in filepaths[1:]:
            vv, ww, mm = extract_vehicle_weight_mode_from_name(Path(fp).name)
            v = v or vv
            w = w or ww
            m = m or mm
            if v and w and m:
                break

    parts = [p for p in [v, date_part, w, m] if p]
    return _sanitize_filename(" ".join(parts)) if parts else _sanitize_filename(f"Merged {_date_tag(start_dt)}")


def _with_final_prefix(name: str) -> str:
    """
    Ensure the output filename always starts with 'FINAL ' (case-insensitive),
    avoiding duplicate prefixes if it already has one.
    """
    # Normalize leading whitespace/underscores for a consistent check
    trimmed = name.lstrip(" _")
    if trimmed.upper().startswith("FINAL "):
        return trimmed
    if trimmed.upper().startswith("FINAL_"):
        return "FINAL " + trimmed[6:].lstrip("_ ")
    return f"FINAL {trimmed}"


# ------------ PARSE A SINGLE TRC FILE ------------
def parse_trc_file(filepath: str):
    lines = Path(filepath).read_text(encoding="utf-8", errors="ignore").splitlines()

    start_sec = None
    for ln in lines:
        m = RE_STARTTIME_SEC.match(ln)
        if m:
            start_sec = float(m.group(1))
            break

    start_str = None
    for ln in lines:
        m = RE_STARTTIME_STR.search(ln)
        if m:
            start_str = m.group(1).strip()
            break

    if start_str is None:
        raise ValueError(f"Missing 'Start time:' in {filepath}")

    frames_raw = []
    for ln in lines:
        m = RE_FRAME.match(ln)
        if m:
            offset = float(m.group(2))
            ftype = m.group(3)
            canid = m.group(4).upper()
            dlc = m.group(5)
            data = m.group(6)

            # 🔥 Apply 409 → 402 conversion here
            canid, data = convert_409_to_402(canid, data)

            frames_raw.append((offset, ftype, canid, dlc, data))

    if not frames_raw:
        raise ValueError(f"No frames found in {filepath}")

    # Use $STARTTIME because it is locale-independent
    if start_sec is not None:
        start_dt = _excel_serial_to_datetime(start_sec)
    else:
        start_dt = _parse_start_datetime(start_str)

    # FIRST FRAME = Start time
    offset_base = frames_raw[0][0]

    frames = []
    for offset, ftype, canid, dlc, data in frames_raw:
        delta_ms = offset - offset_base
        delta_us = int(round(delta_ms * 1000.0))
        actual_dt = start_dt + timedelta(microseconds=delta_us)
        frames.append((actual_dt, ftype, canid, dlc, data))

    return start_sec, start_str, start_dt, frames


# ------------ MERGE MULTIPLE TRC FILES ------------
def merge_trcs(filepaths):
    all_files = []

    for fp in filepaths:
        try:
            start_sec, start_str, start_dt, frames = parse_trc_file(fp)
            all_files.append((start_sec, start_str, start_dt, frames))
            print(f"Loaded: {fp}")
        except Exception as e:
            print(f"Skipping {fp}: {e}")

    if not all_files:
        raise RuntimeError("No valid TRC files selected.")

    all_files.sort(key=lambda x: x[2])

    seen = set()
    unique = []
    for st, st_str, st_dt, fr in all_files:
        dedup_key = st if st is not None else st_dt
        if dedup_key not in seen:
            unique.append((st, st_str, st_dt, fr))
            seen.add(dedup_key)

    merged_all = []
    for _st, _st_str, _st_dt, frames in unique:
        merged_all.extend(frames)

    merged_all.sort(key=lambda x: x[0])

    base_start_sec = unique[0][0] if unique[0][0] is not None else unique[0][2].timestamp()
    base_start_str = unique[0][1]
    earliest_dt = unique[0][2]

    out = []
    out.append(";$FILEVERSION=1.1")
    out.append(f";$STARTTIME={base_start_sec}")
    out.append(";")
    out.append(f";   Start time: {base_start_str}")
    out.append(";   Merged TRC (with corrected timestamp logic)")
    out.append(";")
    out.append(";   Message Number")
    out.append(";   |         Timestamp")
    out.append(";   |         |        Type")
    out.append(";   |         |        |        ID (hex)")
    out.append(";   |         |        |        |     Data Length")
    out.append(";---+--   ----+----  --+--  ----+---  +  -+ -- -- -- -- -- -- --")

    msgnum = 1
    for ts, ftype, canid, dlc, data in merged_all:
        ts_str = _format_timestamp(ts)
        canid_formatted = f"{int(canid, 16):04X}"
        line = f"{msgnum:>6})  {ts_str}  {ftype:<7} {canid_formatted}  {dlc}  {data}"
        out.append(line)
        msgnum += 1

    return "\n".join(out), earliest_dt


# ------------ GUI FILE PICKER ------------
def main():
    tk.Tk().withdraw()
    initial_dir = None
    if len(sys.argv) > 1:
        try:
            candidate = Path(sys.argv[1]).expanduser()
            if candidate.is_dir():
                initial_dir = str(candidate)
        except Exception:
            initial_dir = None

    if initial_dir is None:
        home = Path.home()
        for d in [home / "Downloads", home / "Desktop", home]:
            if d.is_dir():
                initial_dir = str(d)
                break
        if initial_dir is None:
            initial_dir = str(Path.cwd())

    filepaths = filedialog.askopenfilenames(
        title="Select TRC files to merge",
        filetypes=[("TRC files", "*.trc")],
        initialdir=initial_dir,
    )

    if not filepaths:
        print("No TRC files selected.")
        return

    merged_text, earliest_dt = merge_trcs(list(filepaths))

    first_folder = Path(filepaths[0]).parent
    nice_name = build_output_name_from_trc(earliest_dt, list(filepaths))
    nice_name = _with_final_prefix(nice_name)
    outpath = first_folder / f"{nice_name}.trc"
    outpath.write_text(merged_text, encoding="utf-8")

    try:
        marker = Path(__file__).resolve().with_name("last_merged_trc.txt")
        marker.write_text(str(outpath), encoding="utf-8")
    except Exception:
        pass

    print("\n=======================================================")
    print("   ✅ MERGE COMPLETE")
    print(f"   Output file saved as: {outpath}")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
