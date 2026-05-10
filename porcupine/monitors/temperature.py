"""CPU temperature and throttle status (Raspberry Pi)."""
import subprocess
from pathlib import Path

THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"


def _read_temp_c() -> float:
    try:
        raw = int(Path(THERMAL_PATH).read_text().strip())
        return round(raw / 1000.0, 1)
    except (FileNotFoundError, ValueError):
        return float("nan")


def _read_throttle_flags() -> int:
    """Return vcgencmd throttle bitmask, or -1 if unavailable."""
    try:
        out = subprocess.check_output(
            ["vcgencmd", "get_throttled"], text=True, timeout=1
        )
        # output: "throttled=0x50005"
        return int(out.strip().split("=")[1], 16)
    except Exception:
        return -1


def read() -> dict:
    temp_c = _read_temp_c()
    flags = _read_throttle_flags()
    return {
        "cpu_temp_c": temp_c,
        # None when vcgencmd is unavailable (non-Pi host)
        "throttled": (flags > 0) if flags >= 0 else None,
        "throttle_flags": flags,
    }
