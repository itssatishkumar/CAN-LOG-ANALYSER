#!/usr/bin/env python3
"""
Shutdown Process Analysis for CAN Log Analyser
Production version - minimal console output
"""
import re
import json
import sys
from dataclasses import dataclass
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
import textwrap

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))
from trc_utils import progress_by_bytes

PROGRESS_STEP = 0.5

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
ID_SOC_STATE = 0x109       # SOC (battery percentage)
ID_MCU = 0x12B             # MCU counter
ID_VEHICLE = 0x602         # Vehicle state (byte7: 0x02/0x01=running, 0x00=off)
ID_ACK = 0x106             # ACK (byte0 = 0x01)
ID_SHUT = 0x1840F400       # Shutdown command

# -------------------------------------------------------
# CAN FRAME STRUCTURE
# -------------------------------------------------------
@dataclass
class Frame:
    ts: str
    ts_sec: float
    can_id: int
    data: list

# -------------------------------------------------------
# TIMESTAMP PARSING
# -------------------------------------------------------
def parse_timestamp(ts_str: str) -> float:
    """Convert timestamp to seconds since epoch"""
    try:
        if ' ' in ts_str:
            if '.' in ts_str:
                base_ts, fractional = ts_str.split('.')
                fractional = fractional.ljust(6, '0')[:6]
                ts_str_padded = f"{base_ts}.{fractional}"
            else:
                ts_str_padded = ts_str + '.000000'
            
            dt = datetime.strptime(ts_str_padded, "%d-%m-%Y %H:%M:%S.%f")
            return dt.timestamp()
        else:
            parts = ts_str.split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
    except Exception:
        try:
            if ' ' in ts_str:
                date_part, time_part = ts_str.split()
                day, month, year = map(int, date_part.split('-'))
                hours, minutes, sec_part = time_part.split(':')
                
                if '.' in sec_part:
                    seconds_str, fractional_str = sec_part.split('.')
                    seconds = int(seconds_str)
                    fractional_seconds = float(f"0.{fractional_str}")
                else:
                    seconds = int(sec_part)
                    fractional_seconds = 0
                
                total_seconds = seconds + fractional_seconds
                dt = datetime(year, month, day, int(hours), int(minutes), int(total_seconds))
                dt = dt.replace(microsecond=int((total_seconds % 1) * 1000000))
                return dt.timestamp()
            else:
                parts = ts_str.split(':')
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
        except:
            return 0.0

# -------------------------------------------------------
# TRC PARSER
# -------------------------------------------------------
def parse_trc(filepath, progress_cb=None):
    frames = []
    line_re = re.compile(r"^\s*\d+\)\s+([0-9\-]+ [0-9:\.]+)\s+Rx\s+([0-9A-Fa-f]+)\s+8\s+(.+)$")
    
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if progress_cb:
                progress_cb(len(line))
            m = line_re.search(line)
            if not m:
                continue
            ts_str = m.group(1)
            can_id = int(m.group(2), 16)
            data_bytes = m.group(3).strip().split()
            if len(data_bytes) < 8:
                continue
            ts_sec = parse_timestamp(ts_str)
            data = [int(b, 16) for b in data_bytes[:8]]
            frames.append(Frame(ts=ts_str, ts_sec=ts_sec, can_id=can_id, data=data))
    
    return frames

# -------------------------------------------------------
# DECODE FUNCTIONS
# -------------------------------------------------------
def decode_soc(fr: Frame) -> float:
    raw = (fr.data[1] << 8) | fr.data[0]
    return raw * 0.01

def decode_vehicle_state(fr: Frame) -> int:
    return fr.data[7]

def decode_mcu(fr: Frame) -> int:
    return (fr.data[3] << 8) | fr.data[2]

def has_ack(fr: Frame) -> bool:
    return fr.data[0] == 0x01

# -------------------------------------------------------
# SHUTDOWN DETECTION
# -------------------------------------------------------
def detect_shutdown_events(frames):
    events = []
    prev_state = None
    prev_ts_sec = None
    prev_ts_str = None
    last_cycle_sec = None
    pending_shut = None
    pending_veh = None
    
    for fr in frames:
        ts_sec = fr.ts_sec
        ts_str = fr.ts
        
        if last_cycle_sec is not None and (ts_sec - last_cycle_sec) < 3.0:
            continue
        
        if fr.can_id == ID_VEHICLE:
            state = decode_vehicle_state(fr)
            
            if prev_state in (0x02, 0x01) and state == 0x00:
                if pending_shut is not None:
                    time_diff = ts_sec - pending_shut["ts_sec"]
                    if time_diff < 3.0:
                        veh_time = ts_sec - (prev_ts_sec if prev_ts_sec < pending_shut["ts_sec"] else pending_shut["ts_sec"])
                        events.append({
                            "shut_ts": pending_shut["ts_str"],
                            "shut_ts_sec": pending_shut["ts_sec"],
                            "shut_cmd_ts_sec": pending_shut["ts_sec"],
                            "shutdown_cmd": "FOUND",
                            "vehicle_transition": "FOUND",
                            "veh_time": round(veh_time, 3),
                            "time_between": round(time_diff, 3),
                            "first_event": "SHUTDOWN_CMD",
                            "shut_cmd_missing": False,
                            "bms_missing": False,
                            "can_bus_issue": False
                        })
                        last_cycle_sec = pending_shut["ts_sec"]
                        pending_shut = None
                        pending_veh = None
                    else:
                        pending_shut = None
                else:
                    pending_veh = {
                        "ts_sec": ts_sec, 
                        "ts_str": ts_str, 
                        "prev_ts_sec": prev_ts_sec, 
                        "prev_ts_str": prev_ts_str
                    }
            
            prev_state = state
            prev_ts_sec = ts_sec
            prev_ts_str = ts_str
        
        elif fr.can_id == ID_SHUT:
            if pending_veh is not None:
                time_diff = ts_sec - pending_veh["ts_sec"]
                if time_diff < 3.0:
                    veh_time = pending_veh["ts_sec"] - pending_veh["prev_ts_sec"]
                    events.append({
                        "shut_ts": ts_str,
                        "shut_ts_sec": ts_sec,
                        "shut_cmd_ts_sec": ts_sec,
                        "shutdown_cmd": "FOUND",
                        "vehicle_transition": "FOUND",
                        "veh_time": round(veh_time, 3),
                        "time_between": round(time_diff, 3),
                        "first_event": "VEHICLE_TRANSITION",
                        "shut_cmd_missing": False,
                        "bms_missing": False,
                        "can_bus_issue": False
                    })
                    last_cycle_sec = pending_veh["ts_sec"]
                    pending_shut = None
                    pending_veh = None
                else:
                    pending_veh = None
            else:
                pending_shut = {"ts_sec": ts_sec, "ts_str": ts_str}
        
        if pending_shut is not None and (ts_sec - pending_shut["ts_sec"]) > 3.0:
            events.append({
                "shut_ts": pending_shut["ts_str"],
                "shut_ts_sec": pending_shut["ts_sec"],
                "shut_cmd_ts_sec": pending_shut["ts_sec"],
                "shutdown_cmd": "FOUND",
                "vehicle_transition": "NOT_FOUND",
                "veh_time": None,
                "time_between": None,
                "first_event": "SHUTDOWN_CMD_ONLY",
                "shut_cmd_missing": False,
                "bms_missing": False,
                "can_bus_issue": False
            })
            pending_shut = None
        
        if pending_veh is not None and (ts_sec - pending_veh["ts_sec"]) > 3.0:
            veh_transition_ts = pending_veh["ts_sec"]
            
            bms_before = False
            for fr2 in frames:
                if fr2.ts_sec > veh_transition_ts:
                    break
                if fr2.can_id == ID_MCU:
                    bms_before = True
                    break
            
            bms_after = False
            for fr2 in frames:
                if fr2.ts_sec < veh_transition_ts:
                    continue
                if fr2.ts_sec > veh_transition_ts + 2.0:
                    break
                if fr2.can_id == ID_MCU:
                    bms_after = True
                    break
            
            if bms_before and not bms_after:
                events.append({
                    "shut_ts": pending_veh["ts_str"],
                    "shut_ts_sec": pending_veh["ts_sec"],
                    "shut_cmd_ts_sec": None,
                    "shutdown_cmd": "MISSING",
                    "vehicle_transition": "FOUND",
                    "veh_time": pending_veh["ts_sec"] - pending_veh["prev_ts_sec"],
                    "time_between": None,
                    "first_event": "VEHICLE_TRANSITION_ONLY",
                    "shut_cmd_missing": True,
                    "bms_missing": False,
                    "can_bus_issue": True
                })
            elif not bms_before and not bms_after:
                events.append({
                    "shut_ts": pending_veh["ts_str"],
                    "shut_ts_sec": pending_veh["ts_sec"],
                    "shut_cmd_ts_sec": None,
                    "shutdown_cmd": "MISSING",
                    "vehicle_transition": "FOUND",
                    "veh_time": pending_veh["ts_sec"] - pending_veh["prev_ts_sec"],
                    "time_between": None,
                    "first_event": "VEHICLE_TRANSITION_ONLY",
                    "shut_cmd_missing": True,
                    "bms_missing": True,
                    "can_bus_issue": False
                })
            else:
                events.append({
                    "shut_ts": pending_veh["ts_str"],
                    "shut_ts_sec": pending_veh["ts_sec"],
                    "shut_cmd_ts_sec": None,
                    "shutdown_cmd": "MISSING",
                    "vehicle_transition": "FOUND",
                    "veh_time": pending_veh["ts_sec"] - pending_veh["prev_ts_sec"],
                    "time_between": None,
                    "first_event": "VEHICLE_TRANSITION_ONLY",
                    "shut_cmd_missing": True,
                    "bms_missing": False,
                    "can_bus_issue": False
                })
            pending_veh = None
    
    return events

# -------------------------------------------------------
# SOC RESTORE ANALYSIS
# -------------------------------------------------------
def analyze_soc_restore(frames, shutdown_events):
    results = []
    
    for ev in shutdown_events:
        if ev.get("shut_cmd_missing", False):
            if ev.get("can_bus_issue", False):
                remark_text = "CAN bus communication issue - BMS CAN IDs stopped after vehicle transition (1840F400 missing)"
            elif ev.get("bms_missing", False):
                remark_text = "BMS offline/dead - No BMS CAN IDs detected at all (1840F400 missing)"
            else:
                remark_text = "1840F400 missing - Vehicle transition without shutdown command (VCU_Fault)"
            
            results.append({
                **ev,
                "Start_SoC": None,
                "Reflect_SoC": None,
                "Delta": None,
                "SoC_Result": "INCOMPLETE",
                "MCU_After_Shutdown": None,
                "MCU_Reset": "NOT_FOUND",
                "MCU_Reboot_Complete": "NO_SHUTDOWN_CMD",
                "ACK_Received": "MISSING",
                "ACK_Time": "N/A",
                "Final": "FAIL",
                "Remark": remark_text
            })
            continue
        
        ack_ref_sec = ev["shut_cmd_ts_sec"]
        
        start_soc = None
        reflect_soc = None
        prev_mcu = None
        mcu_after_shutdown = None
        mcu_reset_seen = False
        mcu_reboot_complete = False
        ack_received = False
        ack_time_diff = None
        
        for fr in frames:
            if fr.ts_sec < ack_ref_sec:
                continue
            
            if fr.can_id == ID_ACK and has_ack(fr):
                if not ack_received:
                    ack_received = True
                    ack_time_diff = round(fr.ts_sec - ack_ref_sec, 3)
            
            if fr.can_id == ID_MCU:
                mcu = decode_mcu(fr)
                
                if mcu_after_shutdown is None:
                    mcu_after_shutdown = mcu
                
                if prev_mcu is not None and mcu < prev_mcu:
                    mcu_reset_seen = True
                
                if mcu_reset_seen and mcu >= 3 and not mcu_reboot_complete:
                    mcu_reboot_complete = True
                
                prev_mcu = mcu
            
            elif fr.can_id == ID_SOC_STATE:
                soc = decode_soc(fr)
                
                if not mcu_reset_seen and start_soc is None:
                    start_soc = round(soc, 2)
                elif mcu_reboot_complete and reflect_soc is None:
                    reflect_soc = round(soc, 2)
                    break
        
        ack_status = "PASS" if ack_received else "MISSING"
        ack_time_str = f"{ack_time_diff}s" if ack_time_diff else "N/A"
        
        if not mcu_reset_seen:
            delta_soc = None
            soc_result = "INCOMPLETE"
            mcu_status = "NO_RESET"
        elif not mcu_reboot_complete:
            delta_soc = None
            soc_result = "INCOMPLETE"
            mcu_status = "RESET_BUT_NO_REBOOT"
        else:
            mcu_status = "REBOOT_COMPLETE"
            if start_soc is not None and reflect_soc is not None:
                delta_soc = round(abs(start_soc - reflect_soc), 3)
                soc_result = "PASS" if delta_soc <= 0.1 else "FAIL"
            else:
                delta_soc = None
                soc_result = "INCOMPLETE"
        
        final = "PASS"
        remark = "-"
        
        if ev.get("first_event") == "VEHICLE_TRANSITION":
            remark = f"Vehicle off before shutdown command (Δ={ev['time_between']}s)"
        elif ev.get("first_event") == "SHUTDOWN_CMD_ONLY":
            remark = "Shutdown command with no vehicle transition within 3s"
        
        if ack_status == "MISSING":
            if mcu_after_shutdown is not None and mcu_after_shutdown < 90:
                ack_status = "NO_ACK_NEEDED"
                remark += f" | BMS ACK missing but MCU={mcu_after_shutdown} (<90) - ACK not required"
            elif mcu_after_shutdown is not None and 90 <= mcu_after_shutdown <= 200:
                ack_status = "ACK_OPTIONAL"
                remark += f" | BMS ACK missing but MCU={mcu_after_shutdown} (90-200) - ACK optional"
            else:
                final = "FAIL"
                remark += f" | BMS ACK missing after shutdown (MCU={mcu_after_shutdown})"
        
        if soc_result != "PASS":
            final = "FAIL"
            if soc_result == "INCOMPLETE":
                remark += f" | Incomplete SOC data - start={start_soc}, reflect={reflect_soc}"
            else:
                remark += f" | SOC restoration failed (delta={delta_soc}% > 0.1%)"
        
        if mcu_status != "REBOOT_COMPLETE":
            final = "FAIL"
            if mcu_status == "NO_RESET":
                remark += " | MCU reset not detected"
            elif mcu_status == "RESET_BUT_NO_REBOOT":
                remark += f" | MCU reset but did not reach >=3 (max MCU={prev_mcu})"
        
        if remark.startswith(" | "):
            remark = remark[3:]
        
        results.append({
            **ev,
            "Start_SoC": start_soc,
            "Reflect_SoC": reflect_soc,
            "Delta": delta_soc,
            "SoC_Result": soc_result,
            "MCU_After_Shutdown": mcu_after_shutdown,
            "MCU_Reset": "FOUND" if mcu_reset_seen else "NOT_FOUND",
            "MCU_Reboot_Complete": mcu_status,
            "ACK_Received": ack_status,
            "ACK_Time": ack_time_str,
            "Final": final,
            "Remark": remark
        })
    
    return results

# -------------------------------------------------------
# SAVE RESULTS
# -------------------------------------------------------
def save_results(cycles, filepath):
    out = []
    for i, c in enumerate(cycles, 1):
        out.append({
            "cycle": i,
            "shutdown_timestamp": c["shut_ts"],
            "veh_time_s": c["veh_time"],
            "time_between_s": c["time_between"],
            "Start_SoC": c["Start_SoC"],
            "Reflect_SoC": c["Reflect_SoC"],
            "Delta": c["Delta"],
            "SoC_Result": c["SoC_Result"],
            "MCU_After_Shutdown": c["MCU_After_Shutdown"],
            "MCU_Reset": c["MCU_Reset"],
            "MCU_Reboot_Complete": c["MCU_Reboot_Complete"],
            "ACK_Received": c["ACK_Received"],
            "ACK_Time": c["ACK_Time"],
            "Final": c["Final"],
            "Remark": c["Remark"]
        })

    out_path = Path(__file__).resolve().parent / "Shutdown_Process_summary.json"
    with open(out_path, "w", encoding="utf-8") as jf:
        json.dump(out, jf, indent=4, ensure_ascii=False)

    save_plot_png(cycles)

    if not cycles:
        overall_result = "PASS"
    else:
        overall_result = (
            "PASS"
            if all(c.get("Final") == "PASS" for c in cycles)
            else "FAIL"
        )

    results_path = Path(__file__).resolve().parent / "Shutdown_Process_results.json"
    with open(results_path, "w", encoding="utf-8") as jf:
        json.dump({"Result": overall_result}, jf, indent=4, ensure_ascii=False)

    return overall_result

def save_plot_png(cycles):
    headers = [
        "Cycle", "Shutdown Timestamp", "Start\nSoC (%)", "Reflect\nSoC(%)",
        "SoC\nDelta", "SoC\nResult", "BMS_MCU\nCounter", "BMS_ACK\nTime", "Final", "Remark"
    ]
    
    if not cycles:
        rows = [["1", "--", "--", "--", "--", "N/A", "--", "--", "N/A", "No shutdown events found"]]
    else:
        rows = []
        for idx, c in enumerate(cycles, start=1):
            if c['ACK_Received'] == "PASS" and c['ACK_Time'] != "N/A":
                ack_display = f"PASS({c['ACK_Time']})"
            else:
                ack_display = c['ACK_Received']
            
            remark_text = c['Remark'] if c['Remark'] else "--"
            wrapped_lines = textwrap.wrap(remark_text, 45)
            wrapped_remark = '\n'.join(wrapped_lines)
            
            row = [
                str(idx),
                c["shut_ts"],
                f"{c['Start_SoC']:.2f}" if c['Start_SoC'] is not None else "--",
                f"{c['Reflect_SoC']:.2f}" if c['Reflect_SoC'] is not None else "--",
                f"{c['Delta']:.3f}" if c['Delta'] is not None else "--",
                c['SoC_Result'],
                str(c['MCU_After_Shutdown']) if c['MCU_After_Shutdown'] is not None else "--",
                ack_display,
                c['Final'],
                wrapped_remark
            ]
            rows.append(row)
    
    max_remark_lines = 1
    for row in rows:
        remark = row[9]
        if remark and '\n' in remark:
            lines = remark.count('\n') + 1
            max_remark_lines = max(max_remark_lines, lines)
    
    base_height = 0.5 * len(rows)
    extra_height = 0.15 * (max_remark_lines - 1) * len(rows)
    fig_height = max(3, base_height + extra_height + 2)
    fig_width = 22
    
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")
    
    col_widths = [0.03, 0.12, 0.05, 0.07, 0.05, 0.07, 0.07, 0.08, 0.04, 0.2]
    table = ax.table(cellText=rows, colLabels=headers, colWidths=col_widths, 
                     cellLoc="center", bbox=[0.0, 0.0, 1.0, 1.0])
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.1, 1.3)
    
    for (r, c_idx), cell in table.get_celld().items():
        cell.set_edgecolor("black")
        if r == 0:
            cell.set_facecolor("#dddddd")
            cell.set_text_props(weight="bold", ha="center", va="center")
            cell.set_height(cell.get_height() * 2)
        else:
            final_val = rows[r-1][8]
            if final_val == "PASS":
                face = "#d4edda"
            elif final_val == "FAIL":
                face = "#f8d7da"
            else:
                face = "#f0f0f0"
            cell.set_facecolor(face)
            cell.set_text_props(ha="center", va="center")
            
            remark_text = rows[r-1][9]
            if remark_text and '\n' in remark_text:
                num_lines = remark_text.count('\n') + 1
                cell.set_height(cell.get_height() * (0.8 + 0.2 * num_lines))
    
    out_path = Path(__file__).resolve().parent / "Shutdown_Process_plot.png"
    plt.savefig(out_path, dpi=200, bbox_inches='tight', pad_inches=0.2)
    plt.close(fig)

# -------------------------------------------------------
# HISTORY SAVING
# -------------------------------------------------------
def save_history(results):
    if not results:
        text = "No shutdown event"
    else:
        any_fail = any(c.get("Final") == "FAIL" for c in results)
        if any_fail:
            missing_cmd = any(c.get("shut_cmd_missing", False) for c in results)
            if missing_cmd:
                text = "FAIL - 1840F400 missing"
            else:
                text = "FAIL"
        else:
            ack_times = []
            for c in results:
                ack_time_str = c.get("ACK_Time")
                if ack_time_str and ack_time_str != "N/A":
                    try:
                        ack_times.append(float(ack_time_str.replace("s", "")))
                    except:
                        pass
            if ack_times:
                max_ack = max(ack_times)
                text = f"PASS, Valid Shutdown, Max ACK Time: {max_ack:.3f}s"
            else:
                text = "PASS, Valid Shutdown, Max ACK Time: N/A"
    
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        history = parent / "History"
        if history.exists() and history.is_dir():
            history_file = history / "shutdown.txt"
            with open(history_file, "w", encoding="utf-8") as f:
                f.write(text)
            break

# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    if not Path(filepath).exists():
        sys.exit(1)
    
    progress_cb = progress_by_bytes(filepath, step=PROGRESS_STEP)
    frames = parse_trc(filepath, progress_cb=progress_cb)
    
    shutdown_events = detect_shutdown_events(frames)
    results = analyze_soc_restore(frames, shutdown_events)
    overall = save_results(results, filepath)
    
    save_history(results)
    
    print("PROGRESS 100", flush=True)
    sys.exit(0 if overall == "PASS" else 1)

if __name__ == "__main__":
    main()
