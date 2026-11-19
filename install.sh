#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo ./install.sh)" >&2
  exit 1
fi

INSTALL_DIR=/opt/travelserver
CONFIG_DIR=/etc/travelserver

echo "Installing dependencies..."
apt-get update
apt-get install -y \
  python3 \
  libimobiledevice-utils \
  usbmuxd \
  ifuse \
  exfatprogs \
  util-linux \
  libgpiod-utils \
  gdisk

echo "Installing files to ${INSTALL_DIR} ..."
mkdir -p "${INSTALL_DIR}"
cp -r travelserver "${INSTALL_DIR}/"
cp -r config "${INSTALL_DIR}/"

if [[ ! -f "${CONFIG_DIR}/travelserver.conf" ]]; then
  echo "Installing config to ${CONFIG_DIR} ..."
  mkdir -p "${CONFIG_DIR}"
  cp config/travelserver.conf "${CONFIG_DIR}/travelserver.conf"
else
  echo "Config already exists at ${CONFIG_DIR}/travelserver.conf; leaving it in place."
fi

echo "Installing systemd service ..."
cp systemd/travelserver.service /etc/systemd/system/travelserver.service
systemctl daemon-reload

echo "Enabling usbmuxd and travelserver services ..."
systemctl enable --now usbmuxd || true
systemctl enable travelserver

mkdir -p /mnt/travelserver

cat <<EOF

Installation complete. Next steps:

1. Label your two SSDs exactly TRAVEL1 and TRAVEL2:
     sudo e2label /dev/sdX1 TRAVEL1
2. Edit ${CONFIG_DIR}/travelserver.conf (LED GPIO line, extensions, etc).
3. Find your card reader devices:
     python3 ${INSTALL_DIR}/travelserver/main.py sd-check
4. Start the daemon:
     sudo systemctl start travelserver

The LED patterns are documented in ${INSTALL_DIR}/../README.md on the repo.
EOF
