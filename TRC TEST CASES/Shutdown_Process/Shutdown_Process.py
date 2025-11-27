import re
import json
import sys
from dataclasses import dataclass
import matplotlib.pyplot as plt
from pathlib import Path
import textwrap

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
ID_SOC_STATE  = 0x109       # BMS SoC + BMS state
ID_MCU        = 0x12B       # MCU counter
ID_VEHICLE    = 0x602       # Vehicle state (byte7)
ID_ACK        = 0x106       # BMS ACK
ID_SHUT       = 0x1840F400  # VCU Shutdown Command


# -------------------------------------------------------
# CAN FRAME STRUCTURE
# -------------------------------------------------------
@dataclass
class Frame:
    ts: str
    can_id: int
    data: list


# -------------------------------------------------------
# TRC PARSER
# -------------------------------------------------------
def parse_trc(filepath):
    """
    Parse a Vector TRC log file and extract timestamp, CAN ID, and data bytes.
    Returns a list of Frame objects with timestamp preserved as-is.
    """
    frames = []
    line_re = re.compile(
        r"^\s*\d+\)\s+([0-9\-]+ [0-9:\.]+)\s+Rx\s+([0-9A-Fa-f]+)\s+8\s+(.+)$"
    )

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = line_re.search(line)
            if not m:
                continue

            ts = m.group(1)
            can_id = int(m.group(2), 16)
            data_bytes = m.group(3).strip().split()
            if len(data_bytes) < 8:
                continue
            data = [int(b, 16) for b in data_bytes[:8]]

            frames.append(Frame(ts=ts, can_id=can_id, data=data))

    return frames


def _ts_to_float(ts: str) -> float:
    """Extract a floating-point seconds value from the TRC timestamp string."""
    ts_match = re.search(r"(\d+\.\d+)", ts)
    return float(ts_match.group(1)) if ts_match else 0.0


def _ts_multiline(ts: str) -> str:
    """Break the timestamp into date and time on separate lines for display."""
    if " " in ts:
        return ts.replace(" ", "\n", 1)
    return ts


# -------------------------------------------------------
# DECODE FUNCTIONS
# -------------------------------------------------------
def decode_soc(fr: Frame) -> float:
    raw = (fr.data[1] << 8) | fr.data[0]
    return raw * 0.01

def decode_bms_state(fr: Frame) -> int:
    return fr.data[4]

def decode_vehicle_state(fr: Frame) -> int:
    # Vehicle state resides in the last byte (byte7): 0x02=drive, 0x00=off.
    return fr.data[7]

def decode_mcu(fr: Frame) -> int:
    return (fr.data[3] << 8) | fr.data[2]

def has_ack(fr: Frame) -> bool:
    return fr.data[0] == 0x01


# -------------------------------------------------------
# FIND 602 -> (2 or 1 -> 0) TRANSITIONS
# -------------------------------------------------------
def get_vehicle_2_to_0_transitions(frames):
    times = []
    prev = None

    for fr in frames:
        if fr.can_id != ID_VEHICLE:
            continue

        state = decode_vehicle_state(fr)

        if prev in (0x02, 0x01) and state == 0x00:
            times.append(_ts_to_float(fr.ts))

        prev = state

    return times


# -------------------------------------------------------
# SHUTDOWN ANALYSIS CORE
# -------------------------------------------------------
def analyze(frames):
    # All observed 1/2->0 transitions in log (anywhere)
    veh_2to0 = get_vehicle_2_to_0_transitions(frames)

    cycles = []
    active = False

    start_soc = None
    reflect_soc = None
    ack_time = None
    mcu_at_shut = None
    bms_zero_seen = False
    bms_exit_zero = False
    ts_shut = None
    ts_shut_raw = None

    for fr in frames:

        # Detect start of a shutdown cycle: 1840F400
        if fr.can_id == ID_SHUT:
            if not active:
                active = True
                start_soc = None
                reflect_soc = None
                ack_time = None
                mcu_at_shut = None
                bms_zero_seen = False
                bms_exit_zero = False
                ts_shut = _ts_to_float(fr.ts)
                ts_shut_raw = fr.ts
            continue

        if not active:
            continue

        # Decode SoC & BMS State (0x109)
        if fr.can_id == ID_SOC_STATE:
            soc = decode_soc(fr)
            bms_st = decode_bms_state(fr)

            # Start SoC = first non-zero state SoC after shutdown command
            if start_soc is None and bms_st != 0:
                start_soc = soc

            # Detect BMS going to 0
            if bms_st == 0 and not bms_zero_seen:
                bms_zero_seen = True

            # First non-zero state after having been 0 → Reflect SoC (ignore zero SoC glitches)
            if bms_zero_seen and bms_st != 0 and not bms_exit_zero and soc > 0:
                reflect_soc = soc
                bms_exit_zero = True

        # First MCU after shutdown command
        if fr.can_id == ID_MCU and mcu_at_shut is None:
            mcu_at_shut = decode_mcu(fr)

        # First ACK after shutdown
        if fr.can_id == ID_ACK and has_ack(fr):
            if ack_time is None:
                ack_time = _ts_to_float(fr.ts)

        # End cycle once BMS has gone 0 -> non-zero
        if bms_exit_zero:

            # ----- SoC result -----
            if start_soc is not None and reflect_soc is not None:
                delta = round(start_soc - reflect_soc, 3)
                soc_result = "PASS" if abs(delta) <= 0.1 else "FAIL"
            else:
                delta = None
                soc_result = "SHUT_MISS"

            # ----- ACK result -----
            if mcu_at_shut is None:
                ack_state = "NO_MCU"
            else:
                if mcu_at_shut < 105:
                    ack_state = "NO_ACK_NEEDED" if ack_time is None else "ACK_UNEXPECTED"
                elif 105 <= mcu_at_shut <= 200:
                    ack_state = "ACK_OPTIONAL"
                else:
                    ack_state = "ACK_OK" if ack_time is not None else "ACK_MISSING"

            # ----- ACK time label -----
            if ack_time is None:
                ack_time_lbl = "MISS"
            else:
                ack_time_lbl = f"{round(ack_time - ts_shut, 3)}s"

            # ----- Vehicle timing -----
            # Only judge VCU if we actually have at least one 1/2->0 transition in the log.
            if veh_2to0:
                best_dt = None
                for t in veh_2to0:
                    dt = t - ts_shut
                    if abs(dt) <= 2.0:
                        if best_dt is None or abs(dt) < abs(best_dt):
                            best_dt = dt

                if best_dt is None:
                    # We have 1/2->0 transitions in log, but NONE were within 2s of this shutdown → real misalignment
                    veh_timing = "VCU_FAULT(>2s)"
                else:
                    veh_timing = f"OK({round(abs(best_dt),3)}s)"
            else:
                # No 1/2->0 transition anywhere in log → do NOT blame VCU/BMS, just mark as incomplete.
                veh_timing = "INCOMPLETE(no 1/2->0 transition)"

            # ----- Final decision -----
            final = "PASS"
            if soc_result != "PASS":
                final = "FAIL"
            if ack_state in ("ACK_UNEXPECTED", "ACK_MISSING"):
                final = "FAIL"
            if veh_timing.startswith("VCU_FAULT"):
                final = "FAIL"
            # Note: "INCOMPLETE(...)" does NOT force FAIL. We are not blaming anyone.

            # ----- Remarks -----
            remark = "—"

            if final == "FAIL":

                if veh_timing.startswith("VCU_FAULT"):
                    remark = "VCU Fault - Vehicle 1/2->0 and shutdown not aligned within 2s."

                elif veh_timing.startswith("INCOMPLETE"):
                    # This branch technically won't hit with final=FAIL,
                    # but kept for clarity if logic later changes.
                    remark = "Data incomplete - 1/2->0 transition not fully captured in log."

                elif ack_state == "ACK_MISSING":
                    remark = f"BMS Fault - Expected ACK missing when MCU >= 105 (MCU={mcu_at_shut})."

                elif ack_state == "ACK_UNEXPECTED":
                    remark = f"BMS Fault - Unexpected ACK when MCU < 105 (MCU={mcu_at_shut})."

                elif ack_state == "NO_MCU":
                    remark = "Integration Fault - MCU counter frame missing."

                elif soc_result == "SHUT_MISS":
                    remark = "VCU/BMS Integration Fault - No BMS reboot detected."

                elif soc_result != "PASS":
                    remark = "BMS Fault - Incorrect SoC restoration."
            elif ack_state == "ACK_OPTIONAL":
                remark = "ACK optional zone (MCU between 105–200)"

            # Save this shutdown cycle
            cycles.append({
                "Start_SoC": start_soc,
                "Reflect_SoC": reflect_soc,
                "Delta": delta,
                "SoC_Result": soc_result,
                "MCU": mcu_at_shut,
                "ACK_Time": ack_time_lbl,
                "ACK_State": ack_state,
                "VehTime": veh_timing,
                "Shutdown": "OK" if soc_result != "SHUT_MISS" else "MISSING",
                "Final": final,
                "Remark": remark,
                "Shutdown_ts": ts_shut,
                "Shutdown_ts_raw": ts_shut_raw
            })

            active = False

    return cycles


# -------------------------------------------------------
# JSON EXPORT (first version - kept but overridden later)
# -------------------------------------------------------
def save_json(cycles, filepath):

    out = []
    for i, c in enumerate(cycles, 1):
        out.append({
            "cycle": i,
            "StartSoC": c["Start_SoC"],
            "ReflectSoC": c["Reflect_SoC"],
            "Delta": c["Delta"],
            "SoC_Result": c["SoC_Result"],
            "MCU": c["MCU"],
            "ACK_Time": c["ACK_Time"],
            "ACK_State": c["ACK_State"],
            "VehicleTiming": c["VehTime"],
            "Shutdown": c["Shutdown"],
            "Final": c["Final"],
            "Remark": c["Remark"]
        })

    out_path = filepath.replace(".trc", "_shutdown_report.json")
    with open(out_path, "w", encoding="utf-8") as jf:
        json.dump(out, jf, indent=4, ensure_ascii=False)

    print(f"\nJSON saved → {out_path}")


# -------------------------------------------------------
# JSON EXPORT (override: save next to this script)
# -------------------------------------------------------
def save_json(cycles, filepath):
    out = []
    for i, c in enumerate(cycles, 1):
        out.append({
            "cycle": i,
            "StartSoC": c["Start_SoC"],
            "ReflectSoC": c["Reflect_SoC"],
            "Delta": c["Delta"],
            "SoC_Result": c["SoC_Result"],
            "MCU": c["MCU"],
            "ACK_Time": c["ACK_Time"],
            "ACK_State": c["ACK_State"],
            "VehicleTiming": c["VehTime"],
            "Shutdown": c["Shutdown"],
            "Final": c["Final"],
            "Remark": c["Remark"]
        })
    out_path = Path(__file__).resolve().parent / "Shutdown_Process_summary.json"
    with open(out_path, "w", encoding="utf-8") as jf:
        json.dump(out, jf, indent=4, ensure_ascii=False)

    header = (
        f"{'Cycle':>5} | {'Shut_ts':>8} | {'StartSoC':>8} | {'ReflectSoC':>10} | {'Delta':>6} | "
        f"{'SoC':>5} | {'MCU':>5} | {'ACK Time':>10} | {'ACK_State':>13} | "
        f"{'VehTime':>12} | {'Final':>6} | {'Remark'}"
    )
    lines = [header, "-" * len(header)]
    for i, c in enumerate(cycles, 1):
        ss = f"{c['Start_SoC']:.2f}" if c['Start_SoC'] is not None else "--"
        rs = f"{c['Reflect_SoC']:.2f}" if c['Reflect_SoC'] is not None else "--"
        ds = f"{c['Delta']:.2f}" if c['Delta'] is not None else "--"
        mcu_str = "--" if c["MCU"] is None else str(c["MCU"])
        ts_raw = c.get("Shutdown_ts_raw") or "--"
        ts_str = _ts_multiline(ts_raw)
        lines.append(
            f"{i:5d} | {ts_str:>8} | {ss:>8} | {rs:>10} | {ds:>6} | "
            f"{c['SoC_Result']:<5} | {mcu_str:>5} | "
            f"{c['ACK_Time']:<10} | {c['ACK_State']:<13} | "
            f"{c['VehTime']:<12} | {c['Final']:<6} | {c['Remark']}"
        )
    txt_path = Path(__file__).resolve().parent / "Shutdown_Process_summary.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    overall_result = "PASS" if cycles and all(c.get("Final") == "PASS" for c in cycles) else "FAIL"
    results_path = Path(__file__).resolve().parent / "Shutdown_Process_results.json"
    with open(results_path, "w", encoding="utf-8") as jf:
        json.dump({"Result": overall_result}, jf, indent=4, ensure_ascii=False)

    print(f"\nJSON saved -> {out_path}")
    print(f"Table saved -> {txt_path}")
    print(f"Overall result saved -> {results_path} ({overall_result})")


# -------------------------------------------------------
# JSON EXPORT (final override: JSON with embedded table + PNG)
# -------------------------------------------------------
def save_json(cycles, filepath):
    def _clean(text):
        t = str(text)
        for seq in ["â€”", "â€“", "\u2014", "\u2013"]:
            t = t.replace(seq, "-")
        for seq in ["â†’", "\u2192"]:
            t = t.replace(seq, "->")
        t = t.replace("â€™", "'")
        return t

    summary = []
    for i, c in enumerate(cycles, 1):
        summary.append({
            "cycle": i,
            "StartSoC": c["Start_SoC"],
            "ReflectSoC": c["Reflect_SoC"],
            "Delta": c["Delta"],
            "SoC_Result": c["SoC_Result"],
            "MCU": c["MCU"],
            "ACK_Time": c["ACK_Time"],
            "ACK_State": c["ACK_State"],
            "VehicleTiming": c["VehTime"],
            "Shutdown": c["Shutdown"],
            "Final": c["Final"],
            "Remark": c["Remark"]
        })

    header = (
        f"{'Cycle':>5} | {'Shut_ts':>8} | {'StartSoC':>8} | {'ReflectSoC':>10} | {'Delta':>6} | "
        f"{'SoC':>5} | {'MCU':>5} | {'ACK Time':>10} | {'ACK_State':>13} | "
        f"{'VehTime':>12} | {'Final':>6} | {'Remark'}"
    )
    table_rows = []
    for i, c in enumerate(cycles, 1):
        ss = f"{c['Start_SoC']:.2f}" if c['Start_SoC'] is not None else "--"
        rs = f"{c['Reflect_SoC']:.2f}" if c['Reflect_SoC'] is not None else "--"
        ds = f"{c['Delta']:.2f}" if c['Delta'] is not None else "--"
        mcu_str = "--" if c["MCU"] is None else str(c["MCU"])
        remark_clean = _clean(c["Remark"])
        ts_raw = c.get("Shutdown_ts_raw") or "--"
        ts_str = _ts_multiline(ts_raw)
        table_rows.append(
            f"{i:5d} | {ts_str:>8} | {ss:>8} | {rs:>10} | {ds:>6} | "
            f"{c['SoC_Result']:<5} | {mcu_str:>5} | "
            f"{c['ACK_Time']:<10} | {c['ACK_State']:<13} | "
            f"{c['VehTime']:<12} | {c['Final']:<6} | {remark_clean}"
        )

    if not table_rows:
        placeholder = (
            f"{1:5d} | {'--':>8} | {'--':>8} | {'--':>10} | {'--':>6} | "
            f"{'N/A':<5} | {'--':>5} | {'--':<10} | {'NO_SHUT':<13} | "
            f"{'--':<12} | {'N/A':<6} | {'No shutdown events found in the TRC log.'}"
        )
        table_rows.append(placeholder)

    payload = {
        "table_header": header,
        "table_rows": table_rows,
    }

    out_path = Path(__file__).resolve().parent / "Shutdown_Process_summary.json"
    with open(out_path, "w", encoding="utf-8") as jf:
        json.dump(payload, jf, indent=4, ensure_ascii=False)

    if not cycles:
        overall_result = "PASS"  # Nothing to fail if no shutdown was commanded
    else:
        overall_result = "PASS" if all(c.get("Final") == "PASS" for c in cycles) else "FAIL"
    results_path = Path(__file__).resolve().parent / "Shutdown_Process_results.json"
    with open(results_path, "w", encoding="utf-8") as jf:
        json.dump({"Result": overall_result}, jf, indent=4, ensure_ascii=False)

    print(f"\nJSON saved -> {out_path}")
    print(f"Overall result saved -> {results_path} ({overall_result})")

    save_plot_png(cycles)


def save_plot_png(cycles):
    """Render the cycle summary as a colored table and save to PNG next to the script."""
    headers = [
        "Shutdown\ncycle", "Shut_ts", "StartSoC", "ReflectSoC",
        "Delta", "SoC", "MCU", "ACK Time", "ACK_State",
        "VehTime", "Final", "Remark"
    ]

    if not cycles:
        rows = [[
            "1", "--", "--", "--", "--", "N/A", "--", "--",
            "NO_SHUT", "--", "N/A", "No shutdown events found in the TRC log."
        ]]
    else:
        rows = []
        for idx, c in enumerate(cycles, start=1):
            row = [
                str(idx),
                _ts_multiline(c.get("Shutdown_ts_raw") or "--"),
                c.get("Start_SoC"),
                c.get("Reflect_SoC"),
                c.get("Delta"),
                c.get("SoC_Result"),
                c.get("MCU"),
                c.get("ACK_Time"),
                c.get("ACK_State"),
                c.get("VehTime"),
                c.get("Final"),
                c.get("Remark"),
            ]
            rows.append(row)

    fig_height = max(2, 0.6 * len(rows) + 2)
    fig_width = 18
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")

    col_widths = [0.06, 0.08, 0.08, 0.10, 0.08, 0.07, 0.06, 0.06, 0.14, 0.10, 0.06, 0.27]
    table = ax.table(
        cellText=rows,
        colLabels=headers,
        colWidths=col_widths,
        loc="center",
        cellLoc="center"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.1, 1.3)

    for (r, c_idx), cell in table.get_celld().items():
        cell.set_edgecolor("black")
        cell.set_height(cell.get_height() * 2.0)
        if r == 0:
            cell.set_facecolor("#dddddd")
            cell.set_text_props(weight="bold", ha="center", va="center")
        else:
            # rows[r-1][10] is "Final" column
            final_val = rows[r-1][10]
            if final_val == "PASS":
                face = "#d4edda"
            elif final_val == "FAIL":
                face = "#f8d7da"
            else:
                face = "#f0f0f0"
            cell.set_facecolor(face)
            cell.set_text_props(ha="center", va="center")

    out_path = Path(__file__).resolve().parent / "Shutdown_Process_plot.png"
    plt.savefig(out_path, bbox_inches="tight", dpi=200)
    plt.close(fig)


# -------------------------------------------------------
# MAIN (TRC path provided by GUI argument)
# -------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("ERROR: No TRC file received from GUI!")
        sys.exit(1)

    filepath = sys.argv[1]
    if not Path(filepath).exists():
        print(f"ERROR: TRC file not found: {filepath}")
        sys.exit(1)

    print(f"Using TRC file from GUI: {filepath}")

    frames = parse_trc(filepath)
    cycles = analyze(frames)

    header = (
        f"{'Cycle':>5} | {'StartSoC':>8} | {'ReflectSoC':>10} | {'Delta':>6} | "
        f"{'SoC':>5} | {'MCU':>5} | {'ACK Time':>10} | {'ACK_State':>13} | "
        f"{'VehTime':>12} | {'Final':>6} | {'Remark'}"
    )
    print("\n" + header)
    print("-" * len(header))

    for i, c in enumerate(cycles, 1):
        ss = f"{c['Start_SoC']:.2f}" if c['Start_SoC'] is not None else "--"
        rs = f"{c['Reflect_SoC']:.2f}" if c['Reflect_SoC'] is not None else "--"
        ds = f"{c['Delta']:.2f}" if c['Delta'] is not None else "--"
        mcu_str = "--" if c["MCU"] is None else str(c["MCU"])
        ts_raw = c.get("Shutdown_ts_raw") or "--"
        ts_str = _ts_multiline(ts_raw)

        print(
            f"{i:5d} | {ts_str:>8} | {ss:>8} | {rs:>10} | {ds:>6} | "
            f"{c['SoC_Result']:<5} | {mcu_str:>5} | "
            f"{c['ACK_Time']:<10} | {c['ACK_State']:<13} | "
            f"{c['VehTime']:<12} | {c['Final']:<6} | {c['Remark']}"
        )

    save_json(cycles, filepath)


if __name__ == "__main__":
    main()
