"""Daemon wiring tests — no hardware required."""
import argparse
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import porcupine.daemon as daemon
from porcupine.interfaces.lcd import LCD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        boot_every=1, power_every=1, cpu_every=1, temp_every=1, net_every=1,
        gpio_every=1, disk_every=0, conn_every=0, wifi_every=0,
        lcd_addr=0x27, button_pin=4, buzzer_pin=18, ina219_addr=0x41,
        refresh=3.0,
        temp_warn=80.0, cpu_warn=90.0, mem_warn=90.0, bat_warn=40.0, disk_warn=85.0,
        conn_host="8.8.8.8", alert_log=None, only_alert=False,
        fan_enabled=False, fan_pin=19, fan_type="3pin", fan_freq=None, fan_min_duty=30,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _monitors(args: argparse.Namespace) -> list:
    """Shorthand for daemon._make_monitors(args)."""
    return daemon._make_monitors(args)


def _stub_lcd() -> LCD:
    return LCD(cols=16, rows=2)


def _stub_buzzer():
    return MagicMock()


def _stub_controller():
    return MagicMock()


# ---------------------------------------------------------------------------
# _bps_str
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bps,expected", [
    (0,                  "0B"),
    (512,                "512B"),
    (1023,               "1023B"),
    (1024,               "1.0K"),
    (1536,               "1.5K"),
    (100 * 1024,         "100K"),      # exactly 100 K — no decimal
    (1023 * 1024,        "1023K"),     # high K — no decimal
    (1024 * 1024 - 1,    "1024K"),     # rounding boundary (was "1024.0K" before fix)
    (1024 * 1024,        "1.0M"),
    (2.5 * 1024**2,      "2.5M"),
    (100 * 1024 * 1024,  "100M"),      # exactly 100 M — no decimal
])
def test_bps_str(bps, expected):
    assert daemon._bps_str(bps) == expected


# ---------------------------------------------------------------------------
# Monitor.format_screens — boot
# ---------------------------------------------------------------------------

def test_boot_monitor_formats_uptime():
    m = daemon._BootMonitor()
    line1, line2 = m.format_screens({"boot_count": 5, "uptime_s": 7320.0})[0]
    assert line1 == "Boot"
    assert "#5" in line2
    assert "2h02m" in line2


def test_boot_monitor_missing_keys():
    m = daemon._BootMonitor()
    line1, line2 = m.format_screens({})[0]
    assert line1 == "Boot"
    assert "#0" in line2


# ---------------------------------------------------------------------------
# Monitor.format_screens — power
# ---------------------------------------------------------------------------

def test_power_monitor_formats_battery():
    m = daemon._PowerMonitor(bat_warn=40.0)
    line1, line2 = m.format_screens({"power_source": "Battery", "battery_pct": 75.0})[0]
    assert line1 == "Power"
    assert "Battery" in line2
    assert "75%" in line2
    assert "WARN" not in line2


def test_power_monitor_formats_battery_warn():
    m = daemon._PowerMonitor(bat_warn=40.0)
    _, line2 = m.format_screens({"power_source": "Battery", "battery_pct": 25.0})[0]
    assert "25%" in line2
    assert "WARN" in line2


def test_power_monitor_plugged_in_no_warn():
    m = daemon._PowerMonitor(bat_warn=40.0)
    line1, line2 = m.format_screens({"power_source": "Plugged In", "battery_pct": 20.0})[0]
    assert line1 == "Power"
    assert "Plugged In" in line2
    assert "WARN" not in line2


def test_power_monitor_unknown_no_pct():
    m = daemon._PowerMonitor()
    line1, line2 = m.format_screens({"power_source": "Unknown", "battery_pct": float("nan")})[0]
    assert line1 == "Power"
    assert line2 == "Unknown"


# ---------------------------------------------------------------------------
# Monitor.format_screens — cpu/mem
# ---------------------------------------------------------------------------

def test_cpu_monitor_formats_percentages():
    m = daemon._CpuMemMonitor(cpu_warn=90.0, mem_warn=90.0)
    line1, line2 = m.format_screens({"cpu_avg_pct": 23.7, "mem_pct": 45.1})[0]
    assert line1 == " CPU   Mem"
    assert "24%" in line2
    assert "45%" in line2


def test_cpu_monitor_warn_cpu():
    m = daemon._CpuMemMonitor(cpu_warn=90.0, mem_warn=90.0)
    _, line2 = m.format_screens({"cpu_avg_pct": 95.0, "mem_pct": 45.0})[0]
    assert "WARN" in line2
    assert "45%" in line2


def test_cpu_monitor_warn_mem():
    m = daemon._CpuMemMonitor(cpu_warn=90.0, mem_warn=90.0)
    _, line2 = m.format_screens({"cpu_avg_pct": 20.0, "mem_pct": 92.0})[0]
    assert "20%" in line2
    assert line2.endswith("WARN")


def test_cpu_monitor_alignment_stable_across_widths():
    m = daemon._CpuMemMonitor(cpu_warn=101.0, mem_warn=101.0)
    _, line2_low  = m.format_screens({"cpu_avg_pct": 1.0,   "mem_pct": 1.0})[0]
    _, line2_high = m.format_screens({"cpu_avg_pct": 100.0, "mem_pct": 100.0})[0]
    assert line2_low.index("%")  == line2_high.index("%")
    assert line2_low.rindex("%") == line2_high.rindex("%")


# ---------------------------------------------------------------------------
# Monitor.format_screens — temperature
# ---------------------------------------------------------------------------

def test_temp_monitor_formats_ok():
    m = daemon._TempMonitor(temp_warn=80.0)
    _, line2 = m.format_screens({"cpu_temp_c": 52.3})[0]
    assert "52.3C" in line2
    assert "WARN" not in line2


def test_temp_monitor_formats_warn():
    m = daemon._TempMonitor(temp_warn=80.0)
    _, line2 = m.format_screens({"cpu_temp_c": 85.0})[0]
    assert "85.0C" in line2
    assert "WARN" in line2


def test_temp_monitor_formats_unavailable():
    m = daemon._TempMonitor()
    _, line2 = m.format_screens({"cpu_temp_c": float("nan")})[0]
    assert "---" in line2


def test_temp_monitor_formats_missing_key():
    m = daemon._TempMonitor()
    _, line2 = m.format_screens({})[0]
    assert "---" in line2


# ---------------------------------------------------------------------------
# Monitor.format_screens — network
# ---------------------------------------------------------------------------

def test_net_monitor_formats_rates():
    m = daemon._NetMonitor()
    line1, line2 = m.format_screens({"interface": "eth0", "rx_bps": 2048.0, "tx_bps": 512.0})[0]
    assert "eth0" in line1
    assert "2.0K" in line2
    assert "512B" in line2


def test_net_monitor_truncates_long_interface_name():
    m = daemon._NetMonitor()
    line1, _ = m.format_screens({"interface": "docker0", "rx_bps": 0, "tx_bps": 0})[0]
    assert "docke" in line1


# ---------------------------------------------------------------------------
# Monitor.format_screens — gpio
# ---------------------------------------------------------------------------

def test_gpio_monitor_each_page_returns_one_screen():
    data = {"gpio_pins": [None] * 40}
    assert len(daemon._GpioMonitor(page=1).format_screens(data)) == 1
    assert len(daemon._GpioMonitor(page=2).format_screens(data)) == 1


def test_gpio_monitor_page_labels_and_width():
    data = {"gpio_pins": [None] * 40}
    (r1_p1, r2_p1), = daemon._GpioMonitor(page=1).format_screens(data)
    (r1_p2, r2_p2), = daemon._GpioMonitor(page=2).format_screens(data)
    assert r1_p1.startswith("01[") and r1_p1.endswith("]19") and len(r1_p1) == 16
    assert r2_p1.startswith("02[") and r2_p1.endswith("]20") and len(r2_p1) == 16
    assert r1_p2.startswith("21[") and r1_p2.endswith("]39") and len(r1_p2) == 16
    assert r2_p2.startswith("22[") and r2_p2.endswith("]40") and len(r2_p2) == 16


def test_gpio_monitor_pin_count_per_row():
    data = {"gpio_pins": [None] * 40}
    (r1, _), = daemon._GpioMonitor(page=1).format_screens(data)
    # strip the 3-char brackets on each side to get just the 10 status chars
    assert len(r1[3:-3]) == 10


# ---------------------------------------------------------------------------
# _with_alert_indicator
# ---------------------------------------------------------------------------

def test_with_alert_indicator_inactive_returns_screens_unchanged():
    screens = [("Boot", "#1 0h00m"), (" CPU   Mem", "  5%  12%")]
    assert daemon._with_alert_indicator(screens, False) is screens


def test_with_alert_indicator_places_warning_triangle_at_column_15():
    screens = [("Boot", ""), (" CPU   Mem", "")]
    result = daemon._with_alert_indicator(screens, True)
    for line1, _ in result:
        assert len(line1) == 16
        assert line1[15] == chr(5)


def test_with_alert_indicator_short_line1_padded():
    screens = [("Hi", "")]
    line1, _ = daemon._with_alert_indicator(screens, True)[0]
    assert line1 == f"Hi             {chr(5)}"


def test_with_alert_indicator_full_16_char_line1_last_char_replaced():
    screens = [("0123456789ABCDEF", "")]
    line1, _ = daemon._with_alert_indicator(screens, True)[0]
    assert line1 == f"0123456789ABCDE{chr(5)}"
    assert len(line1) == 16


def test_with_alert_indicator_line2_never_modified():
    screens = [("Boot", "content")]
    _, line2 = daemon._with_alert_indicator(screens, True)[0]
    assert line2 == "content"


# ---------------------------------------------------------------------------
# _make_monitors
# ---------------------------------------------------------------------------

def test_make_monitors_returns_only_enabled():
    args = _args(boot_every=1, power_every=0, cpu_every=1, temp_every=0,
                 net_every=0, gpio_every=0)
    monitors = daemon._make_monitors(args)
    flags = [m.flag for m in monitors]
    assert flags == ["boot", "cpu"]


def test_make_monitors_empty_when_all_disabled():
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=0)
    assert daemon._make_monitors(args) == []


def test_make_monitors_every_set_from_args():
    args = _args(boot_every=5, cpu_every=2, power_every=0, temp_every=0,
                 net_every=0, gpio_every=0)
    monitors = daemon._make_monitors(args)
    by_flag = {m.flag: m for m in monitors}
    assert by_flag["boot"].every == 5
    assert by_flag["cpu"].every  == 2


def test_make_monitors_thresholds_set_from_args():
    args = _args(temp_warn=70.0, cpu_warn=85.0, mem_warn=95.0, bat_warn=20.0,
                 disk_warn=75.0, disk_every=1)
    monitors = daemon._make_monitors(args)
    by_flag = {m.flag: m for m in monitors}
    assert by_flag["temp"]._temp_warn  == 70.0
    assert by_flag["cpu"]._cpu_warn    == 85.0
    assert by_flag["power"]._bat_warn  == 20.0
    assert by_flag["disk"]._disk_warn  == 75.0


# ---------------------------------------------------------------------------
# Monitor.has_breach and beep_pattern
# ---------------------------------------------------------------------------

def test_temp_monitor_has_breach():
    m = daemon._TempMonitor(temp_warn=80.0)
    assert m.has_breach({"cpu_temp_c": 85.0}) is True
    assert m.has_breach({"cpu_temp_c": 79.9}) is False
    assert m.has_breach({"cpu_temp_c": float("nan")}) is False
    assert m.has_breach({}) is False


def test_temp_monitor_has_breach_throttled():
    m = daemon._TempMonitor(temp_warn=80.0)
    # Throttled alone triggers breach even when temp is fine
    assert m.has_breach({"cpu_temp_c": 52.0, "throttled": True}) is True
    # Not throttled — no breach below threshold
    assert m.has_breach({"cpu_temp_c": 52.0, "throttled": False}) is False
    # throttled=None (vcgencmd unavailable) does not trigger breach
    assert m.has_breach({"cpu_temp_c": 52.0, "throttled": None}) is False


def test_temp_monitor_formats_throttled_only():
    m = daemon._TempMonitor(temp_warn=80.0)
    _, line2 = m.format_screens({"cpu_temp_c": 52.3, "throttled": True})[0]
    assert "52.3C" in line2
    assert "THRT" in line2
    assert "WARN" not in line2


def test_temp_monitor_formats_warn_and_throttled():
    m = daemon._TempMonitor(temp_warn=80.0)
    _, line2 = m.format_screens({"cpu_temp_c": 85.0, "throttled": True})[0]
    assert "WARN" in line2
    assert "THRT" in line2


def test_temp_monitor_formats_unavailable_throttled():
    m = daemon._TempMonitor()
    _, line2 = m.format_screens({"cpu_temp_c": float("nan"), "throttled": True})[0]
    assert "---" in line2
    assert "THRT" in line2


def test_cpu_mem_monitor_has_breach_cpu():
    m = daemon._CpuMemMonitor(cpu_warn=90.0, mem_warn=90.0)
    assert m.has_breach({"cpu_avg_pct": 91.0, "mem_pct": 50.0}) is True


def test_cpu_mem_monitor_has_breach_mem():
    m = daemon._CpuMemMonitor(cpu_warn=90.0, mem_warn=90.0)
    assert m.has_breach({"cpu_avg_pct": 20.0, "mem_pct": 92.0}) is True


def test_cpu_mem_monitor_single_beep_pattern():
    m = daemon._CpuMemMonitor(cpu_warn=90.0, mem_warn=90.0)
    pattern = m.beep_pattern()
    assert pattern is not None
    assert isinstance(pattern["count"], int)


def test_power_monitor_has_breach():
    m = daemon._PowerMonitor(bat_warn=40.0)
    assert m.has_breach({"power_source": "Battery", "battery_pct": 30.0}) is True
    assert m.has_breach({"power_source": "Battery", "battery_pct": 50.0}) is False
    assert m.has_breach({"power_source": "Plugged In", "battery_pct": 10.0}) is False


def test_disk_monitor_formats_ok():
    m = daemon._DiskMonitor(disk_warn=85.0)
    _, line2 = m.format_screens({"disk_pct": 42.0, "disk_used_gb": 13.4, "disk_total_gb": 32.0})[0]
    assert "42%" in line2
    assert "13.4/32.0GB" in line2
    assert "WARN" not in line2


def test_disk_monitor_formats_warn():
    m = daemon._DiskMonitor(disk_warn=85.0)
    _, line2 = m.format_screens({"disk_pct": 90.0, "disk_used_gb": 28.8, "disk_total_gb": 32.0})[0]
    assert "WARN" in line2
    assert "28.8/32.0GB" in line2


def test_disk_monitor_formats_large_disk():
    m = daemon._DiskMonitor(disk_warn=85.0)
    _, line2 = m.format_screens({"disk_pct": 42.0, "disk_used_gb": 430.0, "disk_total_gb": 1024.0})[0]
    assert "42%" in line2
    assert "430/1024GB" in line2


def test_disk_monitor_formats_unavailable():
    m = daemon._DiskMonitor()
    _, line2 = m.format_screens({"disk_pct": float("nan")})[0]
    assert "---" in line2


def test_disk_monitor_has_breach():
    m = daemon._DiskMonitor(disk_warn=85.0)
    assert m.has_breach({"disk_pct": 90.0}) is True
    assert m.has_breach({"disk_pct": 84.9}) is False
    assert m.has_breach({"disk_pct": float("nan")}) is False
    assert m.has_breach({}) is False


def test_disk_monitor_fits_16_chars():
    m = daemon._DiskMonitor(disk_warn=85.0)
    cases = [
        {"disk_pct": 42.0,  "disk_used_gb": 13.4,  "disk_total_gb": 32.0},
        {"disk_pct": 90.0,  "disk_used_gb": 28.8,  "disk_total_gb": 32.0},
        {"disk_pct": 42.0,  "disk_used_gb": 430.0, "disk_total_gb": 1024.0},
        {"disk_pct": 100.0, "disk_used_gb": 999.9, "disk_total_gb": 1000.0},
    ]
    for data in cases:
        _, line2 = m.format_screens(data)[0]
        assert len(line2) <= 16, f"{line2!r} is {len(line2)} chars"


def test_alert_log_written_on_breach(tmp_path):
    log_path = str(tmp_path / "alerts.log")
    args = _args(temp_every=1, disk_every=0, alert_log=log_path)
    monitors = _monitors(args)
    notifier = daemon._Notifier(
        _stub_lcd(), _stub_buzzer(), _stub_controller(),
        only_alert=False, alert_log=log_path,
    )
    notifier.start(monitors, {"cpu_temp_c": 85.0}, {"temp"}, refresh_s=3.0)
    log = (tmp_path / "alerts.log").read_text()
    assert "BREACH" in log
    assert "temp" in log


def test_alert_log_written_on_clear(tmp_path):
    log_path = str(tmp_path / "alerts.log")
    args = _args(temp_every=1, disk_every=0, alert_log=log_path)
    monitors = _monitors(args)
    notifier = daemon._Notifier(
        _stub_lcd(), _stub_buzzer(), _stub_controller(),
        only_alert=False, alert_log=log_path,
    )
    # Breach then clear
    notifier.start(monitors, {"cpu_temp_c": 85.0}, {"temp"}, refresh_s=3.0)
    notifier.update(monitors, {"cpu_temp_c": 50.0}, set(), d_cycle=0)
    log = (tmp_path / "alerts.log").read_text()
    assert "BREACH" in log
    assert "CLEAR" in log


def test_alert_log_none_does_not_raise():
    args = _args(temp_every=1, disk_every=0, alert_log=None)
    monitors = _monitors(args)
    notifier = daemon._Notifier(
        _stub_lcd(), _stub_buzzer(), _stub_controller(),
        only_alert=False, alert_log=None,
    )
    # Should not raise even with no log path
    notifier.start(monitors, {"cpu_temp_c": 85.0}, {"temp"}, refresh_s=3.0)


# ---------------------------------------------------------------------------
# _ConnectivityMonitor
# ---------------------------------------------------------------------------

def test_conn_monitor_formats_reachable():
    m = daemon._ConnectivityMonitor()
    _, line2 = m.format_screens({"reachable": True, "latency_ms": 12.3})[0]
    assert "OK" in line2
    assert "12.3ms" in line2


def test_conn_monitor_formats_unreachable():
    m = daemon._ConnectivityMonitor()
    _, line2 = m.format_screens({"reachable": False, "latency_ms": float("nan")})[0]
    assert "UNREACHABLE" in line2


def test_conn_monitor_formats_unknown():
    m = daemon._ConnectivityMonitor()
    _, line2 = m.format_screens({})[0]
    assert "---" in line2


def test_conn_monitor_has_breach():
    m = daemon._ConnectivityMonitor()
    assert m.has_breach({"reachable": False}) is True
    assert m.has_breach({"reachable": True})  is False
    assert m.has_breach({})                   is False


def test_conn_monitor_uses_custom_host():
    from unittest.mock import patch
    m = daemon._ConnectivityMonitor(host="192.168.1.1")
    with patch("porcupine.daemon.connectivity.read", return_value={"reachable": True,
                                                                    "conn_host": "192.168.1.1",
                                                                    "latency_ms": 1.0}) as mock_read:
        m.read()
    mock_read.assert_called_once_with(host="192.168.1.1")


# ---------------------------------------------------------------------------
# _WifiMonitor
# ---------------------------------------------------------------------------

def test_wifi_monitor_formats_connected():
    m = daemon._WifiMonitor()
    screens = m.format_screens({
        "wifi_connected": True, "wifi_iface": "wlan0",
        "wifi_ip": "192.168.1.42", "wifi_signal_dbm": -67.0,
    })
    assert len(screens) == 1
    header, line2 = screens[0]
    assert "-67dBm" in header
    assert line2 == "192.168.1.42"


def test_wifi_monitor_formats_disconnected():
    m = daemon._WifiMonitor()
    screens = m.format_screens({
        "wifi_connected": False, "wifi_iface": "wlan0",
        "wifi_ip": None, "wifi_signal_dbm": float("nan"),
    })
    assert len(screens) == 1
    assert "Disconnected" in screens[0][1]


def test_wifi_monitor_formats_no_hardware():
    m = daemon._WifiMonitor()
    screens = m.format_screens({
        "wifi_connected": False, "wifi_iface": None,
        "wifi_ip": None, "wifi_signal_dbm": float("nan"),
    })
    assert len(screens) == 1


def test_wifi_monitor_formats_no_signal():
    m = daemon._WifiMonitor()
    header, line2 = m.format_screens({
        "wifi_connected": True, "wifi_iface": "wlan0",
        "wifi_ip": "10.0.0.5", "wifi_signal_dbm": float("nan"),
    })[0]
    assert header == "WiFi"
    assert "dBm" not in header
    assert line2 == "10.0.0.5"


def test_wifi_monitor_has_breach_when_iface_present():
    m = daemon._WifiMonitor()
    assert m.has_breach({"wifi_connected": False, "wifi_iface": "wlan0"}) is True
    assert m.has_breach({"wifi_connected": True,  "wifi_iface": "wlan0"}) is False


def test_wifi_monitor_no_breach_without_hardware():
    m = daemon._WifiMonitor()
    assert m.has_breach({"wifi_connected": False, "wifi_iface": None}) is False
    assert m.has_breach({}) is False


def test_wifi_monitor_header_fits_16_chars():
    m = daemon._WifiMonitor()
    cases = [
        {"wifi_connected": True,  "wifi_iface": "wlan0", "wifi_ip": "192.168.1.42",   "wifi_signal_dbm": -67.0},
        {"wifi_connected": True,  "wifi_iface": "wlan0", "wifi_ip": "10.0.0.1",        "wifi_signal_dbm": -100.0},
        {"wifi_connected": True,  "wifi_iface": "wlan0", "wifi_ip": "192.168.100.200", "wifi_signal_dbm": float("nan")},
        {"wifi_connected": False, "wifi_iface": "wlan0", "wifi_ip": None,              "wifi_signal_dbm": float("nan")},
    ]
    for data in cases:
        header, line2 = m.format_screens(data)[0]
        assert len(header) <= 16, f"header {header!r} is {len(header)} chars"
        assert len(line2)  <= 16, f"line2 {line2!r} is {len(line2)} chars"


def test_non_alertable_monitors_have_no_beep():
    non_alertable = [daemon._BootMonitor(), daemon._NetMonitor(),
                     daemon._GpioMonitor(page=1), daemon._GpioMonitor(page=2)]
    for m in non_alertable:
        assert m.beep_pattern() is None
        assert m.has_breach({}) is False


def test_alertable_monitors_have_beep_pattern():
    alertable = [
        daemon._TempMonitor(),
        daemon._CpuMemMonitor(),
        daemon._PowerMonitor(),
        daemon._DiskMonitor(),
        daemon._WifiMonitor(),
        daemon._ConnectivityMonitor(),
    ]
    for m in alertable:
        pattern = m.beep_pattern()
        assert pattern is not None, f"{type(m).__name__} must return a beep pattern"
        assert isinstance(pattern["count"],       int)
        assert isinstance(pattern["duration_ms"], int)
        assert isinstance(pattern["gap_ms"],      int)


# ---------------------------------------------------------------------------
# _read_all
# ---------------------------------------------------------------------------

def test_read_all_calls_only_enabled_monitors():
    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    monitors = _monitors(args)
    with patch("porcupine.daemon.boot.read", return_value={"boot_count": 3, "uptime_s": 100.0}), \
         patch("porcupine.daemon.cpu_mem.read") as mock_cpu:
        data = daemon._read_all(monitors)

    mock_cpu.assert_not_called()
    assert "boot_count" in data
    assert "cpu_avg_pct" not in data


def test_read_all_merges_multiple_monitors():
    args = _args(boot_every=1, power_every=0, cpu_every=1, temp_every=0, net_every=0, gpio_every=0)
    monitors = _monitors(args)
    with patch("porcupine.daemon.boot.read", return_value={"boot_count": 1, "uptime_s": 60.0}), \
         patch("porcupine.daemon.cpu_mem.read", return_value={"cpu_avg_pct": 30.0, "mem_pct": 50.0,
                                                              "cpu_pct": [], "mem_used_mb": 512,
                                                              "mem_total_mb": 1024}):
        data = daemon._read_all(monitors)

    assert "boot_count" in data
    assert "cpu_avg_pct" in data


def test_read_all_skips_failing_monitor():
    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    monitors = _monitors(args)
    with patch("porcupine.daemon.boot.read", side_effect=RuntimeError("hw error")):
        data = daemon._read_all(monitors)
    assert data == {}


def test_read_all_no_monitors_returns_empty():
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    monitors = _monitors(args)
    with patch("porcupine.daemon.boot.read") as m:
        data = daemon._read_all(monitors)
    m.assert_not_called()
    assert data == {}


# ---------------------------------------------------------------------------
# _build_screens
# ---------------------------------------------------------------------------

def test_build_screens_one_per_enabled_monitor():
    args = _args(boot_every=1, power_every=0, cpu_every=1, temp_every=0, net_every=0, gpio_every=0)
    monitors = _monitors(args)
    data = {"boot_count": 1, "uptime_s": 60, "cpu_avg_pct": 10, "mem_pct": 20,
            "cpu_pct": [], "mem_used_mb": 100, "mem_total_mb": 500}
    screens = daemon._build_screens(monitors, data)
    assert len(screens) == 2


def test_build_screens_respects_order():
    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0, net_every=1, gpio_every=0)
    monitors = _monitors(args)
    data = {"boot_count": 1, "uptime_s": 0,
            "interface": "eth0", "rx_bps": 0, "tx_bps": 0,
            "rx_total_mb": 0, "tx_total_mb": 0}
    screens = daemon._build_screens(monitors, data)
    assert screens[0][0] == "Boot"
    assert "Net" in screens[1][0]


def test_build_screens_gpio_contributes_two_screens():
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=1)
    monitors = _monitors(args)
    screens = daemon._build_screens(monitors, {"gpio_pins": [None] * 40})
    assert len(screens) == 2


def test_build_screens_fallback_when_none_enabled():
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    monitors = _monitors(args)
    screens = daemon._build_screens(monitors, {})
    assert screens == [("No monitors", "enabled")]


# ---------------------------------------------------------------------------
# _build_screens — d_cycle filtering
# ---------------------------------------------------------------------------

def test_d_cycle_zero_shows_all_enabled():
    """d_cycle=0: every enabled monitor appears (0 % N == 0 for all N)."""
    args = _args(boot_every=10, power_every=0, cpu_every=5, temp_every=1,
                 net_every=10, gpio_every=0)
    monitors = _monitors(args)
    data = {"boot_count": 1, "uptime_s": 0,
            "cpu_avg_pct": 10, "mem_pct": 20, "cpu_pct": [], "mem_used_mb": 100, "mem_total_mb": 500}
    screens = daemon._build_screens(monitors, data, d_cycle=0)
    labels = [s[0] for s in screens]
    assert "Boot" in labels
    assert " CPU   Mem" in labels
    assert "Temperature" in labels


def test_d_cycle_filters_by_every():
    """Monitors with every=N only appear when d_cycle % N == 0."""
    args = _args(boot_every=10, power_every=0, cpu_every=5, temp_every=1,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    data = {"boot_count": 1, "uptime_s": 0,
            "cpu_avg_pct": 10, "mem_pct": 20, "cpu_pct": [], "mem_used_mb": 100, "mem_total_mb": 500}

    # d_cycle=1: only temp (1%1==0); boot (1%10!=0) and cpu (1%5!=0) hidden
    screens = daemon._build_screens(monitors, data, d_cycle=1)
    labels = [s[0] for s in screens]
    assert labels == ["Temperature"]

    # d_cycle=5: cpu and temp appear; boot still hidden (5%10!=0)
    screens = daemon._build_screens(monitors, data, d_cycle=5)
    labels = [s[0] for s in screens]
    assert " CPU   Mem" in labels
    assert "Temperature" in labels
    assert "Boot" not in labels

    # d_cycle=10: all three appear (10%10==0, 10%5==0, 10%1==0)
    screens = daemon._build_screens(monitors, data, d_cycle=10)
    labels = [s[0] for s in screens]
    assert "Boot" in labels
    assert " CPU   Mem" in labels
    assert "Temperature" in labels


def test_d_cycle_fallback_when_no_monitors_due():
    """If no monitors are due at a given d_cycle, show the fallback screen."""
    args = _args(boot_every=10, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    screens = daemon._build_screens(monitors, {"boot_count": 1, "uptime_s": 0}, d_cycle=1)
    assert screens == [("No monitors", "enabled")]


def test_breached_monitor_appears_every_cycle():
    """A breached monitor is included in the screen list even when its d_cycle is not due."""
    args = _args(boot_every=0, power_every=0, cpu_every=10, temp_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    data = {"cpu_avg_pct": 95.0, "mem_pct": 50.0}
    # d_cycle=1: cpu_every=10, 1%10≠0 → normally excluded
    screens, tags = daemon._build_screens_tagged(monitors, data, d_cycle=1, breached={"cpu"})
    assert "cpu" in tags, "breached cpu monitor must appear even when not due by d_cycle"


# ---------------------------------------------------------------------------
# _Notifier — beep behaviour
# ---------------------------------------------------------------------------

def _make_notifier():
    lcd        = MagicMock()
    buzzer     = MagicMock()
    beep_calls = []
    buzzer.beep_async.side_effect = lambda **kwargs: beep_calls.append(kwargs)
    controller = MagicMock()
    controller._lcd_on = True

    notifier = daemon._Notifier(lcd, buzzer, controller, only_alert=False)
    return notifier, lcd, controller, beep_calls


def test_notifier_beeps_on_first_breach():
    notifier, lcd, controller, beep_calls = _make_notifier()
    args = _args(temp_every=1, boot_every=0, power_every=0, cpu_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    data = {"cpu_temp_c": 85.0}   # above 80 °C default

    notifier.update(monitors, data, {"temp"}, d_cycle=0)
    assert any(c["count"] == 3 for c in beep_calls)   # temp = 3 beeps


def test_notifier_no_beep_on_repeated_breach():
    notifier, lcd, controller, beep_calls = _make_notifier()
    args = _args(temp_every=1, boot_every=0, power_every=0, cpu_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    data = {"cpu_temp_c": 85.0}

    notifier.update(monitors, data, {"temp"}, d_cycle=0)
    first_count = len(beep_calls)
    notifier.update(monitors, data, {"temp"}, d_cycle=0)  # still breached — no new beep
    assert len(beep_calls) == first_count


def test_notifier_on_screen_advance_beeps_for_breached_screen():
    notifier, lcd, controller, beep_calls = _make_notifier()
    args = _args(temp_every=1, boot_every=1, power_every=0, cpu_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    data = {"cpu_temp_c": 85.0, "boot_count": 1, "uptime_s": 0}

    # Seed notifier state: temp breached, tags = [boot, temp]
    notifier.update(monitors, data, {"temp"}, d_cycle=0)
    beep_calls.clear()

    # on_screen_advance fired for screen index 0 (boot) — no beep
    notifier.on_screen_advance(0)
    assert len(beep_calls) == 0

    # on_screen_advance fired for screen index 1 (temp) — should beep
    notifier.on_screen_advance(1)
    assert len(beep_calls) == 1
    assert beep_calls[0]["count"] == 3


# ---------------------------------------------------------------------------
# run() — smoke test
# ---------------------------------------------------------------------------

def test_run_starts_and_stops_cleanly(tmp_path):
    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)

    iteration = {"count": 0}

    def fake_sleep(_):
        iteration["count"] += 1
        if iteration["count"] >= 2:
            raise KeyboardInterrupt

    boot_data = {"boot_count": 1, "uptime_s": 60.0}

    with patch("porcupine.daemon.boot.init"), \
         patch("porcupine.daemon.power.init"), \
         patch("porcupine.daemon.boot.read", return_value=boot_data), \
         patch("porcupine.daemon.time.sleep", side_effect=fake_sleep), \
         patch("porcupine.daemon._wifi_startup"), \
         patch("porcupine.daemon.Button") as MockButton, \
         patch("porcupine.daemon.Buzzer"):

        MockButton.return_value.start = MagicMock()
        MockButton.return_value.stop = MagicMock()
        MockButton.return_value._stub = MagicMock()
        MockButton.return_value._stub.on_edge = MagicMock()
        MockButton.return_value._read = lambda: 1

        daemon.run(args)

    assert iteration["count"] == 2


# ---------------------------------------------------------------------------
# Regression: GPIO page 2 skipped when every=2
# ---------------------------------------------------------------------------

def test_gpio_two_instances_each_one_screen():
    """Each _GpioMonitor page returns exactly one screen — no multi-screen monitor."""
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=1)
    monitors = _monitors(args)
    gpio_monitors = [m for m in monitors if m.flag == "gpio"]
    assert len(gpio_monitors) == 2, "must have two GPIO monitor instances"
    data = {"gpio_pins": [None] * 40}
    for m in gpio_monitors:
        screens = m.format_screens(data)
        assert len(screens) == 1, "each GPIO page must produce exactly one screen"


def test_gpio_pages_cover_distinct_pin_ranges():
    """Page 1 mentions pin 01/20; page 2 mentions pin 21/40."""
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=1)
    monitors = _monitors(args)
    gpio_monitors = [m for m in monitors if m.flag == "gpio"]
    data = {"gpio_pins": [None] * 40}
    texts = ["".join(gpio_monitors[i].format_screens(data)[0]) for i in range(2)]
    assert "01" in texts[0] and "20" in texts[0]
    assert "21" in texts[1] and "40" in texts[1]


def test_gpio_both_pages_appear_in_screen_list_when_due():
    """With gpio_every=2 at d_cycle=0 (even), both GPIO pages are in the screen list."""
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=2)
    monitors = _monitors(args)
    data = {"gpio_pins": [None] * 40}
    screens, tags = daemon._build_screens_tagged(monitors, data, d_cycle=0)
    gpio_screens = [s for s, t in zip(screens, tags) if t == "gpio"]
    assert len(gpio_screens) == 2, "both GPIO pages must appear when gpio_every cycle is due"


def test_gpio_pages_absent_when_not_due():
    """With gpio_every=2 at d_cycle=1 (odd), no GPIO screens appear."""
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=2)
    monitors = _monitors(args)
    data = {"gpio_pins": [None] * 40}
    screens, tags = daemon._build_screens_tagged(monitors, data, d_cycle=1)
    assert "gpio" not in tags


def test_update_screens_reset_position_on_wrap():
    """
    When the LCD thread fires an extra tick between setting _lcd_wrapped and
    the main loop consuming it, _index can advance to 1 (GPIO-1) before the
    main loop replaces the screen list.  Without reset_position the shorter
    new list clamps _index and GPIO-2 is skipped forever.
    """
    lcd = LCD(cols=16, rows=2)
    lcd._screens = [("Temp", ""), ("GPIO-1", ""), ("GPIO-2", "")]
    lcd._index = 1  # simulates LCD thread firing one extra tick after the wrap

    lcd.update_screens([("Temp", "")], reset_position=True)

    assert lcd._index == 0


def test_notifier_update_passes_reset_position_on_wrap():
    """_Notifier.update(wrapped=True) must call update_screens(reset_position=True)."""
    lcd = MagicMock()
    buzzer = MagicMock()
    controller = MagicMock()
    controller._lcd_on = True
    notifier = daemon._Notifier(lcd, buzzer, controller, only_alert=False)

    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=2)
    monitors = _monitors(args)
    data = {"boot_count": 1, "uptime_s": 60.0}

    notifier.update(monitors, data, set(), d_cycle=1, wrapped=True)

    _, kwargs = lcd.update_screens.call_args
    assert kwargs.get("reset_position") is True


def test_gpio_both_pages_appear_at_d_cycle_2():
    """With gpio_every=2, both GPIO pages must appear at d_cycle=2 (not only 0)."""
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=2)
    monitors = _monitors(args)
    data = {"gpio_pins": [None] * 40}
    for d in (0, 2, 4, 6):
        screens, tags = daemon._build_screens_tagged(monitors, data, d_cycle=d)
        gpio_screens = [s for s, t in zip(screens, tags) if t == "gpio"]
        assert len(gpio_screens) == 2, f"both GPIO pages must appear at d_cycle={d}"


def test_gpio_page2_appears_after_list_expansion_with_reset():
    """
    Simulate the d_cycle=1→2 transition: LCD had a short list, update_screens
    expands it with reset_position=True; GPIO page 2 must still be reached.
    """
    lcd = LCD(cols=16, rows=2)
    # d_cycle=1 state: only temp, LCD sitting at index 0
    lcd._screens = [("Temperature", "50.0C")]
    lcd._index = 0

    # d_cycle=2: expand to include both GPIO pages
    gpio_p2 = ("21[          ]39", "22[          ]40")
    lcd.update_screens(
        [("Temperature", "50.0C"), ("01[          ]19", "02[          ]20"), gpio_p2],
        reset_position=True,
    )

    assert lcd._index == 0
    # After reset, cycling from 0: next index is 1 (GPIO-1), then 2 (GPIO-2)
    rendered = []
    for _ in range(3):
        with lcd._lock:
            lcd._index = (lcd._index + 1) % len(lcd._screens)
            rendered.append(lcd._screens[lcd._index])

    assert gpio_p2 in rendered, "GPIO page 2 must be reachable after list expansion"


def test_gpio_page2_not_skipped_by_index_clamping():
    """
    Without reset_position, a high _index clamped into a newly-expanded list
    can land on GPIO-2 and skip GPIO-1 in one rotation.  With reset_position=True
    the index always starts at 0 so both pages are guaranteed to appear.
    """
    lcd = LCD(cols=16, rows=2)
    # Simulate LCD was at index 2 in an 8-screen list (d_cycle=1)
    lcd._screens = [("Boot", "")] * 8
    lcd._index = 2

    gpio_p1 = ("01[          ]19", "02[          ]20")
    gpio_p2 = ("21[          ]39", "22[          ]40")
    new_screens = [("Temperature", ""), gpio_p1, gpio_p2]

    # Without reset_position: min(2, 2) = 2 → starts at GPIO-2, skips GPIO-1
    lcd.update_screens(new_screens, reset_position=False)
    assert lcd._index == 2  # landed on GPIO-2

    # With reset_position: always starts at 0 → full rotation shows both pages
    lcd._index = 2
    lcd.update_screens(new_screens, reset_position=True)
    assert lcd._index == 0


def test_lcd_thread_renders_gpio_page2_in_full_rotation():
    """
    End-to-end: with a 3-screen list the LCD background thread must render
    index 2 (GPIO page 2) within two full rotations.
    """
    lcd = LCD(cols=16, rows=2)
    gpio_p2_line1 = "21[          ]39"
    screens = [
        ("Boot", ""),
        ("01[          ]19", "02[          ]20"),
        (gpio_p2_line1, "22[          ]40"),
    ]

    rendered_indices = []
    lcd.on_screen_advance(lambda idx: rendered_indices.append(idx))
    lcd.start(screens, refresh_s=0.01)
    time.sleep(0.12)   # 12 ticks ≥ 4 full rotations of 3 screens
    lcd.stop()

    assert 2 in rendered_indices, (
        f"LCD thread never reached index 2 (GPIO page 2). Indices rendered: {rendered_indices}"
    )


def test_stale_wrap_cleared_after_reset():
    """
    Reproduces the race where a single-screen d_cycle fires an extra wrap event
    between consume_wrap() and update_screens(), causing d_cycle to advance
    prematurely and skip GPIO page 2.

    After notifier.update(wrapped=True), any stale _lcd_wrapped must be cleared
    so the next consume_wrap() returns False until the LCD genuinely completes
    a full rotation of the new screen list.
    """
    from unittest.mock import MagicMock
    lcd_mock = MagicMock(spec=LCD)
    lcd_mock.frozen = False
    buzzer_mock = MagicMock()
    controller_mock = MagicMock()

    notifier = daemon._Notifier(lcd_mock, buzzer_mock, controller_mock, only_alert=False)
    notifier.on_screen_advance = notifier.on_screen_advance  # ensure method exists

    # Simulate the LCD firing an extra wrap event (index=0) during a
    # single-screen rotation — exactly what happens between consume_wrap()
    # and update_screens() in the main loop.
    notifier._lcd_wrapped.set()          # stale event from single-screen rotation

    args = _args(temp_every=1, gpio_every=2)
    monitors = _monitors(args)
    data = {"cpu_temp_c": 40.0, "gpio_pins": [None] * 40}

    # update(wrapped=True) should clear the stale event after calling update_screens
    notifier.update(monitors, data, set(), d_cycle=2, wrapped=True)

    # The stale wrap must have been discarded — not a real rotation-complete signal
    assert not notifier.consume_wrap(), (
        "Stale wrap event survived notifier.update(wrapped=True); "
        "this would cause d_cycle to advance prematurely and skip GPIO page 2"
    )


def test_both_gpio_pages_appear_across_d_cycle_transitions():
    """
    Full simulation: main-loop calling update_screens as d_cycle advances
    through 0→1→2.  GPIO page 2 must appear in the d_cycle=2 rotation even
    when the LCD fired extra ticks between the wrap and the update_screens call.
    """
    REFRESH = 0.01

    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=2, disk_every=0, conn_every=0, wifi_every=0)
    monitors = _monitors(args)
    data = {"boot_count": 1, "uptime_s": 0, "gpio_pins": [None] * 40}

    lcd = LCD(cols=16, rows=2)
    wrap_event = threading.Event()
    d_cycle = 0
    rendered = []
    render_lock = threading.Lock()

    def on_advance(idx):
        nonlocal d_cycle
        if idx == 0 and not lcd.frozen:
            wrap_event.set()
        with lcd._lock:
            if idx < len(lcd._screens):
                with render_lock:
                    rendered.append(lcd._screens[idx][0])

    lcd.on_screen_advance(on_advance)

    screens0, _ = daemon._build_screens_tagged(monitors, data, d_cycle=0)
    lcd.start(screens0, refresh_s=REFRESH)

    for _ in range(60):
        time.sleep(REFRESH)
        wrapped = False
        if wrap_event.is_set():
            wrap_event.clear()
            wrapped = True
            d_cycle += 1
        new_screens, _ = daemon._build_screens_tagged(monitors, data, d_cycle=d_cycle)
        lcd.update_screens(new_screens, reset_position=wrapped)

    lcd.stop()

    with render_lock:
        all_rendered = list(rendered)

    gpio_p1_seen = any("01[" in s for s in all_rendered)
    gpio_p2_seen = any("21[" in s for s in all_rendered)
    assert gpio_p1_seen, "GPIO page 1 never rendered across d_cycle transitions"
    assert gpio_p2_seen, (
        f"GPIO page 2 never rendered across d_cycle transitions.\n"
        f"Rendered: {all_rendered}"
    )


# ---------------------------------------------------------------------------
# _wifi_startup
# ---------------------------------------------------------------------------

def test_wifi_startup_shows_screen_and_exits_when_connected():
    lcd = MagicMock()
    connected_data = {
        "wifi_connected": True, "wifi_iface": "wlan0",
        "wifi_ip": "192.168.1.42", "wifi_ssid": None, "wifi_signal_dbm": -67.0,
    }
    with patch("porcupine.daemon.wifi.read", return_value=connected_data), \
         patch("porcupine.daemon.time.sleep") as mock_sleep:
        daemon._wifi_startup(lcd)

    assert lcd.show.call_count == 1
    header, line2 = lcd.show.call_args[0]
    assert "192.168.1.42" in line2
    mock_sleep.assert_called_once_with(20)


def test_wifi_startup_polls_until_connected():
    lcd = MagicMock()
    disconnected = {
        "wifi_connected": False, "wifi_iface": "wlan0",
        "wifi_ip": None, "wifi_ssid": None, "wifi_signal_dbm": float("nan"),
    }
    connected = {**disconnected, "wifi_connected": True, "wifi_ip": "10.0.0.5"}
    # monotonic: t_start=0, loop check now=10 (<t_max=60) → sleep(5), read connected
    with patch("porcupine.daemon.wifi.read", side_effect=[disconnected, connected]), \
         patch("porcupine.daemon.time.monotonic", side_effect=[0.0, 10.0]), \
         patch("porcupine.daemon.time.sleep"):
        daemon._wifi_startup(lcd)

    assert lcd.show.call_count == 2  # once disconnected, once connected


def test_wifi_startup_exits_after_max_wait_if_never_connected():
    lcd = MagicMock()
    disconnected = {
        "wifi_connected": False, "wifi_iface": "wlan0",
        "wifi_ip": None, "wifi_ssid": None, "wifi_signal_dbm": float("nan"),
    }
    # monotonic: t_start=0, iter1 now=30 (<60), iter2 now=65 (≥60) → exit startup
    with patch("porcupine.daemon.wifi.read", return_value=disconnected), \
         patch("porcupine.daemon.time.monotonic", side_effect=[0.0, 30.0, 65.0]), \
         patch("porcupine.daemon.time.sleep"):
        daemon._wifi_startup(lcd)

    assert lcd.show.call_count == 2  # shown twice before giving up


def test_wifi_startup_no_hw_shows_once_and_returns():
    lcd = MagicMock()
    no_hw = {
        "wifi_connected": False, "wifi_iface": None,
        "wifi_ip": None, "wifi_ssid": None, "wifi_signal_dbm": float("nan"),
    }
    with patch("porcupine.daemon.wifi.read", return_value=no_hw):
        daemon._wifi_startup(lcd)

    assert lcd.show.call_count == 1


# ---------------------------------------------------------------------------
# Fan controller helpers
# ---------------------------------------------------------------------------

def test_fan_running_no_pid_file(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", tmp_path / "fan.pid")
    assert daemon._fan_running() is False


def test_fan_running_stale_pid(tmp_path, monkeypatch):
    pid_file = tmp_path / "fan.pid"
    pid_file.write_text("99999999")  # PID that almost certainly does not exist
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", pid_file)
    assert daemon._fan_running() is False


def test_fan_running_own_pid(tmp_path, monkeypatch):
    import os
    pid_file = tmp_path / "fan.pid"
    pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", pid_file)
    assert daemon._fan_running() is True


def test_ensure_fan_spawns_when_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", tmp_path / "fan.pid")
    spawned = []
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    args = _args(fan_enabled=True, fan_pin=19, fan_type="3pin", fan_min_duty=30, temp_warn=80.0)
    daemon._ensure_fan(args)
    assert len(spawned) == 1
    cmd = spawned[0]
    assert "--fan-on" in cmd
    assert "80.0" in cmd   # uses temp_warn, not a separate fan_on
    assert "--fan-type" in cmd
    assert "3pin" in cmd


def test_ensure_fan_noop_when_already_running(tmp_path, monkeypatch):
    import os
    pid_file = tmp_path / "fan.pid"
    pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", pid_file)
    spawned = []
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    daemon._ensure_fan(_args(fan_enabled=True, temp_warn=80.0))
    assert spawned == []


def test_ensure_fan_4pin_passes_correct_type(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", tmp_path / "fan.pid")
    spawned = []
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    args = _args(fan_enabled=True, fan_pin=13, fan_type="4pin", fan_min_duty=20, temp_warn=80.0)
    daemon._ensure_fan(args)
    cmd = spawned[0]
    assert "4pin" in cmd
    assert "13" in cmd
    assert "20" in cmd


def test_ensure_fan_passes_freq_when_set(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", tmp_path / "fan.pid")
    spawned = []
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    args = _args(fan_enabled=True, fan_freq=10000, temp_warn=80.0)
    daemon._ensure_fan(args)
    cmd = spawned[0]
    assert "--fan-freq" in cmd
    assert "10000" in cmd


def test_ensure_fan_omits_freq_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "_FAN_PID_FILE", tmp_path / "fan.pid")
    spawned = []
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    daemon._ensure_fan(_args(fan_enabled=True, fan_freq=None, temp_warn=80.0))
    assert "--fan-freq" not in spawned[0]


# ---------------------------------------------------------------------------
# _Monitor.effective_every — escalation property
# ---------------------------------------------------------------------------

def test_monitor_effective_every_default():
    m = daemon._TempMonitor(temp_warn=80.0, every=5)
    assert m.effective_every == 5


def test_monitor_effective_every_when_escalated():
    m = daemon._TempMonitor(temp_warn=80.0, every=5)
    m._escalated = True
    assert m.effective_every == 1


# ---------------------------------------------------------------------------
# _apply_escalation — monitor-owned escalation state
# ---------------------------------------------------------------------------

def test_apply_escalation_escalates_breached_alertable():
    args = _args(temp_every=5, boot_every=0, power_every=0, cpu_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    temp_m = next(m for m in monitors if m.flag == "temp")
    assert temp_m.effective_every == 5
    daemon._apply_escalation(monitors, {"temp"})
    assert temp_m.effective_every == 1


def test_apply_escalation_restores_after_breach_clears():
    args = _args(temp_every=5, boot_every=0, power_every=0, cpu_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    temp_m = next(m for m in monitors if m.flag == "temp")
    daemon._apply_escalation(monitors, {"temp"})
    assert temp_m.effective_every == 1
    daemon._apply_escalation(monitors, set())
    assert temp_m.effective_every == 5


def test_apply_escalation_skips_non_alertable():
    args = _args(boot_every=5, power_every=0, cpu_every=0, temp_every=0,
                 net_every=0, gpio_every=0)
    monitors = _monitors(args)
    boot_m = next(m for m in monitors if m.flag == "boot")
    daemon._apply_escalation(monitors, {"boot"})
    assert boot_m.effective_every == 5  # non-alertable: never escalated


# ---------------------------------------------------------------------------
# _toggle_only_alert — module-level function
# ---------------------------------------------------------------------------

def test_toggle_only_alert_flips_flag_in_config(tmp_path):
    config_file = tmp_path / "porcupine.conf"
    config_file.write_text("[display]\nonly_alert = false\n")
    args = _args(config=str(config_file))
    lcd = MagicMock()
    with patch("porcupine.daemon.subprocess.run"), \
         patch("porcupine.daemon.time.sleep"):
        daemon._toggle_only_alert(args, lcd)
    import configparser as _cp
    cp = _cp.ConfigParser()
    cp.read(str(config_file))
    assert cp.getboolean("display", "only_alert") is True


def test_toggle_only_alert_toggles_back_to_false(tmp_path):
    config_file = tmp_path / "porcupine.conf"
    config_file.write_text("[display]\nonly_alert = true\n")
    args = _args(config=str(config_file))
    lcd = MagicMock()
    with patch("porcupine.daemon.subprocess.run"), \
         patch("porcupine.daemon.time.sleep"):
        daemon._toggle_only_alert(args, lcd)
    import configparser as _cp
    cp = _cp.ConfigParser()
    cp.read(str(config_file))
    assert cp.getboolean("display", "only_alert") is False
