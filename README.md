# fprint-control-center v1.1.0

A production-grade PyQt6 GUI control center and daemon for managing fingerprint authentication devices on Linux via `fprintd` D-Bus interface.

## Features & Project Architecture

- **Custom Domain Exception Hierarchy (`src/exceptions.py`)**:
  - `FprintControlError`: Base exception class.
  - `SingleInstanceError`: Prevents multiple simultaneous daemon instances.
  - `DBusCommunicationError`: Handles IPC and D-Bus transport failures.
  - `DeviceNotFoundError`: Raised when fingerprint scanner hardware is absent or unplugged.
  - `EnrollmentError`: Catches fingerprint scanning & registration errors.

- **Defensive D-Bus Client (`src/fprint_manager.py`)**:
  - D-Bus wrapper targeting `net.reactivated.FPrint` and `net.reactivated.FPrint.Device`.
  - Exponential backoff retry handler (`@retry_with_backoff`) for transient IPC timeouts.
  - Automated USB sleep/wake recovery protocol following system suspend/resume cycles.

- **Robust Daemon Entry Point (`src/main.py`)**:
  - Single-instance enforcement via `QLocalServer` lock socket.
  - Global `sys.excepthook` for logging unhandled UI exceptions to `logging` / `journalctl` without silent crashes.
  - Asynchronous UNIX signal handling (`SIGINT`, `SIGTERM`, `SIGHUP`) via `QSocketNotifier` for graceful Qt event loop shutdown.

- **Hardened Systemd User Service (`systemd/fprint-control-center.service`)**:
  - Production process isolation (`ProtectSystem=full`, `PrivateTmp=true`).
  - Automatic crash recovery (`Restart=on-failure`, `RestartSec=3s`).
  - Rate-limited restarts (`StartLimitIntervalSec=60s`, `StartLimitBurst=5`).

- **Packaging (`pkgbuild/PKGBUILD`)**:
  - Arch Linux PKGBUILD specification updated for v1.1.0.

## Repository Structure

```
fprint-control-center/
├── README.md
├── pkgbuild/
│   └── PKGBUILD
├── resources/
│   └── icon.png
├── src/
│   ├── __init__.py
│   ├── exceptions.py
│   ├── fprint_manager.py
│   └── main.py
└── systemd/
    └── fprint-control-center.service
```

## Prerequisites & Dependencies

- Python 3.8+
- PyQt6
- `fprintd` (optional runtime daemon for D-Bus communication)

### Installing Dependencies

**Arch Linux:**
```bash
sudo pacman -S python-pyqt6 fprintd
```

**Using pip:**
```bash
pip install PyQt6 dbus-python
```

## Launching the Application

Run directly from the repository root:
```bash
python3 src/main.py
```

## Deployment Instructions

### 1. Systemd User Service Deployment

To install and run `fprint-control-center` as a background user service:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/fprint-control-center.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now fprint-control-center.service
```

To view live service logs in journald:
```bash
journalctl --user -u fprint-control-center.service -f
```

### 2. Arch Linux Package Installation (PKGBUILD)

To build and install the package locally:

```bash
cd pkgbuild
makepkg -si
```
