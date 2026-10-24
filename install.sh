#!/bin/sh
set -eu

echo "=== rockpi-penta Pi 5 Fix Installer ==="
echo ""

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PACKAGE_FILE="$SCRIPT_DIR/rockpi-penta.deb"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root: sudo $0" >&2
    exit 1
fi

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb is required to build the package." >&2
    exit 1
fi

dpkg-deb --build "$SCRIPT_DIR/rockpi-penta" "$PACKAGE_FILE"
apt-get install --reinstall -y smartmontools iputils-ping "$PACKAGE_FILE"

echo "rockpi-penta, smartmontools, and iputils-ping are installed."
