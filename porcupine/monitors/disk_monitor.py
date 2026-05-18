"""Disk usage monitor."""
import math

from . import disk
from .base import _Monitor, _is_valid


def _gb_fmt(gb: float) -> str:
    """Format gigabytes compactly — one decimal below 100 GB, integer above."""
    return f"{gb:.0f}" if gb >= 100 else f"{gb:.1f}"


class _DiskMonitor(_Monitor):
    flag = "disk"

    def __init__(self, disk_warn: float = 85.0, every: int = 0) -> None:
        super().__init__(every)
        self._disk_warn = disk_warn

    def read(self) -> dict:
        return disk.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        pct   = data.get("disk_pct",      float("nan"))
        used  = data.get("disk_used_gb",  float("nan"))
        total = data.get("disk_total_gb", float("nan"))
        if not math.isnan(pct):
            pct_s  = "WARN" if pct >= self._disk_warn else f"{pct:.0f}%"
            size_s = f"{_gb_fmt(used)}/{_gb_fmt(total)}GB"
        else:
            pct_s  = "---"
            size_s = ""
        return [("Disk /", f"{pct_s} {size_s}".rstrip())]

    def has_breach(self, data: dict) -> bool:
        pct = data.get("disk_pct")
        return _is_valid(pct) and pct >= self._disk_warn

    def beep_pattern(self) -> dict:
        return {"count": 2, "duration_ms": 400, "gap_ms": 200}
