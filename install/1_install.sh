#!/usr/bin/env bash
# Step 1 of 3 — Install package, config, and service template.
# Does NOT enable the service; run step 3 when ready.
#
# Usage:
#   sudo bash install/1_install.sh                  (interactive config)
#   sudo bash install/1_install.sh --non-interactive (all defaults)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
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
NON_INTERACTIVE=false
for arg in "$@"; do
    case "$arg" in
        --non-interactive|--yes|-y) NON_INTERACTIVE=true ;;
        *) die "Unknown argument: $arg  (usage: 1_install.sh [--non-interactive])" ;;
    esac
done
[[ -t 0 ]] || NON_INTERACTIVE=true

# ---------------------------------------------------------------------------
# Root check
# ---------------------------------------------------------------------------
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run as root: sudo bash $0"

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
# Config helpers
# ---------------------------------------------------------------------------

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

prompt() {
    local question="$1" default="$2" varname="$3"
    local input
    read -r -p "  $question [$default]: " input
    printf -v "$varname" '%s' "${input:-$default}"
}

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
    echo " Porcupine — Step 1: Configuration"
    echo " Press Enter to keep the value in [  ]."
    echo " Existing config values shown as defaults."
    echo "========================================"

    local d_lcd;    d_lcd="$(_cfg_get    hardware lcd_addr   0x27)"
    local d_btn;    d_btn="$(_cfg_get    hardware button_pin 17)"
    local d_buz;    d_buz="$(_cfg_get    hardware buzzer_pin 18)"
    local d_ref;    d_ref="$(_cfg_get    display  refresh    3)"
    local d_power;  d_power="$(_cfg_get  monitors power      true)"
    local d_cpu;    d_cpu="$(_cfg_get    monitors cpu        true)"
    local d_temp;   d_temp="$(_cfg_get   monitors temp       true)"
    local d_net;    d_net="$(_cfg_get    monitors net        true)"
    local d_twarn;  d_twarn="$(_cfg_get  alerts   temp_warn  80)"
    local d_cwarn;  d_cwarn="$(_cfg_get  alerts   cpu_warn   90)"
    local d_mwarn;  d_mwarn="$(_cfg_get  alerts   mem_warn   90)"

    h2 "Hardware"
    prompt      "LCD I2C address  (hex ok, e.g. 0x27 or 0x3f)" "$d_lcd"   LCD_ADDR
    prompt      "Button GPIO pin  (BCM numbering)"              "$d_btn"   BUTTON_PIN
    prompt      "Buzzer GPIO pin  (BCM numbering)"              "$d_buz"   BUZZER_PIN

    h2 "Display"
    prompt      "Screen refresh interval in seconds"            "$d_ref"   REFRESH

    h2 "Monitors  (y = enable, n = disable)"
    prompt_bool "Power / uptime monitor"                        "$d_power" ENABLE_POWER
    prompt_bool "CPU & memory monitor"                          "$d_cpu"   ENABLE_CPU
    prompt_bool "Temperature monitor"                           "$d_temp"  ENABLE_TEMP
    prompt_bool "Network monitor"                               "$d_net"   ENABLE_NET

    h2 "Alert thresholds"
    prompt "CPU temperature warning (°C)"                       "$d_twarn" TEMP_WARN
    prompt "CPU usage warning       (%, sustained 30 s)"        "$d_cwarn" CPU_WARN
    prompt "Memory usage warning    (%)"                        "$d_mwarn" MEM_WARN
}

configure_noninteractive() {
    LCD_ADDR="0x27"; BUTTON_PIN="17"; BUZZER_PIN="18"; REFRESH="3"
    ENABLE_POWER="true"; ENABLE_CPU="true"; ENABLE_TEMP="true"; ENABLE_NET="true"
    TEMP_WARN="80"; CPU_WARN="90"; MEM_WARN="90"
    info "Non-interactive — using all defaults"
}

write_config() {
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_FILE" <<EOF
# Porcupine system monitor — generated by 1_install.sh $(date '+%Y-%m-%d %H:%M')
# Re-run 1_install.sh to reconfigure, or edit this file directly.

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
# Run config step
# ---------------------------------------------------------------------------
if $NON_INTERACTIVE; then
    configure_noninteractive
else
    configure_interactive
fi

# ---------------------------------------------------------------------------
# Directories and config
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
# Install service template (but do NOT enable/start yet)
# ---------------------------------------------------------------------------
sed "s|@@PORCUPINE_BIN@@|${PORCUPINE_BIN}|g" \
    "$INSTALL_DIR/install/porcupine.service" > "$SERVICE_DEST"
systemctl daemon-reload
ok "Service template installed → $SERVICE_DEST  (not yet enabled)"

echo
echo "============================================"
echo " Step 1 complete!"
echo " Next: sudo bash $SCRIPT_DIR/2_test.sh"
echo "============================================"
