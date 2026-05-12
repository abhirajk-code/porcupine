#!/usr/bin/env bash
# Uninstall porcupine — removes the service, venv, config, and CLI.
#
# Usage:
#   sudo bash install/uninstall.sh
set -euo pipefail

ok()  { echo "[ OK ]  $*"; }
info(){ echo "[INFO]  $*"; }
die() { echo "[FAIL]  $*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "Run as root: sudo bash $0"

SERVICE=porcupine

echo
echo "════════════════════════════════════════════"
echo "  Porcupine — Uninstall"
echo "════════════════════════════════════════════"
echo

# Stop and disable the service
if systemctl is-active --quiet $SERVICE 2>/dev/null; then
    systemctl stop $SERVICE
    ok "Service stopped"
fi

if systemctl is-enabled --quiet $SERVICE 2>/dev/null; then
    systemctl disable $SERVICE
    ok "Service disabled"
fi

# Remove service file
if [[ -f /etc/systemd/system/${SERVICE}.service ]]; then
    rm /etc/systemd/system/${SERVICE}.service
    systemctl daemon-reload
    ok "Service file removed"
fi

# Remove venv and installed assets
if [[ -d /opt/porcupine ]]; then
    rm -rf /opt/porcupine
    ok "Removed /opt/porcupine"
fi

# Remove management CLI
if [[ -f /usr/local/bin/porcupine ]]; then
    rm /usr/local/bin/porcupine
    ok "Removed /usr/local/bin/porcupine"
fi

# Remove config (ask first — user may want to keep it)
if [[ -d /etc/porcupine ]]; then
    read -r -p "  Remove config at /etc/porcupine? [y/N]: " ans
    if [[ ${ans,,} =~ ^(y|yes)$ ]]; then
        rm -rf /etc/porcupine
        ok "Removed /etc/porcupine"
    else
        info "Config kept at /etc/porcupine"
    fi
fi

# Remove data directory
if [[ -d /var/lib/porcupine ]]; then
    rm -rf /var/lib/porcupine
    ok "Removed /var/lib/porcupine"
fi

echo
echo "════════════════════════════════════════════"
echo "  Porcupine uninstalled."
echo "════════════════════════════════════════════"
