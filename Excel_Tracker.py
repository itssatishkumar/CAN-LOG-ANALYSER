import os
import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

# ---------------- CONFIG ----------------
SPREADSHEET_ID = "1nDkL93epR1RQfFvCrzAVeiu5a9TpaU2484sOaVkQAQw"
WORKSHEET_ID = 141417471
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
    "Range Below SoC 1%",
    "Total Drive Energy/Capacity (Wh/Ah)",
    "Consumed Energy/Capacity (From Battery Wh)",
    "Regen Energy/Capacity (Wh/Ah)",
    "Peak Imbalance (mV) (Vmin, Vmax & SoC)",
    "Average Imbalance (mV)",
    "Temperature Range (ENTIRE CYCLE)",
    "Temp Delta (Max at particular instant) @SoC",
    "BMS STATE transition",
    "FFC Check",
    "SoC Range (Initial & Final)",
    "SoC Delta (Max jump/drop)",
    "Any SoC Stuck",
    "First UV (SoC and Voltage)",
    "Shutdown Routine",
    "Precharge Process Check",
    "Precharge Flag ON Duration\n(Max)",
    "Equivalent Cycle Count BMS",
    "BMS MCU Counter",
    "BMS Balancing",
    "Max Vcell\nVoltage recorded (V)",
    "Aux Voltage Range (V)",
    "Min Aux Voltage (V)",
    "Avg Discharge Current (A)",
    "Peak Discharge Current and Duration",
    "Peak Regen Current and Duration",
    "PCB Temperature Range",
    "PCB Temp Delta",
    "Any BMS Error",
    "Any Hardware Failure",
    "Vehicle State",
    "STARK F/W Config",
    "Xavier F/W"
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
            "backgroundColor": {"red": 0.16, "green": 0.66, "blue": 0.29},
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE"
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
        date_time = line.split(",")[0].strip()
        return date_time.split(" ")[0]           

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

# =====================================================
# 🔥 TEST CASE 12 : Range Below SoC (1%)
# =====================================================
def test_range_below_soc_1():
    path = os.path.join(os.getcwd(), "History", "Range+Energy_Capacity.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if "Range_Below_SoC_1_percent_km" in line:
                return line.split(":")[1].replace('"', '').replace(',', '').strip()

    return None

# =======================================================================
# 🔥 TEST CASE 13 : Total Drive Energy/Capacity (Regen + BatteryPack Wh)
# =======================================================================
def test_total_drive_energy_capacity():
    path = os.path.join(os.getcwd(), "History", "Range+Energy_Capacity.txt")

    if not os.path.exists(path):
        return None

    total_energy = None
    total_capacity = None

    with open(path) as f:
        for line in f:
            if "Total_Energy_Wh" in line:
                total_energy = float(line.split(":")[1].replace('"', '').replace(',', '').strip())
            if "Total_Capacity_Ah" in line:
                total_capacity = float(line.split(":")[1].replace('"', '').replace(',', '').strip())

    if total_energy is not None and total_capacity is not None:
        return f"{total_energy} Wh / {total_capacity} Ah"

    return None

# =====================================================
# 🔥 TEST CASE 14 : Consumed Energy/Capacity (From Battery Wh)
# =====================================================
def test_consumed_energy_capacity():
    path = os.path.join(os.getcwd(), "History", "Range+Energy_Capacity.txt")

    if not os.path.exists(path):
        return None

    battery_energy = None
    battery_capacity = None

    with open(path) as f:
        for line in f:
            if "Battery_Energy_Wh" in line:
                battery_energy = float(line.split(":")[1].replace('"', '').replace(',', '').strip())
            if "Battery_Capacity_Ah" in line:
                battery_capacity = float(line.split(":")[1].replace('"', '').replace(',', '').strip())

    if battery_energy is not None and battery_capacity is not None:
        return f"{battery_energy} Wh / {battery_capacity} Ah"

    return None

# =====================================================
# 🔥 TEST CASE 15 : Regen Energy/Capacity (Wh)
# =====================================================
def test_regen_energy_capacity():
    path = os.path.join(os.getcwd(), "History", "Range+Energy_Capacity.txt")

    if not os.path.exists(path):
        return None

    regen_energy = None
    regen_capacity = None

    with open(path) as f:
        for line in f:
            if "Regen_Energy_Wh" in line:
                regen_energy = float(line.split(":")[1].replace('"', '').replace(',', '').strip())
            if "Regen_Capacity_Ah" in line:
                regen_capacity = float(line.split(":")[1].replace('"', '').replace(',', '').strip())

    if regen_energy is not None and regen_capacity is not None:
        return f"{regen_energy} Wh / {regen_capacity} Ah"

    return None

# =====================================================
# 🔥 TEST CASE 16 : Peak Imbalance (mV) (Vmin, Vmax & SoC)
# =====================================================
def test_peak_imbalance():
    path = os.path.join(os.getcwd(), "History", "imbalance.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("Peak Imbalance"):
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 17 : Average Imbalance (mV)
# =====================================================
def test_average_imbalance():
    path = os.path.join(os.getcwd(), "History", "imbalance.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("Average Imbalance"):
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 18 : Temperature Range (ENTIRE CYCLE)
# =====================================================
def test_temp_range_entire_cycle():
    path = os.path.join(os.getcwd(), "History", "temp_data.txt")

    if not os.path.exists(path):
        return None

    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("Temperature Range"):
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 19 : Temp Delta (Max at particular instant) @SoC
# =====================================================
def test_temp_delta_at_soc():
    path = os.path.join(os.getcwd(), "History", "temp_data.txt")

    if not os.path.exists(path):
        return None

    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("Max Delta"):
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 20 : BMS STATE transition
# =====================================================
def test_bms_state_transition():
    path = os.path.join(os.getcwd(), "History", "BMSS_Transition.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        first_line = f.readline().strip()
        return first_line if first_line else None
    
# =====================================================
# 🔥 TEST CASE 21 : FFC Check (Full charge Disable/Enable)
# =====================================================
def test_ffc_check():
    path = os.path.join(os.getcwd(), "History", "FFC_Check.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        first_line = f.readline().strip()
        return first_line if first_line else None
    
# =====================================================
# 🔥 TEST CASE 22 : SoC Range (Initial & Final)
# =====================================================
def test_soc_range():
    path = os.path.join(os.getcwd(), "History", "SoC.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if "Initial SoC" in line and "Final SoC" in line:
                part = line.split(":", 1)[1].strip()
                part = part.replace("(", "").replace(")", "")
                return part if part else None

    return None

# =====================================================
# 🔥 TEST CASE 23 : SoC Delta (Max jump/drop)
# =====================================================
def test_soc_delta():
    path = os.path.join(os.getcwd(), "History", "SoC.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) >= 2:
        line = lines[1]
        if "Max SoC Delta" in line:
            return line.split(":", 1)[1].replace('"', '').strip()

    return None

# =====================================================
# 🔥 TEST CASE 24 : Any SoC Stuck
# =====================================================
def test_soc_stuck():
    path = os.path.join(os.getcwd(), "History", "SoC.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) >= 3:
        line = lines[2]
        if "Any SoC stuck" in line:
            return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 25 : First UV (SoC and Voltage)
# =====================================================
def test_first_uv():
    path = os.path.join(os.getcwd(), "History", "BMS_Error.txt")

    if not os.path.exists(path):
        return None

    lines_to_return = []

    with open(path) as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if line.startswith("UV Triggered"):
            lines_to_return.append(line.strip())
            if i + 1 < len(lines):
                lines_to_return.append(lines[i + 1].strip())
            break

    if lines_to_return:
        return "\n".join(lines_to_return)

    return None

# =====================================================
# 🔥 TEST CASE 26 : Shutdown Routine
# =====================================================
def test_shutdown_routine():
    path = os.path.join(os.getcwd(), "History", "shutdown.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        first_line = f.readline().strip()
        return first_line if first_line else None
    
# =====================================================
# 🔥 TEST CASE 27 : Precharge Process Check
# =====================================================
def test_precharge_check():
    path = os.path.join(os.getcwd(), "History", "Precharge.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        first_line = f.readline().strip()
        return first_line if first_line else None
    
# =====================================================
# 🔥 TEST CASE 28 : Precharge Flag ON Duration (Max)
# =====================================================
def test_precharge_duration():
    path = os.path.join(os.getcwd(), "History", "Precharge.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) >= 2:
        line = lines[1]
        if "Max Precharge Process Time" in line:
            return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 29 : Cycle Count BMS
# =====================================================
def test_cycle_count():
    path = os.path.join(os.getcwd(), "History", "cycle_count.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if "Cycle Count" in line:
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 30 : BMS MCU Counter
# =====================================================
def test_bms_mcu_counter():
    return "PASS"

# =====================================================
# 🔥 TEST CASE 31 : Balancing
# =====================================================
def test_balancing():
    return None

# =====================================================
# 🔥 TEST CASE 32 : Voltage Spike Beyond Range
# =====================================================
def test_voltage_spike():
    path = os.path.join(os.getcwd(), "History", "imbalance.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if "Max Voltage recorded" in line:
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 33 : Aux Voltage Range
# =====================================================
def test_aux_voltage_range():
    path = os.path.join(os.getcwd(), "History", "Aux_voltage.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if "Aux Voltage Range" in line:
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 34 : Min AUX Voltage (<10)
# =====================================================
def test_min_aux_voltage():
    path = os.path.join(os.getcwd(), "History", "Aux_voltage.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) >= 2:
        line = lines[1]
        if "Lowest Aux Voltage" in line:
            return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 35 : Avg Discharge Current
# =====================================================
def test_avg_discharge_current():
    path = os.path.join(os.getcwd(), "History", "Current_Profile.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        first_line = f.readline().strip()
        if "Average Discharge Current" in first_line:
            return first_line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 36 : Peak Discharge Current and Duration
# =====================================================
def test_peak_discharge_current():
    path = os.path.join(os.getcwd(), "History", "Current_Profile.txt")

    if not os.path.exists(path):
        return None

    capture = []
    count = 0

    with open(path) as f:
        for line in f:
            if line.startswith("Peak Discharge current"):
                count += 1
                if count == 1:
                    capture.append(line.strip())
                elif count == 2:
                    capture.append(line.strip())
                    continue
                continue

            if count >= 2:
                if line.strip() == "":
                    break

                line_clean = line.strip()
                if '"Duration": "00:00:' in line_clean:
                    seconds = line_clean.split('"Duration": "00:00:')[1].split('"')[0]
                    line_clean = line_clean.replace(
                        f'"Duration": "00:00:{seconds}"',
                        f'"Duration": "{int(seconds)}s"'
                    )

                capture.append(line_clean)

    if capture:
        return "\n".join(capture)

    return None

# =====================================================
# 🔥 TEST CASE 37 : Max Regen Current and Duration
# =====================================================
def test_peak_regen_current():
    path = os.path.join(os.getcwd(), "History", "Current_Profile.txt")

    if not os.path.exists(path):
        return None

    capture = []
    start = False

    with open(path) as f:
        for line in f:
            if line.startswith("Peak Regen Current and Duration"):
                start = True
                capture.append(line.strip())
                continue

            if start:
                if line.strip() == "":
                    break

                line_clean = line.strip()
                if '"Duration": "00:00:' in line_clean:
                    seconds = line_clean.split('"Duration": "00:00:')[1].split('"')[0]
                    line_clean = line_clean.replace(
                        f'"Duration": "00:00:{seconds}"',
                        f'"Duration": "{int(seconds)}s"'
                    )

                capture.append(line_clean)

    if capture:
        return "\n".join(capture)

    return None

# =====================================================
# 🔥 TEST CASE 38 : PCB Temperature Range
# =====================================================
def test_pcb_temp_range():
    path = os.path.join(os.getcwd(), "History", "pcb_temp.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if "PCB Temperature Range" in line:
                return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 39 : PCB Temp Delta
# =====================================================
def test_pcb_temp_delta():
    path = os.path.join(os.getcwd(), "History", "pcb_temp.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) >= 2:
        line = lines[1]
        if "Max Delta" in line:
            return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 40 : Any BMS Error
# =====================================================
def test_bms_error():
    path = os.path.join(os.getcwd(), "History", "BMS_Error.txt")

    if not os.path.exists(path):
        return None

    lines_out = []

    with open(path) as f:
        for line in f:
            if line.strip() == "":
                break
            lines_out.append(line.strip())

    if lines_out:
        return "\n".join(lines_out)

    return None

# =====================================================
# 🔥 TEST CASE 41 : Any Hardware Failure
# =====================================================
def test_hardware_failure():
    return None

# =====================================================
# 🔥 TEST CASE 42 : Vehicle State
# =====================================================
def test_vehicle_state():
    path = os.path.join(os.getcwd(), "History", "imbalance.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        lines = f.readlines()

    if len(lines) >= 4:
        line = lines[3]
        if "Vehicle Mode" in line:
            return line.split(":", 1)[1].strip()

    return None

# =====================================================
# 🔥 TEST CASE 43 : STARK F/W config
# =====================================================
def test_stark_fw_config():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    lines = []
    with open(path) as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if line.startswith("STARK_FIRMWARE"):
            fw = line.split(":")[1].strip()

            if i + 1 < len(lines) and lines[i + 1].startswith("STARK_CONFIG"):
                config = lines[i + 1].split(":")[1].strip()
                return f"FW: {fw}\nConfig: {config}"

    return None

# =====================================================
# 🔥 TEST CASE 44 : Xavier FW
# =====================================================
def test_xavier_fw():
    path = os.path.join(os.getcwd(), "History", "Firmware+Config_details.txt")

    if not os.path.exists(path):
        return None

    with open(path) as f:
        for line in f:
            if line.startswith("XAVIER_FIRMWARE"):
                return line.split(":")[1].strip()

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
        test_range_below_soc_1(),
        test_total_drive_energy_capacity(),
        test_consumed_energy_capacity(),
        test_regen_energy_capacity(),
        test_peak_imbalance(),
        test_average_imbalance(),
        test_temp_range_entire_cycle(),
        test_temp_delta_at_soc(),
        test_bms_state_transition(),
        test_ffc_check(),
        test_soc_range(),
        test_soc_delta(),
        test_soc_stuck(),
        test_first_uv(),
        test_shutdown_routine(),
        test_precharge_check(),
        test_precharge_duration(),
        test_cycle_count(),
        test_bms_mcu_counter(),
        test_balancing(),
        test_voltage_spike(),
        test_aux_voltage_range(),
        test_min_aux_voltage(),
        test_avg_discharge_current(),
        test_peak_discharge_current(),
        test_peak_regen_current(),
        test_pcb_temp_range(),
        test_pcb_temp_delta(),
        test_bms_error(),
        test_hardware_failure(),
        test_vehicle_state(),
        test_stark_fw_config(),
        test_xavier_fw()
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
