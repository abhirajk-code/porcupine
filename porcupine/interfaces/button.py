"""GPIO button input handler (short/long press)."""


class Button:
    def __init__(self, pin: int, long_press_ms: int = 2000):
        raise NotImplementedError

    def on_short_press(self, callback) -> None:
        raise NotImplementedError

    def on_long_press(self, callback) -> None:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError
