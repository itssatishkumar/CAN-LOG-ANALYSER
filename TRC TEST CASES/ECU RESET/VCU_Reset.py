import json
import re
import sys
from datetime import datetime
from pathlib import Path

# =========================================================
# CONFIG
# =========================================================
RESET_CAN_ID = "06F0"

# TRC LINE REGEX
RE_LINE = re.compile(
    r"\s*\d+\)\s+(?P<ts>\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(?P<dir>Rx|Tx)\s+(?P<cid>[0-9A-Fa-f]{4})\s+\d+\s+(?P<data>.+)"
)


def parse_ts(ts: str):
    try:
        return datetime.strptime(ts, "%d-%m-%Y %H:%M:%S.%f")
    except ValueError:
        return None


# =========================================================
# DETECT VCU RESET (0x06F0 FRAME)
# =========================================================
def detect_vcu_resets(trc_path: Path):
    resets = []
    count = 0
    vehicle_state = None  # last seen vehicle state from 0x0602 (last byte)

    with trc_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line_no, line in enumerate(f, start=1):
            match = RE_LINE.match(line)
            if not match:
                continue

            ts_str = match.group("ts")
            can_id = match.group("cid").upper()
            data_tokens = match.group("data").split()

            if not parse_ts(ts_str):
                continue

            # Track vehicle state from 0x0602 frames (last byte)
            if can_id == "0602":
                if data_tokens:
                    try:
                        vehicle_state = int(data_tokens[-1], 16)
                    except ValueError:
                        pass
                continue

            # Count VCU reset only when vehicle state is 0x01 or 0x02
            if can_id == RESET_CAN_ID and vehicle_state in (0x01, 0x02):
                count += 1
                resets.append(
                    {
                        "Index": count,
                        "Timestamp": ts_str,
                        "Line_Number": line_no,
                    }
                )

    return resets


# =========================================================
# MAIN
# =========================================================
def main():
    script_dir = Path(__file__).resolve().parent

    if len(sys.argv) < 2:
        print("Usage: python VCU_Reset.py <input.trc> [output.json]")
        sys.exit(1)

    trc_path = Path(sys.argv[1])
    if not trc_path.exists():
        print(f"TRC file not found: {trc_path}")
        sys.exit(1)

    if len(sys.argv) > 2:
        out_json = Path(sys.argv[2])
        if not out_json.is_absolute():
            out_json = script_dir / out_json
    else:
        out_json = script_dir / "VCU_Reset_Result.json"

    try:
        if out_json.exists():
            out_json.unlink()
    except OSError:
        pass

    resets = detect_vcu_resets(trc_path)
    result = "PASS" if len(resets) == 0 else "FAIL"

    output_data = {
        "Reset_Count": len(resets),
        "Result": result,
    }

    compact_json = json.dumps(output_data, separators=(",", ":"))
    formatted_json = compact_json.replace(',"', ',\n"')
    out_json.write_text(formatted_json, encoding="utf-8")

    print(f"VCU Reset check completed -> {result}")
    print(f"Saved JSON -> {out_json}")


if __name__ == "__main__":
    main()
