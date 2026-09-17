"""Exactly two local point queries, with no knowledge of contact sources."""

import math
from .config import B0Config
from .field import ScalarField


def sense(field: ScalarField, position: tuple[float, float], heading: float,
          config: B0Config) -> tuple[float, float]:
    samples = []
    for offset in (config.sensor_angle, -config.sensor_angle):
        angle = heading + offset
        point = (position[0] + config.sensor_distance * math.cos(angle),
                 position[1] + config.sensor_distance * math.sin(angle))
        samples.append(field.sample(point))
    return tuple(samples)
