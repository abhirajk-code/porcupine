"""40-pin GPIO header state monitor — reads direction and level via debugfs."""
import re
from pathlib import Path

# debugfs path — overridable in tests via monkeypatch
_DEBUG_GPIO = Path("/sys/kernel/debug/gpio")
# sysfs fallback — used when debugfs is unreadable (e.g. not running as root)
_SYSFS_ROOT = Path("/sys/class/gpio")

# Physical header pins 1-40: (kind, bcm_number|None)
# kind: "3v3" | "5v" | "gnd" | "gpio"
_PINS: list[tuple[str, int | None]] = [
    ("3v3",  None),  # 1
    ("5v",   None),  # 2
    ("gpio", 2),     # 3
    ("5v",   None),  # 4
    ("gpio", 3),     # 5
    ("gnd",  None),  # 6
    ("gpio", 4),     # 7
    ("gpio", 14),    # 8
    ("gnd",  None),  # 9
    ("gpio", 15),    # 10
    ("gpio", 17),    # 11
    ("gpio", 18),    # 12
    ("gpio", 27),    # 13
    ("gnd",  None),  # 14
    ("gpio", 22),    # 15
    ("gpio", 23),    # 16
    ("3v3",  None),  # 17
    ("gpio", 24),    # 18
    ("gpio", 10),    # 19
    ("gnd",  None),  # 20
    ("gpio", 9),     # 21
    ("gpio", 25),    # 22
    ("gpio", 11),    # 23
    ("gpio", 8),     # 24
    ("gnd",  None),  # 25
    ("gpio", 7),     # 26
    ("gpio", 0),     # 27
    ("gpio", 1),     # 28
    ("gpio", 5),     # 29
    ("gnd",  None),  # 30
    ("gpio", 6),     # 31
    ("gpio", 12),    # 32
    ("gpio", 13),    # 33
    ("gnd",  None),  # 34
    ("gpio", 19),    # 35
    ("gpio", 16),    # 36
    ("gpio", 26),    # 37
    ("gpio", 20),    # 38
    ("gnd",  None),  # 39
    ("gpio", 21),    # 40
]

# Regex for a pin line in /sys/kernel/debug/gpio:
#   " gpio-17   (GPIO17              |label               ) in  hi"
_PIN_RE = re.compile(
    r"\s+gpio-(\d+)\s+\([^|]+\|\s*([^)]*?)\s*\)\s+(in|out)\s+(hi|lo)"
)


def _parse_debugfs() -> dict[int, dict]:
    """
    Parse /sys/kernel/debug/gpio → {bcm: {"direction": "in"|"out", "value": 0|1, "label": str}}.

    Identifies the main header GPIO chip by requiring it covers ≥ 28 pins,
    which filters out small I2C expanders. Works on Pi 4 (chip base=0) and
    Pi 5 (chip base offset, e.g. 571). Returns {} on any read failure.
    """
    try:
        text = _DEBUG_GPIO.read_text()
    except OSError:
        return {}

    result: dict[int, dict] = {}
    chip_base: int = 0
    chip_ok: bool = False

    for line in text.splitlines():
        m = re.match(r"gpiochip\d+: GPIOs (\d+)-(\d+)", line)
        if m:
            chip_base = int(m.group(1))
            chip_ok   = int(m.group(2)) - chip_base + 1 >= 28
            continue

        if not chip_ok:
            continue

        m = _PIN_RE.match(line)
        if not m:
            continue

        bcm = int(m.group(1)) - chip_base
        if 0 <= bcm <= 27:
            result[bcm] = {
                "direction": m.group(3),
                "value":     1 if m.group(4) == "hi" else 0,
                "label":     m.group(2).strip(),
            }

    return result


def _parse_sysfs() -> dict[int, dict]:
    """Fallback: read only pins that have been exported to /sys/class/gpio."""
    result: dict[int, dict] = {}
    for _, bcm in _PINS:
        if bcm is None:
            continue
        base = _SYSFS_ROOT / f"gpio{bcm}"
        if not base.exists():
            continue
        try:
            direction = (base / "direction").read_text().strip()
            value     = int((base / "value").read_text().strip())
            result[bcm] = {"direction": direction, "value": value, "label": ""}
        except OSError:
            pass
    return result


def read() -> dict:
    """
    Return {"gpio_pins": list[str|None]} — 40 entries in physical header order.

    Each entry is one of:
      "3v3"   3.3 V power pin
      "5v"    5 V power pin
      "gnd"   ground pin
      "out_h" GPIO output, level high
      "out_l" GPIO output, level low
      "in_h"  GPIO input, level high
      "in_l"  GPIO input, level low
      None    GPIO not exported / unconfigured

    Reads from /sys/kernel/debug/gpio (single file, shows all pins including
    hardware-claimed ones). Falls back to /sys/class/gpio if debugfs is
    unreadable (e.g. not running as root).
    """
    gpio_data = _parse_debugfs() or _parse_sysfs()

    states: list[str | None] = []
    for kind, bcm in _PINS:
        if kind != "gpio":
            states.append(kind)
        else:
            info = gpio_data.get(bcm)
            if info is None:
                states.append(None)
            elif info["direction"] == "out":
                states.append("out_h" if info["value"] else "out_l")
            else:
                states.append("in_h" if info["value"] else "in_l")
    return {"gpio_pins": states}
