"""Stage 3D matched-lifetime hard-cutoff execution and evidence gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time
from typing import Callable, Iterable

import numpy as np

from .config import DecayConfig, SimulationConfig, half_life_to_rate, matched_cutoff_steps
from .stage3b import RECOVERY_DURATION, old_trail_mask, state_digest
from .stage3c import (
    ARMS,
    CAPPED_RECOVERY_TIME,
    CONFIRMATORY_SEEDS,
    OBSERVATION_END,
    RELOCATION_STEP,
    TOTAL_STEPS,
    Stage3CB0Simulation,
    Stage3CRecoverySimulation,
    _old_trail_ant_count,
    compute_capped_recovery_time,
    confirmatory_config,
    schedule_bundle,
    validate_run_directory as validate_stage3c_run_directory,
    verify_study_protection as verify_stage3c_protection,
)


SEEDS = CONFIRMATORY_SEEDS
CUTOFF_STEPS = 2000
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 2026092299
FORMAL_RESULTS_RELATIVE = Path("results/stage3d_decay_law_ablation")
STAGE3C_RESULTS_RELATIVE = Path("results/stage3c_confirmatory_recovery")
SNAPSHOT_STEPS = (5_999, 6_000, 12_000, 17_999)

PER_RUN_WALL_LIMIT = 600.0
PER_RUN_CPU_LIMIT = 600.0
PER_RUN_RSS_LIMIT = 2 * 1024**3
PER_RUN_TEMP_LIMIT = 512 * 1024**2
PER_FILE_LIMIT = 50 * 1024**2
STUDY_CPU_LIMIT = 28_800.0
STUDY_OUTPUT_LIMIT = 8 * 1024**3

EXECUTION_IDENTITY_FILES = (
    "requirements.txt",
    "docs/STAGE3D_DECAY_LAW_PREREGISTRATION.md",
    "docs/STAGE3D_ENGINEERING_SPEC.md",
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
    "src/scalar_baseline/stage3d.py",
    "src/scalar_baseline/stage3d_analysis.py",
    "scripts/run_stage3d.py",
    "tests/test_stage3d_decay_law.py",
    "run_stage3d.sh",
)

PROTECTED_RELATIVE_PATHS = (
    Path("results/stage1"),
    Path("results/stage2_diagnostic"),
    Path("results/stage2_provisional"),
    Path("results/stage2b_local_geometry"),
    Path("results/stage2c_multiseed_confirmation"),
    Path("results/stage3a_functional_validation"),
    Path("results/stage3a_scalar_baseline"),
    Path("results/stage3b_recovery_pilot"),
    STAGE3C_RESULTS_RELATIVE,
    Path(".tmp_progress_report"),
    Path("from_prof"),
    Path("output"),
    Path("reports"),
    Path("Project Proposal.pdf"),
    Path("_PH6780 Templates.docx"),
    Path("_AY2627_T1_Briefing_updated.pdf"),
)


class Stage3DError(RuntimeError):
    """Base error for a blocked Stage 3D action."""


class ConfigurationError(Stage3DError):
    """The requested arm differs from the frozen configuration."""


class EvidenceError(Stage3DError):
    """Required evidence is missing, inconsistent, or unsafe to overwrite."""


class ResourceLimitError(Stage3DError):
    """A frozen resource limit was reached."""


@dataclass(frozen=True)
class ArmConfiguration:
    seed: int
    arm: str
    simulation: SimulationConfig
    formal: bool
    fixture_label: str | None = None

    def as_record(self) -> dict:
        return {
            "stage": "3D",
            "evidence_status": "prospective_exploratory_extension",
            "formal": self.formal,
            "fixture_label": self.fixture_label,
            "seed": self.seed,
            "arm": self.arm,
            "decay_law": "hard_cutoff_cell_timer",
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
        decay=DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=CUTOFF_STEPS),
        relocation_step=RELOCATION_STEP,
    )


def formal_config(seed: int, arm: str) -> ArmConfiguration:
    if seed not in SEEDS:
        raise ConfigurationError("seed is outside the frozen Stage 3D set")
    if arm not in ARMS:
        raise ConfigurationError("arm must be B0 or C")
    config = ArmConfiguration(seed, arm, _formal_simulation_config(seed), True)
    validate_config(config)
    return config


def fixture_config(
    *, seed: int = 32001, arm: str = "B0", steps: int = 60,
    n_ants: int = 3, relocation_step: int | None = 30,
) -> ArmConfiguration:
    if arm not in ARMS:
        raise ConfigurationError("arm must be B0 or C")
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
        contact_radius=0.75,
        diffusion=0,
        decay=DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=CUTOFF_STEPS),
        relocation_step=relocation_step,
    )
    return ArmConfiguration(seed, arm, sim, False, "stage3d-test-fixture")


def validate_config(config: ArmConfiguration) -> None:
    if not config.formal:
        return
    if config.seed not in SEEDS or config.arm not in ARMS:
        raise ConfigurationError("formal seed or arm is not frozen")
    expected = ArmConfiguration(
        config.seed, config.arm, _formal_simulation_config(config.seed), True
    )
    if config != expected:
        raise ConfigurationError("formal configuration differs from preregistration")


def matched_lifetime_audit() -> dict:
    calculated = matched_cutoff_steps(1, 0.25, half_life_to_rate(1000))
    return {
        "pass": calculated == CUTOFF_STEPS,
        "formula": "ceil(ln(1/0.25)/(ln(2)/1000))",
        "calculated_cutoff_steps": calculated,
        "frozen_cutoff_steps": CUTOFF_STEPS,
        "matches_only": "single-deposit theoretical lifetime to signal_off",
    }


def _normalised_simulation_record(config: SimulationConfig) -> dict:
    return json.loads(json.dumps(asdict(config)))


def decay_single_change_audit(seed: int, arm: str) -> dict:
    exponential = _normalised_simulation_record(confirmatory_config(seed, arm).simulation)
    cutoff = _normalised_simulation_record(formal_config(seed, arm).simulation)
    exp_decay = exponential.pop("decay")
    cut_decay = cutoff.pop("decay")
    return {
        "pass": exponential == cutoff
        and exp_decay["mode"] == "exponential"
        and math.isclose(exp_decay["half_life_steps"], 1000.0)
        and cut_decay == {
            "mode": "hard_cutoff_cell_timer",
            "half_life_steps": None,
            "decay_rate": None,
            "cutoff_steps": CUTOFF_STEPS,
        },
        "seed": seed,
        "arm": arm,
        "shared_non_decay_configuration": exponential if exponential == cutoff else None,
        "exponential_decay": exp_decay,
        "hard_cutoff_decay": cut_decay,
    }


def pair_single_change_audit(seed: int) -> dict:
    b0 = formal_config(seed, "B0").as_record()
    candidate = formal_config(seed, "C").as_record()
    for record in (b0, candidate):
        record.pop("arm")
        record.pop("recovery_duration")
    return {
        "pass": b0 == candidate,
        "seed": seed,
        "only_mechanism_change": "24-step finite recovery search",
        "shared_configuration": b0 if b0 == candidate else None,
    }


def schedule_identity_audit(seed: int = SEEDS[0], ant_ids: Iterable[int] = (0, 1, 2)) -> dict:
    exponential = confirmatory_config(seed, "B0").simulation
    cutoff = formal_config(seed, "B0").simulation
    comparisons = {}
    for ant_id in ant_ids:
        left = schedule_bundle(exponential, ant_id)
        right = schedule_bundle(cutoff, ant_id)
        comparisons[str(ant_id)] = {
            "initial_heading": left["initial_heading"] == right["initial_heading"],
            "fcrw_turns": np.array_equal(left["fcrw_turns"], right["fcrw_turns"]),
            "follower_noise": np.array_equal(
                left["follower_noise"], right["follower_noise"]
            ),
            "recovery_sides": np.array_equal(
                left["recovery_sides"], right["recovery_sides"]
            ),
        }
    return {
        "pass": all(all(values.values()) for values in comparisons.values()),
        "seed": seed,
        "comparisons": comparisons,
        "simulation_steps_executed": 0,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(data) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _write_json(path: Path, data, *, exclusive: bool = False) -> None:
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _directory_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _rss_bytes() -> int:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw if sys.platform == "darwin" else raw * 1024)


def _git_output(repository_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError(f"Git identity query failed: {arguments}") from exc
    return result.stdout.strip()


def source_identity(repository_root: Path) -> dict:
    missing = [name for name in EXECUTION_IDENTITY_FILES if not (repository_root / name).is_file()]
    if missing:
        raise EvidenceError(f"execution identity files missing: {missing}")
    status = _git_output(
        repository_root, "status", "--porcelain=v1", "--untracked-files=no"
    )
    return {
        "schema": "stage3d-execution-identity-v1",
        "git": {
            "head": _git_output(repository_root, "rev-parse", "HEAD"),
            "branch": _git_output(repository_root, "branch", "--show-current"),
            "tracked_clean": status == "",
            "tracked_status": status.splitlines() if status else [],
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
        raise EvidenceError("formal execution requires a clean tracked identity")


def _file_snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def protected_snapshot(repository_root: Path) -> dict:
    files = {}
    roots = []
    for relative in PROTECTED_RELATIVE_PATHS:
        path = repository_root / relative
        if not path.exists():
            continue
        roots.append(str(relative))
        if path.is_file():
            files[str(relative)] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        else:
            for item in sorted(path.rglob("*")):
                if item.is_file():
                    files[str(item.relative_to(repository_root))] = {
                        "bytes": item.stat().st_size,
                        "sha256": _sha256(item),
                    }
    return {"schema": "stage3d-protected-files-v1", "roots": roots, "files": files}


def verify_protected_snapshot(snapshot: dict, repository_root: Path) -> dict:
    current = protected_snapshot(repository_root)
    return {
        "pass": snapshot == current,
        "expected_file_count": len(snapshot.get("files", {})),
        "current_file_count": len(current.get("files", {})),
        "snapshot_sha256": _canonical_sha256(snapshot),
        "current_sha256": _canonical_sha256(current),
    }


def validate_stage3c_reuse(repository_root: Path) -> dict:
    study_root = repository_root / STAGE3C_RESULTS_RELATIVE
    if not study_root.is_dir():
        raise EvidenceError("Stage 3C evidence root is missing")
    audit_path = study_root / "prerun_engineering_audit.json"
    if not audit_path.is_file():
        raise EvidenceError("Stage 3C pre-run identity is missing")
    stage3c_audit = json.loads(audit_path.read_text())
    execution_identity = stage3c_audit.get("execution_identity")
    if execution_identity is None:
        raise EvidenceError("Stage 3C frozen execution identity is missing")
    validations = []
    total_cpu = 0.0
    for seed in SEEDS:
        for arm in ARMS:
            validation = validate_stage3c_run_directory(
                study_root / "runs" / str(seed) / arm,
                confirmatory_config(seed, arm),
                expected_execution_identity=execution_identity,
            )
            validations.append(validation)
            total_cpu += validation["resources"]["cpu_seconds"]
    protection = verify_stage3c_protection(study_root, repository_root)
    if not protection["pass"]:
        raise EvidenceError("Stage 3C protected evidence no longer validates")
    analysis_path = study_root / "confirmatory_analysis.json"
    analysis = json.loads(analysis_path.read_text())
    if analysis.get("decision") != "FAIL" or analysis.get("valid") is not True:
        raise EvidenceError("Stage 3C frozen decision is not valid FAIL evidence")
    if len(validations) != 40:
        raise EvidenceError("Stage 3C does not contain 40 valid reusable arms")
    snapshot = _file_snapshot(study_root)
    return {
        "pass": True,
        "source": str(STAGE3C_RESULTS_RELATIVE),
        "runs_verified": len(validations),
        "total_cpu_seconds": total_cpu,
        "retained_output_bytes": _directory_bytes(study_root),
        "decision": analysis["decision"],
        "analysis_sha256": _sha256(analysis_path),
        "file_count": len(snapshot),
        "files": snapshot,
        "files_sha256": _canonical_sha256(snapshot),
    }


def initialise_prerun_audit(
    study_root: Path, repository_root: Path,
    *, identity_provider: IdentityProvider = source_identity,
) -> dict:
    if study_root.exists():
        raise EvidenceError("Stage 3D formal root already exists")
    identity = identity_provider(repository_root)
    _require_clean_identity(identity)
    protection = protected_snapshot(repository_root)
    reuse = validate_stage3c_reuse(repository_root)
    lifetime = matched_lifetime_audit()
    decay_audits = [
        decay_single_change_audit(seed, arm) for seed in SEEDS for arm in ARMS
    ]
    pair_audits = [pair_single_change_audit(seed) for seed in SEEDS]
    schedule = schedule_identity_audit()
    if not (
        lifetime["pass"]
        and all(item["pass"] for item in decay_audits)
        and all(item["pass"] for item in pair_audits)
        and schedule["pass"]
    ):
        raise EvidenceError("Stage 3D pre-run engineering audit failed")
    study_root.mkdir(parents=True, exist_ok=False)
    _write_json(study_root / "protected_files_before.json", protection, exclusive=True)
    _write_json(study_root / "stage3c_reuse_receipt.json", reuse, exclusive=True)
    audit = {
        "schema": "stage3d-prerun-audit-v1",
        "pass": True,
        "execution_identity": identity,
        "protected_snapshot_sha256": _canonical_sha256(protection),
        "stage3c_reuse_receipt_sha256": _sha256(
            study_root / "stage3c_reuse_receipt.json"
        ),
        "matched_lifetime": lifetime,
        "decay_single_change_audits": decay_audits,
        "pair_single_change_audits": pair_audits,
        "schedule_identity_audit": schedule,
        "seed_order": list(SEEDS),
        "arm_order": list(ARMS),
        "worker_count": 1,
        "execution_mode": "sequential_local_cpu",
        "scientific_stdout_before_complete": False,
    }
    _write_json(study_root / "prerun_engineering_audit.json", audit, exclusive=True)
    return audit


def validate_prerun_audit(
    study_root: Path, repository_root: Path,
    *, identity_provider: IdentityProvider = source_identity,
) -> dict:
    audit_path = study_root / "prerun_engineering_audit.json"
    protection_path = study_root / "protected_files_before.json"
    reuse_path = study_root / "stage3c_reuse_receipt.json"
    if not all(path.is_file() for path in (audit_path, protection_path, reuse_path)):
        raise EvidenceError("Stage 3D pre-run audit files are incomplete")
    audit = json.loads(audit_path.read_text())
    protection = json.loads(protection_path.read_text())
    reuse = json.loads(reuse_path.read_text())
    current_identity = identity_provider(repository_root)
    _require_clean_identity(current_identity)
    if audit.get("pass") is not True or audit.get("execution_identity") != current_identity:
        raise EvidenceError("Stage 3D execution identity changed")
    if audit.get("protected_snapshot_sha256") != _canonical_sha256(protection):
        raise EvidenceError("protected snapshot identity mismatch")
    if audit.get("stage3c_reuse_receipt_sha256") != _sha256(reuse_path):
        raise EvidenceError("Stage 3C reuse receipt hash mismatch")
    current_reuse = validate_stage3c_reuse(repository_root)
    if current_reuse != reuse:
        raise EvidenceError("reused Stage 3C evidence changed")
    protection_check = verify_protected_snapshot(protection, repository_root)
    if not protection_check["pass"]:
        raise EvidenceError("protected evidence changed")
    return audit


def _timeline(config: ArmConfiguration) -> tuple[int, int, int]:
    relocation = config.simulation.relocation_step
    if relocation is None:
        raise ConfigurationError("Stage 3D requires food relocation")
    if config.formal:
        return relocation, OBSERVATION_END, CAPPED_RECOVERY_TIME
    return relocation, config.simulation.steps - 1, config.simulation.steps - relocation


def _snapshot_steps(config: ArmConfiguration) -> tuple[int, ...]:
    if config.formal:
        return SNAPSHOT_STEPS
    relocation, end, _ = _timeline(config)
    return tuple(sorted({max(1, relocation - 1), relocation, end}))


def _simulate(config: ArmConfiguration) -> dict:
    simulation_class = Stage3CB0Simulation if config.arm == "B0" else Stage3CRecoverySimulation
    sim = simulation_class(config.simulation)
    trail_mask = old_trail_mask(sim)
    relocation, observation_end, cap = _timeline(config)
    snapshots = {}
    series = []
    old_food_dwell = 0
    old_trail_occupancy = 0
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    sample_interval = 100 if config.simulation.steps >= 100 else max(1, config.simulation.steps // 5)

    for _ in range(config.simulation.steps):
        sim.step()
        if relocation <= sim.time <= observation_end:
            old_food_dwell += sum(
                math.dist(ant.position, config.simulation.food_a) <= 10
                for ant in sim.ants
            )
            old_trail_occupancy += _old_trail_ant_count(sim)
        if sim.time in _snapshot_steps(config):
            snapshots[str(sim.time)] = sim.field.concentration.copy()
        if sim.time <= observation_end and (
            sim.time % sample_interval == 0 or sim.time == observation_end
        ):
            active = getattr(sim, "recovery", None)
            roles = {
                role: sum(ant.role == role for ant in sim.ants)
                for role in ("fcrw", "follower", "transporter")
            }
            roles["recovery"] = sum(s.recovery_active for s in active) if active else 0
            if active:
                roles["follower"] -= roles["recovery"]
            trail_values = sim.field.concentration[trail_mask]
            series.append({
                "time": sim.time,
                "roles": roles,
                "old_food_dwell_ant_steps": old_food_dwell,
                "obsolete_trail_ant_steps": old_trail_occupancy,
                "obsolete_trail_scalar_mass": float(trail_values.sum()),
                "obsolete_trail_cells_off": int(np.count_nonzero(
                    trail_values >= config.simulation.navigation.signal_off
                )),
                "obsolete_trail_cells_on": int(np.count_nonzero(
                    trail_values >= config.simulation.navigation.signal_on
                )),
                "discoveries": dict(sim.ledger.discoveries),
                "deliveries": dict(sim.ledger.deliveries),
            })
        wall = time.perf_counter() - start_wall
        cpu = time.process_time() - start_cpu
        if wall > PER_RUN_WALL_LIMIT or cpu > PER_RUN_CPU_LIMIT:
            raise ResourceLimitError("per-arm wall or CPU limit exceeded")
        if sim.time % 1000 == 0 and _rss_bytes() > PER_RUN_RSS_LIMIT:
            raise ResourceLimitError("per-arm RSS limit exceeded")

    sim.validate()
    events = list(sim.ledger.events)
    b_pickups = [e for e in events if e["event"] == "pickup" and e["source"] == "B" and e["time"] <= observation_end]
    b_deliveries = [e for e in events if e["event"] == "delivery" and e["source"] == "B" and e["time"] <= observation_end]
    pre_a = [e for e in events if e["event"] == "delivery" and e["source"] == "A" and e["time"] < relocation]
    first_b_delivery = b_deliveries[0]["time"] if b_deliveries else None
    capped_time, non_delivery = compute_capped_recovery_time(
        first_b_delivery, relocation_step=relocation,
        observation_end=observation_end, cap=cap,
    )
    episodes = json.loads(json.dumps(getattr(sim, "recovery_episodes", [])))
    b_events = [e for e in events if e.get("source") == "B" and e["event"] in {"pickup", "delivery"} and e["time"] <= observation_end]
    for episode in episodes:
        episode["post_window_end"] = min(episode["end_time"] + 100, observation_end)
        episode["B_discovery_within_window"] = any(
            e["event"] == "pickup" and e["ant_id"] == episode["ant_id"]
            and episode["end_time"] <= e["time"] <= episode["post_window_end"]
            for e in b_events
        )
        episode["B_delivery_within_window"] = any(
            e["event"] == "delivery" and e["ant_id"] == episode["ant_id"]
            and episode["end_time"] <= e["time"] <= episode["post_window_end"]
            for e in b_events
        )
    summary = {
        "evidence_status": "stage3d_formal" if config.formal else "engineering-fixture",
        "seed": config.seed,
        "arm": config.arm,
        "decay_law": "hard_cutoff_cell_timer",
        "status": "complete",
        "steps_completed": sim.time,
        "first_B_discovery": b_pickups[0]["time"] if b_pickups else None,
        "first_B_delivery": first_b_delivery,
        "B_deliveries": len(b_deliveries),
        "non_delivery": non_delivery,
        "capped_recovery_time": capped_time,
        "pre_relocation_A_deliveries": len(pre_a),
        "old_food_dwell_ant_steps": old_food_dwell,
        "obsolete_trail_ant_steps": old_trail_occupancy,
        "recovery_count": len(episodes),
        "recovery_reacquired": sum(e["outcome"] == "reacquired" for e in episodes),
        "recovery_timeouts": sum(e["outcome"] == "timeout" for e in episodes),
        "recovery_food_contacts": sum(e["outcome"] == "food_contact" for e in episodes),
        "recovery_B_discovery_within_100_steps": sum(bool(e["B_discovery_within_window"]) for e in episodes),
        "recovery_B_delivery_within_100_steps": sum(bool(e["B_delivery_within_window"]) for e in episodes),
        "completed_cargo": dict(sim.ledger.deliveries),
        "incomplete_cargo": dict(sim.ledger.cargo),
        "final_state_digest": state_digest(sim),
        "valid_state_every_completed_step": True,
    }
    integrity = {
        "pass": len(sim.ants) == config.simulation.n_ants
        and np.isfinite(sim.field.concentration).all()
        and all(0 <= x <= config.simulation.arena_size for ant in sim.ants for x in ant.position)
        and all(e.get("source") in {"A", "B"} for e in events if e["event"] in {"pickup", "delivery"})
        and max((e["duration"] for e in episodes), default=0) <= RECOVERY_DURATION,
        "population": len(sim.ants),
        "population_expected": config.simulation.n_ants,
        "finite_numbers": bool(np.isfinite(sim.field.concentration).all()),
        "bounds_valid": all(0 <= x <= config.simulation.arena_size for ant in sim.ants for x in ant.position),
        "cargo_conserved": all(
            sim.ledger.discoveries[source] == sim.ledger.deliveries[source]
            + sum(value == source for value in sim.ledger.cargo.values())
            for source in ("A", "B")
        ),
        "maximum_recovery_duration": max((e["duration"] for e in episodes), default=0),
    }
    return {
        "summary": summary,
        "series": series,
        "events": events,
        "episodes": episodes,
        "snapshots": snapshots,
        "integrity": integrity,
        "wall_seconds": time.perf_counter() - start_wall,
        "cpu_seconds": time.process_time() - start_cpu,
        "peak_rss_bytes": _rss_bytes(),
    }


def restart_equivalence_audit(config: ArmConfiguration | None = None) -> dict:
    fixture = config or fixture_config(steps=24, relocation_step=12, n_ants=2)
    first = _simulate(fixture)
    # An interrupted atomic arm has published no scientific output; exact-identity
    # resume restarts from the deterministic initial state.
    restarted = _simulate(fixture)
    keys = ("summary", "series", "events", "episodes", "integrity")
    left = {key: first[key] for key in keys}
    right = {key: restarted[key] for key in keys}
    for item in (left, right):
        item["summary"].pop("wall_seconds", None)
        item["summary"].pop("cpu_seconds", None)
    snapshot_equal = set(first["snapshots"]) == set(restarted["snapshots"]) and all(
        np.array_equal(first["snapshots"][key], restarted["snapshots"][key])
        for key in first["snapshots"]
    )
    return {
        "pass": left == right and snapshot_equal,
        "resume_policy": "restart unpublished arm from step zero under exact identity",
        "scientific_payload_sha256": _canonical_sha256(left),
        "restarted_payload_sha256": _canonical_sha256(right),
        "snapshots_equal": snapshot_equal,
    }


def _identity_record(frozen: dict, before: dict, after: dict) -> dict:
    return {
        "schema": "stage3d-arm-identity-v1",
        "match": frozen == before == after,
        "frozen_identity_sha256": _canonical_sha256(frozen),
        "pre_run_identity_sha256": _canonical_sha256(before),
        "post_run_identity_sha256": _canonical_sha256(after),
        "frozen": frozen,
        "pre_run": before,
        "post_run": after,
    }


def _execute_arm(
    output: Path, config: ArmConfiguration, repository_root: Path,
    *, frozen_identity: dict, pre_run_identity: dict,
    identity_provider: IdentityProvider = source_identity,
) -> None:
    allowed = {"resume_identity.json"}
    if {p.name for p in output.iterdir()} - allowed:
        raise EvidenceError("unpublished arm directory contains unexpected evidence")
    result = _simulate(config)
    post_identity = identity_provider(repository_root)
    if config.formal:
        _require_clean_identity(post_identity)
    identity = _identity_record(frozen_identity, pre_run_identity, post_identity)
    if not identity["match"]:
        raise EvidenceError("execution identity changed during arm")

    _write_json(output / "config.json", config.as_record(), exclusive=True)
    _write_json(output / "summary.json", result["summary"], exclusive=True)
    _write_json(output / "timeseries_100step.json", result["series"], exclusive=True)
    _write_json(output / "ledger_events.json", result["events"], exclusive=True)
    if config.arm == "C":
        _write_json(output / "recovery_episodes.json", result["episodes"], exclusive=True)
    np.savez_compressed(output / "field_snapshots.npz", **result["snapshots"])
    _write_json(output / "source_identity.json", identity, exclusive=True)
    resources = {
        "pass": result["wall_seconds"] <= PER_RUN_WALL_LIMIT
        and result["cpu_seconds"] <= PER_RUN_CPU_LIMIT
        and result["peak_rss_bytes"] <= PER_RUN_RSS_LIMIT,
        "wall_seconds": result["wall_seconds"],
        "cpu_seconds": result["cpu_seconds"],
        "peak_rss_bytes": result["peak_rss_bytes"],
        "temporary_output_bytes": _directory_bytes(output),
        "limits": {
            "wall_seconds": PER_RUN_WALL_LIMIT,
            "cpu_seconds": PER_RUN_CPU_LIMIT,
            "peak_rss_bytes": PER_RUN_RSS_LIMIT,
            "temporary_output_bytes": PER_RUN_TEMP_LIMIT,
            "single_retained_file_bytes": PER_FILE_LIMIT,
        },
    }
    _write_json(output / "resources.json", resources, exclusive=True)
    _write_json(output / "integrity.json", result["integrity"], exclusive=True)
    if not resources["pass"]:
        raise ResourceLimitError("post-run resource validation failed")
    if not result["integrity"]["pass"]:
        raise EvidenceError("post-run scientific integrity validation failed")
    if _directory_bytes(output) > PER_RUN_TEMP_LIMIT:
        raise ResourceLimitError("temporary output limit exceeded")
    before_storage = {
        str(path.relative_to(output)): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    _write_json(output / "storage.json", {
        "bytes_before_storage": sum(item["bytes"] for item in before_storage.values()),
        "files_before_storage": before_storage,
    }, exclusive=True)
    pre_receipt = [path for path in output.rglob("*") if path.is_file()]
    largest = max((path.stat().st_size for path in pre_receipt), default=0)
    if largest > PER_FILE_LIMIT:
        raise ResourceLimitError("single retained file limit exceeded")
    manifest = {
        str(path.relative_to(output)): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(pre_receipt)
    }
    _write_json(output / "completed_receipt.json", {
        "status": "complete",
        "stage": "3D",
        "seed": config.seed,
        "arm": config.arm,
        "decay_law": "hard_cutoff_cell_timer",
        "formal": config.formal,
        "recursive_files_excluding_this_receipt": manifest,
    }, exclusive=True)


def _required_files(arm: str) -> set[str]:
    result = {
        "resume_identity.json", "config.json", "summary.json",
        "timeseries_100step.json", "ledger_events.json", "field_snapshots.npz",
        "source_identity.json", "resources.json", "integrity.json", "storage.json",
        "completed_receipt.json",
    }
    if arm == "C":
        result.add("recovery_episodes.json")
    return result


def validate_run_directory(
    run_directory: Path, expected: ArmConfiguration,
    *, expected_execution_identity: dict,
) -> dict:
    if not run_directory.is_dir():
        raise EvidenceError("Stage 3D arm directory is missing")
    receipt_path = run_directory / "completed_receipt.json"
    if not receipt_path.is_file():
        raise EvidenceError("Stage 3D completed receipt is missing")
    receipt = json.loads(receipt_path.read_text())
    present = {str(p.relative_to(run_directory)) for p in run_directory.rglob("*") if p.is_file()}
    if not _required_files(expected.arm).issubset(present):
        raise EvidenceError("Stage 3D arm artifacts are incomplete")
    manifest = receipt.get("recursive_files_excluding_this_receipt", {})
    if set(manifest) != present - {"completed_receipt.json"}:
        raise EvidenceError("Stage 3D completed receipt coverage differs")
    for relative, record in manifest.items():
        path = run_directory / relative
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            raise EvidenceError(f"Stage 3D artifact hash mismatch: {relative}")
    config_record = json.loads((run_directory / "config.json").read_text())
    if config_record != json.loads(json.dumps(expected.as_record())):
        raise EvidenceError("Stage 3D run configuration differs")
    summary = json.loads((run_directory / "summary.json").read_text())
    resources = json.loads((run_directory / "resources.json").read_text())
    integrity = json.loads((run_directory / "integrity.json").read_text())
    identity = json.loads((run_directory / "source_identity.json").read_text())
    resume = json.loads((run_directory / "resume_identity.json").read_text())
    if (
        receipt.get("status") != "complete" or receipt.get("stage") != "3D"
        or receipt.get("seed") != expected.seed or receipt.get("arm") != expected.arm
        or receipt.get("formal") is not expected.formal
        or summary.get("status") != "complete" or summary.get("seed") != expected.seed
        or summary.get("arm") != expected.arm or summary.get("steps_completed") != expected.simulation.steps
        or resources.get("pass") is not True or integrity.get("pass") is not True
    ):
        raise EvidenceError("Stage 3D receipt or completion identity is invalid")
    identities = (identity.get("frozen"), identity.get("pre_run"), identity.get("post_run"))
    if (
        identity.get("schema") != "stage3d-arm-identity-v1"
        or identity.get("match") is not True
        or not identities[0] == identities[1] == identities[2] == expected_execution_identity
    ):
        raise EvidenceError("Stage 3D source identity is invalid")
    if resume.get("config_sha256") != _canonical_sha256(expected.as_record()) or resume.get("execution_identity_sha256") != _canonical_sha256(expected_execution_identity):
        raise EvidenceError("Stage 3D resume identity is invalid")
    retained = _directory_bytes(run_directory)
    largest = max((p.stat().st_size for p in run_directory.rglob("*") if p.is_file()), default=0)
    if retained > PER_RUN_TEMP_LIMIT or largest > PER_FILE_LIMIT:
        raise ResourceLimitError("Stage 3D retained output limit exceeded")
    return {
        "pass": True,
        "seed": expected.seed,
        "arm": expected.arm,
        "files_verified": len(manifest),
        "receipt_sha256": _sha256(receipt_path),
        "retained_bytes": retained,
        "file_count": len(present),
        "summary": summary,
        "resources": resources,
    }


def run_arm_atomic(
    study_root: Path, config: ArmConfiguration, repository_root: Path,
    *, identity_provider: IdentityProvider = source_identity,
    validated_audit: dict | None = None,
) -> dict:
    if config.formal:
        validate_config(config)
        audit = validated_audit or validate_prerun_audit(
            study_root, repository_root, identity_provider=identity_provider
        )
        frozen_identity = audit["execution_identity"]
        pre_identity = identity_provider(repository_root)
        _require_clean_identity(pre_identity)
        if pre_identity != frozen_identity:
            raise EvidenceError("formal arm identity differs from frozen audit")
    else:
        pre_identity = identity_provider(repository_root)
        frozen_identity = pre_identity
    final = study_root / "runs" / str(config.seed) / config.arm
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        return validate_run_directory(
            final, config, expected_execution_identity=frozen_identity
        )
    prefix = f".{config.seed}-{config.arm}.tmp-"
    temporary_candidates = sorted(
        p for p in final.parent.iterdir() if p.is_dir() and p.name.startswith(prefix)
    )
    if len(temporary_candidates) > 1:
        raise EvidenceError("multiple unpublished arm directories exist")
    if temporary_candidates:
        temporary = temporary_candidates[0]
        if (temporary / "failure.json").exists():
            raise EvidenceError("failed arm evidence requires review")
        resume_path = temporary / "resume_identity.json"
        if not resume_path.is_file():
            raise EvidenceError("unpublished arm lacks resume identity")
        resume = json.loads(resume_path.read_text())
        expected_resume = {
            "schema": "stage3d-resume-identity-v1",
            "seed": config.seed,
            "arm": config.arm,
            "config_sha256": _canonical_sha256(config.as_record()),
            "execution_identity_sha256": _canonical_sha256(frozen_identity),
            "policy": "restart unpublished deterministic arm from step zero",
        }
        if resume != expected_resume:
            raise EvidenceError("resume seed, arm, configuration, or identity differs")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=prefix, dir=final.parent))
        _write_json(temporary / "resume_identity.json", {
            "schema": "stage3d-resume-identity-v1",
            "seed": config.seed,
            "arm": config.arm,
            "config_sha256": _canonical_sha256(config.as_record()),
            "execution_identity_sha256": _canonical_sha256(frozen_identity),
            "policy": "restart unpublished deterministic arm from step zero",
        }, exclusive=True)
    try:
        _execute_arm(
            temporary, config, repository_root,
            frozen_identity=frozen_identity, pre_run_identity=pre_identity,
            identity_provider=identity_provider,
        )
        validation = validate_run_directory(
            temporary, config, expected_execution_identity=frozen_identity
        )
        os.replace(temporary, final)
        return validation
    except Exception as exc:
        if not (temporary / "failure.json").exists():
            _write_json(temporary / "failure.json", {
                "status": "incomplete",
                "seed": config.seed,
                "arm": config.arm,
                "error": f"{type(exc).__name__}: {exc}",
            })
        raise


def validate_complete_study(study_root: Path, repository_root: Path) -> dict:
    audit = validate_prerun_audit(study_root, repository_root)
    validations = []
    total_cpu = 0.0
    total_wall = 0.0
    peak_rss = 0
    for seed in SEEDS:
        for arm in ARMS:
            item = validate_run_directory(
                study_root / "runs" / str(seed) / arm,
                formal_config(seed, arm),
                expected_execution_identity=audit["execution_identity"],
            )
            validations.append(item)
            total_cpu += item["resources"]["cpu_seconds"]
            total_wall += item["resources"]["wall_seconds"]
            peak_rss = max(peak_rss, item["resources"]["peak_rss_bytes"])
    incomplete = [
        str(path.relative_to(study_root))
        for path in study_root.rglob("*")
        if path.is_dir() and ".tmp-" in path.name
    ]
    retained = _directory_bytes(study_root)
    if incomplete:
        raise EvidenceError("unpublished temporary arm evidence remains")
    if total_cpu > STUDY_CPU_LIMIT or retained > STUDY_OUTPUT_LIMIT:
        raise ResourceLimitError("complete Stage 3D resource limit exceeded")
    protection = verify_protected_snapshot(
        json.loads((study_root / "protected_files_before.json").read_text()),
        repository_root,
    )
    if not protection["pass"]:
        raise EvidenceError("protected evidence changed")
    return {
        "pass": True,
        "new_runs_verified": len(validations),
        "reused_exponential_runs_verified": 40,
        "total_cpu_seconds": total_cpu,
        "cumulative_arm_wall_seconds": total_wall,
        "peak_rss_bytes": peak_rss,
        "retained_output_bytes": retained,
        "protected_files": protection,
    }


def dry_run(repository_root: Path) -> dict:
    configurations = [formal_config(seed, arm).as_record() for seed in SEEDS for arm in ARMS]
    lifetime = matched_lifetime_audit()
    decay = [decay_single_change_audit(seed, arm) for seed in SEEDS for arm in ARMS]
    pairs = [pair_single_change_audit(seed) for seed in SEEDS]
    schedules = schedule_identity_audit()
    restart = restart_equivalence_audit()
    return {
        "mode": "dry-run",
        "pass": lifetime["pass"] and all(x["pass"] for x in decay)
        and all(x["pass"] for x in pairs) and schedules["pass"] and restart["pass"],
        "simulation_initialised_for_formal_seed": False,
        "formal_simulation_steps_executed": 0,
        "formal_results_directory_created": (repository_root / FORMAL_RESULTS_RELATIVE).exists(),
        "configurations_validated": len(configurations),
        "seed_order": list(SEEDS),
        "arm_order": list(ARMS),
        "worker_count": 1,
        "matched_lifetime_audit": lifetime,
        "decay_single_change_pass": all(x["pass"] for x in decay),
        "pair_single_change_pass": all(x["pass"] for x in pairs),
        "schedule_identity_audit": schedules,
        "restart_equivalence_audit": restart,
    }


def run_all(study_root: Path, repository_root: Path) -> dict:
    if not study_root.exists():
        audit = initialise_prerun_audit(study_root, repository_root)
    else:
        audit = validate_prerun_audit(study_root, repository_root)
    completed = 0
    reused_complete = 0
    for seed in SEEDS:
        for arm in ARMS:
            target = study_root / "runs" / str(seed) / arm / "completed_receipt.json"
            existed = target.is_file()
            run_arm_atomic(
                study_root, formal_config(seed, arm), repository_root,
                validated_audit=audit,
            )
            completed += 1
            reused_complete += int(existed)
    validation = validate_complete_study(study_root, repository_root)
    return {
        "mode": "run",
        "outcome_blind": True,
        "scientific_results_in_stdout": False,
        "new_hard_cutoff_arms_complete": completed,
        "previously_completed_arms_reused": reused_complete,
        "execution_order": "seed ascending; B0 then C; one local worker",
        "validation": validation,
    }
