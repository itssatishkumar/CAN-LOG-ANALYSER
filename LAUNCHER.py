
import sys
import sys
import os
import subprocess
import json
import csv
import math
import time
import re
from typing import Dict, Optional, Set

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QComboBox,
    QFileDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QMessageBox,
    QGridLayout, QTableWidget, QTableWidgetItem, QFrame, QDialog,
    QTextEdit, QHeaderView, QAbstractItemView
)
from PySide6.QtGui import QFont, QPixmap, QColor, QLinearGradient, QBrush, QPalette
from PySide6.QtCore import Qt, QThread, Signal, QProcess, QTimer
from updater import check_for_update


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
CLEAR_OUTPUTS_ON_RUN_ALL = True  # set to False to keep previous outputs

# row -> script filename (inside a folder of the same base name)
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

def _default_output_names(script_name: str) -> Dict[str, str]:
    base = os.path.splitext(script_name)[0]
    return {
        "result": f"{base}_results.json",
        "summary": f"{base}_summary.json",
        "graph": f"{base}_plot.png",
    }

# Allow scripts ~4.5 seconds (9 * 0.5s) to persist their JSON outputs
RESULT_POLL_ATTEMPTS = 9
RESULT_POLL_DELAY_MS = 500

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
            proc = subprocess.Popen(
                [sys.executable, FW_CHECKER, self.trc_file],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
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
            proc = subprocess.Popen(
                [sys.executable, self.script_path, self.trc_file, self.output_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(self.script_path),
            )
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
            proc = subprocess.Popen(
                [sys.executable, self.script_path, self.trc_file, self.output_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(self.script_path),
            )
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
# MAIN GUI
# -------------------------------------------------------
class CANLogDebugger(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAN LOG ANALYSER")
        self.setMinimumSize(1250, 780)

        self.selected_file_path = ""
        self.logs_last_output_path: Optional[str] = None
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.default_tests_folder = os.path.join(self.script_dir, "TRC TEST CASES")
        self.tests_folder_overrides = {
            ".csv": os.path.join(self.script_dir, "CSV TEST CASES"),
        }
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

        # ---------------- TITLE ----------------
        self.version_label = QLabel(self._read_version_text())
        self.version_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.version_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.version_label.setStyleSheet("color:white; padding:0 12px; background:transparent;")
        self.version_label.setToolTip("Read from version.txt")

        title = QLabel("CAN LOG ANALYSER")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color:#00FFFF; padding:10px; font-weight:bold; background:transparent;")

        title_bar = QFrame()
        title_bar_layout = QHBoxLayout()
        title_bar_layout.setContentsMargins(10, 6, 10, 6)
        title_bar_layout.setSpacing(10)
        title_bar_layout.addWidget(self.version_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        title_bar_layout.addWidget(title, 1, Qt.AlignCenter)
        title_bar.setLayout(title_bar_layout)

        self._init_title_animation(title, title_bar)

        # ---------------------------------------------------
        # LEFT PANEL
        # ---------------------------------------------------
        ft_label = QLabel("Select file type")
        ft_label.setStyleSheet("background:#1FA37A; color:white; padding:8px; font-weight:bold;")

        self.ft_combo = QComboBox()
        self.ft_combo.addItems([".trc", ".log", ".csv", ".xlsx"])

        self.browse_btn = QPushButton("Browse File")
        self.browse_btn.setStyleSheet("background:#2B8CE7; color:white; font-weight:bold;")
        self.browse_btn.clicked.connect(self.on_browse)

        self.file_box = QLineEdit("No file selected")
        self.file_box.setReadOnly(True)

        self.make_btn = QPushButton("MAKE YOUR LOGS ORGANISED")
        self.make_btn.setStyleSheet("background:#FF0000; color:white; font-weight:bold;")
        self.make_btn.clicked.connect(self.on_make_logs)
        self.make_btn_animating = False
        self.run_all_animating = False

        self.run_all_btn = QPushButton("RUN ALL TEST CASES")
        self.run_all_btn.setEnabled(False)
        self.run_all_btn.setStyleSheet("background:#28A745; color:white; font-weight:bold;")
        self.run_all_btn.clicked.connect(self.start_all_tests)

        # ---------------- Firmware Fields ----------------
        def fw_field(name):
            lbl = QLabel(name)
            box = QLineEdit()
            box.setReadOnly(True)
            return lbl, box

        def style_label(widget: QLabel, bg_color: str):
            widget.setStyleSheet(
                f"background:{bg_color}; color:white; padding:6px; font-weight:bold;"
            )

        (self.lb_hw, self.tx_hw) = fw_field("BMS HW VERSION")
        (self.lb_fw, self.tx_fw) = fw_field("BMS FIRMWARE")
        (self.lb_cfg, self.tx_cfg) = fw_field("BMS CONFIG ID")
        (self.lb_git, self.tx_git) = fw_field("BMS GITSHA")
        (self.lb_manifest, self.tx_manifest) = fw_field("BMS MANIFEST")
        (self.lb_stark_fw, self.tx_stark_fw) = fw_field("STARK FIRMWARE")
        (self.lb_stark_cfg, self.tx_stark_cfg) = fw_field("STARK CONFIG")
        (self.lb_xavier_fw, self.tx_xavier_fw) = fw_field("XAVIER FIRMWARE")
        (self.lb_distance, self.tx_distance) = fw_field("DISTANCE COVERED")

        bms_labels = [
            self.lb_hw,
            self.lb_fw,
            self.lb_cfg,
            self.lb_git,
            self.lb_manifest,
        ]
        for lbl in bms_labels:
            style_label(lbl, "#1F4EB2")

        for lbl in (self.lb_stark_fw, self.lb_stark_cfg):
            style_label(lbl, "#2CBDF2")

        style_label(self.lb_xavier_fw, "#1FA37A")
        style_label(self.lb_distance, "#1FA37A")

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(5, 5, 5, 5)

        fw_rows = [
            (self.lb_hw, self.tx_hw),
            (self.lb_fw, self.tx_fw),
            (self.lb_cfg, self.tx_cfg),
            (self.lb_git, self.tx_git),
            (self.lb_manifest, self.tx_manifest),
            (self.lb_stark_fw, self.tx_stark_fw),
            (self.lb_stark_cfg, self.tx_stark_cfg),
            (self.lb_xavier_fw, self.tx_xavier_fw),
            (self.lb_distance, self.tx_distance),
        ]

        for r, (l, t) in enumerate(fw_rows):
            grid.addWidget(l, r, 0)
            grid.addWidget(t, r, 1)

        grid.setColumnStretch(0, 7)
        grid.setColumnStretch(1, 3)

        md_frame = QFrame()
        md_frame.setLayout(grid)

        # ---------------------------------------------------
        # EXTRA CHECK BUTTONS
        # ---------------------------------------------------
        self.btn_vcu = QPushButton("VCU unexpected Reset")
        self.tx_vcu_value = QLineEdit("0")
        self.tx_vcu_result = QLineEdit("N/A")

        self.btn_bms = QPushButton("MARVEL BMS unexpected Reset")
        self.tx_bms_value = QLineEdit("0")
        self.tx_bms_result = QLineEdit("N/A")

        for t in [self.tx_vcu_value, self.tx_vcu_result, self.tx_bms_value, self.tx_bms_result]:
            t.setReadOnly(True)

        # Store default palettes so we can restore styles cleanly
        self.vcu_value_palette_default = self.tx_vcu_value.palette()
        self.vcu_result_palette_default = self.tx_vcu_result.palette()
        self.bms_value_palette_default = self.tx_bms_value.palette()
        self.bms_result_palette_default = self.tx_bms_result.palette()

        # Auto-driven; disable manual clicks
        self.btn_vcu.setEnabled(False)
        self.btn_bms.setEnabled(False)
        green_btn_style = (
            "QPushButton { background:#28A745; color:white; font-weight:bold;"
            "border:1px solid #1f7a33; border-radius:4px; padding:6px; }"
            "QPushButton:disabled { background:#28A745; color:white;"
            "border:1px solid #1f7a33; }"
        )
        self.btn_vcu.setStyleSheet(green_btn_style)
        self.btn_bms.setStyleSheet(green_btn_style)
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

        # ---------------------------------------------------
        # GENERATE TRACKER BUTTON
        # ---------------------------------------------------
        self.gen_btn = QPushButton("GENERATE TRACKER SUMMARY")
        self.gen_btn.setStyleSheet("background:black; color:white; padding:10px; font-weight:bold;")
        self.gen_btn.clicked.connect(self.generate_tracker)

        # ---------------------------------------------------
        # LEFT PANEL FINAL BUILD
        # ---------------------------------------------------
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
        left.addWidget(self.gen_btn)
        left.addStretch()

        left_frame = QFrame()
        left_frame.setLayout(left)
        left_frame.setFixedWidth(380)

        # ---------------------------------------------------
        # RIGHT TABLE PANEL
        # ---------------------------------------------------
        # Columns:
        # 0 = TEST CASE (with per-test RUN button)
        # 1 = STATUS
        # 2 = View Results
        # 3 = View Graph
        # 4 = Result (PASS/FAIL)
        table = QTableWidget(len(TEST_CASES), 5)
        table.setHorizontalHeaderLabels(
            ["TEST CASE", "STATUS", "View Results", "View Graph", "Result"]
        )
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        result_header_item = table.horizontalHeaderItem(4)
        if result_header_item:
            result_header_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        header = table.horizontalHeader()
        header.setStyleSheet("QHeaderView::section { background-color: #FF0000; color: white; font-weight: bold; }")
        for c in range(5):
            header.setSectionResizeMode(c, QHeaderView.Fixed)

        total_ratio = 11 + 5 + 5 + 5 + 3
        total_width = 900

        table.setColumnWidth(0, int(total_width * (11 / total_ratio)))
        table.setColumnWidth(1, int(total_width * (5 / total_ratio)))
        table.setColumnWidth(2, int(total_width * (5 / total_ratio)))
        table.setColumnWidth(3, int(total_width * (5 / total_ratio)))
        table.setColumnWidth(4, int(total_width * (3 / total_ratio)))

        for i, name in enumerate(TEST_CASES):
            display_name = name
            if i == 0:
                display_name = "SoC BEHAVIOR + SoC STUCK"

            # Base item for data/sorting only; visual handled by widget below
            name_item = QTableWidgetItem(display_name)
            table.setItem(i, 0, name_item)

            # Composite widget in TEST CASE column: label + RUN button
            cell_widget = QWidget()
            cell_widget.setStyleSheet("background:white;")
            h_layout = QHBoxLayout(cell_widget)
            h_layout.setContentsMargins(4, 0, 4, 0)
            h_layout.setSpacing(6)

            lbl = QLabel(display_name)
            lbl.setStyleSheet("color:#1FA37A; font-weight:bold; background:white;")
            h_layout.addWidget(lbl, 1)

            btn_run = QPushButton("▶")
            btn_run.setToolTip("Run only this test case")
            btn_run.setStyleSheet(
                "QPushButton { background:#28A745; color:white; font-weight:bold; border-radius:12px; "
                "min-width:24px; max-width:24px; min-height:24px; max-height:24px; }"
                "QPushButton:pressed { background:#1f7a33; }"
            )
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

            btn_r = QPushButton("View")
            btn_r.clicked.connect(lambda _, r=i: self.on_view_results(r))
            table.setCellWidget(i, 2, btn_r)

            btn_g = QPushButton("Graph")
            btn_g.clicked.connect(lambda _, r=i: self.on_view_graph(r))
            table.setCellWidget(i, 3, btn_g)

        self.test_table = table

        right = QVBoxLayout()
        right.addWidget(table)

        right_frame = QFrame()
        right_frame.setLayout(right)

        # ---------------------------------------------------
        # MAIN LAYOUT
        # ---------------------------------------------------
        main = QHBoxLayout()
        main.addWidget(left_frame)
        main.addWidget(right_frame, 1)

        final = QVBoxLayout()
        final.addWidget(title_bar)
        final.addLayout(main)

        self.setLayout(final)

    # ======================================================
    # UTILS: CELL STYLING & SCRIPT PATHS
    # ======================================================
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

    def _init_title_animation(self, label: QLabel, container: Optional[QFrame] = None):
        """Animate title with a moving glow effect."""
        self.title_label = label
        self.title_container = container
        self.title_anim_step = 0
        self.title_anim_timer = QTimer(self)
        self.title_anim_timer.timeout.connect(self._update_title_glow)
        self.title_anim_timer.start(120)
        self._update_title_glow()

    def _update_title_glow(self):
        if not getattr(self, "title_label", None):
            return
        self.title_anim_step = (self.title_anim_step + 1) % 100
        highlight = self.title_anim_step / 100.0
        start = max(0.0, highlight - 0.2)
        end = min(1.0, highlight + 0.2)
        gradient = (
            "qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,"
            f"stop:0 #001F6B, stop:{start:.2f} #0033CC, stop:{highlight:.2f} #4DE8FF, "
            f"stop:{end:.2f} #0033CC, stop:1 #001F6B)"
        )
        style = (
            "color:#00FFFF; padding:10px; font-weight:bold;"
            f"background:{gradient};"
        )
        if getattr(self, "title_container", None):
            self.title_container.setStyleSheet(f"background:{gradient}; border:0px;")
            self.title_label.setStyleSheet(
                "color:#00FFFF; padding:10px; font-weight:bold; background:transparent;"
            )
            if getattr(self, "version_label", None):
                self.version_label.setStyleSheet(
                    "color:white; padding:0 12px; font-weight:bold; background:transparent;"
                )
        else:
            self.title_label.setStyleSheet(style)

        # Mirror the running glow on the log organiser button while active
        if getattr(self, "make_btn_animating", False) and getattr(self, "make_btn", None):
            btn_style = (
                "color:white; font-weight:bold; padding:10px;"
                "background:qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,"
                f"stop:0 #001F6B, stop:{start:.2f} #0033CC, stop:{highlight:.2f} #4DE8FF, "
                f"stop:{end:.2f} #0033CC, stop:1 #001F6B);"
            )
            self.make_btn.setStyleSheet(btn_style)

        # Apply a green running glow to the RUN ALL button while tests are running
        if getattr(self, "run_all_animating", False) and getattr(self, "run_all_btn", None):
            run_style = (
                "color:white; font-weight:bold; padding:10px;"
                "background:qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,"
                f"stop:0 #0A2F0A, stop:{start:.2f} #0F6B0F, stop:{highlight:.2f} #32CD32, "
                f"stop:{end:.2f} #0F6B0F, stop:1 #0A2F0A);"
            )
            self.run_all_btn.setStyleSheet(run_style)

        # Apply running reflection on status cells
        if getattr(self, "running_rows", None) and getattr(self, "test_table", None):
            phase = self.title_anim_step / 100.0
            for row in list(self.running_rows):
                self._set_running_visual(row, phase)

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
        """Set status cell to Running with static styling."""
        self.running_rows.add(row)
        self.running_started_at[row] = time.time()
        self._set_colored_cell(row, 1, "Running", "#00138B")  # static blue

    def _blend_colors(self, c1: QColor, c2: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        r = int(c1.red() + (c2.red() - c1.red()) * t)
        g = int(c1.green() + (c2.green() - c1.green()) * t)
        b = int(c1.blue() + (c2.blue() - c1.blue()) * t)
        return QColor(r, g, b)

    def _set_running_visual(self, row: int, phase: float):
        """Animate running status cell with a moving light-blue reflection and static text."""
        item = self.test_table.item(row, 1)
        if not item:
            return
        pct = self.running_pct.get(row)
        if pct is not None:
            item.setText(f"Running {pct:.1f}%")
        else:
            item.setText("Running")
        base = QColor("#00124F")
        shine = QColor("#4DE8FF")
        pos = phase % 1.0
        band = 0.18
        # smooth easing for the band movement
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
        """
        Re-enable the RUN ALL button only after all processes have stopped
        and pending result rows have been consumed.
        """
        if not self.processes:
            return
        if any(p.state() != QProcess.NotRunning for p in self.processes.values()):
            return
        if self.pending_result_rows:
            return
        self.run_all_btn.setEnabled(True)
        self.run_all_btn.setText("RUN ALL TEST CASES")
        self.run_all_btn.setStyleSheet("background:#28A745; color:white; font-weight:bold;")
        self.run_all_animating = False

    def _refresh_pending_results(self):
        if not self.pending_result_rows:
            self._ensure_result_timer_running()
            return
        for row in list(self.pending_result_rows):
            self.update_result_cell(row)
        self._ensure_result_timer_running()

    def _style_testcase_cell(self, item: QTableWidgetItem):
        """Style visible test case names."""
        if not item:
            return
        item.setForeground(QColor("#1FA37A"))  # green text
        item.setBackground(QColor("white"))
        font = item.font()
        font.setBold(True)
        item.setFont(font)

    def _get_test_script_paths(self, row: int):
        """
        Returns (folder_path, script_path) for a given row.
        Folder name is assumed to be base name of script.
        E.g. SoC_behavior.py -> TRC TEST CASES/SoC_behavior/SoC_behavior.py
        """
        script_name = SCRIPT_BY_ROW.get(row)
        if not script_name:
            return None, None
        folder_name = os.path.splitext(script_name)[0]

        # Primary path based on selected file type
        folder_path = os.path.join(self.tests_folder, folder_name)
        script_path = os.path.join(folder_path, script_name)

        # Fallback to default TRC folder if script not found (handles CSV/XLSX cases)
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
            defaults = _default_output_names(script_name)
            output_by_row[row] = {
                "result": entry.get("result", defaults["result"]),
                "summary": entry.get("summary", defaults["summary"]),
                "graph": entry.get("graph", defaults["graph"]),
            }
        return output_by_row

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
        """Delete previously generated result/summary/graph files for all test cases."""
        for row, files in self.output_files.items():
            for kind in ("result", "summary", "graph"):
                path = self._get_output_file_path(row, kind)
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    def _clear_outputs_for_row(self, row: int):
        """Delete result/summary/graph files for a single test case row."""
        files = self.output_files.get(row, {})
        for kind in ("result", "summary", "graph"):
            path = self._get_output_file_path(row, kind)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    # ======================================================
    # MAKE LOGS ORGANISED
    # ======================================================
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

        # Run script
        self.logs_proc = QProcess(self)
        self.logs_proc.setWorkingDirectory(self.script_dir)

        self.logs_proc.finished.connect(self.on_logs_finished)
        self.logs_proc.readyReadStandardOutput.connect(self._on_logs_stdout)

        self.logs_proc.start(sys.executable, [logs_script])

    def on_logs_finished(self):
        self.make_btn_animating = False
        self.make_btn.setText("LOGS ARE ORGANISED ✅, RETRY ?")
        self.make_btn.setStyleSheet("background-color: #28A745; color: white; font-weight: bold;")
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

    def _on_logs_stdout(self):
        """Capture logs_organised.py stdout and remember the FINAL output path."""
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

    # ======================================================
    # FILE BROWSE
    # ======================================================
    def _register_scan_task(self):
        self.scan_tasks += 1

    def _on_scan_finished(self):
        self.scan_tasks = max(0, self.scan_tasks - 1)
        if self.scan_tasks == 0:
            self.restore_browse_button()

    def _handle_file_selected(self, path: str):
        """Common handler when a TRC/log file is chosen."""
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
            self._start_vcu_reset_check(path, track_scan=True)
            self._start_bms_reset_check(path, track_scan=True)
        else:
            self.reset_vcu_fields()
            self.reset_bms_fields()

    def on_browse(self):
        ft = self.ft_combo.currentText()
        initial_dir = ""
        if self.logs_last_output_path:
            initial_dir = os.path.dirname(self.logs_last_output_path)
        elif self.selected_file_path:
            initial_dir = os.path.dirname(self.selected_file_path)

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select File",
            initial_dir,
            f"{ft} Files (*{ft})",
        )

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

        # Prefer new keyed distance; fallback if older key used
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
            bg, fg = "#28A745", "white"
        elif result == "FAIL":
            bg, fg = "#FF0000", "white"
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
            bg, fg = "#28A745", "white"
        elif result == "FAIL":
            bg, fg = "#FF0000", "white"
        else:
            bg, fg = "", ""

        apply_style(self.tx_bms_value, self.bms_value_palette_default, bg, fg)
        apply_style(self.tx_bms_result, self.bms_result_palette_default, bg, fg)

    def on_fw_error(self, err):
        QMessageBox.warning(self, "FW Error", err)

    # ======================================================
    # RUN ALL TEST CASES
    # ======================================================
    def start_all_tests(self):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "Browse a file first")
            return

        # Do not start RUN ALL if any tests are already running (single or batch)
        if any(p.state() != QProcess.NotRunning for p in self.processes.values()):
            QMessageBox.information(
                self,
                "Info",
                "Some tests are already running. Please wait for them to finish before running all.",
            )
            return

        # Clear previously generated outputs before running everything (configurable)
        if CLEAR_OUTPUTS_ON_RUN_ALL:
            self._clear_all_outputs()

        self.run_all_btn.setEnabled(False)
        self.run_all_btn.setText("RUNNING... Pls Wait")
        self.run_all_animating = True
        self._update_title_glow()  # kick off glow immediately

        self.pending_result_rows.clear()
        self._ensure_result_timer_running()

        # Reset status and result columns
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
                # Missing script/folder
                self._set_colored_cell(row, 1, "Missing/Incorrect", "#FF0000")
                continue

            self.pending_result_rows.add(row)
            self._ensure_result_timer_running()

            # Mark as running
            self._mark_row_running(row)

            proc = QProcess(self)
            proc.setWorkingDirectory(folder_path)

            # Capture row in lambda default
            proc.finished.connect(lambda exitCode, _status, r=row: self.on_test_finished(r, exitCode))
            proc.errorOccurred.connect(lambda _e, r=row: self.on_test_error(r))
            proc.readyReadStandardOutput.connect(lambda r=row: self._on_test_stdout(r))

            proc.start(python, [script, self.selected_file_path])
            self.processes[row] = proc

        # Edge case: if nothing started, reset button immediately
        if not self.processes:
            self.run_all_btn.setEnabled(True)
            self.run_all_btn.setText("RUN ALL TEST CASES")
            self.run_all_btn.setStyleSheet("background:#28A745; color:white; font-weight:bold;")
            self.run_all_animating = False

    # ======================================================
    # RUN SINGLE TEST CASE
    # ======================================================
    def start_single_test(self, row: int):
        """Run only the selected test case, with live progress updates."""
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "Browse a file first")
            return

        # Prevent re-running if this row is already in progress
        proc = self.processes.get(row)
        if proc and proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Info", "This test is already running.")
            return

        # Optionally clear previous outputs for ALL tests, so every run (even single)
        # starts with a clean set of result/summary/graph files.
        if CLEAR_OUTPUTS_ON_RUN_ALL:
            self._clear_all_outputs()

        # Reset status/result cells for this row
        status_item = QTableWidgetItem("Not Run")
        status_item.setTextAlignment(Qt.AlignCenter)
        self.test_table.setItem(row, 1, status_item)
        result_item = QTableWidgetItem("N/A")
        result_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.test_table.setItem(row, 4, result_item)

        folder_path, script_path = self._get_test_script_paths(row)
        if not folder_path or not os.path.exists(script_path):
            self._set_colored_cell(row, 1, "Missing/Incorrect", "#FF0000")
            return

        python = sys.executable

        # Track as pending so the result cell updates automatically
        self.pending_result_rows.add(row)
        self._ensure_result_timer_running()

        # Reset row-specific running state and mark as running
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
            # Completed OK
            self._set_colored_cell(row, 1, "Completed", "#28A745")
            # Try to update PASS/FAIL for this row
            if not self.update_result_cell(row):
                self._schedule_result_update(row)
        else:
            # Script ran but error/failed
            self._set_colored_cell(row, 1, "Missing/Incorrect", "#FF0000")
            if not self.update_result_cell(row):
                self._schedule_result_update(row)

        self._maybe_finish_run_all()

    def on_test_error(self, row, _):
        self.running_rows.discard(row)
        self.running_started_at.pop(row, None)
        self.running_pct.pop(row, None)
        self._set_colored_cell(row, 1, "Missing/Incorrect", "#FF0000")
        self._maybe_finish_run_all()

    def _on_test_stdout(self, row: int):
        """Handle stdout from a running test process to update live progress."""
        proc = self.processes.get(row)
        if not proc:
            return
        try:
            data = proc.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        except Exception:
            return

        updated = False
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
                updated = True

        if updated:
            # Apply immediate text refresh; background animation updates on its own timer
            self._set_running_visual(row, getattr(self, "title_anim_step", 0) / 100.0)

    def _mark_result_missing(self, row: int, reason: Optional[str] = None):
        # Give one last chance in case the JSON appeared after the retries elapsed.
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
            self._set_colored_cell(
                row, 4, "PASS", "#28A745", align=Qt.AlignLeft | Qt.AlignVCenter, tooltip=tooltip
            )
            success = True
        elif result_str == "FAIL":
            self._set_colored_cell(
                row, 4, "FAIL", "#FF0000", align=Qt.AlignLeft | Qt.AlignVCenter, tooltip=tooltip
            )
            success = True
        elif result_str == "WARNING":
            # Show WARNING as an in-between state (amber color)
            self._set_colored_cell(
                row, 4, "WARNING", "#FFA500", align=Qt.AlignLeft | Qt.AlignVCenter, tooltip=tooltip
            )
            success = True

        if success:
            status_item = self.test_table.item(row, 1)
            current_status = (status_item.text() if status_item else "").strip().lower()
            if current_status != "completed":
                self._set_colored_cell(row, 1, "Completed", "#28A745")

            if row in self.pending_result_rows:
                self.pending_result_rows.discard(row)
                self._ensure_result_timer_running()
            self._maybe_finish_run_all()
        return success

    def _schedule_result_update(
        self, row: int, attempts: int = RESULT_POLL_ATTEMPTS, delay_ms: int = RESULT_POLL_DELAY_MS
    ):
        """Retry updating result after giving scripts time to write output."""
        if attempts <= 0:
            self._mark_result_missing(row)
            return
        QTimer.singleShot(
            delay_ms,
            lambda r=row, a=attempts - 1, d=delay_ms: self._retry_result_update(r, a, d),
        )

    def _retry_result_update(self, row: int, attempts: int, delay_ms: int):
        if self.update_result_cell(row):
            return
        if attempts <= 0:
            self._mark_result_missing(row)
        else:
            self._schedule_result_update(row, attempts, delay_ms)

    # ======================================================
    # VIEW RESULT / GRAPH
    # ======================================================
    def on_view_results(self, idx):
        # Refresh PASS/FAIL manually whenever the user opens the viewer.
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

        # Prefer Microsoft Office Picture Manager if installed; fallback to default handler
        candidate_viewers = [
            r"C:\Program Files (x86)\Microsoft Office\Office12\OIS.EXE",
            r"C:\Program Files\Microsoft Office\Office12\OIS.EXE",
        ]
        for viewer in candidate_viewers:
            if os.path.exists(viewer):
                try:
                    subprocess.Popen([viewer, graph_path])
                    return
                except Exception:
                    pass

        try:
            os.startfile(graph_path)  # type: ignore[attr-defined]
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open graph:\n{e}")

    # ======================================================
    # RESET CHECKERS
    # ======================================================
    def _count_keyword(self, keywords):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "No file loaded!")
            return 0

        total = 0
        try:
            with open(self.selected_file_path, "r", errors="ignore") as f:
                for line in f:
                    l = line.lower()
                    for k in keywords:
                        if k in l:
                            total += 1
                            break
        except Exception:
            pass
        return total

    def check_vcu(self):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "No file loaded!")
            return
        file_ext = os.path.splitext(self.selected_file_path)[1].lower()
        if file_ext != ".trc":
            QMessageBox.warning(self, "Error", "VCU reset check only runs on .trc files.")
            self.reset_vcu_fields()
            return
        self._start_vcu_reset_check(self.selected_file_path, track_scan=False)

    def check_bms(self):
        self._run_bms_reset_check(manual=True)

    def _run_bms_reset_check(self, manual: bool = False):
        self._start_bms_reset_check(self.selected_file_path, track_scan=False, manual=manual)

    # ======================================================
    # GENERATE TRACKER
    # ======================================================
    def generate_tracker(self):
        if not self.selected_file_path:
            QMessageBox.warning(self, "Error", "No file selected!")
            return

        docx_path = os.path.join(self.script_dir, "tracker_summary.docx")
        generator_script = os.path.join(self.script_dir, "Generate_Tracker.py")

        meta_payload = {
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
            proc = subprocess.run(
                [sys.executable, generator_script, docx_path, self.tests_folder],
                cwd=self.script_dir,
                capture_output=True,
                text=True,
                env=env,
            )
        except Exception as e:
            QMessageBox.warning(self, "Tracker", f"Failed to start tracker script:\n{e}")
            return

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Tracker script returned an error."
            QMessageBox.warning(self, "Tracker", err_msg)
            return

        QMessageBox.information(self, "Tracker", f"Tracker generated:\n{docx_path}")

# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
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
    app = QApplication(sys.argv)
    run_updater_first(app)
    w = CANLogDebugger()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
