"""Buzzer and AlertChecker tests — no GPIO hardware required."""
import time
from unittest.mock import patch

import pytest

from porcupine.interfaces.buzzer import AlertChecker, Buzzer, _StubPin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_buzzer() -> Buzzer:
    return Buzzer(pin=18)


def pin_log(buzzer: Buzzer) -> list[bool]:
    return buzzer._stub.log


def fast_beep(buzzer, **kwargs):
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        buzzer.beep(**kwargs)


# ---------------------------------------------------------------------------
# Buzzer — beep mechanics
# ---------------------------------------------------------------------------

def test_single_beep_produces_on_off():
    bz = make_buzzer()
    fast_beep(bz, count=1, duration_ms=200, gap_ms=0)
    assert pin_log(bz) == [True, False]


def test_two_beeps_produce_correct_sequence():
    bz = make_buzzer()
    fast_beep(bz, count=2, duration_ms=200, gap_ms=100)
    assert pin_log(bz) == [True, False, True, False]


def test_three_beeps():
    bz = make_buzzer()
    fast_beep(bz, count=3, duration_ms=200, gap_ms=100)
    assert pin_log(bz) == [True, False, True, False, True, False]


def test_beep_zero_count_does_nothing():
    bz = make_buzzer()
    fast_beep(bz, count=0)
    assert pin_log(bz) == []


def test_gap_sleep_skipped_after_last_beep():
    bz = make_buzzer()
    sleep_calls = []
    with patch("porcupine.interfaces.buzzer.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        bz.beep(count=2, duration_ms=200, gap_ms=100)
    # 2 duration sleeps + 1 gap sleep (no gap after last beep)
    assert len(sleep_calls) == 3


def test_no_gap_sleep_when_gap_ms_zero():
    bz = make_buzzer()
    sleep_calls = []
    with patch("porcupine.interfaces.buzzer.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        bz.beep(count=2, duration_ms=200, gap_ms=0)
    assert len(sleep_calls) == 2


# ---------------------------------------------------------------------------
# _StubPin
# ---------------------------------------------------------------------------

def test_stub_pin_records_set_calls():
    stub = _StubPin()
    stub.set(True)
    stub.set(False)
    assert stub.log == [True, False]


# ---------------------------------------------------------------------------
# AlertChecker — helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def checker():
    bz = make_buzzer()
    ac = AlertChecker(
        buzzer=bz,
        temp_warn=80.0, cpu_warn=90.0, mem_warn=90.0, bat_warn=40.0,
        temp_enabled=True, cpu_enabled=True, bat_enabled=True,
    )
    return bz, ac


def _wait_for_beep(bz: Buzzer, timeout: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pin_log(bz):
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# AlertChecker — short beep on every cycle when threshold exceeded
# ---------------------------------------------------------------------------

def test_temp_alert_fires_short_beep_above_threshold(checker):
    bz, ac = checker
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("temp", {"cpu_temp_c": 85.0})
    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 1


def test_temp_alert_silent_below_threshold(checker):
    bz, ac = checker
    ac.check_for("temp", {"cpu_temp_c": 75.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_temp_alert_fires_every_cycle(checker):
    bz, ac = checker
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("temp", {"cpu_temp_c": 85.0})
        ac.check_for("temp", {"cpu_temp_c": 85.0})
        ac.check_for("temp", {"cpu_temp_c": 85.0})
    _wait_for_beep(bz)
    time.sleep(0.05)
    assert pin_log(bz).count(True) == 3


def test_temp_silent_for_other_monitor(checker):
    bz, ac = checker
    ac.check_for("cpu", {"cpu_temp_c": 85.0})  # temp high but cpu screen showing
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_cpu_alert_fires_immediately(checker):
    bz, ac = checker
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("cpu", {"cpu_avg_pct": 95.0})
    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 1


def test_cpu_alert_silent_below_threshold(checker):
    bz, ac = checker
    ac.check_for("cpu", {"cpu_avg_pct": 80.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_mem_alert_fires_short_beep(checker):
    bz, ac = checker
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("cpu", {"mem_pct": 95.0})
    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 1


def test_mem_alert_silent_below_threshold(checker):
    bz, ac = checker
    ac.check_for("cpu", {"mem_pct": 80.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


# ---------------------------------------------------------------------------
# AlertChecker — battery: long beep (600 ms)
# ---------------------------------------------------------------------------

def test_bat_alert_fires_long_beep_below_threshold(checker):
    bz, ac = checker
    sleep_calls = []
    with patch("porcupine.interfaces.buzzer.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        ac.check_for("power", {"power_source": "Battery", "battery_pct": 25.0})
    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 1
    assert sleep_calls[0] == pytest.approx(0.6)


def test_bat_alert_silent_above_threshold(checker):
    bz, ac = checker
    ac.check_for("power", {"power_source": "Battery", "battery_pct": 75.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_bat_alert_silent_when_plugged_in(checker):
    bz, ac = checker
    ac.check_for("power", {"power_source": "Plugged In", "battery_pct": 5.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_bat_alert_fires_every_cycle(checker):
    bz, ac = checker
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("power", {"power_source": "Battery", "battery_pct": 20.0})
        ac.check_for("power", {"power_source": "Battery", "battery_pct": 20.0})
    _wait_for_beep(bz)
    time.sleep(0.05)
    assert pin_log(bz).count(True) == 2


# ---------------------------------------------------------------------------
# AlertChecker — monitor disabled suppresses beep
# ---------------------------------------------------------------------------

def test_temp_alert_silent_when_monitor_disabled():
    bz = make_buzzer()
    ac = AlertChecker(buzzer=bz, temp_warn=80.0, temp_enabled=False)
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("temp", {"cpu_temp_c": 85.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_cpu_alert_silent_when_monitor_disabled():
    bz = make_buzzer()
    ac = AlertChecker(buzzer=bz, cpu_warn=90.0, cpu_enabled=False)
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("cpu", {"cpu_avg_pct": 95.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_bat_alert_silent_when_monitor_disabled():
    bz = make_buzzer()
    ac = AlertChecker(buzzer=bz, bat_warn=40.0, bat_enabled=False)
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        ac.check_for("power", {"power_source": "Battery", "battery_pct": 10.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


# ---------------------------------------------------------------------------
# AlertChecker — missing / nan data does not crash
# ---------------------------------------------------------------------------

def test_missing_keys_do_not_crash(checker):
    bz, ac = checker
    ac.check_for("temp", {})
    ac.check_for("cpu", {})
    ac.check_for("power", {})
    ac.check_for("temp", {"cpu_temp_c": float("nan")})
    ac.check_for("power", {"battery_pct": float("nan"), "power_source": "Battery"})
    time.sleep(0.05)
    assert pin_log(bz) == []
