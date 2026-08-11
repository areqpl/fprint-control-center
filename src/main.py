#!/usr/bin/env python3
"""
fprint-control-center v1.4.0: PyQt6 Desktop GUI Control Center & Settings.
Features:
 - Multi-tab layout (Overview & Enrollment | CLI & PAM Settings)
 - Verification Match Tester (runs fprintd-verify asynchronously)
 - PAM & Sudo Integration Diagnostic Controls (/etc/pam.d/sudo)
 - Hardware USB Autosuspend Power Tweak Manager (/etc/udev/rules.d/70-synaptics-fingerprint-power.rules)
 - Quiet background workers (QThread) with zero log noise
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
    QProgressBar, QGroupBox, QTabWidget
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

QTabWidget::pane {
    border: 1px solid #24283b;
    background-color: #0f0f17;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #1a1b26;
    color: #a9b1d6;
    padding: 10px 20px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    margin-right: 4px;
}

QTabBar::tab:selected {
    background-color: #24283b;
    color: #7aa2f7;
    border-bottom: 2px solid #7aa2f7;
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
    font-family: 'JetBrains Mono', 'Consolas', monospace;
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
# ASYNCHRONOUS WORKER OBJECTS
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
            "pam_sudo_active": False,
            "enrolled_fingers": [],
        }
        try:
            rule_path = Path("/etc/udev/rules.d/70-synaptics-fingerprint-power.rules")
            result["usb_power_optimized"] = rule_path.is_file()

            # PAM sudo check
            try:
                pam_sudo = Path("/etc/pam.d/sudo")
                if pam_sudo.is_file():
                    result["pam_sudo_active"] = "pam_fprintd.so" in pam_sudo.read_text(errors="ignore")
            except Exception:
                pass

            # D-Bus / CLI queries
            dev_info = self.fprint_mgr.get_default_device()
            result["dev_name"] = dev_info.get("name", "Synaptics Fingerprint Scanner")
            result["dev_path"] = dev_info.get("path", "/net/reactivated/Fprint/Device/0")

            fingers = self.fprint_mgr.list_enrolled_fingers(self.username)
            result["enrolled_fingers"] = fingers

            self.finished.emit(result)

        except Exception as exc:
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


class VerifyWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, finger_code: str, username: str):
        super().__init__()
        self.finger_code = finger_code
        self.username = username

    def run_task(self):
        try:
            cmd = ["fprintd-verify"]
            if self.finger_code:
                cmd.extend(["-f", self.finger_code])
            if self.username:
                cmd.append(self.username)
            
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            output = res.stdout + res.stderr
            if "verify-match" in output.lower() or "matched" in output.lower():
                self.finished.emit(True, "🎉 Fingerprint Verification Match SUCCESS!")
            elif "verify-no-match" in output.lower():
                self.finished.emit(False, "❌ Fingerprint Verification Failed: No match found.")
            else:
                self.finished.emit(False, f"Verification Result:\n{output.strip()}")
        except Exception as exc:
            self.finished.emit(False, f"Verification execution error: {exc}")


# ==============================================================================
# UI COMPONENTS
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
    def __init__(self, fprint_mgr: FprintManager, tray_icon: QSystemTrayIcon):
        super().__init__()
        self.fprint_mgr = fprint_mgr
        self.tray_icon = tray_icon
        self.username = getpass.getuser()

        self.status_thread: Optional[QThread] = None
        self.status_worker: Optional[StatusQueryWorker] = None

        self.reset_thread: Optional[QThread] = None
        self.reset_worker: Optional[TemplateResetWorker] = None

        self.verify_thread: Optional[QThread] = None
        self.verify_worker: Optional[VerifyWorker] = None

        self.setWindowTitle("Fingerprint Control Center")
        self.setFixedSize(620, 560)
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

        # Tab Widget
        self.tabs = QTabWidget()
        
        # TAB 1: OVERVIEW & ENROLLMENT
        tab_overview = QWidget()
        ov_layout = QVBoxLayout(tab_overview)
        ov_layout.setSpacing(14)
        ov_layout.setContentsMargins(14, 14, 14, 14)

        # CARD 1: Hardware & Power
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
        ov_layout.addWidget(card_hw)

        # CARD 2: Enrolled Fingerprints Visual Chips
        card_enrolled = QFrame()
        card_enrolled.setObjectName("cardFrame")
        enrolled_layout = QVBoxLayout(card_enrolled)
        enrolled_layout.setSpacing(12)

        lbl_enrolled_title = QLabel("🖐️ REGISTERED FINGERPRINT TEMPLATES")
        lbl_enrolled_title.setObjectName("cardTitle")
        enrolled_layout.addWidget(lbl_enrolled_title)

        self.chip_container = QWidget()
        self.chip_layout = QHBoxLayout(self.chip_container)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(8)
        self.chip_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.lbl_no_chips = QLabel("No registered fingerprint templates found.")
        self.lbl_no_chips.setStyleSheet("color: #e0af68; font-weight: 600;")
        self.chip_layout.addWidget(self.lbl_no_chips)

        enrolled_layout.addWidget(self.chip_container)

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

        ov_layout.addWidget(card_enrolled)
        self.tabs.addTab(tab_overview, "🖐️ Overview & Templates")

        # TAB 2: CLI & PAM INTEGRATION SETTINGS
        tab_settings = QWidget()
        set_layout = QVBoxLayout(tab_settings)
        set_layout.setSpacing(14)
        set_layout.setContentsMargins(14, 14, 14, 14)

        # CARD 3: PAM Authentication Status
        card_pam = QFrame()
        card_pam.setObjectName("cardFrame")
        pam_layout = QVBoxLayout(card_pam)
        pam_layout.setSpacing(8)

        lbl_pam_title = QLabel("🔑 PAM & TERMINAL AUTHENTICATION INTEGRATION")
        lbl_pam_title.setObjectName("cardTitle")
        pam_layout.addWidget(lbl_pam_title)

        self.lbl_pam_sudo = QLabel("Sudo PAM (/etc/pam.d/sudo): Checking...")
        self.lbl_pam_sudo.setStyleSheet("font-weight: 600;")
        pam_layout.addWidget(self.lbl_pam_sudo)

        set_layout.addWidget(card_pam)

        # CARD 4: Fingerprint Verification Match Test
        card_test = QFrame()
        card_test.setObjectName("cardFrame")
        test_layout = QVBoxLayout(card_test)
        test_layout.setSpacing(10)

        lbl_test_title = QLabel("🧪 INTERACTIVE FINGERPRINT VERIFICATION TEST")
        lbl_test_title.setObjectName("cardTitle")
        test_layout.addWidget(lbl_test_title)

        self.lbl_verify_status = QLabel("Press 'Test Verification' to test sensor match feedback.")
        self.lbl_verify_status.setStyleSheet("color: #a9b1d6;")
        test_layout.addWidget(self.lbl_verify_status)

        self.btn_test_verify = QPushButton("🔍 Test Fingerprint Verification")
        self.btn_test_verify.setObjectName("btnPrimary")
        self.btn_test_verify.clicked.connect(self.run_verification_test)
        test_layout.addWidget(self.btn_test_verify, alignment=Qt.AlignmentFlag.AlignLeft)

        set_layout.addWidget(card_test)
        self.tabs.addTab(tab_settings, "⚙️ CLI & PAM Settings")

        main_layout.addWidget(self.tabs)

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
        self.lbl_usb_power.setStyleSheet("")

        # PAM Sudo status
        if data.get("pam_sudo_active"):
            self.lbl_pam_sudo.setText("Sudo PAM (/etc/pam.d/sudo): 🔵 Active (pam_fprintd.so configured)")
            self.lbl_pam_sudo.setStyleSheet("color: #73daca; font-weight: bold;")
        else:
            self.lbl_pam_sudo.setText("Sudo PAM (/etc/pam.d/sudo): ⚠️ Inactive")
            self.lbl_pam_sudo.setStyleSheet("color: #e0af68;")

        # Device Info
        self.lbl_dev_name.setText(f"Device: {data.get('dev_name')}")
        self.lbl_dev_path.setText(f"D-Bus Path: {data.get('dev_path')}")

        # Enrolled Finger Chips
        fingers = data.get("enrolled_fingers", [])
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

    def run_verification_test(self):
        self.btn_test_verify.setEnabled(False)
        self.btn_test_verify.setText("Testing... Scan finger")
        self.lbl_verify_status.setText("▶ Touch fingerprint reader scanner now...")
        self.lbl_verify_status.setStyleSheet("color: #7dcfff; font-weight: bold;")

        self.verify_thread = QThread()
        self.verify_worker = VerifyWorker("", self.username)
        self.verify_worker.moveToThread(self.verify_thread)

        self.verify_thread.started.connect(self.verify_worker.run_task)
        self.verify_worker.finished.connect(self.on_verify_finished)

        self.verify_worker.finished.connect(self.verify_thread.quit)
        self.verify_worker.finished.connect(self.verify_worker.deleteLater)
        self.verify_thread.finished.connect(self.verify_thread.deleteLater)

        self.verify_thread.start()

    def on_verify_finished(self, success: bool, message: str):
        self.btn_test_verify.setEnabled(True)
        self.btn_test_verify.setText("🔍 Test Fingerprint Verification")
        self.lbl_verify_status.setText(message)
        if success:
            self.lbl_verify_status.setStyleSheet("color: #73daca; font-weight: bold;")
        else:
            self.lbl_verify_status.setStyleSheet("color: #f7768e; font-weight: bold;")

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
