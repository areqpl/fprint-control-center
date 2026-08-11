# fprint-control-center v1.2.1

A background system tray daemon and GUI control center for `fprintd` fingerprint devices on Arch Linux and CachyOS. It addresses fingerprint scanner wake-up dropouts, provides a persistent PyQt6 system tray interface, interactive fingerprint enrollment, template reset, and USB power management diagnostics.

## Key Features in v1.2.1

- **Persistent System Tray Icon (`QSystemTrayIcon`)**:
  - Operates continuously in the system tray (`app.setQuitOnLastWindowClosed(False)`).
  - Left-click toggles main control center window visibility.
  - Context Menu options:
    - **Open Settings / Control Center**: Opens and focuses the main application window.
    - **Enroll Finger...**: Opens interactive fingerprint enrollment dialog.
    - **Reset Templates...**: Prompt to wipe broken or legacy fingerprint templates (`fprintd-delete`).
    - **Check USB Autosuspend**: Diagnoses hardware USB autosuspend power configuration.
    - **Quit**: Safely terminates the background daemon.

- **Control Center GUI (`MainWindow`)**:
  - **Device & USB Autosuspend Panel**: Displays fingerprint scanner hardware status, D-Bus object path, and verifies if `/etc/udev/rules.d/70-synaptics-fingerprint-power.rules` is active (`power/control` = `on`).
  - **Enrolled Fingers Panel**: Displays friendly list of currently registered fingerprint templates for the user (`Right Index Finger`, `Left Thumb`, etc.).
  - **Interactive Enrollment Dialog**: Select target finger (`right-index-finger`, `left-index-finger`, `right-thumb`, etc.) and execute `fprintd-enroll` asynchronously with real-time stage progress feedback and output logging.
  - **Template Reset Action**: Prompts confirmation to wipe stored templates using `fprintd-delete`.

- **Engine Robustness**:
  - **Single Instance Enforcement**: `QLocalServer` UNIX lock socket (`fprint-control-center-lock-<user>`).
  - **Global Exception Hook**: `sys.excepthook` logger directing unhandled errors to `journalctl` / `sys.stderr` with user dialog warnings.
  - **UNIX Signal Handler**: Non-blocking `socket.socketpair()` connected to `QSocketNotifier` for clean Qt main loop termination on `SIGINT`, `SIGTERM`, and `SIGHUP`.
  - **D-Bus Exponential Backoff**: Automatic retry handler for `net.reactivated.FPrint` IPC timeouts.

---

## Hardware Power Fix (Required)

To stop Synaptics and generic fingerprint sensors from dropping scans due to USB autosuspend, add a udev rule to force power state on:

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
│   └── PKGBUILD            # Arch Linux package build script (v1.2.1)
├── resources/
│   └── icon.png            # System tray & window icon asset
├── src/
│   ├── __init__.py
│   ├── exceptions.py       # Custom domain exception hierarchy
│   ├── fprint_manager.py   # D-Bus client wrapper with exponential backoff & CLI fallback
│   └── main.py             # PyQt6 tray daemon, GUI MainWindow, & Enrollment dialog
└── systemd/
    └── fprint-control-center.service
```

---

## Architecture & Components

### 1. Persistent Tray & Lifecycle (`src/main.py`)
- Sets `setQuitOnLastWindowClosed(False)` so closing the window hides it to the tray rather than terminating the process.
- Hooks `SIGINT`, `SIGTERM`, and `SIGHUP` to clean up lock files and D-Bus device claims.

### 2. D-Bus Manager & Retry Loop (`src/fprint_manager.py`)
- Wraps `net.reactivated.FPrint` D-Bus interfaces with exponential backoff retry handling (`retry_with_backoff`).
- Includes CLI fallback mechanisms to query enrolled fingers if D-Bus service is in power-saving standby.

### 3. Interactive Fingerprint Enrollment (`EnrollmentDialog`)
- Executes `fprintd-enroll -f <finger> <username>` asynchronously via `QProcess`.
- Parses stdout in real-time to update multi-stage progress bars and human-readable swipe instructions.

---

## Quickstart

### Prerequisites

On Arch Linux / CachyOS:
```bash
sudo pacman -S python-pyqt6 fprintd
```

### Manual Run

Run directly from source to test GUI and system tray functionality:
```bash
python3 src/main.py
```

---

## Installation & Deployment

### 1. Enable Systemd User Unit

Copy the service unit and restart:
```bash
mkdir -p ~/.config/systemd/user
cp systemd/fprint-control-center.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now fprint-control-center.service
```

View live logs:
```bash
journalctl --user -u fprint-control-center.service -f
```

### 2. Build Arch Package via PKGBUILD

Build native package with `makepkg`:
```bash
cd pkgbuild
makepkg -f
```

Install built package:
```bash
sudo pacman -U fprint-control-center-1.2.1-1-any.pkg.tar.zst
```

---

## License

MIT License. See file header for details.
