"""WiFi monitor tests — no hardware required."""
import math
from unittest.mock import patch

import porcupine.monitors.wifi as wifi


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
