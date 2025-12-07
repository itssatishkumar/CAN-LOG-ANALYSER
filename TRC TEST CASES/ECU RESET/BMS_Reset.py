import json
import re
import sys
from datetime import datetime
from pathlib import Path

# =========================================================
# TRC LINE REGEX
# =========================================================
RE_LINE = re.compile(
    r"\s*\d+\)\s+"
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(Rx|Tx)\s+([0-9A-Fa-f]{4,8})\s+\d+\s+(.+)"
)


def parse_ts(ts_str: str):
    try:
        return datetime.strptime(ts_str, "%d-%m-%Y %H:%M:%S.%f")
    except ValueError:
        return None


def extract_mcu_counter(data_hex: str):
    """MCU counter = bytes 2 and 3 (DBC: 16|16@1+)."""
    try:
        b = [int(x, 16) for x in data_hex.split()]
        return (b[2] << 8) | b[3]
    except Exception:
        return None


# =========================================================
# STATES
# =========================================================
NORMAL = 0
ROLLOVER_ACTIVE = 1
AFTER_1840F400_WAIT_DROP = 2
AFTER_1840F400_INCREASE_ONLY = 3


# =========================================================
# MAIN DETECTION LOGIC
# =========================================================
def detect_resets(trc_path: Path):
    previous_mcu = None
    previous_ts = None
    state = NORMAL
    reset_count = 0
    allow_one_drop = False  # For 0x1840F00
    wait_for_drop = False  # For 0x1840F400 (kept for parity; not directly used)

    with trc_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = RE_LINE.match(line)
            if not m:
                continue

            ts_str, direction, can_id, data = m.groups()
            ts = parse_ts(ts_str)
            if not ts:
                continue

            can_id = can_id.upper()

            if can_id == "1840F00":
                allow_one_drop = True
                continue

            if can_id == "1840F400":
                state = AFTER_1840F400_WAIT_DROP
                continue

            if can_id not in ("012B", "12B", "012B", "12B", "299"):
                continue

            mcu = extract_mcu_counter(data)
            if mcu is None:
                continue

            if previous_mcu is None:
                previous_mcu = mcu
                previous_ts = ts
                continue

            delta = (ts - previous_ts).total_seconds()
            if delta > 3:
                previous_mcu = mcu
                previous_ts = ts
                allow_one_drop = False
                continue

            if state == AFTER_1840F400_WAIT_DROP:
                if mcu < previous_mcu:
                    state = AFTER_1840F400_INCREASE_ONLY
                previous_mcu = mcu
                previous_ts = ts
                allow_one_drop = False
                continue

            if state == AFTER_1840F400_INCREASE_ONLY:
                if mcu < previous_mcu:
                    if allow_one_drop:
                        allow_one_drop = False
                    else:
                        reset_count += 1
                if mcu > 2000:
                    state = NORMAL
                previous_mcu = mcu
                previous_ts = ts
                continue

            if state == NORMAL:
                if mcu >= previous_mcu:
                    previous_mcu = mcu
                    previous_ts = ts
                    allow_one_drop = False
                    continue
                else:
                    if previous_mcu >= 65000:
                        state = ROLLOVER_ACTIVE
                    elif allow_one_drop:
                        allow_one_drop = False
                    else:
                        reset_count += 1
                previous_mcu = mcu
                previous_ts = ts
                continue

            if state == ROLLOVER_ACTIVE:
                if mcu < previous_mcu:
                    if allow_one_drop:
                        allow_one_drop = False
                    else:
                        reset_count += 1
                if mcu > 2000:
                    state = NORMAL
                previous_mcu = mcu
                previous_ts = ts
                continue

    return reset_count


# =========================================================
# MAIN EXECUTION
# =========================================================
def main():
    script_dir = Path(__file__).resolve().parent

    if len(sys.argv) < 2:
        print("Usage: python BMS_Reset.py <log.trc> [output.json]")
        sys.exit(1)

    trc_path = Path(sys.argv[1])
    if not trc_path.exists():
        print(f"TRC file not found: {trc_path}")
        sys.exit(1)

    passed_output = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if passed_output:
        json_path = script_dir / Path(sys.argv[2]).name
    else:
        json_path = script_dir / "BMS_Reset_Result.json"

    try:
        # Delete any old copy at the target location
        if json_path.exists():
            json_path.unlink()
        # If caller passed a different absolute path previously, clean that too
        if passed_output and passed_output.is_absolute() and passed_output.exists():
            try:
                passed_output.unlink()
            except OSError:
                pass
    except OSError:
        pass

    reset_count = detect_resets(trc_path)
    result = "PASS" if reset_count == 0 else "FAIL"

    output = {
        "Reset_Count": reset_count,
        "Result": result,
    }

    json_path.write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")

    print(f"BMS Reset Detection Completed -> {result}")
    print(f"Reset Count: {reset_count}")
    print(f"Output JSON: {json_path}")


if __name__ == "__main__":
    main()
