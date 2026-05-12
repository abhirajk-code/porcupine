"""I2C LCD driver and display loop (HD44780 + PCF8574 backpack)."""
import threading
import time
from typing import Callable

try:
    from RPLCD.i2c import CharLCD
    _HAS_RPLCD = True
except Exception:
    _HAS_RPLCD = False


class LCD:
    """
    Wraps a 16×2 or 20×4 I2C LCD.

    In normal mode the display cycles through a list of (line1, line2) screens
    at a fixed interval. In menu mode it shows a static screen until
    exit_menu() is called.
    """

    def __init__(self, i2c_addr: int = 0x27, cols: int = 16, rows: int = 2):
        self._cols = cols
        self._rows = rows
        self._lock = threading.Lock()
        self._screens: list[tuple[str, str]] = []
        self._index: int = 0
        self._in_menu: bool = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._refresh_s: float = 3.0

        if _HAS_RPLCD:
            self._lcd = CharLCD(
                i2c_expander="PCF8574",
                address=i2c_addr,
                port=1,
                cols=cols,
                rows=rows,
                auto_linebreaks=False,
            )
        else:
            self._lcd = _StubLCD(cols, rows)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, screens: list[tuple[str, str]], refresh_s: float = 3.0) -> None:
        """Start the background cycling loop."""
        self._refresh_s = refresh_s
        with self._lock:
            self._screens = screens
            self._index = 0
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._cycle_loop, args=(refresh_s,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.clear()
        with self._lock:
            self._lcd.backlight_enabled = False

    def pause(self) -> None:
        """Stop cycling, clear display, and turn off backlight."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        with self._lock:
            self._lcd.clear()
            self._lcd.backlight_enabled = False

    def resume(self) -> None:
        """Turn on backlight, render current screen, and restart cycling."""
        with self._lock:
            self._lcd.backlight_enabled = True
            self._render_current()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._cycle_loop, args=(self._refresh_s,), daemon=True
        )
        self._thread.start()

    def next_screen(self) -> None:
        """Advance to the next screen (called from button short-press)."""
        with self._lock:
            if self._screens:
                self._index = (self._index + 1) % len(self._screens)
            self._render_current()

    def show(self, line1: str, line2: str = "") -> None:
        """Write two lines directly, bypassing the cycle loop."""
        with self._lock:
            self._write(line1, line2)

    def enter_menu(self, line1: str, line2: str = "") -> None:
        with self._lock:
            self._in_menu = True
            self._write(line1, line2)

    def update_menu(self, line1: str, line2: str = "") -> None:
        with self._lock:
            self._write(line1, line2)

    def exit_menu(self) -> None:
        with self._lock:
            self._in_menu = False
            self._render_current()

    def clear(self) -> None:
        with self._lock:
            self._lcd.clear()

    def update_screens(self, screens: list[tuple[str, str]]) -> None:
        """Replace the screen list (called when monitors toggled)."""
        with self._lock:
            self._screens = screens
            self._index = min(self._index, max(0, len(screens) - 1))

    def load_custom_chars(self, chars: list[list[int]]) -> None:
        """Load up to 8 custom characters into CGRAM (slots 0–7)."""
        with self._lock:
            for i, bitmap in enumerate(chars[:8]):
                self._lcd.create_char(i, bitmap)

    # ------------------------------------------------------------------
    # Internal helpers (must be called with _lock held)
    # ------------------------------------------------------------------

    def _render_current(self) -> None:
        if not self._screens:
            self._lcd.clear()
            return
        line1, line2 = self._screens[self._index]
        self._write(line1, line2)

    def _write(self, line1: str, line2: str) -> None:
        self._lcd.clear()
        self._lcd.write_string(line1[: self._cols])
        if self._rows >= 2:
            self._lcd.cursor_pos = (1, 0)
            self._lcd.write_string(line2[: self._cols])

    def _cycle_loop(self, refresh_s: float) -> None:
        while not self._stop_event.wait(timeout=refresh_s):
            with self._lock:
                if not self._in_menu:
                    self._index = (self._index + 1) % max(len(self._screens), 1)
                    self._render_current()


class _StubLCD:
    """Silent no-op LCD used when RPLCD is not installed (dev / test host)."""

    def __init__(self, cols: int, rows: int):
        self.cols = cols
        self.rows = rows
        self.cursor_pos = (0, 0)
        self._lines: list[str] = ["", ""]

    def clear(self) -> None:
        self._lines = [""] * self.rows
        self.cursor_pos = (0, 0)

    @property
    def backlight_enabled(self) -> bool:
        return True

    @backlight_enabled.setter
    def backlight_enabled(self, value: bool) -> None:
        pass

    def write_string(self, text: str) -> None:
        row, col = self.cursor_pos
        if row < self.rows:
            self._lines[row] = text[: self.cols - col]

    def create_char(self, location: int, bitmap: list[int]) -> None:
        pass

    def current_display(self) -> list[str]:
        return list(self._lines)
