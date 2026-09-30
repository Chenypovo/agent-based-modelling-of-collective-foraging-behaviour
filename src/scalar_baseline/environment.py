"""Contact-only food environment and metric-only cargo provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from .config import SimulationConfig


@dataclass
class Ledger:
    discoveries: dict = field(default_factory=lambda: {"A": 0, "B": 0})
    deliveries: dict = field(default_factory=lambda: {"A": 0, "B": 0})
    cargo: dict = field(default_factory=dict)
    carried_a_at_relocation: list = field(default_factory=list)
    events: list = field(default_factory=list)

    def pickup(self, ant_id: int, source: str, time: int) -> None:
        if ant_id in self.cargo or source not in self.discoveries:
            raise ValueError("invalid pickup")
        self.cargo[ant_id] = source
        self.discoveries[source] += 1
        self.events.append({"time": time, "event": "pickup", "ant_id": ant_id, "source": source})

    def deliver(self, ant_id: int, time: int) -> None:
        source = self.cargo.pop(ant_id)
        self.deliveries[source] += 1
        self.events.append({"time": time, "event": "delivery", "ant_id": ant_id, "source": source})


class ContactEnvironment:
    def __init__(self, config: SimulationConfig):
        self._nest = config.nest
        self._sources = {"A": config.food_a, "B": config.food_b}
        self._radius = config.contact_radius
        self._relocation_step = config.relocation_step
        self.active_source = "A"
        self.relocated = False

    def relocate(self, time: int, ledger: Ledger) -> None:
        # Deliberately has no field or agent arguments and emits no ant signal.
        if not self.relocated and time == self._relocation_step:
            self.active_source = "B"
            self.relocated = True
            ledger.carried_a_at_relocation = sorted(i for i, source in ledger.cargo.items() if source == "A")
            ledger.events.append({"time": time, "event": "relocation", "carried_a": list(ledger.carried_a_at_relocation)})

    def food_contact(self, position: tuple[float, float]) -> str | None:
        if math.dist(position, self._sources[self.active_source]) <= self._radius:
            return self.active_source
        return None

    def nest_contact(self, position: tuple[float, float]) -> bool:
        return math.dist(position, self._nest) <= self._radius
