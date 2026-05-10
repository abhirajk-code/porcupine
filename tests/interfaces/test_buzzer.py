"""Buzzer and AlertChecker tests — no GPIO hardware required."""
import threading
import time
from unittest.mock import patch

import pytest

from porcupine.interfaces.buzzer import AlertChecker, Buzzer, _StubPin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_buzzer() -> Buzzer:
    """Return a Buzzer backed by _StubPin with time.sleep patched out."""
    return Buzzer(pin=18)


def pin_log(buzzer: Buzzer) -> list[bool]:
    return buzzer._stub.log


def fast_beep(buzzer, **kwargs):
    """Call beep() with sleep patched to a no-op."""
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
    # only duration sleeps
    assert len(sleep_calls) == 2


def test_beep_is_serialized_under_lock():
    """Concurrent beep calls don't interleave pin state."""
    bz = make_buzzer()
    results = []

    def beeper():
        with patch("porcupine.interfaces.buzzer.time.sleep"):
            bz.beep(count=2, duration_ms=10, gap_ms=0)
        results.append("done")

    threads = [threading.Thread(target=beeper) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log = pin_log(bz)
    assert len(log) == 12  # 3 threads × 2 beeps × (on+off)
    # Each on must immediately precede its matching off
    for i in range(0, len(log), 2):
        assert log[i] is True
        assert log[i + 1] is False


# ---------------------------------------------------------------------------
# Named alert patterns
# ---------------------------------------------------------------------------

def test_alert_temp_fires_3_beeps():
    bz = make_buzzer()
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        bz.alert_temp()
    assert pin_log(bz).count(True) == 3


def test_alert_cpu_fires_2_beeps():
    bz = make_buzzer()
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        bz.alert_cpu()
    assert pin_log(bz).count(True) == 2


def test_alert_mem_fires_1_long_beep():
    bz = make_buzzer()
    sleep_calls = []
    with patch("porcupine.interfaces.buzzer.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        bz.alert_mem()
    assert pin_log(bz).count(True) == 1
    assert sleep_calls[0] == pytest.approx(0.6)  # 600 ms


def test_alert_net_fires_1_beep():
    bz = make_buzzer()
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        bz.alert_net()
    assert pin_log(bz).count(True) == 1


# ---------------------------------------------------------------------------
# _StubPin
# ---------------------------------------------------------------------------

def test_stub_pin_records_set_calls():
    stub = _StubPin()
    stub.set(True)
    stub.set(False)
    assert stub.log == [True, False]


# ---------------------------------------------------------------------------
# AlertChecker
# ---------------------------------------------------------------------------

@pytest.fixture
def checker_setup():
    bz = make_buzzer()
    checker = AlertChecker(
        buzzer=bz,
        temp_warn=80.0,
        cpu_warn=90.0,
        mem_warn=90.0,
        cpu_sustained_s=1.0,  # short for tests
    )
    return bz, checker


def _wait_for_beep(bz: Buzzer, timeout: float = 0.5) -> bool:
    """Wait until the stub pin log is non-empty (background thread fired)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pin_log(bz):
            return True
        time.sleep(0.01)
    return False


def test_temp_alert_fires_above_threshold(checker_setup):
    bz, checker = checker_setup
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        checker.check({"cpu_temp_c": 85.0})
    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 3  # alert_temp → 3 beeps


def test_temp_alert_does_not_fire_below_threshold(checker_setup):
    bz, checker = checker_setup
    checker.check({"cpu_temp_c": 75.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_temp_alert_fires_once_not_repeatedly(checker_setup):
    bz, checker = checker_setup
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        checker.check({"cpu_temp_c": 85.0})
        checker.check({"cpu_temp_c": 85.0})
        checker.check({"cpu_temp_c": 85.0})
    assert _wait_for_beep(bz)
    time.sleep(0.05)
    assert pin_log(bz).count(True) == 3  # only one alert fired


def test_temp_alert_rearms_after_condition_clears(checker_setup):
    bz, checker = checker_setup
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        checker.check({"cpu_temp_c": 85.0})   # fires
        checker.check({"cpu_temp_c": 75.0})   # clears
        checker.check({"cpu_temp_c": 85.0})   # fires again
    _wait_for_beep(bz)
    time.sleep(0.1)
    assert pin_log(bz).count(True) == 6  # 3 beeps × 2 alerts


def test_mem_alert_fires_above_threshold(checker_setup):
    bz, checker = checker_setup
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        checker.check({"mem_pct": 95.0})
    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 1


def test_mem_alert_does_not_fire_below_threshold(checker_setup):
    bz, checker = checker_setup
    checker.check({"mem_pct": 80.0})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_net_alert_fires_when_interface_is_lo(checker_setup):
    bz, checker = checker_setup
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        checker.check({"interface": "lo"})
    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 1


def test_net_alert_does_not_fire_for_real_interface(checker_setup):
    bz, checker = checker_setup
    checker.check({"interface": "eth0"})
    time.sleep(0.05)
    assert pin_log(bz) == []


def test_cpu_alert_requires_sustained_duration(checker_setup):
    bz, checker = checker_setup
    # cpu_sustained_s = 1.0 in fixture
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        checker.check({"cpu_avg_pct": 95.0})  # starts timer, no alert yet
    time.sleep(0.05)
    assert pin_log(bz) == []  # not yet


def test_cpu_alert_fires_after_sustained_duration(checker_setup):
    bz, checker = checker_setup
    with patch("porcupine.interfaces.buzzer.time.monotonic") as mock_mono:
        mock_mono.return_value = 0.0
        checker.check({"cpu_avg_pct": 95.0})   # starts timer at t=0

        mock_mono.return_value = 1.1            # 1.1 s later → threshold crossed
        with patch("porcupine.interfaces.buzzer.time.sleep"):
            checker.check({"cpu_avg_pct": 95.0})

    assert _wait_for_beep(bz)
    assert pin_log(bz).count(True) == 2  # alert_cpu → 2 beeps


def test_cpu_alert_resets_timer_when_condition_clears(checker_setup):
    bz, checker = checker_setup
    with patch("porcupine.interfaces.buzzer.time.monotonic") as mock_mono:
        mock_mono.return_value = 0.0
        checker.check({"cpu_avg_pct": 95.0})  # starts timer

        mock_mono.return_value = 0.5
        checker.check({"cpu_avg_pct": 50.0})  # clears — resets timer
        assert checker._cpu_high_since is None

        mock_mono.return_value = 0.6
        checker.check({"cpu_avg_pct": 95.0})  # restarts timer
        assert checker._cpu_high_since == 0.6

    time.sleep(0.05)
    assert pin_log(bz) == []  # never hit sustained threshold


def test_missing_keys_do_not_crash(checker_setup):
    bz, checker = checker_setup
    checker.check({})   # empty dict, all keys missing
    checker.check({"cpu_temp_c": float("nan")})
    time.sleep(0.05)
    assert pin_log(bz) == []
