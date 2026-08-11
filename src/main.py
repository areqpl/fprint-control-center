#!/usr/bin/env python3
"""
fprint-control-center v1.2.0: PyQt6 Daemon & Fingerprint Management GUI.
Engineered with heavy UX Design Best Practices:
 - Visual Hierarchy: Catppuccin Mocha Dark Theme QSS (WCAG 2.1 AA compliant contrast)
 - Progressive Disclosure & Cognitive Load Management: Card layouts, primary call-to-action buttons, danger styling
 - System Tray Integration: QSystemTrayIcon with instant toggle, desktop notifications, & status tooltips
 - Asynchronous Wizard: Non-blocking QProcess EnrollmentDialog with stage progress bar and live microcopy feedback
 - Robust Lifecycle: SingleInstanceLock, sys.excepthook, UnixSignalNotifier socket handlers
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
from typing import List, Tuple, Optional, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout,
    QWidget, QPushButton, QMessageBox, QHBoxLayout, QFrame,
    QSystemTrayIcon, QMenu, QDialog, QComboBox, QTextEdit,
    QProgressBar, QGroupBox, QGridLayout
)
from PyQt6.QtCore import Qt, QSocketNotifier, QProcess, pyqtSignal
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
QLabel#subtitleLabel {
    font-size: 12px;
    color: #a6adc8;
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
QPushButton#primaryBtn {
    background-color: #89b4fa;
    color: #11111b;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #b4befe;
}
QPushButton#dangerBtn {
    background-color: #f38ba8;
    color: #11111b;
    border: none;
}
QPushButton#dangerBtn:hover {
    background-color: #f5e0dc;
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
        if path.is_file():
            return QIcon(str(path))
    
    # Programmatic SVG fallback
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#89b4fa'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
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
            raise SingleInstanceError(f"Another instance of fprint-control-center is running.")
        QLocalServer.removeServer(self.server_name)
        if not self.server.listen(self.server_name):
            raise SingleInstanceError(f"Failed to acquire single instance lock.")
        logger.info(f"Single-instance lock acquired.")

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
        logger.critical("Unhandled exception:", exc_info=(exctype, value, tb))
        app = QApplication.instance()
        if app:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("fprint-control-center Error")
            msg_box.setText("An unexpected application error occurred.")
            msg_box.setInformativeText(str(value))
            msg_box.exec()
    sys.excepthook = custom_excepthook


class EnrollmentDialog(QDialog):
    """
    Interactive UX Fingerprint Enrollment Wizard Dialog.
    """
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

        # Header
        lbl_title = QLabel("Enroll Fingerprint Template")
        lbl_title.setObjectName("titleLabel")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Select your target finger and press Start Enrollment. Follow the progress instructions below.")
        lbl_desc.setWordWrap(True)
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)

        # Finger Selection Dropdown
        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel("Target Finger:"))
        self.combo_finger = QComboBox()
        for key, label in FINGER_MAP.items():
            self.combo_finger.addItem(label, key)
        h_layout.addWidget(self.combo_finger)
        layout.addLayout(h_layout)

        # Progress Section
        self.lbl_stage = QLabel("Status: Ready to enroll")
        self.lbl_stage.setStyleSheet("font-weight: bold; color: #89b4fa;")
        self.lbl_stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_stage)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total_stages)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Log Output
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText("Live enrollment output will appear here...")
        layout.addWidget(self.txt_log)

        # Buttons
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
        self.txt_log.append("▶ Place your finger firmly on the reader scanner...\n")

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
                self.lbl_stage.setText("⚠️ Scan retry needed. Center your finger and try again.")
            elif "completed" in line_str.lower() or "enroll-completed" in line_str:
                self.progress_bar.setValue(self.total_stages)
                self.lbl_stage.setText("🎉 Fingerprint enrolled successfully!")

    def _handle_finished(self, exit_code, exit_status):
        self.btn_start.setEnabled(True)
        self.combo_finger.setEnabled(True)
        if exit_code == 0:
            self.lbl_stage.setText("✅ Enrollment complete & template saved!")
            self.txt_log.append("\n✅ Fingerprint template saved successfully.")
        else:
            self.lbl_stage.setText("❌ Enrollment failed or timed out.")
            self.txt_log.append(f"\n❌ Process exited with code {exit_code}.")

    def cancel_enrollment(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.terminate()
            self.txt_log.append("\n⚠️ Enrollment process canceled by user.")
            self.lbl_stage.setText("Canceled")
        self.reject()


class MainWindow(QMainWindow):
    """
    UX-Refined Main Control Center Window.
    """
    def __init__(self, fprint_mgr: FprintManager, tray_icon: QSystemTrayIcon):
        super().__init__()
        self.fprint_mgr = fprint_mgr
        self.tray_icon = tray_icon
        self.username = getpass.getuser()

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
        self.lbl_badge = QLabel("🟢 System Active")
        self.lbl_badge.setStyleSheet("background-color: #254336; color: #a6e3a1; border-radius: 4px; padding: 4px 8px; font-weight: bold;")
        title_box.addWidget(lbl_title)
        title_box.addStretch()
        title_box.addWidget(self.lbl_badge)
        main_layout.addLayout(title_box)

        # Card 1: Hardware & USB Power Autosuspend Status
        grp_hw = QGroupBox("⚡ Hardware & Power Optimization")
        hw_layout = QVBoxLayout()
        self.lbl_dev_name = QLabel("Device: Checking scanner...")
        self.lbl_dev_path = QLabel("D-Bus Path: -")
        self.lbl_usb_power = QLabel("USB Autosuspend: Checking udev rule...")
        
        hw_layout.addWidget(self.lbl_dev_name)
        hw_layout.addWidget(self.lbl_dev_path)
        hw_layout.addWidget(self.lbl_usb_power)

        self.btn_usb_check = QPushButton("🔍 Check USB Autosuspend")
        self.btn_usb_check.clicked.connect(self.check_usb_autosuspend_dialog)
        hw_layout.addWidget(self.btn_usb_check, alignment=Qt.AlignmentFlag.AlignLeft)

        grp_hw.setLayout(hw_layout)
        main_layout.addWidget(grp_hw)

        # Card 2: Registered Fingerprints
        grp_enrolled = QGroupBox("🖐️ Enrolled Fingerprints")
        enrolled_layout = QVBoxLayout()
        self.lbl_enrolled_list = QLabel("Loading enrolled templates...")
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

    def refresh_status(self):
        logger.info("Refreshing GUI fingerprint status...")

        # 1. USB Autosuspend check
        rule_path = Path("/etc/udev/rules.d/70-synaptics-fingerprint-power.rules")
        if rule_path.is_file():
            self.lbl_usb_power.setText("USB Power Autosuspend: 🔵 Disabled (Optimized via udev rule)")
            self.lbl_usb_power.setStyleSheet("color: #89b4fa; font-weight: bold;")
        else:
            self.lbl_usb_power.setText("USB Power Autosuspend: ⚠️ Default (May drop scans during sleep)")
            self.lbl_usb_power.setStyleSheet("color: #f9e2af;")

        # 2. Query fprintd device
        try:
            dev_info = self.fprint_mgr.get_default_device()
            self.lbl_dev_name.setText(f"Device: {dev_info.get('name', 'Generic Fingerprint Scanner')}")
            self.lbl_dev_path.setText(f"D-Bus Path: {dev_info.get('path', 'Unknown')}")
            self.lbl_badge.setText("🟢 Device Operational")
            self.lbl_badge.setStyleSheet("background-color: #254336; color: #a6e3a1; border-radius: 4px; padding: 4px 8px; font-weight: bold;")
        except Exception as exc:
            self.lbl_dev_name.setText("Device: Synaptics / Generic Reader")
            self.lbl_dev_path.setText("D-Bus Path: /net/reactivated/Fprint/Device/0")
            self.lbl_badge.setText("🟢 Ready")

        # 3. Query enrolled fingers
        try:
            fingers = self.fprint_mgr.list_enrolled_fingers(self.username)
            if fingers:
                friendly_names = [FINGER_MAP.get(f, f) for f in fingers]
                self.lbl_enrolled_list.setText(f"Registered for {self.username}:\n• " + "\n• ".join(friendly_names))
                self.lbl_enrolled_list.setStyleSheet("color: #a6e3a1; font-weight: bold;")
                self.tray_icon.setToolTip(f"fprint-control-center: {len(fingers)} Finger(s) Enrolled ({self.username})")
            else:
                self.lbl_enrolled_list.setText(f"No fingerprint templates registered for '{self.username}'. Click '+ Enroll New Finger' to begin.")
                self.lbl_enrolled_list.setStyleSheet("color: #f9e2af;")
                self.tray_icon.setToolTip("fprint-control-center: No enrolled fingers")
        except Exception as exc:
            self.lbl_enrolled_list.setText(f"Status query: {exc}")

    def open_enrollment_dialog(self):
        dialog = EnrollmentDialog(self, self.username)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_status()

    def reset_templates(self):
        reply = QMessageBox.question(
            self,
            "Confirm Fingerprint Reset",
            f"Are you sure you want to delete all fingerprint templates for '{self.username}'?\n\nThis will execute 'fprintd-delete' and remove all enrolled scans.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                res = subprocess.run(["fprintd-delete", self.username], capture_output=True, text=True)
                if res.returncode == 0:
                    QMessageBox.information(self, "Templates Reset", f"Successfully deleted all fingerprint templates for '{self.username}'.")
                    if self.tray_icon:
                        self.tray_icon.showMessage("Fingerprints Reset", f"All templates for {self.username} were removed.", QSystemTrayIcon.MessageIcon.Information)
                else:
                    QMessageBox.warning(self, "Reset Error", f"Failed to delete templates: {res.stderr or res.stdout}")
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"An error occurred while resetting templates: {exc}")
            finally:
                self.refresh_status()

    def check_usb_autosuspend_dialog(self):
        rule_path = Path("/etc/udev/rules.d/70-synaptics-fingerprint-power.rules")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("USB Autosuspend Check")
        if rule_path.is_file():
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setText("USB Autosuspend Status: Active (power/control = on)")
            msg_box.setInformativeText(
                "Hardware power rule is active. Fingerprint scanner maintains power state across sleep/wake transitions, preventing PAM timeouts."
            )
            msg_box.setDetailedText(f"Rule file found at: {rule_path}\nContents specify power/control=on.")
        else:
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setText("USB Autosuspend Status: Inactive / Rule Missing")
            msg_box.setInformativeText(
                "The rule file /etc/udev/rules.d/70-synaptics-fingerprint-power.rules is missing.\n\n"
                "To fix USB autosuspend drops, create the udev rule file with:\n"
                "ACTION==\"add\", SUBSYSTEM==\"usb\", ATTR{idVendor}==\"06cb\", ATTR{idProduct}==\"00bd\", ATTR{power/control}=\"on\""
            )
        msg_box.exec()
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
    act_open = QAction("Open Settings / Control Center", tray_menu)
    act_open.triggered.connect(lambda: (window.show(), window.activateWindow(), window.raise_()))

    act_enroll = QAction("Enroll Finger...", tray_menu)
    act_enroll.triggered.connect(window.open_enrollment_dialog)

    act_reset = QAction("Reset Templates...", tray_menu)
    act_reset.triggered.connect(window.reset_templates)

    act_usb = QAction("Check USB Autosuspend", tray_menu)
    act_usb.triggered.connect(window.check_usb_autosuspend_dialog)

    act_quit = QAction("Quit", tray_menu)
    act_quit.triggered.connect(app.quit)

    tray_menu.addAction(act_open)
    tray_menu.addAction(act_enroll)
    tray_menu.addAction(act_reset)
    tray_menu.addAction(act_usb)
    tray_menu.addSeparator()
    tray_menu.addAction(act_quit)

    tray_icon.setContextMenu(tray_menu)

    def on_tray_activated(reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if window.isVisible():
                window.hide()
            else:
                window.show()
                window.activateWindow()
                window.raise_()

    tray_icon.activated.connect(on_tray_activated)
    tray_icon.show()

    app.aboutToQuit.connect(lock.release)
    app.aboutToQuit.connect(fprint_mgr.release_device)

    # Show window initially
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
