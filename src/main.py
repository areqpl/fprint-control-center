#!/usr/bin/env python3
"""
fprint-control-center v1.3.0: PyQt6 Ultra-Premium Desktop GUI & Daemon.
Designed with high-end UI/UX standards:
 - TokyoNight / Modern Obsidian Glassmorphism Palette (WCAG AAA Contrast)
 - Visual Finger Chips & Status Badges
 - Custom Rounded Card Widgets with Subtle Borders & Hover Lighting
 - Asynchronous QThread Concurrency & Non-Blocking Subprocess Wizard
"""

import sys
import os
import signal
import socket
import logging
import getpass
import traceback
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout,
    QWidget, QPushButton, QMessageBox, QHBoxLayout, QFrame,
    QSystemTrayIcon, QMenu, QDialog, QComboBox, QTextEdit,
    QProgressBar, QGroupBox, QGridLayout, QScrollArea
)
from PyQt6.QtCore import Qt, QSocketNotifier, QProcess, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QIcon, QAction, QPixmap, QColor, QPainter, QFont, QPen, QBrush
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from exceptions import (
    FprintControlError,
    SingleInstanceError,
    DBusCommunicationError,
    DeviceNotFoundError,
    EnrollmentError
)
from fprint_manager import FprintManager, retry_with_backoff

# Configure logging for standard output / systemd journald
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("fprint-control-center")

PREMIUM_STYLE = """
QMainWindow, QDialog {
    background-color: #0f0f17;
    color: #c0caf5;
    font-family: 'Inter', 'Segoe UI', 'SF Pro Display', sans-serif;
}

QFrame#cardFrame {
    background-color: #1a1b26;
    border: 1px solid #24283b;
    border-radius: 12px;
    padding: 16px;
}

QFrame#cardFrame:hover {
    border: 1px solid #414868;
}

QLabel {
    color: #c0caf5;
    font-size: 13px;
}

QLabel#mainHeader {
    font-size: 20px;
    font-weight: 800;
    color: #7aa2f7;
    letter-spacing: 0.5px;
}

QLabel#cardTitle {
    font-size: 14px;
    font-weight: 700;
    color: #bb9af7;
}

QLabel#badgeActive {
    background-color: #1f372d;
    color: #73daca;
    border: 1px solid #2e5b47;
    border-radius: 12px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel#badgeWarning {
    background-color: #3b2d1d;
    color: #e0af68;
    border: 1px solid #5d4428;
    border-radius: 12px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel#badgeInfo {
    background-color: #1d2d3a;
    color: #7dcfff;
    border: 1px solid #29475c;
    border-radius: 12px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel#fingerChip {
    background-color: #24283b;
    color: #7dcfff;
    border: 1px solid #3b4261;
    border-radius: 14px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
}

QPushButton {
    background-color: #24283b;
    color: #c0caf5;
    border: 1px solid #3b4261;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #2f354f;
    border-color: #565f89;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #414868;
}

QPushButton:disabled {
    background-color: #16161e;
    color: #565f89;
    border-color: #1a1b26;
}

QPushButton#btnPrimary {
    background-color: #7aa2f7;
    color: #15161e;
    border: none;
    font-weight: 700;
}

QPushButton#btnPrimary:hover {
    background-color: #89b4fa;
}

QPushButton#btnPrimary:disabled {
    background-color: #3b4261;
    color: #565f89;
}

QPushButton#btnDanger {
    background-color: #1a1b26;
    color: #f7768e;
    border: 1px solid #f7768e;
    font-weight: 600;
}

QPushButton#btnDanger:hover {
    background-color: #f7768e;
    color: #15161e;
}

QPushButton#btnDanger:disabled {
    background-color: #1a1b26;
    color: #565f89;
    border-color: #3b4261;
}

QProgressBar {
    border: 1px solid #3b4261;
    border-radius: 6px;
    text-align: center;
    background-color: #16161e;
    color: #c0caf5;
    font-weight: bold;
    height: 16px;
}

QProgressBar::chunk {
    background-color: #73daca;
    border-radius: 5px;
}

QComboBox {
    background-color: #24283b;
    color: #c0caf5;
    border: 1px solid #3b4261;
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
}

QTextEdit {
    background-color: #16161e;
    color: #9ece6a;
    border: 1px solid #24283b;
    border-radius: 8px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 12px;
    padding: 8px;
}
"""

FINGER_MAP = {
    "right-index-finger": "☝️ Right Index Finger",
    "left-index-finger": "☝️ Left Index Finger",
    "right-thumb": "👍 Right Thumb",
    "left-thumb": "👍 Left Thumb",
    "right-middle-finger": "🖐️ Right Middle Finger",
    "left-middle-finger": "🖐️ Left Middle Finger",
    "right-ring-finger": "💍 Right Ring Finger",
    "left-ring-finger": "💍 Left Ring Finger",
    "right-little-finger": "🖐️ Right Little Finger",
    "left-little-finger": "🖐️ Left Little Finger",
}


def get_app_icon() -> QIcon:
    candidates = [
        Path('/usr/share/pixmaps/fprint-control-center.png'),
        Path(__file__).resolve().parent.parent / 'resources' / 'icon.png',
        Path(__file__).resolve().parent / 'resources' / 'icon.png',
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 200:
            return QIcon(str(path))
    
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor('#7aa2f7')))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 60, 60)
    painter.end()
    return QIcon(pixmap)


class SingleInstanceLock:
    def __init__(self, app_name: str = "fprint-control-center"):
        username = getpass.getuser()
        self.server_name = f"{app_name}-lock-{username}"
        self.server = QLocalServer()

    def acquire(self) -> None:
        test_socket = QLocalSocket()
        test_socket.connectToServer(self.server_name)
        if test_socket.waitForConnected(500):
            test_socket.disconnectFromServer()
            raise SingleInstanceError("Another instance of fprint-control-center is running.")
        QLocalServer.removeServer(self.server_name)
        if not self.server.listen(self.server_name):
            raise SingleInstanceError("Failed to acquire single instance lock.")
        logger.info("Single-instance lock acquired.")

    def release(self) -> None:
        if self.server.isListening():
            self.server.close()
            QLocalServer.removeServer(self.server_name)


class UnixSignalNotifier:
    def __init__(self, app: QApplication):
        self.app = app
        self.read_sock, self.write_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM, 0)
        self.read_sock.setblocking(False)
        self.write_sock.setblocking(False)

        self.notifier = QSocketNotifier(self.read_sock.fileno(), QSocketNotifier.Type.Read)
        self.notifier.activated.connect(self._handle_signal)

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, self._signal_handler_func)

    def _signal_handler_func(self, signum, frame):
        try:
            self.write_sock.send(bytes([signum]))
        except OSError:
            pass

    def _handle_signal(self):
        self.notifier.setEnabled(False)
        try:
            _ = self.read_sock.recv(1024)
        except OSError:
            pass
        finally:
            self.app.quit()


def setup_exception_hook():
    def custom_excepthook(exctype, value, tb):
        if issubclass(exctype, KeyboardInterrupt):
            sys.__excepthook__(exctype, value, tb)
            return
        logger.critical("Unhandled exception caught:", exc_info=(exctype, value, tb))
        app = QApplication.instance()
        if app:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("fprint-control-center Error")
            msg_box.setText("An unexpected application error occurred.")
            msg_box.setInformativeText(str(value))
            msg_box.exec()
    sys.excepthook = custom_excepthook


# ==============================================================================
# WORKER OBJECTS (PyQt6 QThread Concurrency Pattern)
# ==============================================================================

class StatusQueryWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, fprint_mgr: FprintManager, username: str):
        super().__init__()
        self.fprint_mgr = fprint_mgr
        self.username = username

    def run_task(self):
        result = {
            "dev_name": "Synaptics Prometheus MIS Touch (06cb:00bd)",
            "dev_path": "/net/reactivated/Fprint/Device/0",
            "usb_power_optimized": False,
            "enrolled_fingers": [],
            "status_msg": "Operational"
        }
        try:
            rule_path = Path("/etc/udev/rules.d/70-synaptics-fingerprint-power.rules")
            result["usb_power_optimized"] = rule_path.is_file()

            try:
                dev_info = self.fprint_mgr.get_default_device()
                result["dev_name"] = dev_info.get("name", "Synaptics Fingerprint Scanner")
                result["dev_path"] = dev_info.get("path", "/net/reactivated/Fprint/Device/0")
            except Exception as e_dev:
                logger.warning(f"Device query fallback: {e_dev}")

            try:
                fingers = self.fprint_mgr.list_enrolled_fingers(self.username)
                result["enrolled_fingers"] = fingers
            except Exception as e_fingers:
                logger.warning(f"Enrolled query fallback: {e_fingers}")

            self.finished.emit(result)

        except Exception as exc:
            logger.error(f"StatusQueryWorker exception: {exc}")
            self.error.emit(str(exc))


class TemplateResetWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, username: str):
        super().__init__()
        self.username = username

    def run_task(self):
        try:
            res = subprocess.run(["fprintd-delete", self.username], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                self.finished.emit(True, f"Successfully deleted all templates for '{self.username}'.")
            else:
                self.finished.emit(False, res.stderr or res.stdout or "fprintd-delete failed.")
        except Exception as exc:
            self.finished.emit(False, str(exc))


# ==============================================================================
# UI COMPONENTS & WINDOWS
# ==============================================================================

class EnrollmentDialog(QDialog):
    def __init__(self, parent=None, username: str = ""):
        super().__init__(parent)
        self.username = username or getpass.getuser()
        self.process = None
        self.stages_completed = 0
        self.total_stages = 8

        self.setWindowTitle("Fingerprint Enrollment Wizard")
        self.setFixedSize(500, 440)
        self.setStyleSheet(PREMIUM_STYLE)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl_title = QLabel("Fingerprint Enrollment Wizard")
        lbl_title.setObjectName("mainHeader")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Select your target finger and click Start Enrollment. Place your finger firmly on the reader scanner when prompted.")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #a9b1d6;")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)

        h_layout = QHBoxLayout()
        lbl_target = QLabel("Target Finger:")
        lbl_target.setStyleSheet("font-weight: 700;")
        h_layout.addWidget(lbl_target)
        self.combo_finger = QComboBox()
        for key, label in FINGER_MAP.items():
            self.combo_finger.addItem(label, key)
        h_layout.addWidget(self.combo_finger)
        layout.addLayout(h_layout)

        self.lbl_stage = QLabel("Status: Ready")
        self.lbl_stage.setStyleSheet("font-weight: 700; color: #7dcfff;")
        self.lbl_stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_stage)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total_stages)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText("Live scanner output log...")
        layout.addWidget(self.txt_log)

        b_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start Enrollment")
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.clicked.connect(self.start_enrollment)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_enrollment)

        self.btn_close = QPushButton("Done")
        self.btn_close.clicked.connect(self.accept)

        b_layout.addWidget(self.btn_start)
        b_layout.addWidget(self.btn_cancel)
        b_layout.addWidget(self.btn_close)
        layout.addLayout(b_layout)

        self.setLayout(layout)

    def start_enrollment(self):
        finger_code = self.combo_finger.currentData()
        self.btn_start.setEnabled(False)
        self.combo_finger.setEnabled(False)
        self.stages_completed = 0
        self.progress_bar.setValue(0)
        self.txt_log.clear()

        finger_name = FINGER_MAP.get(finger_code, finger_code)
        self.lbl_stage.setText(f"Enrolling {finger_name}...")
        self.txt_log.append(f"Starting 360° enrollment for '{self.username}' ({finger_name})...\n")
        self.txt_log.append("▶ Place finger on reader...\n")

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._handle_stdout)
        self.process.finished.connect(self._handle_finished)

        cmd = ["fprintd-enroll", "-f", finger_code, self.username]
        self.process.start(cmd[0], cmd[1:])

    def _handle_stdout(self):
        if not self.process:
            return
        output = self.process.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        for line in output.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            self.txt_log.append(line_str)

            if "enroll-stage-passed" in line_str or "stage-passed" in line_str or "swipe" in line_str.lower():
                self.stages_completed += 1
                self.progress_bar.setValue(min(self.stages_completed, self.total_stages))
                self.lbl_stage.setText(f"Stage {self.stages_completed} of {self.total_stages} complete. Lift & place finger again.")
            elif "enroll-retry-scan" in line_str or "retry" in line_str.lower():
                self.lbl_stage.setText("⚠️ Center finger on scanner and try again.")
            elif "completed" in line_str.lower() or "enroll-completed" in line_str:
                self.progress_bar.setValue(self.total_stages)
                self.lbl_stage.setText("🎉 Fingerprint enrolled successfully!")

    def _handle_finished(self, exit_code, exit_status):
        self.btn_start.setEnabled(True)
        self.combo_finger.setEnabled(True)
        if exit_code == 0:
            self.lbl_stage.setText("✅ Enrollment complete & template saved!")
        else:
            self.lbl_stage.setText("❌ Enrollment failed or canceled.")

    def cancel_enrollment(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.terminate()
        self.reject()


class MainWindow(QMainWindow):
    """
    High-End UX & UI Refined Control Center Window.
    """
    def __init__(self, fprint_mgr: FprintManager, tray_icon: QSystemTrayIcon):
        super().__init__()
        self.fprint_mgr = fprint_mgr
        self.tray_icon = tray_icon
        self.username = getpass.getuser()

        self.status_thread: Optional[QThread] = None
        self.status_worker: Optional[StatusQueryWorker] = None

        self.reset_thread: Optional[QThread] = None
        self.reset_worker: Optional[TemplateResetWorker] = None

        self.setWindowTitle("Fingerprint Control Center")
        self.setFixedSize(580, 520)
        self.setStyleSheet(PREMIUM_STYLE)

        icon = get_app_icon()
        self.setWindowIcon(icon)

        self._init_ui()
        self.refresh_status()

    def _init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # Header Title Bar
        title_box = QHBoxLayout()
        lbl_title = QLabel("Fingerprint Control Center")
        lbl_title.setObjectName("mainHeader")
        
        self.lbl_badge = QLabel("🟢 ACTIVE")
        self.lbl_badge.setObjectName("badgeActive")
        
        title_box.addWidget(lbl_title)
        title_box.addStretch()
        title_box.addWidget(self.lbl_badge)
        main_layout.addLayout(title_box)

        # CARD 1: Hardware & USB Power Optimization
        card_hw = QFrame()
        card_hw.setObjectName("cardFrame")
        hw_layout = QVBoxLayout(card_hw)
        hw_layout.setSpacing(8)

        lbl_hw_title = QLabel("⚡ HARDWARE DIAGNOSTICS & POWER OPTIMIZATION")
        lbl_hw_title.setObjectName("cardTitle")
        hw_layout.addWidget(lbl_hw_title)

        self.lbl_dev_name = QLabel("Device: Synaptics Prometheus MIS Touch (06cb:00bd)")
        self.lbl_dev_name.setStyleSheet("font-weight: 600; font-size: 13px;")
        
        self.lbl_dev_path = QLabel("D-Bus Path: /net/reactivated/Fprint/Device/0")
        self.lbl_dev_path.setStyleSheet("color: #767b9d; font-size: 12px;")
        
        self.lbl_usb_power = QLabel("USB Autosuspend: checking...")
        self.lbl_usb_power.setObjectName("badgeInfo")

        hw_layout.addWidget(self.lbl_dev_name)
        hw_layout.addWidget(self.lbl_dev_path)
        hw_layout.addWidget(self.lbl_usb_power, alignment=Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(card_hw)

        # CARD 2: Enrolled Fingerprints Visual Chips
        card_enrolled = QFrame()
        card_enrolled.setObjectName("cardFrame")
        enrolled_layout = QVBoxLayout(card_enrolled)
        enrolled_layout.setSpacing(12)

        lbl_enrolled_title = QLabel("🖐️ REGISTERED FINGERPRINT TEMPLATES")
        lbl_enrolled_title.setObjectName("cardTitle")
        enrolled_layout.addWidget(lbl_enrolled_title)

        # Container layout for chips
        self.chip_container = QWidget()
        self.chip_layout = QHBoxLayout(self.chip_container)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(8)
        self.chip_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.lbl_no_chips = QLabel("No registered fingerprint templates found.")
        self.lbl_no_chips.setStyleSheet("color: #e0af68; font-weight: 600;")
        self.chip_layout.addWidget(self.lbl_no_chips)

        enrolled_layout.addWidget(self.chip_container)

        # Actions Toolbar inside Card 2
        act_layout = QHBoxLayout()
        self.btn_enroll = QPushButton("➕ Enroll New Finger")
        self.btn_enroll.setObjectName("btnPrimary")
        self.btn_enroll.clicked.connect(self.open_enrollment_dialog)

        self.btn_reset = QPushButton("🗑️ Reset All Templates")
        self.btn_reset.setObjectName("btnDanger")
        self.btn_reset.clicked.connect(self.reset_templates)

        act_layout.addWidget(self.btn_enroll)
        act_layout.addWidget(self.btn_reset)
        enrolled_layout.addLayout(act_layout)

        main_layout.addWidget(card_enrolled)

        # Footer Navigation Bar
        footer_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄 Refresh Status")
        self.btn_refresh.clicked.connect(self.refresh_status)

        self.btn_hide = QPushButton("Hide to Tray")
        self.btn_hide.clicked.connect(self.hide)

        footer_layout.addWidget(self.btn_refresh)
        footer_layout.addStretch()
        footer_layout.addWidget(self.btn_hide)
        main_layout.addLayout(footer_layout)

        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    # --------------------------------------------------------------------------
    # ASYNCHRONOUS WORKER SLOTS
    # --------------------------------------------------------------------------
    def refresh_status(self):
        logger.info("Initiating status refresh...")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("Refreshing...")

        self.status_thread = QThread()
        self.status_worker = StatusQueryWorker(self.fprint_mgr, self.username)
        self.status_worker.moveToThread(self.status_thread)

        self.status_thread.started.connect(self.status_worker.run_task)
        self.status_worker.finished.connect(self.on_status_ready)
        self.status_worker.error.connect(self.on_status_error)

        self.status_worker.finished.connect(self.status_thread.quit)
        self.status_worker.finished.connect(self.status_worker.deleteLater)
        self.status_thread.finished.connect(self.status_thread.deleteLater)

        self.status_thread.start()

    def on_status_ready(self, data: dict):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Refresh Status")

        # USB Power Autosuspend update
        if data.get("usb_power_optimized"):
            self.lbl_usb_power.setText("⚡ USB Power: Optimized (udev rule active)")
            self.lbl_usb_power.setObjectName("badgeActive")
        else:
            self.lbl_usb_power.setText("⚠️ USB Power: Default (autosuspend may drop scans)")
            self.lbl_usb_power.setObjectName("badgeWarning")
        self.lbl_usb_power.setStyleSheet("") # Force QSS refresh

        # Device Info
        self.lbl_dev_name.setText(f"Device: {data.get('dev_name')}")
        self.lbl_dev_path.setText(f"D-Bus Path: {data.get('dev_path')}")

        # Re-render Enrolled Finger Chips
        fingers = data.get("enrolled_fingers", [])
        
        # Clear existing layout items
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if fingers:
            for finger_code in fingers:
                chip = QLabel(FINGER_MAP.get(finger_code, finger_code))
                chip.setObjectName("fingerChip")
                self.chip_layout.addWidget(chip)
            self.tray_icon.setToolTip(f"fprint-control-center: {len(fingers)} Finger(s) Registered ({self.username})")
        else:
            lbl_none = QLabel("No fingerprint templates registered.")
            lbl_none.setStyleSheet("color: #e0af68; font-weight: 600;")
            self.chip_layout.addWidget(lbl_none)
            self.tray_icon.setToolTip("fprint-control-center: No enrolled fingers")

    def on_status_error(self, err_msg: str):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Refresh Status")
        logger.error(f"Status query error: {err_msg}")

    def reset_templates(self):
        reply = QMessageBox.question(
            self,
            "Confirm Template Wipe",
            f"Are you sure you want to delete all fingerprint templates for user '{self.username}'?\n\nThis will execute 'fprintd-delete' and remove all enrolled scans.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.btn_reset.setEnabled(False)
            self.btn_reset.setText("Deleting...")

            self.reset_thread = QThread()
            self.reset_worker = TemplateResetWorker(self.username)

            self.reset_worker.moveToThread(self.reset_thread)
            self.reset_thread.started.connect(self.reset_worker.run_task)
            self.reset_worker.finished.connect(self.on_reset_finished)

            self.reset_worker.finished.connect(self.reset_thread.quit)
            self.reset_worker.finished.connect(self.reset_worker.deleteLater)
            self.reset_thread.finished.connect(self.reset_thread.deleteLater)

            self.reset_thread.start()

    def on_reset_finished(self, success: bool, message: str):
        self.btn_reset.setEnabled(True)
        self.btn_reset.setText("🗑️ Reset All Templates")
        if success:
            QMessageBox.information(self, "Templates Reset", message)
            if self.tray_icon:
                self.tray_icon.showMessage("Templates Reset", message, QSystemTrayIcon.MessageIcon.Information)
        else:
            QMessageBox.warning(self, "Reset Error", message)
        self.refresh_status()

    def open_enrollment_dialog(self):
        dialog = EnrollmentDialog(self, self.username)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_status()

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def main():
    setup_exception_hook()

    app = QApplication(sys.argv)
    app.setApplicationName("Fingerprint Control Center")
    app.setOrganizationName("fprint-control-center")
    app.setQuitOnLastWindowClosed(False)

    lock = SingleInstanceLock()
    try:
        lock.acquire()
    except SingleInstanceError as exc:
        logger.error(f"Single instance lock failed: {exc}")
        sys.exit(0)

    signal_notifier = UnixSignalNotifier(app)
    fprint_mgr = FprintManager()

    # System Tray Setup
    tray_icon = QSystemTrayIcon()
    app_icon = get_app_icon()
    tray_icon.setIcon(app_icon)
    tray_icon.setToolTip("Fingerprint Control Center")

    # Main Window
    window = MainWindow(fprint_mgr, tray_icon)

    # Tray Context Menu
    tray_menu = QMenu()
    act_open = QAction("Open Control Center", tray_menu)
    act_open.triggered.connect(lambda: (window.show(), window.activateWindow()))

    act_enroll = QAction("Enroll Finger...", tray_menu)
    act_enroll.triggered.connect(window.open_enrollment_dialog)

    act_reset = QAction("Reset Templates...", tray_menu)
    act_reset.triggered.connect(window.reset_templates)

    act_quit = QAction("Quit", tray_menu)
    act_quit.triggered.connect(app.quit)

    tray_menu.addAction(act_open)
    tray_menu.addSeparator()
    tray_menu.addAction(act_enroll)
    tray_menu.addAction(act_reset)
    tray_menu.addSeparator()
    tray_menu.addAction(act_quit)

    tray_icon.setContextMenu(tray_menu)
    tray_icon.activated.connect(
        lambda reason: (window.show(), window.activateWindow()) if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None
    )
    tray_icon.show()

    app.aboutToQuit.connect(lock.release)
    app.aboutToQuit.connect(fprint_mgr.release_device)

    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
