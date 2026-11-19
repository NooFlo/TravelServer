#!/usr/bin/env bash
set -euo pipefail

WITH_DOCKER=0
for arg in "$@"; do
  case "$arg" in
    --with-docker) WITH_DOCKER=1 ;;
    -h|--help)
      echo "usage: sudo ./install.sh [--with-docker]"
      echo "  --with-docker  also install Docker + Compose (for testing webapps/, see webapps/README.md)"
      exit 0
      ;;
    *)
      echo "unknown option: $arg (see ./install.sh --help)" >&2
      exit 1
      ;;
  esac
done

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

if [[ $WITH_DOCKER -eq 1 ]]; then
  echo "Installing Docker and Compose ..."
  apt-get install -y docker.io
  if ! apt-get install -y docker-compose-v2 2>/dev/null; then
    if ! apt-get install -y docker-compose-plugin 2>/dev/null; then
      apt-get install -y docker-compose || echo "WARNING: no compose package found; install one manually" >&2
    fi
  fi
  systemctl enable --now docker || true
  echo "Docker installed. Example webapps (Immich, PiGallery2) live in webapps/."
fi

mkdir -p /mnt/travelserver

IP_HINT=$(hostname -I 2>/dev/null | awk '{print $1}')

cat <<EOF

Installation complete. Next steps:

1. Label your two SSDs exactly TRAVEL1 and TRAVEL2:
     sudo e2label /dev/sdX1 TRAVEL1
2. Edit ${CONFIG_DIR}/travelserver.conf (LED GPIO line, extensions, web UI port, etc).
3. Find your card reader devices:
     python3 ${INSTALL_DIR}/travelserver/main.py sd-check
4. Start the daemon:
     sudo systemctl start travelserver
5. Open the status dashboard in a browser:
     http://${IP_HINT:-<rock5a-ip>}:8000

The LED patterns are documented in ${INSTALL_DIR}/../README.md on the repo.
EOF
