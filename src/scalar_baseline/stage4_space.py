"""Frozen four-parameter Stage 4 space and content identity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math

PARAMETERS = frozenset({"half_life_steps", "signal_off", "loss_steps", "recovery_duration"})
DURATIONS = frozenset({0, 12, 24, 36, 48})


def _decimal(value: object, name: str, low: str, high: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{name} must be numeric")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not number.is_finite() or not Decimal(low) <= number <= Decimal(high):
        raise ValueError(f"{name} outside [{low},{high}]")
    # Nine significant decimal digits form the frozen simulation value.
    numeric = float(f"{number:.9g}")
    if not math.isfinite(numeric) or not float(low) <= numeric <= float(high):
        raise ValueError(f"{name} rounded outside bounds")
    return format(numeric, ".9g")


@dataclass(frozen=True)
class Candidate:
    half_life_steps: str
    signal_off: str
    loss_steps: int
    recovery_duration: int

    @classmethod
    def parse(cls, values: dict) -> "Candidate":
        if not isinstance(values, dict) or set(values) != PARAMETERS:
            raise ValueError("candidate must contain exactly four frozen parameters")
        loss, duration = values["loss_steps"], values["recovery_duration"]
        if type(loss) is not int or not 1 <= loss <= 6:
            raise ValueError("loss_steps outside [1,6]")
        if type(duration) is not int or duration not in DURATIONS:
            raise ValueError("invalid recovery_duration")
        return cls(_decimal(values["half_life_steps"], "half_life_steps", "250", "4000"),
                   _decimal(values["signal_off"], "signal_off", "0.10", "0.40"),
                   loss, duration)

    def record(self) -> dict:
        return {"half_life_steps": self.half_life_steps, "signal_off": self.signal_off,
                "loss_steps": self.loss_steps, "recovery_duration": self.recovery_duration}

    def canonical_json(self) -> str:
        return json.dumps(self.record(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


BASELINE = Candidate.parse({"half_life_steps": 1000, "signal_off": .25,
                            "loss_steps": 2, "recovery_duration": 0})
