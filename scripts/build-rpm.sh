#!/bin/bash
set -e

VERSION="1.7.0"
NAME="fprint-control-center"
BUILD_ROOT="build/rpmbuild"

echo "Building RPM package spec for fprint-control-center v${VERSION}..."

mkdir -p "$BUILD_ROOT"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
cp rpm/fprint-control-center.spec "$BUILD_ROOT/SPECS/"

# Create source tarball
TARBALL_DIR="build/$NAME-$VERSION"
rm -rf "$TARBALL_DIR"
mkdir -p "$TARBALL_DIR"
cp -r src resources systemd README.md "$TARBALL_DIR/"
tar -czf "$BUILD_ROOT/SOURCES/$NAME-$VERSION.tar.gz" -C build "$NAME-$VERSION"

if command -v rpmbuild >/dev/null 2>&1; then
    rpmbuild --define "_topdir $(pwd)/$BUILD_ROOT" -ba "$BUILD_ROOT/SPECS/$NAME.spec"
    echo "Successfully built RPM package in $BUILD_ROOT/RPMS/"
else
    echo "rpmbuild tool not found. Source tarball prepared at $BUILD_ROOT/SOURCES/$NAME-$VERSION.tar.gz and spec at $BUILD_ROOT/SPECS/$NAME.spec"
fi
