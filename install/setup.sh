#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing porcupine..."

pip install -r "$INSTALL_DIR/requirements.txt"
pip install "$INSTALL_DIR"

mkdir -p /etc/porcupine

cp "$INSTALL_DIR/install/porcupine.service" /etc/systemd/system/porcupine.service
systemctl daemon-reload
systemctl enable --now porcupine

echo "Done. Service status:"
systemctl status porcupine --no-pager
