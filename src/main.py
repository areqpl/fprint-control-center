#!/usr/bin/env python3
"""
fprint-control-center: PyQt6 daemon & GUI application for fprintd fingerprint devices.
Features single-instance lock socket, sys.excepthook logging, UNIX signal socket handling,
and D-Bus exponential backoff retry.
"""

import sys
import os
import signal
import socket
import logging
import getpass
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout,
    QWidget, QPushButton, QMessageBox, QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt, QSocketNotifier
from PyQt6.QtGui import QIcon
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


class SingleInstanceLock:
    """
    Single-instance enforcement using QLocalServer and lock socket.
    """
    def __init__(self, app_name: str = "fprint-control-center"):
        username = getpass.getuser()
        self.server_name = f"{app_name}-lock-{username}"
        self.server = QLocalServer()

    def acquire(self) -> None:
        """
        Attempt to acquire single instance lock.
        Raises SingleInstanceError if another instance is already running.
        """
        # Test if an existing server is actively listening
        test_socket = QLocalSocket()
        test_socket.connectToServer(self.server_name)
        if test_socket.waitForConnected(500):
            test_socket.disconnectFromServer()
            raise SingleInstanceError(
                f"Another instance of fprint-control-center is already running (socket '{self.server_name}')."
            )

        # Cleanup potential stale socket file from prior unclean shutdown
        QLocalServer.removeServer(self.server_name)

        # Attempt to listen on the local server socket
        if not self.server.listen(self.server_name):
            raise SingleInstanceError(
                f"Failed to start single-instance lock server on '{self.server_name}': {self.server.errorString()}"
            )
        logger.info(f"Single-instance lock successfully acquired on socket '{self.server_name}'.")

    def release(self) -> None:
        """Close server and release lock socket."""
        if self.server.isListening():
            self.server.close()
            QLocalServer.removeServer(self.server_name)
            logger.info("Single-instance lock released.")


class UnixSignalNotifier:
    """
    UNIX signal handler using QSocketNotifier for clean Qt event loop shutdown.
    Handles SIGINT, SIGTERM, and SIGHUP.
    """
    def __init__(self, app: QApplication):
        self.app = app
        # Create non-blocking UNIX socket pair
        self.read_fd, self.write_fd = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM, 0)
        os.set_blocking(self.write_fd, False)
        os.set_blocking(self.read_fd, False)

        # Setup Qt socket notifier on the read descriptor
        self.notifier = QSocketNotifier(self.read_fd, QSocketNotifier.Type.Read)
        self.notifier.activated.connect(self._handle_signal)

        # Register signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, self._signal_handler_func)
        logger.info("UNIX signal handlers (SIGINT, SIGTERM, SIGHUP) initialized.")

    def _signal_handler_func(self, signum, frame):
        """Signal handler callback writing to socket pair."""
        try:
            os.write(self.write_fd, bytes([signum]))
        except OSError:
            pass

    def _handle_signal(self):
        """Qt slot activated when signal byte is read from socket."""
        self.notifier.setEnabled(False)
        try:
            data = os.read(self.read_fd, 1024)
            if data:
                signum = data[0]
                try:
                    sig_name = signal.Signals(signum).name
                except Exception:
                    sig_name = str(signum)
                logger.info(f"Received UNIX signal {sig_name} ({signum}). Initiating clean shutdown...")
        except OSError:
            pass
        finally:
            self.app.quit()


def setup_exception_hook():
    """
    Set up sys.excepthook to log unhandled UI exceptions to systemd journal / logging
    and prevent silent UI crashes.
    """
    def custom_excepthook(exctype, value, tb):
        if issubclass(exctype, KeyboardInterrupt):
            sys.__excepthook__(exctype, value, tb)
            return

        logger.critical(
            "Unhandled exception caught by sys.excepthook:",
            exc_info=(exctype, value, tb)
        )

        app = QApplication.instance()
        if app:
            err_msg = "".join(traceback.format_exception(exctype, value, tb))
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("fprint-control-center Error")
            msg_box.setText("An unexpected application error occurred.")
            msg_box.setInformativeText(str(value))
            msg_box.setDetailedText(err_msg)
            msg_box.exec()

    sys.excepthook = custom_excepthook
    logger.info("sys.excepthook exception handler registered.")


class MainWindow(QMainWindow):
    """
    Main application UI window for Fingerprint Control Center.
    """
    def __init__(self, fprint_mgr: FprintManager):
        super().__init__()
        self.fprint_mgr = fprint_mgr
        self.setWindowTitle('Fingerprint Control Center')
        self.resize(500, 360)

        # Set window icon
        icon_path = Path('/usr/share/pixmaps/fprint-control-center.png')
        if not icon_path.is_file():
            icon_path = Path(__file__).resolve().parent.parent / 'resources' / 'icon.png'
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._init_ui()
        self.refresh_status()

    def _init_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Header Label
        title_label = QLabel("Fingerprint Device Status")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Status Frame
        self.status_frame = QFrame()
        self.status_frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout()

        self.lbl_device_name = QLabel("Device: Initializing...")
        self.lbl_device_path = QLabel("D-Bus Path: -")
        self.lbl_enrolled = QLabel("Enrolled Fingers: -")
        self.lbl_status = QLabel("Status: Checking fprintd service...")

        for lbl in (self.lbl_device_name, self.lbl_device_path, self.lbl_enrolled, self.lbl_status):
            lbl.setWordWrap(True)
            frame_layout.addWidget(lbl)

        self.status_frame.setLayout(frame_layout)
        layout.addWidget(self.status_frame)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh Status")
        self.btn_refresh.clicked.connect(self.refresh_status)
        self.btn_quit = QPushButton("Quit")
        self.btn_quit.clicked.connect(QApplication.instance().quit)

        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_quit)
        layout.addLayout(btn_layout)

        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def refresh_status(self):
        """Query fprintd status and update UI labels."""
        logger.info("Refreshing fingerprint device status...")
        try:
            if not self.fprint_mgr.is_service_available():
                self.lbl_device_name.setText("Device: None")
                self.lbl_device_path.setText("D-Bus Path: N/A")
                self.lbl_enrolled.setText("Enrolled Fingers: None")
                self.lbl_status.setText("Status: fprintd D-Bus service is inactive or not installed.")
                return

            dev_info = self.fprint_mgr.get_default_device()
            self.lbl_device_name.setText(f"Device: {dev_info.get('name', 'Unknown')}")
            self.lbl_device_path.setText(f"D-Bus Path: {dev_info.get('path', 'Unknown')}")

            username = getpass.getuser()
            fingers = self.fprint_mgr.list_enrolled_fingers(username)
            if fingers:
                self.lbl_enrolled.setText(f"Enrolled Fingers ({username}): {', '.join(fingers)}")
            else:
                self.lbl_enrolled.setText(f"Enrolled Fingers ({username}): None registered")

            self.lbl_status.setText("Status: Device operational & connected.")

        except DeviceNotFoundError as exc:
            logger.warning(f"Device not found during refresh: {exc}")
            self.lbl_device_name.setText("Device: No scanner found")
            self.lbl_device_path.setText("D-Bus Path: N/A")
            self.lbl_enrolled.setText("Enrolled Fingers: N/A")
            self.lbl_status.setText(f"Status: {exc.message}")
        except DBusCommunicationError as exc:
            logger.error(f"D-Bus error during refresh: {exc}")
            self.lbl_status.setText(f"Status Error: {exc.message}")
        except Exception as exc:
            logger.error(f"Unexpected error during status refresh: {exc}")
            self.lbl_status.setText(f"Status Error: {exc}")


def main():
    setup_exception_hook()

    app = QApplication(sys.argv)
    app.setApplicationName("Fingerprint Control Center")
    app.setOrganizationName("fprint-control-center")

    # Single-instance enforcement
    lock = SingleInstanceLock()
    try:
        lock.acquire()
    except SingleInstanceError as exc:
        logger.error(f"Single instance check failed: {exc}")
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("fprint-control-center Already Running")
        msg_box.setText(str(exc))
        msg_box.exec()
        sys.exit(1)

    # Initialize UNIX signal notifier for clean shutdown
    signal_notifier = UnixSignalNotifier(app)

    # Initialize fprintd manager
    fprint_mgr = FprintManager()

    # Clean shutdown cleanup callback
    app.aboutToQuit.connect(lock.release)
    app.aboutToQuit.connect(fprint_mgr.release_device)

    # Launch GUI Window
    window = MainWindow(fprint_mgr)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
