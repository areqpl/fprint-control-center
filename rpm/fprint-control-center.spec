Name:           fprint-control-center
Version:        1.7.0
Release:        1%{?dist}
Summary:        High-performance PyQt6 control center daemon for fprintd fingerprint devices

License:        MIT
URL:            https://github.com/areqpl/fprint-control-center
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
Requires:       python3 >= 3.10
Requires:       python3-qt6
Recommends:     fprintd

%description
fprint-control-center is a background system tray daemon and PyQt6 GUI control center
for fprintd fingerprint devices on Linux laptops (Synaptics, Validity, Elan).
Features multi-angle fingerprint enrollment, KeePassXC/PAM integration, verification
tester, and USB autosuspend power optimization.

%prep
%autosetup -n %{name}-%{version}

%build
# Pure Python application - no compilation step required

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_prefix}/lib/%{name}
install -pm 0644 src/__init__.py %{buildroot}%{_prefix}/lib/%{name}/__init__.py
install -pm 0644 src/exceptions.py %{buildroot}%{_prefix}/lib/%{name}/exceptions.py
install -pm 0644 src/fprint_manager.py %{buildroot}%{_prefix}/lib/%{name}/fprint_manager.py
install -pm 0644 src/pam_bridge.py %{buildroot}%{_prefix}/lib/%{name}/pam_bridge.py
install -pm 0755 src/main.py %{buildroot}%{_prefix}/lib/%{name}/main.py

install -d %{buildroot}%{_bindir}
cat << 'EOF' > %{buildroot}%{_bindir}/%{name}
#!/bin/sh
exec python3 %{_prefix}/lib/%{name}/main.py "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/%{name}

install -d %{buildroot}%{_datadir}/pixmaps
install -pm 0644 resources/icon.png %{buildroot}%{_datadir}/pixmaps/%{name}.png

install -d %{buildroot}%{_docdir}/%{name}
install -pm 0644 README.md %{buildroot}%{_docdir}/%{name}/README.md

install -d %{buildroot}%{_userunitdir}
install -pm 0644 systemd/fprint-control-center.service %{buildroot}%{_userunitdir}/fprint-control-center.service

%files
%doc README.md
%{_bindir}/%{name}
%{_prefix}/lib/%{name}/
%{_datadir}/pixmaps/%{name}.png
%{_userunitdir}/fprint-control-center.service

%changelog
* Tue Aug 11 2026 areqpl <areqpl@github.com> - 1.7.0-1
- Multi-distro release v1.7.0
- Synaptics & generic USB reader autosuspend power optimization
- 360-degree multi-angle stage configuration
- KeePassXC & PAM sudo biometric unlock bridge
