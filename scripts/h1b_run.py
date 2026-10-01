#!/usr/bin/env python3
"""H1b runs (docs/H1B_ANALYSIS_PLAN.md): main, robust, sweep, check.

main   - Step 2: homo (100 x 60 deg) vs het120 (20 x 120 + 80 x 37.43 deg), D = 0.01, 230 seeds
robust - Step 3: as main at D = 0.02, fresh seeds
sweep  - Step 4/4b: het80, het100 and homo at 37.43 deg on the first 40 main seeds (exploratory)
check  - homo on H1a seed 2026240001 (half-life 1000); must equal the stored H1a delivery times
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from h1a_run import (ARENA, BASE_LANDMARKS, BASE_NOISE, FOOD_A, FOOD_B, NEST, POST, REF_HALF_LIFE,  # noqa: E402
                     RELOCATION, TOTAL, WINDOW, landmarks)
from scalar_baseline.config import B0Config, DecayConfig, SimulationConfig  # noqa: E402
from scalar_baseline.stage4_objective import amended_endpoint  # noqa: E402
from stage5_navigation.diffusion import DiffusingField  # noqa: E402
from stage5_navigation.heterogeneity import HeterogeneousPISimulation, group_assignment, matched_theta  # noqa: E402
from stage5_navigation.path_integration import NavigationConfig  # noqa: E402

OUT = ROOT / "results" / "h1b_heterogeneity"
N_ANTS, N_SCOUTS, THETA_REF = 100, 20, math.pi / 3
ON, OFF = 0.25, 0.125
SEEDS = {"main": range(2026260001, 2026260231), "robust": range(2026270001, 2026270231),
         "sweep": range(2026260001, 2026260041), "check": (2026240001,)}


def colony(scout_deg: float | None) -> dict:
    """None = homogeneous 60 deg; otherwise 20% scouts at scout_deg, rest matched."""
    if scout_deg is None:
        return {"theta_scout": THETA_REF, "theta_recruit": THETA_REF}
    scout = math.radians(scout_deg)
    return {"theta_scout": scout, "theta_recruit": matched_theta(THETA_REF, N_SCOUTS / N_ANTS, scout)}


def conditions(step: str) -> list[dict]:
    d = 0.02 if step == "robust" else 0.01
    if step == "check":
        return [{"name": "homo", "D": 0.01, **colony(None)}]
    if step == "sweep":
        straight = colony(120)["theta_recruit"]
        return [{"name": "het80", "D": d, **colony(80)}, {"name": "het100", "D": d, **colony(100)},
                {"name": "homo_straight", "D": d, "theta_scout": straight, "theta_recruit": straight}]
    return [{"name": "homo", "D": d, **colony(None)}, {"name": "het120", "D": d, **colony(120)}]


def run_one(task: tuple[dict, int]) -> dict:
    cond, seed = task
    config = SimulationConfig(n_ants=N_ANTS, steps=TOTAL, seed=seed, arena_size=ARENA, cell_size=1,
                              nest=NEST, food_a=FOOD_A, food_b=FOOD_B, step_size=0.6, deposit_q=1,
                              contact_radius=0.75, diffusion=0,
                              decay=DecayConfig(half_life_steps=REF_HALF_LIFE), relocation_step=RELOCATION,
                              navigation=B0Config(signal_on=ON, signal_off=OFF))
    scouts = set(group_assignment(seed, N_ANTS, N_SCOUTS))
    thetas = tuple(cond["theta_scout"] if i in scouts else cond["theta_recruit"] for i in range(N_ANTS))
    sim = HeterogeneousPISimulation(config, NavigationConfig(
        compass_noise=BASE_NOISE, landmarks=landmarks(seed, BASE_LANDMARKS), deposit_during_search=False),
        theta_max_per_ant=thetas)
    sim.field = DiffusingField(ARENA, 1, config.decay, diffusion=cond["D"])
    follower_steps = 0
    start = time.perf_counter()
    while sim.time < config.steps:
        sim.step()
        follower_steps += sum(a.role == "follower" for a in sim.ants)
    events = sim.ledger.events
    deliveries = [{"event": "delivery", "source": e["source"], "time": e["time"]}
                  for e in events if e["event"] == "delivery"]
    times_a = [e["time"] for e in deliveries if e["source"] == "A"]
    pickups = [e for e in events if e["event"] == "pickup"]
    first_b = next((e for e in pickups if e["source"] == "B"), None)
    ep = amended_endpoint(deliveries, relocation=RELOCATION, post_horizon=POST, window=WINDOW)
    return {**cond, "seed": seed, "scouts": sorted(scouts),
            "deliveries_A_pre": sum(t < RELOCATION for t in times_a),
            "delivery_times_A": times_a,
            "delivery_times_B": [e["time"] for e in deliveries if e["source"] == "B"],
            "pickups_by_group": {g: {s: sum(e["source"] == s and (e["ant_id"] in scouts) == (g == "scout")
                                             for e in pickups) for s in ("A", "B")}
                                 for g in ("scout", "recruit")},
            "first_B_pickup_group": None if first_b is None else
            ("scout" if first_b["ant_id"] in scouts else "recruit"),
            "follower_fraction": follower_steps / (config.steps * config.n_ants),
            "arrival_error_median": float(np.median(sim.arrival_errors)) if sim.arrival_errors else None,
            "tau": ep.tau_rec, "non_recovery": ep.non_recovery, "R_pre": ep.pre_deliveries,
            "wall_seconds": time.perf_counter() - start}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=tuple(SEEDS))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("use 1-4 workers (more froze the machine in H1a)")
    os.nice(10)  # low priority so the machine stays usable; inherited by workers
    tasks = [(c, s) for c in conditions(args.step) for s in SEEDS[args.step]]
    out = OUT / args.step
    parts = out / "runs"
    parts.mkdir(parents=True, exist_ok=True)
    part = lambda c, s: parts / f"{c['name']}_{s}.json"  # noqa: E731
    todo = [t for t in tasks if not part(*t).exists()]
    print(f"{len(tasks) - len(todo)} of {len(tasks)} runs already done; running {len(todo)}", flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, t): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            tmp = part(*futures[future]).with_suffix(".tmp")
            tmp.write_text(json.dumps(r) + "\n")
            tmp.replace(part(*futures[future]))  # atomic: a stop never leaves a half-written file
            print(f"[{i}/{len(todo)}] {r['name']} {r['seed']} Apre={r['deliveries_A_pre']} "
                  f"B={len(r['delivery_times_B'])} tau={r['tau']} {r['wall_seconds']:.0f}s", flush=True)
    rows = [json.loads(part(*t).read_text()) for t in tasks]
    (out / "runs.json").write_text(json.dumps(rows) + "\n")
    if args.step == "check":
        h1a = {r["seed"]: r for r in json.loads((ROOT / "results/h1a_baseline/h1a/runs.json").read_text())
               if r["half_life"] == REF_HALF_LIFE}
        ok = all(r["delivery_times_A"] == h1a[r["seed"]]["delivery_times_A"]
                 and r["delivery_times_B"] == h1a[r["seed"]]["delivery_times_B"]
                 and r["tau"] == h1a[r["seed"]]["tau"] for r in rows)
        print("reproduces stored H1a run:", ok)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
