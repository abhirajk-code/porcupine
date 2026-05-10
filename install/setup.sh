#!/usr/bin/env bash
# Porcupine install / uninstall script.
# Usage:
#   sudo bash install/setup.sh                  — interactive install
#   sudo bash install/setup.sh --non-interactive — silent install, all defaults
#   sudo bash install/setup.sh --uninstall       — remove service + package
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="/etc/porcupine"
DATA_DIR="/var/lib/porcupine"
SERVICE_NAME="porcupine"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_FILE="$CONFIG_DIR/porcupine.conf"
MIN_PY_MINOR=9

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
info() { echo "[INFO]  $*"; }
ok()   { echo "[ OK ]  $*"; }
die()  { echo "[FAIL]  $*" >&2; exit 1; }
h2()   { echo; echo "--- $* ---"; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
UNINSTALL=false
NON_INTERACTIVE=false
for arg in "$@"; do
    case "$arg" in
        --uninstall)                        UNINSTALL=true ;;
        --non-interactive|--yes|-y)         NON_INTERACTIVE=true ;;
        *) die "Unknown argument: $arg
Usage: setup.sh [--uninstall] [--non-interactive]" ;;
    esac
done

# Auto-detect non-interactive when stdin is not a terminal (e.g. piped install)
[[ -t 0 ]] || NON_INTERACTIVE=true

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
    echo "  Config preserved : $CONFIG_DIR"
    echo "  Data  preserved  : $DATA_DIR"
    echo "  Remove manually if no longer needed."
    exit 0
fi

# ---------------------------------------------------------------------------
# Python version check (≥ 3.9) — must come first so _cfg_get can use Python
# ---------------------------------------------------------------------------
PY="$(command -v python3)" || die "python3 not found — install it first"
PY_VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MINOR="${PY_VER#*.}"
[[ "${PY_VER%%.*}" -ge 3 && "$PY_MINOR" -ge $MIN_PY_MINOR ]] \
    || die "Python 3.${MIN_PY_MINOR}+ required (found $PY_VER)"
ok "Python $PY_VER at $PY"

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

# Read a value from the existing config file (if present), else return default.
_cfg_get() {
    local section="$1" option="$2" default="$3"
    "$PY" - "$section" "$option" "$default" "$CONFIG_FILE" <<'PYEOF'
import configparser, sys
section, option, default, path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
cp = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
cp.read(path)
try:
    print(cp.get(section, option))
except Exception:
    print(default)
PYEOF
}

# Prompt for a string value; press Enter to accept the shown default.
prompt() {
    local question="$1" default="$2" varname="$3"
    local input
    read -r -p "  $question [$default]: " input
    printf -v "$varname" '%s' "${input:-$default}"
}

# Prompt for a boolean value (y/n); press Enter to accept the shown default.
prompt_bool() {
    local question="$1" default="$2" varname="$3"
    local display input
    [[ "$default" == "true" ]] && display="Y/n" || display="y/N"
    read -r -p "  $question [$display]: " input
    input="${input:-$default}"
    case "${input,,}" in
        y|yes|true|1)  printf -v "$varname" 'true'  ;;
        *)              printf -v "$varname" 'false' ;;
    esac
}

# ---------------------------------------------------------------------------
# Interactive configuration
# ---------------------------------------------------------------------------
configure_interactive() {
    echo
    echo "========================================"
    echo " Porcupine configuration"
    echo " Press Enter to keep the value in [  ]."
    echo " Existing values are loaded as defaults."
    echo "========================================"

    # Load current values (or hardcoded defaults if no config exists)
    local d_lcd;    d_lcd="$(_cfg_get hardware  lcd_addr   0x27)"
    local d_btn;    d_btn="$(_cfg_get hardware  button_pin 17)"
    local d_buz;    d_buz="$(_cfg_get hardware  buzzer_pin 18)"
    local d_ref;    d_ref="$(_cfg_get display   refresh    3)"
    local d_power;  d_power="$(_cfg_get monitors power true)"
    local d_cpu;    d_cpu="$(_cfg_get   monitors cpu   true)"
    local d_temp;   d_temp="$(_cfg_get  monitors temp  true)"
    local d_net;    d_net="$(_cfg_get   monitors net   true)"
    local d_twarn;  d_twarn="$(_cfg_get alerts temp_warn 80)"
    local d_cwarn;  d_cwarn="$(_cfg_get alerts cpu_warn  90)"
    local d_mwarn;  d_mwarn="$(_cfg_get alerts mem_warn  90)"

    h2 "Hardware"
    prompt      "LCD I2C address  (hex ok, e.g. 0x27 or 0x3f)"  "$d_lcd"   LCD_ADDR
    prompt      "Button GPIO pin  (BCM numbering)"               "$d_btn"   BUTTON_PIN
    prompt      "Buzzer GPIO pin  (BCM numbering)"               "$d_buz"   BUZZER_PIN

    h2 "Display"
    prompt      "Screen refresh interval in seconds"             "$d_ref"   REFRESH

    h2 "Monitors  (y = enable, n = disable)"
    prompt_bool "Power / uptime monitor"                         "$d_power" ENABLE_POWER
    prompt_bool "CPU & memory monitor"                           "$d_cpu"   ENABLE_CPU
    prompt_bool "Temperature monitor"                            "$d_temp"  ENABLE_TEMP
    prompt_bool "Network monitor"                                "$d_net"   ENABLE_NET

    h2 "Alert thresholds"
    prompt "CPU temperature warning (°C)"                        "$d_twarn" TEMP_WARN
    prompt "CPU usage warning       (%, sustained 30 s)"         "$d_cwarn" CPU_WARN
    prompt "Memory usage warning    (%)"                         "$d_mwarn" MEM_WARN
}

# ---------------------------------------------------------------------------
# Non-interactive: use hardcoded defaults (existing config unaffected)
# ---------------------------------------------------------------------------
configure_noninteractive() {
    LCD_ADDR="0x27"
    BUTTON_PIN="17"
    BUZZER_PIN="18"
    REFRESH="3"
    ENABLE_POWER="true"
    ENABLE_CPU="true"
    ENABLE_TEMP="true"
    ENABLE_NET="true"
    TEMP_WARN="80"
    CPU_WARN="90"
    MEM_WARN="90"
    info "Non-interactive mode — using all defaults"
}

# ---------------------------------------------------------------------------
# Write config file from collected values
# ---------------------------------------------------------------------------
write_config() {
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_FILE" <<EOF
# Porcupine system monitor — generated by setup.sh $(date '+%Y-%m-%d %H:%M')
# Re-run setup.sh to reconfigure, or edit this file directly.

[monitors]
power = ${ENABLE_POWER}
cpu   = ${ENABLE_CPU}
temp  = ${ENABLE_TEMP}
net   = ${ENABLE_NET}

[hardware]
lcd_addr   = ${LCD_ADDR}
button_pin = ${BUTTON_PIN}
buzzer_pin = ${BUZZER_PIN}

[display]
refresh = ${REFRESH}

[alerts]
temp_warn = ${TEMP_WARN}
cpu_warn  = ${CPU_WARN}
mem_warn  = ${MEM_WARN}
EOF
    ok "Config written → $CONFIG_FILE"
}

# ---------------------------------------------------------------------------
# Run configuration step
# ---------------------------------------------------------------------------
if $NON_INTERACTIVE; then
    configure_noninteractive
else
    configure_interactive
fi

# ---------------------------------------------------------------------------
# Create runtime directories and write config
# ---------------------------------------------------------------------------
mkdir -p "$CONFIG_DIR" "$DATA_DIR"
ok "Directories: $CONFIG_DIR, $DATA_DIR"
write_config

# ---------------------------------------------------------------------------
# Install Python package
# ---------------------------------------------------------------------------
echo
info "Installing Python package..."
"$PY" -m pip install --quiet -r "$INSTALL_DIR/requirements.txt"
"$PY" -m pip install --quiet "$INSTALL_DIR"
PORCUPINE_BIN="$(command -v porcupine 2>/dev/null)" \
    || die "'porcupine' binary not found in PATH after install"
ok "Package installed → $PORCUPINE_BIN"

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
echo " Config : $CONFIG_FILE"
echo " Data   : $DATA_DIR"
echo " Logs   : journalctl -u porcupine -f"
echo " Check  : bash $INSTALL_DIR/install/check.sh"
echo "============================================"
