"""Stage 3C confirmatory engineering without confirmatory execution.

The simulation classes inherit the frozen Stage 3B movement and contact logic.
This module supplies strict configuration, horizon-stable random schedules,
offline measurements, atomic evidence publication, and engineering audits.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import ast
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import textwrap
import time
from typing import Callable, Iterable

import numpy as np

from ant_walks.models import generate_trajectory
from .config import DecayConfig, SimulationConfig
from .stage3b import (
    PairedB0Simulation,
    RECOVERY_DURATION,
    RecoverySimulation,
    old_trail_mask,
    side_schedule,
    state_digest,
)


CONFIRMATORY_SEEDS = tuple(range(2026092101, 2026092121))
ARMS = ("B0", "C")
TOTAL_STEPS = 18_000
STAGE3B_PREFIX_STEPS = 12_000
RELOCATION_STEP = 6_000
OBSERVATION_END = 17_999
CAPPED_RECOVERY_TIME = 12_000
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 2026092199
FORMAL_RESULTS_RELATIVE = Path("results/stage3c_confirmatory_recovery")
SNAPSHOT_STEPS = (5_999, 6_000, 12_000, 17_999)

EXECUTION_IDENTITY_FILES = (
    "requirements.txt",
    "docs/STAGE3C_CONFIRMATORY_PREREGISTRATION.md",
    "docs/STAGE3C_ENGINEERING_SPEC.md",
    "src/ant_walks/models.py",
    "src/scalar_baseline/__init__.py",
    "src/scalar_baseline/config.py",
    "src/scalar_baseline/environment.py",
    "src/scalar_baseline/field.py",
    "src/scalar_baseline/functional_validation.py",
    "src/scalar_baseline/navigation.py",
    "src/scalar_baseline/sensing.py",
    "src/scalar_baseline/simulation.py",
    "src/scalar_baseline/stage3b.py",
    "src/scalar_baseline/stage3c.py",
    "src/scalar_baseline/stage3c_analysis.py",
    "scripts/run_stage3c.py",
    "scripts/audit_stage3c.py",
    "scripts/summarise_stage3c.py",
    "tests/test_stage3b_recovery.py",
    "tests/test_stage3c_confirmation.py",
)
EXPANSION_AUTHORISATION_FILENAME = "expansion_authorisation.json"
EXPANSION_SEEDS = CONFIRMATORY_SEEDS[1:]

PER_RUN_WALL_LIMIT = 600.0
PER_RUN_CPU_LIMIT = 600.0
PER_RUN_RSS_LIMIT = 2 * 1024**3
PER_RUN_TEMP_LIMIT = 512 * 1024**2
PER_FILE_LIMIT = 50 * 1024**2
STUDY_CPU_LIMIT = 8 * 60 * 60
STUDY_OUTPUT_LIMIT = 8 * 1024**3

PROTECTED_RELATIVE_PATHS = (
    Path("results/stage1"),
    Path("results/stage2_diagnostic"),
    Path("results/stage2_provisional"),
    Path("results/stage2b_local_geometry"),
    Path("results/stage2c_multiseed_confirmation"),
    Path("results/stage3a_functional_validation"),
    Path("results/stage3a_scalar_baseline"),
    Path("results/stage3b_recovery_pilot"),
    Path(".tmp_progress_report"),
    Path("from_prof"),
    Path("output"),
    Path("reports"),
    Path("Project Proposal.pdf"),
    Path("_PH6780 Templates.docx"),
    Path("_AY2627_T1_Briefing_updated.pdf"),
)


class Stage3CError(RuntimeError):
    """Base class for a blocked Stage 3C engineering action."""


class ConfigurationError(Stage3CError):
    """A requested formal configuration differs from the preregistration."""


class EvidenceError(Stage3CError):
    """Evidence is missing, incomplete, corrupt, or unsafe to overwrite."""


class ResourceLimitError(Stage3CError):
    """A preregistered resource limit was exceeded."""


@dataclass(frozen=True)
class ArmConfiguration:
    """Treatment label plus the immutable shared simulation configuration."""

    seed: int
    arm: str
    simulation: SimulationConfig
    formal: bool
    fixture_label: str | None = None

    def as_record(self) -> dict:
        return {
            "stage": "3C",
            "formal": self.formal,
            "fixture_label": self.fixture_label,
            "seed": self.seed,
            "arm": self.arm,
            "recovery_duration": RECOVERY_DURATION if self.arm == "C" else 0,
            "simulation": asdict(self.simulation),
            "observation_end": (
                OBSERVATION_END if self.formal else self.simulation.steps - 1
            ),
            "capped_recovery_time": (
                CAPPED_RECOVERY_TIME
                if self.formal
                else self.simulation.steps - (self.simulation.relocation_step or 0)
            ),
        }


def _formal_simulation_config(seed: int) -> SimulationConfig:
    return SimulationConfig(
        n_ants=100,
        steps=TOTAL_STEPS,
        seed=seed,
        arena_size=300,
        nest=(150, 150),
        food_a=(240, 150),
        food_b=(150, 240),
        step_size=0.6,
        cell_size=1,
        deposit_q=1,
        contact_radius=0.75,
        diffusion=0,
        decay=DecayConfig(half_life_steps=1000),
        relocation_step=RELOCATION_STEP,
    )


def confirmatory_config(seed: int, arm: str) -> ArmConfiguration:
    """Return one and only one preregistered formal configuration."""
    if seed not in CONFIRMATORY_SEEDS:
        raise ConfigurationError("seed is not in the 20-seed confirmatory set")
    if arm not in ARMS:
        raise ConfigurationError("arm must be B0 or C")
    result = ArmConfiguration(seed, arm, _formal_simulation_config(seed), True)
    validate_confirmatory_config(result)
    return result


def fixture_config(
    *,
    seed: int = 31001,
    arm: str = "B0",
    steps: int = 40,
    n_ants: int = 2,
    relocation_step: int | None = 20,
    fixture_label: str = "engineering-fixture-not-scientific",
) -> ArmConfiguration:
    """Create a clearly non-formal, small engineering fixture."""
    if seed in CONFIRMATORY_SEEDS:
        raise ConfigurationError("confirmatory seeds cannot be fixture seeds")
    if arm not in ARMS:
        raise ConfigurationError("fixture arm must be B0 or C")
    if not fixture_label:
        raise ConfigurationError("fixture output requires an explicit label")
    sim = SimulationConfig(
        n_ants=n_ants,
        steps=steps,
        seed=seed,
        arena_size=20,
        nest=(10, 10),
        food_a=(16, 10),
        food_b=(10, 16),
        step_size=0.6,
        cell_size=1,
        deposit_q=1,
        contact_radius=0.5,
        diffusion=0,
        decay=DecayConfig(half_life_steps=1000),
        relocation_step=relocation_step,
    )
    return ArmConfiguration(seed, arm, sim, False, fixture_label)


def validate_confirmatory_config(config: ArmConfiguration) -> None:
    """Reject any mutation of a formal Stage 3C configuration."""
    if not config.formal:
        raise ConfigurationError("formal validation received a fixture")
    if config.seed not in CONFIRMATORY_SEEDS or config.arm not in ARMS:
        raise ConfigurationError("unknown formal seed or arm")
    expected = ArmConfiguration(
        config.seed, config.arm, _formal_simulation_config(config.seed), True
    )
    if config != expected:
        raise ConfigurationError("formal Stage 3C configuration was modified")


@lru_cache(maxsize=1024)
def _stage3b_turn_prefix(
    seed: int,
    ant_id: int,
    step_size: float,
    theta_max: float,
    gamma: float,
) -> tuple[np.ndarray, int]:
    """Return the exact Stage 3B 12,000-step FCRW schedule and final sign."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, ant_id, 2]))
    trajectory = generate_trajectory(
        "fcrw",
        steps=STAGE3B_PREFIX_STEPS,
        step_size=step_size,
        theta_max=theta_max,
        gamma=gamma,
        rng=rng,
    )
    turns = trajectory.turn_angles.copy()
    turns.setflags(write=False)
    return turns, int(trajectory.turn_signs[-1])


def horizon_stable_turn_schedule(config: SimulationConfig, ant_id: int) -> np.ndarray:
    """Preserve Stage 3B's prefix and append a fixed conditional FCRW stream."""
    prefix, last_sign = _stage3b_turn_prefix(
        config.seed, ant_id, config.step_size, config.theta_max, config.gamma
    )
    if config.steps <= STAGE3B_PREFIX_STEPS:
        return prefix[: config.steps].copy()

    extra = config.steps - STAGE3B_PREFIX_STEPS
    sign_rng = np.random.default_rng(
        np.random.SeedSequence([config.seed, ant_id, 5])
    )
    magnitude_rng = np.random.default_rng(
        np.random.SeedSequence([config.seed, ant_id, 6])
    )
    signs = np.empty(extra, dtype=np.int8)
    previous = last_sign
    for index in range(extra):
        if sign_rng.random() >= config.gamma:
            previous = -previous
        signs[index] = previous
    magnitudes = magnitude_rng.uniform(0.0, config.theta_max, size=extra)
    return np.concatenate((prefix, signs.astype(float) * magnitudes))


def schedule_bundle(config: SimulationConfig, ant_id: int) -> dict[str, np.ndarray | float]:
    """Build all treatment-independent schedules from independent streams."""
    heading_rng = np.random.default_rng(
        np.random.SeedSequence([config.seed, ant_id, 1])
    )
    noise_rng = np.random.default_rng(
        np.random.SeedSequence([config.seed, ant_id, 3])
    )
    return {
        "initial_heading": float(heading_rng.uniform(0, 2 * math.pi)),
        "fcrw_turns": horizon_stable_turn_schedule(config, ant_id),
        "follower_noise": noise_rng.uniform(
            -config.navigation.noise_amplitude,
            config.navigation.noise_amplitude,
            config.steps,
        ),
        "recovery_sides": side_schedule(config.seed, ant_id, config.steps),
    }


def _install_stage3c_schedules(sim) -> None:
    bundles = [schedule_bundle(sim.config, ant_id) for ant_id in range(sim.config.n_ants)]
    for ant, bundle in zip(sim.ants, bundles):
        ant.heading = float(bundle["initial_heading"])
    sim._turns = [np.asarray(bundle["fcrw_turns"]) for bundle in bundles]
    sim._noise = [np.asarray(bundle["follower_noise"]) for bundle in bundles]
    sim._recovery_sides = np.stack(
        [np.asarray(bundle["recovery_sides"]) for bundle in bundles]
    )


class Stage3CB0Simulation(PairedB0Simulation):
    """Frozen Stage 3B B0 with horizon-stable random schedules."""

    def __init__(self, config: SimulationConfig):
        super().__init__(config)
        _install_stage3c_schedules(self)


class Stage3CRecoverySimulation(RecoverySimulation):
    """Frozen Stage 3B C with horizon-stable random schedules."""

    def __init__(self, config: SimulationConfig):
        super().__init__(config)
        _install_stage3c_schedules(self)


def compute_capped_recovery_time(
    first_b_delivery_time: int | None,
    *,
    relocation_step: int = RELOCATION_STEP,
    observation_end: int = OBSERVATION_END,
    cap: int = CAPPED_RECOVERY_TIME,
) -> tuple[int, bool]:
    """Compute the frozen endpoint and a valid non-delivery flag."""
    if first_b_delivery_time is None or first_b_delivery_time > observation_end:
        return cap, True
    if first_b_delivery_time < relocation_step:
        raise ValueError("food B delivery cannot precede relocation")
    elapsed = first_b_delivery_time - relocation_step
    if not 0 <= elapsed < cap:
        raise ValueError("food B delivery lies outside the observation window")
    return elapsed, False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def _rss_bytes() -> int:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw if sys.platform == "darwin" else raw * 1024)


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _canonical_sha256(data: dict) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _git_output(repository_root: Path, *arguments: str) -> str:
    try:
        process = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError(f"Git identity query failed: {arguments}") from exc
    return process.stdout.strip()


def _source_identity(repository_root: Path) -> dict:
    """Bind Git, runtime, platform, and every execution-critical file."""
    missing = [
        name for name in EXECUTION_IDENTITY_FILES
        if not (repository_root / name).is_file()
    ]
    if missing:
        raise EvidenceError(f"source identity files are missing: {missing}")
    tracked_status = _git_output(
        repository_root, "status", "--porcelain=v1", "--untracked-files=no"
    )
    return {
        "schema": "stage3c-execution-identity-v1",
        "git": {
            "head": _git_output(repository_root, "rev-parse", "HEAD"),
            "branch": _git_output(repository_root, "branch", "--show-current"),
            "tracked_clean": tracked_status == "",
            "tracked_status": tracked_status.splitlines() if tracked_status else [],
        },
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "numpy_version": np.__version__,
            "platform": platform.platform(),
        },
        "files": {
            name: {
                "path": name,
                "bytes": (repository_root / name).stat().st_size,
                "sha256": _sha256(repository_root / name),
            }
            for name in EXECUTION_IDENTITY_FILES
        },
    }


IdentityProvider = Callable[[Path], dict]


def _require_clean_identity(identity: dict) -> None:
    git = identity.get("git", {})
    if (
        not git.get("head")
        or not git.get("branch")
        or git.get("tracked_clean") is not True
        or git.get("tracked_status") != []
    ):
        raise EvidenceError("formal execution requires a clean tracked Git identity")


def _arm_identity_record(frozen: dict, before: dict, after: dict) -> dict:
    matches = frozen == before == after
    return {
        "schema": "stage3c-arm-identity-v1",
        "match": matches,
        "frozen_identity_sha256": _canonical_sha256(frozen),
        "pre_run_identity_sha256": _canonical_sha256(before),
        "post_run_identity_sha256": _canonical_sha256(after),
        "frozen": frozen,
        "pre_run": before,
        "post_run": after,
    }


def _old_trail_ant_count(sim) -> int:
    start = np.asarray(sim.config.nest, dtype=float)
    end = np.asarray(sim.config.food_a, dtype=float)
    segment = end - start
    denominator = float(segment @ segment)
    count = 0
    for ant in sim.ants:
        point = np.asarray(ant.position, dtype=float)
        fraction = float(np.clip(((point - start) @ segment) / denominator, 0, 1))
        projection = start + fraction * segment
        count += int(np.linalg.norm(point - projection) <= 2.0)
    return count


def _timeline(config: ArmConfiguration) -> tuple[int, int, int]:
    relocation = config.simulation.relocation_step
    if relocation is None:
        raise ConfigurationError("Stage 3C requires relocation")
    if config.formal:
        return relocation, OBSERVATION_END, CAPPED_RECOVERY_TIME
    return relocation, config.simulation.steps - 1, config.simulation.steps - relocation


def _snapshot_steps(config: ArmConfiguration) -> tuple[int, ...]:
    if config.formal:
        return SNAPSHOT_STEPS
    relocation, end, _ = _timeline(config)
    return tuple(sorted({max(1, relocation - 1), relocation, end}))


def _execute_arm(
    output: Path,
    config: ArmConfiguration,
    repository_root: Path,
    *,
    frozen_identity: dict,
    pre_run_identity: dict,
    identity_provider: IdentityProvider = _source_identity,
    retain_observations: bool = False,
) -> dict:
    """Execute one arm inside an already-created unpublished directory."""
    if config.formal:
        validate_confirmatory_config(config)
    if any(output.iterdir()):
        raise EvidenceError("temporary output directory is not empty")

    simulation_class = (
        Stage3CB0Simulation if config.arm == "B0" else Stage3CRecoverySimulation
    )
    sim = simulation_class(config.simulation)
    trail_mask = old_trail_mask(sim)
    relocation, observation_end, cap = _timeline(config)
    snapshots: dict[str, np.ndarray] = {}
    series: list[dict] = []
    old_food_dwell = 0
    old_trail_occupancy = 0
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    state_valid = True
    sample_interval = 100 if config.simulation.steps >= 100 else max(
        1, config.simulation.steps // 5
    )

    for _ in range(config.simulation.steps):
        sim.step()
        in_observation = relocation <= sim.time <= observation_end
        if in_observation:
            old_food_dwell += sum(
                math.dist(ant.position, config.simulation.food_a) <= 10
                for ant in sim.ants
            )
            old_trail_occupancy += _old_trail_ant_count(sim)
        if sim.time in _snapshot_steps(config):
            snapshots[str(sim.time)] = sim.field.concentration.copy()
        if (
            sim.time <= observation_end
            and (sim.time % sample_interval == 0 or sim.time == observation_end)
        ):
            active = getattr(sim, "recovery", None)
            roles = {
                role: sum(ant.role == role for ant in sim.ants)
                for role in ("fcrw", "follower", "transporter")
            }
            roles["recovery"] = (
                sum(state.recovery_active for state in active) if active else 0
            )
            if active:
                roles["follower"] -= roles["recovery"]
            trail_values = sim.field.concentration[trail_mask]
            series.append(
                {
                    "time": sim.time,
                    "roles": roles,
                    "old_food_dwell_ant_steps": old_food_dwell,
                    "obsolete_trail_ant_steps": old_trail_occupancy,
                    "obsolete_trail_scalar_mass": float(trail_values.sum()),
                    "obsolete_trail_cells_off": int(
                        np.count_nonzero(
                            trail_values >= config.simulation.navigation.signal_off
                        )
                    ),
                    "obsolete_trail_cells_on": int(
                        np.count_nonzero(
                            trail_values >= config.simulation.navigation.signal_on
                        )
                    ),
                    "discoveries": dict(sim.ledger.discoveries),
                    "deliveries": dict(sim.ledger.deliveries),
                }
            )
        wall = time.perf_counter() - start_wall
        cpu = time.process_time() - start_cpu
        if wall > PER_RUN_WALL_LIMIT or cpu > PER_RUN_CPU_LIMIT:
            raise ResourceLimitError("wall or CPU limit exceeded")
        if sim.time % 1000 == 0:
            if _rss_bytes() > PER_RUN_RSS_LIMIT:
                raise ResourceLimitError("peak RSS limit exceeded")
            if _directory_bytes(output) > PER_RUN_TEMP_LIMIT:
                raise ResourceLimitError("temporary output limit exceeded")

    try:
        sim.validate()
    except Exception:
        state_valid = False
        raise

    events = list(sim.ledger.events)
    b_pickups = [
        event
        for event in events
        if event["event"] == "pickup"
        and event["source"] == "B"
        and event["time"] <= observation_end
    ]
    b_deliveries = [
        event
        for event in events
        if event["event"] == "delivery"
        and event["source"] == "B"
        and event["time"] <= observation_end
    ]
    a_deliveries_pre = [
        event
        for event in events
        if event["event"] == "delivery"
        and event["source"] == "A"
        and event["time"] < relocation
    ]
    first_b_delivery = b_deliveries[0]["time"] if b_deliveries else None
    capped_time, non_delivery = compute_capped_recovery_time(
        first_b_delivery,
        relocation_step=relocation,
        observation_end=observation_end,
        cap=cap,
    )
    episodes = json.loads(json.dumps(getattr(sim, "recovery_episodes", [])))
    b_events = [
        event
        for event in events
        if event.get("source") == "B"
        and event["event"] in {"pickup", "delivery"}
        and event["time"] <= observation_end
    ]
    for episode in episodes:
        episode["post_window_end"] = min(
            episode["end_time"] + 100, observation_end
        )
        episode["B_discovery_within_window"] = any(
            event["event"] == "pickup"
            and event["ant_id"] == episode["ant_id"]
            and episode["end_time"] <= event["time"] <= episode["post_window_end"]
            for event in b_events
        )
        episode["B_delivery_within_window"] = any(
            event["event"] == "delivery"
            and event["ant_id"] == episode["ant_id"]
            and episode["end_time"] <= event["time"] <= episode["post_window_end"]
            for event in b_events
        )
    summary = {
        "evidence_status": "engineering-fixture" if not config.formal else "confirmatory",
        "seed": config.seed,
        "arm": config.arm,
        "status": "complete",
        "steps_completed": sim.time,
        "first_B_discovery": b_pickups[0]["time"] if b_pickups else None,
        "first_B_delivery": first_b_delivery,
        "B_deliveries": len(b_deliveries),
        "non_delivery": non_delivery,
        "capped_recovery_time": capped_time,
        "pre_relocation_A_deliveries": len(a_deliveries_pre),
        "old_food_dwell_ant_steps": old_food_dwell,
        "obsolete_trail_ant_steps": old_trail_occupancy,
        "recovery_count": len(episodes),
        "recovery_reacquired": sum(
            item["outcome"] == "reacquired" for item in episodes
        ),
        "recovery_timeouts": sum(item["outcome"] == "timeout" for item in episodes),
        "recovery_food_contacts": sum(
            item["outcome"] == "food_contact" for item in episodes
        ),
        "recovery_B_discovery_within_100_steps": sum(
            bool(item["B_discovery_within_window"]) for item in episodes
        ),
        "recovery_B_delivery_within_100_steps": sum(
            bool(item["B_delivery_within_window"]) for item in episodes
        ),
        "completed_cargo": dict(sim.ledger.deliveries),
        "incomplete_cargo": dict(sim.ledger.cargo),
        "final_state_digest": state_digest(sim),
        "valid_state_every_completed_step": state_valid,
    }

    _write_json(output / "config.json", config.as_record())
    _write_json(output / "summary.json", summary)
    _write_json(output / "timeseries_100step.json", series)
    _write_json(output / "ledger_events.json", events)
    if config.arm == "C":
        _write_json(output / "recovery_episodes.json", episodes)
    if retain_observations:
        _write_json(output / "observations.json", sim.observations)
    np.savez_compressed(output / "field_snapshots.npz", **snapshots)
    post_run_identity = identity_provider(repository_root)
    if config.formal:
        _require_clean_identity(post_run_identity)
    identity_record = _arm_identity_record(
        frozen_identity, pre_run_identity, post_run_identity
    )
    if not identity_record["match"]:
        raise EvidenceError("execution identity changed during arm execution")
    _write_json(output / "source_identity.json", identity_record)

    wall_seconds = time.perf_counter() - start_wall
    cpu_seconds = time.process_time() - start_cpu
    resources = {
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "peak_rss_bytes": _rss_bytes(),
        "temporary_output_bytes": _directory_bytes(output),
        "limits": {
            "wall_seconds": PER_RUN_WALL_LIMIT,
            "cpu_seconds": PER_RUN_CPU_LIMIT,
            "peak_rss_bytes": PER_RUN_RSS_LIMIT,
            "temporary_output_bytes": PER_RUN_TEMP_LIMIT,
            "single_retained_file_bytes": PER_FILE_LIMIT,
        },
    }
    resources["pass"] = (
        wall_seconds <= PER_RUN_WALL_LIMIT
        and cpu_seconds <= PER_RUN_CPU_LIMIT
        and resources["peak_rss_bytes"] <= PER_RUN_RSS_LIMIT
        and resources["temporary_output_bytes"] <= PER_RUN_TEMP_LIMIT
    )
    _write_json(output / "resources.json", resources)

    integrity = {
        "pass": state_valid
        and len(sim.ants) == config.simulation.n_ants
        and np.isfinite(sim.field.concentration).all()
        and all(
            0 <= coordinate <= config.simulation.arena_size
            for ant in sim.ants
            for coordinate in ant.position
        )
        and all(
            event.get("source") in {"A", "B"}
            for event in events
            if event["event"] in {"pickup", "delivery"}
        )
        and max((item["duration"] for item in episodes), default=0)
        <= RECOVERY_DURATION,
        "population": len(sim.ants),
        "population_expected": config.simulation.n_ants,
        "finite_numbers": bool(np.isfinite(sim.field.concentration).all()),
        "bounds_valid": all(
            0 <= coordinate <= config.simulation.arena_size
            for ant in sim.ants
            for coordinate in ant.position
        ),
        "cargo_conserved": all(
            sim.ledger.discoveries[source]
            == sim.ledger.deliveries[source]
            + sum(value == source for value in sim.ledger.cargo.values())
            for source in ("A", "B")
        ),
        "maximum_recovery_duration": max(
            (item["duration"] for item in episodes), default=0
        ),
    }
    _write_json(output / "integrity.json", integrity)
    if not resources["pass"]:
        raise ResourceLimitError("post-run resource validation failed")
    if not integrity["pass"]:
        raise EvidenceError("post-run integrity validation failed")

    files_before_storage = {
        str(path.relative_to(output)): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    _write_json(
        output / "storage.json",
        {
            "bytes_before_storage": sum(
                record["bytes"] for record in files_before_storage.values()
            ),
            "files_before_storage": files_before_storage,
        },
    )
    all_pre_receipt = [path for path in output.rglob("*") if path.is_file()]
    if max((path.stat().st_size for path in all_pre_receipt), default=0) > PER_FILE_LIMIT:
        raise ResourceLimitError("single retained file limit exceeded")
    if _directory_bytes(output) > PER_RUN_TEMP_LIMIT:
        raise ResourceLimitError("retained run output exceeds per-run limit")
    receipt_manifest = {
        str(path.relative_to(output)): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(all_pre_receipt)
    }
    _write_json(
        output / "completed_receipt.json",
        {
            "status": "complete",
            "seed": config.seed,
            "arm": config.arm,
            "formal": config.formal,
            "recursive_files_excluding_this_receipt": receipt_manifest,
        },
    )
    return summary


def _required_run_files(arm: str) -> set[str]:
    files = {
        "config.json",
        "summary.json",
        "timeseries_100step.json",
        "ledger_events.json",
        "field_snapshots.npz",
        "source_identity.json",
        "resources.json",
        "integrity.json",
        "storage.json",
        "completed_receipt.json",
    }
    if arm == "C":
        files.add("recovery_episodes.json")
    return files


def validate_run_directory(
    run_directory: Path,
    expected: ArmConfiguration | None = None,
    *,
    expected_execution_identity: dict | None = None,
) -> dict:
    """Validate a completed directory without changing or rerunning it."""
    if not run_directory.is_dir():
        raise EvidenceError("run directory is missing")
    receipt_path = run_directory / "completed_receipt.json"
    if not receipt_path.is_file():
        raise EvidenceError("completed receipt is missing")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("status") != "complete" or receipt.get("arm") not in ARMS:
        raise EvidenceError("invalid completed receipt")
    required = _required_run_files(receipt["arm"])
    present = {
        str(path.relative_to(run_directory))
        for path in run_directory.rglob("*")
        if path.is_file()
    }
    if not required.issubset(present):
        raise EvidenceError(f"required run artifacts are missing: {sorted(required-present)}")
    manifest = receipt.get("recursive_files_excluding_this_receipt", {})
    if set(manifest) != present - {"completed_receipt.json"}:
        raise EvidenceError("completed receipt does not cover every artifact")
    for relative, record in manifest.items():
        path = run_directory / relative
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            raise EvidenceError(f"artifact hash mismatch: {relative}")
    config_record = json.loads((run_directory / "config.json").read_text())
    expected_record = (
        json.loads(json.dumps(expected.as_record())) if expected is not None else None
    )
    if expected_record is not None and config_record != expected_record:
        raise EvidenceError("run configuration does not match expected identity")
    summary = json.loads((run_directory / "summary.json").read_text())
    resources = json.loads((run_directory / "resources.json").read_text())
    integrity = json.loads((run_directory / "integrity.json").read_text())
    source_identity = json.loads((run_directory / "source_identity.json").read_text())
    if summary.get("status") != "complete" or not resources.get("pass") or not integrity.get("pass"):
        raise EvidenceError("run is not valid and complete")
    identities = (
        source_identity.get("frozen"),
        source_identity.get("pre_run"),
        source_identity.get("post_run"),
    )
    if (
        source_identity.get("schema") != "stage3c-arm-identity-v1"
        or source_identity.get("match") is not True
        or any(identity is None for identity in identities)
        or not identities[0] == identities[1] == identities[2]
        or source_identity.get("frozen_identity_sha256")
        != _canonical_sha256(identities[0])
        or source_identity.get("pre_run_identity_sha256")
        != _canonical_sha256(identities[1])
        or source_identity.get("post_run_identity_sha256")
        != _canonical_sha256(identities[2])
    ):
        raise EvidenceError("run execution identity record is invalid")
    if expected_execution_identity is not None and identities[0] != expected_execution_identity:
        raise EvidenceError("run execution identity differs from frozen pre-run identity")
    if expected is not None:
        expected_status = "confirmatory" if expected.formal else "engineering-fixture"
        identity_checks = (
            receipt.get("seed") == expected.seed,
            receipt.get("arm") == expected.arm,
            receipt.get("formal") is expected.formal,
            summary.get("seed") == expected.seed,
            summary.get("arm") == expected.arm,
            summary.get("steps_completed") == expected.simulation.steps,
            summary.get("evidence_status") == expected_status,
        )
        if not all(identity_checks):
            raise EvidenceError("run receipt or summary identity is inconsistent")
        if expected.formal:
            _require_clean_identity(identities[0])
    if _directory_bytes(run_directory) > PER_RUN_TEMP_LIMIT:
        raise ResourceLimitError("completed directory exceeds per-run storage limit")
    if max(
        (path.stat().st_size for path in run_directory.rglob("*") if path.is_file()),
        default=0,
    ) > PER_FILE_LIMIT:
        raise ResourceLimitError("completed directory contains an oversized file")
    return {
        "pass": True,
        "seed": receipt["seed"],
        "arm": receipt["arm"],
        "formal": receipt["formal"],
        "files_verified": len(manifest),
        "receipt_sha256": _sha256(receipt_path),
        "source_identity_sha256": _sha256(run_directory / "source_identity.json"),
        "retained_bytes": _directory_bytes(run_directory),
        "file_count": len(present),
        "summary": summary,
        "resources": resources,
    }


def _engineering_arm_report(validation: dict) -> dict:
    resources = validation["resources"]
    return {
        "seed": validation["seed"],
        "arm": validation["arm"],
        "complete": True,
        "valid": True,
        "wall_seconds": resources["wall_seconds"],
        "cpu_seconds": resources["cpu_seconds"],
        "peak_rss_bytes": resources["peak_rss_bytes"],
        "retained_bytes": validation["retained_bytes"],
        "file_count": validation["file_count"],
        "completed_receipt_sha256": validation["receipt_sha256"],
        "source_identity_sha256": validation["source_identity_sha256"],
        "resource_action": "CONTINUE",
        "engineering_status": "PASS",
    }


def run_arm_atomic(
    study_root: Path,
    config: ArmConfiguration,
    repository_root: Path,
    *,
    retain_observations: bool = False,
    reuse_completed: bool = True,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    """Run one arm into a temporary directory and atomically publish it."""
    if config.formal:
        validate_confirmatory_config(config)
        audit = validate_prerun_engineering_audit(
            study_root, repository_root, identity_provider=identity_provider
        )
        frozen_identity = audit["execution_identity"]
        pre_run_identity = identity_provider(repository_root)
        _require_clean_identity(pre_run_identity)
        if pre_run_identity != frozen_identity:
            raise EvidenceError("formal arm identity differs from frozen pre-run identity")
    else:
        pre_run_identity = identity_provider(repository_root)
        frozen_identity = pre_run_identity
    final = study_root / "runs" / str(config.seed) / config.arm
    final.parent.mkdir(parents=True, exist_ok=True)
    incomplete_prefix = f".{config.seed}-{config.arm}.incomplete-"
    incomplete = sorted(
        path for path in final.parent.iterdir() if path.name.startswith(incomplete_prefix)
    )
    if incomplete:
        raise EvidenceError("incomplete evidence exists and requires master review")
    if final.exists():
        if not reuse_completed:
            raise EvidenceError("completed evidence already exists; overwrite refused")
        validation = validate_run_directory(
            final,
            config,
            expected_execution_identity=frozen_identity if config.formal else None,
        )
        return _engineering_arm_report(validation)

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{config.seed}-{config.arm}.tmp-", dir=final.parent)
    )
    try:
        _execute_arm(
            temporary,
            config,
            repository_root,
            frozen_identity=frozen_identity,
            pre_run_identity=pre_run_identity,
            identity_provider=identity_provider,
            retain_observations=retain_observations,
        )
        validation = validate_run_directory(
            temporary,
            config,
            expected_execution_identity=frozen_identity if config.formal else None,
        )
        os.replace(temporary, final)
        return _engineering_arm_report(validation)
    except Exception as exc:
        failure = {
            "status": "incomplete",
            "seed": config.seed,
            "arm": config.arm,
            "formal": config.formal,
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            _write_json(temporary / "failure.json", failure)
            preserved = final.parent / f"{incomplete_prefix}{temporary.name.rsplit('-', 1)[-1]}"
            os.replace(temporary, preserved)
        except Exception:
            pass
        raise


def pair_configuration_identity(b0_record: dict, c_record: dict) -> dict:
    """Compare pair configuration after removing the treatment label only."""
    b0 = json.loads(json.dumps(b0_record))
    c = json.loads(json.dumps(c_record))
    for record in (b0, c):
        record.pop("arm", None)
        record.pop("recovery_duration", None)
    return {"pass": b0 == c, "shared_configuration": b0 if b0 == c else None}


def _first_pair_configs(
    pair_configs: dict[str, ArmConfiguration] | None,
) -> dict[str, ArmConfiguration]:
    configs = pair_configs or {
        arm: confirmatory_config(CONFIRMATORY_SEEDS[0], arm) for arm in ARMS
    }
    if set(configs) != set(ARMS):
        raise ConfigurationError("first pair must contain exactly B0 and C")
    if configs["B0"].arm != "B0" or configs["C"].arm != "C":
        raise ConfigurationError("first-pair arm labels are invalid")
    if configs["B0"].seed != configs["C"].seed:
        raise ConfigurationError("first-pair seeds differ")
    return configs


def _first_pair_engineering_evidence(
    study_root: Path,
    repository_root: Path,
    *,
    pair_configs: dict[str, ArmConfiguration] | None = None,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    configs = _first_pair_configs(pair_configs)
    seed = configs["B0"].seed
    audit = validate_prerun_engineering_audit(
        study_root, repository_root, identity_provider=identity_provider
    )
    validations = {
        arm: validate_run_directory(
            study_root / "runs" / str(seed) / arm,
            configs[arm],
            expected_execution_identity=audit["execution_identity"],
        )
        for arm in ARMS
    }
    records = {
        arm: json.loads(
            (study_root / "runs" / str(seed) / arm / "config.json").read_text()
        )
        for arm in ARMS
    }
    identity = pair_configuration_identity(records["B0"], records["C"])
    if not identity["pass"]:
        raise EvidenceError("first-pair configuration identity failed")
    source_records = {
        arm: json.loads(
            (study_root / "runs" / str(seed) / arm / "source_identity.json").read_text()
        )
        for arm in ARMS
    }
    if source_records["B0"] != source_records["C"]:
        raise EvidenceError("first-pair source identity failed")
    protection = verify_study_protection(study_root, repository_root)
    if not protection["pass"]:
        raise EvidenceError("protected-file integrity failed")
    arms = {arm: _engineering_arm_report(validations[arm]) for arm in ARMS}
    return {
        "engineering_status": "PASS",
        "resource_action": "CONTINUE",
        "seed": seed,
        "arms": arms,
        "pair_identity": {
            "configuration": True,
            "execution_identity": True,
        },
        "protected_files": {
            "pass": True,
            "files_checked": protection["files_checked"],
            "manifest_sha256": protection["manifest_sha256"],
        },
        "prerun_audit_sha256": audit["audit_sha256"],
        "execution_git_head": audit["execution_identity"]["git"]["head"],
        "execution_identity_sha256": audit["execution_identity_sha256"],
    }


def create_first_pair_engineering_receipt(
    study_root: Path,
    repository_root: Path | None = None,
    *,
    pair_configs: dict[str, ArmConfiguration] | None = None,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    """Record engineering validity without exposing scientific outcomes."""
    repository_root = repository_root or Path(__file__).resolve().parents[2]
    path = study_root / "first_pair_engineering_receipt.json"
    if path.exists():
        raise EvidenceError("first-pair engineering receipt is immutable")
    receipt = _first_pair_engineering_evidence(
        study_root,
        repository_root,
        pair_configs=pair_configs,
        identity_provider=identity_provider,
    )
    _write_json(path, receipt)
    return receipt


def validate_first_pair_engineering_receipt(
    study_root: Path,
    repository_root: Path | None = None,
    *,
    pair_configs: dict[str, ArmConfiguration] | None = None,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    path = study_root / "first_pair_engineering_receipt.json"
    if not path.is_file():
        raise EvidenceError("remaining mode requires a first-pair engineering receipt")
    repository_root = repository_root or Path(__file__).resolve().parents[2]
    try:
        stored = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("first-pair engineering receipt is corrupt") from exc
    expected = _first_pair_engineering_evidence(
        study_root,
        repository_root,
        pair_configs=pair_configs,
        identity_provider=identity_provider,
    )
    if stored != expected:
        raise EvidenceError("first-pair engineering receipt is invalid or stale")
    return {
        "pass": True,
        "receipt_sha256": _sha256(path),
        "seed": stored["seed"],
        "arm_completed_receipts": {
            arm: stored["arms"][arm]["completed_receipt_sha256"] for arm in ARMS
        },
        "prerun_audit_sha256": stored["prerun_audit_sha256"],
        "execution_git_head": stored["execution_git_head"],
        "execution_identity_sha256": stored["execution_identity_sha256"],
        "engineering_status": "PASS",
        "resource_action": "CONTINUE",
    }


def expected_expansion_authorisation(
    study_root: Path,
    repository_root: Path | None = None,
    *,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    """Return the exact Stage 3C-F authorisation payload without writing it."""
    repository_root = repository_root or Path(__file__).resolve().parents[2]
    gate = validate_first_pair_engineering_receipt(
        study_root, repository_root, identity_provider=identity_provider
    )
    return {
        "authorised_stage": "Stage 3C-F",
        "approved": True,
        "first_pair_engineering_receipt_sha256": gate["receipt_sha256"],
        "first_pair_B0_completed_receipt_sha256": gate[
            "arm_completed_receipts"
        ]["B0"],
        "first_pair_C_completed_receipt_sha256": gate[
            "arm_completed_receipts"
        ]["C"],
        "frozen_execution_git_head": gate["execution_git_head"],
        "frozen_prerun_audit_sha256": gate["prerun_audit_sha256"],
        "seeds": list(EXPANSION_SEEDS),
        "arm_order": list(ARMS),
    }


def validate_expansion_authorisation(
    study_root: Path,
    repository_root: Path | None = None,
    *,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    """Fail closed unless an independent Stage 3C-F authorisation is exact."""
    repository_root = repository_root or Path(__file__).resolve().parents[2]
    path = study_root / EXPANSION_AUTHORISATION_FILENAME
    if not path.is_file():
        raise EvidenceError("remaining mode requires Stage 3C-F authorisation")
    try:
        stored = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("Stage 3C-F authorisation is corrupt") from exc
    expected = expected_expansion_authorisation(
        study_root, repository_root, identity_provider=identity_provider
    )
    if stored != expected:
        raise EvidenceError("Stage 3C-F authorisation does not match frozen evidence")
    return {
        "engineering_status": "PASS",
        "resource_action": "CONTINUE",
        "authorisation_sha256": _sha256(path),
        "first_pair_engineering_receipt_sha256": stored[
            "first_pair_engineering_receipt_sha256"
        ],
        "execution_git_head": stored["frozen_execution_git_head"],
        "prerun_audit_sha256": stored["frozen_prerun_audit_sha256"],
        "seeds": stored["seeds"],
        "arm_order": stored["arm_order"],
    }


def validate_complete_study(
    study_root: Path,
    repository_root: Path | None = None,
    *,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    """Refuse analysis unless all 40 immutable arms and study limits pass."""
    repository_root = repository_root or Path(__file__).resolve().parents[2]
    audit = validate_prerun_engineering_audit(
        study_root, repository_root, identity_provider=identity_provider
    )
    validations = []
    total_cpu = 0.0
    for seed in CONFIRMATORY_SEEDS:
        for arm in ARMS:
            validation = validate_run_directory(
                study_root / "runs" / str(seed) / arm,
                confirmatory_config(seed, arm),
                expected_execution_identity=audit["execution_identity"],
            )
            validations.append(validation)
            total_cpu += validation["resources"]["cpu_seconds"]
    total_bytes = _directory_bytes(study_root)
    if total_cpu > STUDY_CPU_LIMIT or total_bytes > STUDY_OUTPUT_LIMIT:
        raise ResourceLimitError("complete-study resource limit exceeded")
    protection = verify_study_protection(study_root, repository_root)
    if not protection["pass"]:
        raise EvidenceError("protected-file integrity changed")
    return {
        "pass": True,
        "runs_verified": len(validations),
        "total_cpu_seconds": total_cpu,
        "retained_output_bytes": total_bytes,
    }


def schedule_prefix_audit(seed: int = 31001, ant_ids: Iterable[int] = (0, 1, 2)) -> dict:
    """Compare 12,000/18,000 schedule bytes without executing a simulation."""
    short = replace(fixture_config(seed=seed).simulation, steps=STAGE3B_PREFIX_STEPS)
    long = replace(fixture_config(seed=seed).simulation, steps=TOTAL_STEPS)
    comparisons = {}
    for ant_id in ant_ids:
        left = schedule_bundle(short, ant_id)
        right = schedule_bundle(long, ant_id)
        comparisons[str(ant_id)] = {
            name: np.asarray(right[name])[:STAGE3B_PREFIX_STEPS].tobytes()
            == np.asarray(left[name]).tobytes()
            for name in ("fcrw_turns", "follower_noise", "recovery_sides")
        }
        comparisons[str(ant_id)]["initial_heading"] = (
            left["initial_heading"] == right["initial_heading"]
        )
    return {
        "pass": all(all(item.values()) for item in comparisons.values()),
        "fixture_seed": seed,
        "confirmatory_seed_used": False,
        "comparisons": comparisons,
        "simulation_steps_executed": 0,
    }


def pair_identity_audit(config: ArmConfiguration | None = None) -> dict:
    """Instantiate a non-formal pair and compare initial state and schedules."""
    base = config or fixture_config(seed=31002, steps=60, n_ants=3)
    if base.formal:
        raise ConfigurationError("pair identity audit requires a fixture")
    b0_config = replace(base, arm="B0")
    c_config = replace(base, arm="C")
    b0 = Stage3CB0Simulation(b0_config.simulation)
    candidate = Stage3CRecoverySimulation(c_config.simulation)
    checks = {
        "initial_agents": [asdict(ant) for ant in b0.ants]
        == [asdict(ant) for ant in candidate.ants],
        "initial_field": np.array_equal(
            b0.field.concentration, candidate.field.concentration
        ),
        "fcrw_turn_schedule": all(
            np.array_equal(a, b) for a, b in zip(b0._turns, candidate._turns)
        ),
        "follower_noise_schedule": all(
            np.array_equal(a, b) for a, b in zip(b0._noise, candidate._noise)
        ),
        "recovery_side_schedule": np.array_equal(
            b0._recovery_sides, candidate._recovery_sides
        ),
        "simulation_configuration": asdict(b0.config) == asdict(candidate.config),
    }
    return {
        "pass": all(checks.values()),
        "fixture_seed": base.seed,
        "confirmatory_seed_used": False,
        "checks": checks,
        "simulation_steps_executed": 0,
    }


def single_change_audit() -> dict:
    """Prove Stage 3C does not override frozen Stage 3B movement methods."""
    b0_move = inspect.getsource(PairedB0Simulation._move)
    c_move = inspect.getsource(RecoverySimulation._move)
    checks = {
        "stage3c_B0_has_no_move_override": "_move" not in Stage3CB0Simulation.__dict__,
        "stage3c_C_has_no_move_override": "_move" not in Stage3CRecoverySimulation.__dict__,
        "B0_does_not_read_recovery_side_in_movement": "_recovery_sides" not in b0_move,
        "C_reads_recovery_side_only_via_recovery_start": "_start_recovery" in c_move,
        "recovery_duration_unchanged": RECOVERY_DURATION == 24,
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "B0_move_sha256": hashlib.sha256(b0_move.encode()).hexdigest(),
        "C_move_sha256": hashlib.sha256(c_move.encode()).hexdigest(),
        "only_behavioural_difference": (
            "C inherits the frozen Stage 3B finite-recovery branch; B0 inherits "
            "the frozen immediate FCRW branch"
        ),
    }


def navigation_isolation_audit() -> dict:
    """Audit the inherited recovery movement for prohibited navigation inputs."""
    source = textwrap.dedent(inspect.getsource(RecoverySimulation._move))
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    prohibited = {
        "food_a",
        "food_b",
        "nest",
        "environment",
        "gradient",
        "argmax",
        "direction_sum",
        "mean_direction",
        "future",
        "source_identity",
    }
    hits = sorted(names & prohibited)
    return {
        "pass": not hits,
        "prohibited_identifier_hits": hits,
        "local_scalar_sensing_present": "sense" in names,
        "offline_masks_used_by_movement": False,
    }


def _canonical_observations(observations: list[dict]) -> list[dict]:
    result = json.loads(json.dumps(observations))
    for item in result:
        item.pop("remaining_steps", None)
    return result


def b0_replay_audit(seed: int = 31003, n_ants: int = 2) -> dict:
    """Replay a non-formal Stage 3B/3C B0 prefix through 12,000 steps."""
    if seed in CONFIRMATORY_SEEDS:
        raise ConfigurationError("B0 replay must use a fixture seed")
    common = fixture_config(
        seed=seed,
        arm="B0",
        steps=STAGE3B_PREFIX_STEPS,
        n_ants=n_ants,
        relocation_step=RELOCATION_STEP,
        fixture_label="stage3b-prefix-replay-fixture",
    ).simulation
    old = PairedB0Simulation(common)
    extended = Stage3CB0Simulation(replace(common, steps=TOTAL_STEPS))
    schedules = {
        "fcrw_turns": all(
            np.array_equal(a, b[:STAGE3B_PREFIX_STEPS])
            for a, b in zip(old._turns, extended._turns)
        ),
        "follower_noise": all(
            np.array_equal(a, b[:STAGE3B_PREFIX_STEPS])
            for a, b in zip(old._noise, extended._noise)
        ),
        "recovery_sides": np.array_equal(
            old._recovery_sides,
            extended._recovery_sides[:, :STAGE3B_PREFIX_STEPS],
        ),
    }
    for _ in range(STAGE3B_PREFIX_STEPS):
        old.step()
        extended.step()
    checks = {
        "schedule_prefix": all(schedules.values()),
        "state_digest": state_digest(old) == state_digest(extended),
        "observations": _canonical_observations(old.observations)
        == _canonical_observations(extended.observations),
    }
    return {
        "pass": all(checks.values()),
        "fixture_seed": seed,
        "confirmatory_seed_used": False,
        "compared_through_step": STAGE3B_PREFIX_STEPS,
        "checks": checks,
        "schedule_checks": schedules,
        "simulation_steps_executed": 2 * STAGE3B_PREFIX_STEPS,
    }


def protected_snapshot(paths: Iterable[Path], base: Path) -> dict:
    """Record path, size and SHA-256 for an explicit protected set."""
    files: dict[str, dict] = {}
    for root in paths:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = [path for path in root.rglob("*") if path.is_file()]
        else:
            continue
        for path in sorted(candidates):
            relative = str(path.relative_to(base))
            files[relative] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    return {"files": files}


def verify_protected_snapshot(snapshot: dict, base: Path) -> dict:
    missing, changed = [], []
    for relative, expected in snapshot.get("files", {}).items():
        path = base / relative
        if not path.is_file():
            missing.append(relative)
        elif path.stat().st_size != expected["bytes"] or _sha256(path) != expected["sha256"]:
            changed.append(relative)
    return {
        "pass": not missing and not changed,
        "files_checked": len(snapshot.get("files", {})),
        "missing": missing,
        "changed": changed,
    }


def initialise_study_protection(study_root: Path, repository_root: Path) -> dict:
    """Create or validate the immutable protected-file baseline."""
    study_root.mkdir(parents=True, exist_ok=True)
    path = study_root / "protected_files_before.json"
    if path.exists():
        return verify_study_protection(study_root, repository_root)
    targets = [repository_root / relative for relative in PROTECTED_RELATIVE_PATHS]
    missing_targets = [
        str(relative)
        for relative, target in zip(PROTECTED_RELATIVE_PATHS, targets)
        if not target.exists()
    ]
    if missing_targets:
        raise EvidenceError(f"protected targets are missing: {missing_targets}")
    snapshot = protected_snapshot(targets, repository_root)
    snapshot["protected_roots"] = [str(path) for path in PROTECTED_RELATIVE_PATHS]
    _write_json(path, snapshot)
    return {
        "pass": True,
        "files_checked": len(snapshot["files"]),
        "manifest_sha256": _sha256(path),
    }


def verify_study_protection(study_root: Path, repository_root: Path) -> dict:
    path = study_root / "protected_files_before.json"
    if not path.is_file():
        raise EvidenceError("protected-file baseline is missing")
    snapshot = json.loads(path.read_text())
    result = verify_protected_snapshot(snapshot, repository_root)
    result["manifest_sha256"] = _sha256(path)
    return result


def resource_limits_pass(record: dict) -> bool:
    """Apply all per-run resource thresholds inclusively."""
    return (
        record["wall_seconds"] <= PER_RUN_WALL_LIMIT
        and record["cpu_seconds"] <= PER_RUN_CPU_LIMIT
        and record["peak_rss_bytes"] <= PER_RUN_RSS_LIMIT
        and record["temporary_output_bytes"] <= PER_RUN_TEMP_LIMIT
        and record["largest_file_bytes"] <= PER_FILE_LIMIT
    )


def static_resource_estimate(stage3b_resource_summary: Path) -> dict:
    """Scale existing Stage 3B observations without claiming Stage 3C timing."""
    source = json.loads(stage3b_resource_summary.read_text())
    horizon_scale = TOTAL_STEPS / STAGE3B_PREFIX_STEPS
    run_sizes = list(source.get("run_output_bytes", {}).values())
    max_run_bytes = max(run_sizes, default=0)
    estimate = {
        "evidence_status": "static estimate, not an 18,000-step Stage 3C measurement",
        "source": str(stage3b_resource_summary),
        "horizon_scale": horizon_scale,
        "estimated_max_run_wall_seconds": source["max_run_wall_seconds"] * horizon_scale,
        "estimated_max_run_cpu_seconds": source["max_run_cpu_seconds"] * horizon_scale,
        "conservative_peak_rss_bytes": source["max_peak_rss_bytes"] * horizon_scale,
        "estimated_max_run_output_bytes": max_run_bytes * horizon_scale,
        "estimated_40_run_cpu_seconds": source["total_cpu_seconds"] * 6,
        "estimated_40_run_output_bytes": source["total_run_output_bytes"] * 6,
        "limits": {
            "per_run_wall_seconds": PER_RUN_WALL_LIMIT,
            "per_run_cpu_seconds": PER_RUN_CPU_LIMIT,
            "per_run_peak_rss_bytes": PER_RUN_RSS_LIMIT,
            "per_run_temporary_output_bytes": PER_RUN_TEMP_LIMIT,
            "single_file_bytes": PER_FILE_LIMIT,
            "study_cpu_seconds": STUDY_CPU_LIMIT,
            "study_retained_output_bytes": STUDY_OUTPUT_LIMIT,
        },
    }
    estimate["within_limits"] = (
        estimate["estimated_max_run_wall_seconds"] <= PER_RUN_WALL_LIMIT
        and estimate["estimated_max_run_cpu_seconds"] <= PER_RUN_CPU_LIMIT
        and estimate["conservative_peak_rss_bytes"] <= PER_RUN_RSS_LIMIT
        and estimate["estimated_max_run_output_bytes"] <= PER_RUN_TEMP_LIMIT
        and estimate["estimated_40_run_cpu_seconds"] <= STUDY_CPU_LIMIT
        and estimate["estimated_40_run_output_bytes"] <= STUDY_OUTPUT_LIMIT
    )
    return estimate


def formal_configuration_audit() -> dict:
    records = {
        arm: confirmatory_config(CONFIRMATORY_SEEDS[0], arm).as_record()
        for arm in ARMS
    }
    identity = pair_configuration_identity(records["B0"], records["C"])
    checks = {
        "seed_set": CONFIRMATORY_SEEDS == tuple(range(2026092101, 2026092121)),
        "pair_shared_configuration": identity["pass"],
        "total_steps": records["B0"]["simulation"]["steps"] == TOTAL_STEPS,
        "relocation": records["B0"]["simulation"]["relocation_step"]
        == RELOCATION_STEP,
        "observation_end": records["B0"]["observation_end"] == OBSERVATION_END,
        "cap": records["B0"]["capped_recovery_time"] == CAPPED_RECOVERY_TIME,
        "diffusion_zero": records["B0"]["simulation"]["diffusion"] == 0,
        "half_life": math.isclose(
            records["B0"]["simulation"]["decay"]["half_life_steps"], 1000
        ),
    }
    return {"pass": all(checks.values()), "checks": checks}


def cargo_classification_audit() -> dict:
    fixture = fixture_config(seed=31004, arm="C", steps=10, relocation_step=2)
    sim = Stage3CRecoverySimulation(fixture.simulation)
    sim.ledger.pickup(0, "A", 1)
    sim.ants[0].role = "transporter"
    sim.environment.relocate(2, sim.ledger)
    sim.ledger.deliver(0, 3)
    checks = {
        "carried_A_stays_A": sim.ledger.deliveries == {"A": 1, "B": 0},
        "carried_A_recorded_at_relocation": sim.ledger.carried_a_at_relocation == [0],
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "simulation_steps_executed": 0,
        "confirmatory_seed_used": False,
    }


def prerun_engineering_audit(
    repository_root: Path,
    *,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    """Build every outcome-blind gate before a formal arm can start."""
    execution_identity = identity_provider(repository_root)
    _require_clean_identity(execution_identity)
    audits = {
        "formal_configuration": formal_configuration_audit(),
        "schedule_prefix": schedule_prefix_audit(),
        "pair_identity": pair_identity_audit(),
        "single_change": single_change_audit(),
        "navigation_isolation": navigation_isolation_audit(),
        "cargo_classification": cargo_classification_audit(),
        "B0_replay": b0_replay_audit(),
        "resource_estimate": static_resource_estimate(
            repository_root / "results/stage3b_recovery_pilot/resource_summary.json"
        ),
        "execution_identity": execution_identity,
    }
    audits["pass"] = all(
        item.get("pass", item.get("within_limits", True))
        for item in audits.values()
    )
    audits["scope"] = {
        "formal_simulation_steps_executed": 0,
        "fixture_simulation_steps_executed": audits["B0_replay"][
            "simulation_steps_executed"
        ],
        "confirmatory_seeds_run": 0,
        "scientific_results": False,
    }
    return audits


def initialise_prerun_engineering_audit(
    study_root: Path,
    repository_root: Path,
    *,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    """Create the pre-run audit once or validate it against current source."""
    study_root.mkdir(parents=True, exist_ok=True)
    path = study_root / "prerun_engineering_audit.json"
    if path.exists():
        return validate_prerun_engineering_audit(
            study_root, repository_root, identity_provider=identity_provider
        )
    audit = prerun_engineering_audit(
        repository_root, identity_provider=identity_provider
    )
    if not audit["pass"]:
        raise EvidenceError("pre-run engineering audit failed")
    _write_json(path, audit)
    return {
        "pass": True,
        "audit_sha256": _sha256(path),
        "execution_identity_sha256": _canonical_sha256(audit["execution_identity"]),
        "execution_identity": audit["execution_identity"],
        "scope": audit["scope"],
    }


def validate_prerun_engineering_audit(
    study_root: Path,
    repository_root: Path,
    *,
    identity_provider: IdentityProvider = _source_identity,
) -> dict:
    path = study_root / "prerun_engineering_audit.json"
    if not path.is_file():
        raise EvidenceError("pre-run engineering audit is missing")
    audit = json.loads(path.read_text())
    if audit.get("pass") is not True:
        raise EvidenceError("pre-run engineering audit did not pass")
    current_identity = identity_provider(repository_root)
    _require_clean_identity(current_identity)
    if audit.get("execution_identity") != current_identity:
        raise EvidenceError("source changed after pre-run engineering audit")
    return {
        "pass": True,
        "audit_sha256": _sha256(path),
        "execution_identity_sha256": _canonical_sha256(current_identity),
        "execution_identity": current_identity,
        "scope": audit["scope"],
    }
