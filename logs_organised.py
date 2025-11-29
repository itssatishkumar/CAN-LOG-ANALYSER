#!/usr/bin/env python3
import re
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

# ------------ REGEX PATTERNS ------------
RE_STARTTIME_SEC = re.compile(r"^\s*;\$STARTTIME\s*=\s*([0-9.]+)")
RE_STARTTIME_STR = re.compile(r"Start time:\s*(.+)")
RE_FRAME = re.compile(
    r"^\s*(\d+)\)?\s+([\d.]+)\s+([A-Za-z]+)\s+([0-9A-Fa-f]+)\s+(\d+)\s*(.*)$"
)

# ------------ HELPERS ------------
def _parse_start_datetime(text: str) -> datetime:
    """
    Parse the Start time string from TRC header, allowing minor formatting issues
    like missing dot before milliseconds (e.g., '14:27:3041' -> '14:27:30.41').
    """
    cleaned = text.strip().replace(".0", "")  # common suffix like '...502.0' -> '...502'

    # Try standard format first
    try:
        return datetime.strptime(cleaned, "%d-%m-%Y %H:%M:%S.%f")
    except ValueError:
        pass

    # If seconds are stuck to milliseconds (e.g., 14:27:3041)
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
            cleaned2 = f"{date_part} {hh}:{mm}:{sec}"
            return datetime.strptime(cleaned2, "%d-%m-%Y %H:%M:%S.%f")
    except Exception:
        pass

    # Final fallback: try without milliseconds
    try:
        return datetime.strptime(cleaned, "%d-%m-%Y %H:%M:%S")
    except ValueError as e:
        raise ValueError(f"Unparseable start time '{text}': {e}")


def _format_timestamp(ts: datetime) -> str:
    """
    Format timestamp similar to PCAN style with millisecond + 0.1 ms precision.
    Example: '11-11-2025 05:03:30.5026'
    """
    base = ts.strftime("%d-%m-%Y %H:%M:%S")
    total_us = ts.microsecond                # 0..999_999
    ms = total_us // 1000                    # full milliseconds (0..999)
    tenth_ms = (total_us % 1000) // 100      # tenth of a millisecond (0..9)
    return f"{base}.{ms:03d}{tenth_ms}"


# ------------ PARSE A SINGLE TRC FILE ------------
def parse_trc_file(filepath: str):
    lines = Path(filepath).read_text(encoding="utf-8", errors="ignore").splitlines()

    # Read STARTTIME from header (seconds) — used only for sorting between files if needed
    start_sec = None
    for ln in lines:
        m = RE_STARTTIME_SEC.match(ln)
        if m:
            start_sec = float(m.group(1))
            break

    # Read "Start time:" line (absolute datetime string)
    start_str = None
    for ln in lines:
        m = RE_STARTTIME_STR.search(ln)
        if m:
            start_str = m.group(1).strip()
            break

    if start_str is None:
        raise ValueError(f"Missing 'Start time:' in {filepath}")

    # Parse frames
    frames_raw = []
    for ln in lines:
        m = RE_FRAME.match(ln)
        if m:
            msgnum  = int(m.group(1))
            offset  = float(m.group(2))   # "Time Offset (ms)" from header
            ftype   = m.group(3)
            canid   = m.group(4)
            dlc     = m.group(5)
            data    = m.group(6)
            frames_raw.append((offset, ftype, canid, dlc, data))

    if not frames_raw:
        raise ValueError(f"No frames found in {filepath}")

    # Convert absolute Start Time string → datetime (lenient parsing)
    start_dt = _parse_start_datetime(start_str)

    # ---------- APPLY RULE ----------
    # FIRST FRAME = Start time (no offset added)
    offset_base = frames_raw[0][0]

    frames = []
    for offset, ftype, canid, dlc, data in frames_raw:
        # Offsets are in ms (with 0.1 ms resolution). Convert to microseconds.
        delta_ms = offset - offset_base               # relative to first frame
        delta_us = int(round(delta_ms * 1000.0))      # ms → µs
        actual_dt = start_dt + timedelta(microseconds=delta_us)
        frames.append((actual_dt, ftype, canid, dlc, data))

    # Include parsed datetime so caller can order files reliably
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

    # Sort by actual parsed start datetime so header matches earliest file
    all_files.sort(key=lambda x: x[2])

    # Remove duplicate TRC files based on STARTTIME seconds
    seen = set()
    unique = []
    for st, st_str, st_dt, fr in all_files:
        dedup_key = st if st is not None else st_dt
        if dedup_key not in seen:
            unique.append((st, st_str, st_dt, fr))
            seen.add(dedup_key)

    # Flatten all frames with timestamps
    merged_all = []
    for st, st_str, _st_dt, frames in unique:
        merged_all.extend(frames)

    # Sort all frames by actual datetime
    merged_all.sort(key=lambda x: x[0])

    # Header of final output = first TRC file's header info
    base_start_sec = (
        unique[0][0] if unique[0][0] is not None else unique[0][2].timestamp()
    )
    base_start_str  = unique[0][1]

    # ------------ BUILD FINAL OUTPUT ------------
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
        line = f"{msgnum:>6})  {ts_str}  {ftype:<7} {canid:>4}  {dlc}  {data}"
        out.append(line)
        msgnum += 1

    return "\n".join(out)


# ------------ GUI FILE PICKER ------------
def main():
    tk.Tk().withdraw()
    filepaths = filedialog.askopenfilenames(
        title="Select TRC files to merge",
        filetypes=[("TRC files", "*.trc")]
    )

    if not filepaths:
        print("No TRC files selected.")
        return

    merged_text = merge_trcs(filepaths)

    # Save merged TRC next to the first selected raw file with PC timestamp in name
    first_folder = Path(filepaths[0]).parent
    ts_str = datetime.now().strftime("%d%b%Y_%H_%M_%S")
    outpath = first_folder / f"Final_Trc_Merged_{ts_str}.trc"
    outpath.write_text(merged_text, encoding="utf-8")

    print("\n=======================================================")
    print("   ✅ MERGE COMPLETE")
    print(f"   Output file saved as: {outpath}")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
