"""Fan controller — spawned by daemon when CPU temp exceeds fan_on threshold.

Self-terminates when temperature drops below fan_on * 0.8 (20 % hysteresis).
Writes a PID file so the daemon can check whether it is already running.

GPIO backend: lgpio is tried first (works on Pi 4 and Pi 5 via the kernel
character-device interface).  RPi.GPIO is used as a fallback for setups where
lgpio is not available (Pi 1-3 with older toolchains).
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


def _find_gpiochip() -> int:
    """Return the gpiochip number whose label matches the BCM/RP1 GPIO controller."""
    for chip in range(8):
        chip_path = Path(f"/dev/gpiochip{chip}")
        if not chip_path.exists():
            continue
        # Accept any chip that we can open — caller will verify
        return chip
    return 0


class _PWM:
    """PWM abstraction — lgpio (Pi 4/5) with RPi.GPIO fallback."""

    def __init__(self, pin: int, freq: int, initial_duty: float) -> None:
        self._pin  = pin
        self._freq = freq
        self._lgpio: object = None
        self._h: int = -1
        self._rpipwm: object = None
        self._GPIO: object = None

        if self._try_lgpio(pin, freq, initial_duty):
            return
        if self._try_rpigpio(pin, freq, initial_duty):
            return
        sys.exit("[porcupine-fan] No GPIO library available (lgpio or RPi.GPIO required)")

    def _try_lgpio(self, pin: int, freq: int, duty: float) -> bool:
        try:
            import lgpio  # noqa: PLC0415
        except ImportError:
            return False
        # Try gpiochip0 first, then higher numbers (Pi 5 may use gpiochip4).
        for chip in range(8):
            if not Path(f"/dev/gpiochip{chip}").exists():
                continue
            try:
                h = lgpio.gpiochip_open(chip)
                lgpio.gpio_claim_output(h, pin, 0)
                lgpio.tx_pwm(h, pin, freq, duty)
                self._lgpio = lgpio
                self._h     = h
                return True
            except Exception:
                try:
                    lgpio.gpiochip_close(h)
                except Exception:
                    pass
        return False

    def _try_rpigpio(self, pin: int, freq: int, duty: float) -> bool:
        try:
            import RPi.GPIO as GPIO  # noqa: PLC0415
        except ImportError:
            return False
        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pin, GPIO.OUT)
            pwm = GPIO.PWM(pin, freq)
            pwm.start(duty)
            self._GPIO   = GPIO
            self._rpipwm = pwm
            return True
        except Exception:
            return False

    def change_duty(self, duty: float) -> None:
        if self._lgpio is not None:
            self._lgpio.tx_pwm(self._h, self._pin, self._freq, duty)
        elif self._rpipwm is not None:
            self._rpipwm.ChangeDutyCycle(duty)

    def cleanup(self) -> None:
        if self._lgpio is not None:
            try:
                self._lgpio.tx_pwm(self._h, self._pin, self._freq, 0)
                self._lgpio.gpio_free(self._h, self._pin)
                self._lgpio.gpiochip_close(self._h)
            except Exception:
                pass
            self._lgpio = None
        elif self._rpipwm is not None:
            try:
                self._rpipwm.stop()
                self._GPIO.cleanup(self._pin)
            except Exception:
                pass
            self._rpipwm = None


def run(args: argparse.Namespace) -> None:
    freq    = args.fan_freq if args.fan_freq is not None else (25_000 if args.fan_type == "4pin" else 1_000)
    stop_at = args.fan_on * 0.8

    _PID_FILE.write_text(str(os.getpid()))

    pwm = _PWM(args.fan_pin, freq, float(args.min_duty))
    _done = False

    def _cleanup(signum=None, frame=None) -> None:
        nonlocal _done
        if not _done:
            _done = True
            pwm.cleanup()
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
            pwm.change_duty(_duty(temp, args.fan_on, args.min_duty))
            time.sleep(_POLL_S)
    finally:
        if not _done:
            _done = True
            pwm.cleanup()
            _PID_FILE.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="porcupine-fan", description="Porcupine fan controller")
    p.add_argument("--fan-pin",  type=int,   default=19,   metavar="PIN")
    p.add_argument("--fan-type", choices=["3pin", "4pin"], default="3pin")
    p.add_argument("--fan-freq", type=int,   default=None, metavar="HZ",
                   help="PWM frequency in Hz; overrides fan-type default (3pin=1000, 4pin=25000)")
    p.add_argument("--fan-on",   type=float, default=45.0, metavar="C")
    p.add_argument("--min-duty", type=int,   default=30,   metavar="PCT")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
