"""WiFi monitor tests — no hardware required."""
import math
import time
from unittest.mock import MagicMock, call, patch

import pytest

import porcupine.monitors.wifi as wifi


@pytest.fixture(autouse=True)
def reset_ssid_cache():
    """Reset module-level SSID cache between tests."""
    wifi._ssid_cache = None
    wifi._ssid_cache_iface = None
    wifi._ssid_cache_time = 0.0
    yield
    wifi._ssid_cache = None
    wifi._ssid_cache_iface = None
    wifi._ssid_cache_time = 0.0


# ---------------------------------------------------------------------------
# read() — high-level contract
# ---------------------------------------------------------------------------

def test_read_returns_required_keys():
    with patch.object(wifi, "_find_wifi_iface", return_value=None):
        data = wifi.read()
    for key in ("wifi_connected", "wifi_iface", "wifi_ip", "wifi_ssid", "wifi_signal_dbm"):
        assert key in data


def test_read_no_wifi_hardware():
    with patch.object(wifi, "_find_wifi_iface", return_value=None):
        data = wifi.read()
    assert data["wifi_connected"] is False
    assert data["wifi_iface"]     is None
    assert data["wifi_ip"]        is None


def test_read_disconnected_iface():
    with patch.object(wifi, "_find_wifi_iface", return_value="wlan0"), \
         patch.object(wifi, "_read_ip",         return_value=None), \
         patch.object(wifi, "_read_ssid",        return_value=None), \
         patch.object(wifi, "_read_signal_dbm",  return_value=float("nan")):
        data = wifi.read()
    assert data["wifi_connected"] is False
    assert data["wifi_iface"]     == "wlan0"
    assert data["wifi_ip"]        is None


def test_read_connected():
    with patch.object(wifi, "_find_wifi_iface", return_value="wlan0"), \
         patch.object(wifi, "_read_ip",         return_value="192.168.1.42"), \
         patch.object(wifi, "_read_ssid",        return_value="MyNetwork"), \
         patch.object(wifi, "_read_signal_dbm",  return_value=-67.0):
        data = wifi.read()
    assert data["wifi_connected"]  is True
    assert data["wifi_iface"]      == "wlan0"
    assert data["wifi_ip"]         == "192.168.1.42"
    assert data["wifi_ssid"]       == "MyNetwork"
    assert data["wifi_signal_dbm"] == -67.0


def test_read_exception_returns_safe_defaults():
    with patch.object(wifi, "_find_wifi_iface", side_effect=RuntimeError("boom")):
        data = wifi.read()
    assert data["wifi_connected"] is False
    assert data["wifi_iface"]     is None
    assert math.isnan(data["wifi_signal_dbm"])


# ---------------------------------------------------------------------------
# _read_ssid — caching
# ---------------------------------------------------------------------------

def test_ssid_cache_avoids_repeated_calls():
    with patch.object(wifi, "_read_ssid_ioctl",      return_value="HomeNet") as mock_ioctl, \
         patch.object(wifi, "_read_ssid_subprocess",  return_value=None):
        first  = wifi._read_ssid("wlan0")
        second = wifi._read_ssid("wlan0")

    assert first == second == "HomeNet"
    mock_ioctl.assert_called_once_with("wlan0")  # second call served from cache


def test_ssid_cache_expires_after_ttl():
    call_count = 0

    def fake_ioctl(iface):
        nonlocal call_count
        call_count += 1
        return "HomeNet"

    with patch.object(wifi, "_read_ssid_ioctl",     side_effect=fake_ioctl), \
         patch.object(wifi, "_read_ssid_subprocess", return_value=None), \
         patch("porcupine.monitors.wifi.time") as mock_time:

        mock_time.monotonic.return_value = 0.0
        wifi._read_ssid("wlan0")

        mock_time.monotonic.return_value = wifi._SSID_TTL - 1
        wifi._read_ssid("wlan0")   # still within TTL — cache hit
        assert call_count == 1

        mock_time.monotonic.return_value = wifi._SSID_TTL + 1
        wifi._read_ssid("wlan0")   # TTL expired — cache miss
        assert call_count == 2


def test_ssid_cache_invalidated_on_iface_change():
    with patch.object(wifi, "_read_ssid_ioctl",      return_value="HomeNet") as mock_ioctl, \
         patch.object(wifi, "_read_ssid_subprocess",  return_value=None):
        wifi._read_ssid("wlan0")
        wifi._read_ssid("wlan1")  # different iface — must bypass cache

    assert mock_ioctl.call_count == 2


# ---------------------------------------------------------------------------
# _read_ssid — ioctl vs subprocess priority
# ---------------------------------------------------------------------------

def test_ioctl_is_tried_before_subprocess():
    with patch.object(wifi, "_read_ssid_ioctl",     return_value="ViaIoctl") as mock_ioctl, \
         patch.object(wifi, "_read_ssid_subprocess", return_value="ViaSubprocess") as mock_sub:
        result = wifi._read_ssid("wlan0")

    assert result == "ViaIoctl"
    mock_ioctl.assert_called_once()
    mock_sub.assert_not_called()


def test_subprocess_fallback_when_ioctl_fails():
    with patch.object(wifi, "_read_ssid_ioctl",     return_value=None), \
         patch.object(wifi, "_read_ssid_subprocess", return_value="ViaFallback") as mock_sub:
        result = wifi._read_ssid("wlan0")

    assert result == "ViaFallback"
    mock_sub.assert_called_once_with("wlan0")


# ---------------------------------------------------------------------------
# _read_ssid_ioctl — error handling
# ---------------------------------------------------------------------------

def test_read_ssid_ioctl_returns_none_on_oserror():
    with patch("porcupine.monitors.wifi.fcntl") as mock_fcntl:
        mock_fcntl.ioctl.side_effect = OSError("not supported")
        result = wifi._read_ssid_ioctl("wlan0")
    assert result is None


# ---------------------------------------------------------------------------
# _read_ssid_subprocess — error handling
# ---------------------------------------------------------------------------

def test_read_ssid_subprocess_returns_none_on_failure():
    with patch("porcupine.monitors.wifi.subprocess") as mock_sub:
        mock_sub.check_output.side_effect = FileNotFoundError("iwgetid not found")
        result = wifi._read_ssid_subprocess("wlan0")
    assert result is None


def test_read_ssid_subprocess_returns_none_on_empty_output():
    with patch("porcupine.monitors.wifi.subprocess") as mock_sub:
        mock_sub.check_output.return_value = "   \n"
        result = wifi._read_ssid_subprocess("wlan0")
    assert result is None
