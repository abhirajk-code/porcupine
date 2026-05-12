#!/usr/bin/env bash
# Enable the porcupine systemd service.
# The service will start now and automatically on every boot.
#
# Prerequisite: install.sh must have been run first.
#
# Usage:
#   sudo bash install/enable.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="porcupine"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_FILE="/etc/porcupine/porcupine.conf"
VENV_DIR="/opt/porcupine/venv"

ok()  { echo "[ OK ]  $*"; }
die() { echo "[FAIL]  $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Root check
# ---------------------------------------------------------------------------
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run as root: sudo bash $0"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
[[ -f "$SERVICE_DEST" ]] \
    || die "Service file not found: $SERVICE_DEST — run Step 1 first: sudo bash $SCRIPT_DIR/install.sh"

[[ -f "$CONFIG_FILE" ]] \
    || die "Config file not found: $CONFIG_FILE — run Step 1 first: sudo bash $SCRIPT_DIR/install.sh"

"$VENV_DIR/bin/porcupine" --help &>/dev/null 2>&1 \
    || die "porcupine not found in venv ($VENV_DIR) — run Step 1 first: sudo bash $SCRIPT_DIR/install.sh"

# ---------------------------------------------------------------------------
# Enable and start
# ---------------------------------------------------------------------------
echo
echo "════════════════════════════════════════════"
echo "  Porcupine — Step 3: Enable startup service"
echo "════════════════════════════════════════════"
echo

echo "Reloading systemd and enabling ${SERVICE_NAME}..."
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
ok "Service enabled — will start automatically on every boot"

# ---------------------------------------------------------------------------
# Post-start validation
# ---------------------------------------------------------------------------
sleep 1
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running now"
else
    echo
    systemctl status "$SERVICE_NAME" --no-pager || true
    die "Service failed to start — see output above"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
echo "════════════════════════════════════════════"
echo " Porcupine is live!"
echo " Config  : $CONFIG_FILE"
echo " Logs    : journalctl -u porcupine -f"
echo " Status  : porcupine status"
echo " Stop    : sudo porcupine stop"
echo " Remove  : sudo bash install/uninstall.sh"
echo " Help    : porcupine help"
echo "════════════════════════════════════════════"
