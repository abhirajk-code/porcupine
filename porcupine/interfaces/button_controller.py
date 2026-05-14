"""Button FSM — maps short/long press sequences to LCD and system actions."""
import subprocess
import threading
import time

from .button import Button
from .lcd import LCD


class ButtonController:
    """
    Button press sequences:
      1. Short press (LCD on)         — start 5-second window; if no follow-up,
                                        turn off LCD backlight (monitoring continues)
      2. Short press (LCD off)        — turn LCD back on
      3. Short + short press (< 5 s)  — 20-second reboot countdown
      4. Short + long press  (< 5 s)  — 20-second shutdown countdown

    During a countdown, a short press cancels it.
    Data collection always continues regardless of LCD state.
    """

    _WINDOW_S    = 5.0
    _COUNTDOWN_S = 20

    def __init__(self, button: Button, lcd: LCD, on_long_idle=None):
        self._lcd    = lcd
        self._lcd_on = True
        # idle | after_first | after_second_start | counting
        self._state  = "idle"
        self._window_timer: threading.Timer | None = None
        self._cancel = threading.Event()
        self._on_long_idle = on_long_idle

        button.on_press_start(self._on_press_down)
        button.on_short_press(self._on_short)
        button.on_long_press(self._on_long)

    @property
    def monitoring(self) -> bool:
        return True  # data collection never stops; only the LCD turns off

    def _on_press_down(self) -> None:
        # Cancel the window as soon as a second press begins so the full
        # long-press duration (2 s) doesn't eat into the follow-up window.
        if self._state == "after_first":
            self._cancel_window()
            self._state = "after_second_start"

    def _on_short(self) -> None:
        if self._state == "idle":
            if not self._lcd_on:
                self._lcd_on = True
                self._lcd.resume()
            else:
                self._state = "after_first"
                self._window_timer = threading.Timer(self._WINDOW_S, self._window_expired)
                self._window_timer.start()
        elif self._state == "after_second_start":
            self._begin_countdown("reboot")
        elif self._state == "counting":
            self._cancel.set()

    def _on_long(self) -> None:
        if self._state == "after_second_start":
            self._begin_countdown("shutdown")
        elif self._state == "idle" and self._on_long_idle:
            self._on_long_idle()

    def set_lcd_on(self, state: bool) -> None:
        """Sync LCD on/off from external code (e.g. only_alert logic) without disturbing FSM state."""
        if state == self._lcd_on:
            return
        self._lcd_on = state
        if state:
            self._lcd.resume()
        else:
            self._lcd.pause()

    def _window_expired(self) -> None:
        self._lcd_on = False
        self._lcd.pause()
        self._state = "idle"

    def _cancel_window(self) -> None:
        if self._window_timer is not None:
            self._window_timer.cancel()
            self._window_timer = None

    def _begin_countdown(self, action: str) -> None:
        self._state = "counting"
        if not self._lcd_on:
            self._lcd_on = True
            self._lcd.resume()
        self._cancel.clear()
        line1 = "Rebooting..." if action == "reboot" else "Shutdown"
        self._lcd.enter_menu(line1, f"{self._COUNTDOWN_S}s  Press:cancel")
        threading.Thread(
            target=self._countdown_loop, args=(action, line1), daemon=True
        ).start()

    def _countdown_loop(self, action: str, line1: str) -> None:
        for remaining in range(self._COUNTDOWN_S - 1, -1, -1):
            if self._cancel.wait(timeout=1.0):
                self._lcd.update_menu("Cancelled", "")
                time.sleep(1.5)
                self._lcd.exit_menu()
                self._state = "idle"
                return
            self._lcd.update_menu(line1, f"{remaining}s  Press:cancel")
        if action == "reboot":
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)
