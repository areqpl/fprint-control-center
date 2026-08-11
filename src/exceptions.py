"""
Custom domain exception hierarchy for fprint-control-center.
"""

class FprintControlError(Exception):
    """Base exception for all fprint-control-center errors."""
    def __init__(self, message: str = "An error occurred in fprint-control-center", original_exception: Exception = None):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception

    def __str__(self) -> str:
        if self.original_exception:
            return f"{self.message} (Caused by: {type(self.original_exception).__name__}: {self.original_exception})"
        return self.message


class SingleInstanceError(FprintControlError):
    """Raised when another instance of fprint-control-center is already running."""
    def __init__(self, message: str = "Another instance of fprint-control-center is already running."):
        super().__init__(message)


class DBusCommunicationError(FprintControlError):
    """Raised when D-Bus communication with fprintd or system bus fails."""
    def __init__(self, message: str = "Failed to communicate with D-Bus / fprintd service.", original_exception: Exception = None):
        super().__init__(message, original_exception)


class DeviceNotFoundError(DBusCommunicationError):
    """Raised when no compatible fingerprint device is detected or available."""
    def __init__(self, message: str = "No fingerprint scanner device found or device unavailable.", original_exception: Exception = None):
        super().__init__(message, original_exception)


class EnrollmentError(FprintControlError):
    """Raised when fingerprint enrollment fails, is canceled, or encounters a hardware error."""
    def __init__(self, message: str = "Fingerprint enrollment failed.", original_exception: Exception = None):
        super().__init__(message, original_exception)
