"""Tracks boot count and uptime."""
import time
from pathlib import Path

import psutil

BOOTCOUNT_PATH = "/var/lib/porcupine/bootcount"

_boot_count: int = 0


def init(path: str = BOOTCOUNT_PATH) -> None:
    """Increment and persist boot count. Call once at daemon startup."""
    global _boot_count
    p = Path(path)
    try:
        count = int(p.read_text().strip())
    except (FileNotFoundError, ValueError):
        count = 0
    _boot_count = count + 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(_boot_count))


def read() -> dict:
    uptime_s = time.time() - psutil.boot_time()
    return {
        "boot_count": _boot_count,
        "uptime_s": round(uptime_s, 1),
    }
