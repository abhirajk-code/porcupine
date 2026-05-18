"""CPU usage and memory monitor."""
from . import cpu_mem
from .base import _Monitor, _is_valid


class _CpuMemMonitor(_Monitor):
    flag = "cpu"

    def __init__(self, cpu_warn: float = 90.0, mem_warn: float = 90.0, every: int = 0) -> None:
        super().__init__(every)
        self._cpu_warn = cpu_warn
        self._mem_warn = mem_warn

    def read(self) -> dict:
        return cpu_mem.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        cpu   = data.get("cpu_avg_pct", 0)
        mem   = data.get("mem_pct", 0)
        cpu_s = "WARN" if cpu >= self._cpu_warn else f"{cpu:.0f}%"
        mem_s = "WARN" if mem >= self._mem_warn else f"{mem:.0f}%"
        return [(" CPU   Mem", f"{cpu_s:>4}  {mem_s:>4}")]

    def has_breach(self, data: dict) -> bool:
        cpu = data.get("cpu_avg_pct")
        mem = data.get("mem_pct")
        return (
            (_is_valid(cpu) and cpu >= self._cpu_warn)
            or (_is_valid(mem) and mem >= self._mem_warn)
        )

    def beep_pattern(self) -> dict:
        return {"count": 2, "duration_ms": 200, "gap_ms": 100}
