"""Pure B0 decision function: no position, environment or food access."""

from dataclasses import dataclass
import math

from .config import B0Config, integer


@dataclass(frozen=True)
class Decision:
    heading: float
    role: str
    low_steps: int
    deterministic_turn: float


def navigate(*, heading: float, left: float, right: float, role: str,
             low_steps: int, fcrw_turn: float, noise: float, config: B0Config) -> Decision:
    if role not in {"follower", "fcrw"}:
        raise ValueError("B0 navigation accepts follower or fcrw only")
    if not all(math.isfinite(x) for x in (heading, left, right, fcrw_turn, noise)) or min(left, right) < 0:
        raise ValueError("navigation inputs must be finite; concentrations nonnegative")
    integer(low_steps, "low_steps", 0)
    if abs(noise) > config.noise_amplitude or abs(fcrw_turn) > math.pi:
        raise ValueError("noise or FCRW turn outside declared bounds")
    signal = max(left, right)
    if role == "follower":
        low_steps = low_steps + 1 if signal < config.signal_off else 0
        if low_steps >= config.loss_steps:
            role, low_steps = "fcrw", 0
    elif signal >= config.signal_on:
        role, low_steps = "follower", 0
    if role == "fcrw":
        return Decision((heading + fcrw_turn) % (2 * math.pi), role, 0, 0.0)
    # Scale before summing to prevent overflow at large finite concentration.
    scale = max(left, right, config.epsilon)
    bias = (left / scale - right / scale) / (left / scale + right / scale + config.epsilon / scale)
    deterministic = config.max_turn * bias
    turn = max(-config.max_turn, min(config.max_turn, deterministic + noise))
    return Decision((heading + turn) % (2 * math.pi), role, low_steps, deterministic)
