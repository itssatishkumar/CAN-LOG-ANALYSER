import sys
import os
import re
import json

TARGET_CAN_ID = 0x0726


def decode_0726(data):
    """
    Decode CAN ID 0x0726 based strictly on DBC
    """
    b0, b1, b2, b3, b4, b5, b6, b7 = data

    # Serial Number (5 bytes, little-endian)
    serial = (
        (b4 << 32)
        | (b3 << 24)
        | (b2 << 16)
        | (b1 << 8)
        | b0
    )

    # OS Version (16-bit, little-endian)
    os_version_raw = (b6 << 8) | b5

    # OS Build Number (8-bit)
    os_build = b7

    # -------- Platform detection logic (UNCHANGED) --------
    if os_version_raw < 256:
        platform = "HEPU"
        os_version_str = str(os_version_raw)
        confidence = "HIGH"
    else:
        major = b6
        minor = b5
        os_version_str = f"{major}.{minor}"

        if b4 == 0xE1:
            platform = "GTAKE"
            confidence = "HIGH"
        elif b4 == 0x58:
            platform = "PEGASUS"
            confidence = "HIGH"
        else:
            platform = "UNKNOWN"
            confidence = "MEDIUM"
    # ------------------------------------------------------

    return {
        "platform": platform,
        "confidence": confidence,
        "serial_hex": f"0x{serial:010X}",  # keep only HEX
        "os_version": os_version_str,
        "os_build": os_build,
    }


def extract_can_id(line):
    """
    Extract CAN ID safely from PCAN or Vector TRC logs
    """
    parts = line.strip().split()

    for token in parts:
        if re.fullmatch(r"[0-9A-Fa-f]{3,8}", token):
            try:
                return int(token, 16)
            except ValueError:
                pass
    return None


def parse_trc(file_path):
    ecus = {}

    with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            if line.startswith(";") or ")" not in line:
                continue

            can_id = extract_can_id(line)
            if can_id != TARGET_CAN_ID:
                continue

            bytes_found = re.findall(r"\b[0-9A-Fa-f]{2}\b", line)
            if len(bytes_found) < 8:
                continue

            data = [int(x, 16) for x in bytes_found[-8:]]
            decoded = decode_0726(data)

            # Use Serial Number (HEX) as unique ECU key
            key = decoded["serial_hex"]
            if key not in ecus:
                ecus[key] = decoded

    return ecus


def main():
    # GUI-friendly CLI interface (matches FW_Config_checker.py style)
    if len(sys.argv) < 2:
        print(json.dumps({
            "platform": "N/A",
            "serial": "N/A",
            "os_version": "N/A",
            "os_build": "N/A",
            "error": "No TRC file provided",
        }))
        return

    trc_file = sys.argv[1]
    if not os.path.exists(trc_file):
        print(json.dumps({
            "platform": "N/A",
            "serial": "N/A",
            "os_version": "N/A",
            "os_build": "N/A",
            "error": f"TRC file not found: {trc_file}",
        }))
        return

    ecus = parse_trc(trc_file)

    # Output ONLY JSON (first ECU found, or N/A fields)
    if not ecus:
        result = {
            "platform": "N/A",
            "serial": "N/A",
            "os_version": "N/A",
            "os_build": "N/A",
        }
    else:
        ecu = next(iter(ecus.values()))
        result = {
            "platform": ecu.get("platform", "N/A"),
            "serial": ecu.get("serial_hex", "N/A"),
            "os_version": ecu.get("os_version", "N/A"),
            "os_build": ecu.get("os_build", "N/A"),
        }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
