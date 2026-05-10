"""Buzzer alert driver."""


class Buzzer:
    def __init__(self, pin: int):
        raise NotImplementedError

    def beep(self, count: int = 1, duration_ms: int = 200, gap_ms: int = 100) -> None:
        raise NotImplementedError
