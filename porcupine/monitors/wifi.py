"""WiFi connectivity, IP address, SSID, and signal strength."""
import ctypes
import fcntl
import logging
import socket
import struct
import subprocess
import time
from pathlib import Path

import psutil


# SSID changes rarely; cache it and refresh at most every 60 s.
_ssid_cache: str | None = None
_ssid_cache_iface: str | None = None
_ssid_cache_time: float = 0.0
_SSID_TTL = 60.0

# SIOCGIWESSID ioctl reads SSID in-process, avoiding a subprocess spawn.
# ifreq layout: 16-byte ifr_name + iw_point (void *ptr, __u16 len, __u16 flags).
# Pointer width differs on 32-bit vs 64-bit ARM; struct iwreq is always 32 bytes.
_SIOCGIWESSID = 0x8B1B
_PTR_FMT = "Q" if struct.calcsize("P") == 8 else "I"
_IFREQ_HDR_FMT = f"16s{_PTR_FMT}HH"
_IFREQ_PAD = max(0, 32 - struct.calcsize(_IFREQ_HDR_FMT))


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
    global _ssid_cache, _ssid_cache_iface, _ssid_cache_time
    now = time.monotonic()
    if iface == _ssid_cache_iface and (now - _ssid_cache_time) < _SSID_TTL:
        return _ssid_cache
    ssid = _read_ssid_ioctl(iface) or _read_ssid_subprocess(iface)
    _ssid_cache = ssid
    _ssid_cache_iface = iface
    _ssid_cache_time = now
    return ssid


def _read_ssid_ioctl(iface: str) -> str | None:
    """Read SSID via SIOCGIWESSID ioctl — no subprocess."""
    try:
        ssid_buf = ctypes.create_string_buffer(32)
        ifreq = struct.pack(
            _IFREQ_HDR_FMT,
            iface.encode()[:16].ljust(16, b"\x00"),
            ctypes.addressof(ssid_buf),
            32,
            0,
        ) + b"\x00" * _IFREQ_PAD
        buf = bytearray(ifreq)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            fcntl.ioctl(sock.fileno(), _SIOCGIWESSID, buf)
        return ssid_buf.value.decode("utf-8", errors="replace").strip() or None
    except Exception:
        return None


def _read_ssid_subprocess(iface: str) -> str | None:
    """Fallback: iwgetid subprocess (used when the ioctl is unavailable)."""
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
