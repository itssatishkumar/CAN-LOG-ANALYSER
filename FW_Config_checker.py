import re
import sys
import os
import json
from collections import Counter


# STRICT regex for CAN ID 0402 only (DLC=8)
RE_0402 = re.compile(
    r"\b0402\b\s+8\s+((?:[0-9A-Fa-f]{2}\s+){4})"
)

# CAN ID 0706 (Drive Mode)
RE_0706 = re.compile(
    r"\b0706\b\s+\d+\s+([0-9A-Fa-f]{2})"
)


def parse_firmware_versions(trc_path):
    if not os.path.exists(trc_path):
        return {"error": f"TRC file not found: {trc_path}"}

    # Storage (ordered unique values)
    bms_hw = []
    bms_fw = []
    bms_cfg = []
    bms_git = []
    bms_manifest = []
    stark_fw = []
    stark_cfg = []
    xavier_fw = []

    # Drive mode tracking (ALL samples)
    drive_modes = []

    def add_unique(lst, value):
        if value and value not in lst:
            lst.append(value)

    def decode_drive_mode(byte_val):
        modes = []
        if byte_val & (1 << 0):
            modes.append("NEUTRAL")
        if byte_val & (1 << 1):
            modes.append("ECO")
        if byte_val & (1 << 2):
            modes.append("REVERSE")
        if byte_val & (1 << 3):
            modes.append("THUNDER")
        return "+".join(modes) if modes else "UNKNOWN"

    # Distance
    initial_distance = None
    final_distance = None

    with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:

            # -------- 0402 Distance --------
            m = RE_0402.search(line)
            if m:
                p = m.group(1).split()
                if len(p) == 4:
                    raw = (
                        int(p[0], 16)
                        | (int(p[1], 16) << 8)
                        | (int(p[2], 16) << 16)
                        | (int(p[3], 16) << 24)
                    )
                    dist_km = raw * 0.1

                    if initial_distance is None:
                        initial_distance = dist_km
                    final_distance = dist_km

            # -------- 0706 Drive Mode --------
            m = RE_0706.search(line)
            if m:
                val = int(m.group(1), 16)
                drive_modes.append(decode_drive_mode(val))

            # -------- 07A1 Firmware --------
            if "07A1" in line:
                m = re.match(r".*?\b07A1\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 4:
                        byte0 = int(p[0], 16)
                        ver = f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}"

                        if byte0 == 2:
                            add_unique(bms_fw, ver)
                        elif byte0 == 0:
                            add_unique(stark_fw, ver)
                        elif byte0 == 4:
                            add_unique(xavier_fw, ver)

            # -------- 07A2 Hardware --------
            if "07A2" in line:
                m = re.match(r".*?\b07A2\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 4 and p[0].upper() == "02":
                        add_unique(bms_hw, f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}")

            # -------- 07A3 Config --------
            if "07A3" in line:
                m = re.match(r".*?\b07A3\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()

                    if len(p) >= 4 and p[0].upper() == "02":
                        add_unique(bms_cfg, f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}")

                    if len(p) >= 4 and p[0].upper() == "00":
                        add_unique(stark_cfg, f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}")

            # -------- 07B1 Git --------
            if "07B1" in line:
                m = re.match(r".*?\b07B1\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 5 and p[0].upper() == "02":
                        add_unique(bms_git, "".join(p[1:5]).upper())

            # -------- 012F Manifest --------
            if "012F" in line:
                m = re.match(r".*?\b012F\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 4 and p[0].upper() == "02":
                        add_unique(bms_manifest, f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}")

    distance_covered = round(final_distance - initial_distance, 1) if initial_distance and final_distance else None

    return {
        "BMS_HW": ", ".join(bms_hw),
        "BMS_FIRMWARE": ", ".join(bms_fw),
        "BMS_CONFIG_ID": ", ".join(bms_cfg),
        "BMS_GITSHA": ", ".join(bms_git),
        "BMS_MANIFEST": ", ".join(bms_manifest),
        "STARK_FIRMWARE": ", ".join(stark_fw),
        "STARK_CONFIG": ", ".join(stark_cfg),
        "XAVIER_FIRMWARE": ", ".join(xavier_fw),
        "Start_Odo_KM": round(initial_distance, 1) if initial_distance is not None else None,
        "End_Odo_KM": round(final_distance, 1) if final_distance is not None else None,
        "DISTANCE_COVERED_KM": round(distance_covered, 1) if distance_covered is not None else None,
        "_DRIVE_MODES_RAW": drive_modes
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No TRC file provided"}))
        return

    trc_path = sys.argv[1]
    info = parse_firmware_versions(trc_path)

    gui_info = {k: v for k, v in info.items() if not k.startswith("_")}
    print(json.dumps(gui_info))

    script_dir = os.path.dirname(os.path.abspath(__file__))
    history_dir = os.path.join(script_dir, "History")
    os.makedirs(history_dir, exist_ok=True)

    file_path = os.path.join(history_dir, "Firmware+Config_details.txt")

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            for k, v in gui_info.items():
                f.write(f"{k}: {v}\n")

            drive_modes = info.get("_DRIVE_MODES_RAW", [])
            if drive_modes:
                total = len(drive_modes)
                counts = Counter(drive_modes)
                sorted_modes = sorted(counts.items(), key=lambda x: x[1], reverse=True)

                parts = []
                for mode, cnt in sorted_modes:
                    pct = round((cnt / total) * 100)
                    if pct == 0:
                        continue
                    parts.append(f"{mode} ({pct}%)")

                f.write("\nVehicle_Drive_Mode : " + ", ".join(parts) + "\n")

    except Exception:
        pass


if __name__ == "__main__":
    main()
