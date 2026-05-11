"""Buzzer alert driver with named beep patterns and threshold-based AlertChecker."""
import math
import threading
import time
from typing import Callable

try:
    import lgpio as _lgpio
    _HAS_LGPIO = True
except ImportError:
    _HAS_LGPIO = False

try:
    import RPi.GPIO as _RPIGPIO
    _HAS_RPIGPIO = True
except (ImportError, RuntimeError):
    _HAS_RPIGPIO = False

# True when any GPIO backend is available
_HAS_GPIO = _HAS_LGPIO or _HAS_RPIGPIO


class Buzzer:
    """
    Buzzer driver supporting passive (PWM) and active (DC) buzzers.

    Key parameters for passive buzzers (inspired by working MicroPython code):
    - frequency_hz=1047: resonant frequency of most cheap piezo buzzers
    - duty_pct=3.0:      short spike waveform — low duty cycle sounds louder
                         than 50% on passive buzzers (less damping per cycle)
    Set frequency_hz=0 for active buzzers that have an internal oscillator.

    Uses lgpio.tx_pwm on Pi 5+ and RPi.GPIO.PWM on older Pi models.
    Both produce a hardware/software PWM signal at the configured frequency
    and duty cycle for the duration of each beep.
    """

    def __init__(
        self,
        pin: int,
        active_high: bool = True,
        frequency_hz: int = 1047,
        duty_pct: float = 3.0,
    ):
        self._pin = pin
        self._active_high = active_high
        self._frequency_hz = frequency_hz
        self._duty_pct = duty_pct
        self._lock = threading.Lock()

        if _HAS_LGPIO:
            self._h = _lgpio.gpiochip_open(0)
            _lgpio.gpio_claim_output(self._h, pin, 0)  # initial low
        elif _HAS_RPIGPIO:
            self._h = None
            _RPIGPIO.setmode(_RPIGPIO.BCM)
            _RPIGPIO.setup(pin, _RPIGPIO.OUT, initial=_RPIGPIO.LOW)
            self._pwm = (
                _RPIGPIO.PWM(pin, max(frequency_hz, 1)) if frequency_hz > 0 else None
            )
        else:
            self._h = None
            self._stub = _StubPin()

    def beep(self, count: int = 1, duration_ms: int = 200, gap_ms: int = 100) -> None:
        with self._lock:
            for i in range(count):
                self._play_tone(duration_ms / 1000.0)
                if gap_ms > 0 and i < count - 1:
                    time.sleep(gap_ms / 1000.0)

    # Named alert patterns
    def alert_temp(self) -> None:
        """3 short beeps — CPU temperature critical."""
        self.beep(count=3, duration_ms=200, gap_ms=100)

    def alert_cpu(self) -> None:
        """2 beeps — CPU usage sustained high."""
        self.beep(count=2, duration_ms=200, gap_ms=100)

    def alert_mem(self) -> None:
        """1 long beep — RAM usage high."""
        self.beep(count=1, duration_ms=600, gap_ms=0)

    def alert_net(self) -> None:
        """1 beep — network interface lost."""
        self.beep(count=1, duration_ms=200, gap_ms=0)

    def cleanup(self) -> None:
        if _HAS_LGPIO:
            _lgpio.tx_pwm(self._h, self._pin, 0, 0)
            _lgpio.gpiochip_close(self._h)
        elif _HAS_RPIGPIO:
            if self._pwm is not None:
                self._pwm.stop()
            _RPIGPIO.cleanup(self._pin)

    # ------------------------------------------------------------------
    # Core tone generator
    # ------------------------------------------------------------------

    def _play_tone(self, duration_s: float) -> None:
        if _HAS_LGPIO:
            self._lgpio_tone(duration_s)
        elif _HAS_RPIGPIO:
            self._rpigpio_tone(duration_s)
        else:
            self._stub.set(True)
            time.sleep(duration_s)
            self._stub.set(False)

    def _lgpio_tone(self, duration_s: float) -> None:
        if self._frequency_hz <= 0:
            _lgpio.gpio_write(self._h, self._pin, 1 if self._active_high else 0)
            time.sleep(duration_s)
            _lgpio.gpio_write(self._h, self._pin, 0)
            return
        # Low duty cycle (~3%) at ~1047 Hz matches the working pattern from
        # the MicroPython doorLock code (duty_u16=2000/65535 ≈ 3%, freq=1047).
        _lgpio.tx_pwm(self._h, self._pin, self._frequency_hz, self._duty_pct)
        time.sleep(duration_s)
        _lgpio.tx_pwm(self._h, self._pin, 0, 0)

    def _rpigpio_tone(self, duration_s: float) -> None:
        if self._pwm is not None:
            self._pwm.start(self._duty_pct)
            time.sleep(duration_s)
            self._pwm.stop()
        else:
            level = _RPIGPIO.HIGH if self._active_high else _RPIGPIO.LOW
            _RPIGPIO.output(self._pin, level)
            time.sleep(duration_s)
            _RPIGPIO.output(self._pin,
                            _RPIGPIO.LOW if self._active_high else _RPIGPIO.HIGH)


# ---------------------------------------------------------------------------
# Alert checker
# ---------------------------------------------------------------------------

class AlertChecker:
    """
    Watches merged monitor data and fires Buzzer alert patterns when
    configurable thresholds are exceeded.

    Each alert fires once per threshold-crossing and re-arms when the
    condition clears, preventing buzzer spam on sustained conditions
    (except CPU, which requires the condition to persist for cpu_sustained_s).
    """

    _TEMP = "temp"
    _CPU  = "cpu"
    _MEM  = "mem"
    _NET  = "net"

    def __init__(
        self,
        buzzer: Buzzer,
        temp_warn: float = 80.0,
        cpu_warn: float = 90.0,
        mem_warn: float = 90.0,
        cpu_sustained_s: float = 30.0,
    ):
        self._buzzer = buzzer
        self._temp_warn = temp_warn
        self._cpu_warn = cpu_warn
        self._mem_warn = mem_warn
        self._cpu_sustained_s = cpu_sustained_s

        self._cpu_high_since: float | None = None
        self._alerted: set[str] = set()

    def check(self, data: dict) -> None:
        """Inspect the latest merged monitor snapshot and fire alerts as needed."""
        self._check_temp(data)
        self._check_cpu(data)
        self._check_mem(data)
        self._check_net(data)

    def _check_temp(self, data: dict) -> None:
        temp = data.get("cpu_temp_c")
        if temp is None or (isinstance(temp, float) and math.isnan(temp)):
            return
        if temp > self._temp_warn:
            self._fire_once(self._TEMP, self._buzzer.alert_temp)
        else:
            self._alerted.discard(self._TEMP)

    def _check_cpu(self, data: dict) -> None:
        cpu_avg = data.get("cpu_avg_pct")
        if cpu_avg is None:
            return
        now = time.monotonic()
        if cpu_avg > self._cpu_warn:
            if self._cpu_high_since is None:
                self._cpu_high_since = now
            elif now - self._cpu_high_since >= self._cpu_sustained_s:
                self._fire_once(self._CPU, self._buzzer.alert_cpu)
        else:
            self._cpu_high_since = None
            self._alerted.discard(self._CPU)

    def _check_mem(self, data: dict) -> None:
        mem_pct = data.get("mem_pct")
        if mem_pct is None:
            return
        if mem_pct > self._mem_warn:
            self._fire_once(self._MEM, self._buzzer.alert_mem)
        else:
            self._alerted.discard(self._MEM)

    def _check_net(self, data: dict) -> None:
        iface = data.get("interface")
        if iface is None:
            return
        if iface == "lo":
            self._fire_once(self._NET, self._buzzer.alert_net)
        else:
            self._alerted.discard(self._NET)

    def _fire_once(self, key: str, alert_fn: Callable) -> None:
        if key not in self._alerted:
            self._alerted.add(key)
            threading.Thread(target=alert_fn, daemon=True).start()


# ---------------------------------------------------------------------------
# Stub for non-Pi hosts
# ---------------------------------------------------------------------------

class _StubPin:
    """Records set(True/False) calls instead of toggling a real GPIO pin."""

    def __init__(self):
        self.log: list[bool] = []

    def set(self, on: bool) -> None:
        self.log.append(on)
