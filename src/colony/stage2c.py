"""Resumable Stage 2C orchestration; simulation rules remain in frozen modules."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ColonyConfig
from .simulation import ColonySimulation
from .stage2b_audit import sha256, single_change_audit
from .stage2c_analysis import (
    NOTICE, RULES, SEEDS, analyse_rows,
    planned_rows, seed_manifest, write_comparison_figures, write_metric_tables,
)
from .stage2c_checkpoint import (
    atomic_write, behavioural_config, digest_bytes,
    hash_value, initial_identity, load_checkpoint, load_shared_seed_artifact,
    read_json, save_checkpoint, save_field_artifact, save_shared_seed_artifact, write_json,
    storage_only_measurement,
)
from .stage2c_streaming import StreamingSimulation
from .stage2c_storage import HistoryStore

PREREGISTRATION_COMMIT = "25994defe0b61e04fa03f3977cd65a2b9a61e640"
IMPLEMENTATION_COMMIT = "f216ed88b9ab35b88627d1b34473245f16a0559e"
PROTOCOL_INPUT_COMMIT = "3226100a5fa52777acedbf8cfa25c71559ab525d"
PREREGISTRATION_PATH = "docs/STAGE2C_PREREGISTRATION.md"
DEFAULT_OUTPUT = "results/stage2c_multiseed_confirmation"
TIME_LIMIT = 14400.0
STORAGE_LIMIT = 2_000_000_000
SAFETY_FACTOR = 1.5
CHECKPOINT_INTERVAL = 100
PROTECTED_DIRS = ("results/stage1", "results/stage2_provisional", "results/stage2_diagnostic",
                  "results/stage2b_local_geometry", "reports")
PROTECTED_FILES = ("docs/STAGE1_SPEC.md", "docs/STAGE2_SPEC.md", "docs/STAGE2B_SPEC.md",
                   PREREGISTRATION_PATH, "Project Proposal.pdf", "_PH6780 Templates.docx",
                   "_AY2627_T1_Briefing_updated.pdf", "references.bib")
STATES = {
    "planned": {"running"}, "running": {"interrupted", "engineering_failed", "completed"},
    "interrupted": {"running"}, "engineering_failed": {"running"}, "completed": set(),
}


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))


def validate_output(root: Path, output: Path) -> None:
    root, output = root.resolve(), output.resolve()
    dedicated = root / DEFAULT_OUTPUT
    if output == root or output in root.parents:
        raise ValueError("output must not contain the project")
    if root in output.parents and output != dedicated and dedicated not in output.parents:
        raise ValueError("in-project outputs are restricted to the dedicated Stage 2C directory")


def protected_hashes(root: Path) -> dict:
    paths = {root / name for name in PROTECTED_FILES}
    for folder in PROTECTED_DIRS:
        if not (root / folder).is_dir():
            raise FileNotFoundError("missing protected directory: " + folder)
        paths.update(p for p in (root / folder).rglob("*") if p.is_file())
    if (root / "similarity check.pdf").exists():
        paths.add(root / "similarity check.pdf")
    return {str(p.relative_to(root)): sha256(p) for p in sorted(paths)}


def _tree(root: Path, commit: str, *paths: str) -> dict:
    entries = git(root, "ls-tree", "-r", "-z", commit, "--", *paths).split(b"\0")
    return {entry.split(b"\t", 1)[1].decode(): entry.split(b"\t", 1)[0].split()[2].decode()
            for entry in entries if entry}


def _blob_hash(path: Path) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_identity(root: Path, output: Path | None = None) -> dict:
    """Read and validate actual bytes; a commit label alone is not an audit."""
    root = root.resolve()
    source_scope = ("src", "scripts", "run_stage1.sh", "run_stage2.sh", "run_stage2b.sh")
    frozen_names = _tree(root, IMPLEMENTATION_COMMIT, *source_scope)
    if frozen_names != _tree(root, PROTOCOL_INPUT_COMMIT, *source_scope):
        raise ValueError("the two recorded implementation commits differ")
    frozen_hashes = {}
    for name, expected_blob in frozen_names.items():
        if _blob_hash(root / name) != expected_blob:
            raise ValueError("frozen model/source changed: " + name)
        frozen_hashes[name] = sha256(root / name)
    expected_protocol = git(root, "show", f"{PREREGISTRATION_COMMIT}:{PREREGISTRATION_PATH}")
    if (root / PREREGISTRATION_PATH).read_bytes() != expected_protocol:
        raise ValueError("committed preregistration changed")
    inputs = protected_hashes(root)
    tracked = _tree(root, PREREGISTRATION_COMMIT)
    for name in inputs.keys() & tracked.keys():
        if _blob_hash(root / name) != tracked[name]:
            raise ValueError("frozen input artifact changed: " + name)
    sources = set(root.glob("src/**/*.py")) | set(root.glob("scripts/*.py")) | set(root.glob("tests/*.py"))
    sources.update(root / p for p in ("run_stage2c.sh", "requirements.txt"))
    source_hashes = {str(p.relative_to(root)): sha256(p) for p in sorted(sources)}
    status = git(root, "status", "--porcelain", "--untracked-files=all").decode().splitlines()
    excluded = ["?? " + DEFAULT_OUTPUT + "/"]
    if output is not None and root in output.resolve().parents:
        excluded.append("?? " + str(output.resolve().relative_to(root)) + "/")
    source_status = [line for line in status if not any(line.startswith(prefix) for prefix in excluded)]
    return {"preregistration_commit": PREREGISTRATION_COMMIT,
            "stage2b_implementation_commit": IMPLEMENTATION_COMMIT,
            "protocol_input_commit": PROTOCOL_INPUT_COMMIT,
            "implementation_commits_source_equivalent": True,
            "runner_commit": git(root, "rev-parse", "HEAD").decode().strip(),
            "runner_worktree_clean": not bool(source_status),
            "source_hashes": source_hashes, "source_hash": hash_value(source_hashes),
            "frozen_source_hashes": frozen_hashes, "input_hashes": inputs,
            "input_hash": hash_value(inputs), "preregistration_hash": digest_bytes(expected_protocol),
            "environment": {"python": platform.python_version(), "numpy": np.__version__,
                            "pandas": pd.__version__, "platform": platform.platform(),
                            "machine": platform.machine()}}


def config_pair(seed: int, output: Path) -> tuple[ColonyConfig, ColonyConfig]:
    if seed not in SEEDS:
        raise ValueError("seed is not in the confirmatory manifest")
    return tuple(replace(ColonyConfig.paper_scale(), seed=seed, follower_direction_rule=rule,
                         output_dir=str(output / "runs" / str(seed) / rule)) for rule in RULES)


def audit_pair(baseline: ColonyConfig, pca: ColonyConfig) -> dict:
    audit = single_change_audit(baseline.to_dict(), pca.to_dict())
    if baseline.seed not in SEEDS or not audit["only_follower_direction_rule_changed"]:
        raise ValueError("invalid seed or paired behavioural configuration")
    return audit


def directory_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def retained_study_bytes(path: Path) -> int:
    """Long-term bytes only; active checkpoint/history overlap is separate."""
    total = 0
    items = Path(path).rglob("*") if Path(path).exists() else ()
    for item in items:
        if not item.is_file():
            continue
        parts = item.relative_to(path).parts
        if "completed" not in parts and (
                item.name in ("checkpoint-0.zip", "checkpoint-1.zip")
                or "history" in parts
                or any(part.startswith("completion-") for part in parts)):
            continue
        total += item.stat().st_size
    return total


def resource_projection(*, elapsed_seconds: float, stored_bytes: int, remaining_runs: int,
                        run_seconds: float | None,
                        retained_completed_run_bytes: int | None,
                        retained_checkpoint_bytes_per_completed_run: int | None,
                        shared_seed_artifact_bytes: int | None,
                        remaining_shared_seed_artifacts: int,
                        active_checkpoint_overlap_bytes: int | None,
                        final_analysis_allowance_bytes: int = 20_000_000,
                        completion_publication_overlap_bytes: int = 0,
                        analysis_seconds: float = 600.0,
                        pilot_observed: bool = False,
                        assumptions: list[str] | None = None,
                        measurement_status: dict | None = None) -> dict:
    values = (elapsed_seconds, stored_bytes, remaining_runs, analysis_seconds,
              final_analysis_allowance_bytes, completion_publication_overlap_bytes,
              remaining_shared_seed_artifacts)
    if any(not np.isfinite(v) or v < 0 for v in values) or remaining_runs > 40:
        raise ValueError("invalid resource accounting")
    time_known = run_seconds is not None and np.isfinite(run_seconds) and run_seconds > 0
    storage_inputs = (retained_completed_run_bytes,
                      retained_checkpoint_bytes_per_completed_run,
                      shared_seed_artifact_bytes, active_checkpoint_overlap_bytes)
    storage_known = all(value is not None and np.isfinite(value) and value >= 0
                        for value in storage_inputs)
    projected_time = (elapsed_seconds + SAFETY_FACTOR * remaining_runs * run_seconds
                      + analysis_seconds) if time_known else None
    projected_bytes = None
    if storage_known:
        per_run_retained = (retained_completed_run_bytes
                            + retained_checkpoint_bytes_per_completed_run)
        projected_bytes = (
            stored_bytes
            + SAFETY_FACTOR * remaining_runs * per_run_retained
            + remaining_shared_seed_artifacts * shared_seed_artifact_bytes
            + active_checkpoint_overlap_bytes
            + completion_publication_overlap_bytes
            + final_analysis_allowance_bytes)
    reasons = []
    if not time_known or not storage_known:
        reasons.append("projection_unresolved")
    if projected_time is not None and (projected_time > TIME_LIMIT or elapsed_seconds >= TIME_LIMIT):
        reasons.append("four_hour_limit")
    if projected_bytes is not None and (projected_bytes > STORAGE_LIMIT or stored_bytes >= STORAGE_LIMIT):
        reasons.append("two_gb_limit")
    return {"action": "pause" if reasons else "continue", "reasons": reasons,
            "safety_factor": SAFETY_FACTOR, "elapsed_seconds": elapsed_seconds, "stored_bytes": stored_bytes,
            "remaining_runs": remaining_runs, "per_run_seconds": run_seconds,
            "retained_completed_run_bytes": retained_completed_run_bytes,
            "retained_checkpoint_bytes_per_completed_run": retained_checkpoint_bytes_per_completed_run,
            "shared_seed_artifact_bytes": shared_seed_artifact_bytes,
            "remaining_shared_seed_artifacts": remaining_shared_seed_artifacts,
            "active_checkpoint_overlap_bytes": active_checkpoint_overlap_bytes,
            "completion_publication_overlap_bytes": completion_publication_overlap_bytes,
            "analysis_seconds_allowance": analysis_seconds,
            "final_analysis_allowance_bytes": final_analysis_allowance_bytes,
            "projected_total_seconds": projected_time, "projected_peak_additional_bytes": projected_bytes,
            "time_limit_seconds": TIME_LIMIT, "storage_limit_bytes": STORAGE_LIMIT,
            "calculation_formula": (
                "stored_bytes + safety_factor * remaining_runs * "
                "(retained_completed_run_bytes + retained_checkpoint_bytes_per_completed_run) + "
                "remaining_shared_seed_artifacts * shared_seed_artifact_bytes + "
                "active_checkpoint_overlap_bytes + completion_publication_overlap_bytes + "
                "final_analysis_allowance_bytes"),
            "assumptions": assumptions or [],
            "measurement_status": measurement_status or {},
            "current_machine_pilot_observed": pilot_observed,
            "basis": "current_completed_runs" if pilot_observed else "historical_only_no_current_machine_pilot",
            "cpu_only": True, "gpu_used": False, "autodl_used": False, "external_costs": 0}


def historical_resources(root: Path, storage_measurement: dict) -> dict:
    old = read_json(root / "results/stage2b_local_geometry/runtime.json")
    sizes = {}
    for folder in ("results/stage2_provisional", "results/stage2b_local_geometry"):
        # Top-level artifacts are comparable full-run outputs; pilot subfolders are not.
        sizes[folder] = sum(p.stat().st_size for p in (root / folder).iterdir() if p.is_file())
    largest = max(sizes.values())
    legacy_checkpoint_allowance = 30_001_600
    legacy_run_bytes = largest + 2 * legacy_checkpoint_allowance

    def largest_file(*names: str) -> int:
        paths = [root / name for name in names]
        return max(path.stat().st_size for path in paths if path.is_file())

    retained_components = {
        "metrics_history_proxy": largest_file(
            "results/stage2_provisional/metrics.csv",
            "results/stage2b_local_geometry/metrics.csv"),
        "agent_state_samples_proxy": largest_file(
            "results/stage2_provisional/agent_states.csv"),
        "role_specific_observations_proxy": largest_file(
            "results/stage2b_local_geometry/role_specific_order.csv"),
        "events_proxy": largest_file(
            "results/stage2_provisional/events.csv",
            "results/stage2b_local_geometry/events.csv"),
        "completed_transport_proxy": largest_file(
            "results/stage2b_local_geometry/transport_path_efficiency.csv"),
        "final_agents_proxy": largest_file(
            "results/stage2_provisional/final_agents.csv",
            "results/stage2b_local_geometry/final_agents.csv"),
        "dense_final_field_storage_fixture": storage_measurement[
            "synthetic_dense_final_field_bytes"],
        "receipts_config_hashes_and_manifests_allowance": 1_000_000,
    }
    retained_completed = sum(retained_components.values())
    return {"run_seconds": max(old["baseline_replay_seconds"], old["paper_simulation_seconds"]),
            "legacy_run_bytes": legacy_run_bytes,
            "legacy_projected_peak_additional_bytes": (
                legacy_run_bytes * 40 * SAFETY_FACTOR + legacy_checkpoint_allowance
                + 20_000_000),
            "legacy_checkpoint_numeric_bytes_allowance": legacy_checkpoint_allowance,
            "retained_completed_run_bytes": retained_completed,
            "retained_checkpoint_bytes_per_completed_run": storage_measurement[
                "synthetic_max_completed_checkpoint_bytes"],
            "shared_seed_artifact_bytes": storage_measurement["shared_seed_artifact_bytes"],
            "active_checkpoint_overlap_bytes": storage_measurement[
                "active_checkpoint_overlap_bytes"],
            "completion_publication_overlap_bytes": retained_completed,
            "retained_completed_components": retained_components,
            "historical_artifact_sizes": sizes,
            "checkpoint_numeric_bytes_allowance": legacy_checkpoint_allowance,
            "storage_assumption": (
                "historical category measurements bound retained tables; full-shape non-zero "
                "storage fixtures measure the production lossless checkpoint format; the 1.5 "
                "factor remains applied to every remaining run's retained output and checkpoint")}


def new_progress(identity: dict) -> dict:
    return {"schema_version": 1, "identity": identity, "study_state": "planned",
            "elapsed_seconds": 0.0, "completed_samples": [], "resource_history": [],
            "runs": [{"seed": s, "rule": r, "status": "planned", "reason": "not_started",
                      "time": 0, "checkpoint": None, "checkpoint_sha256": None,
                      "checkpoint_generation": 0, "elapsed_seconds": 0.0,
                      "history_manifest": None, "history_manifest_sha256": None,
                      "shared_seed_artifact": None, "shared_seed_artifact_sha256": None,
                      "initial_identity": None, "attempts": []} for s in SEEDS for r in RULES]}


def transition(entry: dict, state: str, reason: str) -> None:
    if state not in STATES[entry["status"]]:
        raise ValueError(f"invalid status transition {entry['status']} -> {state}")
    entry.update(status=state, reason=reason)


def _publish_checkpoint(run_dir: Path, simulation: StreamingSimulation, entry: dict,
                        identity: dict, persist) -> None:
    generation = entry["checkpoint_generation"] + 1
    # Keep the referenced slot intact until the other slot and pointer are durable.
    filename = f"checkpoint-{generation % 2}.zip"
    history = HistoryStore(run_dir / "history")
    previous_manifest = run_dir / entry["history_manifest"] if entry["history_manifest"] else None
    manifest_path, manifest_checksum, _ = history.commit(
        simulation, generation, previous_manifest=previous_manifest)
    target = run_dir / filename
    if target.exists() and entry["checkpoint"] != filename:
        # The other slot remains the last referenced checkpoint while this stale
        # target is removed, so atomic publication peaks at exactly two slots.
        target.unlink()
    start = time.perf_counter()
    shared = run_dir.parent / "shared_seed_artifact.zip"
    checksum = save_checkpoint(
        target, simulation, identity, shared_artifact=shared,
        history_manifest=manifest_path, initial=entry["initial_identity"])
    simulation.runtime_counters["checkpoint_seconds"] += time.perf_counter() - start
    simulation.runtime_counters["checkpoint_count"] += 1
    entry.update(checkpoint=filename, checkpoint_sha256=checksum,
                 checkpoint_generation=generation, time=simulation.time,
                 history_manifest=str(manifest_path.relative_to(run_dir)),
                 history_manifest_sha256=manifest_checksum,
                 shared_seed_artifact=os.path.relpath(shared, start=run_dir),
                 shared_seed_artifact_sha256=sha256(shared))
    persist()


def _artifact_hashes(directory: Path) -> dict:
    return {str(path.relative_to(directory)): sha256(path)
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path.name != "receipt.json"}


def _completed_record(completed: Path, config: ColonyConfig, identity: dict) -> dict:
    receipt = read_json(completed / "receipt.json")
    if receipt["identity"] != identity or receipt["config_hash"] != hash_value(behavioural_config(config)):
        raise ValueError("completed run configuration/code identity mismatch")
    actual = _artifact_hashes(completed)
    if actual != receipt["artifact_hashes"]:
        raise ValueError("completed run artifacts changed or missing")
    shared = completed.parent.parent / "shared_seed_artifact.zip"
    if not shared.is_file() or sha256(shared) != receipt["shared_seed_artifact_sha256"]:
        raise ValueError("completed run shared seed artifact changed or missing")
    row = read_json(completed / "result.json")
    if (row["seed"], row["rule"], row["status"]) != (config.seed, config.follower_direction_rule, "completed"):
        raise ValueError("completed run receipt identity mismatch")
    return row


def _bind_completed_entry(entry: dict, completed: Path, config: ColonyConfig) -> None:
    receipt = read_json(completed / "receipt.json")
    entry.update(
        status="completed", reason="verified_completed_receipt", time=config.steps,
        checkpoint="completed/" + receipt["final_checkpoint"],
        checkpoint_sha256=receipt["final_checkpoint_sha256"],
        checkpoint_generation=receipt["checkpoint_generation"],
        history_manifest="completed/" + receipt["history_manifest"],
        history_manifest_sha256=receipt["history_manifest_sha256"],
        shared_seed_artifact=receipt["shared_seed_artifact"],
        shared_seed_artifact_sha256=receipt["shared_seed_artifact_sha256"])


def _write_completed(run_dir: Path, simulation: StreamingSimulation, identity: dict,
                     initial: dict, entry: dict) -> tuple[dict, dict]:
    completed = run_dir / "completed"
    if completed.exists():
        raise FileExistsError("completed run must not be overwritten")
    # This run() only assembles the already-complete base result; it takes no steps.
    result = ColonySimulation.run(simulation)
    row = {"seed": simulation.config.seed, "rule": simulation.config.follower_direction_rule,
           "status": "completed", "engineering_valid": True,
           "metrics": simulation.endpoint_metrics(), "transition_counts": dict(simulation.transition_counts),
           "initial_identity": initial, "horizon": simulation.time,
           "config_hash": hash_value(behavioural_config(simulation.config)),
           "late_window": list(simulation.late_window)}
    start, end = simulation.late_window
    before = simulation._metric_rows[max(start - 1, 0)]["cumulative_deliveries"]
    row["late_window_delivery_increment"] = simulation.cumulative_deliveries - before
    row["late_window_transition_counts"] = {
        name: sum(start <= event.time <= end and f"{event.from_role}_to_{event.to_role}" == name
                  for event in simulation._event_records)
        for name in simulation.transition_counts}
    stage = Path(tempfile.mkdtemp(prefix="completion-", dir=run_dir))
    final_generation = entry["checkpoint_generation"] + 1
    manifest, manifest_checksum = HistoryStore.write_completed(
        stage, simulation, final_generation)
    atomic_write(stage / "final_agents.csv",
                 result.final_agents.to_csv(index=False, lineterminator="\n").encode(), replace=False)
    write_json(stage / "result.json", row, replace=False)
    write_json(stage / "config.json", simulation.config.to_dict(), replace=False)
    write_json(stage / "diagnostic_accumulators.json", simulation.diagnostic_evidence(), replace=False)
    write_json(stage / "transition_counts.json", simulation.transition_counts, replace=False)
    field_path = stage / "final_pheromone.npz"
    save_field_artifact(field_path, simulation.field)
    shared = run_dir.parent / "shared_seed_artifact.zip"
    final_checkpoint = stage / "final_checkpoint.zip"
    final_checksum = save_checkpoint(
        final_checkpoint, simulation, identity, shared_artifact=shared,
        history_manifest=manifest, initial=initial, external_field=field_path)
    receipt = {
        "identity": identity,
        "config_hash": row["config_hash"],
        "completion_time_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_generation": final_generation,
        "final_checkpoint": "final_checkpoint.zip",
        "final_checkpoint_sha256": final_checksum,
        "history_manifest": str(manifest.relative_to(stage)),
        "history_manifest_sha256": manifest_checksum,
        "shared_seed_artifact": os.path.relpath(shared, start=completed),
        "shared_seed_artifact_sha256": sha256(shared),
    }
    receipt["artifact_hashes"] = _artifact_hashes(stage)
    write_json(stage / "receipt.json", receipt, replace=False)
    os.rename(stage, completed)
    return row, receipt


def run_one(config: ColonyConfig, run_dir: Path, identity: dict, entry: dict, *,
            resume: bool, persist, resource_check, late_window=(9000, 10000),
            checkpoint_interval: int = CHECKPOINT_INTERVAL, boundary_observer=None,
            expected_initial: dict | None = None) -> dict | None:
    """One state machine, also exercised by bounded tests with small configs.

    The CLI never offers small-config or seed overrides. Tests pass their own
    temporary path/configuration and cannot enter the formal study analyser.
    """
    run_dir = Path(run_dir)
    if checkpoint_interval < 1:
        raise ValueError("checkpoint interval must be positive")
    if (entry["seed"], entry["rule"]) != (config.seed, config.follower_direction_rule):
        raise ValueError("progress seed/rule mismatch")
    if (run_dir / "completed").exists():
        row = _completed_record(run_dir / "completed", config, identity)
        if entry["status"] != "completed":
            # Recover a crash after the atomic directory rename, never rerun it.
            _bind_completed_entry(entry, run_dir / "completed", config)
            persist()
        return row
    if entry["status"] == "completed":
        raise ValueError("completed run is missing its artifacts")
    if entry["status"] != "planned" and not resume:
        raise ValueError("unfinished run requires --resume")
    if resource_check()["action"] == "pause":
        return None
    if entry["status"] == "running":
        transition(entry, "interrupted", "previous_process_stopped_without_final_status")
    if entry["checkpoint"]:
        # Reject identity/config mismatches before changing the progress manifest.
        simulation = load_checkpoint(run_dir / entry["checkpoint"], config, identity,
                                     expected_sha256=entry["checkpoint_sha256"])
        if simulation.late_window != tuple(late_window):
            raise ValueError("checkpoint observation window mismatch")
        if expected_initial is not None and entry["initial_identity"] != expected_initial:
            raise ValueError("paired initial identity mismatch on resume")
    else:
        simulation = None
    transition(entry, "running", "same_seed_resume" if resume else "started")
    entry["attempts"].append({"start_time_step": entry["time"], "status": "running"})
    persist()
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    previous_elapsed = entry["elapsed_seconds"]

    def account():
        entry["elapsed_seconds"] = previous_elapsed + time.perf_counter() - started
        if simulation is not None:
            simulation.runtime_counters["elapsed_seconds"] = entry["elapsed_seconds"]
            simulation.runtime_counters["peak_storage_bytes"] = max(
                simulation.runtime_counters["peak_storage_bytes"], directory_bytes(run_dir))

    try:
        if simulation is None:
            shared_path = run_dir.parent / "shared_seed_artifact.zip"
            if shared_path.exists():
                shared = load_shared_seed_artifact(
                    shared_path, config, identity,
                    expected_sha256=entry.get("shared_seed_artifact_sha256"))
                simulation = StreamingSimulation(
                    config, late_window=late_window, initial_agents=shared["ants"],
                    turn_schedules=shared["turn_schedules"])
                entry["initial_identity"] = initial_identity(simulation)
                if entry["initial_identity"] != shared["initial_identity"]:
                    raise ValueError("shared seed artifact did not recreate its initial state")
                shared_checksum = shared["sha256"]
            else:
                simulation = StreamingSimulation(config, late_window=late_window)
                entry["initial_identity"] = initial_identity(simulation)
                shared_checksum, shared_initial = save_shared_seed_artifact(
                    shared_path, simulation, identity)
                if shared_initial != entry["initial_identity"]:
                    raise RuntimeError("shared seed artifact identity changed during publication")
            entry.update(
                shared_seed_artifact=os.path.relpath(shared_path, start=run_dir),
                shared_seed_artifact_sha256=shared_checksum)
            if expected_initial is not None and entry["initial_identity"] != expected_initial:
                raise ValueError("paired initial state or turn schedule mismatch before first step")
            account()
            _publish_checkpoint(run_dir, simulation, entry, identity, persist)
        while simulation.time < config.steps:
            simulation.step()
            if simulation.time % checkpoint_interval == 0 or simulation.time == config.steps:
                account()
                _publish_checkpoint(run_dir, simulation, entry, identity, persist)
                account()
                if resource_check()["action"] == "pause":
                    transition(entry, "interrupted", "resource_pause")
                    entry["attempts"][-1]["status"] = "interrupted"
                    persist()
                    return None
            if boundary_observer is not None:
                boundary_observer(simulation, entry)
        row, receipt = _write_completed(
            run_dir, simulation, identity, entry["initial_identity"], entry)
        account()
        transition(entry, "completed", "complete_horizon_and_engineering_checks")
        entry["time"] = simulation.time
        entry.update(
            checkpoint="completed/" + receipt["final_checkpoint"],
            checkpoint_sha256=receipt["final_checkpoint_sha256"],
            checkpoint_generation=receipt["checkpoint_generation"],
            history_manifest="completed/" + receipt["history_manifest"],
            history_manifest_sha256=receipt["history_manifest_sha256"],
            shared_seed_artifact=receipt["shared_seed_artifact"],
            shared_seed_artifact_sha256=receipt["shared_seed_artifact_sha256"])
        entry["attempts"][-1]["status"] = "completed"
        persist()
        for name in ("checkpoint-0.zip", "checkpoint-1.zip"):
            path = run_dir / name
            if path.exists():
                path.unlink()
        if (run_dir / "history").exists():
            shutil.rmtree(run_dir / "history")
        return row
    except (KeyboardInterrupt, SystemExit):
        account()
        # A signal can land inside a step: keep the last published valid slot.
        transition(entry, "interrupted", "signal_or_keyboard_interrupt")
        entry["attempts"][-1]["status"] = "interrupted"
        persist()
        return None
    except Exception as error:
        account()
        transition(entry, "engineering_failed", type(error).__name__ + ": " + str(error))
        entry["attempts"][-1]["status"] = "engineering_failed"
        persist()
        raise


@contextlib.contextmanager
def study_lock(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".runner.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another process holds the study lock") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def verify_engineering_tests(root: Path, output: Path, identity: dict) -> dict:
    """Before future execution, bind the complete small-test suite to this code."""
    path = output / "engineering_validation.json"
    if path.exists():
        receipt = read_json(path)
        if receipt["identity"] != identity or not receipt["passed"]:
            raise ValueError("engineering test receipt mismatch")
        return receipt
    temporary = tempfile.mkdtemp(prefix="stage2c-engineering-tests-")
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", temporary],
        cwd=root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", MPLBACKEND="Agg"),
        text=True, capture_output=True, check=False,
    )
    matches = re.findall(r"\b(\d+) passed\b", completed.stdout)
    receipt = {"identity": identity, "passed": completed.returncode == 0 and bool(matches),
               "passed_count": int(matches[-1]) if matches else None,
               "output": completed.stdout + completed.stderr,
               "elapsed_seconds": time.perf_counter() - started,
               "temporary_artifact_bytes": directory_bytes(Path(temporary)),
               "temporary_directory": temporary, "paper_scale_simulation_executed": False}
    write_json(path, receipt, replace=False)
    if not receipt["passed"]:
        raise RuntimeError("engineering tests failed; no confirmatory simulation started")
    return receipt


class Study:
    def __init__(self, root: Path, output: Path, *, dry_run: bool = False):
        self._session_start = time.perf_counter()
        self._prior_elapsed = 0.0
        self.root, self.output = root.resolve(), output.resolve()
        validate_output(self.root, self.output)
        self.identity = build_identity(self.root, self.output)
        preflight_path = self.output / "storage_preflight.json"
        if preflight_path.exists():
            self.storage_measurement = read_json(preflight_path)
            if self.storage_measurement.get("source_hash") != self.identity["source_hash"]:
                raise ValueError("storage-only preflight source identity mismatch")
        else:
            with tempfile.TemporaryDirectory(prefix="stage2c-storage-only-") as temporary:
                self.storage_measurement = storage_only_measurement(
                    ColonyConfig.paper_scale(), self.identity, Path(temporary))
            self.storage_measurement["source_hash"] = self.identity["source_hash"]
        self.history = historical_resources(self.root, self.storage_measurement)
        self.progress_path = self.output / "checkpoint/progress_manifest.json"
        self.configurations = [c for seed in SEEDS for c in config_pair(seed, self.output)]
        self.rows = planned_rows()
        for seed in SEEDS:
            audit_pair(*config_pair(seed, self.output))
        if self.progress_path.exists():
            self.progress = read_json(self.progress_path)
            self._prior_elapsed = self.progress["elapsed_seconds"]
            if self.progress["identity"] != self.identity:
                raise ValueError("study source/input/environment identity mismatch")
            if [(r["seed"], r["rule"]) for r in self.progress["runs"]] != [(s, r) for s in SEEDS for r in RULES]:
                raise ValueError("progress seed manifest mismatch")
            if read_json(self.output / "seed_manifest.json") != seed_manifest():
                raise ValueError("seed manifest changed")
            manifest = read_json(self.output / "config_manifest.json")
            if (manifest["configurations"] != self._config_entries() or manifest["identity"] != self.identity
                    or manifest["late_window"] != [9000, 10000]):
                raise ValueError("config manifest changed")
            self.refresh_rows()
        else:
            # Never initialise over unidentified files from an earlier attempt.
            existing = [p for p in self.output.iterdir() if p.name != ".runner.lock"] if self.output.exists() else []
            if existing:
                raise FileExistsError("output has files but no recognised progress manifest")
            self.progress = new_progress(self.identity)
            self.output.mkdir(parents=True, exist_ok=True)
            write_json(preflight_path, self.storage_measurement, replace=False)
            write_json(self.output / "seed_manifest.json", seed_manifest(), replace=False)
            write_json(self.output / "config_manifest.json", {
                "identity": self.identity, "configurations": self._config_entries(),
                "initialisation_hashes": [],
                "pair_audits": [audit_pair(*config_pair(seed, self.output)) for seed in SEEDS],
                "late_window": [9000, 10000], "dry_run": dry_run,
            }, replace=False)
            self.persist()
        write_metric_tables(self.output, self.rows)

    def _config_entries(self):
        return [{"seed": c.seed, "rule": c.follower_direction_rule,
                 "config": dict(behavioural_config(c), output_dir=c.output_dir),
                 "config_hash": hash_value(behavioural_config(c))} for c in self.configurations]

    def persist(self):
        self.progress["elapsed_seconds"] = self._prior_elapsed + time.perf_counter() - self._session_start
        manifest_path = self.output / "config_manifest.json"
        if manifest_path.exists():
            manifest = read_json(manifest_path)
            if manifest["identity"] != self.identity or manifest["configurations"] != self._config_entries():
                raise ValueError("configuration manifest changed during execution")
            manifest["initialisation_hashes"] = [
                {"seed": row["seed"], "rule": row["rule"],
                 "initial_state_hash": (row["initial_identity"] or {}).get("initial_state_hash"),
                 "turn_schedule_hash": (row["initial_identity"] or {}).get("turn_schedule_hash"),
                 "availability": "available" if row["initial_identity"] else "unavailable",
                 "reason": "" if row["initial_identity"] else "not_initialised"}
                for row in self.progress["runs"]]
            write_json(manifest_path, manifest)
        write_json(self.progress_path, self.progress)

    def refresh_rows(self):
        for index, (entry, config) in enumerate(zip(self.progress["runs"], self.configurations)):
            completed = Path(config.output_dir) / "completed"
            if completed.exists():
                self.rows[index] = _completed_record(completed, config, self.identity)
                if entry["status"] != "completed":
                    _bind_completed_entry(entry, completed, config)
            else:
                self.rows[index]["status"] = entry["status"]
                for metric in self.rows[index]["metrics"].values():
                    metric["reason"] = entry["status"] + "_no_complete_result"

    def resources(self):
        self.persist()
        done = [r for r in self.progress["runs"] if r["status"] == "completed"]
        samples = []
        for entry, config in zip(self.progress["runs"], self.configurations):
            if entry["status"] != "completed":
                continue
            completed = Path(config.output_dir) / "completed"
            checkpoint = completed / "final_checkpoint.zip"
            samples.append({
                "seconds": entry["elapsed_seconds"],
                "retained_output_bytes": directory_bytes(completed) - checkpoint.stat().st_size,
                "retained_checkpoint_bytes": checkpoint.stat().st_size,
            })
        pilot_observed = all(r["status"] == "completed" for r in self.progress["runs"][:2])
        seconds = max((sample["seconds"] for sample in samples),
                      default=self.history["run_seconds"])
        retained_output = max(
            (sample["retained_output_bytes"] for sample in samples),
            default=self.history["retained_completed_run_bytes"])
        retained_checkpoint = max(
            (sample["retained_checkpoint_bytes"] for sample in samples),
            default=self.history["retained_checkpoint_bytes_per_completed_run"])
        # Use historical bound until the entire first pair is available.
        if not pilot_observed:
            seconds = max(seconds, self.history["run_seconds"])
            retained_output = max(
                retained_output, self.history["retained_completed_run_bytes"])
            retained_checkpoint = max(
                retained_checkpoint,
                self.history["retained_checkpoint_bytes_per_completed_run"])
        validation_path = self.output / "engineering_validation.json"
        test_bytes = read_json(validation_path)["temporary_artifact_bytes"] if validation_path.exists() else 0
        shared_remaining = sum(
            not (self.output / "runs" / str(seed) / "shared_seed_artifact.zip").is_file()
            for seed in SEEDS)
        projection = resource_projection(elapsed_seconds=self.progress["elapsed_seconds"],
            stored_bytes=retained_study_bytes(self.output) + test_bytes,
            remaining_runs=40 - len(done), run_seconds=seconds,
            retained_completed_run_bytes=retained_output,
            retained_checkpoint_bytes_per_completed_run=retained_checkpoint,
            shared_seed_artifact_bytes=self.history["shared_seed_artifact_bytes"],
            remaining_shared_seed_artifacts=shared_remaining,
            active_checkpoint_overlap_bytes=self.history["active_checkpoint_overlap_bytes"],
            completion_publication_overlap_bytes=self.history[
                "completion_publication_overlap_bytes"],
            pilot_observed=pilot_observed,
            assumptions=[
                "only one active run can hold two rotating checkpoint slots",
                "each completed run retains one compact final checkpoint",
                "baseline and PCA share one initial-state and turn-schedule artifact per seed",
                "incremental history chunks are consolidated on completed publication",
                "the 1.5 safety factor applies to every remaining run's retained output and checkpoint",
                "final analysis and figures retain a separate fixed allowance",
            ],
            measurement_status={
                "runtime": "historical_only_no_current_machine_pilot" if not pilot_observed else "current_completed_pair",
                "retained_completed_run_bytes": "historical_category_proxy" if not pilot_observed else "current_completed_run_measured",
                "retained_checkpoint_bytes_per_completed_run": self.storage_measurement["measurement_status"] if not pilot_observed else "current_completed_run_measured",
                "shared_seed_artifact_bytes": self.storage_measurement["measurement_status"],
                "active_checkpoint_overlap_bytes": self.storage_measurement["measurement_status"],
                "stored_bytes": "current_filesystem_measured_excluding_active_transient_files",
            })
        projection.update(historical_evidence=self.history, environment=self.identity["environment"],
                          storage_only_preflight=self.storage_measurement,
                          per_run=[{"seed": entry["seed"], "rule": entry["rule"], "status": entry["status"],
                                    "elapsed_seconds": entry["elapsed_seconds"], "time_step": entry["time"],
                                    "retained_bytes": directory_bytes(Path(config.output_dir))}
                                   for entry, config in zip(self.progress["runs"], self.configurations)])
        self.progress["resource_history"].append(projection)
        write_json(self.output / "runtime.json", projection)
        self.persist()
        return projection

    def execute(self, mode: str, *, resume: bool = False) -> dict:
        if mode not in ("pilot", "full"):
            raise ValueError("execution mode must be pilot or full")
        if platform.system() != "Darwin":
            raise RuntimeError("formal execution is restricted to Mac CPU")
        if not self.identity["runner_worktree_clean"]:
            raise RuntimeError("formal execution requires a clean committed runner")
        if self.resources()["action"] == "pause":
            return {"status": "paused", "runtime": read_json(self.output / "runtime.json")}
        verify_engineering_tests(self.root, self.output, self.identity)
        for index in range(2 if mode == "pilot" else 40):
            if index == 2 and not all(r["status"] == "completed" for r in self.progress["runs"][:2]):
                raise RuntimeError("resource pilot pair is incomplete")
            if self.resources()["action"] == "pause":
                self.progress["study_state"] = "paused"
                self.persist()
                return {"status": "paused", "runtime": read_json(self.output / "runtime.json")}
            if build_identity(self.root, self.output) != self.identity:
                raise ValueError("protected source/input changed before run")
            entry, config = self.progress["runs"][index], self.configurations[index]
            row = run_one(config, Path(config.output_dir), self.identity, entry, resume=resume,
                          persist=self.persist, resource_check=self.resources,
                          expected_initial=self.rows[index - 1]["initial_identity"] if index % 2 else None)
            self.refresh_rows()
            write_metric_tables(self.output, self.rows)
            if row is None:
                self.progress["study_state"] = "paused"
                self.persist()
                return {"status": "paused", "reason": entry["reason"]}
            if index % 2:
                if self.rows[index - 1]["initial_identity"] != row["initial_identity"]:
                    raise ValueError("paired initial state or turn schedule mismatch")
            if build_identity(self.root, self.output) != self.identity:
                raise ValueError("protected source/input changed after run")
        self.progress["study_state"] = "pilot_complete" if mode == "pilot" else "completed"
        self.persist()
        runtime = self.resources()
        if mode == "full":
            if runtime["action"] == "pause":
                return {"status": "paused", "runtime": runtime, "final_verdict_available": False}
            return self.analyse()
        return {"status": "pilot_complete", "runtime": runtime, "final_verdict_available": False}

    def analyse(self) -> dict:
        self.refresh_rows()
        if any(row["status"] != "completed" or not row["engineering_valid"] for row in self.rows):
            raise ValueError("analyse requires all 20 complete valid pairs")
        if build_identity(self.root, self.output) != self.identity:
            raise ValueError("source/input changed before analysis")
        validation = read_json(self.output / "engineering_validation.json")
        if validation["identity"] != self.identity or not validation["passed"]:
            raise ValueError("valid engineering test evidence required for final analysis")
        projection = self.resources()
        if projection["action"] == "pause":
            return {"status": "paused", "runtime": projection, "final_verdict_available": False}
        for row, config in zip(self.rows, self.configurations):
            if row["config_hash"] != hash_value(behavioural_config(config)) or row["horizon"] != 10000 or row["late_window"] != [9000, 10000]:
                raise ValueError("analysis requires the frozen full-size design")
        summary = analyse_rows(self.rows)
        if not summary["final_verdict_available"]:
            raise ValueError("complete paired identity evidence is missing")
        final = self.output / "analysis"
        if final.exists():
            if read_json(final / "summary.json") != summary:
                raise ValueError("existing final analysis differs; refusing overwrite")
            top_summary = self.output / "summary.json"
            if top_summary.exists():
                if read_json(top_summary) != summary:
                    raise ValueError("top-level summary changed")
            else:
                write_json(top_summary, summary, replace=False)
            return summary
        stage = Path(tempfile.mkdtemp(prefix="analysis-", dir=self.output))
        write_metric_tables(stage, self.rows)
        write_json(stage / "summary.json", summary, replace=False)
        write_comparison_figures(stage, self.rows, summary)
        lines = ["# Stage 2C paired confirmation", "", NOTICE, "",
                 "Mechanism improvement: " + summary["mechanism_improvement"],
                 "Scientific conclusion: " + summary["scientific_conclusion"],
                 "Fig. 4 candidate: " + summary["fig4_candidate"], "",
                 "These conclusions apply only to the 20 registered seeds and frozen provisional implementation.",
                 "Conflicting indicators and missing observations cannot compensate for failed mechanism gates.", "",
                 "All per-seed metrics, denominators, censoring and differences: per_seed_metrics.csv and paired_comparison.csv.",
                 "All thresholds, bootstrap intervals, failures and per-seed candidate checks: summary.json.", "",
                 "The primary endpoint is the equal-seed mean PCA-minus-baseline difference in mean psi over t=9000..10000 inclusive.",
                 "Follower late-window order requires at least five followers at every late-window sample; other sensing and leg means cover the full run.",
                 "Full endpoint definitions and fixed PASS/FAIL/MIXED interpretation: " + str(self.root / PREREGISTRATION_PATH), "",
                 "| Seed | Baseline psi | PCA psi | Delta psi | Delivery ratio |", "|---|---|---|---|---|"]
        for pair in summary["paired_rows"]:
            lines.append("| " + " | ".join(str(pair[k]) for k in
                ("seed", "late_window_mean_psi_baseline", "late_window_mean_psi_pca", "late_window_mean_psi_delta", "delivery_ratio")) + " |")
        import shlex
        output_option = " --output-dir " + shlex.quote(str(self.output))
        lines.extend(["", "## Reproduction", "", "```bash",
                      "cd " + shlex.quote(str(self.root)),
                      "git checkout " + self.identity["runner_commit"],
                      "python3 -m pip install -r requirements.txt",
                      "./run_stage2c.sh --mode dry-run",
                      "./run_stage2c.sh --mode pilot" + output_option,
                      "./run_stage2c.sh --mode full --resume" + output_option,
                      "./run_stage2c.sh --mode analyse" + output_option, "```", "",
                      "Exact environment, preregistration, source/input/configuration hashes: ../config_manifest.json.",
                      "Accumulated resource costs and pauses: ../runtime.json and ../checkpoint/progress_manifest.json."])
        atomic_write(stage / "REPORT.md", ("\n".join(lines) + "\n").encode(), replace=False)
        if build_identity(self.root, self.output) != self.identity:
            raise ValueError("source/input changed during analysis")
        os.rename(stage, final)
        # Stable top-level summary contract; publication occurs only after complete analysis.
        write_json(self.output / "summary.json", summary, replace=False)
        self.persist()
        self.resources()
        return summary


def dry_run(root: Path, output: Path | None = None) -> dict:
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="stage2c-dry-run-"))
    output = output.resolve()
    temp_roots = (Path(tempfile.gettempdir()).resolve(), Path("/private/tmp"), Path("/tmp").resolve())
    if not any(parent == output or parent in output.parents for parent in temp_roots) or root.resolve() in output.parents:
        raise ValueError("dry-run output must be a temporary directory outside the project")
    with study_lock(output):
        study = Study(root, output, dry_run=True)
        projection = study.resources()
    return {"mode": "dry-run", "output_dir": str(output), "planned_runs": 40,
            "simulation_started": False, "scientific_metrics_generated": False,
            "final_verdict_available": False, "runtime": projection}
