#!/usr/bin/env bash
# Step 3 of 3 — Enable the porcupine systemd service.
# The service will start now and automatically on every boot.
#
# Prerequisite: Step 1 (1_install.sh) must have been run first.
#
# Usage:
#   sudo bash install/3_enable.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="porcupine"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_FILE="/etc/porcupine/porcupine.conf"

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
    || die "Service file not found: $SERVICE_DEST — run Step 1 first: sudo bash $SCRIPT_DIR/1_install.sh"

[[ -f "$CONFIG_FILE" ]] \
    || die "Config file not found: $CONFIG_FILE — run Step 1 first: sudo bash $SCRIPT_DIR/1_install.sh"

porcupine --help &>/dev/null \
    || die "'porcupine' binary not found — run Step 1 first: sudo bash $SCRIPT_DIR/1_install.sh"

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
echo " Status  : systemctl status porcupine"
echo " Stop    : systemctl stop porcupine"
echo " Disable : systemctl disable porcupine"
echo "════════════════════════════════════════════"
