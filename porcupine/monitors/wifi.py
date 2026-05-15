"""WiFi connectivity, IP address, SSID, and signal strength."""
import logging
import socket
import subprocess
from pathlib import Path

import psutil


def _find_wifi_iface() -> str | None:
    """Return a WiFi interface name, preferring up ones; None if no WiFi hardware."""
    try:
        candidates = sorted(
            p.name for p in Path("/sys/class/net").iterdir()
            if (p / "wireless").exists()
        )
        if not candidates:
            return None
        stats = psutil.net_if_stats()
        for name in candidates:
            if name in stats and stats[name].isup:
                return name
        return candidates[0]
    except Exception:
        return None


def _read_ip(iface: str) -> str | None:
    try:
        for addr in psutil.net_if_addrs().get(iface, []):
            if addr.family == socket.AF_INET:
                return addr.address
    except Exception:
        pass
    return None


def _read_ssid(iface: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["iwgetid", iface, "--raw"], text=True, timeout=2
        )
        ssid = out.strip()
        return ssid or None
    except Exception:
        return None


def _read_signal_dbm(iface: str) -> float:
    try:
        for line in Path("/proc/net/wireless").read_text().splitlines():
            if line.strip().startswith(iface + ":"):
                parts = line.split()
                return float(parts[3].rstrip("."))
    except Exception:
        pass
    return float("nan")


def read() -> dict:
    try:
        iface = _find_wifi_iface()
    except Exception:
        logging.warning("wifi monitor read failed", exc_info=True)
        return {"wifi_connected": False, "wifi_iface": None,
                "wifi_ip": None, "wifi_ssid": None, "wifi_signal_dbm": float("nan")}

    if iface is None:
        return {"wifi_connected": False, "wifi_iface": None,
                "wifi_ip": None, "wifi_ssid": None, "wifi_signal_dbm": float("nan")}

    ip     = _read_ip(iface)
    ssid   = _read_ssid(iface)
    signal = _read_signal_dbm(iface)
    return {
        "wifi_connected":  ip is not None,
        "wifi_iface":      iface,
        "wifi_ip":         ip,
        "wifi_ssid":       ssid,
        "wifi_signal_dbm": signal,
    }
