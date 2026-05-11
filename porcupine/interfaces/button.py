"""GPIO button input handler with short/long press detection and menu FSM."""
import time
from enum import Enum, auto
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

    Fires on_short_press when released before long_press_ms,
    fires on_long_press when released after long_press_ms.

    Uses lgpio on Pi 5+ and falls back to RPi.GPIO on older Pi models.
    """

    def __init__(self, pin: int, long_press_ms: int = 2000, debounce_ms: int = 50):
        self._pin = pin
        self._long_press_s = long_press_ms / 1000.0
        self._debounce_ms = debounce_ms
        self._press_time: float | None = None
        self._short_cb: Callable | None = None
        self._long_cb: Callable | None = None
        self._running = False
        self._cb = None  # lgpio callback handle

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

    def on_short_press(self, callback: Callable) -> None:
        self._short_cb = callback

    def on_long_press(self, callback: Callable) -> None:
        self._long_cb = callback

    def start(self) -> None:
        self._running = True
        if _HAS_LGPIO:
            self._cb = _lgpio.callback(
                self._h, self._pin, _lgpio.BOTH_EDGES,
                self._lgpio_edge_handler,
            )
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
        if _HAS_LGPIO:
            if self._cb is not None:
                _lgpio.callback_cancel(self._cb)
                self._cb = None
            _lgpio.gpiochip_close(self._h)
        elif _HAS_RPIGPIO:
            _RPIGPIO.remove_event_detect(self._pin)
            _RPIGPIO.cleanup(self._pin)
        else:
            self._stub.remove_edge()

    # lgpio callback: (chip, gpio, level, tick) — level is 0/1 directly
    def _lgpio_edge_handler(self, chip: int, gpio: int, level: int, tick: int) -> None:
        if not self._running:
            return
        if level == 0:       # falling → pressed (active-low)
            self._press_time = time.monotonic()
        elif level == 1:     # rising → released
            self._fire_if_valid()

    # RPi.GPIO / stub callback: (channel,)
    def _rpigpio_edge_handler(self, channel: int) -> None:  # noqa: ARG002
        if not self._running:
            return
        if self._read() == 0:   # falling → pressed
            self._press_time = time.monotonic()
        else:                    # rising → released
            self._fire_if_valid()

    def _fire_if_valid(self) -> None:
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


# ---------------------------------------------------------------------------
# Menu FSM
# ---------------------------------------------------------------------------

class _State(Enum):
    NORMAL = auto()
    MENU = auto()


class MenuFSM:
    """
    Wires a Button to normal/menu mode transitions.

    Normal mode:
      short press → next_screen_cb()
      long press  → enter_menu_cb()  + switch to MENU

    Menu mode:
      short press → menu_next_cb()
      long press  → menu_confirm_cb() + switch to NORMAL
    """

    def __init__(
        self,
        button: Button,
        next_screen_cb: Callable,
        enter_menu_cb: Callable,
        menu_next_cb: Callable,
        menu_confirm_cb: Callable,
    ):
        self._next_screen_cb = next_screen_cb
        self._enter_menu_cb = enter_menu_cb
        self._menu_next_cb = menu_next_cb
        self._menu_confirm_cb = menu_confirm_cb
        self._state = _State.NORMAL

        button.on_short_press(self._on_short)
        button.on_long_press(self._on_long)

    @property
    def in_menu(self) -> bool:
        return self._state == _State.MENU

    def reset(self) -> None:
        """Force return to NORMAL (e.g. after a shutdown/restart is confirmed)."""
        self._state = _State.NORMAL

    def _on_short(self) -> None:
        if self._state == _State.NORMAL:
            self._next_screen_cb()
        else:
            self._menu_next_cb()

    def _on_long(self) -> None:
        if self._state == _State.NORMAL:
            self._state = _State.MENU
            self._enter_menu_cb()
        else:
            self._state = _State.NORMAL
            self._menu_confirm_cb()


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
