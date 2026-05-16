#!/usr/bin/env bash
# Install porcupine — package, config, and service template.
# Does NOT enable the service; run enable.sh when ready.
#
# Usage:
#   sudo bash install/install.sh                  (interactive config)
#   sudo bash install/install.sh --non-interactive (all defaults)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="/etc/porcupine"
DATA_DIR="/var/lib/porcupine"
VENV_DIR="/opt/porcupine/venv"
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
        *) die "Unknown argument: $arg  (usage: install.sh [--non-interactive])" ;;
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

    local d_lcd;    d_lcd="$(_cfg_get    hardware lcd_addr    0x27)"
    local d_btn;    d_btn="$(_cfg_get    hardware button_pin  4)"
    local d_buz;    d_buz="$(_cfg_get    hardware buzzer_pin  18)"
    local d_ina;    d_ina="$(_cfg_get    hardware ina219_addr 0x41)"
    local d_ref;    d_ref="$(_cfg_get    display  refresh     5)"
    local d_boot_ev;  d_boot_ev="$(_cfg_get  monitors boot_every  10)"
    local d_power_ev; d_power_ev="$(_cfg_get monitors power_every  5)"
    local d_cpu_ev;   d_cpu_ev="$(_cfg_get  monitors cpu_every    5)"
    local d_temp_ev;  d_temp_ev="$(_cfg_get monitors temp_every   1)"
    local d_net_ev;   d_net_ev="$(_cfg_get  monitors net_every   10)"
    local d_gpio_ev;  d_gpio_ev="$(_cfg_get monitors gpio_every   2)"
    local d_disk_ev;  d_disk_ev="$(_cfg_get monitors disk_every  30)"
    local d_conn_ev;  d_conn_ev="$(_cfg_get monitors conn_every  12)"
    local d_wifi_ev;  d_wifi_ev="$(_cfg_get monitors wifi_every  60)"
    # Convert cycle value to bool default for the yes/no prompt (0 = disabled)
    local d_boot;   [[ "$d_boot_ev"  != "0" ]] && d_boot="true"  || d_boot="false"
    local d_power;  [[ "$d_power_ev" != "0" ]] && d_power="true" || d_power="false"
    local d_cpu;    [[ "$d_cpu_ev"   != "0" ]] && d_cpu="true"   || d_cpu="false"
    local d_temp;   [[ "$d_temp_ev"  != "0" ]] && d_temp="true"  || d_temp="false"
    local d_net;    [[ "$d_net_ev"   != "0" ]] && d_net="true"   || d_net="false"
    local d_gpio;   [[ "$d_gpio_ev"  != "0" ]] && d_gpio="true"  || d_gpio="false"
    local d_disk;   [[ "$d_disk_ev"  != "0" ]] && d_disk="true"  || d_disk="false"
    local d_conn;   [[ "$d_conn_ev"  != "0" ]] && d_conn="true"  || d_conn="false"
    local d_wifi;   [[ "$d_wifi_ev"  != "0" ]] && d_wifi="true"  || d_wifi="false"
    local d_twarn;  d_twarn="$(_cfg_get  alerts   temp_warn  80)"
    local d_cwarn;  d_cwarn="$(_cfg_get  alerts   cpu_warn   90)"
    local d_mwarn;  d_mwarn="$(_cfg_get  alerts   mem_warn   90)"
    local d_bwarn;  d_bwarn="$(_cfg_get  alerts   bat_warn   40)"
    local d_dwarn;  d_dwarn="$(_cfg_get  alerts   disk_warn  85)"
    local d_chost;  d_chost="$(_cfg_get  network  conn_host  8.8.8.8)"
    local d_alog;   d_alog="$(_cfg_get   alerts   alert_log  /var/log/porcupine/alerts.log)"
    local d_only;   d_only="$(_cfg_get   display  only_alert false)"

    h2 "Hardware"
    prompt      "LCD I2C address  (hex ok, e.g. 0x27 or 0x3f)" "$d_lcd"   LCD_ADDR
    prompt      "Button GPIO pin  (BCM numbering)"              "$d_btn"   BUTTON_PIN
    prompt      "Buzzer GPIO pin  (BCM numbering)"              "$d_buz"   BUZZER_PIN
    prompt      "INA219 I2C address (hex ok, e.g. 0x41)"       "$d_ina"   INA219_ADDR

    h2 "Display"
    prompt      "Screen refresh interval in seconds"            "$d_ref"   REFRESH
    prompt_bool "Only-alert mode (LCD off until threshold breach)" "$d_only" ONLY_ALERT

    h2 "Monitors  (y = enable, n = disable)"
    prompt_bool "Boot / uptime monitor"                         "$d_boot"  ENABLE_BOOT
    prompt_bool "Power / INA219 battery monitor"                "$d_power" ENABLE_POWER
    prompt_bool "CPU & memory monitor"                          "$d_cpu"   ENABLE_CPU
    prompt_bool "Temperature monitor"                           "$d_temp"  ENABLE_TEMP
    prompt_bool "Network monitor"                               "$d_net"   ENABLE_NET
    prompt_bool "GPIO 40-pin header monitor"                    "$d_gpio"  ENABLE_GPIO
    prompt_bool "Disk space monitor"                            "$d_disk"  ENABLE_DISK
    prompt_bool "Internet connectivity monitor"                 "$d_conn"  ENABLE_CONN
    prompt_bool "WiFi monitor"                                  "$d_wifi"  ENABLE_WIFI

    h2 "Alert thresholds"
    prompt "CPU temperature warning (°C)"                       "$d_twarn" TEMP_WARN
    prompt "CPU usage warning       (%, sustained 30 s)"        "$d_cwarn" CPU_WARN
    prompt "Memory usage warning    (%)"                        "$d_mwarn" MEM_WARN
    prompt "Battery warning         (% below which to warn)"    "$d_bwarn" BAT_WARN
    prompt "Disk usage warning      (%)"                        "$d_dwarn" DISK_WARN
    prompt "Connectivity check host (IP or hostname)"           "$d_chost" CONN_HOST
    prompt "Alert log path"                                     "$d_alog"  ALERT_LOG
}

configure_noninteractive() {
    LCD_ADDR="0x27"; BUTTON_PIN="4"; BUZZER_PIN="18"; INA219_ADDR="0x41"; REFRESH="5"
    ONLY_ALERT="false"
    ENABLE_BOOT="true"; ENABLE_POWER="true"; ENABLE_CPU="true"; ENABLE_TEMP="true"
    ENABLE_NET="true"; ENABLE_GPIO="true"; ENABLE_DISK="true"; ENABLE_CONN="true"
    ENABLE_WIFI="true"
    TEMP_WARN="80"; CPU_WARN="90"; MEM_WARN="90"; BAT_WARN="40"; DISK_WARN="85"
    CONN_HOST="8.8.8.8"; ALERT_LOG="/var/log/porcupine/alerts.log"
    info "Non-interactive — using all defaults"
}

write_config() {
    # Convert enable/disable booleans to cycle frequency (0=disabled, else default freq)
    local be pe ce te ne ge dke cke wke
    [[ "$ENABLE_BOOT"  == "true" ]] && be=10  || be=0
    [[ "$ENABLE_POWER" == "true" ]] && pe=5   || pe=0
    [[ "$ENABLE_CPU"   == "true" ]] && ce=5   || ce=0
    [[ "$ENABLE_TEMP"  == "true" ]] && te=1   || te=0
    [[ "$ENABLE_NET"   == "true" ]] && ne=10  || ne=0
    [[ "$ENABLE_GPIO"  == "true" ]] && ge=2   || ge=0
    [[ "$ENABLE_DISK"  == "true" ]] && dke=30 || dke=0
    [[ "$ENABLE_CONN"  == "true" ]] && cke=12 || cke=0
    [[ "$ENABLE_WIFI"  == "true" ]] && wke=60 || wke=0

    mkdir -p "$CONFIG_DIR" /var/log/porcupine
    cat > "$CONFIG_FILE" <<EOF
# Porcupine system monitor — generated by install.sh $(date '+%Y-%m-%d %H:%M')
# Re-run install.sh to reconfigure, or edit this file directly.

[monitors]
boot_every  = ${be}
power_every = ${pe}
cpu_every   = ${ce}
temp_every  = ${te}
net_every   = ${ne}
gpio_every  = ${ge}
disk_every  = ${dke}
conn_every  = ${cke}
wifi_every  = ${wke}

[hardware]
lcd_addr    = ${LCD_ADDR}
button_pin  = ${BUTTON_PIN}
buzzer_pin  = ${BUZZER_PIN}
ina219_addr = ${INA219_ADDR}

[display]
refresh    = ${REFRESH}
only_alert = ${ONLY_ALERT}

[network]
conn_host = ${CONN_HOST}

[alerts]
temp_warn = ${TEMP_WARN}
cpu_warn  = ${CPU_WARN}
mem_warn  = ${MEM_WARN}
bat_warn  = ${BAT_WARN}
disk_warn = ${DISK_WARN}
alert_log = ${ALERT_LOG}
EOF
    ok "Config written → $CONFIG_FILE"
}

# ---------------------------------------------------------------------------
# Run config step
# ---------------------------------------------------------------------------
SKIP_CONFIG=false
if [[ -f "$CONFIG_FILE" ]]; then
    if $NON_INTERACTIVE; then
        info "Existing config found — keeping $CONFIG_FILE"
        SKIP_CONFIG=true
    else
        echo
        echo "  Existing config found: $CONFIG_FILE"
        KEEP_EXISTING="true"
        prompt_bool "Keep existing config? (n = reconfigure from scratch)" "true" KEEP_EXISTING
        [[ "$KEEP_EXISTING" == "true" ]] && SKIP_CONFIG=true
    fi
fi

if ! $SKIP_CONFIG; then
    if $NON_INTERACTIVE; then
        configure_noninteractive
    else
        configure_interactive
    fi
fi

# ---------------------------------------------------------------------------
# Directories and config
# ---------------------------------------------------------------------------
mkdir -p "$CONFIG_DIR" "$DATA_DIR"
ok "Directories: $CONFIG_DIR, $DATA_DIR"
if ! $SKIP_CONFIG; then
    write_config
fi

# ---------------------------------------------------------------------------
# Create virtual environment and install package
# (avoids the PEP 668 "externally-managed-environment" error on Pi OS 12+)
# ---------------------------------------------------------------------------
echo
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at $VENV_DIR..."
    # --system-site-packages lets the venv inherit apt-installed packages
    # (RPi.GPIO, psutil, smbus2, lgpio) without re-downloading them.
    "$PY" -m venv --system-site-packages "$VENV_DIR"
elif ! grep -q "^include-system-site-packages = true" "$VENV_DIR/pyvenv.cfg" 2>/dev/null; then
    info "Existing venv lacks --system-site-packages; recreating..."
    rm -rf "$VENV_DIR"
    "$PY" -m venv --system-site-packages "$VENV_DIR"
else
    info "Reusing existing virtual environment at $VENV_DIR"
fi
ok "Virtual environment: $VENV_DIR"

info "Installing Python package into venv..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
# --force-reinstall ensures the installed package matches the source tree
# even when the version number hasn't changed (e.g. after a git pull).
"$VENV_DIR/bin/pip" install --quiet --force-reinstall "$INSTALL_DIR"
PORCUPINE_BIN="$VENV_DIR/bin/porcupine"
[[ -f "$PORCUPINE_BIN" ]] || die "'porcupine' binary not found in venv after install"
ok "Package installed → $PORCUPINE_BIN"

# ---------------------------------------------------------------------------
# Install management CLI
# ---------------------------------------------------------------------------
cp "$SCRIPT_DIR/porcupine" /usr/local/bin/porcupine
chmod +x /usr/local/bin/porcupine
ok "Management CLI installed → /usr/local/bin/porcupine"

# Copy test assets so 'porcupine test' works independently of the source tree
cp "$SCRIPT_DIR/test_hardware.py" /opt/porcupine/test_hardware.py
cp "$SCRIPT_DIR/test.sh"          /opt/porcupine/test.sh
ok "Test assets installed → /opt/porcupine/"

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
echo " Next: sudo porcupine test"
echo "============================================"
