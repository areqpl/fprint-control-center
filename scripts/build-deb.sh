#!/bin/bash
set -e

VERSION="1.7.0"
REVISION="1"
PKG_DIR="build/debian/fprint-control-center_${VERSION}-${REVISION}_all"

echo "Building Debian package for fprint-control-center v${VERSION}-${REVISION}..."

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/usr/lib/fprint-control-center"
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/usr/share/pixmaps"
mkdir -p "$PKG_DIR/usr/share/doc/fprint-control-center"
mkdir -p "$PKG_DIR/usr/lib/systemd/user"

cp src/__init__.py src/exceptions.py src/fprint_manager.py src/pam_bridge.py "$PKG_DIR/usr/lib/fprint-control-center/"
cp src/main.py "$PKG_DIR/usr/lib/fprint-control-center/main.py"
chmod 755 "$PKG_DIR/usr/lib/fprint-control-center/main.py"

cat << 'EOF' > "$PKG_DIR/usr/bin/fprint-control-center"
#!/bin/sh
exec python3 /usr/lib/fprint-control-center/main.py "$@"
EOF
chmod 755 "$PKG_DIR/usr/bin/fprint-control-center"

cp resources/icon.png "$PKG_DIR/usr/share/pixmaps/fprint-control-center.png"
cp README.md "$PKG_DIR/usr/share/doc/fprint-control-center/README.md"
cp systemd/fprint-control-center.service "$PKG_DIR/usr/lib/systemd/user/fprint-control-center.service"
cp debian/control "$PKG_DIR/DEBIAN/control"

dpkg-deb --build --root-owner-group "$PKG_DIR"
echo "Successfully built Debian package: build/debian/fprint-control-center_${VERSION}-${REVISION}_all.deb"
