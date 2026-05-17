"""Fan controller tests — no hardware required."""
import sys
import types

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
# run() — stop-at logic (mocked GPIO + temp)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_gpio(monkeypatch):
    """Inject a minimal RPi.GPIO stub into sys.modules."""
    pwm_mock = types.SimpleNamespace(
        start=lambda d: None,
        stop=lambda: None,
        ChangeDutyCycle=lambda d: None,
    )

    class _GPIO:
        BCM = 11
        OUT = 0
        @staticmethod
        def setwarnings(_): pass
        @staticmethod
        def setmode(_): pass
        @staticmethod
        def setup(*_): pass
        @staticmethod
        def PWM(*_): return pwm_mock
        @staticmethod
        def cleanup(*_): pass

    rpi_mod  = types.ModuleType("RPi")
    gpio_mod = types.ModuleType("RPi.GPIO")
    gpio_mod.__dict__.update({k: v for k, v in vars(_GPIO).items() if not k.startswith("__")})
    for name in ("BCM", "OUT"):
        setattr(gpio_mod, name, getattr(_GPIO, name))
    gpio_mod.setwarnings      = _GPIO.setwarnings
    gpio_mod.setmode          = _GPIO.setmode
    gpio_mod.setup            = _GPIO.setup
    gpio_mod.PWM              = _GPIO.PWM
    gpio_mod.cleanup          = _GPIO.cleanup

    monkeypatch.setitem(sys.modules, "RPi",      rpi_mod)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio_mod)
    return gpio_mod


def test_run_exits_immediately_below_stop_at(tmp_path, monkeypatch, mock_gpio):
    # stop_at = 45 * 0.8 = 36.0 °C — temp at 35 °C exits immediately
    temp_file = tmp_path / "temp"
    temp_file.write_text("35000")  # 35.0 °C < 36.0 stop_at
    pid_file = tmp_path / "fan.pid"
    monkeypatch.setattr(fan_control, "_TEMP_PATH", temp_file)
    monkeypatch.setattr(fan_control, "_PID_FILE",  pid_file)

    args = fan_control.parse_args(["--fan-on", "45", "--fan-pin", "19"])
    fan_control.run(args)
    assert not pid_file.exists()


def test_run_cleans_up_pid_on_exit(tmp_path, monkeypatch, mock_gpio):
    temp_file = tmp_path / "temp"
    temp_file.write_text("35000")  # 35 °C < 36.0 stop_at
    pid_file  = tmp_path / "fan.pid"
    monkeypatch.setattr(fan_control, "_TEMP_PATH", temp_file)
    monkeypatch.setattr(fan_control, "_PID_FILE",  pid_file)

    fan_control.run(fan_control.parse_args(["--fan-on", "45"]))
    assert not pid_file.exists()
