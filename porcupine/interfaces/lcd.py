"""I2C LCD driver and display logic."""


class LCD:
    def __init__(self, i2c_addr: int = 0x27):
        raise NotImplementedError

    def show(self, line1: str, line2: str = "") -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError
