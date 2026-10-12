"""Simulated scale. Swap SimulatedScale for a hardware driver later without touching the API."""
import random
from typing import Protocol


class Scale(Protocol):
    def read_kg(self) -> float: ...


class SimulatedScale:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def read_kg(self) -> float:
        return round(self._rng.uniform(8.0, 30.0), 1)
