"""_Monitor abstract base class and shared utilities."""
import math
from abc import ABC, abstractmethod


def _is_valid(value: object) -> bool:
    """Return True if value is a usable number (not None and not NaN)."""
    return value is not None and not (isinstance(value, float) and math.isnan(value))


class _Monitor(ABC):
    """Per-feature monitor with a uniform interface for the orchestrator."""
    flag: str

    def __init__(self, every: int = 0) -> None:
        self.every = every
        self._escalated: bool = False

    @property
    def effective_every(self) -> int:
        """Read cadence: 1 when a breach is active, configured every otherwise."""
        return 1 if self._escalated else self.every

    @abstractmethod
    def read(self) -> dict: ...

    @abstractmethod
    def format_screens(self, data: dict) -> list[tuple[str, str]]: ...

    def has_breach(self, data: dict) -> bool:
        return False

    def beep_pattern(self) -> dict | None:
        return None
