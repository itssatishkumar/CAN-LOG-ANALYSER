import sys
import os
import subprocess
import json
import csv
import math
import time
import re
import ast
import urllib.request
import importlib.util
import requests
import socket
import threading
import shutil


def ensure_package_installed(import_name: str, package_name: str):
    if importlib.util.find_spec(import_name):
        return
    print(f"Installing missing package: {package_name}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
    except Exception as e:
        raise RuntimeError(
            f"Required package '{package_name}' is missing and auto-install failed. "
            f"Please install it manually with: {sys.executable} -m pip install {package_name}"
        ) from e


ensure_package_installed("pyautogui", "pyautogui")
ensure_package_installed("pygetwindow", "PyGetWindow")
import pyautogui
import pygetwindow as gw
from typing import Dict, Optional, Set, List
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QComboBox,
    QFileDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QMessageBox,
    QGridLayout, QTableWidget, QTableWidgetItem, QFrame, QDialog,
    QTextEdit, QHeaderView, QAbstractItemView, QColorDialog, QScrollArea,
    QProgressBar, QGroupBox, QListWidget, QListWidgetItem
)
from PySide6.QtGui import QFont, QPixmap, QColor, QLinearGradient, QBrush, QPalette
from PySide6.QtCore import Qt, QThread, Signal, QProcess, QTimer, QPropertyAnimation, QEasingCurve, Slot, QMetaObject, Q_ARG

from updater import check_for_update
# Inlined KeyboardAutomation to remove external dependency (keeps LAUNCHER self-contained)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05  # 50ms between key presses


class KeyboardAutomation:
    """Real keyboard-based automation for CAN Log Analyzer (inlined)
    This replaces the external `keyboard_automation.py` to avoid missing-import
    diagnostics and keep all automation inside `LAUNCHER.py`.
    """
    def __init__(self, window_title: str = "CAN LOG ANALYSER", verbose: bool = True):
        self.window_title = window_title
        self.verbose = verbose
        self.window = None
        self.find_window()

    def log(self, message: str):
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")

    def find_window(self) -> bool:
        try:
            windows = gw.getWindowsWithTitle(self.window_title)
            if not windows:
                self.log(f"❌ Window '{self.window_title}' not found!")
                return False
            self.window = windows[0]
            self.log(f"✅ Found window: {self.window.title}")
            self.window.activate()
            time.sleep(0.3)
            self.log(f"✅ Window brought to foreground")
            return True
        except Exception as e:
            self.log(f"❌ Error finding window: {e}")
            return False

    def ensure_window_focused(self) -> bool:
        if not self.window:
            return self.find_window()
        try:
            if self.window.isMinimized:
                self.window.maximize()
            self.window.activate()
            time.sleep(0.2)
            return True
        except Exception as e:
            self.log(f"❌ Error focusing window: {e}")
            return False

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1) -> bool:
        try:
            for _ in range(presses):
                pyautogui.press(key)
                time.sleep(interval)
            self.log(f"⌨️ Pressed: {key}")
            return True
        except Exception as e:
            self.log(f"❌ Error pressing key: {e}")
            return False

    def type_text(self, text: str, interval: float = 0.05) -> bool:
        try:
            pyautogui.typewrite(text, interval=interval)
            self.log(f"⌨️ Typed: {text}")
            return True
        except Exception as e:
            self.log(f"❌ Error typing text: {e}")
            return False

    def hotkey(self, *keys) -> bool:
        try:
            pyautogui.hotkey(*keys)
            key_combo = '+'.join(keys)
            self.log(f"⌨️ Hotkey: {key_combo}")
            time.sleep(0.2)
            return True
        except Exception as e:
            self.log(f"❌ Error with hotkey: {e}")
            return False

    def click_make_organised(self) -> bool:
        self.log(f"\n{'='*60}")
        self.log(f"🎯 Activating: 'MAKE YOUR LOGS ORGANISED'")
        self.log(f"{'='*60}")
        if not self.ensure_window_focused():
            return False
        time.sleep(0.3)
        if self.hotkey('alt', 'm'):
            self.log(f"✅ Button activated via Alt+M shortcut")
            time.sleep(1.0)
            return True
        return False

    def click_browse_file(self) -> bool:
        self.log(f"\n{'='*60}")
        self.log(f"🎯 Activating: 'Browse File'")
        self.log(f"{'='*60}")
        if not self.ensure_window_focused():
            return False
        time.sleep(0.3)
        if self.hotkey('alt', 'b'):
            self.log(f"✅ Button activated via Alt+B shortcut")
            time.sleep(1.5)
            return True
        return False

    def click_run_all_tests(self) -> bool:
        self.log(f"\n{'='*60}")
        self.log(f"🎯 Activating: 'RUN ALL TEST CASES'")
        self.log(f"{'='*60}")
        if not self.ensure_window_focused():
            return False
        time.sleep(0.3)
        if self.hotkey('alt', 'r'):
            self.log(f"✅ Button activated via Alt+R shortcut")
            time.sleep(1.0)
            return True
        return False

    def click_create_excel_tracker(self) -> bool:
        self.log(f"\n{'='*60}")
        self.log(f"🎯 Activating: 'CREATE EXCEL TRACKER'")
        self.log(f"{'='*60}")
        if not self.ensure_window_focused():
            return False
        time.sleep(0.3)
        if self.hotkey('alt', 'c'):
            self.log(f"✅ Button activated via Alt+C shortcut")
            time.sleep(1.5)
            return True
        return False

    def select_file_in_dialog(self, file_path: str) -> bool:
        self.log(f"\n{'='*60}")
        self.log(f"📂 Selecting file in dialog")
        self.log(f"{'='*60}")
        try:
            time.sleep(0.5)
            self.log(f"⌨️ Clearing filename field...")
            self.hotkey('ctrl', 'a')
            time.sleep(0.1)
            self.log(f"⌨️ Typing file path: {file_path}")
            pyautogui.typewrite(file_path, interval=0.01)
            time.sleep(0.3)
            self.log(f"⌨️ Pressing Enter to confirm...")
            self.press_key('return')
            time.sleep(0.5)
            self.log(f"✅ File selected: {file_path}")
            return True
        except Exception as e:
            self.log(f"❌ Error selecting file: {e}")
            return False

    def handle_dialog_no(self) -> bool:
        self.log(f"\n{'='*60}")
        self.log(f"🎯 Clicking NO in dialog")
        self.log(f"{'='*60}")
        try:
            time.sleep(0.3)
            if self.hotkey('alt', 'n'):
                self.log(f"✅ NO button activated via Alt+N shortcut")
                time.sleep(0.5)
                return True
            self.log(f"⌨️ Using Tab to navigate to NO button...")
            self.press_key('tab')
            time.sleep(0.2)
            self.press_key('space')
            time.sleep(0.5)
            self.log(f"✅ NO button activated")
            return True
        except Exception as e:
            self.log(f"❌ Error clicking NO: {e}")
            return False

    def navigate_and_activate_button(self, button_index: int = 0) -> bool:
        self.log(f"\n{'='*60}")
        self.log(f"🎯 Navigating to button {button_index}")
        self.log(f"{'='*60}")
        if not self.ensure_window_focused():
            return False
        try:
            for i in range(button_index):
                self.press_key('tab', interval=0.15)
            time.sleep(0.2)
            self.log(f"⌨️ Pressing Space to activate button...")
            self.press_key('space')
            time.sleep(0.5)
            self.log(f"✅ Button activated via Tab navigation")
            return True
        except Exception as e:
            self.log(f"❌ Error navigating: {e}")
            return False
from PySide6.QtCore import qInstallMessageHandler

def silence_qt_warnings(msg_type, context, message):
    pass
qInstallMessageHandler(silence_qt_warnings)

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
TEST_CASES = [
    "SoC BEHAVIOR", "SHUTDOWN PROCESS", "PRECHARGE PROCESS",
    "BMS STATE TRANSITION", "CELL TEMP IMBALANCE", "BMS PCB TEMP",
    "ANY BMS ERROR", "FLAG FULL CHARGE DISABLE", "DCLI / DCLO MAP",
    "EQUIVALENT CYCLE COUNT", "BMS BALANCING",
    "PRIMARY VS SECONDARY LATCH", "MCU OBC ERROR", "AuxCharge_with_Vehicle_state_change",
    "SoC vs VOLTAGE SUMMARY", "CAPACITY + SoC vs RANGE CHECK", "BMS CURRENT IN READY MODE", "DRIVE_CHARGE Max Min Avg CURRENT"
]

FW_CHECKER = "FW_Config_checker.py"
CLEAR_OUTPUTS_ON_RUN_ALL = True
AUTOMATE_BUTTON_ENABLED = False
DEFAULT_EXCEL_SEQUENCE_FILE = "excel_tracker_sequence.txt"

SCRIPT_BY_ROW: Dict[int, str] = {
    0: "SoC_behavior.py",
    1: "Shutdown_Process.py",
    2: "Precharge_Process.py",
    3: "BMS_State_transition.py",
    4: "Cell_Temp_Imbalance.py",
    5: "BMS_PCB_Temp.py",
    6: "Any_BMS_Error.py",
    7: "Flag_Full_Charge_Disable.py",
    8: "DCLI_DCLO_Map.py",
    9: "Equivalent_cycle_count.py",
    10: "BMS_Balancing.py",
    11: "Primary_vs_Secondary_Latch.py",
    12: "MCU_OBC_Error.py",
    13: "AuxCharge_with_Vehicle_state_change.py",
    14: "SoC_vs_Voltage_Summary.py",
    15: "Capacity_check.py",
    16: "BMS_Current_in_Ready_Mode.py",
    17: "DRIVE_CHARGE_Max_Min_Avg_CURRENT.py",
}

RESULT_POLL_ATTEMPTS = 10
RESULT_POLL_DELAY_MS = 500


# -------------------------------------------------------
# MULTI-SOURCE AUTOMATION WORKER (Google Drive + Local Folders)
# -------------------------------------------------------
class MultiSourceAutomationWorker(QThread):
    log_signal = Signal(str)
    status_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)
    
    def __init__(self, sources: List[str], parent=None):
        super().__init__(parent)
        self.sources = sources  # List of URLs or local paths
        self.parent_gui = parent
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.temp_folder = os.path.join(self.script_dir, "temp_automation")
        self.all_downloaded_files = []
        self.source_count = len(sources)
        
    def _extract_folder_id(self, url: str) -> str:
        import re
        patterns = [
            r'/folders/([a-zA-Z0-9_-]+)',
            r'id=([a-zA-Z0-9_-]+)',
            r'drive.google.com/open\?id=([a-zA-Z0-9_-]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return url
    
    def _is_google_drive_link(self, source: str) -> bool:
        return "drive.google.com" in source.lower() or "google.com" in source.lower()
    
    def _download_from_drive(self, drive_link: str) -> List[str]:
        """Download TRC files from Google Drive"""
        import gdown
        
        folder_id = self._extract_folder_id(drive_link)
        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
        self.log_signal.emit(f"📁 Google Drive Folder ID: {folder_id}")
        
        # Create temp folder
        os.makedirs(self.temp_folder, exist_ok=True)
        
        self.log_signal.emit("⬇️ Downloading TRC files from Google Drive...")
        
        try:
            gdown.download_folder(url=folder_url, output=self.temp_folder, use_cookies=False)
        except Exception as e:
            self.log_signal.emit(f"⚠️ Error downloading: {str(e)}")
            return []
        
        # Find all downloaded .trc files
        downloaded_files = []
        for root, dirs, files in os.walk(self.temp_folder):
            for file in files:
                if file.lower().endswith('.trc'):
                    downloaded_files.append(os.path.join(root, file))
        
        return downloaded_files
    
    def _copy_from_local_folder(self, local_path: str) -> List[str]:
        """Copy TRC files from local folder"""
        self.log_signal.emit(f"📂 Scanning local folder: {local_path}")
        
        if not os.path.isdir(local_path):
            self.log_signal.emit(f"❌ Folder not found: {local_path}")
            return []
        
        # Create temp folder
        os.makedirs(self.temp_folder, exist_ok=True)
        
        copied_files = []
        for root, dirs, files in os.walk(local_path):
            for file in files:
                if file.lower().endswith('.trc'):
                    src_path = os.path.join(root, file)
                    dst_path = os.path.join(self.temp_folder, file)
                    
                    # If file exists, add counter to avoid overwrite
                    counter = 1
                    base_name, ext = os.path.splitext(file)
                    while os.path.exists(dst_path):
                        dst_path = os.path.join(self.temp_folder, f"{base_name}_{counter}{ext}")
                        counter += 1
                    
                    try:
                        shutil.copy2(src_path, dst_path)
                        copied_files.append(dst_path)
                        self.log_signal.emit(f"  ✓ Copied: {os.path.basename(dst_path)}")
                    except Exception as e:
                        self.log_signal.emit(f"  ✗ Failed to copy {file}: {str(e)}")
        
        return copied_files
    
    def run(self):
        try:
            self.log_signal.emit("🚀 Starting Multi-Source Automation")
            self.log_signal.emit(f"📊 Processing {self.source_count} source(s)...")
            
            # Clear temp folder at start
            if os.path.exists(self.temp_folder):
                shutil.rmtree(self.temp_folder)
            os.makedirs(self.temp_folder, exist_ok=True)
            
            # Process each source
            for idx, source in enumerate(self.sources):
                self.log_signal.emit(f"\n📌 Processing source {idx+1}/{self.source_count}...")
                
                if self._is_google_drive_link(source):
                    files = self._download_from_drive(source)
                else:
                    files = self._copy_from_local_folder(source)
                
                self.all_downloaded_files.extend(files)
                self.log_signal.emit(f"✅ Found {len(files)} TRC file(s)")
            
            if not self.all_downloaded_files:
                self.log_signal.emit("❌ No TRC files found in any source")
                self.finished_signal.emit(False, "No TRC files found")
                return
            
            self.log_signal.emit(f"📊 Total: {len(self.all_downloaded_files)} TRC file(s) collected")
            for f in self.all_downloaded_files:
                size = os.path.getsize(f) / 1024 / 1024
                self.log_signal.emit(f"  📄 {os.path.basename(f)} ({size:.1f} MB)")
            
            self.progress_signal.emit(20)
            
            # Step 2: Click MAKE YOUR LOGS ORGANISED (KEYBOARD SHORTCUT)
            self.log_signal.emit("\n📂 Activating 'MAKE YOUR LOGS ORGANISED' (Alt+M)...")
            self.status_signal.emit("Organising logs...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            # Notify UI to highlight the Make button
            self.status_signal.emit("UI:make_btn:start")
            if automation.click_make_organised():
                self.log_signal.emit("✅ Button activated via keyboard shortcut")
                self.status_signal.emit("UI:make_btn:done")
            else:
                self.log_signal.emit("⚠️ Could not click button")
                self.status_signal.emit("UI:make_btn:failed")
            
            # Wait for logs_organised to complete
            self.log_signal.emit("⏳ Waiting for logs organisation...")
            timeout = 120
            elapsed = 0
            while elapsed < timeout:
                if hasattr(self.parent_gui, 'logs_organised_complete') and self.parent_gui.logs_organised_complete:
                    break
                time.sleep(1)
                elapsed += 1
            
            if elapsed >= timeout:
                self.log_signal.emit("⚠️ Timeout waiting for logs organisation")
            else:
                self.log_signal.emit("✅ Logs organised successfully")
            
            self.progress_signal.emit(40)
            
            # Step 3: Find the organised TRC file
            organised_trc = None
            if hasattr(self.parent_gui, 'logs_last_output_path') and self.parent_gui.logs_last_output_path:
                organised_trc = self.parent_gui.logs_last_output_path
                if os.path.exists(organised_trc):
                    self.log_signal.emit(f"📄 Organised file: {os.path.basename(organised_trc)}")
                    # Save the FINAL filename
                    self._save_final_filename(organised_trc)
            
            if not organised_trc or not os.path.exists(organised_trc):
                # Use the first downloaded TRC file
                if self.all_downloaded_files:
                    organised_trc = self.all_downloaded_files[0]
                    self.log_signal.emit(f"📄 Using file: {os.path.basename(organised_trc)}")
                    self._save_final_filename(organised_trc)
            
            if not organised_trc or not os.path.exists(organised_trc):
                self.log_signal.emit("❌ Could not find TRC file")
                self.finished_signal.emit(False, "TRC file not found")
                return
            
            # Step 4: Click Browse and select file (KEYBOARD SHORTCUT)
            self.log_signal.emit("🖱️ Activating file browser (Alt+B)...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            self.status_signal.emit("UI:browse_btn:start")
            if automation.click_browse_file():
                self.log_signal.emit("✅ Browse button activated")
                self.status_signal.emit("UI:browse_btn:done")
                # Handle file selection in dialog
                self.status_signal.emit("UI:dialog_select:start")
                if automation.select_file_in_dialog(organised_trc):
                    self.log_signal.emit(f"✅ File selected: {os.path.basename(organised_trc)}")
                    self.status_signal.emit("UI:dialog_select:done")
                else:
                    self.log_signal.emit("⚠️ Could not select file in dialog")
                    self.status_signal.emit("UI:dialog_select:failed")
            else:
                self.log_signal.emit("⚠️ Could not activate Browse button")
                self.status_signal.emit("UI:browse_btn:failed")
            
            time.sleep(3)
            self.progress_signal.emit(50)
            
            # Step 5: Click RUN ALL TEST CASES (KEYBOARD SHORTCUT)
            self.log_signal.emit("\n▶️ Activating 'RUN ALL TEST CASES' (Alt+R)...")
            self.status_signal.emit("Running test cases...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            self.status_signal.emit("UI:run_all_btn:start")
            if automation.click_run_all_tests():
                self.log_signal.emit("✅ Run All Tests activated via keyboard")
                self.status_signal.emit("UI:run_all_btn:done")
            else:
                self.log_signal.emit("⚠️ Could not click Run All Tests button")
                self.status_signal.emit("UI:run_all_btn:failed")
            
            # Wait for tests to complete
            self.log_signal.emit("⏳ Waiting for tests to complete (this may take a while)...")
            timeout = 1800
            elapsed = 0
            while elapsed < timeout:
                if hasattr(self.parent_gui, 'tests_complete') and self.parent_gui.tests_complete:
                    break
                time.sleep(2)
                elapsed += 2
                self.progress_signal.emit(50 + int(elapsed / timeout * 35))
            
            if elapsed >= timeout:
                self.log_signal.emit("⚠️ Timeout waiting for tests")
            else:
                self.log_signal.emit("✅ All tests completed")
            
            self.progress_signal.emit(85)
            
            # Step 6: Click CREATE EXCEL TRACKER (KEYBOARD SHORTCUT)
            self.log_signal.emit("\n📊 Activating 'CREATE EXCEL TRACKER' (Alt+C)...")
            self.status_signal.emit("Generating Excel tracker...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            self.status_signal.emit("UI:gen_excel_btn:start")
            if automation.click_create_excel_tracker():
                self.log_signal.emit("✅ Create Tracker activated via keyboard")
                self.status_signal.emit("UI:gen_excel_btn:done")
            else:
                self.log_signal.emit("⚠️ Could not click Create Tracker button")
                self.status_signal.emit("UI:gen_excel_btn:failed")
            
            time.sleep(5)
            
            # Step 7: Handle the popup (click NO via Alt+N)
            self.log_signal.emit("✋ Handling Excel popup (Alt+N)...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            self.status_signal.emit("UI:dialog_no:start")
            if automation.handle_dialog_no():
                self.log_signal.emit("✅ NO button activated via keyboard")
                self.status_signal.emit("UI:dialog_no:done")
            else:
                self.log_signal.emit("⚠️ Could not click NO button")
                self.status_signal.emit("UI:dialog_no:failed")
            
            time.sleep(2)
            self.progress_signal.emit(100)
            
            self.log_signal.emit("🎉 Automation completed successfully!")
            self.log_signal.emit("📁 Ready for next source if needed...")
            self.finished_signal.emit(True, "All tasks completed successfully")
            
        except Exception as e:
            self.log_signal.emit(f"❌ Error: {str(e)}")
            import traceback
            self.log_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(e))
    
    def _save_final_filename(self, file_path: str):
        """Save the FINAL filename to a text file"""
        try:
            final_txt_path = os.path.join(self.script_dir, "FINAL_start.txt")
            with open(final_txt_path, "w", encoding="utf-8") as f:
                f.write(file_path)
            self.log_signal.emit(f"💾 Saved FINAL filename to: {final_txt_path}")
        except Exception as e:
            self.log_signal.emit(f"⚠️ Could not save FINAL filename: {str(e)}")


# -------------------------------------------------------
# DRIVE AUTOMATION WORKER (DEPRECATED - keeping for backward compatibility)
# -------------------------------------------------------
class DriveAutomationWorker(QThread):
    log_signal = Signal(str)
    status_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)
    
    def __init__(self, drive_link: str, parent=None):
        super().__init__(parent)
        self.drive_link = drive_link
        self.parent_gui = parent
        self.temp_folder = None
        self.downloaded_files = []
        
    def _extract_folder_id(self, url: str) -> str:
        import re
        patterns = [
            r'/folders/([a-zA-Z0-9_-]+)',
            r'id=([a-zA-Z0-9_-]+)',
            r'drive.google.com/open\?id=([a-zA-Z0-9_-]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return url
    
    def run(self):
        try:
            import gdown
            
            self.log_signal.emit("🔐 Connecting to Google Drive...")
            
            folder_id = self._extract_folder_id(self.drive_link)
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
            self.log_signal.emit(f"📁 Folder ID: {folder_id}")
            
            # Create temp folder
            self.temp_folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), "temp_automation")
            os.makedirs(self.temp_folder, exist_ok=True)
            
            self.log_signal.emit("🔍 Scanning for TRC files...")
            self.log_signal.emit("⬇️ Downloading TRC files...")
            
            # Download entire folder using gdown
            gdown.download_folder(url=folder_url, output=self.temp_folder, use_cookies=False)
            
            # Find all downloaded .trc files
            self.downloaded_files = []
            for root, dirs, files in os.walk(self.temp_folder):
                for file in files:
                    if file.lower().endswith('.trc'):
                        self.downloaded_files.append(os.path.join(root, file))
            
            if not self.downloaded_files:
                self.log_signal.emit("❌ No TRC files found in the provided link")
                self.finished_signal.emit(False, "No TRC files found")
                return
            
            self.log_signal.emit(f"📊 Found {len(self.downloaded_files)} TRC file(s)")
            for f in self.downloaded_files:
                size = os.path.getsize(f) / 1024 / 1024
                self.log_signal.emit(f"  📄 {os.path.basename(f)} ({size:.1f} MB)")
            
            self.progress_signal.emit(30)
            
            # Step 2: Click MAKE YOUR LOGS ORGANISED (KEYBOARD SHORTCUT)
            self.log_signal.emit("📂 Activating 'MAKE YOUR LOGS ORGANISED' (Alt+M)...")
            self.status_signal.emit("Organising logs...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            if automation.click_make_organised():
                self.log_signal.emit("✅ Button activated via keyboard shortcut")
            else:
                self.log_signal.emit("⚠️ Could not activate button")
            
            # Wait for logs_organised to complete
            self.log_signal.emit("⏳ Waiting for logs organisation...")
            timeout = 120
            elapsed = 0
            while elapsed < timeout:
                if hasattr(self.parent_gui, 'logs_organised_complete') and self.parent_gui.logs_organised_complete:
                    break
                time.sleep(1)
                elapsed += 1
            
            if elapsed >= timeout:
                self.log_signal.emit("⚠️ Timeout waiting for logs organisation")
            else:
                self.log_signal.emit("✅ Logs organised successfully")
            
            self.progress_signal.emit(50)
            
            # Step 3: Find the organised TRC file
            organised_trc = None
            if hasattr(self.parent_gui, 'logs_last_output_path') and self.parent_gui.logs_last_output_path:
                organised_trc = self.parent_gui.logs_last_output_path
                if os.path.exists(organised_trc):
                    self.log_signal.emit(f"📄 Organised file: {os.path.basename(organised_trc)}")
            
            if not organised_trc or not os.path.exists(organised_trc):
                # Use the first downloaded TRC file
                if self.downloaded_files:
                    organised_trc = self.downloaded_files[0]
                    self.log_signal.emit(f"📄 Using downloaded file: {os.path.basename(organised_trc)}")
            
            if not organised_trc or not os.path.exists(organised_trc):
                self.log_signal.emit("❌ Could not find TRC file")
                self.finished_signal.emit(False, "TRC file not found")
                return
            
            # Step 4: Click Browse and select file (KEYBOARD SHORTCUT)
            self.log_signal.emit("🖱️ Activating file browser (Alt+B)...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            if automation.click_browse_file():
                self.log_signal.emit("✅ Browse button activated")
                # Handle file selection in dialog
                if automation.select_file_in_dialog(organised_trc):
                    self.log_signal.emit(f"✅ File selected: {os.path.basename(organised_trc)}")
                else:
                    self.log_signal.emit("⚠️ Could not select file in dialog")
            else:
                self.log_signal.emit("⚠️ Could not activate Browse button")
            
            time.sleep(3)
            self.progress_signal.emit(60)
            
            # Step 5: Click RUN ALL TEST CASES (KEYBOARD SHORTCUT)
            self.log_signal.emit("▶️ Activating 'RUN ALL TEST CASES' (Alt+R)...")
            self.status_signal.emit("Running test cases...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            if automation.click_run_all_tests():
                self.log_signal.emit("✅ Run All Tests activated via keyboard")
            else:
                self.log_signal.emit("⚠️ Could not activate Run All Tests button")
            
            # Wait for tests to complete
            self.log_signal.emit("⏳ Waiting for tests to complete...")
            timeout = 1800
            elapsed = 0
            while elapsed < timeout:
                if hasattr(self.parent_gui, 'tests_complete') and self.parent_gui.tests_complete:
                    break
                time.sleep(2)
                elapsed += 2
                self.progress_signal.emit(60 + int(elapsed / timeout * 30))
            
            if elapsed >= timeout:
                self.log_signal.emit("⚠️ Timeout waiting for tests")
            else:
                self.log_signal.emit("✅ All tests completed")
            
            self.progress_signal.emit(90)
            
            # Step 6: Click CREATE EXCEL TRACKER (KEYBOARD SHORTCUT)
            self.log_signal.emit("📊 Activating 'CREATE EXCEL TRACKER' (Alt+C)...")
            self.status_signal.emit("Generating Excel tracker...")
            automation = KeyboardAutomation(window_title="CAN LOG ANALYSER", verbose=True)
            if automation.click_create_excel_tracker():
                self.log_signal.emit("✅ Create Tracker activated via keyboard")
            else:
                self.log_signal.emit("⚠️ Could not activate Create Tracker button")
            
            time.sleep(5)
            self.progress_signal.emit(100)
            
            self.log_signal.emit("🎉 Automation completed successfully!")
            self.finished_signal.emit(True, "All tasks completed successfully")
            
        except Exception as e:
            self.log_signal.emit(f"❌ Error: {str(e)}")
            import traceback
            self.log_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(e))


# -------------------------------------------------------
# COLOR THEME MANAGER
# -------------------------------------------------------
class ColorTheme:
    def __init__(self):
        self.colors = {
            "title_bg_start": "#001F6B",
            "title_bg_mid": "#0033CC", 
            "title_bg_end": "#4DE8FF",
            "title_text": "#00FFFF",
            "version_text": "white",
            "ft_label_bg": "#1FA37A",
            "browse_btn_bg": "#2B8CE7",
            "make_btn_bg": "#FF0000",
            "run_all_btn_bg": "#28A745",
            "bms_label_bg": "#1F4EB2",
            "stark_label_bg": "#2CBDF2",
            "xavier_label_bg": "#1FA37A",
            "distance_label_bg": "#1FA37A",
            "mcu_label_bg": "#006400",
            "table_header_bg": "#FF0000",
            "table_header_text": "white",
            "testcase_text": "#1FA37A",
            "pass_bg": "#28A745",
            "fail_bg": "#FF0000",
            "warning_bg": "#FFA500",
            "running_bg": "#00138B",
            "running_shine": "#4DE8FF",
            "completed_bg": "#28A745",
            "error_bg": "#FF0000",
            "gen_btn_bg": "black",
            "gen_btn_text": "white",
            "auto_btn_bg": "#17a2b8",
            "vcu_btn_bg": "#28A745",
            "bms_btn_bg": "#28A745",
            "view_btn_bg": "#3a7bd5",
            "graph_btn_bg": "#00b8ff",
            "run_btn_bg": "#28A745",
            "main_bg": "#f0f0f0",
        }
    
    def get(self, key, default=None):
        return self.colors.get(key, default)
    
    def set(self, key, value):
        self.colors[key] = value
    
    def save_to_file(self, path="theme.json"):
        try:
            with open(path, "w") as f:
                json.dump(self.colors, f, indent=4)
        except Exception:
            pass
    
    def load_from_file(self, path="theme.json"):
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    loaded = json.load(f)
                    self.colors.update(loaded)
        except Exception:
            pass


# -------------------------------------------------------
# COLOR CUSTOMIZATION PANEL
# -------------------------------------------------------
class ColorCustomizationPanel(QDialog):
    def __init__(self, theme: ColorTheme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle("🎨 Customize Colors")
        self.setMinimumSize(580, 700)
        self.setModal(True)
        
        self.setStyleSheet("""
            QDialog { background-color: #000000; color: #ffffff; }
            QLabel { color: #ffffff; font-weight: bold; font-size: 12px; background-color: transparent; }
            QComboBox { background-color: #2a2a2a; color: #ffffff; border: 1px solid #555555; padding: 5px; border-radius: 5px; min-width: 110px; }
            QComboBox QAbstractItemView { background-color: #2a2a2a; color: #ffffff; selection-background-color: #4CAF50; }
            QPushButton { background-color: #4CAF50; color: #ffffff; border: none; padding: 8px 15px; border-radius: 5px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #45a049; }
            QPushButton#reset { background-color: #f44336; }
            QPushButton#reset:hover { background-color: #da190b; }
            QPushButton#save { background-color: #2196F3; }
            QPushButton#save:hover { background-color: #0b7dda; }
            QScrollArea { border: none; background-color: transparent; }
            QFrame { background-color: #1a1a1a; border-radius: 6px; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        title = QLabel("🎨 COLOR CUSTOMIZATION")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 12px; background-color: #1a1a1a; border-radius: 8px; color: #00ffcc;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: #000000;")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(5)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        
        color_groups = {
            "🎨 TITLE BAR": [
                ("Title Background Start", "title_bg_start"),
                ("Title Background Middle", "title_bg_mid"),
                ("Title Background End", "title_bg_end"),
                ("Title Text", "title_text"),
            ],
            "📁 FILE SECTION": [
                ("File Type Label BG", "ft_label_bg"),
                ("Browse Button BG", "browse_btn_bg"),
                ("Organize Logs Button BG", "make_btn_bg"),
                ("Run All Button BG", "run_all_btn_bg"),
            ],
            "🔧 FIRMWARE LABELS": [
                ("BMS Label BG", "bms_label_bg"),
                ("STARK Label BG", "stark_label_bg"),
                ("XAVIER Label BG", "xavier_label_bg"),
                ("Distance Label BG", "distance_label_bg"),
                ("MCU/Serial/OS Label BG", "mcu_label_bg"),
            ],
            "📊 TABLE SECTION": [
                ("Table Header BG", "table_header_bg"),
                ("Table Header Text", "table_header_text"),
                ("Test Case Text", "testcase_text"),
            ],
            "✅ TEST RESULTS": [
                ("PASS Background", "pass_bg"),
                ("FAIL Background", "fail_bg"),
                ("WARNING Background", "warning_bg"),
                ("Running Background", "running_bg"),
                ("Running Shine", "running_shine"),
                ("Completed Background", "completed_bg"),
                ("Error Background", "error_bg"),
            ],
            "🔘 BUTTONS": [
                ("Generate Report BG", "gen_btn_bg"),
                ("Generate Report Text", "gen_btn_text"),
                ("Automate Button BG", "auto_btn_bg"),
                ("View Button BG", "view_btn_bg"),
                ("Graph Button BG", "graph_btn_bg"),
                ("Run Button BG", "run_btn_bg"),
            ],
        }
        
        self.color_pickers = {}
        self.color_previews = {}
        
        for group_name, options in color_groups.items():
            group_label = QLabel(group_name)
            group_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #00ffcc; padding: 10px 0px 5px 5px; background-color: transparent;")
            scroll_layout.addWidget(group_label)
            
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("background-color: #333333; max-height: 1px;")
            scroll_layout.addWidget(sep)
            
            for label_text, color_key in options:
                row_frame = QFrame()
                row_frame.setStyleSheet("background-color: #1a1a1a; border-radius: 6px;")
                row_layout = QHBoxLayout(row_frame)
                row_layout.setContentsMargins(12, 8, 12, 8)
                row_layout.setSpacing(10)
                
                label = QLabel(label_text)
                label.setMinimumWidth(180)
                label.setStyleSheet("color: #ffffff; background-color: transparent; font-weight: bold;")
                row_layout.addWidget(label)
                
                color_preview = QFrame()
                color_preview.setFixedSize(40, 28)
                current_color = self.theme.get(color_key, "#1FA37A")
                color_preview.setStyleSheet(f"background-color: {current_color}; border-radius: 5px; border: 1px solid #888888;")
                row_layout.addWidget(color_preview)
                
                hex_label = QLabel(current_color.upper())
                hex_label.setStyleSheet("color: #00ffcc; font-family: monospace; font-size: 10px; background-color: #2a2a2a; padding: 4px 8px; border-radius: 4px;")
                hex_label.setMinimumWidth(80)
                hex_label.setAlignment(Qt.AlignCenter)
                row_layout.addWidget(hex_label)
                
                combo = QComboBox()
                combo.addItems(["Select...", "Red", "Green", "Blue", "Yellow", "Cyan", "Magenta", "Orange", "Purple", "Black", "White", "Custom..."])
                combo.setMinimumWidth(110)
                combo.color_key = color_key
                combo.color_preview = color_preview
                combo.hex_label = hex_label
                combo.currentTextChanged.connect(lambda text, k=color_key, p=color_preview, h=hex_label: self.on_color_selected(text, k, p, h))
                row_layout.addWidget(combo)
                
                scroll_layout.addWidget(row_frame)
                
                self.color_pickers[color_key] = combo
                self.color_previews[color_key] = color_preview
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        btn_container = QFrame()
        btn_container.setStyleSheet("background-color: #1a1a1a; border-radius: 8px; margin-top: 5px;")
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setSpacing(10)
        btn_layout.setContentsMargins(15, 10, 15, 10)
        
        apply_btn = QPushButton("✓ APPLY CHANGES")
        apply_btn.clicked.connect(self.apply_colors)
        btn_layout.addWidget(apply_btn)
        
        reset_btn = QPushButton("↺ RESET ALL")
        reset_btn.setObjectName("reset")
        reset_btn.clicked.connect(self.reset_colors)
        btn_layout.addWidget(reset_btn)
        
        save_btn = QPushButton("💾 SAVE THEME")
        save_btn.setObjectName("save")
        save_btn.clicked.connect(self.save_theme)
        btn_layout.addWidget(save_btn)
        
        load_btn = QPushButton("📂 LOAD THEME")
        load_btn.clicked.connect(self.load_theme)
        btn_layout.addWidget(load_btn)
        
        layout.addWidget(btn_container)
        
        close_btn = QPushButton("CLOSE")
        close_btn.setStyleSheet("background-color: #6c757d; padding: 10px; font-size: 12px;")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self.resize(600, 750)
    
    def on_color_selected(self, text, color_key, preview_widget, hex_label):
        color_map = {
            "Red": "#FF0000", "Green": "#00FF00", "Blue": "#0000FF",
            "Yellow": "#FFFF00", "Cyan": "#00FFFF", "Magenta": "#FF00FF",
            "Orange": "#FFA500", "Purple": "#800080", "Black": "#000000", "White": "#FFFFFF",
        }
        
        if text == "Custom...":
            color = QColorDialog.getColor()
            if color.isValid():
                color_hex = color.name().upper()
                self.theme.set(color_key, color_hex)
                preview_widget.setStyleSheet(f"background-color: {color_hex}; border-radius: 5px; border: 1px solid #888888;")
                hex_label.setText(color_hex)
        elif text in color_map:
            color_hex = color_map[text]
            self.theme.set(color_key, color_hex)
            preview_widget.setStyleSheet(f"background-color: {color_hex}; border-radius: 5px; border: 1px solid #888888;")
            hex_label.setText(color_hex)
    
    def apply_colors(self):
        if self.parent():
            self.parent().apply_theme_colors()
        QMessageBox.information(self, "Success", "✓ Colors applied successfully!")
    
    def reset_colors(self):
        reply = QMessageBox.question(self, "Reset Colors", "Reset ALL colors to default?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            new_theme = ColorTheme()
            for key in self.color_pickers.keys():
                default_color = new_theme.get(key, "#1FA37A")
                self.theme.set(key, default_color)
                if key in self.color_previews:
                    self.color_previews[key].setStyleSheet(f"background-color: {default_color}; border-radius: 5px; border: 1px solid #888888;")
                if key in self.color_pickers:
                    combo = self.color_pickers[key]
                    if hasattr(combo, 'hex_label') and combo.hex_label:
                        combo.hex_label.setText(default_color.upper())
                    combo.setCurrentIndex(0)
            self.apply_colors()
    
    def save_theme(self):
        self.theme.save_to_file()
        QMessageBox.information(self, "Success", "✓ Theme saved to theme.json")
    
    def load_theme(self):
        self.theme.load_from_file()
        for key in self.color_pickers.keys():
            loaded_color = self.theme.get(key, "#1FA37A")
            if key in self.color_previews:
                self.color_previews[key].setStyleSheet(f"background-color: {loaded_color}; border-radius: 5px; border: 1px solid #888888;")
            if key in self.color_pickers:
                combo = self.color_pickers[key]
                if hasattr(combo, 'hex_label') and combo.hex_label:
                    combo.hex_label.setText(loaded_color.upper())
                combo.setCurrentIndex(0)
        self.apply_colors()


class TestSequenceDialog(QDialog):
    def __init__(self, sequence_items: List[str], parent=None):
        super().__init__(parent)
        self.default_items = list(sequence_items)
        self.script_dir = getattr(parent, "script_dir", os.path.dirname(os.path.realpath(__file__)))
        self.setWindowTitle("Arrange Test Sequence")
        self.setMinimumSize(520, 640)
        self.setModal(True)

        layout = QVBoxLayout(self)

        title = QLabel("Arrange Excel Tracker Sequence")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px; background:#2b8ce7; color:white; border-radius:4px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.list_widget, 1)

        move_layout = QHBoxLayout()
        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(self.move_up)
        move_layout.addWidget(up_btn)
        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(self.move_down)
        move_layout.addWidget(down_btn)
        reset_btn = QPushButton("Reset Default")
        reset_btn.clicked.connect(self.reset_default)
        move_layout.addWidget(reset_btn)
        layout.addLayout(move_layout)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet("background:#28A745; color:white; font-weight:bold; padding:8px;")
        save_btn.clicked.connect(self.save_sequence)
        btn_layout.addWidget(save_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.ensure_sequence_file()
        self.load_sequence()

    def _default_sequence_path(self) -> str:
        return os.path.join(self.script_dir, DEFAULT_EXCEL_SEQUENCE_FILE)

    def _saved_sequence_path(self) -> str:
        return self._default_sequence_path()

    def _write_sequence_items(self, path: str, items: List[str]):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def ensure_sequence_file(self):
        path = self._saved_sequence_path()
        if os.path.exists(path):
            return
        try:
            self._write_sequence_items(path, self.default_items)
        except Exception:
            pass

    def _read_sequence_items(self, path: str) -> List[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            return []

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except Exception:
            pass

        valid_items = set(self.default_items)
        items = []
        pending = ""
        for line in raw.splitlines():
            part = line.strip()
            if not part:
                continue
            if pending:
                combined = f"{pending}\n{part}"
                if combined in valid_items:
                    items.append(combined)
                    pending = ""
                    continue
                if pending in valid_items:
                    items.append(pending)
                pending = ""
            if part in valid_items:
                items.append(part)
            else:
                pending = part
        if pending and pending in valid_items:
            items.append(pending)
        return items

    def _current_items(self) -> List[str]:
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]

    def _set_items(self, items: List[str]):
        self.list_widget.clear()
        for item in items:
            self.list_widget.addItem(QListWidgetItem(item))
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def load_sequence(self):
        items = []
        sequence_path = self._saved_sequence_path()
        if os.path.exists(sequence_path):
            items = self._read_sequence_items(sequence_path)
        valid = [item for item in items if item in self.default_items]
        valid.extend(item for item in self.default_items if item not in valid)
        self._set_items(valid)

    def move_up(self):
        row = self.list_widget.currentRow()
        if row <= 0:
            return
        item = self.list_widget.takeItem(row)
        self.list_widget.insertItem(row - 1, item)
        self.list_widget.setCurrentRow(row - 1)

    def move_down(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= self.list_widget.count() - 1:
            return
        item = self.list_widget.takeItem(row)
        self.list_widget.insertItem(row + 1, item)
        self.list_widget.setCurrentRow(row + 1)

    def reset_default(self):
        self._set_items(self.default_items)
        try:
            self._write_sequence_items(self._saved_sequence_path(), self.default_items)
        except Exception as e:
            QMessageBox.warning(self, "Reset Failed", f"Could not save default test sequence:\n{e}")

    def save_sequence(self):
        path = self._saved_sequence_path()
        try:
            self._write_sequence_items(path, self._current_items())
            QMessageBox.information(self, "Saved", "Test sequence settings saved.")
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", f"Could not save test sequence settings:\n{e}")


# -------------------------------------------------------
# JSON POPUP
# -------------------------------------------------------
class JsonDialog(QDialog):
    def __init__(self, json_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Test Result")
        self.resize(550, 380)
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="cp1252", errors="replace") as f:
                    loaded = json.load(f)
                pretty = json.dumps(loaded, indent=4, ensure_ascii=False)
            except Exception as e:
                pretty = f"Failed to load JSON:\n{e}"
        else:
            pretty = f"File not found:\n{json_path}"
        text.setPlainText(pretty)
        layout.addWidget(text)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, alignment=Qt.AlignCenter)


# -------------------------------------------------------
# IMAGE POPUP
# -------------------------------------------------------
class ImageDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Graph")
        self.resize(650, 480)
        layout = QVBoxLayout(self)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        if os.path.exists(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                if pix.width() > 620 or pix.height() > 420:
                    pix = pix.scaled(620, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(pix)
            else:
                label.setText("Failed to load image.")
        else:
            label.setText(f"File not found:\n{image_path}")
        layout.addWidget(label)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, alignment=Qt.AlignCenter)


# -------------------------------------------------------
# FW CHECK THREAD
# -------------------------------------------------------
class FWCheckerThread(QThread):
    finished_ok = Signal(dict)
    finished_err = Signal(str)
    def __init__(self, trc_file):
        super().__init__()
        self.trc_file = trc_file
    def run(self):
        try:
            proc = subprocess.Popen([sys.executable, FW_CHECKER, self.trc_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            out, err = proc.communicate()
            if proc.returncode != 0:
                self.finished_err.emit(err)
                return
            try:
                self.finished_ok.emit(json.loads(out))
            except Exception:
                self.finished_err.emit("Invalid FW JSON output")
        except Exception as e:
            self.finished_err.emit(str(e))


# -------------------------------------------------------
# VCU RESET THREAD
# -------------------------------------------------------
class VCUResetThread(QThread):
    finished_ok = Signal(dict)
    finished_err = Signal(str)
    def __init__(self, trc_file: str, script_path: str, output_path: str):
        super().__init__()
        self.trc_file = trc_file
        self.script_path = script_path
        self.output_path = output_path
    def run(self):
        try:
            proc = subprocess.Popen([sys.executable, self.script_path, self.trc_file, self.output_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=os.path.dirname(self.script_path))
            out, err = proc.communicate()
            if proc.returncode != 0:
                self.finished_err.emit(err or out or "VCU reset script failed")
                return
            with open(self.output_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            self.finished_ok.emit(data)
        except Exception as e:
            self.finished_err.emit(str(e))


class BMSResetThread(QThread):
    finished_ok = Signal(dict)
    finished_err = Signal(str)
    def __init__(self, trc_file: str, script_path: str, output_path: str):
        super().__init__()
        self.trc_file = trc_file
        self.script_path = script_path
        self.output_path = output_path
    def run(self):
        try:
            proc = subprocess.Popen([sys.executable, self.script_path, self.trc_file, self.output_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=os.path.dirname(self.script_path))
            out, err = proc.communicate()
            if proc.returncode != 0:
                self.finished_err.emit(err or out or "BMS reset script failed")
                return
            with open(self.output_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            self.finished_ok.emit(data)
        except Exception as e:
            self.finished_err.emit(str(e))


# -------------------------------------------------------
# MCU DETECTION THREAD
# -------------------------------------------------------
class MCUDetectionThread(QThread):
    finished_ok = Signal(dict)
    finished_err = Signal(str)
    def __init__(self, trc_file: str, script_dir: str):
        super().__init__()
        self.trc_file = trc_file
        self.script_dir = script_dir
    def run(self):
        try:
            proc = subprocess.Popen([sys.executable, os.path.join(self.script_dir, "MCU_detection.py"), self.trc_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            out, err = proc.communicate()
            if proc.returncode != 0:
                self.finished_err.emit(err or "MCU detection failed")
                return
            self.finished_ok.emit(json.loads(out.strip()))
        except Exception as e:
            self.finished_err.emit(str(e))


# -------------------------------------------------------
# MAIN GUI
# -------------------------------------------------------
class CANLogDebugger(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAN LOG ANALYSER")
        self.setMinimumSize(1250, 780)

        self.theme = ColorTheme()
        self.theme.load_from_file()

        self.selected_file_path = ""
        self.logs_last_output_path: Optional[str] = None
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self._excel_tracker_headers_cache: Optional[List[str]] = None
        self.default_tests_folder = os.path.join(self.script_dir, "TRC TEST CASES")
        self.tests_folder_overrides = {".csv": os.path.join(self.script_dir, "CSV TEST CASES")}
        self.tests_folder = self._tests_folder_for_extension(".trc")
        self.vcu_reset_script = os.path.join(self.script_dir, "TRC TEST CASES", "ECU RESET", "VCU_Reset.py")
        self.vcu_reset_output = os.path.join(self.script_dir, "TRC TEST CASES", "ECU RESET", "VCU_Reset_Result.json")
        self.bms_reset_script = os.path.join(self.script_dir, "TRC TEST CASES", "ECU RESET", "BMS_Reset.py")
        self.bms_reset_output = os.path.join(self.script_dir, "TRC TEST CASES", "ECU RESET", "BMS_Reset_Result.json")
        self.scan_tasks = 0
        self.processes: Dict[int, QProcess] = {}
        self.running_rows: Set[int] = set()
        self.running_started_at: Dict[int, float] = {}
        self.running_pct: Dict[int, float] = {}
        self.output_files = self._load_output_config()
        self.pending_result_rows: Set[int] = set()
        self.result_refresh_timer = QTimer(self)
        self.result_refresh_timer.setInterval(1000)
        self.result_refresh_timer.timeout.connect(self._refresh_pending_results)

        self.testcase_labels = []
        self.run_btns = []
        self.view_btns = []
        self.graph_btns = []

        # Automation flags
        self.logs_organised_complete = False
        self.tests_complete = False
        self.automation_worker = None
        self.automation_in_progress = False
        self.auto_input_rows = []

        # ---------------- TITLE ----------------
        self.version_label = QLabel(self._read_version_text())
        self.version_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.version_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.version_label.setToolTip("Read from version.txt")

        self.auto_btn = QPushButton("🤖 LET'S AUTOMATE")
        self.auto_btn.setStyleSheet("background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 4px;")
        self.auto_btn.clicked.connect(self.on_automate_clicked)

        title = QLabel("CAN LOG ANALYSER")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        title_bar = QFrame()
        title_bar_layout = QHBoxLayout()
        title_bar_layout.setContentsMargins(10, 6, 10, 6)
        title_bar_layout.setSpacing(10)

        version_col = QVBoxLayout()
        version_col.setSpacing(4)
        version_col.addWidget(self.version_label, 0, Qt.AlignLeft | Qt.AlignTop)
        version_col.addWidget(self.auto_btn, 0, Qt.AlignLeft)

        title_bar_layout.addLayout(version_col, 0)
        title_bar_layout.addWidget(title, 1, Qt.AlignCenter)
        
        self.settings_btn = QPushButton("⚙ Settings")
        self.settings_btn.setStyleSheet("background:#6c757d; color:white; font-weight:bold; padding:5px 15px; border-radius:5px;")
        self.settings_btn.clicked.connect(self.on_settings_clicked)
        title_bar_layout.addWidget(self.settings_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        
        title_bar.setLayout(title_bar_layout)

        self.title_label = title
        self.title_container = title_bar
        self.title_anim_step = 0
        self.title_anim_timer = QTimer(self)
        self.title_anim_timer.timeout.connect(self._update_title_glow)
        self.title_anim_timer.start(120)
        
        self.make_btn_animating = False
        self.run_all_animating = False

        # ---------------------------------------------------
        # LEFT PANEL
        # ---------------------------------------------------
        ft_label = QLabel("Select file type")
        self.ft_combo = QComboBox()
        self.ft_combo.addItems([".trc", ".log", ".csv", ".xlsx"])
        self.browse_btn = QPushButton("Browse File")
        self.browse_btn.clicked.connect(self.on_browse)
        self.file_box = QLineEdit("No file selected")
        self.file_box.setReadOnly(True)
        self.make_btn = QPushButton("MAKE YOUR LOGS ORGANISED")
        self.make_btn.clicked.connect(self.on_make_logs)
        self.run_all_btn = QPushButton("RUN ALL TEST CASES")
        self.run_all_btn.setEnabled(False)
        self.run_all_btn.clicked.connect(self.start_all_tests)

        # Firmware Fields
        def fw_field(name):
            lbl = QLabel(name)
            box = QLineEdit()
            box.setReadOnly(True)
            return lbl, box

        (self.lb_hw, self.tx_hw) = fw_field("BMS HW VERSION")
        (self.lb_fw, self.tx_fw) = fw_field("BMS FIRMWARE")
        (self.lb_cfg, self.tx_cfg) = fw_field("BMS CONFIG ID")
        (self.lb_git, self.tx_git) = fw_field("BMS GITSHA")
        (self.lb_manifest, self.tx_manifest) = fw_field("BMS MANIFEST")
        (self.lb_stark_fw, self.tx_stark_fw) = fw_field("STARK FIRMWARE")
        (self.lb_stark_cfg, self.tx_stark_cfg) = fw_field("STARK CONFIG")
        (self.lb_xavier_fw, self.tx_xavier_fw) = fw_field("XAVIER FIRMWARE")
        (self.lb_distance, self.tx_distance) = fw_field("DISTANCE COVERED")
        (self.lb_mcu, self.tx_mcu) = fw_field("MCU BRANCH")
        (self.lb_serial, self.tx_serial) = fw_field("SERIAL NO")
        (self.lb_os, self.tx_os) = fw_field("OS Version & OS Build No")

        self.bms_labels = [self.lb_hw, self.lb_fw, self.lb_cfg, self.lb_git, self.lb_manifest]
        self.stark_labels = [self.lb_stark_fw, self.lb_stark_cfg]
        self.xavier_labels = [self.lb_xavier_fw]
        self.distance_labels = [self.lb_distance]
        self.mcu_labels = [self.lb_mcu, self.lb_serial, self.lb_os]

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(5, 5, 5, 5)
        fw_rows = [
            (self.lb_hw, self.tx_hw), (self.lb_fw, self.tx_fw), (self.lb_cfg, self.tx_cfg),
            (self.lb_git, self.tx_git), (self.lb_manifest, self.tx_manifest), (self.lb_stark_fw, self.tx_stark_fw),
            (self.lb_stark_cfg, self.tx_stark_cfg), (self.lb_xavier_fw, self.tx_xavier_fw), (self.lb_distance, self.tx_distance),
            (self.lb_mcu, self.tx_mcu), (self.lb_serial, self.tx_serial), (self.lb_os, self.tx_os),
        ]
        for r, (l, t) in enumerate(fw_rows):
            grid.addWidget(l, r, 0)
            grid.addWidget(t, r, 1)
        grid.setColumnStretch(0, 7)
        grid.setColumnStretch(1, 3)
        md_frame = QFrame()
        md_frame.setLayout(grid)

        # Extra Check Buttons
        self.btn_vcu = QPushButton("VCU unexpected Reset")
        self.tx_vcu_value = QLineEdit("0")
        self.tx_vcu_result = QLineEdit("N/A")
        self.btn_bms = QPushButton("MARVEL BMS unexpected Reset")
        self.tx_bms_value = QLineEdit("0")
        self.tx_bms_result = QLineEdit("N/A")
        for t in [self.tx_vcu_value, self.tx_vcu_result, self.tx_bms_value, self.tx_bms_result]:
            t.setReadOnly(True)
        self.vcu_value_palette_default = self.tx_vcu_value.palette()
        self.vcu_result_palette_default = self.tx_vcu_result.palette()
        self.bms_value_palette_default = self.tx_bms_value.palette()
        self.bms_result_palette_default = self.tx_bms_result.palette()
        self.btn_vcu.setEnabled(False)
        self.btn_bms.setEnabled(False)
        self.btn_vcu.setFocusPolicy(Qt.NoFocus)
        self.btn_bms.setFocusPolicy(Qt.NoFocus)

        extra_grid = QGridLayout()
        extra_grid.addWidget(self.btn_vcu, 0, 0)
        extra_grid.addWidget(self.tx_vcu_value, 0, 1)
        extra_grid.addWidget(self.tx_vcu_result, 0, 2)
        extra_grid.addWidget(self.btn_bms, 1, 0)
        extra_grid.addWidget(self.tx_bms_value, 1, 1)
        extra_grid.addWidget(self.tx_bms_result, 1, 2)
        extra_frame = QFrame()
        extra_frame.setLayout(extra_grid)

        # Generate Tracker Buttons
        btn_layout = QHBoxLayout()
        self.gen_btn = QPushButton("📄 CREATE REPORT")
        self.gen_btn.clicked.connect(self.generate_tracker)
        self.gen_excel_btn = QPushButton("📄 CREATE EXCEL TRACKER")
        self.gen_excel_btn.clicked.connect(self.generate_excel_tracker)
        btn_layout.addWidget(self.gen_btn)
        btn_layout.addWidget(self.gen_excel_btn)
        btn_frame = QFrame()
        btn_frame.setLayout(btn_layout)

        # LEFT PANEL FINAL BUILD
        left = QVBoxLayout()
        left.addWidget(self.make_btn)
        top_row = QHBoxLayout()
        top_row.addWidget(ft_label)
        top_row.addWidget(self.ft_combo)
        top_row.addWidget(self.browse_btn)
        left.addLayout(top_row)
        left.addWidget(self.file_box)
        left.addWidget(self.run_all_btn)
        left.addWidget(md_frame)
        left.addWidget(extra_frame)
        left.addWidget(btn_frame)
        left.addStretch()
        left_frame = QFrame()
        left_frame.setLayout(left)
        left_frame.setFixedWidth(380)

        # ---------------------------------------------------
        # RIGHT TABLE PANEL
        # ---------------------------------------------------
        table = QTableWidget(len(TEST_CASES), 5)
        table.setHorizontalHeaderLabels(["TEST CASE", "STATUS", "View Results", "View Graph", "Result"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table_header = table.horizontalHeader()
        for c in range(5):
            self.table_header.setSectionResizeMode(c, QHeaderView.Fixed)
        total_ratio = 10 + 5 + 5 + 5 + 3
        total_width = 900
        table.setColumnWidth(0, int(total_width * (10 / total_ratio)))
        table.setColumnWidth(1, int(total_width * (5 / total_ratio)))
        table.setColumnWidth(2, int(total_width * (5 / total_ratio)))
        table.setColumnWidth(3, int(total_width * (5 / total_ratio)))
        table.setColumnWidth(4, int(total_width * (3 / total_ratio)))

        for i, name in enumerate(TEST_CASES):
            display_name = "SoC BEHAVIOR + SoC STUCK" if i == 0 else name
            name_item = QTableWidgetItem(display_name)
            table.setItem(i, 0, name_item)
            cell_widget = QWidget()
            cell_widget.setStyleSheet("background:white;")
            h_layout = QHBoxLayout(cell_widget)
            h_layout.setContentsMargins(4, 0, 4, 0)
            h_layout.setSpacing(6)
            lbl = QLabel(display_name)
            lbl.setStyleSheet("font-weight:bold; background:white;")
            h_layout.addWidget(lbl, 1)
            btn_run = QPushButton("▶")
            btn_run.setToolTip("Run only this test case")
            btn_run.setStyleSheet("QPushButton { color:white; font-weight:bold; border-radius:12px; min-width:24px; max-width:24px; min-height:24px; max-height:24px; } QPushButton:pressed { background:#1f7a33; }")
            btn_run.clicked.connect(lambda _, r=i: self.start_single_test(r))
            btn_run.setFocusPolicy(Qt.NoFocus)
            h_layout.addWidget(btn_run, 0, Qt.AlignRight | Qt.AlignVCenter)
            table.setCellWidget(i, 0, cell_widget)
            status_item = QTableWidgetItem("Not Run")
            status_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 1, status_item)
            result_item = QTableWidgetItem("N/A")
            result_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(i, 4, result_item)
            btn_r = QPushButton("👁 View")
            btn_r.setStyleSheet("background-color: white; color: black; border: 1px solid #888888; border-radius: 6px; padding: 4px 10px;")
            btn_r.clicked.connect(lambda _, r=i: self.on_view_results(r))
            table.setCellWidget(i, 2, btn_r)
            btn_g = QPushButton("📊 Graph")
            btn_g.setStyleSheet("background-color: white; color: black; border: 1px solid #888888; border-radius: 6px; padding: 4px 10px;")
            btn_g.clicked.connect(lambda _, r=i: self.on_view_graph(r))
            table.setCellWidget(i, 3, btn_g)
            
            self.testcase_labels.append(lbl)
            self.run_btns.append(btn_run)
            self.view_btns.append(btn_r)
            self.graph_btns.append(btn_g)

        self.test_table = table

        right = QVBoxLayout()
        right.addWidget(table)
        right_frame = QFrame()
        right_frame.setLayout(right)

        # ---------------------------------------------------
        # AUTOMATION DIALOG (popup)
        # ---------------------------------------------------
        self.automation_dialog = None
        self.auto_link_input = None
        self.auto_progress = None
        self.auto_log = None
        self.auto_start_btn = None
        self.auto_cancel_btn = None

        # MAIN LAYOUT
        main = QHBoxLayout()
        main.addWidget(left_frame)
        main.addWidget(right_frame, 1)
        final = QVBoxLayout()
        final.addWidget(title_bar)
        final.addLayout(main)
        self.setLayout(final)
        
        self.ft_label = ft_label
        self.title_bar = title_bar
        self.title = title
        self.md_frame = md_frame
        self.extra_frame = extra_frame
        self.btn_frame = btn_frame
        self.left_frame = left_frame
        self.right_frame = right_frame
        
        self.apply_theme_colors()
        
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(send_heartbeat)
        self.heartbeat_timer.start(5000)

    # ======================================================
    # AUTOMATION METHODS
    # ======================================================
    def on_automate_clicked(self):
        if not AUTOMATE_BUTTON_ENABLED:
            QTimer.singleShot(30, lambda: QMessageBox.information(self, "Automation", "This feature is under development."))
            return
        QTimer.singleShot(30, self.show_automation_dialog)

    def show_automation_dialog(self):
        """Show the enhanced automation dialog with multi-link support"""
        self.automation_dialog = QDialog(self)
        self.automation_dialog.setWindowTitle("🤖 Drive Automation - Multi Source")
        self.automation_dialog.setMinimumWidth(600)
        self.automation_dialog.setMinimumHeight(500)
        self.automation_dialog.setModal(True)
        
        layout = QVBoxLayout(self.automation_dialog)
        
        # Title
        title_label = QLabel("🤖 AUTOMATION - Add Multiple Sources (Max 50)")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 10px; background-color: #17a2b8; color: white; border-radius: 4px;")
        layout.addWidget(title_label)
        
        # Instructions
        info_label = QLabel("• Add Google Drive folder links OR select local folders containing TRC files\n• Click the + button to add more sources (max 50)\n• Local folders will be copied to temp_automation folder")
        info_label.setStyleSheet("font-size: 10px; padding: 8px; background-color: #f0f0f0; border-radius: 4px;")
        layout.addWidget(info_label)
        
        # Scroll area for multiple inputs
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(5, 5, 5, 5)
        scroll_layout.setSpacing(8)
        
        # Store list of input rows
        self.auto_input_rows = []
        
        # Add first input
        self.add_auto_input_row(scroll_layout)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        # Add + button to add more inputs
        add_btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ ADD MORE SOURCE (Max 50)")
        add_btn.setStyleSheet("background-color: #007bff; color: white; font-weight: bold; padding: 8px;")
        add_btn.clicked.connect(lambda: self.add_auto_input_row(scroll_layout))
        add_btn_layout.addWidget(add_btn)
        add_btn_layout.addStretch()
        layout.addLayout(add_btn_layout)
        
        # Progress bar
        self.auto_progress = QProgressBar()
        self.auto_progress.setVisible(False)
        layout.addWidget(self.auto_progress)
        
        # Log area
        self.auto_log = QTextEdit()
        self.auto_log.setReadOnly(True)
        self.auto_log.setMaximumHeight(150)
        self.auto_log.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace; font-size: 9px;")
        self.auto_log.setVisible(False)
        layout.addWidget(self.auto_log)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.auto_start_btn = QPushButton("🚀 START AUTOMATION")
        self.auto_start_btn.setStyleSheet("background-color: #28A745; color: white; font-weight: bold; padding: 8px;")
        self.auto_start_btn.clicked.connect(self.start_automation_from_dialog)
        btn_layout.addWidget(self.auto_start_btn)
        
        self.auto_cancel_btn = QPushButton("❌ CLOSE")
        self.auto_cancel_btn.setStyleSheet("background-color: #6c757d; color: white; font-weight: bold; padding: 8px;")
        self.auto_cancel_btn.clicked.connect(self.automation_dialog.reject)
        btn_layout.addWidget(self.auto_cancel_btn)
        
        layout.addLayout(btn_layout)
        
        self.automation_dialog.exec()
    
    def add_auto_input_row(self, scroll_layout):
        """Add a new input row for Google Drive link or local folder"""
        if len(self.auto_input_rows) >= 50:
            QMessageBox.warning(self.automation_dialog, "Limit Reached", "Maximum 50 sources allowed!")
            return
        
        row_frame = QFrame()
        row_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 4px; padding: 8px;")
        row_layout = QHBoxLayout(row_frame)
        
        # Input field
        input_field = QLineEdit()
        input_field.setPlaceholderText("Paste Google Drive link OR click Browse to select local folder")
        row_layout.addWidget(input_field)
        
        # Browse button for local folder
        browse_btn = QPushButton("📁 Browse")
        browse_btn.setStyleSheet("background-color: #28A745; color: white; font-weight: bold; padding: 6px 12px;")
        browse_btn.clicked.connect(lambda: self.browse_local_folder(input_field))
        row_layout.addWidget(browse_btn)
        
        # Remove button
        remove_btn = QPushButton("❌")
        remove_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 6px 12px; max-width: 40px;")
        remove_btn.clicked.connect(lambda: self.remove_auto_input_row(row_frame))
        row_layout.addWidget(remove_btn)
        
        # Insert before stretch
        scroll_layout.insertWidget(scroll_layout.count() - 1, row_frame)
        self.auto_input_rows.append((row_frame, input_field))
    
    def browse_local_folder(self, input_field):
        """Browse and select a local folder"""
        folder = QFileDialog.getExistingDirectory(self.automation_dialog, "Select Folder with TRC files")
        if folder:
            input_field.setText(folder)
    
    def remove_auto_input_row(self, row_frame):
        """Remove an input row"""
        self.auto_input_rows = [(f, i) for f, i in self.auto_input_rows if f != row_frame]
        row_frame.deleteLater()
    
    def start_automation_from_dialog(self):
        """Start automation with multiple sources"""
        # Collect all sources
        sources = []
        for _, input_field in self.auto_input_rows:
            source = input_field.text().strip()
            if source:
                sources.append(source)
        
        if not sources:
            QMessageBox.warning(self.automation_dialog, "Error", "Please add at least one Google Drive link or local folder")
            return
        
        if self.automation_worker and self.automation_worker.isRunning():
            QMessageBox.warning(self.automation_dialog, "Error", "Automation already running")
            return
        
        self.auto_log.clear()
        self.auto_log.setVisible(True)
        self.auto_progress.setValue(0)
        self.auto_progress.setVisible(True)
        self.auto_start_btn.setEnabled(False)
        self.auto_cancel_btn.setText("❌ CANCEL")
        self.auto_cancel_btn.clicked.disconnect()
        self.auto_cancel_btn.clicked.connect(self.cancel_automation_from_dialog)
        
        self.logs_organised_complete = False
        self.tests_complete = False
        
        self.automation_worker = MultiSourceAutomationWorker(sources, self)
        self.automation_worker.log_signal.connect(self.append_auto_log)
        self.automation_worker.status_signal.connect(self.handle_automation_status)
        self.automation_worker.progress_signal.connect(self.auto_progress.setValue)
        self.automation_worker.finished_signal.connect(self.on_automation_finished_from_dialog)
        self.automation_worker.start()
    
    def cancel_automation_from_dialog(self):
        if self.automation_worker and self.automation_worker.isRunning():
            self.automation_worker.terminate()
            self.automation_worker.wait(2000)
            self.append_auto_log("🛑 Automation cancelled by user")
            self.on_automation_finished_from_dialog(False, "Cancelled by user")
    
    def on_automation_finished_from_dialog(self, success: bool, message: str):
        self.auto_start_btn.setEnabled(True)
        self.auto_cancel_btn.setText("❌ CLOSE")
        self.auto_cancel_btn.clicked.disconnect()
        self.auto_cancel_btn.clicked.connect(self.automation_dialog.reject)
        if success:
            self.append_auto_log(f"✅ {message}")
            self.auto_progress.setValue(100)
        else:
            self.append_auto_log(f"❌ {message}")
    
    def append_auto_log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.auto_log.append(f"[{timestamp}] {text}")
        scrollbar = self.auto_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def handle_automation_status(self, text: str):
        # Always append to auto log with a marker
        self.append_auto_log(f"📌 {text}")

        # Handle UI-specific tags: UI:<widget_name>:<state>
        if not text.startswith("UI:"):
            return
        try:
            _, widget_key, state = text.split(":", 2)
        except ValueError:
            return

        widget_map = {
            'make_btn': getattr(self, 'make_btn', None),
            'browse_btn': getattr(self, 'browse_btn', None),
            'run_all_btn': getattr(self, 'run_all_btn', None),
            'gen_excel_btn': getattr(self, 'gen_excel_btn', None),
            'dialog_select': getattr(self, 'browse_btn', None),
            'dialog_no': getattr(self, 'gen_excel_btn', None),
        }

        btn = widget_map.get(widget_key)
        if btn and state in ('start', 'done', 'failed'):
            if state == 'start':
                self.flash_button(btn, highlight_color='#ffd54f')
                # Trigger the actual GUI action when automation starts
                if widget_key == 'make_btn':
                    QTimer.singleShot(50, lambda: self.auto_click_make_organised())
                elif widget_key == 'browse_btn':
                    # If a file was already determined by the automation, select it
                    QTimer.singleShot(50, lambda: self._handle_file_selected(self.logs_last_output_path) if getattr(self, 'logs_last_output_path', None) else None)
                elif widget_key == 'dialog_select':
                    QTimer.singleShot(50, lambda: self.auto_browse_and_select_file(self.logs_last_output_path if getattr(self, 'logs_last_output_path', None) else ''))
                elif widget_key == 'run_all_btn':
                    QTimer.singleShot(50, lambda: self.auto_click_run_all())
                elif widget_key == 'gen_excel_btn':
                    QTimer.singleShot(50, lambda: self.auto_click_excel_tracker())
                elif widget_key == 'dialog_no':
                    QTimer.singleShot(50, lambda: self.auto_handle_excel_popup())
            elif state == 'done':
                self.flash_button(btn, highlight_color='#8bc34a')
            elif state == 'failed':
                self.flash_button(btn, highlight_color='#f44336')

    def flash_button(self, button: QPushButton, highlight_color: str = '#ffd54f', duration_ms: int = 800):
        if not button:
            return
        # save original stylesheet
        if not hasattr(self, '_orig_styles'):
            self._orig_styles = {}
        if button not in self._orig_styles:
            self._orig_styles[button] = button.styleSheet()

        # apply highlight
        button.setStyleSheet(f"background:{highlight_color}; color:black; font-weight:bold;")

        # restore after timeout
        QTimer.singleShot(duration_ms, lambda: button.setStyleSheet(self._orig_styles.get(button, '')))
    
    def auto_click_make_organised(self):
        self.logs_organised_complete = False
        self.on_make_logs()
    
    def auto_browse_and_select_file(self, file_path: str):
        self._handle_file_selected(file_path)
    
    def auto_click_run_all(self):
        self.tests_complete = False
        self.start_all_tests()
    
    def auto_click_excel_tracker(self):
        self.generate_excel_tracker()
    
    def auto_handle_excel_popup(self):
        """Handle the Excel popup by clicking NO"""
        # The popup is handled by the automation_in_progress flag in generate_excel_tracker
        time.sleep(1)  # Wait for dialog to appear

    # ======================================================
    # THEME MANAGEMENT
    # ======================================================
    def _open_after_settings(self, dialog: QDialog, callback):
        dialog.accept()
        QTimer.singleShot(60, callback)

    def on_settings_clicked(self):
        QTimer.singleShot(30, self.open_settings_panel)

    def open_settings_panel(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setModal(True)
        dialog.setMinimumSize(460, 330)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
            }
            QLabel {
                color: white;
                background: transparent;
            }
            QFrame#settingsHeader {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,
                    stop:0 #001F6B, stop:0.48 #D8002B, stop:1 #0033CC);
                border-radius: 6px;
            }
            QFrame#settingsBody {
                background-color: #f6f9fd;
                border: 1px solid #b6c4d8;
                border-radius: 6px;
            }
            QPushButton#settingsOption {
                background-color: #ffffff;
                color: #09214a;
                border: 1px solid #9fb3cf;
                border-left: 6px solid #2B8CE7;
                border-radius: 6px;
                padding: 12px 14px;
                font-weight: bold;
                text-align: left;
                min-height: 38px;
            }
            QPushButton#settingsOption:hover {
                background-color: #eaf4ff;
                border: 1px solid #2B8CE7;
                border-left: 6px solid #FF0000;
            }
            QPushButton#settingsOption:pressed {
                background-color: #d9ecff;
                padding-top: 14px;
                padding-bottom: 10px;
            }
            QPushButton#settingsClose {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 18px;
                font-weight: bold;
            }
            QPushButton#settingsClose:hover {
                background-color: #5a6268;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("settingsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("CAN LOG ANALYSER SETTINGS")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px; font-weight:bold;")
        subtitle = QLabel("Choose what you want to configure")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size:11px; color:#e8f7ff;")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        body = QFrame()
        body.setObjectName("settingsBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.setSpacing(10)

        theme_btn = QPushButton("🎨  Theme")
        theme_btn.setObjectName("settingsOption")
        theme_btn.clicked.connect(lambda: self._open_after_settings(dialog, self.open_theme_panel))
        body_layout.addWidget(theme_btn)

        sequence_btn = QPushButton("📋  Arrange Test Sequence")
        sequence_btn.setObjectName("settingsOption")
        sequence_btn.clicked.connect(lambda: self._open_after_settings(dialog, self.open_test_sequence_panel))
        body_layout.addWidget(sequence_btn)

        note = QLabel("Saved test sequence is used when creating the Excel tracker.")
        note.setStyleSheet("color:#3f536e; font-size:10px; padding:4px 2px;")
        body_layout.addWidget(note)

        layout.addWidget(body)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("settingsClose")
        close_btn.clicked.connect(dialog.reject)
        layout.addWidget(close_btn, 0, Qt.AlignRight)
        dialog.exec()

    def open_test_sequence_panel(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            items = self._load_excel_tracker_headers()
            if not items:
                QMessageBox.warning(self, "Test Sequence", "Could not read tracker sequence from Excel_Tracker.py")
                return
            dialog = TestSequenceDialog(items, self)
        finally:
            QApplication.restoreOverrideCursor()
        dialog.exec()

    def _load_excel_tracker_headers(self) -> List[str]:
        if self._excel_tracker_headers_cache is not None:
            return list(self._excel_tracker_headers_cache)
        tracker_path = os.path.join(self.script_dir, "Excel_Tracker.py")
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=tracker_path)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                    if "HEADERS" in names:
                        headers = ast.literal_eval(node.value)
                        self._excel_tracker_headers_cache = [str(item) for item in headers]
                        return list(self._excel_tracker_headers_cache)
        except Exception:
            return []
        return []

    def open_theme_panel(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dialog = ColorCustomizationPanel(self.theme, self)
        finally:
            QApplication.restoreOverrideCursor()
        dialog.exec()
    
    def apply_theme_colors(self):
        gradient = ("qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,"
                    f"stop:0 {self.theme.get('title_bg_start')}, "
                    f"stop:0.5 {self.theme.get('title_bg_mid')}, "
                    f"stop:1 {self.theme.get('title_bg_end')})")
        self.title_container.setStyleSheet(f"background:{gradient}; border:0px;")
        self.title_label.setStyleSheet(f"color:{self.theme.get('title_text')}; padding:10px; font-weight:bold; background:transparent;")
        self.version_label.setStyleSheet(f"color:{self.theme.get('version_text')}; padding:0 12px; font-weight:bold; background:transparent;")
        self.ft_label.setStyleSheet(f"background:{self.theme.get('ft_label_bg')}; color:white; padding:8px; font-weight:bold;")
        self.browse_btn.setStyleSheet(f"background:{self.theme.get('browse_btn_bg')}; color:white; font-weight:bold;")
        self.make_btn.setStyleSheet(f"background:{self.theme.get('make_btn_bg')}; color:white; font-weight:bold;")
        self.run_all_btn.setStyleSheet(f"background:{self.theme.get('run_all_btn_bg')}; color:white; font-weight:bold;")
        for lbl in self.bms_labels:
            lbl.setStyleSheet(f"background:{self.theme.get('bms_label_bg')}; color:white; padding:6px; font-weight:bold;")
        for lbl in self.stark_labels:
            lbl.setStyleSheet(f"background:{self.theme.get('stark_label_bg')}; color:white; padding:6px; font-weight:bold;")
        for lbl in self.xavier_labels:
            lbl.setStyleSheet(f"background:{self.theme.get('xavier_label_bg')}; color:white; padding:6px; font-weight:bold;")
        for lbl in self.distance_labels:
            lbl.setStyleSheet(f"background:{self.theme.get('distance_label_bg')}; color:white; padding:6px; font-weight:bold;")
        for lbl in self.mcu_labels:
            lbl.setStyleSheet(f"background:{self.theme.get('mcu_label_bg')}; color:white; padding:6px; font-weight:bold;")
        self.table_header.setStyleSheet(f"QHeaderView::section {{ background-color: {self.theme.get('table_header_bg')}; color: {self.theme.get('table_header_text')}; font-weight: bold; }}")
        for lbl in self.testcase_labels:
            lbl.setStyleSheet(f"color:{self.theme.get('testcase_text')}; font-weight:bold; background:white;")
        for btn in self.run_btns:
            btn.setStyleSheet(f"QPushButton {{ background:{self.theme.get('run_btn_bg')}; color:white; font-weight:bold; border-radius:12px; min-width:24px; max-width:24px; min-height:24px; max-height:24px; }} QPushButton:pressed {{ background:#1f7a33; }}")
        self.gen_btn.setStyleSheet(f"background:{self.theme.get('gen_btn_bg')}; color:{self.theme.get('gen_btn_text')}; padding:10px; font-weight:bold;")
        self.gen_excel_btn.setStyleSheet(f"background:{self.theme.get('gen_btn_bg')}; color:{self.theme.get('gen_btn_text')}; padding:10px; font-weight:bold;")
        if AUTOMATE_BUTTON_ENABLED:
            self.auto_btn.setStyleSheet(f"background:{self.theme.get('auto_btn_bg')}; color:white; font-weight:bold; padding:8px; border-radius:4px;")
            self.auto_btn.setToolTip("")
        else:
            self.auto_btn.setStyleSheet("background:#9aa3a8; color:white; font-weight:bold; padding:8px; border-radius:4px;")
            self.auto_btn.setToolTip("This feature is under development.")
        self.btn_vcu.setStyleSheet(f"QPushButton {{ background:{self.theme.get('vcu_btn_bg')}; color:white; font-weight:bold; border:1px solid #1f7a33; border-radius:4px; padding:6px; }} QPushButton:disabled {{ background:#28A745; color:white; border:1px solid #1f7a33; }}")
        self.btn_bms.setStyleSheet(f"QPushButton {{ background:{self.theme.get('bms_btn_bg')}; color:white; font-weight:bold; border:1px solid #1f7a33; border-radius:4px; padding:6px; }} QPushButton:disabled {{ background:#28A745; color:white; border:1px solid #1f7a33; }}")
        if self.running_rows:
            phase = self.title_anim_step / 100.0
            for row in list(self.running_rows):
                self._set_running_visual(row, phase)
        for row in self.pending_result_rows:
            self.update_result_cell(row)

    def _update_title_glow(self):
        if not getattr(self, "title_label", None):
            return
        self.title_anim_step = (self.title_anim_step + 1) % 100
        highlight = self.title_anim_step / 100.0
        start = max(0.0, highlight - 0.2)
        end = min(1.0, highlight + 0.2)
        gradient = ("qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,"
                    f"stop:0 {self.theme.get('title_bg_start')}, "
                    f"stop:{start:.2f} {self.theme.get('title_bg_mid')}, "
                    f"stop:{highlight:.2f} {self.theme.get('title_bg_end')}, "
                    f"stop:{end:.2f} {self.theme.get('title_bg_mid')}, "
                    f"stop:1 {self.theme.get('title_bg_start')})")
        if getattr(self, "title_container", None):
            self.title_container.setStyleSheet(f"background:{gradient}; border:0px;")
            self.title_label.setStyleSheet(f"color:{self.theme.get('title_text')}; padding:10px; font-weight:bold; background:transparent;")
            if getattr(self, "version_label", None):
                self.version_label.setStyleSheet(f"color:{self.theme.get('version_text')}; padding:0 12px; font-weight:bold; background:transparent;")
        if getattr(self, "make_btn_animating", False) and getattr(self, "make_btn", None):
            self.make_btn.setStyleSheet(f"color:white; font-weight:bold; padding:10px; background:{gradient};")
        if getattr(self, "run_all_animating", False) and getattr(self, "run_all_btn", None):
            run_gradient = ("qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,"
                           f"stop:0 #0A2F0A, stop:{start:.2f} #0F6B0F, stop:{highlight:.2f} #32CD32, "
                           f"stop:{end:.2f} #0F6B0F, stop:1 #0A2F0A)")
            self.run_all_btn.setStyleSheet(f"color:white; font-weight:bold; padding:10px; background:{run_gradient};")
        if getattr(self, "running_rows", None) and getattr(self, "test_table", None):
            phase = self.title_anim_step / 100.0
            for row in list(self.running_rows):
                self._set_running_visual(row, phase)

    def _read_version_text(self) -> str:
        version_file = os.path.join(self.script_dir, "version.txt")
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except FileNotFoundError:
            raw = ""
        except Exception:
            raw = ""
        raw = raw.lstrip("vV")
        return f"v{raw or '0.0.0'}"

    def _set_colored_cell(self, row: int, col: int, text: str, bg_color: str, align=Qt.AlignCenter, tooltip=None):
        item = QTableWidgetItem(text)
        item.setTextAlignment(align)
        item.setForeground(QColor("white"))
        item.setBackground(QColor(bg_color))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        if tooltip:
            item.setToolTip(tooltip)
        self.test_table.setItem(row, col, item)

    def _mark_row_running(self, row: int):
        self.running_rows.add(row)
        self.running_started_at[row] = time.time()
        self._set_colored_cell(row, 1, "Running", self.theme.get("running_bg"))

    def _set_running_visual(self, row: int, phase: float):
        item = self.test_table.item(row, 1)
        if not item:
            return
        pct = self.running_pct.get(row)
        if pct is not None:
            item.setText(f"Running {pct:.1f}%")
        else:
            item.setText("Running")
        base = QColor(self.theme.get("running_bg"))
        shine = QColor(self.theme.get("running_shine"))
        pos = phase % 1.0
        band = 0.18
        eased = 0.5 * (1 + math.sin(2 * math.pi * pos))
        center = eased
        g = QLinearGradient(0, 0, 1, 0)
        g.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
        g.setColorAt(0.0, base)
        g.setColorAt(max(0.0, center - band), base)
        g.setColorAt(center, shine)
        g.setColorAt(min(1.0, center + band), base)
        g.setColorAt(1.0, base)
        item.setBackground(QBrush(g))
        item.setForeground(QColor("white"))
        font = item.font()
        font.setBold(True)
        item.setFont(font)

    def _ensure_result_timer_running(self):
        if self.pending_result_rows:
            if not self.result_refresh_timer.isActive():
                self.result_refresh_timer.start()
        elif self.result_refresh_timer.isActive():
            self.result_refresh_timer.stop()

    def _maybe_finish_run_all(self):
        if not self.processes:
            return
        if any(p.state() != QProcess.NotRunning for p in self.processes.values()):
            return
        if self.pending_result_rows:
            return
        self.run_all_btn.setEnabled(True)
        self.run_all_btn.setText("RUN ALL TEST CASES")
        self.run_all_btn.setStyleSheet(f"background:{self.theme.get('run_all_btn_bg')}; color:white; font-weight:bold;")
        self.run_all_animating = False
        self.tests_complete = True

    def _refresh_pending_results(self):
        if not self.pending_result_rows:
            self._ensure_result_timer_running()
            return
        for row in list(self.pending_result_rows):
            self.update_result_cell(row)
        self._ensure_result_timer_running()

    def _get_test_script_paths(self, row: int):
        script_name = SCRIPT_BY_ROW.get(row)
        if not script_name:
            return None, None
        folder_name = os.path.splitext(script_name)[0]
        folder_path = os.path.join(self.tests_folder, folder_name)
        script_path = os.path.join(folder_path, script_name)
        if not os.path.exists(script_path):
            fallback_folder = os.path.join(self.default_tests_folder, folder_name)
            fallback_script = os.path.join(fallback_folder, script_name)
            if os.path.exists(fallback_script):
                return fallback_folder, fallback_script
        return folder_path, script_path

    def _tests_folder_for_extension(self, ext: str) -> str:
        ext = (ext or "").lower()
        return self.tests_folder_overrides.get(ext, self.default_tests_folder)

    def _set_tests_folder_for_extension(self, ext: str):
        new_folder = self._tests_folder_for_extension(ext)
        if new_folder != self.tests_folder:
            self.tests_folder = new_folder
            self.output_files = self._load_output_config()

    def _load_output_config(self) -> Dict[int, Dict[str, str]]:
        config_path = os.path.join(self.tests_folder, "file_name.json")
        config_data: Dict[str, Dict[str, str]] = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    raw = json.load(f)
                config_data = {k.lower(): v for k, v in raw.items() if isinstance(v, dict)}
            except Exception:
                config_data = {}
        output_by_row: Dict[int, Dict[str, str]] = {}
        for row, script_name in SCRIPT_BY_ROW.items():
            test_name = TEST_CASES[row].lower()
            entry = config_data.get(test_name, {})
            defaults = self._default_output_names(script_name)
            output_by_row[row] = {
                "result": entry.get("result", defaults["result"]),
                "summary": entry.get("summary", defaults["summary"]),
                "graph": entry.get("graph", defaults["graph"]),
            }
        return output_by_row

    def _default_output_names(self, script_name: str) -> Dict[str, str]:
        base = os.path.splitext(script_name)[0]
        return {
            "result": f"{base}_results.json",
            "summary": f"{base}_summary.json",
            "graph": f"{base}_plot.png",
        }

    def _get_output_file_path(self, row: int, kind: str) -> Optional[str]:
        folder_path, _ = self._get_test_script_paths(row)
        if not folder_path:
            return None
        file_name = self.output_files.get(row, {}).get(kind)
        if not file_name:
            return None
        return os.path.join(folder_path, file_name)

    def _get_result_file_path(self, row: int):
        return self._get_output_file_path(row, "result")

    def _clear_all_outputs(self):
        for row, files in self.output_files.items():
            for kind in ("result", "summary", "graph"):
                path = self._get_output_file_path(row, kind)
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    def _clear_outputs_for_row(self, row: int):
        files = self.output_files.get(row, {})
        for kind in ("result", "summary", "graph"):
            path = self._get_output_file_path(row, kind)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def on_make_logs(self):
        logs_script = os.path.join(self.script_dir, "logs_organised.py")
        if not os.path.exists(logs_script):
            QMessageBox.warning(self, "Error", f"logs_organised.py not found:\n{logs_script}")
            return
        self.logs_last_output_path = None
        self.make_btn.setText("RUNNING....Pls Wait")
        self.make_btn_animating = True
        self._update_title_glow()
        self.make_btn.setEnabled(False)
        home = os.path.expanduser("~")
        initial_dir = ""
        candidates = [os.path.join(home, "Downloads"), os.path.join(home, "Desktop")]
        for d in candidates:
            if os.path.isdir(d):
                initial_dir = d
                break
        if not initial_dir:
            if os.path.isdir(home):
                initial_dir = home
            else:
                initial_dir = "C:/"
        self.logs_proc = QProcess(self)
        self.logs_proc.setWorkingDirectory(self.script_dir)
        self.logs_proc.finished.connect(self.on_logs_finished)
        self.logs_proc.readyReadStandardOutput.connect(self._on_logs_stdout)
        self.logs_proc.start(sys.executable, [logs_script, initial_dir])

    def on_logs_finished(self):
        self.make_btn_animating = False
        self.make_btn.setText("LOGS ARE ORGANISED ✅, RETRY ?")
        self.make_btn.setStyleSheet(f"background-color: {self.theme.get('completed_bg')}; color: white; font-weight: bold;")
        self.make_btn.setEnabled(True)
        if not self.logs_last_output_path:
            marker = os.path.join(self.script_dir, "last_merged_trc.txt")
            if os.path.exists(marker):
                try:
                    candidate = open(marker, "r", encoding="utf-8", errors="ignore").read().strip()
                except Exception:
                    candidate = ""
                if candidate and os.path.exists(candidate):
                    self.logs_last_output_path = candidate
        self.logs_organised_complete = True

    def _on_logs_stdout(self):
        proc = getattr(self, "logs_proc", None)
        if not proc:
            return
        try:
            data = proc.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        except Exception:
            return
        for line in data.splitlines():
            m = re.search(r"Output file saved as:\s*(.+)", line)
            if m:
                candidate = m.group(1).strip()
                if candidate:
                    self.logs_last_output_path = candidate

    def _register_scan_task(self):
        self.scan_tasks += 1

    def _on_scan_finished(self):
        self.scan_tasks = max(0, self.scan_tasks - 1)
        if self.scan_tasks == 0:
            self.restore_browse_button()

    def _handle_file_selected(self, path: str):
        if not path:
            return
        file_ext = os.path.splitext(path)[1].lower()
        self._set_tests_folder_for_extension(file_ext)
        self.selected_file_path = path
        self.file_box.setText(path)
        self.run_all_btn.setEnabled(True)
        self.scan_tasks = 0
        self.browse_btn.setEnabled(False)
        self.browse_btn.setText("Scanning...")
        self._start_fw_scan(path)
        if file_ext == ".trc":
            self._start_mcu_detection(path)
            self._start_vcu_reset_check(path, track_scan=True)
            self._start_bms_reset_check(path, track_scan=True)
        else:
            self.reset_vcu_fields()
            self.reset_bms_fields()
            self.tx_mcu.setText("N/A")
            self.tx_serial.setText("N/A")
            self.tx_os.setText("N/A")

    def on_browse(self):
        ft = self.ft_combo.currentText()
        initial_dir = ""
        if self.logs_last_output_path:
            initial_dir = os.path.dirname(self.logs_last_output_path)
        elif self.selected_file_path:
            initial_dir = os.path.dirname(self.selected_file_path)
        else:
            home = os.path.expanduser("~")
            candidates = [os.path.join(home, "Downloads"), os.path.join(home, "Desktop"), home]
            for d in candidates:
                if os.path.isdir(d):
                    initial_dir = d
                    break
        path, _ = QFileDialog.getOpenFileName(self, "Select File", initial_dir, f"{ft} Files (*{ft})")
        if not path:
            return
        self._handle_file_selected(path)

    def _start_fw_scan(self, path: str):
        thread = FWCheckerThread(path)
        self.fw_thread = thread
        self._register_scan_task()
        thread.finished_ok.connect(self.update_fw_info)
        thread.finished_err.connect(self.on_fw_error)
        thread.finished.connect(self._on_scan_finished)
        thread.start()

    def _start_mcu_detection(self, path: str):
        self.tx_mcu.setText("...")
        self.tx_serial.setText("...")
        self.tx_os.setText("...")
        thread = MCUDetectionThread(path, self.script_dir)
        self.mcu_thread = thread
        self._register_scan_task()
        thread.finished_ok.connect(self.update_mcu_fields)
        thread.finished_err.connect(self.on_mcu_error)
        thread.finished.connect(self._on_scan_finished)
        thread.start()

    def update_mcu_fields(self, info: dict):
        self.tx_mcu.setText(info.get("platform", "N/A"))
        self.tx_serial.setText(info.get("serial", "N/A"))
        self.tx_os.setText(f"{info.get('os_version', 'N/A')} & {info.get('os_build', 'N/A')}")

    def on_mcu_error(self, msg: str):
        self.tx_mcu.setText("N/A")
        self.tx_serial.setText("N/A")
        self.tx_os.setText("N/A")

    def _start_vcu_reset_check(self, path: str, track_scan: bool):
        if not os.path.exists(self.vcu_reset_script):
            self.reset_vcu_fields()
            QMessageBox.warning(self, "Error", f"VCU reset script not found:\n{self.vcu_reset_script}")
            return
        self.btn_vcu.setEnabled(False)
        self.tx_vcu_value.setText("Count : ...")
        self.tx_vcu_result.setText("...")
        self._style_vcu_fields(None)
        thread = VCUResetThread(path, self.vcu_reset_script, self.vcu_reset_output)
        if track_scan:
            self._register_scan_task()
        thread.finished_ok.connect(self.update_vcu_reset_fields)
        thread.finished_err.connect(self.on_vcu_reset_error)
        thread.finished.connect(lambda: self._on_vcu_reset_finished(track_scan))
        thread.start()
        self.vcu_thread = thread

    def _on_vcu_reset_finished(self, track_scan: bool):
        self.btn_vcu.setEnabled(False)
        if track_scan:
            self._on_scan_finished()

    def _start_bms_reset_check(self, path: str, track_scan: bool, manual: bool = False):
        if not path:
            if manual:
                QMessageBox.warning(self, "Error", "No file loaded!")
            self.reset_bms_fields()
            return
        if not os.path.exists(self.bms_reset_script):
            self.reset_bms_fields()
            QMessageBox.warning(self, "Error", f"BMS reset script not found:\n{self.bms_reset_script}")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext != ".trc":
            self.reset_bms_fields()
            if manual:
                QMessageBox.warning(self, "Error", "BMS reset check only runs on .trc files.")
            return
        self.btn_bms.setEnabled(False)
        self.tx_bms_value.setText("Count : ...")
        self.tx_bms_result.setText("...")
        self._style_bms_fields(None)
        thread = BMSResetThread(path, self.bms_reset_script, self.bms_reset_output)
        if track_scan:
            self._register_scan_task()
        thread.finished_ok.connect(self.update_bms_reset_fields)
        thread.finished_err.connect(self.on_bms_reset_error)
        thread.finished.connect(lambda: self._on_bms_reset_finished(track_scan))
        thread.start()
        self.bms_thread = thread

    def _on_bms_reset_finished(self, track_scan: bool):
        self.btn_bms.setEnabled(False)
        if track_scan:
            self._on_scan_finished()

    def restore_browse_button(self):
        if getattr(self, "scan_tasks", 0) > 0:
            return
        self.browse_btn.setEnabled(True)
        self.browse_btn.setText("Browse File")

    def update_fw_info(self, info):
        self.tx_hw.setText(info.get("BMS_HW", ""))
        self.tx_fw.setText(info.get("BMS_FIRMWARE", ""))
        self.tx_cfg.setText(info.get("BMS_CONFIG_ID", ""))
        self.tx_git.setText(info.get("BMS_GITSHA", ""))
        self.tx_manifest.setText(info.get("BMS_MANIFEST", ""))
        self.tx_stark_fw.setText(info.get("STARK_FIRMWARE", ""))
        self.tx_stark_cfg.setText(info.get("STARK_CONFIG", ""))
        self.tx_xavier_fw.setText(info.get("XAVIER_FIRMWARE", ""))
        def _fmt_dist(val):
            if val is None:
                return ""
            try:
                return f"{float(val):.1f} km"
            except Exception:
                return f"{val} km" if val else ""
        dist_val = info.get("DISTANCE_COVERED_KM", info.get("DISTANCE_COVERED", ""))
        self.tx_distance.setText(_fmt_dist(dist_val))

    def update_vcu_reset_fields(self, data: dict):
        count = data.get("Reset_Count", 0)
        result_raw = str(data.get("Result", "")).strip().upper()
        result = result_raw or ("PASS" if count == 0 else "FAIL")
        tooltip = f"Read from {self.vcu_reset_output}"
        self.tx_vcu_value.setToolTip(tooltip)
        self.tx_vcu_result.setToolTip(tooltip)
        self.tx_vcu_value.setText(f"Count : {count}")
        self.tx_vcu_result.setText(result)
        self.tx_vcu_value.setAlignment(Qt.AlignCenter)
        self.tx_vcu_result.setAlignment(Qt.AlignCenter)
        self._style_vcu_fields(result)

    def on_vcu_reset_error(self, msg: str):
        self.reset_vcu_fields()
        QMessageBox.warning(self, "VCU Reset Error", msg)

    def update_bms_reset_fields(self, data: dict):
        count = data.get("Reset_Count", 0)
        result_raw = str(data.get("Result", "")).strip().upper()
        result = result_raw or ("PASS" if count == 0 else "FAIL")
        tooltip = f"Read from {self.bms_reset_output}"
        self.tx_bms_value.setToolTip(tooltip)
        self.tx_bms_result.setToolTip(tooltip)
        self.tx_bms_value.setText(f"Count : {count}")
        self.tx_bms_result.setText(result)
        self.tx_bms_value.setAlignment(Qt.AlignCenter)
        self.tx_bms_result.setAlignment(Qt.AlignCenter)
        self._style_bms_fields(result)

    def on_bms_reset_error(self, msg: str):
        self.reset_bms_fields()
        QMessageBox.warning(self, "BMS Reset Error", msg)

    def reset_vcu_fields(self):
        self.tx_vcu_value.setText("Count : N/A")
        self.tx_vcu_result.setText("N/A")
        self.tx_vcu_value.setToolTip("")
        self.tx_vcu_result.setToolTip("")
        self.tx_vcu_value.setAlignment(Qt.AlignCenter)
        self.tx_vcu_result.setAlignment(Qt.AlignCenter)
        self._style_vcu_fields(None)

    def reset_bms_fields(self):
        self.tx_bms_value.setText("Count : N/A")
        self.tx_bms_result.setText("N/A")
        self.tx_bms_value.setToolTip("")
        self.tx_bms_result.setToolTip("")
        self.tx_bms_value.setAlignment(Qt.AlignCenter)
        self.tx_bms_result.setAlignment(Qt.AlignCenter)
        self._style_bms_fields(None)

    def _style_vcu_fields(self, result: Optional[str]):
        def apply_style(widget: QLineEdit, default_palette: QPalette, bg: str, fg: str):
            if not bg:
                widget.setPalette(default_palette)
                widget.setStyleSheet("")
                widget.setAlignment(Qt.AlignCenter)
                return
            pal = QPalette(default_palette)
            pal.setColor(QPalette.Base, QColor(bg))
            pal.setColor(QPalette.Text, QColor(fg))
            widget.setPalette(pal)
            widget.setStyleSheet(f"QLineEdit {{ background:{bg}; color:{fg}; font-weight:bold; }}")
            widget.setAlignment(Qt.AlignCenter)
        if result == "PASS":
            bg, fg = self.theme.get("pass_bg"), "white"
        elif result == "FAIL":
            bg, fg = self.theme.get("fail_bg"), "white"
        else:
            bg, fg = "", ""
        apply_style(self.tx_vcu_value, self.vcu_value_palette_default, bg, fg)
        apply_style(self.tx_vcu_result, self.vcu_result_palette_default, bg, fg)

    def _style_bms_fields(self, result: Optional[str]):
        def apply_style(widget: QLineEdit, default_palette: QPalette, bg: str, fg: str):
            if not bg:
                widget.setPalette(default_palette)
                widget.setStyleSheet("")
                widget.setAlignment(Qt.AlignCenter)
                return
            pal = QPalette(default_palette)
            pal.setColor(QPalette.Base, QColor(bg))
            pal.setColor(QPalette.Text, QColor(fg))
            widget.setPalette(pal)
            widget.setStyleSheet(f"QLineEdit {{ background:{bg}; color:{fg}; font-weight:bold; }}")
            widget.setAlignment(Qt.AlignCenter)
        if result == "PASS":
            bg, fg = self.theme.get("pass_bg"), "white"
        elif result == "FAIL":
            bg, fg = self.theme.get("fail_bg"), "white"
        else:
            bg, fg = "", ""
        apply_style(self.tx_bms_value, self.bms_value_palette_default, bg, fg)
        apply_style(self.tx_bms_result, self.bms_result_palette_default, bg, fg)

    def on_fw_error(self, err):
        QMessageBox.warning(self, "FW Error", err)

    def start_all_tests(self):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "Browse a file first")
            return
        if any(p.state() != QProcess.NotRunning for p in self.processes.values()):
            QMessageBox.information(self, "Info", "Some tests are already running. Please wait for them to finish before running all.")
            return
        if CLEAR_OUTPUTS_ON_RUN_ALL:
            self._clear_all_outputs()
        self.run_all_btn.setEnabled(False)
        self.run_all_btn.setText("RUNNING... Pls Wait")
        self.run_all_animating = True
        self._update_title_glow()
        self.pending_result_rows.clear()
        self._ensure_result_timer_running()
        for i in range(len(TEST_CASES)):
            status_item = QTableWidgetItem("Not Run")
            status_item.setTextAlignment(Qt.AlignCenter)
            self.test_table.setItem(i, 1, status_item)
            result_item = QTableWidgetItem("N/A")
            result_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.test_table.setItem(i, 4, result_item)
        self.processes.clear()
        python = sys.executable
        self.running_rows.clear()
        self.running_started_at.clear()
        self.running_pct.clear()
        for row, script in SCRIPT_BY_ROW.items():
            folder_path, script_path = self._get_test_script_paths(row)
            if not folder_path or not os.path.exists(script_path):
                self._set_colored_cell(row, 1, "Missing/Incorrect", self.theme.get("error_bg"))
                continue
            self.pending_result_rows.add(row)
            self._ensure_result_timer_running()
            self._mark_row_running(row)
            proc = QProcess(self)
            proc.setWorkingDirectory(folder_path)
            proc.finished.connect(lambda exitCode, _status, r=row: self.on_test_finished(r, exitCode))
            proc.errorOccurred.connect(lambda _e, r=row: self.on_test_error(r))
            proc.readyReadStandardOutput.connect(lambda r=row: self._on_test_stdout(r))
            proc.start(python, [script, self.selected_file_path])
            self.processes[row] = proc
        if not self.processes:
            self.run_all_btn.setEnabled(True)
            self.run_all_btn.setText("RUN ALL TEST CASES")
            self.run_all_btn.setStyleSheet(f"background:{self.theme.get('run_all_btn_bg')}; color:white; font-weight:bold;")
            self.run_all_animating = False

    def start_single_test(self, row: int):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "Browse a file first")
            return
        proc = self.processes.get(row)
        if proc and proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Info", "This test is already running.")
            return
        if CLEAR_OUTPUTS_ON_RUN_ALL:
            self._clear_outputs_for_row(row)
        status_item = QTableWidgetItem("Not Run")
        status_item.setTextAlignment(Qt.AlignCenter)
        self.test_table.setItem(row, 1, status_item)
        result_item = QTableWidgetItem("N/A")
        result_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.test_table.setItem(row, 4, result_item)
        folder_path, script_path = self._get_test_script_paths(row)
        if not folder_path or not os.path.exists(script_path):
            self._set_colored_cell(row, 1, "Missing/Incorrect", self.theme.get("error_bg"))
            return
        python = sys.executable
        self.pending_result_rows.add(row)
        self._ensure_result_timer_running()
        self.running_rows.discard(row)
        self.running_started_at.pop(row, None)
        self.running_pct.pop(row, None)
        self._mark_row_running(row)
        proc = QProcess(self)
        proc.setWorkingDirectory(folder_path)
        proc.finished.connect(lambda exitCode, _status, r=row: self.on_test_finished(r, exitCode))
        proc.errorOccurred.connect(lambda _e, r=row: self.on_test_error(r, _e))
        proc.readyReadStandardOutput.connect(lambda r=row: self._on_test_stdout(r))
        proc.start(python, [script_path, self.selected_file_path])
        self.processes[row] = proc

    def on_test_finished(self, row, exitCode):
        self.running_rows.discard(row)
        self.running_started_at.pop(row, None)
        self.running_pct.pop(row, None)
        if exitCode == 0:
            self._set_colored_cell(row, 1, "Completed", self.theme.get("completed_bg"))
            if not self.update_result_cell(row):
                self._schedule_result_update(row)
        else:
            self._set_colored_cell(row, 1, "Missing/Incorrect", self.theme.get("error_bg"))
            if not self.update_result_cell(row):
                self._schedule_result_update(row)
        self._maybe_finish_run_all()

    def on_test_error(self, row, _):
        self.running_rows.discard(row)
        self.running_started_at.pop(row, None)
        self.running_pct.pop(row, None)
        self._set_colored_cell(row, 1, "Missing/Incorrect", self.theme.get("error_bg"))
        self._maybe_finish_run_all()

    def _on_test_stdout(self, row: int):
        proc = self.processes.get(row)
        if not proc:
            return
        try:
            data = proc.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        except Exception:
            return
        for line in data.splitlines():
            if not line.startswith("PROGRESS"):
                continue
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            try:
                pct = float(parts[1])
            except Exception:
                continue
            pct = max(0.0, min(99.9, pct))
            prev = self.running_pct.get(row, 0.0)
            if pct >= prev:
                self.running_pct[row] = pct
        if row in self.running_pct:
            self._set_running_visual(row, getattr(self, "title_anim_step", 0) / 100.0)

    def _mark_result_missing(self, row: int, reason: Optional[str] = None):
        if self.update_result_cell(row):
            return
        if reason is None:
            result_path = self._get_result_file_path(row)
            if result_path:
                reason = f"{os.path.basename(result_path)} not found after waiting."
            else:
                reason = "Result JSON not configured for this test."
        item = QTableWidgetItem("N/A")
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        item.setToolTip(reason)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.test_table.setItem(row, 4, item)
        if row in self.pending_result_rows:
            self.pending_result_rows.discard(row)
        self._ensure_result_timer_running()
        self._maybe_finish_run_all()

    def update_result_cell(self, row: int) -> bool:
        results_path = self._get_result_file_path(row)
        if not results_path:
            return False
        if not os.path.exists(results_path):
            return False
        try:
            with open(results_path, "r") as f:
                data = json.load(f)
            result_str = str(data.get("Result", "")).strip().upper()
        except Exception:
            return False
        tooltip = f"Read from {os.path.basename(results_path)}"
        success = False
        if result_str == "PASS":
            self._set_colored_cell(row, 4, "PASS", self.theme.get("pass_bg"), align=Qt.AlignLeft | Qt.AlignVCenter, tooltip=tooltip)
            success = True
        elif result_str == "FAIL":
            self._set_colored_cell(row, 4, "FAIL", self.theme.get("fail_bg"), align=Qt.AlignLeft | Qt.AlignVCenter, tooltip=tooltip)
            success = True
        elif result_str == "WARNING":
            self._set_colored_cell(row, 4, "WARNING", self.theme.get("warning_bg"), align=Qt.AlignLeft | Qt.AlignVCenter, tooltip=tooltip)
            success = True
        if success:
            status_item = self.test_table.item(row, 1)
            current_status = (status_item.text() if status_item else "").strip().lower()
            if current_status != "completed":
                self._set_colored_cell(row, 1, "Completed", self.theme.get("completed_bg"))
            if row in self.pending_result_rows:
                self.pending_result_rows.discard(row)
                self._ensure_result_timer_running()
            self._maybe_finish_run_all()
        return success

    def _schedule_result_update(self, row: int, attempts: int = RESULT_POLL_ATTEMPTS, delay_ms: int = RESULT_POLL_DELAY_MS):
        if attempts <= 0:
            self._mark_result_missing(row)
            return
        QTimer.singleShot(delay_ms, lambda r=row, a=attempts - 1, d=delay_ms: self._retry_result_update(r, a, d))

    def _retry_result_update(self, row: int, attempts: int, delay_ms: int):
        if self.update_result_cell(row):
            return
        if attempts <= 0:
            self._mark_result_missing(row)
        else:
            self._schedule_result_update(row, attempts, delay_ms)

    def on_view_results(self, idx):
        self.update_result_cell(idx)
        summary_path = self._get_output_file_path(idx, "summary")
        if not summary_path:
            QMessageBox.information(self, "Info", "No summary file configured for this test.")
            return
        dlg = JsonDialog(summary_path, self)
        dlg.exec()

    def on_view_graph(self, idx):
        graph_path = self._get_output_file_path(idx, "graph")
        if not graph_path:
            QMessageBox.information(self, "Info", "No graph configured for this test.")
            return
        if not os.path.exists(graph_path):
            QMessageBox.information(self, "Info", f"File not found:\n{graph_path}")
            return
        candidate_viewers = [r"C:\Program Files (x86)\Microsoft Office\Office12\OIS.EXE", r"C:\Program Files\Microsoft Office\Office12\OIS.EXE"]
        for viewer in candidate_viewers:
            if os.path.exists(viewer):
                try:
                    subprocess.Popen([viewer, graph_path])
                    return
                except Exception:
                    pass
        try:
            os.startfile(graph_path)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open graph:\n{e}")

    def generate_tracker(self):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "No file selected!")
            return
        docx_path = os.path.join(self.script_dir, "tracker_summary.docx")
        generator_script = os.path.join(self.script_dir, "Generate_Tracker.py")
        meta_payload = {
            "VEHICLE NAME": os.path.basename(self.selected_file_path),
            "BMS HW VERSION": self.tx_hw.text(),
            "BMS FIRMWARE": self.tx_fw.text(),
            "BMS CONFIG ID": self.tx_cfg.text(),
            "BMS GITSHA": self.tx_git.text(),
            "BMS MANIFEST": self.tx_manifest.text(),
            "STARK FIRMWARE": self.tx_stark_fw.text(),
            "STARK CONFIG": self.tx_stark_cfg.text(),
            "XAVIER FIRMWARE": self.tx_xavier_fw.text(),
            "DISTANCE COVERED": self.tx_distance.text(),
            "VCU Reset Count": self.tx_vcu_value.text(),
            "VCU Reset Result": self.tx_vcu_result.text(),
            "BMS Reset Count": self.tx_bms_value.text(),
            "BMS Reset Result": self.tx_bms_result.text(),
        }
        if not os.path.exists(generator_script):
            QMessageBox.warning(self, "Tracker", f"Generate_Tracker.py not found:\n{generator_script}")
            return
        try:
            env = os.environ.copy()
            env["META_JSON"] = json.dumps(meta_payload)
            env["SELECTED_FILE_NAME"] = os.path.basename(self.selected_file_path)
            proc = subprocess.run([sys.executable, generator_script, docx_path, self.tests_folder], cwd=self.script_dir, capture_output=True, text=True, env=env)
        except Exception as e:
            QMessageBox.warning(self, "Tracker", f"Failed to start tracker script:\n{e}")
            return
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Tracker script returned an error."
            QMessageBox.warning(self, "Tracker", err_msg)
            return
        reply = QMessageBox.question(self, "Tracker", f"Tracker generated:\n{docx_path}\n\nDo you want to open this report?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(docx_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", docx_path])
                else:
                    subprocess.Popen(["xdg-open", docx_path])
            except Exception as e:
                QMessageBox.warning(self, "Tracker", f"Failed to open report:\n{e}")

    def generate_excel_tracker(self):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "No file selected!")
            return
        excel_path = os.path.join(self.script_dir, "TRACKER.xlsx")
        generator_script = os.path.join(self.script_dir, "Excel_Tracker.py")
        meta_payload = {
            "VEHICLE NAME": os.path.basename(self.selected_file_path),
            "BMS HW VERSION": self.tx_hw.text(),
            "BMS FIRMWARE": self.tx_fw.text(),
            "BMS CONFIG ID": self.tx_cfg.text(),
            "BMS GITSHA": self.tx_git.text(),
            "BMS MANIFEST": self.tx_manifest.text(),
            "STARK FIRMWARE": self.tx_stark_fw.text(),
            "STARK CONFIG": self.tx_stark_cfg.text(),
            "XAVIER FIRMWARE": self.tx_xavier_fw.text(),
            "DISTANCE COVERED": self.tx_distance.text(),
            "VCU Reset Count": self.tx_vcu_value.text(),
            "VCU Reset Result": self.tx_vcu_result.text(),
            "BMS Reset Count": self.tx_bms_value.text(),
            "BMS Reset Result": self.tx_bms_result.text(),
        }
        if not os.path.exists(generator_script):
            QMessageBox.warning(self, "Excel Tracker", f"Excel_Tracker.py not found:\n{generator_script}")
            return
        try:
            env = os.environ.copy()
            env["META_JSON"] = json.dumps(meta_payload)
            env["SELECTED_FILE_NAME"] = os.path.basename(self.selected_file_path)
            proc = subprocess.run([sys.executable, generator_script, excel_path, self.tests_folder], cwd=self.script_dir, capture_output=True, text=True, env=env)
        except Exception as e:
            QMessageBox.warning(self, "Excel Tracker", f"Failed to start script:\n{e}")
            return
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Excel tracker script returned an error."
            QMessageBox.warning(self, "Excel Tracker", err_msg)
            return
        
        # If automation is in progress, skip the popup and just click NO
        if getattr(self, 'automation_in_progress', False):
            return
        
        # Normal popup behavior
        reply = QMessageBox.question(self, "Excel Tracker", f"Excel tracker generated:\n{excel_path}\n\nDo you want to open this file?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(excel_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", excel_path])
                else:
                    subprocess.Popen(["xdg-open", excel_path])
            except Exception as e:
                QMessageBox.warning(self, "Excel Tracker", f"Failed to open file:\n{e}")


def send_heartbeat():
    try:
        requests.post("https://heartbeat-server-1z5n.onrender.com/heartbeat", json={"device": socket.gethostname(), "name": os.getlogin(), "status": "running"}, timeout=2)
    except:
        pass


def check_kill_switch():
    url = "https://raw.githubusercontent.com/itssatishkumar/Runner/main/runner.txt"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            value = response.read().decode().strip().upper()
            return value == "TRUE"
    except Exception:
        return False


def run_updater_first(app: QApplication):
    version_file = os.path.join(os.path.dirname(__file__), "version.txt")
    try:
        with open(version_file, "r") as f:
            local_version = f.read().strip() or "1.0.0"
    except FileNotFoundError:
        local_version = "1.0.0"
    except Exception:
        local_version = "1.0.0"
    check_for_update(local_version=local_version, app=app)


def main():
    if check_kill_switch():
        runner_path = os.path.join(os.path.dirname(__file__), "runner.py")
        if os.path.exists(runner_path):
            subprocess.Popen([sys.executable, runner_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
        time.sleep(2)
        sys.exit(0)
    app = QApplication(sys.argv)
    run_updater_first(app)
    w = CANLogDebugger()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
