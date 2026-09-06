"""Provisional paper-informed Stage 2A ant-colony simulation."""

from .agents import Ant, Role, coarse_grain_path
from .config import (
    ColonyConfig,
    FollowerDirectionRule,
    MovementConfig,
    PheromoneConfig,
    SiteConfig,
)
from .metrics import compute_order_parameters
from .simulation import ColonySimulation, SimulationResult
from .trail_direction import local_weighted_pca_tangent

__all__ = [
    "Ant",
    "ColonyConfig",
    "ColonySimulation",
    "FollowerDirectionRule",
    "MovementConfig",
    "PheromoneConfig",
    "Role",
    "SimulationResult",
    "SiteConfig",
    "coarse_grain_path",
    "compute_order_parameters",
    "local_weighted_pca_tangent",
]
