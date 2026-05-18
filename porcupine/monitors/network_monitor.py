"""Network interface throughput monitor."""
from . import network
from .base import _Monitor

_KB = 1024
_MB = 1024 * 1024


def _bps_str(bps: float) -> str:
    if bps >= _MB:
        mb = bps / _MB
        return f"{mb:.0f}M" if mb >= 100 else f"{mb:.1f}M"
    if bps >= _KB:
        kb = bps / _KB
        return f"{kb:.0f}K" if kb >= 100 else f"{kb:.1f}K"
    return f"{int(bps)}B"


class _NetMonitor(_Monitor):
    flag = "net"

    def __init__(self, every: int = 0) -> None:
        super().__init__(every)

    def read(self) -> dict:
        return network.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return [(
            f"Net {data.get('interface', '???')[:5]}",
            f"R:{_bps_str(data.get('rx_bps', 0))} T:{_bps_str(data.get('tx_bps', 0))}",
        )]
