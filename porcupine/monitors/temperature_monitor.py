"""CPU temperature and throttle-state monitor."""
import math

from . import temperature
from .base import _Monitor, _is_valid


class _TempMonitor(_Monitor):
    flag = "temp"

    def __init__(self, temp_warn: float = 80.0, every: int = 0) -> None:
        super().__init__(every)
        self._temp_warn = temp_warn

    def read(self) -> dict:
        return temperature.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        temp      = data.get("cpu_temp_c", float("nan"))
        throttled = data.get("throttled")
        if not math.isnan(temp):
            temp_str = f"{temp:.0f}C" if temp >= 100 else f"{temp:.1f}C"
            parts    = []
            if temp >= self._temp_warn:
                parts.append("WARN")
            if throttled:
                parts.append("THRT")
            suffix = (" " + "+".join(parts)) if parts else ""
        else:
            temp_str = "---"
            suffix   = " THRT" if throttled else ""
        return [("Temperature", f"{temp_str}{suffix}")]

    def has_breach(self, data: dict) -> bool:
        temp      = data.get("cpu_temp_c")
        throttled = data.get("throttled")
        return (
            (_is_valid(temp) and temp >= self._temp_warn)
            or throttled is True
        )

    def beep_pattern(self) -> dict:
        return {"count": 3, "duration_ms": 200, "gap_ms": 100}
