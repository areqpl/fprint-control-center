#!/usr/bin/env python3
"""
fprint-control-center v1.2.1: PyQt6 Desktop GUI Application & Daemon.
Re-architected strictly following PyQt6 Desktop GUI Development Best Practices:
 - Golden Rule: All D-Bus I/O, subprocess execution, and disk checks offloaded to QThread workers
 - Garbage Collection Protection: Active references held for all worker threads
 - Strict Thread Safety: UI widget state mutated exclusively via pyqtSignal slots
 - Modern QSS & Visual Hierarchy: Responsive controls, Catppuccin Mocha styling, disabled/hover states
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
    QProgressBar, QGroupBox, QGridLayout
)
from PyQt6.QtCore import Qt, QSocketNotifier, QProcess, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QIcon, QAction, QPixmap, QColor, QPainter, QFont
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

DARK_STYLE = """
QMainWindow, QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Inter', 'Segoe UI', 'Noto Sans', sans-serif;
}
QGroupBox {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 14px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #89b4fa;
}
QLabel {
    color: #cdd6f4;
    font-size: 13px;
}
QLabel#titleLabel {
    font-size: 18px;
    font-weight: bold;
    color: #cba6f7;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #45475a;
    border-color: #585b70;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:disabled {
    background-color: #181825;
    color: #6c7086;
    border-color: #313244;
}
QPushButton#primaryBtn {
    background-color: #89b4fa;
    color: #11111b;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #b4befe;
}
QPushButton#primaryBtn:disabled {
    background-color: #45475a;
    color: #7f849c;
}
QPushButton#dangerBtn {
    background-color: #f38ba8;
    color: #11111b;
    border: none;
}
QPushButton#dangerBtn:hover {
    background-color: #f5e0dc;
}
QPushButton#dangerBtn:disabled {
    background-color: #45475a;
    color: #7f849c;
}
QProgressBar {
    border: 1px solid #45475a;
    border-radius: 6px;
    text-align: center;
    background-color: #181825;
    color: #cdd6f4;
    font-weight: bold;
}
QProgressBar::chunk {
    background-color: #a6e3a1;
    border-radius: 5px;
}
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 12px;
}
QTextEdit {
    background-color: #11111b;
    color: #a6e3a1;
    border: 1px solid #313244;
    border-radius: 6px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 12px;
}
"""

FINGER_MAP = {
    "right-index-finger": "Right Index Finger",
    "left-index-finger": "Left Index Finger",
    "right-thumb": "Right Thumb",
    "left-thumb": "Left Thumb",
    "right-middle-finger": "Right Middle Finger",
    "left-middle-finger": "Left Middle Finger",
    "right-ring-finger": "Right Ring Finger",
    "left-ring-finger": "Left Ring Finger",
    "right-little-finger": "Right Little Finger",
    "left-little-finger": "Left Little Finger",
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
    painter.setBrush(QColor('#89b4fa'))
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
    """
    Worker executing D-Bus queries and file system checks off the main GUI thread.
    """
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, fprint_mgr: FprintManager, username: str):
        super().__init__()
        self.fprint_mgr = fprint_mgr
        self.username = username

    def run_task(self):
        result = {
            "dev_name": "Generic Fingerprint Reader",
            "dev_path": "/net/reactivated/Fprint/Device/0",
            "usb_power_optimized": False,
            "enrolled_fingers": [],
            "status_msg": "Operational"
        }
        try:
            # Check udev rule
            rule_path = Path("/etc/udev/rules.d/70-synaptics-fingerprint-power.rules")
            result["usb_power_optimized"] = rule_path.is_file()

            # D-Bus queries
            try:
                dev_info = self.fprint_mgr.get_default_device()
                result["dev_name"] = dev_info.get("name", "Synaptics Fingerprint Reader")
                result["dev_path"] = dev_info.get("path", "/net/reactivated/Fprint/Device/0")
            except Exception as e_dev:
                logger.warning(f"Default device query warning: {e_dev}")

            # Enrolled fingers query
            try:
                fingers = self.fprint_mgr.list_enrolled_fingers(self.username)
                result["enrolled_fingers"] = fingers
            except Exception as e_fingers:
                logger.warning(f"Enrolled fingers query warning: {e_fingers}")

            self.finished.emit(result)

        except Exception as exc:
            logger.error(f"StatusQueryWorker exception: {exc}")
            self.error.emit(str(exc))


class TemplateResetWorker(QObject):
    """
    Worker executing fprintd-delete process off the main GUI thread.
    """
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
        self.setFixedSize(480, 420)
        self.setStyleSheet(DARK_STYLE)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(14)

        lbl_title = QLabel("Enroll Fingerprint Template")
        lbl_title.setObjectName("titleLabel")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Select target finger and press Start Enrollment. Follow progress instructions.")
        lbl_desc.setWordWrap(True)
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)

        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel("Target Finger:"))
        self.combo_finger = QComboBox()
        for key, label in FINGER_MAP.items():
            self.combo_finger.addItem(label, key)
        h_layout.addWidget(self.combo_finger)
        layout.addLayout(h_layout)

        self.lbl_stage = QLabel("Status: Ready to enroll")
        self.lbl_stage.setStyleSheet("font-weight: bold; color: #89b4fa;")
        self.lbl_stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_stage)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total_stages)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText("Live enrollment log output...")
        layout.addWidget(self.txt_log)

        b_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start Enrollment")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_start.clicked.connect(self.start_enrollment)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_enrollment)

        self.btn_close = QPushButton("Close")
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

        self.lbl_stage.setText(f"Enrolling {FINGER_MAP.get(finger_code, finger_code)}...")
        self.txt_log.append(f"Starting enrollment for user '{self.username}' ({finger_code})...\n")
        self.txt_log.append("▶ Place finger on sensor...\n")

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
                self.lbl_stage.setText(f"Stage {self.stages_completed} of {self.total_stages} complete. Lift and place finger again.")
            elif "enroll-retry-scan" in line_str or "retry" in line_str.lower():
                self.lbl_stage.setText("⚠️ Scan retry needed. Center finger on reader.")
            elif "completed" in line_str.lower() or "enroll-completed" in line_str:
                self.progress_bar.setValue(self.total_stages)
                self.lbl_stage.setText("🎉 Fingerprint enrolled successfully!")

    def _handle_finished(self, exit_code, exit_status):
        self.btn_start.setEnabled(True)
        self.combo_finger.setEnabled(True)
        if exit_code == 0:
            self.lbl_stage.setText("✅ Enrollment complete & template saved!")
        else:
            self.lbl_stage.setText("❌ Enrollment failed or timed out.")

    def cancel_enrollment(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.terminate()
        self.reject()


class MainWindow(QMainWindow):
    """
    Main Application Window with strictly asynchronous QThread worker offloading.
    """
    def __init__(self, fprint_mgr: FprintManager, tray_icon: QSystemTrayIcon):
        super().__init__()
        self.fprint_mgr = fprint_mgr
        self.tray_icon = tray_icon
        self.username = getpass.getuser()

        # Thread references to prevent GC destruction
        self.status_thread: Optional[QThread] = None
        self.status_worker: Optional[StatusQueryWorker] = None

        self.reset_thread: Optional[QThread] = None
        self.reset_worker: Optional[TemplateResetWorker] = None

        self.setWindowTitle("Fingerprint Control Center")
        self.setFixedSize(540, 480)
        self.setStyleSheet(DARK_STYLE)

        icon = get_app_icon()
        self.setWindowIcon(icon)

        self._init_ui()
        self.refresh_status()

    def _init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(14)

        # Header Title
        title_box = QHBoxLayout()
        lbl_title = QLabel("Fingerprint Control Center")
        lbl_title.setObjectName("titleLabel")
        self.lbl_badge = QLabel("🟢 Active")
        self.lbl_badge.setStyleSheet("background-color: #254336; color: #a6e3a1; border-radius: 4px; padding: 4px 8px; font-weight: bold;")
        title_box.addWidget(lbl_title)
        title_box.addStretch()
        title_box.addWidget(self.lbl_badge)
        main_layout.addLayout(title_box)

        # Card 1: Hardware & USB Power Autosuspend Status
        grp_hw = QGroupBox("⚡ Hardware & Power Optimization")
        hw_layout = QVBoxLayout()
        self.lbl_dev_name = QLabel("Device: Loading...")
        self.lbl_dev_path = QLabel("D-Bus Path: -")
        self.lbl_usb_power = QLabel("USB Autosuspend: Checking...")
        
        hw_layout.addWidget(self.lbl_dev_name)
        hw_layout.addWidget(self.lbl_dev_path)
        hw_layout.addWidget(self.lbl_usb_power)
        grp_hw.setLayout(hw_layout)
        main_layout.addWidget(grp_hw)

        # Card 2: Registered Fingerprints
        grp_enrolled = QGroupBox("🖐️ Enrolled Fingerprints")
        enrolled_layout = QVBoxLayout()
        self.lbl_enrolled_list = QLabel("Querying enrolled templates...")
        self.lbl_enrolled_list.setWordWrap(True)
        enrolled_layout.addWidget(self.lbl_enrolled_list)

        act_layout = QHBoxLayout()
        self.btn_enroll = QPushButton("➕ Enroll New Finger...")
        self.btn_enroll.setObjectName("primaryBtn")
        self.btn_enroll.clicked.connect(self.open_enrollment_dialog)

        self.btn_reset = QPushButton("🗑️ Reset All Templates")
        self.btn_reset.setObjectName("dangerBtn")
        self.btn_reset.clicked.connect(self.reset_templates)

        act_layout.addWidget(self.btn_enroll)
        act_layout.addWidget(self.btn_reset)
        enrolled_layout.addLayout(act_layout)

        grp_enrolled.setLayout(enrolled_layout)
        main_layout.addWidget(grp_enrolled)

        # Footer Actions
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
    # ASYNCHRONOUS QTHREAD WORKER HANDLERS
    # --------------------------------------------------------------------------
    def refresh_status(self):
        """Asynchronously query device and enrolled status without blocking main UI thread."""
        logger.info("Initiating asynchronous status query on worker QThread...")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("Refreshing...")

        # 1. Instantiate Thread and Worker
        self.status_thread = QThread()
        self.status_worker = StatusQueryWorker(self.fprint_mgr, self.username)

        # 2. Move worker to thread
        self.status_worker.moveToThread(self.status_thread)

        # 3. Connect Signals & Slots
        self.status_thread.started.connect(self.status_worker.run_task)
        self.status_worker.finished.connect(self.on_status_ready)
        self.status_worker.error.connect(self.on_status_error)

        # 4. Clean Teardown
        self.status_worker.finished.connect(self.status_thread.quit)
        self.status_worker.finished.connect(self.status_worker.deleteLater)
        self.status_thread.finished.connect(self.status_thread.deleteLater)

        # 5. Start Thread
        self.status_thread.start()

    def on_status_ready(self, data: dict):
        """Qt Slot called on main thread when StatusQueryWorker emits finished."""
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Refresh Status")

        # USB Power Autosuspend update
        if data.get("usb_power_optimized"):
            self.lbl_usb_power.setText("USB Power Autosuspend: 🔵 Disabled (Optimized via udev rule)")
            self.lbl_usb_power.setStyleSheet("color: #89b4fa; font-weight: bold;")
        else:
            self.lbl_usb_power.setText("USB Power Autosuspend: ⚠️ Default (May drop scans during sleep)")
            self.lbl_usb_power.setStyleSheet("color: #f9e2af;")

        # Device Info
        self.lbl_dev_name.setText(f"Device: {data.get('dev_name')}")
        self.lbl_dev_path.setText(f"D-Bus Path: {data.get('dev_path')}")

        # Enrolled Fingers
        fingers = data.get("enrolled_fingers", [])
        if fingers:
            friendly = [FINGER_MAP.get(f, f) for f in fingers]
            self.lbl_enrolled_list.setText(f"Registered for '{self.username}':\n• " + "\n• ".join(friendly))
            self.lbl_enrolled_list.setStyleSheet("color: #a6e3a1; font-weight: bold;")
            self.tray_icon.setToolTip(f"fprint-control-center: {len(fingers)} Finger(s) Enrolled")
        else:
            self.lbl_enrolled_list.setText(f"No fingerprint templates registered for '{self.username}'. Click '+ Enroll New Finger' to begin.")
            self.lbl_enrolled_list.setStyleSheet("color: #f9e2af;")
            self.tray_icon.setToolTip("fprint-control-center: No enrolled fingers")

    def on_status_error(self, err_msg: str):
        """Qt Slot called when StatusQueryWorker encounters an exception."""
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Refresh Status")
        self.lbl_enrolled_list.setText(f"Status query error: {err_msg}")

    def reset_templates(self):
        reply = QMessageBox.question(
            self,
            "Confirm Fingerprint Reset",
            f"Are you sure you want to delete all fingerprint templates for '{self.username}'?\n\nThis will execute 'fprintd-delete' and remove all enrolled scans.",
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
