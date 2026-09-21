"""Finite local recovery C and observation-only paired relocation runner."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time

import numpy as np

from .config import DecayConfig, SimulationConfig
from .functional_validation import ObservedSimulation, SEEDS, field_metrics
from .navigation import navigate
from .sensing import sense

RECOVERY_DURATION = 24
SEGMENT_STEPS = 6
OFFSETS = tuple(math.radians(x) for x in (15, -30, 45, -60))
POST_EPISODE_WINDOW = 100
SNAPSHOT_STEPS = (5999, 6000, 7000, 9000, 12000)


def paired_config(seed: int) -> SimulationConfig:
    if seed not in SEEDS:
        raise ValueError("seed must be one of the five frozen exploratory seeds")
    return SimulationConfig(n_ants=100, steps=12000, seed=seed, arena_size=300,
                            nest=(150, 150), food_a=(240, 150), food_b=(150, 240),
                            step_size=0.6, cell_size=1, deposit_q=1, contact_radius=0.75,
                            diffusion=0, decay=DecayConfig(half_life_steps=1000),
                            relocation_step=6000)


def shortest_angle(target: float, current: float) -> float:
    return (target - current + math.pi) % (2 * math.pi) - math.pi


def side_schedule(seed: int, ant_id: int, steps: int) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence([seed, ant_id, 4]))
    return np.where(rng.random(steps) < 0.5, -1, 1).astype(np.int8)


@dataclass
class RecoveryState:
    recovery_active: bool = False
    recovery_step: int = 0
    recovery_anchor_heading: float | None = None
    recovery_initial_side: int | None = None
    last_reliable_heading: float | None = None


class PairedB0Simulation(ObservedSimulation):
    """Frozen B0 plus an unused side schedule for common-randomness auditing."""

    def __init__(self, config: SimulationConfig):
        super().__init__(config)
        self._recovery_sides = np.stack([side_schedule(config.seed, i, config.steps)
                                         for i in range(config.n_ants)])


class RecoverySimulation(ObservedSimulation):
    """C changes only the follower signal-loss branch."""

    def __init__(self, config: SimulationConfig):
        super().__init__(config)
        self._recovery_sides = np.stack([side_schedule(config.seed, i, config.steps)
                                         for i in range(config.n_ants)])
        self.recovery = [RecoveryState() for _ in range(config.n_ants)]
        self.recovery_episodes: list[dict] = []
        self._open_recovery: dict[int, dict] = {}
        self.anchor_fallbacks = 0

    def _start_recovery(self, ant, state: RecoveryState) -> None:
        fallback = state.last_reliable_heading is None
        anchor = ant.heading if fallback else state.last_reliable_heading
        side = int(self._recovery_sides[ant.ant_id, self.time - 1])
        state.recovery_active = True
        state.recovery_step = 0
        state.recovery_anchor_heading = float(anchor)
        state.recovery_initial_side = side
        self.anchor_fallbacks += int(fallback)
        self._open_recovery[ant.ant_id] = {
            "seed": self.config.seed, "ant_id": ant.ant_id,
            "start_time": self.time, "start_position": ant.position,
            "anchor_heading": float(anchor), "initial_side": side,
            "anchor_fallback": fallback, "distance": 0.0,
        }

    def _finish_recovery(self, ant, state: RecoveryState, outcome: str,
                         concentration: float | None = None) -> None:
        episode = self._open_recovery.pop(ant.ant_id)
        episode.update({"end_time": self.time, "duration": state.recovery_step,
                        "outcome": outcome,
                        "reacquisition_position": ant.position if outcome == "reacquired" else None,
                        "reacquisition_concentration": concentration if outcome == "reacquired" else None,
                        "movement_distance": episode.pop("distance"),
                        "post_window_end": min(self.config.steps, self.time + POST_EPISODE_WINDOW),
                        "B_discovery_within_window": False,
                        "B_delivery_within_window": False})
        self.recovery_episodes.append(episode)
        state.recovery_active = False
        state.recovery_step = 0
        state.recovery_anchor_heading = None
        state.recovery_initial_side = None

    def _move(self, ant) -> None:
        state = self.recovery[ant.ant_id]
        old_role, position = ant.role, ant.position
        if old_role == "transporter":
            self.ever_deposited.add(ant.ant_id)
            super()._move(ant)
            return

        left, right = sense(self.field, ant.position, ant.heading, self.config.navigation)
        signal = max(left, right)
        noise = float(self._noise[ant.ant_id][self.time - 1])

        if state.recovery_active:
            if signal >= self.config.navigation.signal_on:
                decision = navigate(heading=ant.heading, left=left, right=right, role="follower",
                                    low_steps=0, fcrw_turn=float(self._turns[ant.ant_id][self.time - 1]),
                                    noise=noise, config=self.config.navigation)
                ant.heading, ant.role, ant.low_steps = decision.heading, decision.role, decision.low_steps
                state.last_reliable_heading = ant.heading
                self._finish_recovery(ant, state, "reacquired", signal)
            else:
                segment = min(3, state.recovery_step // SEGMENT_STEPS)
                target = state.recovery_anchor_heading + state.recovery_initial_side * OFFSETS[segment]
                correction = max(-self.config.navigation.max_turn,
                                 min(self.config.navigation.max_turn, shortest_angle(target, ant.heading)))
                turn = max(-self.config.navigation.max_turn,
                           min(self.config.navigation.max_turn, correction + noise))
                ant.heading = (ant.heading + turn) % (2 * math.pi)
                state.recovery_step += 1
                if state.recovery_step == RECOVERY_DURATION:
                    ant.role, ant.low_steps = "fcrw", 0
                    self._finish_recovery(ant, state, "timeout")
        else:
            previous_low = ant.low_steps
            decision = navigate(heading=ant.heading, left=left, right=right, role=ant.role,
                                low_steps=ant.low_steps, fcrw_turn=float(self._turns[ant.ant_id][self.time - 1]),
                                noise=noise, config=self.config.navigation)
            if old_role == "follower" and signal < self.config.navigation.signal_off \
                    and previous_low + 1 >= self.config.navigation.loss_steps:
                # Discard B0's same-step FCRW decision and execute recovery movement.
                ant.low_steps = 0
                self._start_recovery(ant, state)
                target = state.recovery_anchor_heading + state.recovery_initial_side * OFFSETS[0]
                correction = max(-self.config.navigation.max_turn,
                                 min(self.config.navigation.max_turn, shortest_angle(target, ant.heading)))
                turn = max(-self.config.navigation.max_turn,
                           min(self.config.navigation.max_turn, correction + noise))
                ant.heading = (ant.heading + turn) % (2 * math.pi)
                ant.role = "follower"
                state.recovery_step = 1
            else:
                ant.heading, ant.role, ant.low_steps = decision.heading, decision.role, decision.low_steps
                if ant.role == "follower" and signal >= self.config.navigation.signal_off:
                    state.last_reliable_heading = ant.heading
                if old_role == "fcrw" and ant.role == "follower":
                    verified = ant.ant_id not in self.ever_deposited
                    self.observations.append({"event": "recruitment", "time": self.time,
                                              "ant_id": ant.ant_id, "left": left, "right": right,
                                              "position": position, "heading_after": ant.heading,
                                              "verified_other_ant_trail": verified, "zero_field_role": "fcrw"})
                    self.episodes[ant.ant_id] = {"time": self.time, "position": position,
                                                 "verified": verified, "distance": 0.0}

        ant.position = tuple(max(0.0, min(self.config.arena_size, p + self.config.step_size * d))
                             for p, d in zip(ant.position, (math.cos(ant.heading), math.sin(ant.heading))))
        ant.path.append(ant.position)
        if ant.ant_id in self._open_recovery:
            self._open_recovery[ant.ant_id]["distance"] += math.dist(position, ant.position)
        if ant.ant_id in self.episodes:
            self.episodes[ant.ant_id]["distance"] += math.dist(position, ant.position)
            if ant.role == "fcrw":
                self._end_episode(ant.ant_id, "signal_loss", ant.position)
        if ant.role == "follower":
            self.follower_steps += 1
            self.follower_low_signal_steps += int(signal < self.config.navigation.signal_off)

    def _contacts(self, ant) -> None:
        active_before = self.recovery[ant.ant_id].recovery_active
        role_before = ant.role
        count = len(self.ledger.events)
        # Call the original contact implementation, bypassing ObservedSimulation's observer.
        super(ObservedSimulation, self)._contacts(ant)
        if len(self.ledger.events) == count:
            return
        event = dict(self.ledger.events[-1])
        event["role_before_contact"] = "recovery" if active_before else role_before
        if event["event"] == "pickup":
            event["own_path_vertices"] = len(ant.path)
            event["remaining_steps"] = self.config.steps - self.time
            if self.first_returner is None:
                self.first_returner = ant.ant_id
            if active_before:
                self._finish_recovery(ant, self.recovery[ant.ant_id], "food_contact")
            elif role_before == "follower" and ant.ant_id in self.episodes:
                event["follower_episode"] = self._end_episode(ant.ant_id, "food_contact", ant.position)
        if event["event"] == "delivery" and sum(self.ledger.deliveries.values()) == 1:
            self.first_delivery_pending = True
        self.observations.append(event)
        if event["source"] == "B":
            key = "B_discovery_within_window" if event["event"] == "pickup" else "B_delivery_within_window"
            for episode in self.recovery_episodes:
                if episode["ant_id"] == ant.ant_id and episode["end_time"] <= self.time <= episode["post_window_end"]:
                    episode[key] = True

    def validate(self) -> None:
        super().validate()
        for ant, state in zip(self.ants, self.recovery):
            if state.recovery_active:
                if ant.role != "follower" or not 1 <= state.recovery_step < RECOVERY_DURATION:
                    raise AssertionError("invalid recovery state")
                if state.recovery_initial_side not in {-1, 1}:
                    raise AssertionError("invalid recovery side")


def old_trail_mask(sim) -> np.ndarray:
    n = sim.field.concentration.shape[0]
    centres = (np.indices((n, n)).transpose(1, 2, 0) + 0.5) * sim.config.cell_size
    a = np.asarray(sim.config.nest); b = np.asarray(sim.config.food_a); ab = b - a
    t = np.clip(((centres - a) @ ab) / (ab @ ab), 0, 1)
    distance = np.linalg.norm(centres - (a + t[..., None] * ab), axis=-1)
    return distance <= 2.0


def state_digest(sim) -> dict:
    payload = [{"position": a.position, "heading": a.heading, "role": a.role,
                "low_steps": a.low_steps, "path": a.path,
                "cargo": sim.ledger.cargo.get(a.ant_id)} for a in sim.ants]
    return {"agents_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "field_sha256": hashlib.sha256(sim.field.concentration.tobytes()).hexdigest(),
            "events_sha256": hashlib.sha256(json.dumps(sim.ledger.events, sort_keys=True).encode()).hexdigest(),
            "discoveries": dict(sim.ledger.discoveries), "deliveries": dict(sim.ledger.deliveries)}


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def run_arm(output: Path, config: SimulationConfig, arm: str, *, retain_events: bool) -> dict:
    if arm not in {"B0", "C"}:
        raise ValueError("arm must be B0 or C")
    output.mkdir(parents=True, exist_ok=False)
    sim = PairedB0Simulation(config) if arm == "B0" else RecoverySimulation(config)
    mask = old_trail_mask(sim)
    start, cpu_start = time.perf_counter(), time.process_time()
    series, snapshots = [], {}
    old_food_dwell = 0
    status, error = "complete", None
    try:
        for _ in range(config.steps):
            sim.step()
            if sim.time >= config.relocation_step:
                old_food_dwell += sum(math.dist(a.position, config.food_a) <= 10 for a in sim.ants)
            if sim.time in SNAPSHOT_STEPS:
                snapshots[str(sim.time)] = sim.field.concentration.copy()
            if sim.time % 100 == 0:
                if time.perf_counter() - start > 600 or time.process_time() - cpu_start > 600:
                    raise RuntimeError("resource_cap: wall/CPU >600 seconds")
                active = getattr(sim, "recovery", None)
                roles = {r: sum(a.role == r for a in sim.ants) for r in ("fcrw", "follower", "transporter")}
                roles["recovery"] = sum(s.recovery_active for s in active) if active else 0
                if active:
                    roles["follower"] -= roles["recovery"]
                old_values = sim.field.concentration[mask]
                series.append({"time": sim.time, "roles": roles,
                               "ants_near_old_A": sum(math.dist(a.position, config.food_a) <= 10 for a in sim.ants),
                               "old_food_dwell_ant_steps": old_food_dwell,
                               "active_cells_off": int(np.count_nonzero(sim.field.concentration >= config.navigation.signal_off)),
                               "active_cells_on": int(np.count_nonzero(sim.field.concentration >= config.navigation.signal_on)),
                               "old_trail_cells_off": int(np.count_nonzero(old_values >= config.navigation.signal_off)),
                               "old_trail_intensity": float(old_values.sum()),
                               "discoveries": dict(sim.ledger.discoveries), "deliveries": dict(sim.ledger.deliveries)})
            if sim.time % 1000 == 0:
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
                current_bytes = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
                if rss > 2 * 1024**3 or current_bytes > 512 * 1024**2:
                    raise RuntimeError("resource_cap: RSS/disk")
                print(json.dumps({"seed": config.seed, "arm": arm, "step": sim.time,
                                  "A": sim.ledger.deliveries["A"], "B": sim.ledger.deliveries["B"],
                                  "wall": round(time.perf_counter()-start, 2)}), flush=True)
    except Exception as exc:
        status, error = "incomplete", f"{type(exc).__name__}: {exc}"

    ledger_events = sim.ledger.events
    pickups_a = [e for e in ledger_events if e["event"] == "pickup" and e["source"] == "A"]
    pickups_b = [e for e in ledger_events if e["event"] == "pickup" and e["source"] == "B"]
    deliveries_a = [e for e in ledger_events if e["event"] == "delivery" and e["source"] == "A"]
    deliveries_b = [e for e in ledger_events if e["event"] == "delivery" and e["source"] == "B"]
    recruitments = [e for e in sim.observations if e.get("event") == "recruitment" and e["time"] < 6000]
    arrivals_a = [e for e in sim.observations if e.get("event") == "pickup" and e["source"] == "A"
                  and e.get("role_before_contact") == "follower"]
    episodes = getattr(sim, "recovery_episodes", [])
    capped = min(6000, deliveries_b[0]["time"] - 6000) if deliveries_b else 6000
    summary = {"seed": config.seed, "arm": arm, "status": status, "error": error,
               "steps_completed": sim.time, "first_A_discovery": pickups_a[0]["time"] if pickups_a else None,
               "first_A_delivery": deliveries_a[0]["time"] if deliveries_a else None,
               "pre_relocation_A_deliveries": sum(e["time"] < 6000 for e in deliveries_a),
               "pre_relocation_verified_recruitments": sum(e.get("verified_other_ant_trail", False) for e in recruitments),
               "pre_relocation_follower_food_arrivals": len(arrivals_a),
               "pre_relocation_follower_episode_lengths": [e.get("follower_episode", {}).get("duration_steps") for e in arrivals_a if e.get("follower_episode")],
               "pre_relocation_delivery_rate_per_1000": sum(e["time"] < 6000 for e in deliveries_a) / 6,
               "pre_relocation_recovery_episodes": sum(e["start_time"] < 6000 for e in episodes),
               "first_B_discovery": pickups_b[0]["time"] if pickups_b else None,
               "first_B_delivery": deliveries_b[0]["time"] if deliveries_b else None,
               "B_not_discovered": not pickups_b, "B_not_delivered": not deliveries_b,
               "B_deliveries": len(deliveries_b), "capped_recovery_time": capped,
               "old_food_dwell_ant_steps": old_food_dwell,
               "recovery_episodes": len(episodes),
               "recovery_reacquired": sum(e["outcome"] == "reacquired" for e in episodes),
               "recovery_timeouts": sum(e["outcome"] == "timeout" for e in episodes),
               "recovery_food_contacts": sum(e["outcome"] == "food_contact" for e in episodes),
               "recovery_reacquisition_rate": (sum(e["outcome"] == "reacquired" for e in episodes) / len(episodes)) if episodes else None,
               "anchor_fallbacks": getattr(sim, "anchor_fallbacks", 0),
               "completed_cargo": dict(sim.ledger.deliveries), "incomplete_cargo": dict(sim.ledger.cargo),
               "final_field": field_metrics(sim), "final_state_digest": state_digest(sim),
               "wall_seconds": time.perf_counter()-start, "cpu_seconds": time.process_time()-cpu_start,
               "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
               "valid_state_every_completed_step": status == "complete"}
    write_json(output / "config.json", {**asdict(config), "arm": arm, "recovery_duration": RECOVERY_DURATION if arm == "C" else 0})
    write_json(output / "summary.json", summary)
    write_json(output / "timeseries_100step.json", series)
    write_json(output / "ledger_events.json", ledger_events)
    if arm == "C":
        write_json(output / "recovery_episodes.json", episodes)
    if retain_events:
        write_json(output / "observations.json", sim.observations)
    np.savez_compressed(output / "field_snapshots.npz", **snapshots)
    files = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in output.iterdir() if p.is_file()}
    write_json(output / "storage.json", {"bytes_excluding_manifest": sum(x["bytes"] for x in files.values()), "files": files})
    largest = max([p.stat().st_size for p in output.iterdir() if p.is_file()], default=0)
    if largest > 50 * 1024**2:
        raise RuntimeError("output file exceeded 50 MiB")
    return summary
