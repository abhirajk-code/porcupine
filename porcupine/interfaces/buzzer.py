"""Buzzer alert driver with named beep patterns and threshold-based AlertChecker."""
import math
import threading
import time

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


    def cleanup(self) -> None:
        if _HAS_LGPIO:
            self._lgpio_stop()
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
        self._lgpio_stop()

    def _lgpio_stop(self) -> None:
        """Stop lgpio PWM without passing freq=0 (which raises 'bad PWM micros')."""
        if self._frequency_hz > 0:
            # duty=0 silences the pin while keeping a valid frequency.
            # Harmless if no PWM is currently running.
            try:
                _lgpio.tx_pwm(self._h, self._pin, self._frequency_hz, 0)
            except Exception:
                pass
        _lgpio.gpio_write(self._h, self._pin, 0)

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
    Watches merged monitor data and fires a short beep on every check cycle
    where a threshold is exceeded. Battery fires a long beep instead.
    """

    def __init__(
        self,
        buzzer: Buzzer,
        temp_warn: float = 80.0,
        cpu_warn: float = 90.0,
        mem_warn: float = 90.0,
        bat_warn: float = 40.0,
        temp_enabled: bool = True,
        cpu_enabled: bool = True,
        bat_enabled: bool = True,
    ):
        self._buzzer = buzzer
        self._temp_warn    = temp_warn
        self._cpu_warn     = cpu_warn
        self._mem_warn     = mem_warn
        self._bat_warn     = bat_warn
        self._temp_enabled = temp_enabled
        self._cpu_enabled  = cpu_enabled
        self._bat_enabled  = bat_enabled

    def check_for(self, monitor: str, data: dict) -> None:
        """Beep if the named monitor's screen is active and its threshold is exceeded."""
        if monitor == "temp" and self._temp_enabled:
            temp = data.get("cpu_temp_c")
            if temp is not None and not (isinstance(temp, float) and math.isnan(temp)):
                if temp >= self._temp_warn:
                    self._beep(150)

        elif monitor == "cpu" and self._cpu_enabled:
            cpu = data.get("cpu_avg_pct")
            if cpu is not None and cpu >= self._cpu_warn:
                self._beep(150)

            mem = data.get("mem_pct")
            if mem is not None and mem >= self._mem_warn:
                self._beep(150)

        elif monitor == "power" and self._bat_enabled:
            pct = data.get("battery_pct")
            if (pct is not None and not (isinstance(pct, float) and math.isnan(pct))
                    and data.get("power_source") == "Battery" and pct < self._bat_warn):
                self._beep(600)

    def _beep(self, duration_ms: int) -> None:
        threading.Thread(
            target=lambda: self._buzzer.beep(count=1, duration_ms=duration_ms),
            daemon=True,
        ).start()


# ---------------------------------------------------------------------------
# Stub for non-Pi hosts
# ---------------------------------------------------------------------------

class _StubPin:
    """Records set(True/False) calls instead of toggling a real GPIO pin."""

    def __init__(self):
        self.log: list[bool] = []

    def set(self, on: bool) -> None:
        self.log.append(on)
