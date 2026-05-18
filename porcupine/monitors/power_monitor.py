"""Battery / power-source monitor (INA219)."""
import math

from . import power
from .base import _Monitor, _is_valid


class _PowerMonitor(_Monitor):
    flag = "power"

    def __init__(self, bat_warn: float = 40.0, every: int = 0) -> None:
        super().__init__(every)
        self._bat_warn = bat_warn

    def read(self) -> dict:
        return power.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        source = data.get("power_source", "Unknown")
        pct    = data.get("battery_pct", float("nan"))
        if not math.isnan(pct):
            warn   = source == "Battery" and pct < self._bat_warn
            suffix = f" {pct:.0f}%" + (" WARN" if warn else "")
        else:
            suffix = ""
        return [("Power", f"{source}{suffix}")]

    def has_breach(self, data: dict) -> bool:
        pct = data.get("battery_pct")
        return (
            _is_valid(pct)
            and data.get("power_source") == "Battery"
            and pct < self._bat_warn
        )

    def beep_pattern(self) -> dict:
        return {"count": 1, "duration_ms": 600, "gap_ms": 0}
