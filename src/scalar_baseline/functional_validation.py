"""Observation-only research-scale B0 validation; no changes to steering."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time

import numpy as np

from .config import DecayConfig, SimulationConfig
from .navigation import navigate
from .sensing import sense
from .simulation import Simulation

SEEDS = (2026091701, 2026091702, 2026091703, 2026091704, 2026091705)


def research_config(seed: int) -> SimulationConfig:
    if seed not in SEEDS:
        raise ValueError("seed must be one of the five preregistered seeds")
    return SimulationConfig(n_ants=100, steps=12000, seed=seed, arena_size=300,
                            nest=(150, 150), food_a=(240, 150), food_b=(150, 240),
                            step_size=0.6, diffusion=0, decay=DecayConfig(half_life_steps=1000),
                            relocation_step=None)


def connected(mask: np.ndarray, start: tuple, end: tuple) -> bool:
    """Metric-only 8-neighbour connectivity; never called by navigation."""
    if not mask[start] or not mask[end]:
        return False
    queue, seen = deque([start]), {start}
    while queue:
        x, y = queue.popleft()
        if (x, y) == end:
            return True
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                point = (x + dx, y + dy)
                if (dx or dy) and 0 <= point[0] < mask.shape[0] and 0 <= point[1] < mask.shape[1]:
                    if mask[point] and point not in seen:
                        seen.add(point)
                        queue.append(point)
    return False


def route_detectability(values: list, threshold: float) -> dict:
    longest = current = 0
    for value in values:
        current = current + 1 if value < threshold else 0
        longest = max(longest, current)
    return {"points": len(values), "detectable_fraction": sum(v >= threshold for v in values) / len(values) if values else None,
            "longest_undetectable_run_points": longest}


class ObservedSimulation(Simulation):
    """Adds a separate observer ledger; delegates every movement/contact to B0."""

    def __init__(self, config: SimulationConfig):
        super().__init__(config)
        self.observations = []
        self.ever_deposited = set()
        self.episodes = {}
        self.first_returner = None
        self.first_return_route = []
        self.first_delivery_pending = False
        self.follower_steps = 0
        self.follower_low_signal_steps = 0

    def _end_episode(self, ant_id: int, reason: str, position: tuple) -> dict:
        episode = self.episodes.pop(ant_id)
        result = {"event": "follower_episode_end", "time": self.time, "ant_id": ant_id,
                  "reason": reason, "duration_steps": self.time - episode["time"] + 1,
                  "distance_travelled": episode["distance"],
                  "displacement": math.dist(episode["position"], position),
                  "verified_recruitment": episode["verified"]}
        self.observations.append(result)
        return result

    def _move(self, ant) -> None:
        old_role, position = ant.role, ant.position
        if old_role != "transporter":
            left, right = sense(self.field, ant.position, ant.heading, self.config.navigation)
        else:
            self.ever_deposited.add(ant.ant_id)
        super()._move(ant)
        if old_role == "fcrw" and ant.role == "follower":
            verified = ant.ant_id not in self.ever_deposited
            counterfactual = navigate(heading=0, left=0, right=0, role="fcrw", low_steps=0,
                                      fcrw_turn=float(self._turns[ant.ant_id][self.time - 1]),
                                      noise=float(self._noise[ant.ant_id][self.time - 1]), config=self.config.navigation)
            assert max(left, right) >= self.config.navigation.signal_on and counterfactual.role == "fcrw"
            self.observations.append({"event": "recruitment", "time": self.time, "ant_id": ant.ant_id,
                                      "left": left, "right": right, "position": position, "heading_after": ant.heading,
                                      "verified_other_ant_trail": verified, "zero_field_role": counterfactual.role})
            self.episodes[ant.ant_id] = {"time": self.time, "position": position, "verified": verified, "distance": 0.0}
        if ant.ant_id in self.episodes:
            self.episodes[ant.ant_id]["distance"] += math.dist(position, ant.position)
            if ant.role == "fcrw":
                self._end_episode(ant.ant_id, "signal_loss", ant.position)
        if ant.role == "follower":
            self.follower_steps += 1
            self.follower_low_signal_steps += int(max(left, right) < self.config.navigation.signal_off)
        if old_role == "transporter" and ant.ant_id == self.first_returner:
            self.first_return_route.append(ant.position)

    def _contacts(self, ant) -> None:
        role_before = ant.role
        old_event_count = len(self.ledger.events)
        super()._contacts(ant)
        if len(self.ledger.events) == old_event_count:
            return
        event = dict(self.ledger.events[-1])
        event["role_before_contact"] = role_before
        if event["event"] == "pickup":
            event["own_path_vertices"] = len(ant.path)
            event["remaining_steps"] = self.config.steps - self.time
            if self.first_returner is None:
                self.first_returner = ant.ant_id
            if role_before == "follower":
                event["follower_episode"] = self._end_episode(ant.ant_id, "food_contact", ant.position)
        if event["event"] == "delivery" and sum(self.ledger.deliveries.values()) == 1:
            self.first_delivery_pending = True
            # First returner need not be first deliverer; name diagnostics exactly.
            event["first_pickup_ant_is_first_deliverer"] = ant.ant_id == self.first_returner
        self.observations.append(event)


def field_metrics(sim: Simulation) -> dict:
    result = {"time": sim.time, "field_sum": float(sim.field.concentration.sum()),
              "positive_cells": int(np.count_nonzero(sim.field.concentration))}
    for label, threshold in (("on", sim.config.navigation.signal_on), ("off", sim.config.navigation.signal_off)):
        mask = sim.field.concentration >= threshold
        result[label] = {"threshold": threshold, "detectable_cells": int(mask.sum()),
                         "nest_food_centre_cells_connected_8": connected(mask, sim.field._index(sim.config.nest), sim.field._index(sim.config.food_a))}
    return result


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def run_seed(output: Path, config: SimulationConfig) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    start, cpu_start = time.perf_counter(), time.process_time()
    write_json(output / "config.json", asdict(config))
    sim = ObservedSimulation(config)
    checkpoints = []
    status, error = "complete", None
    try:
        for _ in range(config.steps):
            sim.step()
            if sim.first_delivery_pending:
                metrics = field_metrics(sim)
                values = [sim.field.sample(p) for p in sim.first_return_route]
                metrics["first_pickup_ant_route"] = {"ant_id": sim.first_returner,
                    "on": route_detectability(values, config.navigation.signal_on),
                    "off": route_detectability(values, config.navigation.signal_off)}
                write_json(output / "first_delivery_field_metrics.json", metrics)
                np.savez_compressed(output / "field_first_delivery.npz", concentration=sim.field.concentration)
                sim.first_delivery_pending = False
            if sim.time % 100 == 0:
                if time.perf_counter() - start > 600 or time.process_time() - cpu_start > 600:
                    raise RuntimeError("resource_cap: wall/CPU >600 seconds")
            if sim.time % 1000 == 0:
                metrics = field_metrics(sim)
                metrics.update({"discoveries": dict(sim.ledger.discoveries), "deliveries": dict(sim.ledger.deliveries),
                                "raw_recruitments": sum(e["event"] == "recruitment" for e in sim.observations),
                                "roles": {r: sum(a.role == r for a in sim.ants) for r in ("fcrw", "follower", "transporter")}})
                checkpoints.append(metrics)
                write_json(output / "progress.json", {"time": sim.time, "wall_seconds": time.perf_counter() - start, "metrics": metrics})
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
                if rss > 2 * 1024 ** 3 or sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) > 512 * 1024 ** 2:
                    raise RuntimeError("resource_cap: RSS/disk")
                print(json.dumps({"seed": config.seed, "step": sim.time, "deliveries": sim.ledger.deliveries,
                                  "recruitments": metrics["raw_recruitments"], "wall_seconds": round(time.perf_counter() - start, 2)}), flush=True)
    except Exception as exc:
        status, error = "incomplete", f"{type(exc).__name__}: {exc}"
    recruits = [e for e in sim.observations if e["event"] == "recruitment"]
    verified = [e for e in recruits if e["verified_other_ant_trail"]]
    pickups = [e for e in sim.observations if e["event"] == "pickup"]
    deliveries = [e for e in sim.observations if e["event"] == "delivery"]
    arrivals = [e for e in pickups if e["role_before_contact"] == "follower"]
    write_json(output / "events.json", sim.observations)
    write_json(output / "checkpoints.json", checkpoints)
    np.savez_compressed(output / "field_final.npz", concentration=sim.field.concentration)
    write_json(output / "final_agents.json", [{"ant_id": a.ant_id, "position": a.position, "heading": a.heading,
                                               "role": a.role, "path_vertices": len(a.path)} for a in sim.ants])
    write_json(output / "ledger.json", asdict(sim.ledger))
    summary = {"seed": config.seed, "status": status, "error": error, "steps_completed": sim.time,
               "first_discovery": pickups[0] if pickups else None,
               "first_delivery": deliveries[0] if deliveries else None,
               "first_raw_recruitment": recruits[0] if recruits else None,
               "first_verified_recruitment": verified[0] if verified else None,
               "raw_recruitments": len(recruits), "verified_recruitments": len(verified),
               "unique_verified_recruits": len({e["ant_id"] for e in verified}),
               "follower_food_arrivals": len(arrivals), "first_follower_food_arrival": arrivals[0] if arrivals else None,
               "verified_episode_food_arrivals": sum(e["follower_episode"]["verified_recruitment"] for e in arrivals),
               "discoveries": sim.ledger.discoveries, "deliveries": sim.ledger.deliveries,
               "follower_steps": sim.follower_steps, "follower_low_signal_steps": sim.follower_low_signal_steps,
               "final_field": field_metrics(sim),
               "valid_state_every_completed_step": status == "complete",
               "functional_success": status == "complete" and bool(pickups and deliveries and verified),
               "wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu_start,
               "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)}
    write_json(output / "summary.json", summary)
    files = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in output.iterdir() if p.is_file()}
    write_json(output / "storage.json", {"bytes_excluding_this_manifest": sum(v["bytes"] for v in files.values()), "files": files})
    print(json.dumps(summary, indent=2), flush=True)
    return summary
