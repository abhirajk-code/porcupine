"""Fan controller tests — no hardware required."""
import sys

import pytest

import porcupine.fan_control as fan_control


# ---------------------------------------------------------------------------
# _duty — pure math
# ---------------------------------------------------------------------------

def test_duty_at_threshold_equals_min_duty():
    assert fan_control._duty(45.0, 45.0, 30) == pytest.approx(30.0)


def test_duty_at_85_equals_100():
    assert fan_control._duty(85.0, 45.0, 30) == pytest.approx(100.0)


def test_duty_midpoint():
    # Midpoint between 45 and 85 is 65 °C → (30+100)/2 = 65 %
    assert fan_control._duty(65.0, 45.0, 30) == pytest.approx(65.0)


def test_duty_clamped_below_min():
    # temp < fan_on → clamped to min_duty
    assert fan_control._duty(30.0, 45.0, 30) == pytest.approx(30.0)


def test_duty_clamped_above_100():
    # temp far above 85 → clamped to 100
    assert fan_control._duty(120.0, 45.0, 30) == pytest.approx(100.0)


def test_duty_custom_min_duty():
    assert fan_control._duty(45.0, 45.0, 50) == pytest.approx(50.0)
    assert fan_control._duty(85.0, 45.0, 50) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# _read_temp
# ---------------------------------------------------------------------------

def test_read_temp_parses_millidegrees(tmp_path, monkeypatch):
    f = tmp_path / "temp"
    f.write_text("47500\n")
    monkeypatch.setattr(fan_control, "_TEMP_PATH", f)
    assert fan_control._read_temp() == pytest.approx(47.5)


def test_read_temp_missing_raises_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(fan_control, "_TEMP_PATH", tmp_path / "nonexistent")
    with pytest.raises(OSError):
        fan_control._read_temp()


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

def test_parse_args_defaults():
    args = fan_control.parse_args([])
    assert args.fan_pin  == 19
    assert args.fan_type == "3pin"
    assert args.fan_on   == pytest.approx(45.0)
    assert args.min_duty == 30


def test_parse_args_4pin():
    args = fan_control.parse_args(["--fan-type", "4pin"])
    assert args.fan_type == "4pin"


def test_parse_args_custom_values():
    args = fan_control.parse_args([
        "--fan-pin", "13", "--fan-type", "4pin",
        "--fan-on", "50.0", "--min-duty", "20",
    ])
    assert args.fan_pin  == 13
    assert args.fan_type == "4pin"
    assert args.fan_on   == pytest.approx(50.0)
    assert args.min_duty == 20


# ---------------------------------------------------------------------------
# run() — stop-at logic (PWM stubbed out entirely)
# ---------------------------------------------------------------------------

class _StubPWM:
    """No-op PWM — lets run() loop tests focus on temp/stop logic."""
    duties: list

    def __init__(self, *_, **__):
        self.duties = []

    def change_duty(self, duty: float) -> None:
        self.duties.append(duty)

    def cleanup(self) -> None:
        pass


@pytest.fixture()
def stub_pwm(monkeypatch):
    """Replace _PWM with the no-op stub and return the instance holder."""
    instances: list[_StubPWM] = []

    def _make(*args, **kwargs):
        inst = _StubPWM(*args, **kwargs)
        instances.append(inst)
        return inst

    monkeypatch.setattr(fan_control, "_PWM", _make)
    return instances


def test_run_exits_immediately_below_stop_at(tmp_path, monkeypatch, stub_pwm):
    # stop_at = 45 * 0.8 = 36.0 °C — temp at 35 °C exits on first check
    temp_file = tmp_path / "temp"
    temp_file.write_text("35000")  # 35.0 °C < 36.0
    pid_file = tmp_path / "fan.pid"
    monkeypatch.setattr(fan_control, "_TEMP_PATH", temp_file)
    monkeypatch.setattr(fan_control, "_PID_FILE",  pid_file)

    fan_control.run(fan_control.parse_args(["--fan-on", "45", "--fan-pin", "19"]))
    assert not pid_file.exists()


def test_run_cleans_up_pid_on_exit(tmp_path, monkeypatch, stub_pwm):
    temp_file = tmp_path / "temp"
    temp_file.write_text("35000")
    pid_file  = tmp_path / "fan.pid"
    monkeypatch.setattr(fan_control, "_TEMP_PATH", temp_file)
    monkeypatch.setattr(fan_control, "_PID_FILE",  pid_file)

    fan_control.run(fan_control.parse_args(["--fan-on", "45"]))
    assert not pid_file.exists()


# ---------------------------------------------------------------------------
# _PWM backend selection
# ---------------------------------------------------------------------------

def test_pwm_uses_lgpio_when_available(monkeypatch):
    """_PWM._try_lgpio is called first; RPi.GPIO is never touched."""
    calls = []

    class _FakeLgpio:
        @staticmethod
        def gpiochip_open(chip): return 99
        @staticmethod
        def gpio_claim_output(h, pin, val): calls.append(("claim", pin))
        @staticmethod
        def tx_pwm(h, pin, freq, duty): calls.append(("pwm", duty))
        @staticmethod
        def gpio_free(h, pin): pass
        @staticmethod
        def gpiochip_close(h): pass

    from pathlib import Path
    monkeypatch.setitem(sys.modules, "lgpio", _FakeLgpio())
    monkeypatch.setattr(Path, "exists", lambda self: "/dev/gpiochip" in str(self))

    pwm = fan_control._PWM(pin=19, freq=1000, initial_duty=30.0)
    assert pwm._lgpio is not None
    assert ("claim", 19) in calls

    pwm.change_duty(50.0)
    assert ("pwm", 50.0) in calls

    pwm.cleanup()  # must not raise
