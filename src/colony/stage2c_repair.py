"""Explicit, zero-scientific-step preflight repair with immutable evidence.

No simulation constructor, step, pilot, full run or scientific analyser is called.
An immutable intent and replacement bundle make partial publication recoverable.
"""
from __future__ import annotations

import fcntl
import io
import json
import os
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

from .stage2c import (Study, audit_pair, build_identity, config_pair, directory_bytes,
                     git, new_progress, validate_output, verify_engineering_tests)
from .stage2c_analysis import SEEDS, metric_table_bytes, planned_rows, seed_manifest
from .stage2c_checkpoint import (atomic_write, behavioural_config, digest_bytes,
                                hash_value, json_bytes, read_json, write_json)
from .stage2c_storage import sha256_file

FILES = ("config_manifest.json", "checkpoint/progress_manifest.json", "seed_manifest.json",
         "storage_preflight.json", "runtime.json", "engineering_validation.json",
         "per_seed_metrics.csv", "paired_comparison.csv")
ATTEMPT = "engineering_failures/attempt-01"


def _json(data: bytes):
    return json.loads(data, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def _hashes(payload: dict[str, bytes]) -> dict:
    return {name: {"bytes": len(raw), "sha256": digest_bytes(raw)}
            for name, raw in sorted(payload.items())}


def _once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("immutable repair evidence differs: " + str(path))
    else:
        atomic_write(path, data, replace=False)


def _config_entries(output: Path) -> list:
    return [{"seed": c.seed, "rule": c.follower_direction_rule,
             "config": dict(behavioural_config(c), output_dir=c.output_dir),
             "config_hash": hash_value(behavioural_config(c))}
            for seed in SEEDS for c in config_pair(seed, output)]


def _zero_state(payload: dict[str, bytes], output: Path, identity: dict) -> None:
    """Exact planned schemas, including null references and empty attempts."""
    progress = _json(payload["checkpoint/progress_manifest.json"])
    if not np.isfinite(progress["elapsed_seconds"]) or progress["elapsed_seconds"] < 0:
        raise ValueError("invalid zero-step elapsed accounting")
    if (progress["schema_version"] != 1 or progress["identity"] != identity
            or progress["study_state"] != "planned" or progress["completed_samples"] != []
            or progress["runs"] != new_progress(identity)["runs"]):
        raise ValueError("repair requires all 40 exact planned zero-step records")
    config = _json(payload["config_manifest.json"])
    initial = [{"seed": e["seed"], "rule": e["rule"], "initial_state_hash": None,
                "turn_schedule_hash": None, "availability": "unavailable",
                "reason": "not_initialised"} for e in progress["runs"]]
    if (config["identity"] != identity or config["configurations"] != _config_entries(output)
            or config["initialisation_hashes"] != initial or config["late_window"] != [9000, 10000]
            or config["dry_run"] is not False
            or config["pair_audits"] != [audit_pair(*config_pair(s, output)) for s in SEEDS]):
        raise ValueError("repair configuration or initial identity mismatch")
    if _json(payload["seed_manifest.json"]) != seed_manifest():
        raise ValueError("repair seed/rule manifest mismatch")
    for name, raw in metric_table_bytes(planned_rows()).items():
        if payload[name] != raw:
            raise ValueError("repair refuses scientific or noncanonical metric tables")
    storage = _json(payload["storage_preflight.json"])
    if (storage["source_hash"] != identity["source_hash"]
            or storage["simulation_steps_executed"] != 0
            or storage["scientific_seed_used"] is not False
            or storage["storage_fixture_seed"] != 991337):
        raise ValueError("repair storage preflight identity or scientific state mismatch")
    runtime = _json(payload["runtime.json"])
    if (runtime["storage_only_preflight"] != storage or runtime["remaining_runs"] != 40
            or runtime["current_machine_pilot_observed"] is not False
            or runtime["safety_factor"] != 1.5 or runtime["time_limit_seconds"] != identity.get("resource_amendment", {}).get("effective_time_limit_seconds", 14400)
            or runtime["storage_limit_bytes"] != 2_000_000_000
            or len(runtime["per_run"]) != 40):
        raise ValueError("repair runtime preflight mismatch")
    for row, entry in zip(runtime["per_run"], progress["runs"]):
        if any(row[k] != entry[k] for k in ("seed", "rule", "status", "elapsed_seconds")) or row["time_step"] != 0 or row["retained_bytes"] != 0:
            raise ValueError("repair runtime contains scientific state")
    for prior in progress["resource_history"]:
        if (prior["remaining_runs"] != 40 or prior["current_machine_pilot_observed"] is not False
                or prior["storage_only_preflight"] != storage
                or prior["per_run"] != runtime["per_run"]):
            raise ValueError("repair resource history contains inconsistent scientific state")


def _failed_receipt(payload: dict[str, bytes]) -> tuple[dict, list[str]]:
    receipt = _json(payload["engineering_validation.json"])
    if receipt["passed"] is not False or receipt["paper_scale_simulation_executed"] is not False:
        raise ValueError("repair requires a failed non-scientific engineering receipt")
    if not isinstance(receipt["output"], str):
        raise ValueError("missing complete engineering test output")
    failures = re.findall(r"^FAILED\s+(\S+)", receipt["output"], re.MULTILINE)
    failed_count = re.findall(r"\b(\d+) failed\b", receipt["output"])
    passed_count = re.findall(r"\b(\d+) passed\b", receipt["output"])
    if (not failures or not failed_count or int(failed_count[-1]) != len(failures)
            or not passed_count or int(passed_count[-1]) != receipt["passed_count"]):
        raise ValueError("incomplete or inconsistent failed engineering output")
    for key in ("elapsed_seconds", "temporary_artifact_bytes"):
        if not np.isfinite(receipt[key]) or receipt[key] < 0:
            raise ValueError("invalid failed engineering resource evidence")
    if not isinstance(receipt["temporary_directory"], str):
        raise ValueError("missing engineering temporary-directory evidence")
    if "exit_code" in receipt and (not isinstance(receipt["exit_code"], int) or receipt["exit_code"] == 0):
        raise ValueError("failed engineering exit code is inconsistent")
    return receipt, failures


def _passed_receipt(receipt: dict, identity: dict) -> None:
    counts = re.findall(r"\b(\d+) passed\b", receipt["output"])
    if (receipt["identity"] != identity or receipt["passed"] is not True
            or receipt["paper_scale_simulation_executed"] is not False
            or receipt.get("exit_code") != 0 or not counts
            or int(counts[-1]) != receipt["passed_count"] or receipt["passed_count"] < 1):
        raise ValueError("new engineering preflight failed or is inconsistent; preserve it")


@lru_cache(maxsize=8)
def _committed_sources(root: Path, commit: str) -> tuple:
    """Git commits are immutable; avoid re-reading every blob at each phase."""
    names = git(root, "ls-tree", "-r", "--name-only", commit, "--",
                "src", "scripts", "tests", "run_stage2c.sh", "requirements.txt").decode().splitlines()
    return tuple((name, digest_bytes(git(root, "show", f"{commit}:{name}")))
                 for name in names if name.endswith(".py")
                 or name in ("run_stage2c.sh", "requirements.txt"))


def _old_identity(root: Path, old: dict, current: dict) -> None:
    for group in ("source", "input"):
        if hash_value(old[group + "_hashes"]) != old[group + "_hash"]:
            raise ValueError("old identity hash map mismatch")
    for key in ("preregistration_commit", "stage2b_implementation_commit", "protocol_input_commit",
                "preregistration_hash", "input_hash", "frozen_source_hashes"):
        if old[key] != current[key]:
            raise ValueError("repair cannot change protected scientific identity")
    commit = old["runner_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not old["runner_worktree_clean"]:
        raise ValueError("old runner identity is not a committed clean source")
    if old["source_hashes"] != dict(_committed_sources(root, commit)):
        raise ValueError("incomplete or mismatched old committed source identity")


def _layout(output: Path, *, transaction: bool) -> None:
    """Fail closed on extra files/directories, symlinks and scientific state."""
    allowed_dirs = {"checkpoint"}
    if transaction:
        allowed_dirs.update({"engineering_failures", ATTEMPT, ATTEMPT + "/files",
                             ATTEMPT + "/files/checkpoint"})
    allowed_files = set(FILES) | {".runner.lock"}
    if transaction:
        allowed_files |= {ATTEMPT + "/" + n for n in (
            "intent.json", "failure_receipt.json", "replacement.zip", "complete.json")}
        allowed_files |= {ATTEMPT + "/files/" + n for n in FILES}
    for path in output.rglob("*"):
        name = path.relative_to(output).as_posix()
        if path.is_symlink():
            raise ValueError("repair refuses symlinks")
        # Atomic-write leftovers never replace evidence; retain and charge them.
        pending = transaction and path.is_file() and path.name.startswith(".") and path.name.endswith(".tmp") and any(
            path.parent == (output / n).parent and path.name.startswith("." + Path(n).name + ".") for n in allowed_files)
        if (path.is_dir() and name not in allowed_dirs) or (not path.is_dir() and name not in allowed_files and not pending):
            raise ValueError("repair refuses unexpected or scientific state: " + name)


def _archive_payload(attempt: Path, intent: dict) -> dict:
    payload = {name: (attempt / "files" / name).read_bytes() for name in FILES}
    if _hashes(payload) != intent["original_files"]:
        raise ValueError("archived preflight checksum mismatch")
    return payload


def verify_repair_archive(output: Path, *, require_complete: bool = True,
                          engineering_validation_bytes: bytes | None = None) -> int:
    """Also used by Study: an unfinished repair may never enter pilot/full."""
    parent = output / "engineering_failures"
    if not parent.exists():
        return 0
    if sorted(p.name for p in parent.iterdir()) != ["attempt-01"]:
        raise ValueError("unrecognised engineering failure archive")
    attempt = output / ATTEMPT
    intent = read_json(attempt / "intent.json")
    _archive_payload(attempt, intent)
    receipt = read_json(attempt / "failure_receipt.json")
    if receipt["intent_sha256"] != sha256_file(attempt / "intent.json") or receipt["files"] != intent["original_files"]:
        raise ValueError("failure receipt/archive mismatch")
    if require_complete:
        if not (attempt / "complete.json").exists():
            raise ValueError("preflight repair is incomplete; explicit repair-preflight required")
        complete = read_json(attempt / "complete.json")
        if (complete["identity"] != intent["new_identity"]
                or complete["failure_receipt_sha256"] != sha256_file(attempt / "failure_receipt.json")
                or complete["replacement_sha256"] != sha256_file(attempt / "replacement.zip")
                or complete["engineering_validation_sha256"] != (digest_bytes(engineering_validation_bytes)
                    if engineering_validation_bytes is not None else sha256_file(output / "engineering_validation.json"))):
            raise ValueError("repair completion receipt mismatch")
    return int(receipt["old_engineering_temporary_bytes"])


def _replacement(root: Path, output: Path, identity: dict, carry: float) -> bytes:
    # Prepare in isolation. Publishing one immutable bundle precedes all root
    # replacement, so a crash cannot produce a second, contradictory generation.
    with tempfile.TemporaryDirectory(prefix="stage2c-repair-build-") as temporary:
        study = Study(root, Path(temporary), dry_run=True)
        if study.identity != identity:
            raise ValueError("current source changed while preparing repair")
        study.configurations = [c for s in SEEDS for c in config_pair(s, output)]
        manifest = read_json(study.output / "config_manifest.json")
        manifest.update(configurations=study._config_entries(), dry_run=False)
        write_json(study.output / "config_manifest.json", manifest)
        study._prior_elapsed = carry
        study.resources()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in FILES:
                if name != "engineering_validation.json":
                    archive.writestr(name, (study.output / name).read_bytes())
        return buffer.getvalue()


def _bundle(attempt: Path) -> dict:
    with zipfile.ZipFile(attempt / "replacement.zip") as archive:
        if (set(archive.namelist()) != set(FILES) - {"engineering_validation.json"}
                or len(archive.namelist()) != len(FILES) - 1
                or sum(i.file_size for i in archive.infolist()) > 100_000_000):
            raise ValueError("invalid repair replacement bundle")
        return {name: archive.read(name) for name in archive.namelist()}


def repair_preflight(root: Path, output: Path) -> dict:
    """Repair one zero-step failure; never initialise a scientific run."""
    root, output = root.resolve(), output.resolve()
    validate_output(root, output)
    if not output.is_dir() or not (output / ".runner.lock").is_file():
        raise ValueError("repair requires an existing recognised preflight directory")
    identity = build_identity(root, output)
    if not identity["runner_worktree_clean"]:
        raise ValueError("repair requires committed code and a clean worktree outside the study")
    # Read-only open: even a refused repair must not create a lock or directory.
    with (output / ".runner.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            return _repair_locked(root, output, identity)
        except (KeyError, TypeError, FileNotFoundError, zipfile.BadZipFile) as error:
            raise ValueError("incomplete or corrupt preflight repair evidence") from error


def _repair_locked(root: Path, output: Path, identity: dict) -> dict:
    attempt = output / ATTEMPT
    intent_path = attempt / "intent.json"
    transaction = (output / "engineering_failures").exists()
    _layout(output, transaction=transaction)
    if (attempt / "complete.json").exists():
        verify_repair_archive(output)
        raise ValueError("completed preflight must not be repaired again")
    if intent_path.exists():
        intent = read_json(intent_path)
        if intent["new_identity"] != identity:
            raise ValueError("interrupted repair is bound to a different current identity")
        # Before archive completion all originals still exist at the root.
        payload = (_archive_payload(attempt, intent) if (attempt / "failure_receipt.json").exists()
                   else {name: (output / name).read_bytes() for name in FILES})
        if _hashes(payload) != intent["original_files"]:
            raise ValueError("original failure changed during repair")
    else:
        if transaction and any(p.is_file() for p in (output / "engineering_failures").rglob("*")):
            raise ValueError("unrecognised partial repair without intent")
        payload = {name: (output / name).read_bytes() for name in FILES}
        old, failures = _failed_receipt(payload)
        _zero_state(payload, output, old["identity"])
        _old_identity(root, old["identity"], identity)
        intent = {"schema_version": 1, "old_identity": old["identity"], "new_identity": identity,
                  "original_files": _hashes(payload), "started_at_epoch": time.time(),
                  "failure_time_utc": old.get("finished_at_utc") or datetime.fromtimestamp((output / "engineering_validation.json").stat().st_mtime, timezone.utc).isoformat(),
                  "failure_time_basis": "engineering_receipt" if old.get("finished_at_utc") else "failed_receipt_filesystem_mtime",
                  "failed_tests": failures}
    old, failures = _failed_receipt(payload)
    if (intent["schema_version"] != 1 or intent["old_identity"] != old["identity"]
            or intent["failed_tests"] != failures or not np.isfinite(intent["started_at_epoch"])):
        raise ValueError("repair intent contradicts the original failed evidence")
    _zero_state(payload, output, old["identity"])
    _old_identity(root, old["identity"], identity)
    new = _bundle(attempt) if (attempt / "replacement.zip").exists() else {}
    if new:
        _zero_state(new, output, identity)
    checked_path = output / "engineering_validation.json"
    finalising = (bool(new) and checked_path.exists()
                  and checked_path.read_bytes() != payload["engineering_validation.json"])
    if finalising:
        _zero_state({name: (output / name).read_bytes() for name in FILES}, output, identity)
    # Every root file must be either the exact old evidence or this transaction's
    # prepared new generation. A new receipt is handled separately below.
    for name in FILES:
        path = output / name
        if name == "engineering_validation.json" and new:
            if path.exists() and path.read_bytes() != payload[name]:
                _passed_receipt(read_json(path), identity)
            continue
        if finalising and name in ("runtime.json", "checkpoint/progress_manifest.json"):
            continue  # Only canonical zero-state accounting may change after tests.
        if not path.is_file() or path.read_bytes() not in (payload[name], new.get(name)):
            raise ValueError("root preflight changed outside the repair transaction")
    # All preconditions above are read-only. Durable evidence publication begins.
    _once(intent_path, json_bytes(intent))
    for name, raw in payload.items():
        _once(attempt / "files" / name, raw)
    _archive_payload(attempt, intent)
    receipt = {"schema_version": 1, "intent_sha256": sha256_file(intent_path),
               "old_runner_commit": old["identity"]["runner_commit"],
               "old_source_hash": old["identity"]["source_hash"], "failed_tests": failures,
               "failure_time_utc": intent["failure_time_utc"], "failure_time_basis": intent["failure_time_basis"],
               "exit_code": old.get("exit_code", 1),
               "exit_code_basis": "engineering_receipt" if "exit_code" in old else "legacy_failed_pytest_then_runner_RuntimeError",
               "old_engineering_temporary_bytes": old["temporary_artifact_bytes"],
               "files": intent["original_files"]}
    _once(attempt / "failure_receipt.json", json_bytes(receipt))
    verify_repair_archive(output, require_complete=False)
    # Persist every new directory entry in the archive's ancestry before any
    # root replacement/removal, not just the individual copied files.
    for directory in (attempt / "files/checkpoint", attempt / "files", attempt,
                      attempt.parent, output):
        fd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    progress = _json(payload["checkpoint/progress_manifest.json"])
    carry = max(progress["elapsed_seconds"], _json(payload["runtime.json"])["elapsed_seconds"]) + old["elapsed_seconds"]
    if not new:
        _once(attempt / "replacement.zip", _replacement(root, output, identity, carry))
        new = _bundle(attempt)
        _zero_state(new, output, identity)
    for name, raw in new.items():
        if (output / name).read_bytes() != raw:
            atomic_write(output / name, raw)
    engineering_path = output / "engineering_validation.json"
    if engineering_path.exists() and engineering_path.read_bytes() == payload["engineering_validation.json"]:
        engineering_path.unlink()  # Full original has already been durably archived and verified.
    verification = verify_engineering_tests(root, output, identity)
    _passed_receipt(verification, identity)
    if not verification["passed"] or build_identity(root, output) != identity:
        raise ValueError("repair tests/source verification failed")
    # Reuse production accounting without reopening an incomplete transaction as
    # a runnable Study. Include all repair elapsed time (including interruption
    # gaps), archives, replacement bundle and previous external test evidence.
    study = object.__new__(Study)
    study.root, study.output, study.identity = root, output, identity
    study._session_start = time.perf_counter()
    study._prior_elapsed = carry + max(0.0, time.time() - intent["started_at_epoch"])
    study.storage_measurement = read_json(output / "storage_preflight.json")
    from .stage2c import historical_resources
    study.history = historical_resources(root, study.storage_measurement)
    study.configurations = [c for s in SEEDS for c in config_pair(s, output)]
    study.rows = planned_rows()
    study.progress_path = output / "checkpoint/progress_manifest.json"
    study.progress = read_json(study.progress_path)
    runtime = study.resources()
    current = {name: (output / name).read_bytes() for name in FILES}
    _zero_state(current, output, identity)
    complete = {"identity": identity, "failure_receipt_sha256": sha256_file(attempt / "failure_receipt.json"),
                "replacement_sha256": sha256_file(attempt / "replacement.zip"),
                "engineering_validation_sha256": sha256_file(engineering_path),
                "status": "preflight_repaired", "simulation_started": False,
                "scientific_metrics_generated": False}
    _once(attempt / "complete.json", json_bytes(complete))
    # The receipt itself is retained data, and must enter the final projection.
    runtime = study.resources()
    return dict(complete, runtime=runtime)
