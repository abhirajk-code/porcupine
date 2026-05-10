"""GPIO button input handler with short/long press detection and menu FSM."""
import time
from enum import Enum, auto
from typing import Callable

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except (ImportError, RuntimeError):
    _HAS_GPIO = False


class Button:
    """
    Single GPIO button wired active-low (internal pull-up).

    Fires on_short_press when released before long_press_ms,
    fires on_long_press when released after long_press_ms.
    """

    def __init__(self, pin: int, long_press_ms: int = 2000, debounce_ms: int = 50):
        self._pin = pin
        self._long_press_s = long_press_ms / 1000.0
        self._debounce_ms = debounce_ms
        self._press_time: float | None = None
        self._short_cb: Callable | None = None
        self._long_cb: Callable | None = None
        self._running = False

        if _HAS_GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._read = lambda: GPIO.input(pin)
        else:
            self._stub = _StubGPIO(pin)
            self._read = self._stub.read

    def on_short_press(self, callback: Callable) -> None:
        self._short_cb = callback

    def on_long_press(self, callback: Callable) -> None:
        self._long_cb = callback

    def start(self) -> None:
        self._running = True
        if _HAS_GPIO:
            GPIO.add_event_detect(
                self._pin, GPIO.BOTH,
                callback=self._edge_handler,
                bouncetime=self._debounce_ms,
            )
        else:
            self._stub.on_edge(self._edge_handler)

    def stop(self) -> None:
        self._running = False
        if _HAS_GPIO:
            GPIO.remove_event_detect(self._pin)
            GPIO.cleanup(self._pin)
        else:
            self._stub.remove_edge()

    def _edge_handler(self, channel: int) -> None:  # noqa: ARG002
        if not self._running:
            return
        if self._read() == 0:  # falling edge → pressed
            self._press_time = time.monotonic()
        else:                   # rising edge → released
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
    """In-process GPIO stand-in used when RPi.GPIO is not available."""

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
