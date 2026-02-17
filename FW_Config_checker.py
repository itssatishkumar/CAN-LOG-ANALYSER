import re
import sys
import os
import json

# -------------------- REGEX --------------------

# 0402 → ODO_TRIP (Little Endian, scale 0.1)
RE_0402 = re.compile(
    r"\b0402\b\s+8\s+((?:[0-9A-Fa-f]{2}\s+){4})"
)

# 0409 → Odo (Motorola, scale 0.01)
RE_0409 = re.compile(
    r"\b0409\b\s+8\s+((?:[0-9A-Fa-f]{2}\s+){8})"
)


def parse_firmware_versions(trc_path):
    if not os.path.exists(trc_path):
        return {"error": f"TRC file not found: {trc_path}"}

    # -------------------- Storage --------------------
    bms_hw = bms_fw = bms_cfg = bms_git = bms_manifest = None
    stark_fw = stark_cfg = xavier_fw = None

    # Distance
    initial_distance = None
    final_distance = None
    odo_source = None

    found_0402 = False
    found_0409 = False

    def all_found():
        return all([
            bms_hw, bms_fw, bms_cfg, bms_git, bms_manifest,
            stark_fw, stark_cfg, xavier_fw
        ])

    with open(trc_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:

            # =====================================================
            # PRIORITY 1 → CAN ID 0402 (Little Endian, scale 0.1)
            # =====================================================
            if not found_0402:
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

                        found_0402 = True
                        odo_source = "0402"

                        if initial_distance is None:
                            initial_distance = dist_km
                        final_distance = dist_km
                    continue

            # =====================================================
            # PRIORITY 2 → CAN ID 0409 (Motorola, scale 0.01)
            # =====================================================
            if not found_0402:
                m2 = RE_0409.search(line)
                if m2:
                    p = m2.group(1).split()
                    if len(p) >= 4:
                        raw = (
                            (int(p[0], 16) << 24)
                            | (int(p[1], 16) << 16)
                            | (int(p[2], 16) << 8)
                            | int(p[3], 16)
                        )
                        dist_km = raw * 0.01

                        found_0409 = True
                        odo_source = "0409"

                        if initial_distance is None:
                            initial_distance = dist_km
                        final_distance = dist_km

            # -------------------- 07A1: Firmware Versions --------------------
            if "07A1" in line:
                m = re.match(r".*?\b07A1\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 4:
                        byte0 = int(p[0], 16)
                        ver = f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}"

                        if byte0 == 2 and bms_fw is None:
                            bms_fw = ver
                        elif byte0 == 0 and stark_fw is None:
                            stark_fw = ver
                        elif byte0 == 4 and xavier_fw is None:
                            xavier_fw = ver

            # -------------------- 07A2: BMS Hardware --------------------
            if bms_hw is None and "07A2" in line:
                m = re.match(r".*?\b07A2\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 4 and p[0].upper() == "02":
                        bms_hw = f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}"

            # -------------------- 07A3: CONFIG IDs --------------------
            if "07A3" in line:
                m = re.match(r".*?\b07A3\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()

                    if bms_cfg is None and len(p) >= 4 and p[0].upper() == "02":
                        bms_cfg = f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}"

                    if stark_cfg is None and len(p) >= 4 and p[0].upper() == "00":
                        stark_cfg = f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}"

            # -------------------- 07B1: BMS GitSha --------------------
            if bms_git is None and "07B1" in line:
                m = re.match(r".*?\b07B1\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 5 and p[0].upper() == "02":
                        bms_git = "".join(p[1:5]).upper()

            # -------------------- 012F: BMS Manifest --------------------
            if bms_manifest is None and "012F" in line:
                m = re.match(r".*?\b012F\b\s+\d+\s+((?:[0-9A-Fa-f]{2}\s+){1,8})", line)
                if m:
                    p = m.group(1).split()
                    if len(p) >= 4 and p[0].upper() == "02":
                        bms_manifest = f"{int(p[1],16):02X}.{int(p[2],16):02X}.{int(p[3],16):02X}"

            if all_found():
                pass

    # -------------------- Final Distance Calculation --------------------
    if initial_distance is not None and final_distance is not None:
        delta = final_distance - initial_distance
        distance_covered = round(max(delta, 0), 2)  # prevent negative
    else:
        distance_covered = None
        odo_source = None

    return {
        "BMS_HW": bms_hw,
        "BMS_FIRMWARE": bms_fw,
        "BMS_CONFIG_ID": bms_cfg,
        "BMS_GITSHA": bms_git,
        "BMS_MANIFEST": bms_manifest,
        "STARK_FIRMWARE": stark_fw,
        "STARK_CONFIG": stark_cfg,
        "XAVIER_FIRMWARE": xavier_fw,

        "DIST_INITIAL_KM": initial_distance,
        "DIST_FINAL_KM": final_distance,
        "DISTANCE_COVERED_KM": distance_covered,
        "ODO_SOURCE": odo_source
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No TRC file provided"}))
        return

    trc_path = sys.argv[1]
    info = parse_firmware_versions(trc_path)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
