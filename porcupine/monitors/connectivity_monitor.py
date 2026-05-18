"""Internet connectivity and latency monitor."""
from . import connectivity
from .base import _Monitor


class _ConnectivityMonitor(_Monitor):
    flag = "conn"

    def __init__(self, host: str = "8.8.8.8", every: int = 0) -> None:
        super().__init__(every)
        self._host = host

    def read(self) -> dict:
        return connectivity.read(host=self._host)

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        reachable  = data.get("reachable")
        latency_ms = data.get("latency_ms", float("nan"))
        if reachable is True:
            line2 = f"OK {latency_ms:.1f}ms"
        elif reachable is False:
            line2 = "UNREACHABLE"
        else:
            line2 = "---"
        return [("Internet", line2)]

    def has_breach(self, data: dict) -> bool:
        return data.get("reachable") is False

    def beep_pattern(self) -> dict:
        return {"count": 3, "duration_ms": 300, "gap_ms": 150}
