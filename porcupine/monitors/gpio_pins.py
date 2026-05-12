"""40-pin GPIO header state monitor — reads pin directions and levels via sysfs."""
from pathlib import Path

# Sysfs root — overridable in tests via monkeypatch
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


def _read_bcm(bcm: int) -> dict | None:
    """Return {"direction": "in"|"out", "value": 0|1} for an exported GPIO, else None."""
    base = _SYSFS_ROOT / f"gpio{bcm}"
    if not base.exists():
        return None
    try:
        direction = (base / "direction").read_text().strip()
        value = int((base / "value").read_text().strip())
        return {"direction": direction, "value": value}
    except OSError:
        return None


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
    """
    states: list[str | None] = []
    for kind, bcm in _PINS:
        if kind == "3v3":
            states.append("3v3")
        elif kind == "5v":
            states.append("5v")
        elif kind == "gnd":
            states.append("gnd")
        else:
            info = _read_bcm(bcm)
            if info is None:
                states.append(None)
            elif info["direction"] == "out":
                states.append("out_h" if info["value"] else "out_l")
            else:
                states.append("in_h" if info["value"] else "in_l")
    return {"gpio_pins": states}
