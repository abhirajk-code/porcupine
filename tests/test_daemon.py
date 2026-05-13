"""Daemon wiring tests — no hardware required."""
import argparse
import math
from unittest.mock import MagicMock, patch

import pytest

import porcupine.daemon as daemon
from porcupine.interfaces.lcd import LCD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        boot_every=1, power_every=1, cpu_every=1, temp_every=1, net_every=1, gpio_every=1,
        lcd_addr=0x27, button_pin=4, buzzer_pin=18, ina219_addr=0x41,
        refresh=3.0,
        temp_warn=80.0, cpu_warn=90.0, mem_warn=90.0,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _stub_lcd() -> LCD:
    return LCD(cols=16, rows=2)


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
# _fmt_boot
# ---------------------------------------------------------------------------

def test_fmt_boot_formats_uptime():
    data = {"boot_count": 5, "uptime_s": 7320.0}   # 2h 2m
    line1, line2 = daemon._fmt_boot(data)
    assert line1 == "Boot"
    assert "#5" in line2
    assert "2h02m" in line2


def test_fmt_boot_missing_keys():
    line1, line2 = daemon._fmt_boot({})
    assert line1 == "Boot"
    assert "#0" in line2


# ---------------------------------------------------------------------------
# _fmt_power (INA219)
# ---------------------------------------------------------------------------

def test_fmt_power_battery():
    data = {"power_source": "Battery", "battery_pct": 75.0}
    line1, line2 = daemon._fmt_power(data)
    assert line1 == "Power"
    assert "Battery" in line2
    assert "75%" in line2


def test_fmt_power_plugged_in():
    data = {"power_source": "Plugged In", "battery_pct": 100.0}
    line1, line2 = daemon._fmt_power(data)
    assert line1 == "Power"
    assert "Plugged In" in line2


def test_fmt_power_unknown_no_pct():
    data = {"power_source": "Unknown", "battery_pct": float("nan")}
    line1, line2 = daemon._fmt_power(data)
    assert line1 == "Power"
    assert line2 == "Unknown"


# ---------------------------------------------------------------------------
# _fmt_cpu
# ---------------------------------------------------------------------------

def test_fmt_cpu_formats_percentages():
    data = {"cpu_avg_pct": 23.7, "mem_pct": 45.1, "cpu_warn": 90.0, "mem_warn": 90.0}
    line1, line2 = daemon._fmt_cpu(data)
    assert line1 == " CPU   Mem"
    assert "24%" in line2
    assert "45%" in line2


def test_fmt_cpu_warn_cpu():
    data = {"cpu_avg_pct": 95.0, "mem_pct": 45.0, "cpu_warn": 90.0, "mem_warn": 90.0}
    _, line2 = daemon._fmt_cpu(data)
    assert "WARN" in line2
    assert "45%" in line2


def test_fmt_cpu_warn_mem():
    data = {"cpu_avg_pct": 20.0, "mem_pct": 92.0, "cpu_warn": 90.0, "mem_warn": 90.0}
    _, line2 = daemon._fmt_cpu(data)
    assert "20%" in line2
    assert line2.endswith("WARN")


def test_fmt_cpu_alignment_stable_across_widths():
    # The % sign for both values must always land in the same column
    # Use thresholds above 100 so WARN is never triggered
    base = {"cpu_warn": 101.0, "mem_warn": 101.0}
    _, line2_low  = daemon._fmt_cpu({**base, "cpu_avg_pct": 1.0,   "mem_pct": 1.0})
    _, line2_high = daemon._fmt_cpu({**base, "cpu_avg_pct": 100.0, "mem_pct": 100.0})
    assert line2_low.index("%")  == line2_high.index("%")   # CPU % column stable
    assert line2_low.rindex("%") == line2_high.rindex("%")  # Mem % column stable


# ---------------------------------------------------------------------------
# _fmt_temp
# ---------------------------------------------------------------------------

def test_fmt_temp_ok():
    data = {"cpu_temp_c": 52.3, "temp_warn": 80.0}
    _, line2 = daemon._fmt_temp(data)
    assert "52.3C" in line2
    assert "WARN" not in line2


def test_fmt_temp_warn():
    data = {"cpu_temp_c": 85.0, "temp_warn": 80.0}
    _, line2 = daemon._fmt_temp(data)
    assert "85.0C" in line2
    assert "WARN" in line2


def test_fmt_temp_unavailable():
    data = {"cpu_temp_c": float("nan")}
    _, line2 = daemon._fmt_temp(data)
    assert "---" in line2


def test_fmt_temp_missing_keys():
    _, line2 = daemon._fmt_temp({})
    assert "---" in line2


# ---------------------------------------------------------------------------
# _fmt_net
# ---------------------------------------------------------------------------

def test_fmt_net_formats_rates():
    data = {"interface": "eth0", "rx_bps": 2048.0, "tx_bps": 512.0}
    line1, line2 = daemon._fmt_net(data)
    assert "eth0" in line1
    assert "2.0K" in line2
    assert "512B" in line2


def test_fmt_net_truncates_long_interface_name():
    data = {"interface": "docker0", "rx_bps": 0, "tx_bps": 0}
    line1, _ = daemon._fmt_net(data)
    assert "docke" in line1   # truncated to 5 chars


# ---------------------------------------------------------------------------
# _read_all
# ---------------------------------------------------------------------------

def test_read_all_calls_only_enabled_monitors():
    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    with patch("porcupine.daemon.boot.read", return_value={"boot_count": 3, "uptime_s": 100.0}), \
         patch("porcupine.daemon.cpu_mem.read") as mock_cpu:
        data = daemon._read_all(args)

    mock_cpu.assert_not_called()
    assert "boot_count" in data
    assert "cpu_avg_pct" not in data


def test_read_all_merges_multiple_monitors():
    args = _args(boot_every=1, power_every=0, cpu_every=1, temp_every=0, net_every=0, gpio_every=0)
    with patch("porcupine.daemon.boot.read", return_value={"boot_count": 1, "uptime_s": 60.0}), \
         patch("porcupine.daemon.cpu_mem.read", return_value={"cpu_avg_pct": 30.0, "mem_pct": 50.0,
                                                              "cpu_pct": [], "mem_used_mb": 512,
                                                              "mem_total_mb": 1024}):
        data = daemon._read_all(args)

    assert "boot_count" in data
    assert "cpu_avg_pct" in data


def test_read_all_skips_failing_monitor():
    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    with patch("porcupine.daemon.boot.read", side_effect=RuntimeError("hw error")):
        data = daemon._read_all(args)
    assert data == {}


def test_read_all_no_monitors_returns_empty():
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    with patch("porcupine.daemon.boot.read") as m:
        data = daemon._read_all(args)
    m.assert_not_called()
    assert data == {}


# ---------------------------------------------------------------------------
# _fmt_gpio
# ---------------------------------------------------------------------------

def test_fmt_gpio_returns_two_pages():
    data = {"gpio_pins": [None] * 40}
    pages = daemon._fmt_gpio(data)
    assert len(pages) == 2


def test_fmt_gpio_page_labels_and_width():
    data = {"gpio_pins": [None] * 40}
    (r1_p1, r2_p1), (r1_p2, r2_p2) = daemon._fmt_gpio(data)
    assert r1_p1.startswith("01[") and r1_p1.endswith("]19") and len(r1_p1) == 16
    assert r2_p1.startswith("02[") and r2_p1.endswith("]20") and len(r2_p1) == 16
    assert r1_p2.startswith("21[") and r1_p2.endswith("]39") and len(r1_p2) == 16
    assert r2_p2.startswith("22[") and r2_p2.endswith("]40") and len(r2_p2) == 16


def test_fmt_gpio_pin_count_per_row():
    data = {"gpio_pins": [None] * 40}
    (r1, _), _ = daemon._fmt_gpio(data)
    # strip the 3-char brackets on each side to get just the 10 status chars
    assert len(r1[3:-3]) == 10


# ---------------------------------------------------------------------------
# _build_screens
# ---------------------------------------------------------------------------

def test_build_screens_one_per_enabled_monitor():
    args = _args(boot_every=1, power_every=0, cpu_every=1, temp_every=0, net_every=0, gpio_every=0)
    data = {"boot_count": 1, "uptime_s": 60, "cpu_avg_pct": 10, "mem_pct": 20,
            "cpu_pct": [], "mem_used_mb": 100, "mem_total_mb": 500}
    screens = daemon._build_screens(args, data)
    assert len(screens) == 2


def test_build_screens_respects_order():
    args = _args(boot_every=1, power_every=0, cpu_every=0, temp_every=0, net_every=1, gpio_every=0)
    data = {"boot_count": 1, "uptime_s": 0,
            "interface": "eth0", "rx_bps": 0, "tx_bps": 0,
            "rx_total_mb": 0, "tx_total_mb": 0}
    screens = daemon._build_screens(args, data)
    assert screens[0][0] == "Boot"
    assert "Net" in screens[1][0]


def test_build_screens_gpio_contributes_two_screens():
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=1)
    screens = daemon._build_screens(args, {"gpio_pins": [None] * 40})
    assert len(screens) == 2


def test_build_screens_fallback_when_none_enabled():
    args = _args(boot_every=0, power_every=0, cpu_every=0, temp_every=0, net_every=0, gpio_every=0)
    screens = daemon._build_screens(args, {})
    assert screens == [("No monitors", "enabled")]


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
         patch("porcupine.daemon.Buzzer") as MockBuzzer:

        MockButton.return_value.start = MagicMock()
        MockButton.return_value.stop = MagicMock()
        MockButton.return_value._stub = MagicMock()
        MockButton.return_value._stub.on_edge = MagicMock()
        MockButton.return_value._read = lambda: 1

        daemon.run(args)

    assert iteration["count"] == 2
