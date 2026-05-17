"""Fan controller — spawned by daemon when CPU temp exceeds fan_on threshold.

Self-terminates when temperature drops below fan_on * 0.9 (10 % hysteresis)
to avoid on/off flapping.  Writes a PID file so the daemon can check whether
it is already running before spawning a duplicate.
"""
import argparse
import os
import signal
import sys
import time
from pathlib import Path

_TEMP_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
_PID_FILE  = Path("/run/porcupine-fan.pid")
_POLL_S    = 2.0


def _read_temp() -> float:
    """Read CPU temperature in °C from the sysfs thermal zone."""
    return int(_TEMP_PATH.read_text()) / 1_000.0


def _duty(temp: float, fan_on: float, min_duty: int) -> float:
    """Proportional duty cycle: min_duty % at fan_on °C, 100 % at 85 °C."""
    span = max(85.0 - fan_on, 1.0)
    raw  = min_duty + (temp - fan_on) / span * (100 - min_duty)
    return max(float(min_duty), min(100.0, raw))


def run(args: argparse.Namespace) -> None:
    try:
        import RPi.GPIO as GPIO  # noqa: PLC0415
    except ImportError:
        sys.exit("[porcupine-fan] RPi.GPIO not available — aborting")

    freq    = 25_000 if args.fan_type == "4pin" else 1_000
    stop_at = args.fan_on * 0.8

    _PID_FILE.write_text(str(os.getpid()))

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(args.fan_pin, GPIO.OUT)
    pwm = GPIO.PWM(args.fan_pin, freq)
    pwm.start(float(args.min_duty))

    def _cleanup(signum=None, frame=None) -> None:
        pwm.stop()
        GPIO.cleanup(args.fan_pin)
        _PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT,  _cleanup)

    try:
        while True:
            try:
                temp = _read_temp()
            except OSError:
                time.sleep(_POLL_S)
                continue
            if temp < stop_at:
                break
            pwm.ChangeDutyCycle(_duty(temp, args.fan_on, args.min_duty))
            time.sleep(_POLL_S)
    finally:
        pwm.stop()
        GPIO.cleanup(args.fan_pin)
        _PID_FILE.unlink(missing_ok=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="porcupine-fan", description="Porcupine fan controller")
    p.add_argument("--fan-pin",  type=int,   default=19,     metavar="PIN")
    p.add_argument("--fan-type", choices=["3pin", "4pin"],   default="3pin")
    p.add_argument("--fan-on",   type=float, default=45.0,   metavar="C")
    p.add_argument("--min-duty", type=int,   default=30,     metavar="PCT")
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
