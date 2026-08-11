# fprint-control-center

A PyQt6-based control center GUI for managing fingerprint authentication devices on Linux systems.

## Features & Project Structure

- `src/main.py`: Main application entry point using PyQt6.
- `resources/`: Application assets (icons, images).
- `systemd/`: Systemd service configurations.
- `pkgbuild/`: Arch Linux PKGBUILD packaging specification.

## Prerequisites & Dependencies

- Python 3.8 or higher
- PyQt6

### Installing Dependencies

**Arch Linux:**
```bash
sudo pacman -S python-pyqt6
```

**Using pip:**
```bash
pip install PyQt6
```

## Running the Application

Launch directly from the repository root:
```bash
python3 src/main.py
```

## Systemd User Service Setup

To run `fprint-control-center` as a background user service:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/fprint-control-center.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now fprint-control-center.service
```

## Arch Linux Package (PKGBUILD)

To build and install the Arch Linux package locally:

```bash
cd pkgbuild
makepkg -si
```
