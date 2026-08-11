"""
Defensive fprintd D-Bus client for fprint-control-center.
Handles interaction with net.reactivated.FPrint with device state validation
and USB sleep/wake recovery.
"""

import logging
import time
import functools
from typing import Callable, Type, Tuple, Any, Optional, List, Dict

from exceptions import (
    FprintControlError,
    DBusCommunicationError,
    DeviceNotFoundError,
    EnrollmentError
)

logger = logging.getLogger("fprint-control-center.dbus")


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (DBusCommunicationError, Exception)
):
    """
    Decorator executing exponential backoff retries for D-Bus / fprintd transient failures.
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
                        logger.error(
                            f"Operation '{func.__name__}' failed after {max_retries} attempts: {exc}"
                        )
                        raise
                    logger.warning(
                        f"Attempt {attempt}/{max_retries} for '{func.__name__}' failed: {exc}. "
                        f"Retrying in {delay:.2f}s..."
                    )
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
            logger.info("Connected to D-Bus system bus via dbus-python.")
        except Exception as e_dbus:
            try:
                from PyQt6.QtDBus import QDBusConnection
                if QDBusConnection.systemBus().isConnected():
                    self._bus = QDBusConnection.systemBus()
                    self._bus_type = "qtdbus"
                    logger.info("Connected to D-Bus system bus via PyQt6.QtDBus.")
                else:
                    raise DBusCommunicationError("PyQt6 System Bus is not connected.", e_dbus)
            except Exception as e_qt:
                raise DBusCommunicationError(
                    "Unable to connect to D-Bus System Bus via python-dbus or PyQt6.QtDBus.",
                    original_exception=e_dbus
                )

    def is_service_available(self) -> bool:
        """Check if net.reactivated.FPrint service is present on the D-Bus system bus."""
        try:
            if self._bus is None:
                self._init_dbus_connection()

            if self._bus_type == "dbus":
                import dbus
                dbus_object = self._bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
                dbus_iface = dbus.Interface(dbus_object, "org.freedesktop.DBus")
                names = dbus_iface.ListNames()
                return self.FPRINT_SERVICE in names
            elif self._bus_type == "qtdbus":
                from PyQt6.QtDBus import QDBusInterface
                iface = QDBusInterface(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    self._bus
                )
                reply = iface.call("ListNames")
                if reply and reply.arguments():
                    return self.FPRINT_SERVICE in reply.arguments()[0]
                return False
        except Exception as exc:
            logger.warning(f"Error checking D-Bus service availability: {exc}")
            return False
        return False

    @retry_with_backoff(max_retries=3, initial_delay=0.5, backoff_factor=2.0)
    def get_default_device(self) -> Dict[str, Any]:
        """
        Query fprintd for the default fingerprint scanner device with defensive backoff.
        """
        if not self.is_service_available():
            raise DBusCommunicationError("fprintd D-Bus service (net.reactivated.FPrint) is not available.")

        try:
            if self._bus_type == "dbus":
                import dbus
                manager_obj = self._bus.get_object(self.FPRINT_SERVICE, self.MANAGER_PATH)
                manager_iface = dbus.Interface(manager_obj, self.MANAGER_IFACE)
                dev_path = manager_iface.GetDefaultDevice()
                self._current_device_path = str(dev_path)

                # Fetch device details
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
                mgr_iface = QDBusInterface(
                    self.FPRINT_SERVICE,
                    self.MANAGER_PATH,
                    self.MANAGER_IFACE,
                    self.INVALID_BUS if hasattr(self, 'INVALID_BUS') else self._bus
                )
                reply = mgr_iface.call("GetDefaultDevice")
                if reply and reply.arguments():
                    arg = reply.arguments()[0]
                    self._current_device_path = arg.path() if isinstance(arg, QDBusObjectPath) else str(arg)
                    return {
                        "path": self._current_device_path,
                        "name": "Generic Fingerprint Reader",
                        "num_enroll_stages": 5,
                        "scan_type": "press",
                    }
                raise DeviceNotFoundError("No default fingerprint device returned by D-Bus.")
        except Exception as exc:
            if "NoDevice" in str(exc) or "NoSuchObject" in str(exc):
                raise DeviceNotFoundError("No fingerprint device detected by fprintd.", original_exception=exc)
            raise DBusCommunicationError("Failed to retrieve default fingerprint device via D-Bus.", original_exception=exc)

    def validate_device_state(self) -> bool:
        """
        Validate that the currently tracked device object is still accessible on D-Bus.
        """
        if not self._current_device_path:
            return False
        try:
            if self._bus_type == "dbus" and self._bus:
                import dbus
                dev_obj = self._bus.get_object(self.FPRINT_SERVICE, self._current_device_path)
                props_iface = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
                _ = props_iface.Get(self.DEVICE_IFACE, "name")
                return True
            elif self._bus_type == "qtdbus" and self._bus:
                from PyQt6.QtDBus import QDBusInterface
                dev_iface = QDBusInterface(
                    self.FPRINT_SERVICE,
                    self._current_device_path,
                    "org.freedesktop.DBus.Properties",
                    self._bus
                )
                reply = dev_iface.call("Get", self.DEVICE_IFACE, "name")
                return reply.isValid()
        except Exception as exc:
            logger.warning(f"Device state validation failed: {exc}")
            return False
        return False

    def recover_usb_state(self) -> bool:
        """
        USB Sleep/Wake recovery handler.
        Invalidates broken D-Bus connection references, resets state, and reconnects to D-Bus.
        """
        logger.info("Executing USB sleep/wake recovery protocol...")
        self._claimed = False
        self._current_device_path = None
        self._bus = None

        try:
            self._init_dbus_connection()
            if self.is_service_available():
                info = self.get_default_device()
                logger.info(f"USB recovery successful. Found device: {info.get('name')} at {info.get('path')}")
                return True
            else:
                logger.error("USB recovery failed: fprintd D-Bus service is not responding.")
                return False
        except Exception as exc:
            logger.error(f"USB recovery failed with exception: {exc}")
            return False

    @retry_with_backoff(max_retries=3, initial_delay=0.5, backoff_factor=2.0)
    def claim_device(self, username: str = "") -> None:
        """
        Claim fingerprint device for exclusive access with USB state validation.
        """
        if not self.validate_device_state():
            if not self.recover_usb_state():
                raise DeviceNotFoundError("Cannot claim device: Device state validation and USB recovery failed.")

        try:
            if self._bus_type == "dbus":
                import dbus
                dev_obj = self._bus.get_object(self.FPRINT_SERVICE, self._current_device_path)
                dev_iface = dbus.Interface(dev_obj, self.DEVICE_IFACE)
                dev_iface.Claim(username)
                self._claimed = True
                logger.info(f"Successfully claimed fingerprint device for user '{username}'.")
            elif self._bus_type == "qtdbus":
                from PyQt6.QtDBus import QDBusInterface
                dev_iface = QDBusInterface(
                    self.FPRINT_SERVICE,
                    self._current_device_path,
                    self.DEVICE_IFACE,
                    self._bus
                )
                reply = dev_iface.call("Claim", username)
                if reply.type() == reply.ResponseType.ErrorMessage:
                    raise DBusCommunicationError(f"D-Bus error claiming device: {reply.errorMessage()}")
                self._claimed = True
                logger.info(f"Successfully claimed fingerprint device for user '{username}'.")
        except Exception as exc:
            if "AlreadyInUse" in str(exc) or "Claimed" in str(exc):
                logger.warning(f"Device was already claimed: {exc}")
                self._claimed = True
                return
            raise DBusCommunicationError("Failed to claim fingerprint device.", original_exception=exc)

    def release_device(self) -> None:
        """
        Release exclusive access to fingerprint device.
        """
        if not self._claimed or not self._current_device_path:
            return
        try:
            if self._bus_type == "dbus" and self._bus:
                import dbus
                dev_obj = self._bus.get_object(self.FPRINT_SERVICE, self._current_device_path)
                dev_iface = dbus.Interface(dev_obj, self.DEVICE_IFACE)
                dev_iface.Release()
                logger.info("Released fingerprint device.")
            elif self._bus_type == "qtdbus" and self._bus:
                from PyQt6.QtDBus import QDBusInterface
                dev_iface = QDBusInterface(
                    self.FPRINT_SERVICE,
                    self._current_device_path,
                    self.DEVICE_IFACE,
                    self._bus
                )
                dev_iface.call("Release")
                logger.info("Released fingerprint device.")
        except Exception as exc:
            logger.warning(f"Error releasing fingerprint device: {exc}")
        finally:
            self._claimed = False

    def _list_enrolled_fingers_cli(self, username: str = "") -> List[str]:
        import subprocess
        try:
            cmd = ["fprintd-list"]
            if username:
                cmd.append(username)
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            fingers = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("- #") and ":" in line:
                    finger = line.split(":", 1)[1].strip()
                    if finger:
                        fingers.append(finger)
            return fingers
        except Exception as exc:
            logger.warning(f"fprintd-list CLI fallback failed: {exc}")
            return []

    @retry_with_backoff(max_retries=2, initial_delay=0.5)
    def list_enrolled_fingers(self, username: str = "") -> List[str]:
        """
        Get list of enrolled fingers for specified user.
        """
        if not self.validate_device_state():
            self.recover_usb_state()

        if not self._current_device_path:
            try:
                self.get_default_device()
            except Exception:
                pass

        if not self._current_device_path:
            return self._list_enrolled_fingers_cli(username)

        try:
            if self._bus_type == "dbus":
                import dbus
                dev_obj = self._bus.get_object(self.FPRINT_SERVICE, self._current_device_path)
                dev_iface = dbus.Interface(dev_obj, self.DEVICE_IFACE)
                fingers = dev_iface.ListEnrolledFingers(username)
                return [str(f) for f in fingers]
            elif self._bus_type == "qtdbus":
                from PyQt6.QtDBus import QDBusInterface
                dev_iface = QDBusInterface(
                    self.FPRINT_SERVICE,
                    self._current_device_path,
                    self.DEVICE_IFACE,
                    self._bus
                )
                reply = dev_iface.call("ListEnrolledFingers", username)
                if reply.isValid() and reply.arguments():
                    return [str(f) for f in reply.arguments()[0]]
                return self._list_enrolled_fingers_cli(username)
        except Exception as exc:
            if "NoEnrolledFingers" in str(exc):
                return []
            logger.warning(f"D-Bus list_enrolled_fingers failed ({exc}), attempting CLI fallback...")
            return self._list_enrolled_fingers_cli(username)
        return []
