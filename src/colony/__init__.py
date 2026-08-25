"""Provisional paper-informed Stage 2A ant-colony simulation."""

from .agents import Ant, Role, coarse_grain_path
from .config import ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig
from .metrics import compute_order_parameters
from .simulation import ColonySimulation, SimulationResult

__all__ = [
    "Ant",
    "ColonyConfig",
    "ColonySimulation",
    "MovementConfig",
    "PheromoneConfig",
    "Role",
    "SimulationResult",
    "SiteConfig",
    "coarse_grain_path",
    "compute_order_parameters",
]
