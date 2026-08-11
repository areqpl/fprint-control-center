# fprint-control-center

A background tray daemon and system bridge for `fprintd` on Arch Linux and CachyOS. It fixes fingerprint scanner wake-up drops, provides a PyQt6 system tray interface, and handles PAM authentication prompts.

## Why this exists

If you use fingerprint login on Linux with laptops running Synaptics sensors (like `06cb:00bd`), you've likely hit these issues:

1. **USB Autosuspend Drops**: Linux puts the fingerprint reader to sleep to save power. When `sudo` triggers PAM, `fprintd` tries to access the sensor before it wakes up, causing instant match timeouts.
2. **Missing Tray Feedback**: You scan your finger without knowing if `fprintd` is ready, locked out, or waiting for input.
3. **PAM Lockups**: Unhandled D-Bus disconnects during sleep/wake cycles freeze terminal authentication.

`fprint-control-center` addresses these failure modes directly:
- Locks single-instance execution via a local socket (`QLocalServer`).
- Retries D-Bus IPC calls (`net.reactivated.FPrint`) with exponential backoff.
- Listens for UNIX signals (`SIGINT`, `SIGTERM`, `SIGHUP`) via non-blocking socket pairs to clean up Qt event loops.
- Runs as an isolated systemd user unit with crash recovery.

---

## Hardware Power Fix (Required)

To stop your Synaptics sensor from dropping scans due to USB autosuspend, add a udev rule to keep power state on:

```bash
# /etc/udev/rules.d/70-synaptics-fingerprint-power.rules
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="06cb", ATTR{idProduct}=="00bd", ATTR{power/control}="on"
```

Reload udev rules:
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Repository Layout

```
fprint-control-center/
├── README.md
├── pkgbuild/
│   └── PKGBUILD
├── resources/
│   └── icon.png
├── src/
│   ├── __init__.py
│   ├── exceptions.py       # Domain exception hierarchy
│   ├── fprint_manager.py   # D-Bus client wrapper with exponential backoff
│   └── main.py             # PyQt6 tray daemon and signal handling
└── systemd/
    └── fprint-control-center.service
```

---

## Code Architecture

### 1. Exception Hierarchy (`src/exceptions.py`)
Custom domain exceptions ensure specific error handling instead of generic failures:
- `FprintControlError`: Base exception for all errors.
- `SingleInstanceError`: Prevents duplicate tray daemons.
- `DBusCommunicationError`: Handles IPC connection failures.
- `DeviceNotFoundError`: Raised when scanner hardware is missing or suspended.
- `EnrollmentError`: Catches finger scanning and template registration errors.

### 2. D-Bus Manager & Retry Loop (`src/fprint_manager.py`)
Wraps `net.reactivated.FPrint` using an exponential backoff decorator:
```python
def retry_with_backoff(max_retries=5, initial_delay=1.0, backoff_factor=2.0):
    # Retries transient D-Bus timeouts before raising DBusCommunicationError
```

### 3. Application Lifecycle (`src/main.py`)
- **Single Instance Socket**: Uses `QLocalServer` (`fprint-control-center-lock-<user>`). If an instance exists, new launches exit immediately with code `0`.
- **Global Error Hook**: Overrides `sys.excepthook` to write stack traces directly to `journalctl` / `sys.stderr` and present an alert dialog rather than crashing silently.
- **Signal Safety**: Uses `socket.socketpair()` wired into `QSocketNotifier` to handle `SIGINT` and `SIGTERM` inside the Qt main loop.

---

## Quickstart

### Prerequisites

On Arch Linux / CachyOS:
```bash
sudo pacman -S python-pyqt6 fprintd
```

### Manual Run

Run directly from source to verify:
```bash
python3 src/main.py
```

---

## Installation & Deployment

### 1. Enable Systemd User Unit

Copy the service unit and start it:
```bash
mkdir -p ~/.config/systemd/user
cp systemd/fprint-control-center.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now fprint-control-center.service
```

Check live logs:
```bash
journalctl --user -u fprint-control-center.service -f
```

### 2. Build & Install via PKGBUILD

To build a native Arch package:
```bash
cd pkgbuild
makepkg -si
```

---

## License

MIT License. See file header for details.
