"""Fixed, tiny engineering fixtures. No scientific parameter sweep entry point."""

from dataclasses import asdict
import math
import time
import numpy as np

from .config import B0Config, DecayConfig, SimulationConfig
from .field import ScalarField
from .sensing import sense
from .simulation import Simulation


def decay_trace() -> list:
    fields = {
        "exponential": ScalarField(1, 1, DecayConfig(half_life_steps=2)),
        "hard_cutoff_cell_timer": ScalarField(1, 1, DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=4)),
    }
    for field in fields.values():
        field.deposit((0.5, 0.5), 1)
    rows = [{"time": 0, **{mode: f.sample((0.5, 0.5)) for mode, f in fields.items()}}]
    for t in range(1, 9):
        for f in fields.values():
            f.step([((0.5, 0.5), 1)] if t == 2 else [])
        rows.append({"time": t, **{mode: f.sample((0.5, 0.5)) for mode, f in fields.items()}})
    assert rows[5]["hard_cutoff_cell_timer"] == 2
    assert rows[6]["hard_cutoff_cell_timer"] == 0
    assert math.isclose(rows[2]["exponential"], 1.5)
    return rows


def trail_fixture(gap: bool) -> dict:
    config = SimulationConfig(n_ants=1, steps=24 if gap else 8, theta_max=0,
                              navigation=B0Config(noise_amplitude=0))
    sim = Simulation(config)
    ant = sim.ants[0]
    ant.position, ant.heading, ant.role, ant.path = (3.5, 10.0), 0.0, "follower", [(3.5, 10.0)]
    for x in range(2, 24):
        if gap and 10 <= x <= 13:
            continue
        for y in (9, 10):
            sim.field.deposit((x + 0.5, y + 0.5), 1)
    rows = []
    for _ in range(config.steps):
        # Record the exact concentrations that step() will sense after decay.
        sim.field.advance(sim.time + 1)
        left, right = sense(sim.field, ant.position, ant.heading, config.navigation)
        sim.step()
        rows.append({"time": sim.time, "left": left, "right": right,
                     "position": ant.position, "heading": ant.heading,
                     "role": ant.role, "low_steps": ant.low_steps})
    if gap:
        first_loss = next(i for i, row in enumerate(rows) if max(row["left"], row["right"]) < config.navigation.signal_off)
        assert rows[first_loss]["role"] == "follower"
        assert rows[first_loss + 1]["role"] == "fcrw"
        assert all(row["role"] in {"follower", "fcrw"} for row in rows)
    else:
        assert all(row["role"] == "follower" and row["heading"] == 0 for row in rows)
    return {"config": asdict(config), "fixture": "artificial two-cell-wide straight trail; heading=0; initial=(3.5,10); gap x cells 10..13" if gap else "artificial two-cell-wide straight trail; heading=0; initial=(3.5,10)", "rows": rows}


def relocation_fixture() -> dict:
    config = SimulationConfig(n_ants=2, steps=10, arena_size=10, nest=(2, 2),
                              food_a=(4.4, 2), food_b=(2, 4.4), contact_radius=0.15,
                              relocation_step=5, theta_max=0,
                              navigation=B0Config(signal_on=100, signal_off=100, noise_amplitude=0))
    sim = Simulation(config)
    sim.ants[0].heading = 0
    ant = sim.ants[1]
    ant.position, ant.heading = (2, 0.8), math.pi / 2
    ant.path = [(2, 2), (2, 1.4), (2, 0.8)]
    rows = []
    for _ in range(config.steps):
        sim.step()
        rows.append({"time": sim.time, "agents": [asdict(a) for a in sim.ants],
                     "discoveries": dict(sim.ledger.discoveries), "deliveries": dict(sim.ledger.deliveries)})
    assert sim.ledger.carried_a_at_relocation == [0]
    assert sim.ledger.discoveries == {"A": 1, "B": 1}
    assert sim.ledger.deliveries == {"A": 1, "B": 1}
    assert sim.field.concentration.sum() > 0
    return {"config": asdict(config), "fixture": "deterministic contact geometry; ant0 heading=0; ant1 starts (2,0.8), heading=pi/2 with declared own prefix [(2,2),(2,1.4),(2,0.8)]; high thresholds isolate contact bookkeeping", "ledger": asdict(sim.ledger), "rows": rows}


def run_pilots() -> tuple[dict, dict]:
    outputs, timings = {}, {}
    for name, function in (("single_cell_decay", decay_trace),
                           ("straight_trail", lambda: trail_fixture(False)),
                           ("trail_gap", lambda: trail_fixture(True)),
                           ("food_relocation", relocation_fixture)):
        start = time.perf_counter()
        outputs[name] = function()
        timings[name] = time.perf_counter() - start
    start = time.perf_counter()
    sim = Simulation(SimulationConfig())
    sim.run()
    outputs["population_smoke"] = {"config": asdict(sim.config), "agents": [asdict(a) for a in sim.ants],
                                   "ledger": asdict(sim.ledger), "finite": bool(np.isfinite(sim.field.concentration).all()),
                                   "population": len(sim.ants), "field_sum": float(sim.field.concentration.sum())}
    timings["population_smoke"] = time.perf_counter() - start
    return outputs, timings
