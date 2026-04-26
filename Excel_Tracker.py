import os
import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

# ---------------- CONFIG ----------------
SPREADSHEET_ID = "1nDkL93epR1RQfFvCrzAVeiu5a9TpaU2484sOaVkQAQw"
WORKSHEET_ID = 888141416
SERVICE_ACCOUNT_FILE = "Google_sheet.json"


# ---------------- CONNECT ----------------
def get_sheet():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).get_worksheet_by_id(WORKSHEET_ID)


# ---------------- HEADER ----------------
HEADERS = [
    "TnV Vehicle",
    "DATE",
    "BMS Hardware",
    "BMS Firmware",
    "BMS Configuration",
    "BMS Manifest",
    "BMS Gitsha",
    "Vehicle Drive Mode",
    "Payload (kg)",
    "Vehicle Total Range (km)",
    "Pack Voltage Range (V)",
]

def reset_sheet(sheet):
    sheet.clear()
    end = rowcol_to_a1(1, len(HEADERS))
    sheet.update(f"A1:{end}", [HEADERS])

    sheet.format(
        f"A1:{end}",
        {
            "textFormat": {
                "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                "bold": True
            },
            "backgroundColor": {"red": 0.16, "green": 0.66, "blue": 0.29}
        }
    )

# =====================================================
# 🔥 TEST CASE 1 : TnV Vehicle
# =====================================================
def test_tnv_vehicle():
    return None


# =====================================================
# 🔥 TEST CASE 2 : DATE
# =====================================================
def test_date():
    path = os.path.join(os.getcwd(), "History", "vehicle_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) >= 2:
        line = lines[1]  # 2nd line
        date_time = line.split(",")[0].strip()   # "15-04-2026 23:57:21.7930"
        return date_time.split(" ")[0]           # "15-04-2026"

    return None

# =====================================================
# 🔥 TEST CASE 3 : BMS Hardware
# =====================================================
def test_bms_hw():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("BMS_HW"):
                return line.split(":")[1].strip()
    return None


# =====================================================
# 🔥 TEST CASE 4 : BMS Firmware
# =====================================================
def test_bms_fw():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("BMS_FIRMWARE"):
                return line.split(":")[1].strip()
    return None


# =====================================================
# 🔥 TEST CASE 5 : BMS Configuration
# =====================================================
def test_bms_config():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("BMS_CONFIG_ID"):
                return line.split(":")[1].strip()
    return None


# =====================================================
# 🔥 TEST CASE 6 : BMS Manifest
# =====================================================
def test_bms_manifest():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("BMS_MANIFEST"):
                return line.split(":")[1].strip()
    return None


# =====================================================
# 🔥 TEST CASE 7 : BMS Gitsha
# =====================================================
def test_bms_gitsha():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("BMS_GITSHA"):
                return line.split(":")[1].strip()
    return None


# =====================================================
# 🔥 TEST CASE 8 : Vehicle Drive Mode
# =====================================================
def test_vehicle_mode():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("Vehicle_Drive_Mode"):
                return line.split(":")[1].strip()
    return None


# =====================================================
# 🔥 TEST CASE 9 : Payload
# =====================================================
def test_payload():
    return None


# =====================================================
# 🔥 TEST CASE 10 : Vehicle Total Range
# =====================================================
def test_vehicle_range():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("DISTANCE_COVERED_KM"):
                return line.split(":")[1].strip()
    return None

# =====================================================
# 🔥 TEST CASE 11 : Pack Voltage Range (V)
# =====================================================
def test_pack_voltage_range():
    path = os.path.join(os.getcwd(), "History", "Range+Energy_Capacity.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) < 2:
        return None

    line = lines[1]

    for item in line.split(","):
        if "Pack_Voltage_Range" in item:
            return item.split(":")[1].replace('"', '').strip()

    return None

# ---------------- BUILD ROW ----------------
def build_row():
    row = [
        test_tnv_vehicle(),
        test_date(),
        test_bms_hw(),
        test_bms_fw(),
        test_bms_config(),
        test_bms_manifest(),
        test_bms_gitsha(),
        test_vehicle_mode(),
        test_payload(),
        test_vehicle_range(),
        test_pack_voltage_range(),

    ]

    return [row]


# ---------------- MAIN ----------------
def main():
    sheet = get_sheet()
    reset_sheet(sheet)

    row = build_row()
    end = rowcol_to_a1(2, len(row[0]))
    sheet.update(f"A2:{end}", row)

    print("DONE")


if __name__ == "__main__":
    main()
