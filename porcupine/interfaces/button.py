"""GPIO button input handler with short/long press detection."""
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


class Button:
    """
    Single GPIO button wired active-low (internal pull-up).

    Callbacks:
      on_press_start — fires immediately on button-down (falling edge);
                       use for instant audio feedback that the press registered
      on_short_press — fires on release after a short press (< long_press_ms)
      on_long_press  — fires on release after a long press  (≥ long_press_ms)
      on_held        — fires at the long_press_ms mark while the button is
                       still held; use for a "held long enough, release now" cue

    Uses lgpio on Pi 5+ and falls back to RPi.GPIO on older Pi models.
    """

    def __init__(self, pin: int, long_press_ms: int = 2000, debounce_ms: int = 50):
        self._pin = pin
        self._long_press_s = long_press_ms / 1000.0
        self._debounce_ms = debounce_ms
        self._press_time: float | None = None
        self._press_start_cbs: list[Callable] = []
        self._short_cb: Callable | None = None
        self._long_cb: Callable | None = None
        self._held_cb: Callable | None = None
        self._held_timer: threading.Timer | None = None
        self._running = False
        self._poll_thread: threading.Thread | None = None  # lgpio polling thread

        if _HAS_LGPIO:
            self._h = _lgpio.gpiochip_open(0)
            _lgpio.gpio_claim_input(self._h, pin, _lgpio.SET_PULL_UP)
            self._read = lambda: _lgpio.gpio_read(self._h, pin)
        elif _HAS_RPIGPIO:
            self._h = None
            _RPIGPIO.setmode(_RPIGPIO.BCM)
            _RPIGPIO.setup(pin, _RPIGPIO.IN, pull_up_down=_RPIGPIO.PUD_UP)
            self._read = lambda: _RPIGPIO.input(pin)
        else:
            self._h = None
            self._stub = _StubGPIO(pin)
            self._read = self._stub.read

    def on_press_start(self, callback: Callable) -> None:
        """Fires immediately on button-down — before release classification."""
        self._press_start_cbs.append(callback)

    def on_short_press(self, callback: Callable) -> None:
        self._short_cb = callback

    def on_long_press(self, callback: Callable) -> None:
        self._long_cb = callback

    def on_held(self, callback: Callable) -> None:
        """Fires once at the long-press threshold while the button is still held."""
        self._held_cb = callback

    def start(self) -> None:
        self._running = True
        if _HAS_LGPIO:
            # Use a polling thread rather than lgpio.callback — edge-triggered
            # interrupts are unreliable on Pi 5 / kernel 6.x, while polling
            # (the same technique used by the hardware test) works correctly.
            self._poll_thread = threading.Thread(
                target=self._lgpio_poll_loop, daemon=True
            )
            self._poll_thread.start()
        elif _HAS_RPIGPIO:
            _RPIGPIO.add_event_detect(
                self._pin, _RPIGPIO.BOTH,
                callback=self._rpigpio_edge_handler,
                bouncetime=self._debounce_ms,
            )
        else:
            self._stub.on_edge(self._rpigpio_edge_handler)

    def stop(self) -> None:
        self._running = False
        self._cancel_held_timer()
        if _HAS_LGPIO:
            if self._poll_thread is not None:
                self._poll_thread.join(timeout=0.5)
                self._poll_thread = None
            _lgpio.gpiochip_close(self._h)
        elif _HAS_RPIGPIO:
            _RPIGPIO.remove_event_detect(self._pin)
            _RPIGPIO.cleanup(self._pin)
        else:
            self._stub.remove_edge()

    # ------------------------------------------------------------------
    # lgpio polling loop (replaces unreliable edge callbacks on Pi 5)
    # ------------------------------------------------------------------

    def _lgpio_poll_loop(self) -> None:
        debounce_s = self._debounce_ms / 1000.0
        last_level = _lgpio.gpio_read(self._h, self._pin)
        while self._running:
            level = _lgpio.gpio_read(self._h, self._pin)
            if level != last_level:
                time.sleep(debounce_s)
                level = _lgpio.gpio_read(self._h, self._pin)
                if level != last_level:
                    last_level = level
                    if level == 0:
                        self._on_press_start()
                    else:
                        self._on_press_end()
            time.sleep(0.005)

    # ------------------------------------------------------------------
    # RPi.GPIO / stub edge handler
    # ------------------------------------------------------------------

    # RPi.GPIO / stub callback: (channel,)
    def _rpigpio_edge_handler(self, channel: int) -> None:  # noqa: ARG002
        if not self._running:
            return
        if self._read() == 0:
            self._on_press_start()
        else:
            self._on_press_end()

    # ------------------------------------------------------------------
    # Press lifecycle
    # ------------------------------------------------------------------

    def _on_press_start(self) -> None:
        self._press_time = time.monotonic()
        for cb in self._press_start_cbs:
            cb()
        if self._held_cb is not None:
            self._held_timer = threading.Timer(self._long_press_s, self._fire_held)
            self._held_timer.start()

    def _on_press_end(self) -> None:
        self._cancel_held_timer()
        if self._press_time is None:
            return
        duration = time.monotonic() - self._press_time
        self._press_time = None
        if duration >= self._long_press_s:
            if self._long_cb:
                self._long_cb()
        else:
            if self._short_cb:
                self._short_cb()

    def _fire_held(self) -> None:
        """Timer callback — button still held at long_press threshold."""
        if self._held_cb:
            self._held_cb()

    def _cancel_held_timer(self) -> None:
        if self._held_timer is not None:
            self._held_timer.cancel()
            self._held_timer = None


# ---------------------------------------------------------------------------
# Stub for non-Pi hosts
# ---------------------------------------------------------------------------

class _StubGPIO:
    """In-process GPIO stand-in used when neither lgpio nor RPi.GPIO is available."""

    def __init__(self, pin: int):
        self._pin = pin
        self._state: int = 1  # released (active-low: 1 = not pressed)
        self._callback: Callable | None = None

    def on_edge(self, callback: Callable) -> None:
        self._callback = callback

    def remove_edge(self) -> None:
        self._callback = None

    def read(self) -> int:
        return self._state

    def simulate_press(self) -> None:
        self._state = 0
        if self._callback:
            self._callback(self._pin)

    def simulate_release(self) -> None:
        self._state = 1
        if self._callback:
            self._callback(self._pin)
