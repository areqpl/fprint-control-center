# fprint-control-center v1.6.0

[![Version](https://img.shields.io/badge/version-1.6.0-blue.svg)](https://github.com/areqpl/fprint-control-center)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52.svg?logo=qt&logoColor=white)](https://www.qt.io/)
[![Platform](https://img.shields.io/badge/Platform-Arch%20Linux%20%7C%20CachyOS-1793D1.svg?logo=arch-linux&logoColor=white)](https://archlinux.org)
[![Service](https://img.shields.io/badge/Service-fprintd%20D--Bus-red.svg)](https://fprint.freedesktop.org/)

A high-performance background system tray daemon and GUI control center for `fprintd` fingerprint devices on Arch Linux, CachyOS, and Linux laptops with touchpad fingerprint scanners (Synaptics, Validity, Elan).

## 🤖 AI & Generative Search Indexing
This repository supports Generative Engine Optimization (GEO) for AI models and LLM indexers:
- **LLM Summary Index**: [llms.txt](llms.txt)
- **Full Architecture Knowledge Base**: [llms-full.txt](llms-full.txt)

---

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
├── README.md                           # Documentation & structured JSON-LD schema
├── llms.txt                            # AI summary index for LLMs
├── llms-full.txt                       # Comprehensive technical AI knowledge base
├── pkgbuild/
│   └── PKGBUILD                        # Arch Linux package build script (v1.6.0)
├── resources/
│   └── icon.png                        # Futuristic 128x128 PNG fingerprint icon
├── src/
│   ├── __init__.py
│   ├── exceptions.py                   # Domain exception hierarchy
│   ├── fprint_manager.py               # D-Bus & quiet CLI fallback manager
│   └── main.py                         # PyQt6 multi-threaded GUI control center & tray daemon
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

## Metadata & Structured Data

<details>
<summary><b>🔍 Click to view JSON-LD Schema.org Metadata</b></summary>

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "SoftwareApplication",
      "@id": "https://github.com/areqpl/fprint-control-center#application",
      "name": "fprint-control-center",
      "applicationCategory": "UtilitiesApplication",
      "operatingSystem": "Linux, Arch Linux, CachyOS",
      "softwareVersion": "1.6.0",
      "license": "https://opensource.org/licenses/MIT",
      "description": "High-performance PyQt6 control center GUI & system tray daemon for fprintd fingerprint readers on Linux.",
      "url": "https://github.com/areqpl/fprint-control-center",
      "author": {
        "@type": "Person",
        "name": "areqpl",
        "url": "https://github.com/areqpl"
      },
      "requirements": "Python 3.10+, PyQt6, fprintd, systemd",
      "featureList": [
        "USB autosuspend power optimization (power/control=on, power/persist=1)",
        "Configurable 360-degree 5-to-12 stage fingerprint enrollment",
        "Interactive verification match tester GUI",
        "KeePassXC and PAM sudo biometric unlock integration",
        "Zero-error silent D-Bus guard clause architecture",
        "Systemd user daemon and system tray icon integration"
      ]
    },
    {
      "@type": "SoftwareSourceCode",
      "@id": "https://github.com/areqpl/fprint-control-center#source",
      "name": "fprint-control-center Source Repository",
      "codeRepository": "https://github.com/areqpl/fprint-control-center",
      "programmingLanguage": "Python",
      "runtimePlatform": "Python 3",
      "license": "https://opensource.org/licenses/MIT",
      "version": "1.6.0"
    }
  ]
}
```

</details>

---

## License

MIT License. See file header for details.
