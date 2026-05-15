"""Daemon wiring tests — no hardware required."""
import argparse
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
        gpio_every=1, disk_every=0,
        lcd_addr=0x27, button_pin=4, buzzer_pin=18, ina219_addr=0x41,
        refresh=3.0,
        temp_warn=80.0, cpu_warn=90.0, mem_warn=90.0, bat_warn=40.0, disk_warn=85.0,
        alert_log=None,
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

def test_gpio_monitor_returns_two_pages():
    data = {"gpio_pins": [None] * 40}
    pages = daemon._GpioMonitor().format_screens(data)
    assert len(pages) == 2


def test_gpio_monitor_page_labels_and_width():
    data = {"gpio_pins": [None] * 40}
    (r1_p1, r2_p1), (r1_p2, r2_p2) = daemon._GpioMonitor().format_screens(data)
    assert r1_p1.startswith("01[") and r1_p1.endswith("]19") and len(r1_p1) == 16
    assert r2_p1.startswith("02[") and r2_p1.endswith("]20") and len(r2_p1) == 16
    assert r1_p2.startswith("21[") and r1_p2.endswith("]39") and len(r1_p2) == 16
    assert r2_p2.startswith("22[") and r2_p2.endswith("]40") and len(r2_p2) == 16


def test_gpio_monitor_pin_count_per_row():
    data = {"gpio_pins": [None] * 40}
    (r1, _), _ = daemon._GpioMonitor().format_screens(data)
    # strip the 3-char brackets on each side to get just the 10 status chars
    assert len(r1[3:-3]) == 10


# ---------------------------------------------------------------------------
# _with_alert_indicator
# ---------------------------------------------------------------------------

def test_with_alert_indicator_inactive_returns_screens_unchanged():
    screens = [("Boot", "#1 0h00m"), (" CPU   Mem", "  5%  12%")]
    assert daemon._with_alert_indicator(screens, False) is screens


def test_with_alert_indicator_places_exclamation_at_column_15():
    screens = [("Boot", ""), (" CPU   Mem", "")]
    result = daemon._with_alert_indicator(screens, True)
    for line1, _ in result:
        assert len(line1) == 16
        assert line1[15] == "!"


def test_with_alert_indicator_short_line1_padded():
    screens = [("Hi", "")]
    line1, _ = daemon._with_alert_indicator(screens, True)[0]
    assert line1 == "Hi             !"


def test_with_alert_indicator_full_16_char_line1_last_char_replaced():
    screens = [("0123456789ABCDEF", "")]
    line1, _ = daemon._with_alert_indicator(screens, True)[0]
    assert line1 == "0123456789ABCDE!"
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


def test_non_alertable_monitors_have_no_beep():
    for cls in (daemon._BootMonitor, daemon._NetMonitor, daemon._GpioMonitor):
        m = cls()
        assert m.beep_pattern() is None
        assert m.has_breach({}) is False


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
         patch("porcupine.daemon.Button") as MockButton, \
         patch("porcupine.daemon.Buzzer"):

        MockButton.return_value.start = MagicMock()
        MockButton.return_value.stop = MagicMock()
        MockButton.return_value._stub = MagicMock()
        MockButton.return_value._stub.on_edge = MagicMock()
        MockButton.return_value._read = lambda: 1

        daemon.run(args)

    assert iteration["count"] == 2
