"""WiFi connection, IP, and signal monitor."""
import math

from . import wifi
from .base import _Monitor


class _WifiMonitor(_Monitor):
    flag = "wifi"

    def __init__(self, every: int = 0) -> None:
        super().__init__(every)

    def read(self) -> dict:
        return wifi.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        connected = data.get("wifi_connected")
        ip        = data.get("wifi_ip")
        signal    = data.get("wifi_signal_dbm", float("nan"))

        sig_str = f" {signal:.0f}dBm" if not math.isnan(signal) else ""
        header  = f"WiFi{sig_str}"

        if connected is True:
            line2 = ip or "No IP"
        elif connected is False:
            line2 = "Disconnected"
        else:
            line2 = "---"

        return [(header, line2)]

    def has_breach(self, data: dict) -> bool:
        # Only breach when WiFi hardware is present but not connected
        return data.get("wifi_connected") is False and data.get("wifi_iface") is not None

    def beep_pattern(self) -> dict:
        return {"count": 2, "duration_ms": 400, "gap_ms": 200}
