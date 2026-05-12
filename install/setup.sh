#!/usr/bin/env bash
# Full end-to-end install — runs all three steps in sequence.
#
# For step-by-step control run each script individually:
#   Install package & config  : sudo bash install/install.sh
#   Test hardware             : sudo bash install/test.sh
#   Enable startup service    : sudo bash install/enable.sh
#
# To remove porcupine:        sudo bash install/uninstall.sh
#
# Usage:
#   sudo bash install/setup.sh                  (interactive, all three steps)
#   sudo bash install/setup.sh --non-interactive (all defaults, skip hw tests)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

die() { echo "[FAIL]  $*" >&2; exit 1; }

[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run as root: sudo bash $0"

NON_INTERACTIVE=false
for arg in "$@"; do
    case "$arg" in
        --non-interactive|--yes|-y) NON_INTERACTIVE=true ;;
        *) die "Unknown argument: $arg
Usage: setup.sh [--non-interactive]" ;;
    esac
done
[[ -t 0 ]] || NON_INTERACTIVE=true

# ---------------------------------------------------------------------------
# Step 1 — Install
# ---------------------------------------------------------------------------
STEP1_ARGS=()
$NON_INTERACTIVE && STEP1_ARGS+=(--non-interactive)
bash "$SCRIPT_DIR/install.sh" "${STEP1_ARGS[@]}"

# ---------------------------------------------------------------------------
# Step 2 — Hardware tests (skipped in non-interactive mode)
# ---------------------------------------------------------------------------
if $NON_INTERACTIVE; then
    echo
    echo "[INFO]  Non-interactive mode — skipping hardware tests."
    echo "        Run manually when ready: sudo porcupine test"
else
    bash "$SCRIPT_DIR/test.sh"
fi

# ---------------------------------------------------------------------------
# Step 3 — Enable service
# ---------------------------------------------------------------------------
bash "$SCRIPT_DIR/enable.sh"
