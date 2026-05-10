"""Network rx/tx rate and totals for the best active interface."""
import time

import psutil

_prev_counters: dict | None = None
_prev_time: float = 0.0
_PREFERRED = ("eth0", "wlan0", "en0", "wlan1")


def _best_interface() -> str:
    stats = psutil.net_if_stats()
    for name in _PREFERRED:
        if name in stats and stats[name].isup:
            return name
    for name, stat in stats.items():
        if stat.isup and name != "lo":
            return name
    return "lo"


def read() -> dict:
    global _prev_counters, _prev_time

    iface = _best_interface()
    all_counters = psutil.net_io_counters(pernic=True)
    now = time.monotonic()
    current = all_counters.get(iface)

    if current is None:
        return {"interface": iface, "rx_bps": 0.0, "tx_bps": 0.0,
                "rx_total_mb": 0.0, "tx_total_mb": 0.0}

    rx_bps = tx_bps = 0.0
    if _prev_counters and iface in _prev_counters:
        dt = now - _prev_time
        if dt > 0:
            prev = _prev_counters[iface]
            rx_bps = (current.bytes_recv - prev.bytes_recv) / dt
            tx_bps = (current.bytes_sent - prev.bytes_sent) / dt

    _prev_counters = {iface: current}
    _prev_time = now

    return {
        "interface": iface,
        "rx_bps": round(max(rx_bps, 0.0), 1),
        "tx_bps": round(max(tx_bps, 0.0), 1),
        "rx_total_mb": round(current.bytes_recv / (1024 ** 2), 2),
        "tx_total_mb": round(current.bytes_sent / (1024 ** 2), 2),
    }
