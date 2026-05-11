#!/usr/bin/env bash
# Collect system information for porcupine install diagnostics.
# Usage: bash install/sysinfo.sh
# Output: ~/porcupine_sysinfo.txt

OUT="$HOME/porcupine_sysinfo.txt"

{
  echo "=== OS ==="
  cat /etc/os-release
  echo

  echo "=== Pi Model ==="
  cat /proc/device-tree/model 2>/dev/null \
    || cat /sys/firmware/devicetree/base/model 2>/dev/null \
    || echo "unknown"
  echo

  echo "=== Python ==="
  python3 --version
  python3 -c "import sys; print(sys.executable)"
  echo

  echo "=== pip ==="
  pip3 --version 2>/dev/null || echo "pip3 not found"
  echo

  echo "=== I2C devices ==="
  ls /dev/i2c* 2>/dev/null || echo "none"
  echo

  echo "=== GPIO ==="
  ls /dev/gpiomem /dev/gpio* 2>/dev/null || echo "none"
  echo

  echo "=== Installed python3 apt packages ==="
  dpkg -l "python3*" 2>/dev/null | grep "^ii" || echo "none"
  echo

  echo "=== pip list (system) ==="
  pip3 list 2>/dev/null || echo "unavailable"
  echo

  echo "=== pip install dry-run: RPi.GPIO ==="
  pip3 install --dry-run RPi.GPIO 2>&1 || true
  echo

  echo "=== pip install dry-run: RPLCD ==="
  pip3 install --dry-run RPLCD 2>&1 || true
  echo

  echo "=== pip install dry-run: psutil ==="
  pip3 install --dry-run psutil 2>&1 || true
  echo

  echo "=== pip install dry-run: smbus2 ==="
  pip3 install --dry-run smbus2 2>&1 || true
  echo

  echo "=== apt: python3-rpi.gpio ==="
  apt-cache show python3-rpi.gpio 2>/dev/null | grep -E "^(Package|Version)" \
    || echo "not in apt"
  echo

  echo "=== apt: python3-smbus ==="
  apt-cache show python3-smbus 2>/dev/null | grep -E "^(Package|Version)" \
    || echo "not in apt"
  echo

  echo "=== apt: python3-psutil ==="
  apt-cache show python3-psutil 2>/dev/null | grep -E "^(Package|Version)" \
    || echo "not in apt"
  echo

  echo "=== apt: python3-rplcd ==="
  apt-cache show python3-rplcd 2>/dev/null | grep -E "^(Package|Version)" \
    || echo "not in apt"

} > "$OUT" 2>&1

echo "Done — saved to $OUT"
