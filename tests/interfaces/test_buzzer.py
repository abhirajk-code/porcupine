"""Buzzer and AlertChecker tests — no GPIO hardware required."""
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
    ac = AlertChecker(
        temp_warn=80.0, cpu_warn=90.0, mem_warn=90.0, bat_warn=40.0,
        temp_enabled=True, cpu_enabled=True, bat_enabled=True,
    )
    return ac


# ---------------------------------------------------------------------------
# AlertChecker — check() returns set of active alert keys
# ---------------------------------------------------------------------------

def test_temp_alert_active_above_threshold(checker):
    assert "temp" in checker.check({"cpu_temp_c": 85.0})


def test_temp_alert_inactive_below_threshold(checker):
    assert "temp" not in checker.check({"cpu_temp_c": 75.0})


def test_temp_alert_returned_on_every_call(checker):
    for _ in range(3):
        assert "temp" in checker.check({"cpu_temp_c": 85.0})


def test_cpu_alert_active_above_threshold(checker):
    assert "cpu" in checker.check({"cpu_avg_pct": 95.0})


def test_cpu_alert_inactive_below_threshold(checker):
    assert "cpu" not in checker.check({"cpu_avg_pct": 80.0})


def test_mem_alert_active_above_threshold(checker):
    assert "mem" in checker.check({"mem_pct": 95.0})


def test_mem_alert_inactive_below_threshold(checker):
    assert "mem" not in checker.check({"mem_pct": 80.0})


# ---------------------------------------------------------------------------
# AlertChecker — battery key
# ---------------------------------------------------------------------------

def test_bat_alert_active_below_threshold(checker):
    result = checker.check({"power_source": "Battery", "battery_pct": 25.0})
    assert "bat" in result


def test_bat_alert_inactive_above_threshold(checker):
    result = checker.check({"power_source": "Battery", "battery_pct": 75.0})
    assert "bat" not in result


def test_bat_alert_inactive_when_plugged_in(checker):
    result = checker.check({"power_source": "Plugged In", "battery_pct": 5.0})
    assert "bat" not in result


def test_bat_alert_returned_on_every_call(checker):
    for _ in range(2):
        assert "bat" in checker.check({"power_source": "Battery", "battery_pct": 20.0})


# ---------------------------------------------------------------------------
# AlertChecker — monitor disabled suppresses key
# ---------------------------------------------------------------------------

def test_temp_alert_suppressed_when_monitor_disabled():
    ac = AlertChecker(temp_warn=80.0, temp_enabled=False)
    assert "temp" not in ac.check({"cpu_temp_c": 85.0})


def test_cpu_alert_suppressed_when_monitor_disabled():
    ac = AlertChecker(cpu_warn=90.0, cpu_enabled=False)
    assert "cpu" not in ac.check({"cpu_avg_pct": 95.0})


def test_bat_alert_suppressed_when_monitor_disabled():
    ac = AlertChecker(bat_warn=40.0, bat_enabled=False)
    assert "bat" not in ac.check({"power_source": "Battery", "battery_pct": 10.0})


# ---------------------------------------------------------------------------
# AlertChecker — missing / nan data does not crash, returns empty set
# ---------------------------------------------------------------------------

def test_missing_keys_return_empty_set(checker):
    assert checker.check({}) == set()
    assert checker.check({"cpu_temp_c": float("nan")}) == set()
    assert checker.check({"battery_pct": float("nan"), "power_source": "Battery"}) == set()
