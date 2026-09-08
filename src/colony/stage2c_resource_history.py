"""Bounded Stage 2C resource history and an explicit administrative migration.

This module never constructs or steps a simulation.  The formal migration is a
fail-closed transaction over administrative metadata.  Existing scientific
artifacts are treated as opaque, immutable files, apart from checkpoint loader
validation of identity, time and population.
"""
from __future__ import annotations

import fcntl
import io
import json
import os
import re
import time
import zipfile
from copy import deepcopy
from pathlib import Path

from .stage2c_checkpoint import (
    atomic_write, behavioural_config, digest_bytes, hash_value, json_bytes,
    load_checkpoint, load_shared_seed_artifact, read_json,
)
from .stage2c_storage import sha256_file

OLD_CONTROL_COMMIT = "2072f86aba72109bd4c6d60645a86cff6aff4211"
BASELINE_EXECUTION_COMMIT = "51504fa4156042f1fbc7468c4db26a64dd16d527"
ATTEMPT = "resource_history_migrations/attempt-01"
PREVIOUS_ARCHIVE = "previous_admin.zip"
PREPARED_ARCHIVE = "prepared_admin.zip"
STATIC_PATH = "resource_history/static_evidence.json"
HISTORY_SCHEMA_VERSION = 2
RECORD_SCHEMA_VERSION = 1
STATIC_SCHEMA_VERSION = 1
MAX_COMPACT_RECORD_BYTES = 2_048
MAX_COMPACT_RECORDS = 4_096
MAX_STATIC_EVIDENCE_BYTES = 1_000_000
STATIC_FIELDS = (
    "assumptions", "calculation_formula", "environment", "historical_evidence",
    "measurement_status", "resource_amendment", "storage_only_preflight",
    "time_calculation_formula",
)
FIXED_STATIC_FIELDS = set(STATIC_FIELDS) - {"measurement_status"}
ADMIN = (
    "config_manifest.json", "checkpoint/progress_manifest.json", "seed_manifest.json",
    "storage_preflight.json", "runtime.json", "engineering_validation.json",
    "per_seed_metrics.csv", "paired_comparison.csv",
)
FORMAL_EXPECTATION = {
    "old_control_commit": OLD_CONTROL_COMMIT,
    "baseline_time": 10_000,
    "pca_time": 7_500,
    "pca_generation": 76,
    "pca_checkpoint": "checkpoint-0.zip",
    "pca_checkpoint_sha256": "dd042505c74127d091eb5ca5ff8c34d75e07841026dbc7608d9ba4645c530d0d",
    "legacy_history_count": 190,
}


def _json(raw: bytes) -> dict:
    return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _hashes(payload: dict[str, bytes]) -> dict:
    return {name: {"bytes": len(raw), "sha256": digest_bytes(raw)}
            for name, raw in sorted(payload.items())}


def _inventory(path: Path) -> dict:
    return {item.relative_to(path).as_posix(): {
                "bytes": item.stat().st_size, "sha256": sha256_file(item)}
            for item in sorted(path.rglob("*")) if item.is_file()}


def inventory_digest(path: Path) -> dict:
    """Return a complete path/size/hash inventory plus one deterministic digest."""
    files = _inventory(Path(path))
    return {"files": files, "file_count": len(files),
            "total_bytes": sum(value["bytes"] for value in files.values()),
            "inventory_sha256": digest_bytes(json_bytes(files))}


def _zip(payload: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name, raw in sorted(payload.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw, compresslevel=9)
    return buffer.getvalue()


def _unzip(raw: bytes, *, expected: set[str] | None = None) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if (len(names) != len(set(names)) or any(name.startswith("/") or ".." in Path(name).parts
                                                 for name in names)
                or sum(item.file_size for item in archive.infolist()) > 1_000_000_000):
            raise ValueError("invalid resource-history archive")
        if expected is not None and set(names) != expected:
            raise ValueError("resource-history archive member mismatch")
        return {name: archive.read(name) for name in names}


def _once(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError("immutable resource-history evidence differs: " + str(path))
    else:
        atomic_write(path, raw, replace=False)


def _fsync(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _record_hashes(records: list[dict]) -> list[str]:
    return [digest_bytes(json_bytes(record)) for record in records]


def _static_value_hash(value) -> str:
    return digest_bytes(json_bytes(value))


def _new_catalogue(projection: dict) -> tuple[dict, dict]:
    objects, references = {}, {}
    for name in STATIC_FIELDS:
        if name not in projection:
            raise ValueError("resource projection is missing static evidence: " + name)
        digest = _static_value_hash(projection[name])
        existing = objects.get(digest)
        if existing is not None and existing != projection[name]:
            raise ValueError("static evidence hash collision")
        objects[digest] = projection[name]
        references[name] = digest
    reference_hash = hash_value(references)
    return {"schema_version": STATIC_SCHEMA_VERSION, "objects": objects,
            "reference_sets": {reference_hash: references}}, reference_hash


def _verify_catalogue(catalogue: dict) -> None:
    if (set(catalogue) != {"schema_version", "objects", "reference_sets"}
            or catalogue["schema_version"] != STATIC_SCHEMA_VERSION):
        raise ValueError("unknown static resource evidence format")
    if not isinstance(catalogue["objects"], dict):
        raise ValueError("invalid static evidence catalogue")
    for digest, value in catalogue["objects"].items():
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or _static_value_hash(value) != digest:
            raise ValueError("static evidence content hash mismatch")
    if not isinstance(catalogue["reference_sets"], dict):
        raise ValueError("invalid static reference-set catalogue")
    for digest, references in catalogue["reference_sets"].items():
        if (not re.fullmatch(r"[0-9a-f]{64}", digest) or hash_value(references) != digest
                or set(references) != set(STATIC_FIELDS)
                or any(value not in catalogue["objects"] for value in references.values())):
            raise ValueError("static reference-set hash or member mismatch")
    if len(json_bytes(catalogue)) > MAX_STATIC_EVIDENCE_BYTES:
        raise ValueError("static resource evidence exceeds its study-wide bound")


def _references(catalogue: dict, projection: dict, prior_records: list[dict]) -> tuple[dict, dict]:
    catalogue = deepcopy(catalogue)
    references = {}
    fixed_prior = {name: {catalogue["reference_sets"][record["static_reference_set"]][name]
                          for record in prior_records}
                   for name in FIXED_STATIC_FIELDS}
    for name in STATIC_FIELDS:
        if name not in projection:
            raise ValueError("resource projection is missing static evidence: " + name)
        digest = _static_value_hash(projection[name])
        if name in FIXED_STATIC_FIELDS and fixed_prior[name] and digest not in fixed_prior[name]:
            raise ValueError("fixed resource evidence changed: " + name)
        if digest in catalogue["objects"] and catalogue["objects"][digest] != projection[name]:
            raise ValueError("static evidence hash collision")
        catalogue["objects"][digest] = projection[name]
        references[name] = digest
    reference_hash = hash_value(references)
    if (reference_hash in catalogue["reference_sets"]
            and catalogue["reference_sets"][reference_hash] != references):
        raise ValueError("static reference-set hash collision")
    catalogue["reference_sets"][reference_hash] = references
    _verify_catalogue(catalogue)
    return catalogue, reference_hash


def _compact_record(projection: dict, sequence: int, reference_set: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", reference_set):
        raise ValueError("invalid static resource reference set")
    dynamic = {name: value for name, value in projection.items()
               if name not in set(STATIC_FIELDS) | {"per_run", "resource_history_bounds"}}
    record = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "sequence": int(sequence),
        "projection_sha256": digest_bytes(json_bytes(projection)),
        "dynamic": dynamic,
        "static_reference_set": reference_set,
        "per_run_sha256": digest_bytes(json_bytes(projection.get("per_run", []))),
    }
    if len(json_bytes(record)) > MAX_COMPACT_RECORD_BYTES:
        raise ValueError("compact resource record exceeds the 2 KiB bound")
    return record


def _legacy_descriptor(progress_raw: bytes, archive_raw: bytes, records: list[dict]) -> dict:
    hashes = _record_hashes(records)
    latest = records[-1]
    return {
        "schema_version": 1,
        "archive_path": ATTEMPT + "/" + PREVIOUS_ARCHIVE,
        "archive_bytes": len(archive_raw),
        "archive_sha256": digest_bytes(archive_raw),
        "progress_member": "checkpoint/progress_manifest.json",
        "progress_manifest_bytes": len(progress_raw),
        "progress_manifest_sha256": digest_bytes(progress_raw),
        "resource_record_count": len(records),
        "ordered_record_hashes_sha256": digest_bytes(json_bytes(hashes)),
        "latest_record_sha256": hashes[-1],
        "latest_action": latest["action"],
        "latest_reasons": latest["reasons"],
    }


def compact_legacy_progress(progress_raw: bytes, archive_raw: bytes,
                            catalogue_raw: bytes) -> bytes:
    """Losslessly bind a legacy list to its archive and return a small active manifest."""
    progress = _json(progress_raw)
    records = progress.get("resource_history")
    if not isinstance(records, list) or not records or not all(isinstance(value, dict) for value in records):
        raise ValueError("legacy resource history must be a non-empty ordered list")
    catalogue = _json(catalogue_raw)
    _verify_catalogue(catalogue)
    progress["resource_history"] = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "legacy": _legacy_descriptor(progress_raw, archive_raw, records),
        "static_evidence": {
            "path": STATIC_PATH, "bytes": len(catalogue_raw),
            "sha256": digest_bytes(catalogue_raw),
        },
        "records": [],
    }
    return json_bytes(progress)


def initialise_compact_history(output: Path, progress: dict, projection: dict) -> None:
    catalogue, _ = _new_catalogue(projection)
    catalogue_raw = json_bytes(catalogue)
    atomic_write(Path(output) / STATIC_PATH, catalogue_raw, replace=False)
    progress["resource_history"] = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "legacy": None,
        "static_evidence": {"path": STATIC_PATH, "bytes": len(catalogue_raw),
                            "sha256": digest_bytes(catalogue_raw)},
        "records": [],
    }


def append_resource_projection(output: Path, progress: dict, projection: dict,
                               identity: dict | None = None) -> dict:
    """Append one bounded record.  Non-empty legacy histories require explicit migration."""
    output = Path(output)
    history = progress.get("resource_history")
    if isinstance(history, list):
        # All legacy studies remain byte/schema compatible and require the explicit
        # E5A transaction.  Only a verified schema-2 manifest may use compact writes.
        history.append(projection)
        return {"format": "legacy_v1", "record_bytes": len(json_bytes(projection))}
    _verify_history_shape(history)
    if len(history["records"]) >= MAX_COMPACT_RECORDS:
        raise ValueError("resource history reached its registered study-wide record bound")
    static_path = output / history["static_evidence"]["path"]
    raw = static_path.read_bytes()
    if len(raw) != history["static_evidence"]["bytes"] or digest_bytes(raw) != history["static_evidence"]["sha256"]:
        raise ValueError("static resource evidence changed")
    catalogue = _json(raw)
    _verify_catalogue(catalogue)
    catalogue, reference_set = _references(catalogue, projection, history["records"])
    new_raw = json_bytes(catalogue)
    if new_raw != raw:
        atomic_write(static_path, new_raw)
    legacy_count = history["legacy"]["resource_record_count"] if history["legacy"] else 0
    record = _compact_record(projection, legacy_count + len(history["records"]), reference_set)
    history["records"].append(record)
    history["static_evidence"].update(bytes=len(new_raw), sha256=digest_bytes(new_raw))
    return {"format": "content_addressed_v2", "record_bytes": len(json_bytes(record)),
            "static_evidence_bytes": len(new_raw)}


def _verify_history_shape(history: dict) -> None:
    if (not isinstance(history, dict)
            or set(history) != {"schema_version", "legacy", "static_evidence", "records"}
            or history["schema_version"] != HISTORY_SCHEMA_VERSION
            or set(history["static_evidence"]) != {"path", "bytes", "sha256"}
            or history["static_evidence"]["path"] != STATIC_PATH
            or not isinstance(history["records"], list)):
        raise ValueError("unknown compact resource history format")


def resource_history_allowance(progress: dict, static_bytes: int | None = None) -> dict:
    history = progress.get("resource_history")
    if not isinstance(history, dict):
        return {"remaining_compact_records": MAX_COMPACT_RECORDS,
                "future_compact_record_bytes": MAX_COMPACT_RECORDS * MAX_COMPACT_RECORD_BYTES,
                "future_static_evidence_bytes": MAX_STATIC_EVIDENCE_BYTES,
                "future_resource_history_bytes": (MAX_COMPACT_RECORDS * MAX_COMPACT_RECORD_BYTES
                                                  + MAX_STATIC_EVIDENCE_BYTES)}
    _verify_history_shape(history)
    remaining = MAX_COMPACT_RECORDS - len(history["records"])
    if remaining < 0:
        raise ValueError("resource history record bound exceeded")
    size = history["static_evidence"]["bytes"] if static_bytes is None else static_bytes
    static_remaining = max(0, MAX_STATIC_EVIDENCE_BYTES - size)
    return {"remaining_compact_records": remaining,
            "future_compact_record_bytes": remaining * MAX_COMPACT_RECORD_BYTES,
            "future_static_evidence_bytes": static_remaining,
            "future_resource_history_bytes": remaining * MAX_COMPACT_RECORD_BYTES + static_remaining}


def _verify_legacy(output: Path, descriptor: dict) -> dict[str, bytes]:
    required = {"schema_version", "archive_path", "archive_bytes", "archive_sha256",
                "progress_member", "progress_manifest_bytes", "progress_manifest_sha256",
                "resource_record_count", "ordered_record_hashes_sha256",
                "latest_record_sha256", "latest_action", "latest_reasons"}
    if set(descriptor) != required or descriptor["schema_version"] != 1:
        raise ValueError("unknown archived resource history format")
    archive_path = output / descriptor["archive_path"]
    raw = archive_path.read_bytes()
    if (len(raw) != descriptor["archive_bytes"] or digest_bytes(raw) != descriptor["archive_sha256"]):
        raise ValueError("archived resource history checksum mismatch")
    payload = _unzip(raw, expected=set(ADMIN))
    progress_raw = payload[descriptor["progress_member"]]
    if (len(progress_raw) != descriptor["progress_manifest_bytes"]
            or digest_bytes(progress_raw) != descriptor["progress_manifest_sha256"]):
        raise ValueError("original progress manifest checksum mismatch")
    old = _json(progress_raw)
    records = old.get("resource_history")
    if (not isinstance(records, list) or len(records) != descriptor["resource_record_count"]
            or not records):
        raise ValueError("archived resource history count mismatch")
    hashes = _record_hashes(records)
    if (digest_bytes(json_bytes(hashes)) != descriptor["ordered_record_hashes_sha256"]
            or hashes[-1] != descriptor["latest_record_sha256"]
            or records[-1].get("action") != descriptor["latest_action"]
            or records[-1].get("reasons") != descriptor["latest_reasons"]
            or payload["runtime.json"] != json_bytes(records[-1])):
        raise ValueError("archived resource history order or latest decision mismatch")
    return payload


def verify_resource_history(output: Path, *, require_latest_runtime: bool = True) -> dict:
    output = Path(output)
    progress = read_json(output / "checkpoint/progress_manifest.json")
    history = progress.get("resource_history")
    _verify_history_shape(history)
    static = history["static_evidence"]
    static_raw = (output / static["path"]).read_bytes()
    if len(static_raw) != static["bytes"] or digest_bytes(static_raw) != static["sha256"]:
        raise ValueError("static evidence file checksum mismatch")
    catalogue = _json(static_raw)
    _verify_catalogue(catalogue)
    legacy_payload = _verify_legacy(output, history["legacy"]) if history["legacy"] else None
    legacy_count = history["legacy"]["resource_record_count"] if history["legacy"] else 0
    seen = set()
    for offset, record in enumerate(history["records"]):
        if (set(record) != {"schema_version", "sequence", "projection_sha256", "dynamic",
                            "static_reference_set", "per_run_sha256"}
                or record["schema_version"] != RECORD_SCHEMA_VERSION
                or record["sequence"] != legacy_count + offset
                or record["sequence"] in seen
                or len(json_bytes(record)) > MAX_COMPACT_RECORD_BYTES
                or not re.fullmatch(r"[0-9a-f]{64}", record["projection_sha256"])
                or not re.fullmatch(r"[0-9a-f]{64}", record["per_run_sha256"])
                or record["static_reference_set"] not in catalogue["reference_sets"]):
            raise ValueError("invalid, duplicate or unordered compact resource record")
        seen.add(record["sequence"])
        for name, digest in catalogue["reference_sets"][record["static_reference_set"]].items():
            if digest not in catalogue["objects"]:
                raise ValueError("compact record has a missing static reference: " + name)
    if len(history["records"]) > MAX_COMPACT_RECORDS:
        raise ValueError("compact resource record bound exceeded")
    if require_latest_runtime and history["records"]:
        runtime = read_json(output / "runtime.json")
        latest = history["records"][-1]
        references = {name: _static_value_hash(runtime[name]) for name in STATIC_FIELDS}
        expected = _compact_record(runtime, latest["sequence"], hash_value(references))
        if expected != latest:
            raise ValueError("latest compact record does not bind runtime.json")
    return {"legacy_archive_verified": legacy_payload is not None,
            "static_objects": len(catalogue["objects"]),
            "static_reference_sets": len(catalogue["reference_sets"]),
            "legacy_records": legacy_count, "compact_records": len(history["records"]),
            "max_record_bytes": max((len(json_bytes(value)) for value in history["records"]), default=0)}


def archived_admin(output: Path) -> dict[str, bytes]:
    """Read the immutable pre-E5A administration without consulting E4 helpers."""
    output = Path(output)
    folder = output / ATTEMPT
    intent = read_json(folder / "intent.json")
    raw = (folder / PREVIOUS_ARCHIVE).read_bytes()
    if (digest_bytes(raw) != intent["previous_archive_sha256"]
            or len(raw) != intent["previous_archive_bytes"]):
        raise ValueError("pre-E5A administrative archive checksum mismatch")
    payload = _unzip(raw, expected=set(ADMIN))
    if _hashes(payload) != intent["previous_files"]:
        raise ValueError("pre-E5A administrative file hash mismatch")
    return payload


def migration_context(output: Path, *, require_complete: bool = True):
    output = Path(output)
    parent = output / "resource_history_migrations"
    if not parent.exists():
        return None
    if (not parent.is_dir() or sorted(item.name for item in parent.iterdir()) != ["attempt-01"]):
        raise ValueError("unknown resource-history migration transaction")
    folder = output / ATTEMPT
    intent = read_json(folder / "intent.json")
    previous = archived_admin(output)
    prepared_raw = (folder / PREPARED_ARCHIVE).read_bytes()
    if (digest_bytes(prepared_raw) != intent["prepared_archive_sha256"]
            or len(prepared_raw) != intent["prepared_archive_bytes"]):
        raise ValueError("prepared resource-history archive checksum mismatch")
    prepared = _unzip(prepared_raw, expected=set(ADMIN) - {"engineering_validation.json", "runtime.json"})
    if _hashes(prepared) != intent["prepared_files"]:
        raise ValueError("prepared administrative file hash mismatch")
    if require_complete:
        receipt_path = folder / "receipt.json"
        if not receipt_path.is_file():
            raise ValueError("resource-history migration incomplete; explicit repair required")
        receipt = read_json(receipt_path)
        flags = {
            "simulation_started": False, "simulation_steps_executed": 0,
            "scientific_metrics_generated": False, "pca_resumed": False,
            "other_seed_initialised": False, "final_scientific_conclusion_available": False,
        }
        if (receipt.get("status") != "resource_history_repaired"
                or receipt.get("schema_version") != 1
                or receipt.get("intent_sha256") != sha256_file(folder / "intent.json")
                or receipt.get("new_identity") != intent["new_identity"]
                or any(receipt.get(name) != value for name, value in flags.items())
                or receipt.get("engineering_validation_sha256") != sha256_file(output / "engineering_validation.json")
                or receipt.get("runtime_sha256") != sha256_file(output / "runtime.json")):
            raise ValueError("resource-history migration receipt mismatch")
        progress = read_json(output / "checkpoint/progress_manifest.json")
        config = read_json(output / "config_manifest.json")
        if (progress.get("identity") != intent["new_identity"]
                or config.get("identity") != intent["new_identity"]
                or progress.get("execution_identity_lineage") != config.get("execution_identity_lineage")
                or receipt.get("lineage_sha256") != hash_value(progress["execution_identity_lineage"])):
            raise ValueError("resource-history root identity or lineage mismatch")
        runtime = read_json(output / "runtime.json")
        if (receipt.get("action") != runtime.get("action")
                or receipt.get("reasons") != runtime.get("reasons")
                or receipt.get("stored_bytes") != runtime.get("stored_bytes")
                or receipt.get("projected_peak_bytes") != runtime.get("projected_peak_additional_bytes")):
            raise ValueError("resource-history receipt decision mismatch")
        _verify_immutable(output, intent["immutable_files"])
        verify_resource_history(output)
    return intent, previous, prepared


def legacy_engineering_validation_bytes(output: Path) -> bytes | None:
    if not (Path(output) / "resource_history_migrations").exists():
        return None
    return archived_admin(Path(output))["engineering_validation.json"]


def _require_committed(root: Path, identity: dict) -> None:
    from .stage2c import git
    from .stage2c_repair import _committed_sources
    if (not identity["runner_worktree_clean"]
            or git(root, "rev-parse", "HEAD").decode().strip() != identity["runner_commit"]
            or dict(_committed_sources(root, identity["runner_commit"])) != identity["source_hashes"]):
        raise ValueError("resource-history migration requires committed clean code")


def control_equivalence(root: Path, old_control: dict, current: dict, *,
                        baseline_identity: dict, rehearsal: bool = False) -> dict:
    from . import stage2c as runner
    from . import stage2c_amendment as amendment
    from .stage2c_repair import _old_identity
    if old_control["runner_commit"] != OLD_CONTROL_COMMIT:
        raise ValueError("unexpected pre-E5A control identity")
    _old_identity(root, old_control, current)
    for key in ("preregistration_hash", "input_hash", "frozen_source_hashes"):
        if old_control[key] != current[key]:
            raise ValueError("resource-history migration changed frozen scientific identity")
    if len(current["frozen_source_hashes"]) != 26:
        raise ValueError("expected 26 frozen scientific source files")
    allowed = {
        "docs/STAGE2C_RESOURCE_HISTORY.md", "scripts/run_stage2c.py",
        "src/colony/stage2c.py", "src/colony/stage2c_amendment.py",
        "src/colony/stage2c_resource_history.py", "tests/test_stage2c_resource_history.py",
    }
    if rehearsal:
        changed = sorted(allowed)
    else:
        changed = runner.git(root, "diff", "--name-only", OLD_CONTROL_COMMIT,
                             current["runner_commit"]).decode().splitlines()
        if not changed or set(changed) - allowed:
            raise ValueError("E5A commit changes files outside the administrative allow-list")
    # This existing proof compares the actual frozen runner functions and metric,
    # checkpoint, streaming and storage definitions against the accepted baseline.
    if baseline_identity.get("runner_commit") != BASELINE_EXECUTION_COMMIT:
        raise ValueError("missing accepted Baseline execution identity")
    scientific = amendment.scientific_equivalence(root, baseline_identity, current)
    checked = {"changed_files": changed, "scientific_equivalence": scientific,
               "preregistration_hash": current["preregistration_hash"],
               "input_hash": current["input_hash"],
               "frozen_source_hashes": current["frozen_source_hashes"],
               "rehearsal": rehearsal}
    return {"checked": checked, "sha256": hash_value(checked)}


def _lineage(previous_progress: dict, current: dict, proof: dict) -> dict:
    prior = previous_progress.get("execution_identity_lineage")
    if not isinstance(prior, dict) or set(prior) < {"identities", "runs", "scientific_equivalence"}:
        raise ValueError("missing E4 execution identity lineage")
    if len(prior["runs"]) != len(previous_progress["runs"]):
        raise ValueError("E4 execution lineage length mismatch")
    identities = deepcopy(prior["identities"])
    if current["runner_commit"] in identities or current["runner_commit"] == OLD_CONTROL_COMMIT:
        raise ValueError("E5A requires a third, distinct control identity")
    identities[current["runner_commit"]] = current
    runs = []
    for index, entry in enumerate(previous_progress["runs"]):
        commit = (current["runner_commit"] if entry["status"] == "planned"
                  else prior["runs"][index]["execution_commit"])
        runs.append({"seed": entry["seed"], "rule": entry["rule"], "execution_commit": commit})
    if (runs[0]["execution_commit"] != BASELINE_EXECUTION_COMMIT
            or runs[1]["execution_commit"] != OLD_CONTROL_COMMIT
            or any(value["execution_commit"] != current["runner_commit"] for value in runs[2:])):
        raise ValueError("three-level execution identity assignment is invalid")
    return {"identities": identities, "runs": runs,
            "scientific_equivalence": deepcopy(prior["scientific_equivalence"]),
            "resource_history_migration": proof}


def execution_identity(root: Path, output: Path, progress: dict, index: int, current: dict) -> dict:
    context = migration_context(output)
    if context is None:
        raise ValueError("missing resource-history migration context")
    intent, previous, _ = context
    if current != intent["new_identity"]:
        raise ValueError("resource-history control identity mismatch")
    old_progress = _json(previous["checkpoint/progress_manifest.json"])
    baseline = old_progress["execution_identity_lineage"]["identities"][BASELINE_EXECUTION_COMMIT]
    proof = control_equivalence(Path(root), old_progress["identity"], current,
                                baseline_identity=baseline,
                                rehearsal=bool(intent.get("rehearsal")))
    expected = _lineage(old_progress, current, proof)
    if progress.get("execution_identity_lineage") != expected:
        raise ValueError("resource-history execution lineage changed")
    binding = expected["runs"][index]
    if (binding["seed"], binding["rule"]) != (progress["runs"][index]["seed"], progress["runs"][index]["rule"]):
        raise ValueError("execution lineage run order changed")
    return expected["identities"][binding["execution_commit"]]


def _baseline_files(complete: Path, entry: dict, config, identity: dict) -> set[str]:
    receipt = read_json(complete / "receipt.json")
    actual = {item.relative_to(complete).as_posix(): sha256_file(item)
              for item in complete.rglob("*") if item.is_file() and item.name != "receipt.json"}
    required = {
        "agent_states.csv", "completed_transport.csv", "config.json",
        "diagnostic_accumulators.json", "events.csv", "final_agents.csv",
        "final_checkpoint.zip", "final_pheromone.npz",
        "history/manifests/history-%08d.json" % entry["checkpoint_generation"],
        "metrics.csv", "pheromone_snapshots.npz", "result.json",
        "role_specific_order.csv", "transition_counts.json",
    }
    if (set(actual) != required or actual != receipt["artifact_hashes"]
            or receipt["identity"] != identity
            or receipt["config_hash"] != hash_value(behavioural_config(config))
            or len(required | {"receipt.json"}) != 15):
        raise ValueError("Baseline 15-artifact receipt validation failed")
    stored = read_json(complete / "config.json")
    stored.pop("output_dir")
    if stored != behavioural_config(config):
        raise ValueError("Baseline configuration changed")
    return required | {"receipt.json"}


def _expected_layout(output: Path, progress: dict, configs: list, baseline_files: set[str]) -> set[str]:
    expected = set(ADMIN) | {".runner.lock"}
    expected |= {"engineering_failures/attempt-01/" + name for name in
                 ("intent.json", "failure_receipt.json", "replacement.zip", "complete.json")}
    expected |= {"engineering_failures/attempt-01/files/" + name for name in ADMIN}
    expected |= {"checkpoint_repairs/attempt-01/" + name for name in
                 ("intent.json", "repair_receipt.json")}
    expected |= {"resource_amendments/attempt-01/" + name for name in
                 ("intent.json", "previous.zip", "prepared.zip", "receipt.json")}
    baseline = Path(configs[0].output_dir)
    expected |= {(baseline / "completed" / name).relative_to(output).as_posix()
                 for name in baseline_files}
    expected.add((baseline.parent / "shared_seed_artifact.zip").relative_to(output).as_posix())
    pca = Path(configs[1].output_dir)
    expected |= {(pca / name).relative_to(output).as_posix()
                 for name in ("checkpoint-0.zip", "checkpoint-1.zip")}
    generation = progress["runs"][1]["checkpoint_generation"]
    expected |= {(pca / "history/manifests" / f"history-{value:08d}.json").relative_to(output).as_posix()
                 for value in range(1, generation + 1)}
    manifest = read_json(pca / progress["runs"][1]["history_manifest"])
    for entries in manifest["streams"].values():
        expected |= {(pca / "history" / entry["path"]).relative_to(output).as_posix()
                     for entry in entries}
    expected |= {(pca / "history" / entry["path"]).relative_to(output).as_posix()
                 for entry in manifest["pheromone_snapshots"]}
    return expected


def _admit(root: Path, output: Path, current: dict, *, expectation: dict | None = None,
           rehearsal: bool = False) -> dict:
    from . import stage2c as runner
    from . import stage2c_amendment as amendment
    from .stage2c_repair import _passed_receipt, verify_repair_archive
    expectation = FORMAL_EXPECTATION if expectation is None else expectation
    payload = {name: (output / name).read_bytes() for name in ADMIN}
    progress = _json(payload["checkpoint/progress_manifest.json"])
    old_control = progress["identity"]
    if (old_control["runner_commit"] != expectation["old_control_commit"]
            or progress["study_state"] != "paused" or len(progress["runs"]) != 40):
        raise ValueError("migration requires the exact paused pre-E5A study")
    e4 = amendment.migration_context(output)
    if e4 is None:
        raise ValueError("valid E4 migration evidence is required")
    e4_intent, e4_previous, _ = e4
    e4_receipt = read_json(output / amendment.ATTEMPT / "receipt.json")
    if (e4_intent["new_identity"] != old_control
            or e4_receipt["runtime"]["action"] != "continue"):
        raise ValueError("E4 receipt must bind the old control and a continue action")
    verify_repair_archive(output, engineering_validation_bytes=e4_previous["engineering_validation.json"])
    amendment._e2(output)
    _passed_receipt(_json(payload["engineering_validation.json"]), old_control)
    baseline_identity = progress["execution_identity_lineage"]["identities"][BASELINE_EXECUTION_COMMIT]
    proof = control_equivalence(root, old_control, current,
                                baseline_identity=baseline_identity, rehearsal=rehearsal)
    configs = [config for seed in runner.SEEDS for config in runner.config_pair(seed, output)]
    manifest = _json(payload["config_manifest.json"])
    expected_entries = [{"seed": config.seed, "rule": config.follower_direction_rule,
                         "config": dict(behavioural_config(config), output_dir=config.output_dir),
                         "config_hash": hash_value(behavioural_config(config))}
                        for config in configs]
    for expected, stored in zip(expected_entries, manifest.get("configurations", [])):
        stored_output = stored.get("config", {}).get("output_dir")
        suffix = (Path("runs") / str(expected["seed"]) / expected["rule"]).as_posix()
        if not isinstance(stored_output, str) or not Path(stored_output).as_posix().endswith(suffix):
            raise ValueError("pre-E5A output routing is not the registered seed/rule path")
        expected["config"]["output_dir"] = stored_output
    if (manifest["identity"] != old_control or manifest["configurations"] != expected_entries
            or manifest.get("execution_identity_lineage") != progress.get("execution_identity_lineage")
            or manifest["late_window"] != [9000, 10000] or manifest["dry_run"] is not False):
        raise ValueError("pre-E5A configuration manifest mismatch")
    baseline_entry, pca_entry = progress["runs"][:2]
    baseline_identity = progress["execution_identity_lineage"]["identities"][BASELINE_EXECUTION_COMMIT]
    if (baseline_entry["status"] != "completed" or baseline_entry["time"] != expectation["baseline_time"]
            or baseline_entry["attempts"] != amendment.BASELINE_ATTEMPTS):
        raise ValueError("Baseline completion state mismatch")
    complete = Path(configs[0].output_dir) / "completed"
    baseline_files = _baseline_files(complete, baseline_entry, configs[0], baseline_identity)
    if (pca_entry["status"] != "interrupted" or pca_entry["time"] != expectation["pca_time"]
            or pca_entry["checkpoint_generation"] != expectation["pca_generation"]
            or pca_entry["checkpoint"] != expectation["pca_checkpoint"]
            or pca_entry["checkpoint_sha256"] != expectation["pca_checkpoint_sha256"]
            or pca_entry["attempts"] != [{"start_time_step": 0, "status": "interrupted"}]
            or pca_entry["initial_identity"] != baseline_entry["initial_identity"]):
        raise ValueError("PCA interrupted state mismatch")
    pca_dir = Path(configs[1].output_dir)
    checkpoint = pca_dir / pca_entry["checkpoint"]
    if sha256_file(checkpoint) != pca_entry["checkpoint_sha256"]:
        raise ValueError("PCA checkpoint checksum mismatch")
    state = load_checkpoint(checkpoint, configs[1], old_control,
                            expected_sha256=pca_entry["checkpoint_sha256"])
    if state.time != expectation["pca_time"] or len(state.ants) != configs[1].n_ants:
        raise ValueError("PCA checkpoint internal state mismatch")
    del state
    shared = load_shared_seed_artifact(
        pca_dir.parent / "shared_seed_artifact.zip", configs[1], old_control,
        expected_sha256=pca_entry["shared_seed_artifact_sha256"])
    if shared["initial_identity"] != pca_entry["initial_identity"]:
        raise ValueError("PCA shared initial identity mismatch")
    prior_slot = pca_dir / ("checkpoint-1.zip" if pca_entry["checkpoint"] == "checkpoint-0.zip"
                            else "checkpoint-0.zip")
    prior = load_checkpoint(prior_slot, configs[1], old_control)
    if prior.time != expectation["pca_time"] - runner.CHECKPOINT_INTERVAL:
        raise ValueError("nonstandard rotating PCA checkpoint")
    del prior
    if progress["runs"][2:] != runner.new_progress(old_control)["runs"][2:]:
        raise ValueError("the remaining 38 runs must be strictly uninitialised")
    runtime = _json(payload["runtime.json"])
    history = progress.get("resource_history")
    if (runtime.get("action") != "pause" or runtime.get("reasons") != ["two_gb_limit"]
            or runtime.get("storage_limit_bytes") != 2_000_000_000
            or runtime.get("safety_factor") != 1.5 or runtime.get("time_limit_seconds") != 28_800
            or not isinstance(history, list) or len(history) != expectation["legacy_history_count"]
            or history[-1] != runtime):
        raise ValueError("exact resource pause/history admission failed")
    expected_layout = _expected_layout(output, progress, configs, baseline_files)
    actual_layout = set(_inventory(output))
    if actual_layout != expected_layout:
        extra = sorted(actual_layout - expected_layout)
        missing = sorted(expected_layout - actual_layout)
        raise ValueError("unknown, missing or nonstandard formal files: extra=%r missing=%r" % (extra, missing))
    return {"payload": payload, "progress": progress, "runtime": runtime,
            "old_control": old_control, "proof": proof, "configs": configs,
            "inventory": _inventory(output), "baseline_complete": complete,
            "pca_checkpoint": checkpoint}


def _prepared(output: Path, admitted: dict, current: dict,
              previous_raw: bytes) -> tuple[bytes, bytes, dict[str, bytes], dict]:
    progress = deepcopy(admitted["progress"])
    progress["identity"] = current
    progress["execution_identity_lineage"] = _lineage(admitted["progress"], current,
                                                       admitted["proof"])
    catalogue, _ = _new_catalogue(admitted["runtime"])
    catalogue_raw = json_bytes(catalogue)
    progress_raw = compact_legacy_progress(
        admitted["payload"]["checkpoint/progress_manifest.json"], previous_raw, catalogue_raw)
    progress = _json(progress_raw)
    progress["identity"] = current
    progress["execution_identity_lineage"] = _lineage(admitted["progress"], current,
                                                       admitted["proof"])
    progress_raw = json_bytes(progress)
    config = _json(admitted["payload"]["config_manifest.json"])
    config["identity"] = current
    config["execution_identity_lineage"] = progress["execution_identity_lineage"]
    storage = _json(admitted["payload"]["storage_preflight.json"])
    storage["source_hash"] = current["source_hash"]
    prepared = {name: raw for name, raw in admitted["payload"].items()
                if name not in {"engineering_validation.json", "runtime.json"}}
    prepared["checkpoint/progress_manifest.json"] = progress_raw
    prepared["config_manifest.json"] = json_bytes(config)
    prepared["storage_preflight.json"] = json_bytes(storage)
    return _zip(prepared), catalogue_raw, prepared, progress


def _intent(admitted: dict, current: dict, previous_raw: bytes, prepared_raw: bytes,
            prepared: dict, catalogue_raw: bytes, *, started: float,
            rehearsal: bool) -> dict:
    immutable = {name: value for name, value in admitted["inventory"].items()
                 if name not in ADMIN}
    return {
        "schema_version": 1,
        "old_control_identity": admitted["old_control"],
        "new_identity": current,
        "control_equivalence": admitted["proof"],
        "rehearsal": rehearsal,
        "started_at_epoch": started,
        "previous_files": _hashes(admitted["payload"]),
        "previous_archive_bytes": len(previous_raw),
        "previous_archive_sha256": digest_bytes(previous_raw),
        "prepared_files": _hashes(prepared),
        "prepared_archive_bytes": len(prepared_raw),
        "prepared_archive_sha256": digest_bytes(prepared_raw),
        "static_evidence_bytes": len(catalogue_raw),
        "static_evidence_sha256": digest_bytes(catalogue_raw),
        "immutable_files": immutable,
        "formal_state": deepcopy(FORMAL_EXPECTATION),
        "declared_flags": {
            "simulation_started": False, "simulation_steps_executed": 0,
            "scientific_metrics_generated": False, "pca_resumed": False,
            "other_seed_initialised": False, "final_scientific_conclusion_available": False,
        },
    }


def _verify_immutable(output: Path, files: dict) -> None:
    for name, expected in files.items():
        path = output / name
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != expected["bytes"]
                or sha256_file(path) != expected["sha256"]):
            raise ValueError("immutable formal evidence changed: " + name)


def _transaction_layout(output: Path, intent: dict) -> None:
    allowed = set(ADMIN) | set(intent["immutable_files"])
    allowed |= {STATIC_PATH, ATTEMPT + "/intent.json", ATTEMPT + "/" + PREVIOUS_ARCHIVE,
                ATTEMPT + "/" + PREPARED_ARCHIVE, ATTEMPT + "/receipt.json"}
    allowed_dirs = set()
    for name in allowed:
        allowed_dirs.update(parent.as_posix() for parent in Path(name).parents if parent.as_posix() != ".")
    for item in output.rglob("*"):
        if item.is_symlink():
            raise ValueError("resource-history migration refuses symlinks")
        if item.is_dir() and item.relative_to(output).as_posix() not in allowed_dirs:
            raise ValueError("unexpected resource-history transaction directory: "
                             + item.relative_to(output).as_posix())
        if item.is_file():
            name = item.relative_to(output).as_posix()
            pending = item.name.startswith(".") and item.name.endswith(".tmp") and any(
                item.parent == (output / value).parent
                and item.name.startswith("." + Path(value).name + ".") for value in allowed)
            if name not in allowed and not pending:
                raise ValueError("unexpected resource-history transaction file: " + name)


def _external_retained_test_bytes(previous: dict) -> int:
    """Count existing historical pytest directories; never delete or rewrite them."""
    receipt = _json(previous["engineering_validation.json"])
    directory = receipt.get("temporary_directory")
    if not isinstance(directory, str):
        return 0
    path = Path(directory)
    if not path.exists() or path.is_symlink() or not path.is_dir():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _projection(root: Path, output: Path, progress: dict, current: dict,
                previous: dict, extra_long_term_bytes: int) -> dict:
    from . import stage2c as runner
    from .stage2c_amendment import retain_resource_floors
    storage = read_json(output / "storage_preflight.json")
    history = retain_resource_floors(runner.historical_resources(root, storage),
                                     _json(previous["runtime.json"]))
    complete = Path(runner.config_pair(runner.SEEDS[0], output)[0].output_dir) / "completed"
    checkpoint_bytes = (complete / "final_checkpoint.zip").stat().st_size
    retained = max(history["retained_completed_run_bytes"],
                   runner.directory_bytes(complete) - checkpoint_bytes)
    checkpoint = max(history["retained_checkpoint_bytes_per_completed_run"], checkpoint_bytes)
    allowance = resource_history_allowance(progress)
    stored = (runner.retained_study_bytes(output) + _external_retained_test_bytes(previous)
              + extra_long_term_bytes)
    result = runner.resource_projection(
        elapsed_seconds=progress["elapsed_seconds"], stored_bytes=stored,
        remaining_runs=38, run_seconds=max(progress["runs"][0]["elapsed_seconds"],
                                           history["run_seconds"]),
        completed_checkpoint_seconds=history["completed_checkpoint_seconds"],
        retained_completed_run_bytes=retained,
        retained_checkpoint_bytes_per_completed_run=checkpoint,
        shared_seed_artifact_bytes=history["shared_seed_artifact_bytes"],
        remaining_shared_seed_artifacts=19,
        active_checkpoint_overlap_bytes=history["active_checkpoint_overlap_bytes"],
        completion_publication_overlap_bytes=history["completion_publication_overlap_bytes"],
        amendment=current["resource_amendment"],
        future_resource_history_allowance_bytes=allowance["future_resource_history_bytes"],
    )
    result.update(
        historical_evidence=history, environment=current["environment"],
        storage_only_preflight=storage,
        per_run=[{"seed": entry["seed"], "rule": entry["rule"], "status": entry["status"],
                  "elapsed_seconds": entry["elapsed_seconds"], "time_step": entry["time"],
                  "retained_bytes": runner.directory_bytes(Path(config.output_dir))}
                 for entry, config in zip(progress["runs"],
                                          [c for seed in runner.SEEDS for c in runner.config_pair(seed, output)])],
        resource_history_bounds=allowance,
    )
    previous_runtime = _json(previous["runtime.json"])
    for name in ("assumptions", "measurement_status"):
        result[name] = deepcopy(previous_runtime[name])
    return result


def _receipt(intent_path: Path, current: dict, validation_path: Path,
             runtime_raw: bytes, progress: dict, projection: dict,
             catalogue_raw: bytes, previous: dict) -> dict:
    history = progress["resource_history"]
    legacy = history["legacy"]
    flags = {
        "simulation_started": False, "simulation_steps_executed": 0,
        "scientific_metrics_generated": False, "pca_resumed": False,
        "other_seed_initialised": False, "final_scientific_conclusion_available": False,
    }
    receipt = {
        "schema_version": 1, "status": "resource_history_repaired",
        "intent_sha256": sha256_file(intent_path), "new_identity": current,
        "old_control_commit": OLD_CONTROL_COMMIT,
        "baseline_execution_commit": BASELINE_EXECUTION_COMMIT,
        "engineering_validation_sha256": sha256_file(validation_path),
        "runtime_sha256": digest_bytes(runtime_raw),
        "lineage_sha256": hash_value(progress["execution_identity_lineage"]),
        "original_progress_manifest_bytes": legacy["progress_manifest_bytes"],
        "original_progress_manifest_sha256": legacy["progress_manifest_sha256"],
        "original_resource_records": legacy["resource_record_count"],
        "previous_archive_bytes": legacy["archive_bytes"],
        "previous_archive_sha256": legacy["archive_sha256"],
        "compact_manifest_bytes": len(json_bytes(progress)),
        "static_evidence_bytes": len(catalogue_raw),
        "static_evidence_sha256": digest_bytes(catalogue_raw),
        "external_historical_test_bytes": _external_retained_test_bytes(previous),
        "action": projection["action"], "reasons": projection["reasons"],
        "stored_bytes": projection["stored_bytes"],
        "projected_peak_bytes": projection["projected_peak_additional_bytes"],
        "storage_headroom_bytes": 2_000_000_000 - projection["projected_peak_additional_bytes"],
        "future_resource_history_bytes": projection["future_resource_history_allowance_bytes"],
        **flags,
    }
    return receipt


def _finalise_fixed_point(root: Path, output: Path, current: dict, previous: dict,
                          progress: dict, intent_path: Path, validation_path: Path,
                          catalogue_raw: bytes) -> tuple[bytes, bytes, bytes, dict]:
    base = 0
    progress = deepcopy(progress)
    # One compact migration decision is the first post-archive resource record.
    progress["elapsed_seconds"] = max(progress["elapsed_seconds"],
                                      _json(previous["checkpoint/progress_manifest.json"])["elapsed_seconds"])
    extra = 0
    for _ in range(60):
        current_static = (output / STATIC_PATH).read_bytes()
        progress["resource_history"]["static_evidence"].update(
            bytes=len(current_static), sha256=digest_bytes(current_static))
        candidate = deepcopy(progress)
        projection = _projection(root, output, candidate, current, previous, extra)
        append_resource_projection(output, candidate, projection, current)
        progress["resource_history"]["static_evidence"] = deepcopy(
            candidate["resource_history"]["static_evidence"])
        runtime_raw = json_bytes(projection)
        progress_raw = json_bytes(candidate)
        receipt = _receipt(intent_path, current, validation_path, runtime_raw, candidate,
                           projection, (output / STATIC_PATH).read_bytes(), previous)
        receipt_raw = json_bytes(receipt)
        # Replace two old root files and add one receipt; every other final byte is
        # already present and counted by retained_study_bytes(output).
        old = (output / "runtime.json").stat().st_size + (output / "checkpoint/progress_manifest.json").stat().st_size
        desired = len(runtime_raw) + len(progress_raw) + len(receipt_raw) - old
        if desired == extra:
            return runtime_raw, progress_raw, receipt_raw, projection
        extra = desired
        base = desired
    raise ValueError("resource-history receipt size did not converge: " + str(base))


def repair_resource_history(root: Path, output: Path) -> dict:
    """Run the explicit production migration.  It cannot run a scientific step."""
    from . import stage2c as runner
    root, output = Path(root).resolve(), Path(output).resolve()
    runner.validate_output(root, output)
    if (not output.is_dir() or not (output / ".runner.lock").is_file()
            or (output / ".runner.lock").is_symlink()):
        raise ValueError("existing locked formal Stage 2C directory required")
    current = runner.build_identity(root, output)
    _require_committed(root, current)
    with (output / ".runner.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _migrate_locked(root, output, current, expectation=FORMAL_EXPECTATION,
                               rehearsal=False)


def _migrate_locked(root: Path, output: Path, current: dict, *, expectation: dict,
                    rehearsal: bool) -> dict:
    from . import stage2c as runner
    from .stage2c_repair import _passed_receipt
    folder = output / ATTEMPT
    intent_path = folder / "intent.json"
    receipt_path = folder / "receipt.json"
    if receipt_path.exists():
        migration_context(output)
        raise ValueError("completed resource-history migration must not be repeated")
    if intent_path.exists():
        intent = read_json(intent_path)
        if intent["new_identity"] != current or bool(intent.get("rehearsal")) != rehearsal:
            raise ValueError("interrupted resource-history transaction identity changed")
        previous_path = folder / PREVIOUS_ARCHIVE
        if previous_path.exists():
            previous_raw = previous_path.read_bytes()
            if (digest_bytes(previous_raw) != intent["previous_archive_sha256"]
                    or len(previous_raw) != intent["previous_archive_bytes"]):
                raise ValueError("interrupted original archive changed")
            previous = _unzip(previous_raw, expected=set(ADMIN))
        else:
            previous = {name: (output / name).read_bytes() for name in ADMIN}
            if _hashes(previous) != intent["previous_files"]:
                raise ValueError("cannot recover missing original archive from changed roots")
            previous_raw = _zip(previous)
        old_progress = _json(previous["checkpoint/progress_manifest.json"])
        baseline = old_progress["execution_identity_lineage"]["identities"][BASELINE_EXECUTION_COMMIT]
        proof = control_equivalence(root, old_progress["identity"], current,
                                    baseline_identity=baseline, rehearsal=rehearsal)
        if proof != intent["control_equivalence"]:
            raise ValueError("interrupted E5A equivalence proof changed")
        prepared_path = folder / PREPARED_ARCHIVE
        if prepared_path.exists():
            prepared_raw = prepared_path.read_bytes()
            prepared = _unzip(prepared_raw, expected=set(ADMIN) - {"engineering_validation.json", "runtime.json"})
        else:
            admitted = {"payload": previous, "progress": old_progress,
                        "old_control": old_progress["identity"], "proof": proof,
                        "runtime": _json(previous["runtime.json"]),
                        "inventory": intent["immutable_files"]}
            prepared_raw, regenerated_catalogue, prepared, _ = _prepared(
                output, admitted, current, previous_raw)
            if digest_bytes(regenerated_catalogue) != intent["static_evidence_sha256"]:
                raise ValueError("cannot reproduce interrupted static evidence")
        catalogue_raw = (output / STATIC_PATH).read_bytes() if (output / STATIC_PATH).exists() else None
        admitted = {"payload": previous, "progress": old_progress,
                    "old_control": old_progress["identity"], "proof": proof,
                    "runtime": _json(previous["runtime.json"]),
                    "inventory": intent["immutable_files"]}
    else:
        if (output / "resource_history_migrations").exists():
            raise ValueError("unrecognised resource-history transaction without intent")
        admitted = _admit(root, output, current, expectation=expectation, rehearsal=rehearsal)
        previous = admitted["payload"]
        previous_raw = _zip(previous)
        prepared_raw, catalogue_raw, prepared, _ = _prepared(output, admitted, current, previous_raw)
        intent = _intent(admitted, current, previous_raw, prepared_raw, prepared,
                         catalogue_raw, started=time.time(), rehearsal=rehearsal)
        if _inventory(output) != admitted["inventory"]:
            raise ValueError("formal study changed during read-only migration preparation")
    if digest_bytes(previous_raw) != intent["previous_archive_sha256"] or _hashes(previous) != intent["previous_files"]:
        raise ValueError("original administrative archive changed")
    if digest_bytes(prepared_raw) != intent["prepared_archive_sha256"] or _hashes(prepared) != intent["prepared_files"]:
        raise ValueError("prepared administrative archive changed")
    _verify_immutable(output, intent["immutable_files"])
    _once(intent_path, json_bytes(intent))
    _once(folder / PREVIOUS_ARCHIVE, previous_raw)
    _once(folder / PREPARED_ARCHIVE, prepared_raw)
    for directory in (folder, folder.parent, output):
        _fsync(directory)
    if catalogue_raw is None:
        _, catalogue_raw, _, _ = _prepared(output, admitted, current, previous_raw)
    _verify_catalogue(_json(catalogue_raw))
    if not (output / STATIC_PATH).exists():
        atomic_write(output / STATIC_PATH, catalogue_raw, replace=False)
    elif (output / STATIC_PATH).read_bytes() != catalogue_raw:
        raise ValueError("interrupted static evidence differs")
    _transaction_layout(output, intent)
    for name, raw in prepared.items():
        path = output / name
        if not path.exists() or path.read_bytes() != raw:
            atomic_write(path, raw)
    validation = output / "engineering_validation.json"
    if validation.exists() and validation.read_bytes() == previous["engineering_validation.json"]:
        validation.unlink()
        _fsync(output)
    receipt = runner.verify_engineering_tests(root, output, current)
    _passed_receipt(receipt, current)
    if not rehearsal and runner.build_identity(root, output) != current:
        raise ValueError("source identity changed during E5A engineering tests")
    progress = read_json(output / "checkpoint/progress_manifest.json")
    expected_lineage = _lineage(_json(previous["checkpoint/progress_manifest.json"]),
                                current, intent["control_equivalence"])
    if (progress.get("execution_identity_lineage") != expected_lineage
            or progress["runs"] != _json(previous["checkpoint/progress_manifest.json"])["runs"]):
        raise ValueError("run state or three-level execution lineage changed during migration")
    progress["elapsed_seconds"] = max(
        progress["elapsed_seconds"],
        _json(previous["checkpoint/progress_manifest.json"])["elapsed_seconds"]
        + max(0.0, time.time() - intent["started_at_epoch"]))
    # The exact old PCA identity must load the immutable checkpoint after all root
    # administrative publication and before the final receipt is made durable.
    pca = progress["runs"][1]
    pca_config = runner.config_pair(runner.SEEDS[0], output)[1]
    state = load_checkpoint(Path(pca_config.output_dir) / pca["checkpoint"], pca_config,
                            expected_lineage["identities"][OLD_CONTROL_COMMIT],
                            expected_sha256=pca["checkpoint_sha256"])
    if state.time != pca["time"]:
        raise ValueError("post-publication PCA checkpoint time changed")
    del state
    runtime_raw, progress_raw, receipt_raw, projection = _finalise_fixed_point(
        root, output, current, previous, progress, intent_path, validation, catalogue_raw)
    _verify_immutable(output, intent["immutable_files"])
    atomic_write(output / "runtime.json", runtime_raw)
    atomic_write(output / "checkpoint/progress_manifest.json", progress_raw)
    _once(receipt_path, receipt_raw)
    context = migration_context(output)
    result = read_json(receipt_path)
    result.update(action=projection["action"], runtime=projection,
                  previous_archive_path=str(folder / PREVIOUS_ARCHIVE),
                  static_evidence_path=str(output / STATIC_PATH),
                  migration_context_verified=context is not None)
    return result


def rehearsal_identity(root: Path, output: Path) -> dict:
    """Create a deterministic, clearly non-formal identity for a copied rehearsal."""
    from .stage2c import build_identity
    identity = build_identity(Path(root), Path(output))
    identity = deepcopy(identity)
    identity["runner_commit"] = digest_bytes(json_bytes(identity["source_hashes"]))[:40]
    if identity["runner_commit"] == OLD_CONTROL_COMMIT:
        identity["runner_commit"] = "e" + identity["runner_commit"][1:]
    identity["runner_worktree_clean"] = True
    return identity


def rehearse_resource_history_migration(root: Path, output: Path) -> dict:
    """Migrate a copied formal directory only; no production bypass is exposed by CLI."""
    from . import stage2c as runner
    root, output = Path(root).resolve(), Path(output).resolve()
    formal = (root / runner.DEFAULT_OUTPUT).resolve()
    if output == formal or root in output.parents:
        raise ValueError("rehearsal requires a copied study outside the project workspace")
    current = rehearsal_identity(root, output)
    with (output / ".runner.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _migrate_locked(root, output, current, expectation=FORMAL_EXPECTATION,
                               rehearsal=True)
