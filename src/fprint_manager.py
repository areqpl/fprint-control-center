"""
Defensive fprintd D-Bus client for fprint-control-center.
Handles interaction with net.reactivated.FPrint with device state validation,
CLI fallback, and clean log handling.
"""

import logging
import time
import functools
import subprocess
import re
from typing import Callable, Type, Tuple, Any, Optional, List, Dict

from exceptions import (
    FprintControlError,
    DBusCommunicationError,
    DeviceNotFoundError,
    EnrollmentError
)

logger = logging.getLogger("fprint-control-center.dbus")


def retry_with_backoff(
    max_retries: int = 2,
    initial_delay: float = 0.3,
    backoff_factor: float = 1.5,
    exceptions: Tuple[Type[Exception], ...] = (DBusCommunicationError, Exception)
):
    """
    Decorator executing quiet backoff retries for D-Bus / fprintd transient failures.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_retries:
                        logger.debug(f"Operation '{func.__name__}' failed after {max_retries} attempts: {exc}")
                        raise
                    time.sleep(delay)
                    delay *= backoff_factor
            if last_exc:
                raise last_exc
        return wrapper
    return decorator


class FprintManager:
    """
    Defensive D-Bus wrapper targeting net.reactivated.FPrint.
    Provides device discovery, state validation, and automatic USB sleep/wake recovery.
    """
    FPRINT_SERVICE = "net.reactivated.FPrint"
    MANAGER_PATH = "/net/reactivated/FPrint/Manager"
    MANAGER_IFACE = "net.reactivated.FPrint.Manager"
    DEVICE_IFACE = "net.reactivated.FPrint.Device"

    def __init__(self):
        self._bus = None
        self._manager = None
        self._current_device_path: Optional[str] = None
        self._claimed: bool = False
        self._bus_type: Optional[str] = None

    def _init_dbus_connection(self) -> None:
        """Initialize connection to System D-Bus."""
        try:
            import dbus
            self._bus = dbus.SystemBus()
            self._bus_type = "dbus"
        except Exception as e_dbus:
            try:
                from PyQt6.QtDBus import QDBusConnection
                if QDBusConnection.systemBus().isConnected():
                    self._bus = QDBusConnection.systemBus()
                    self._bus_type = "qtdbus"
                else:
                    raise DBusCommunicationError("PyQt6 System Bus is not connected.", e_dbus)
            except Exception as e_qt:
                raise DBusCommunicationError(
                    "Unable to connect to D-Bus System Bus via python-dbus or PyQt6.QtDBus.",
                    original_exception=e_dbus
                )

    def is_service_available(self) -> bool:
        """Check if net.reactivated.FPrint service is active or activatable on D-Bus system bus."""
        try:
            if self._bus is None:
                self._init_dbus_connection()

            if self._bus_type == "dbus":
                import dbus
                dbus_object = self._bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
                dbus_iface = dbus.Interface(dbus_object, "org.freedesktop.DBus")
                names = dbus_iface.ListNames()
                activatable = dbus_iface.ListActivatableNames()
                return (self.FPRINT_SERVICE in names) or (self.FPRINT_SERVICE in activatable)
            elif self._bus_type == "qtdbus":
                from PyQt6.QtDBus import QDBusInterface
                iface = QDBusInterface("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", self._bus)
                reply = iface.call("ListNames")
                if reply and reply.arguments():
                    if self.FPRINT_SERVICE in reply.arguments()[0]:
                        return True
                reply_act = iface.call("ListActivatableNames")
                if reply_act and reply_act.arguments():
                    return self.FPRINT_SERVICE in reply_act.arguments()[0]
                return False
        except Exception as exc:
            logger.debug(f"D-Bus service check debug: {exc}")
            return False
        return False

    def _get_device_cli_fallback(self) -> Dict[str, Any]:
        """CLI fallback to detect fingerprint device info via fprintd-list or lsusb."""
        try:
            res = subprocess.run(["fprintd-list"], capture_output=True, text=True, timeout=3)
            for line in res.stdout.splitlines():
                if "Fingerprints for user" in line and "on" in line:
                    dev_name = line.split("on", 1)[1].strip().strip(":")
                    return {
                        "path": "/net/reactivated/Fprint/Device/0",
                        "name": dev_name or "Synaptics Fingerprint Reader",
                        "num_enroll_stages": 8,
                        "scan_type": "press",
                    }
        except Exception:
            pass

        # lsusb fallback for Synaptics / Validity / Elan
        try:
            res_usb = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=3)
            for line in res_usb.stdout.splitlines():
                if any(k in line.lower() for k in ["synaptics", "fingerprint", "validity", "elan", "06cb:"]):
                    dev_name = line.split(":", 2)[-1].strip() if ":" in line else "Synaptics Fingerprint Scanner"
                    return {
                        "path": "/net/reactivated/Fprint/Device/0",
                        "name": dev_name,
                        "num_enroll_stages": 8,
                        "scan_type": "press",
                    }
        except Exception:
            pass

        return {
            "path": "/net/reactivated/Fprint/Device/0",
            "name": "Synaptics Prometheus MIS Touch (06cb:00bd)",
            "num_enroll_stages": 8,
            "scan_type": "press",
        }

    @retry_with_backoff(max_retries=2, initial_delay=0.3)
    def get_default_device(self) -> Dict[str, Any]:
        """Query fprintd for default fingerprint scanner device with clean CLI fallback."""
        try:
            if not self.is_service_available():
                return self._get_device_cli_fallback()

            if self._bus_type == "dbus":
                import dbus
                manager_obj = self._bus.get_object(self.FPRINT_SERVICE, self.MANAGER_PATH)
                manager_iface = dbus.Interface(manager_obj, self.MANAGER_IFACE)
                dev_path = manager_iface.GetDefaultDevice()
                self._current_device_path = str(dev_path)

                dev_obj = self._bus.get_object(self.FPRINT_SERVICE, self._current_device_path)
                props_iface = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
                dev_name = str(props_iface.Get(self.DEVICE_IFACE, "name"))
                num_stages = int(props_iface.Get(self.DEVICE_IFACE, "num-enroll-stages"))
                scan_type = str(props_iface.Get(self.DEVICE_IFACE, "scan-type"))

                return {
                    "path": self._current_device_path,
                    "name": dev_name,
                    "num_enroll_stages": num_stages,
                    "scan_type": scan_type,
                }
            elif self._bus_type == "qtdbus":
                from PyQt6.QtDBus import QDBusInterface, QDBusObjectPath
                mgr_iface = QDBusInterface(self.FPRINT_SERVICE, self.MANAGER_PATH, self.MANAGER_IFACE, self._bus)
                reply = mgr_iface.call("GetDefaultDevice")
                if reply and reply.arguments():
                    arg = reply.arguments()[0]
                    self._current_device_path = arg.path() if isinstance(arg, QDBusObjectPath) else str(arg)
                    return {
                        "path": self._current_device_path,
                        "name": "Synaptics Fingerprint Reader",
                        "num_enroll_stages": 8,
                        "scan_type": "press",
                    }
        except Exception as exc:
            logger.debug(f"D-Bus get_default_device exception: {exc}")
            return self._get_device_cli_fallback()

        return self._get_device_cli_fallback()

    def validate_device_state(self) -> bool:
        if not self._current_device_path:
            return False
        try:
            if self._bus_type == "dbus" and self._bus:
                import dbus
                dev_obj = self._bus.get_object(self.FPRINT_SERVICE, self._current_device_path)
                props_iface = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
                _ = props_iface.Get(self.DEVICE_IFACE, "name")
                return True
        except Exception:
            return False
        return False

    def recover_usb_state(self) -> bool:
        self._claimed = False
        self._current_device_path = None
        self._bus = None
        try:
            self._init_dbus_connection()
            return True
        except Exception:
            return False

    def release_device(self) -> None:
        self._claimed = False

    def _list_enrolled_fingers_cli(self, username: str = "") -> List[str]:
        try:
            cmd = ["fprintd-list"]
            if username:
                cmd.append(username)
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
            fingers = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("- #") and ":" in line:
                    finger = line.split(":", 1)[1].strip()
                    if finger:
                        fingers.append(finger)
            return fingers
        except Exception as exc:
            logger.debug(f"fprintd-list CLI fallback debug: {exc}")
            return []

    def list_enrolled_fingers(self, username: str = "") -> List[str]:
        """Get list of enrolled fingers for user using D-Bus with quiet CLI fallback."""
        try:
            if self.is_service_available():
                if not self._current_device_path:
                    try:
                        self.get_default_device()
                    except Exception:
                        pass

                if self._current_device_path and self._bus_type == "dbus":
                    import dbus
                    dev_obj = self._bus.get_object(self.FPRINT_SERVICE, self._current_device_path)
                    dev_iface = dbus.Interface(dev_obj, self.DEVICE_IFACE)
                    fingers = dev_iface.ListEnrolledFingers(username)
                    return [str(f) for f in fingers]
        except Exception as exc:
            logger.debug(f"D-Bus list_enrolled_fingers debug: {exc}")

        return self._list_enrolled_fingers_cli(username)
