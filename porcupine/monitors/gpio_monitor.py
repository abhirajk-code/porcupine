"""40-pin GPIO header state monitor (two-page display)."""
from . import gpio_pins
from .base import _Monitor

# Maps gpio_pins state strings → the display character for that pin
_GPIO_CHARS: dict[str | None, str] = {
    "3v3":   "^",
    "5v":    "+",
    "gnd":   "-",
    "out_h": chr(0),  # CGRAM slot 0: output driving high
    "out_l": chr(1),  # CGRAM slot 1: output driving low
    "in_h":  chr(2),  # CGRAM slot 2: input reading high
    "in_l":  chr(3),  # CGRAM slot 3: input reading low
    None:    " ",
}


class _GpioMonitor(_Monitor):
    flag = "gpio"

    def __init__(self, page: int, every: int = 0) -> None:
        super().__init__(every)
        self._page = page  # 1 = pins 1-20, 2 = pins 21-40

    def read(self) -> dict:
        return gpio_pins.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        pins  = data.get("gpio_pins", [])
        chars = [_GPIO_CHARS.get(s, " ") for s in pins]
        chars += [" "] * (40 - len(chars))

        def _row(indices: range, first_pin: int, last_pin: int) -> str:
            return f"{first_pin:02d}[{''.join(chars[i] for i in indices)}]{last_pin:02d}"

        if self._page == 1:
            return [(_row(range( 0, 20, 2),  1, 19), _row(range( 1, 20, 2),  2, 20))]
        else:
            return [(_row(range(20, 40, 2), 21, 39), _row(range(21, 40, 2), 22, 40))]
