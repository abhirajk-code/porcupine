#!/usr/bin/env bash
# Porcupine install / uninstall script.
# Must be run as root: sudo bash install/setup.sh [--uninstall]
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="/etc/porcupine"
DATA_DIR="/var/lib/porcupine"
SERVICE_NAME="porcupine"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
MIN_PY_MINOR=9

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info() { echo "[INFO]  $*"; }
ok()   { echo "[ OK ]  $*"; }
die()  { echo "[FAIL]  $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
UNINSTALL=false
for arg in "$@"; do
    case "$arg" in
        --uninstall) UNINSTALL=true ;;
        *) die "Unknown argument: $arg  (usage: setup.sh [--uninstall])" ;;
    esac
done

# ---------------------------------------------------------------------------
# Root check
# ---------------------------------------------------------------------------
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run as root: sudo bash $0"

# ---------------------------------------------------------------------------
# Uninstall path
# ---------------------------------------------------------------------------
if $UNINSTALL; then
    info "Stopping and disabling ${SERVICE_NAME} service..."
    systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_DEST"
    systemctl daemon-reload
    info "Removing Python package..."
    python3 -m pip uninstall -y porcupine 2>/dev/null || true
    ok "Porcupine uninstalled."
    echo "  Config preserved: $CONFIG_DIR"
    echo "  Data  preserved: $DATA_DIR"
    echo "  Remove them manually if no longer needed."
    exit 0
fi

# ---------------------------------------------------------------------------
# Python version check (≥ 3.9)
# ---------------------------------------------------------------------------
PY="$(command -v python3)" || die "python3 not found — install it first"
PY_VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MINOR="${PY_VER#*.}"
[[ "${PY_VER%%.*}" -ge 3 && "$PY_MINOR" -ge $MIN_PY_MINOR ]] \
    || die "Python 3.${MIN_PY_MINOR}+ required (found $PY_VER)"
ok "Python $PY_VER at $PY"

# ---------------------------------------------------------------------------
# Install Python package
# ---------------------------------------------------------------------------
info "Installing Python dependencies..."
"$PY" -m pip install --quiet -r "$INSTALL_DIR/requirements.txt"
"$PY" -m pip install --quiet "$INSTALL_DIR"
PORCUPINE_BIN="$(command -v porcupine 2>/dev/null)" \
    || die "'porcupine' binary not found in PATH after install"
ok "Package installed → $PORCUPINE_BIN"

# ---------------------------------------------------------------------------
# Runtime directories
# ---------------------------------------------------------------------------
mkdir -p "$CONFIG_DIR" "$DATA_DIR"
ok "Directories: $CONFIG_DIR, $DATA_DIR"

# ---------------------------------------------------------------------------
# Config file (non-destructive)
# ---------------------------------------------------------------------------
if [[ ! -f "$CONFIG_DIR/porcupine.conf" ]]; then
    cp "$INSTALL_DIR/install/porcupine.conf.example" "$CONFIG_DIR/porcupine.conf"
    ok "Default config installed → $CONFIG_DIR/porcupine.conf"
else
    info "Existing config kept:    $CONFIG_DIR/porcupine.conf"
fi

# ---------------------------------------------------------------------------
# systemd service (substitute real binary path into template)
# ---------------------------------------------------------------------------
sed "s|@@PORCUPINE_BIN@@|${PORCUPINE_BIN}|g" \
    "$INSTALL_DIR/install/porcupine.service" > "$SERVICE_DEST"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
ok "Service enabled and started"

# ---------------------------------------------------------------------------
# Post-install validation
# ---------------------------------------------------------------------------
sleep 1
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running"
else
    echo
    systemctl status "$SERVICE_NAME" --no-pager || true
    die "Service failed to start — see output above"
fi

echo
echo "============================================"
echo " Porcupine installed successfully!"
echo " Config : $CONFIG_DIR/porcupine.conf"
echo " Data   : $DATA_DIR"
echo " Logs   : journalctl -u porcupine -f"
echo " Check  : bash $INSTALL_DIR/install/check.sh"
echo "============================================"
