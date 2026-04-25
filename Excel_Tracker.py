import os
import json
import gspread
from google.oauth2.service_account import Credentials

# ---------------- GOOGLE SHEET CONFIG ----------------
SPREADSHEET_ID = "1nDkL93epR1RQfFvCrzAVeiu5a9TpaU2484sOaVkQAQw"
WORKSHEET_ID = 888141416
SERVICE_ACCOUNT_FILE = "Google_sheet.json"

DEFAULT_TESTS_FOLDER = "TRC TEST CASES"


# ---------------- CONNECT SHEET ----------------
def get_sheet():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).get_worksheet_by_id(WORKSHEET_ID)


# ---------------- RESET + HEADER ----------------
def reset_sheet_with_header(sheet):
    headers = [
        "TnV Vehicle",
        "DATE",
        "Firmware",
        "Configuration",
        "Manifest",
        "GITSHA",
        "MODE",
        "Payload (kg)",
        "Vehicle Total Range (km)",
        "Range Below SoC 1%",
        "Consumed Energy (From Battery Wh)",
        "Regen Energy (Wh)"
    ]

    sheet.clear()
    sheet.update("A1:L1", [headers])

    sheet.format(
        "A1:L1",
        {
            "textFormat": {
                "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                "fontFamily": "Calibri",
                "bold": True
            },
            "backgroundColor": {"red": 0.16, "green": 0.66, "blue": 0.29},
            "horizontalAlignment": "CENTER"
        }
    )

# =====================================================
# 🔥 TEST CASE PLACEHOLDERS (FILL LOGIC LATER)
# =====================================================

def test_soc_behavior(tests_folder):
    # TODO: extract SoC behavior data
    return None


def test_shutdown_process(tests_folder):
    # TODO
    return None


def test_precharge_process(tests_folder):
    # TODO
    return None


def test_bms_state_transition(tests_folder):
    # TODO
    return None


def test_cell_temp_imbalance(tests_folder):
    # TODO
    return None


def test_bms_pcb_temp(tests_folder):
    # TODO
    return None


def test_any_bms_error(tests_folder):
    # TODO
    return None


def test_flag_full_charge_disable(tests_folder):
    # TODO
    return None


def test_dcli_dclo_map(tests_folder):
    # TODO
    return None


def test_equivalent_cycle_count(tests_folder):
    # TODO
    return None


def test_bms_balancing(tests_folder):
    # TODO
    return None


def test_primary_secondary_latch(tests_folder):
    # TODO
    return None


def test_mcu_obc_error(tests_folder):
    # TODO
    return None


def test_aux_charge_state_change(tests_folder):
    # TODO
    return None


def test_soc_voltage_summary(tests_folder):
    # TODO
    return None


def test_capacity_check(tests_folder):
    # TODO
    return None


def test_bms_current_ready_mode(tests_folder):
    # TODO
    return None


def test_drive_charge_current(tests_folder):
    # TODO
    return None


# ---------------- BUILD MAIN ROW ----------------
def build_main_row(meta):
    return [[
        meta.get("VEHICLE NAME", "N/A"),
        meta.get("DATE", "N/A"),
        meta.get("BMS FIRMWARE", "N/A"),
        meta.get("BMS CONFIG ID", "N/A"),
        meta.get("BMS MANIFEST", "N/A"),
        meta.get("BMS GITSHA", "N/A"),

        # 👇 THESE WILL USE TEST FUNCTIONS LATER
        "TODO",  # MODE
        "TODO",  # Payload
        "TODO",  # Total Range
        "TODO",  # Range below SoC
        "TODO",  # Consumed Energy
        "TODO"   # Regen Energy
    ]]


# ---------------- MAIN FUNCTION ----------------
def update_full_sheet(meta, tests_folder=DEFAULT_TESTS_FOLDER):
    sheet = get_sheet()

    # RESET SHEET
    reset_sheet_with_header(sheet)

    # WRITE DATA
    sheet.update("A2:L2", build_main_row(meta))

    print("✅ Sheet ready (test slots created)")


# ---------------- TEST RUN ----------------
if __name__ == "__main__":
    meta = {
        "VEHICLE NAME": "Test Vehicle",
        "DATE": "2026-01-01",
        "BMS FIRMWARE": "01.00.02",
        "BMS CONFIG ID": "0A.01.2E",
        "BMS MANIFEST": "XYZ123",
        "BMS GITSHA": "abc456"
    }

    update_full_sheet(meta)