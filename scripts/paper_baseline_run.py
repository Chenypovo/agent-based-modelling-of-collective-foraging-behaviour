#!/usr/bin/env python3
"""Paper-baseline runs (docs/PAPER_BASELINE_PLAN.md Sec. 3).

paper  - Step 2: paper-faithful (no decay, D = 0, FCRW, 0.5/0.25) + pheromone-off, 10 seeds
calib  - Step 3: half-life x D x thresholds (18 cells) + pheromone-off, 10 seeds (stride-3 return; all failed)
calib2 - Step 3b (user decision after Step 3): home-vector return, compass noise {0, 0.1, 0.3} x the
         same 18 cells = 54 cells, + pheromone-off per noise level, 10 fresh seeds (no cell passed check 5)
calib3 - Step 3c (Amendment B, after Step 3b): calib2 grid at 20,000 steps, late windows +8,000, fresh seeds
valid  - Step 4: chosen cell (results/paper_baseline/calib3/selection.json); ZW; arena 600;
         paper layout; each with its own pheromone-off control, 20 seeds, 20,000 steps
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

import numpy as np  # noqa: E402

from scalar_baseline.config import B0Config, DecayConfig, SimulationConfig  # noqa: E402
from paper_baseline import checks  # noqa: E402
from paper_baseline.model import PaperOptions, PaperSimulation, baseline_options  # noqa: E402

OUT = ROOT / "results" / "paper_baseline"
SEEDS = {"paper": range(2026280001, 2026280011), "calib": range(2026290001, 2026290011),
         "calib2": range(2026310001, 2026310011), "calib3": range(2026320001, 2026320011),
         "valid": range(2026300001, 2026300021)}
N_ANTS, STEP, GAMMA, THETA = 100, 0.6, 0.1, math.radians(50)
STATIC_STEPS, PAPER_STEPS = 12000, 20000
SNAP_TIMES, SERIES_EVERY, FIELD_SEEDS = (1000, 4000, 10000, 18000), 10, 3
THRESHOLDS = {"t50": (0.5, 0.25), "t25": (0.25, 0.125)}


def layout(name: str) -> dict:
    if name == "paper":  # paper Fig. 4, estimated from the figure; B unused, same distance at 30 deg
        r = math.dist((90, 90), (240, 240))
        return {"arena": 300.0, "nest": (90.0, 90.0), "food_a": (240.0, 240.0),
                "food_b": (90 + r * math.cos(math.pi / 6), 90 + r * math.sin(math.pi / 6))}
    arena = {"std": 300.0, "a600": 600.0}[name]
    c, d = arena / 2, 90 / math.sqrt(2)
    return {"arena": arena, "nest": (c, c), "food_a": (c + d, c + d), "food_b": (c - d, c + d)}


NOISES = (0.0, 0.1, 0.3)


def cond(name, *, field="diffusing", half_life=1000.0, D=0.0, thr="t50", walk="fcrw", deposit=True,
         where="std", steps=STATIC_STEPS, homing="route", noise=0.0):
    return {"name": name, "field": field, "half_life": half_life, "D": D, "thr": thr, "walk": walk,
            "deposit": deposit, "layout": where, "steps": steps, "homing": homing, "noise": noise}


def conditions(step: str) -> list[dict]:
    if step == "paper":
        return [cond("nodecay", field="no_decay"), cond("off", deposit=False)]
    if step == "calib":
        cells = [cond(f"h{h}_D{D}_{t}", half_life=float(h), D=D, thr=t)
                 for h in (500, 1000, 2000) for D in (0.0, 0.01, 0.02) for t in THRESHOLDS]
        return cells + [cond("off", deposit=False)]
    if step in ("calib2", "calib3"):
        steps = STATIC_STEPS if step == "calib2" else PAPER_STEPS
        cells = [cond(f"n{n}_h{h}_D{D}_{t}", half_life=float(h), D=D, thr=t, homing="vector", noise=n, steps=steps)
                 for n in NOISES for h in (500, 1000, 2000) for D in (0.0, 0.01, 0.02) for t in THRESHOLDS]
        return cells + [cond(f"n{n}_off", deposit=False, homing="vector", noise=n, steps=steps) for n in NOISES]
    chosen = json.loads((OUT / "calib3" / "selection.json").read_text())["chosen"]
    base = {k: chosen[k] for k in ("half_life", "D", "thr", "homing", "noise")}
    base["steps"] = PAPER_STEPS
    arms = [("base", {}), ("zw", {"walk": "zw"}), ("a600", {"where": "a600"}), ("paperlayout", {"where": "paper"})]
    out = []
    for name, extra in arms:
        out.append(cond(name, **base, **extra))
        out.append(cond(f"{name}_off", **base, **extra, deposit=False))
    return out


def build(c: dict, seed: int) -> PaperSimulation:
    g = layout(c["layout"])
    on, off = THRESHOLDS[c["thr"]]
    config = SimulationConfig(n_ants=N_ANTS, steps=c["steps"], seed=seed, arena_size=g["arena"], cell_size=1,
                              nest=g["nest"], food_a=g["food_a"], food_b=g["food_b"], step_size=STEP,
                              gamma=GAMMA, theta_max=THETA, deposit_q=1, contact_radius=0.75,
                              decay=DecayConfig(half_life_steps=c["half_life"]),
                              navigation=B0Config(signal_on=on, signal_off=off))
    if c["field"] == "no_decay":
        opts = PaperOptions(walk=c["walk"], boundary="reflect", return_stride=3, after_delivery="follower",
                            deposit=c["deposit"], field="no_decay")
    else:
        opts = baseline_options(c["D"], walk=c["walk"], deposit=c["deposit"], homing=c.get("homing", "route"),
                                compass_noise=c.get("noise", 0.0))
    return PaperSimulation(config, opts, record=True)


def run_one(task):
    c, seed, out_dir = task
    start = time.perf_counter()
    sim = build(c, seed)
    g = layout(c["layout"])
    snaps, trail = {}, None
    win = checks.WINDOWS[c["steps"]]
    while sim.time < sim.config.steps:
        sim.step()
        if sim.time in SNAP_TIMES:
            snaps[sim.time] = [[round(a.position[0], 2), round(a.position[1], 2), a.role] for a in sim.ants]
        if sim.time == win["trail_time"]:
            trail = checks.trail_share(sim.field.concentration, 1.0, g["nest"], g["food_a"])
            if seed - SEEDS_START[out_dir.parent.name] < FIELD_SEEDS:
                np.savez_compressed(out_dir / f"field_{c['name']}_{seed}.npz",
                                    c=sim.field.concentration.astype(np.float32))
    events = sim.ledger.events
    pickups = [e["time"] for e in events if e["event"] == "pickup"]
    deliveries = [e["time"] for e in events if e["event"] == "delivery"]
    count, r2 = checks.transport(deliveries, window=win["transport"])
    row = {**c, "seed": seed, "windows": win, "first_pickup": checks.first_pickup(pickups, c["steps"]),
           "recruitment": checks.recruitment_share(sim.pickup_roles, window=win["recruit"]), "trail_share": trail,
           "deliveries_window": count, "r2": r2,
           **checks.window_means(sim.phi, sim.psi, sim.counts, window=win["order"]),
           "deliveries_total": len(deliveries), "pickups_total": len(pickups),
           "pickup_roles": sim.pickup_roles, "delivery_times": deliveries}
    k = SERIES_EVERY
    row["series"] = {"time": list(range(k, c["steps"] + 1, k)),
                     "phi": np.round(sim.phi[k - 1::k], 4).tolist(), "psi": np.round(sim.psi[k - 1::k], 4).tolist(),
                     "F": sim.counts[k - 1::k, 0].tolist(), "T": sim.counts[k - 1::k, 1].tolist(),
                     "f": sim.counts[k - 1::k, 2].tolist()}
    row["snapshots"] = snaps
    if sim.options.homing == "vector":
        row["search_starts"] = sim.search_starts
    row["wall_seconds"] = time.perf_counter() - start
    return row


SEEDS_START = {k: v.start for k, v in SEEDS.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=tuple(SEEDS))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    os.nice(10)
    out = OUT / args.step
    parts = out / "runs"
    parts.mkdir(parents=True, exist_ok=True)
    tasks = [(c, s, parts) for c in conditions(args.step) for s in SEEDS[args.step]]
    part = lambda c, s: parts / f"{c['name']}_{s}.json"  # noqa: E731
    todo = [t for t in tasks if not part(t[0], t[1]).exists()]
    print(f"{len(tasks) - len(todo)} of {len(tasks)} runs already done; running {len(todo)}", flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, t): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            c, s, _ = futures[future]
            tmp = part(c, s).with_suffix(".tmp")
            tmp.write_text(json.dumps(r) + "\n")
            tmp.replace(part(c, s))
            print(f"[{i}/{len(todo)}] {r['name']} {s} first={r['first_pickup']} del={r['deliveries_window']} "
                  f"psi={r['psi']:.3f} phi={r['phi']:.3f} F={r['foragers']:.0f} {r['wall_seconds']:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
