#!/usr/bin/env bash
# Post-install hardware sanity check. Run on the Pi after setup.sh.
# Usage: bash install/check.sh [LCD_I2C_ADDR]
#   LCD_I2C_ADDR defaults to 0x27

set -uo pipefail

I2C_ADDR="${1:-0x27}"
PASS=0
WARN=0

ok()   { echo "[ OK ]  $*"; ((PASS++)); }
warn() { echo "[WARN]  $*"; ((WARN++)); }
fail() { echo "[FAIL]  $*"; }

echo "=== Porcupine post-install check ==="
echo

# 1. Package importable
if python3 -c "import porcupine" 2>/dev/null; then
    ok "porcupine package imports cleanly"
else
    fail "porcupine package not importable — run setup.sh first"
fi

# 2. CLI entry point
if porcupine --help &>/dev/null; then
    ok "porcupine CLI entry point works"
else
    fail "'porcupine --help' failed — check installation"
fi

# 3. Config file
CONFIG="/etc/porcupine/porcupine.conf"
if [[ -f "$CONFIG" ]]; then
    ok "Config file present: $CONFIG"
else
    warn "Config file missing: $CONFIG — defaults will be used"
fi

# 4. I2C LCD
if command -v i2cdetect &>/dev/null; then
    DEC_ADDR="$(printf '%d' "$I2C_ADDR" 2>/dev/null || echo "")"
    HEX_ADDR="$(printf '%x' "$DEC_ADDR" 2>/dev/null || echo "")"
    if i2cdetect -y 1 2>/dev/null | grep -qiE "[[:space:]]${HEX_ADDR}[[:space:]]|[[:space:]]${HEX_ADDR}$"; then
        ok "LCD found at I2C address $I2C_ADDR"
    else
        warn "LCD not detected at $I2C_ADDR — check wiring and i2c_arm=on in /boot/config.txt"
    fi
else
    warn "i2c-tools not installed — run: sudo apt install i2c-tools"
fi

# 5. Temperature sensor (vcgencmd)
if command -v vcgencmd &>/dev/null; then
    TEMP="$(vcgencmd measure_temp 2>/dev/null || echo 'unavailable')"
    ok "vcgencmd available: $TEMP"
else
    warn "vcgencmd not found — temperature monitor will show N/A (non-Pi host?)"
fi

# 6. Service status
if systemctl is-active --quiet porcupine 2>/dev/null; then
    ok "porcupine service is running"
else
    warn "porcupine service is NOT running — check: journalctl -u porcupine"
fi

echo
echo "=== Results: ${PASS} passed, ${WARN} warnings ==="
[[ $WARN -eq 0 ]] && echo "All good!" || echo "Review warnings above before deploying."
