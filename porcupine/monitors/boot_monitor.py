"""Boot count and uptime monitor."""
from . import boot
from .base import _Monitor


class _BootMonitor(_Monitor):
    flag = "boot"

    def __init__(self, every: int = 0) -> None:
        super().__init__(every)

    def read(self) -> dict:
        return boot.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        uptime = int(data.get("uptime_s", 0))
        return [("Boot", f"#{data.get('boot_count', 0)} {uptime // 3600}h{uptime % 3600 // 60:02d}m")]
