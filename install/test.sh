#!/usr/bin/env bash
# Interactive hardware tests.
# Tests each interface and monitor, prompting for confirmation at each step.
# Button tests ask you to perform an action and verify it was captured.
#
# Usage:
#   sudo bash install/test.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_PY="$SCRIPT_DIR/test_hardware.py"
CONFIG_FILE="/etc/porcupine/porcupine.conf"
VENV_DIR="/opt/porcupine/venv"

# Prefer the venv Python (has porcupine installed); fall back to system python3
if [[ -f "$VENV_DIR/bin/python" ]]; then
    PY="$VENV_DIR/bin/python"
else
    PY="$(command -v python3)"
fi

PASS=0; FAIL=0; SKIP=0

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
ok()   { echo "  [ PASS ]  $*"; PASS=$((PASS + 1)); }
fail() { echo "  [ FAIL ]  $*"; FAIL=$((FAIL + 1)); }
skip() { echo "  [ SKIP ]  $*"; SKIP=$((SKIP + 1)); }
sep()  { echo; echo "────────────────────────────────────────"; echo "  $*"; echo "────────────────────────────────────────"; }

confirm() {
    local answer
    read -r -p "  $1 [y/N]: " answer
    [[ "${answer,,}" =~ ^(y|yes)$ ]]
}

# ---------------------------------------------------------------------------
# Test runners
# ---------------------------------------------------------------------------

# visual_test: run a command, then ask user if it looked correct.
# Exit 2 from the command → skip (hardware unavailable).
visual_test() {
    local label="$1"; shift
    local rc=0
    "$@" || rc=$?
    echo
    if [[ $rc -eq 2 ]]; then
        skip "$label — hardware driver not available"
        return
    elif [[ $rc -ne 0 ]]; then
        fail "$label — test script error (exit $rc)"
        return
    fi
    if confirm "Does the above output look correct?"; then
        ok "$label"
    else
        fail "$label — user reported issue"
    fi
}

# action_test: run a command that passes/fails on its own (no user confirmation).
# Exit 2 → skip; non-zero → fail.
action_test() {
    local label="$1"; shift
    local rc=0
    "$@" || rc=$?
    if [[ $rc -eq 0 ]]; then
        ok "$label"
    elif [[ $rc -eq 2 ]]; then
        skip "$label — hardware driver not available"
    else
        fail "$label"
    fi
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
echo
echo "════════════════════════════════════════════"
echo "  Porcupine Hardware Test — Step 2 of 3"
echo "════════════════════════════════════════════"
echo "  Config : $CONFIG_FILE"
echo "  Script : $TEST_PY"
echo

[[ "${EUID:-$(id -u)}" -eq 0 ]] \
    || echo "  NOTE: Not running as root — GPIO tests may fail if user lacks gpio group access."

"$VENV_DIR/bin/porcupine" --help &>/dev/null 2>&1 \
    || { echo "[FAIL]  porcupine not found in venv — run Step 1 first."; exit 1; }

# ════════════════════════════════════════════════════════
sep "1 / 6 — LCD display"
echo "  The LCD should display two lines of text for ~6 seconds."
visual_test "LCD display" "$PY" "$TEST_PY" lcd

# ════════════════════════════════════════════════════════
sep "2 / 6 — Buzzer patterns"
echo "  Listen for 4 distinct beep patterns played one after another."
visual_test "Buzzer patterns" "$PY" "$TEST_PY" buzzer

# ════════════════════════════════════════════════════════
sep "3 / 6 — Button: short press"
echo "  ACTION  ➜  Press and release the button quickly (under 2 seconds)."
echo "  The script will wait up to 30 s."
echo
action_test "Button short press" "$PY" "$TEST_PY" button-short

# ════════════════════════════════════════════════════════
sep "4 / 6 — Button: long press"
echo "  ACTION  ➜  Hold the button for at least 2 seconds, then release."
echo "  The script will wait up to 30 s."
echo
action_test "Button long press" "$PY" "$TEST_PY" button-long

# ════════════════════════════════════════════════════════
sep "5 / 6 — Monitor readings"
echo "  Reading all monitors once. Verify the values are plausible."
echo

echo "  [Boot / uptime]"
"$PY" "$TEST_PY" monitor-boot 2>/dev/null || echo "  (unavailable)"
echo

echo "  [Power / INA219]"
"$PY" "$TEST_PY" monitor-power 2>/dev/null || echo "  (unavailable)"
echo

echo "  [CPU & memory]"
"$PY" "$TEST_PY" monitor-cpu 2>/dev/null || echo "  (unavailable)"
echo

echo "  [Temperature]"
"$PY" "$TEST_PY" monitor-temp 2>/dev/null || echo "  (unavailable)"
echo

echo "  [Network]"
"$PY" "$TEST_PY" monitor-net 2>/dev/null || echo "  (unavailable)"
echo

if confirm "Do all monitor readings look reasonable?"; then
    ok "Monitor readings"
else
    fail "Monitor readings — user reported issue"
fi

# ════════════════════════════════════════════════════════
sep "6 / 6 — Alert checker (dry-run)"
echo "  Verifying AlertChecker wires up without error..."
"$PY" - <<'PYEOF'
from porcupine.interfaces.buzzer import AlertChecker
from porcupine.config import load_config
cfg = load_config()
ac = AlertChecker(temp_warn=cfg.get("temp_warn", 80),
                  cpu_warn=cfg.get("cpu_warn", 90),
                  mem_warn=cfg.get("mem_warn", 90),
                  bat_warn=cfg.get("bat_warn", 40))
ac.check({})   # must not raise
print("  AlertChecker OK.")
PYEOF
ok "AlertChecker dry-run"

# ════════════════════════════════════════════════════════
echo
echo "════════════════════════════════════════════"
echo "  Test Summary"
printf  "    Passed  : %d\n" "$PASS"
printf  "    Failed  : %d\n" "$FAIL"
printf  "    Skipped : %d\n" "$SKIP"
echo "════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    echo
    echo "  Some tests FAILED. Fix hardware issues and re-run:"
    echo "    sudo porcupine test"
    exit 1
else
    echo
    echo "  All tests passed (or skipped)."
    echo "  Next: sudo bash $SCRIPT_DIR/enable.sh"
fi
