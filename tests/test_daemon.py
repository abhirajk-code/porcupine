"""Daemon wiring tests — no hardware required."""
import argparse
import math
from unittest.mock import MagicMock, call, patch

import pytest

import porcupine.daemon as daemon
from porcupine.interfaces.lcd import LCD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        power=True, cpu=True, temp=True, net=True,
        lcd_addr=0x27, button_pin=17, buzzer_pin=18,
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
    (0,              "0B"),
    (512,            "512B"),
    (1023,           "1023B"),
    (1024,           "1.0K"),
    (1536,           "1.5K"),
    (1024 * 1024,    "1.0M"),
    (2.5 * 1024**2,  "2.5M"),
])
def test_bps_str(bps, expected):
    assert daemon._bps_str(bps) == expected


# ---------------------------------------------------------------------------
# _fmt_power
# ---------------------------------------------------------------------------

def test_fmt_power_formats_uptime():
    data = {"boot_count": 5, "uptime_s": 7320.0}   # 2h 2m
    line1, line2 = daemon._fmt_power(data)
    assert line1 == "Power"
    assert "Boot:5" in line2
    assert "2h02m" in line2


def test_fmt_power_missing_keys():
    line1, line2 = daemon._fmt_power({})
    assert line1 == "Power"
    assert "Boot:0" in line2


# ---------------------------------------------------------------------------
# _fmt_cpu
# ---------------------------------------------------------------------------

def test_fmt_cpu_formats_percentages():
    data = {"cpu_avg_pct": 23.7, "mem_pct": 45.1}
    line1, line2 = daemon._fmt_cpu(data)
    assert line1 == "CPU      Mem"
    assert "24%" in line2
    assert "45%" in line2


# ---------------------------------------------------------------------------
# _fmt_temp
# ---------------------------------------------------------------------------

def test_fmt_temp_ok():
    data = {"cpu_temp_c": 52.3, "throttled": False}
    _, line2 = daemon._fmt_temp(data)
    assert "52.3C" in line2
    assert "OK" in line2


def test_fmt_temp_throttled():
    data = {"cpu_temp_c": 85.0, "throttled": True}
    _, line2 = daemon._fmt_temp(data)
    assert "THROTTLED" in line2


def test_fmt_temp_unavailable():
    data = {"cpu_temp_c": float("nan"), "throttled": None}
    _, line2 = daemon._fmt_temp(data)
    assert "---" in line2
    assert "N/A" in line2


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
    args = _args(power=True, cpu=False, temp=False, net=False)
    with patch("porcupine.daemon.power.read", return_value={"boot_count": 3, "uptime_s": 100.0}), \
         patch("porcupine.daemon.cpu_mem.read") as mock_cpu:
        data = daemon._read_all(args)

    mock_cpu.assert_not_called()
    assert "boot_count" in data
    assert "cpu_avg_pct" not in data


def test_read_all_merges_multiple_monitors():
    args = _args(power=True, cpu=True, temp=False, net=False)
    with patch("porcupine.daemon.power.read", return_value={"boot_count": 1, "uptime_s": 60.0}), \
         patch("porcupine.daemon.cpu_mem.read", return_value={"cpu_avg_pct": 30.0, "mem_pct": 50.0,
                                                               "cpu_pct": [], "mem_used_mb": 512,
                                                               "mem_total_mb": 1024}):
        data = daemon._read_all(args)

    assert "boot_count" in data
    assert "cpu_avg_pct" in data


def test_read_all_skips_failing_monitor():
    args = _args(power=True, cpu=False, temp=False, net=False)
    with patch("porcupine.daemon.power.read", side_effect=RuntimeError("hw error")):
        data = daemon._read_all(args)
    assert data == {}


def test_read_all_no_monitors_returns_empty():
    args = _args(power=False, cpu=False, temp=False, net=False)
    with patch("porcupine.daemon.power.read") as m:
        data = daemon._read_all(args)
    m.assert_not_called()
    assert data == {}


# ---------------------------------------------------------------------------
# _build_screens
# ---------------------------------------------------------------------------

def test_build_screens_one_per_enabled_monitor():
    args = _args(power=True, cpu=True, temp=False, net=False)
    data = {"boot_count": 1, "uptime_s": 60, "cpu_avg_pct": 10, "mem_pct": 20,
            "cpu_pct": [], "mem_used_mb": 100, "mem_total_mb": 500}
    screens = daemon._build_screens(args, data)
    assert len(screens) == 2


def test_build_screens_respects_order():
    args = _args(power=True, cpu=False, temp=False, net=True)
    data = {"boot_count": 1, "uptime_s": 0,
            "interface": "eth0", "rx_bps": 0, "tx_bps": 0,
            "rx_total_mb": 0, "tx_total_mb": 0}
    screens = daemon._build_screens(args, data)
    assert screens[0][0] == "Power"
    assert "Net" in screens[1][0]


def test_build_screens_fallback_when_none_enabled():
    args = _args(power=False, cpu=False, temp=False, net=False)
    screens = daemon._build_screens(args, {})
    assert screens == [("No monitors", "enabled")]


# ---------------------------------------------------------------------------
# _MenuController
# ---------------------------------------------------------------------------

@pytest.fixture
def menu_setup():
    args = _args()
    lcd = _stub_lcd()
    screens = [("CPU", "50%")]
    menu = daemon._MenuController(lcd, args, lambda: screens)
    return menu, lcd, args


def test_menu_enter_resets_to_first_item(menu_setup):
    menu, lcd, _ = menu_setup
    menu._index = 3
    lcd.start([("A", "1")], refresh_s=60)
    lcd.enter_menu("dummy", "")
    menu.enter()
    assert menu._index == 0
    lcd.stop()


def test_menu_next_advances_index(menu_setup):
    menu, lcd, _ = menu_setup
    lcd.start([("A", "1")], refresh_s=60)
    lcd.enter_menu("dummy", "")
    menu.enter()
    menu.next_item()
    assert menu._index == 1
    lcd.stop()


def test_menu_next_wraps_around(menu_setup):
    menu, lcd, _ = menu_setup
    lcd.start([("A", "1")], refresh_s=60)
    lcd.enter_menu("dummy", "")
    menu._index = len(menu._ITEMS) - 1
    menu.next_item()
    assert menu._index == 0
    lcd.stop()


def test_menu_confirm_toggles_power_flag(menu_setup):
    menu, lcd, args = menu_setup
    lcd.start([("A", "1")], refresh_s=60)
    lcd.enter_menu("dummy", "")
    menu._index = 0  # "Toggle POWER"
    was = args.power
    menu.confirm()
    assert args.power is not was
    lcd.stop()


def test_menu_confirm_toggle_re_renders_state(menu_setup):
    menu, lcd, args = menu_setup
    lcd.start([("A", "1")], refresh_s=60)
    lcd.enter_menu("dummy", "")
    menu._index = 1  # "Toggle CPU"
    args.cpu = True
    menu.confirm()
    # After toggle, LCD menu line should reflect new OFF state
    assert lcd._lcd._lines[1].strip().startswith("Now:OFF")
    lcd.stop()


def test_menu_confirm_restart_calls_subprocess(menu_setup):
    menu, lcd, _ = menu_setup
    reset_called = []
    menu._reset_fn = lambda: reset_called.append(True)
    menu._index = 4  # "Restart Pi"
    with patch("porcupine.daemon.subprocess.run") as mock_run:
        menu.confirm()
    mock_run.assert_called_once_with(["sudo", "reboot"], check=False)
    assert reset_called == [True]


def test_menu_confirm_shutdown_calls_subprocess(menu_setup):
    menu, lcd, _ = menu_setup
    menu._reset_fn = lambda: None
    menu._index = 5  # "Shutdown Pi"
    with patch("porcupine.daemon.subprocess.run") as mock_run:
        menu.confirm()
    mock_run.assert_called_once_with(["sudo", "shutdown", "-h", "now"], check=False)


# ---------------------------------------------------------------------------
# run() — smoke test
# ---------------------------------------------------------------------------

def test_run_starts_and_stops_cleanly(tmp_path):
    args = _args(power=True, cpu=False, temp=False, net=False)

    iteration = {"count": 0}

    def fake_sleep(_):
        iteration["count"] += 1
        if iteration["count"] >= 2:
            raise KeyboardInterrupt

    power_data = {"boot_count": 1, "uptime_s": 60.0}

    with patch("porcupine.daemon.power.init"), \
         patch("porcupine.daemon.power.read", return_value=power_data), \
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
