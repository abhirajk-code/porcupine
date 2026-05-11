#!/usr/bin/env bash
# Full end-to-end install — runs all three steps in sequence.
#
# For step-by-step control run each script individually:
#   Step 1 — Install package & config  : sudo bash install/1_install.sh
#   Step 2 — Test hardware             : sudo bash install/2_test.sh
#   Step 3 — Enable startup service    : sudo bash install/3_enable.sh
#
# Usage:
#   sudo bash install/setup.sh                  (interactive, all three steps)
#   sudo bash install/setup.sh --non-interactive (all defaults, skip hw tests)
#   sudo bash install/setup.sh --uninstall
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

die() { echo "[FAIL]  $*" >&2; exit 1; }

[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run as root: sudo bash $0"

# Parse flags — pass relevant ones through to sub-scripts
NON_INTERACTIVE=false
UNINSTALL=false
for arg in "$@"; do
    case "$arg" in
        --non-interactive|--yes|-y) NON_INTERACTIVE=true ;;
        --uninstall)                UNINSTALL=true ;;
        *) die "Unknown argument: $arg
Usage: setup.sh [--non-interactive] [--uninstall]" ;;
    esac
done
[[ -t 0 ]] || NON_INTERACTIVE=true

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
if $UNINSTALL; then
    SERVICE_NAME="porcupine"
    SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
    VENV_DIR="/opt/porcupine/venv"
    echo "Stopping and disabling service..."
    systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_DEST"
    systemctl daemon-reload
    echo "Removing virtual environment..."
    rm -rf "$VENV_DIR"
    echo "[ OK ]  Porcupine uninstalled."
    echo "        Config/data dirs preserved — remove manually if no longer needed."
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 1 — Install
# ---------------------------------------------------------------------------
STEP1_ARGS=()
$NON_INTERACTIVE && STEP1_ARGS+=(--non-interactive)
bash "$SCRIPT_DIR/1_install.sh" "${STEP1_ARGS[@]}"

# ---------------------------------------------------------------------------
# Step 2 — Hardware tests (skipped in non-interactive mode)
# ---------------------------------------------------------------------------
if $NON_INTERACTIVE; then
    echo
    echo "[INFO]  Non-interactive mode — skipping hardware tests (Step 2)."
    echo "        Run manually when ready: sudo bash $SCRIPT_DIR/2_test.sh"
else
    bash "$SCRIPT_DIR/2_test.sh"
fi

# ---------------------------------------------------------------------------
# Step 3 — Enable service
# ---------------------------------------------------------------------------
bash "$SCRIPT_DIR/3_enable.sh"
