# fprint-control-center v1.5.0

A high-performance background system tray daemon and GUI control center for `fprintd` fingerprint devices on Arch Linux, CachyOS, and Linux laptops with touchpad fingerprint scanners (Synaptics, Validity, Elan).

## Key Features & Responsiveness Optimizations

### 🚀 Touchpad & Sensor Responsiveness Boost
- **High-Responsiveness Mode (`power/control = on` & `power/persist = 1`)**: Disables USB autosuspend for Synaptics (`06cb:*`) and generic USB fingerprint sensors. Prevents instant match timeouts during `sudo` and PAM authentication.
- **Configurable 360° Position Stages (5 to 12 Angles)**: Configure the exact number of fingerprint scan positions captured during enrollment. Select `5` for rapid setup, `8` for balanced accuracy, or `12` for ultra-precise match ratio.
- **Interactive Verification Match Tester**: Perform real-time fingerprint match verification (`fprintd-verify`) directly inside the GUI with visual feedback.

### 🔐 KeePassXC & PAM Integration
- **Password Manager PAM Bridge**: Detects and integrates with `/etc/pam.d/sudo` and `/etc/pam.d/keepassxc` to allow instant fingerprint database unlocking.
- **`SUDO_ASKPASS` Compatible**: Connects to graphical authentication helpers (`kaskpass`, `zenity`) for terminal and GUI sudo prompts.

### 🛡️ Zero-Error Silent Guard Clause Architecture
- **Fault-Tolerant Exception Handling**: All D-Bus calls, sysfs reads, and subprocess invocations operate within silent guard clauses.
- **Clean Journalctl Logs**: Eliminates 3-attempt retry warning spam and tracebacks from system logs (`journalctl`).

---

## Hardware Power Optimization (Recommended)

Add a udev rule to keep your fingerprint reader powered and prevent scan drops:

```bash
# /etc/udev/rules.d/70-synaptics-fingerprint-power.rules
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="06cb", ATTR{idProduct}=="00bd", ATTR{power/control}="on", ATTR{power/persist}="1"
```

Reload rules:
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Repository Layout

```
fprint-control-center/
├── README.md
├── pkgbuild/
│   └── PKGBUILD            # Arch Linux package build script (v1.5.0)
├── resources/
│   └── icon.png            # Futuristic 128x128 PNG fingerprint icon
├── src/
│   ├── __init__.py
│   ├── exceptions.py       # Domain exception hierarchy
│   ├── fprint_manager.py   # D-Bus & quiet CLI fallback manager
│   └── main.py             # PyQt6 multi-threaded GUI control center & tray daemon
└── systemd/
    └── fprint-control-center.service
```

---

## Quickstart

### Installation on Arch Linux / CachyOS

```bash
cd pkgbuild
makepkg -si
```

### Enable Systemd User Daemon

```bash
mkdir -p ~/.config/systemd/user
cp systemd/fprint-control-center.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now fprint-control-center.service
```

---

## License

MIT License. See file header for details.
