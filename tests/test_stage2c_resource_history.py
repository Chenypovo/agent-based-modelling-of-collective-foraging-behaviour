from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import pytest

import colony.stage2c as runner
import colony.stage2c_resource_history as history
from colony.config import SiteConfig
from colony.stage2c_checkpoint import digest_bytes, json_bytes, read_json, write_json
from colony.stage2c_checkpoint import load_checkpoint

ROOT = Path(__file__).resolve().parents[1]


def projection(index=0):
    value = runner.resource_projection(
        elapsed_seconds=float(index), stored_bytes=90_000_000 + index,
        remaining_runs=38, run_seconds=250.0,
        retained_completed_run_bytes=11_800_000,
        retained_checkpoint_bytes_per_completed_run=17_000_000,
        shared_seed_artifact_bytes=7_700_000, remaining_shared_seed_artifacts=19,
        active_checkpoint_overlap_bytes=51_000_000,
        completion_publication_overlap_bytes=11_800_000,
        future_resource_history_allowance_bytes=9_000_000,
        assumptions=["fixed resource assumption"],
        measurement_status={"runtime": "historical"},
        amendment={"effective_time_limit_seconds": 28800.0},
    )
    value.update(
        storage_only_preflight={"dense": "x" * 45_000},
        historical_evidence={"retained": 11_800_000},
        environment={"platform": "fixture"},
        per_run=[{"seed": 800_000 + n, "rule": "fixture", "status": "planned"}
                 for n in range(40)],
        resource_history_bounds={"future_resource_history_bytes": 9_000_000},
    )
    return value


def legacy_admin(count=190):
    records = []
    for index in range(count):
        item = projection(index)
        records.append(item)
    progress = {"schema_version": 1, "identity": {"runner_commit": history.OLD_CONTROL_COMMIT},
                "resource_history": records, "runs": [], "study_state": "paused",
                "elapsed_seconds": float(count)}
    payload = {
        "checkpoint/progress_manifest.json": json_bytes(progress),
        "runtime.json": json_bytes(records[-1]),
        "config_manifest.json": json_bytes({"fixture": True}),
        "seed_manifest.json": json_bytes({"fixture": True}),
        "storage_preflight.json": json_bytes({"fixture": True}),
        "engineering_validation.json": json_bytes({"fixture": True}),
        "per_seed_metrics.csv": b"fixture\n",
        "paired_comparison.csv": b"fixture\n",
    }
    return progress, payload


def compact_fixture(tmp_path, count=190):
    output = tmp_path / "study"
    (output / history.ATTEMPT).mkdir(parents=True)
    progress, payload = legacy_admin(count)
    archive = history._zip(payload)
    catalogue, _ = history._new_catalogue(progress["resource_history"][-1])
    catalogue_raw = json_bytes(catalogue)
    (output / history.ATTEMPT / history.PREVIOUS_ARCHIVE).write_bytes(archive)
    (output / history.STATIC_PATH).parent.mkdir(parents=True)
    (output / history.STATIC_PATH).write_bytes(catalogue_raw)
    compact_raw = history.compact_legacy_progress(
        payload["checkpoint/progress_manifest.json"], archive, catalogue_raw)
    target = output / "checkpoint/progress_manifest.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(compact_raw)
    (output / "runtime.json").write_bytes(payload["runtime.json"])
    return output, progress, payload, archive, catalogue_raw


def test_190_legacy_records_compress_deterministically_and_losslessly(tmp_path):
    output, old, payload, archive, catalogue = compact_fixture(tmp_path)
    again = history._zip(dict(reversed(list(payload.items()))))
    assert archive == again
    compact_a = (output / "checkpoint/progress_manifest.json").read_bytes()
    compact_b = history.compact_legacy_progress(
        payload["checkpoint/progress_manifest.json"], again, catalogue)
    assert compact_a == compact_b
    assert len(compact_a) < len(payload["checkpoint/progress_manifest.json"]) / 20
    checked = history.verify_resource_history(output, require_latest_runtime=False)
    assert checked["legacy_records"] == 190 and checked["compact_records"] == 0
    descriptor = read_json(output / "checkpoint/progress_manifest.json")["resource_history"]["legacy"]
    assert descriptor["progress_manifest_sha256"] == digest_bytes(payload["checkpoint/progress_manifest.json"])
    assert descriptor["archive_sha256"] == digest_bytes(archive)


def test_static_evidence_is_content_addressed_once_and_records_are_bounded(tmp_path):
    output = tmp_path / "study"
    output.mkdir()
    progress = {"resource_history": []}
    history.initialise_compact_history(output, progress, projection(0))
    first = history.append_resource_projection(output, progress, projection(0), {"runner_commit": "e" * 40})
    static_before = (output / history.STATIC_PATH).read_bytes()
    second = history.append_resource_projection(output, progress, projection(1), {"runner_commit": "e" * 40})
    static_after = (output / history.STATIC_PATH).read_bytes()
    assert first["record_bytes"] <= 2048 and second["record_bytes"] <= 2048
    assert static_before == static_after
    catalogue = json.loads(static_after)
    assert len(catalogue["objects"]) == len(history.STATIC_FIELDS)
    assert len(progress["resource_history"]["records"]) == 2
    assert "storage_only_preflight" not in json.dumps(progress["resource_history"]["records"])


@pytest.mark.parametrize("checks", [100, 1000, 4000])
def test_future_management_growth_has_a_study_wide_bound(checks):
    item = projection(0)
    catalogue, reference_set = history._new_catalogue(item)
    records = [history._compact_record(item, index, reference_set) for index in range(checks)]
    resource_history = {"schema_version": 2, "legacy": None,
                        "static_evidence": {"path": history.STATIC_PATH,
                                            "bytes": len(json_bytes(catalogue)),
                                            "sha256": digest_bytes(json_bytes(catalogue))},
                        "records": records}
    actual = len(json_bytes(resource_history)) + len(json_bytes(catalogue))
    assert all(len(json_bytes(record)) <= history.MAX_COMPACT_RECORD_BYTES for record in records)
    assert actual <= 1_000_000 + checks * history.MAX_COMPACT_RECORD_BYTES
    allowance = history.resource_history_allowance({"resource_history": resource_history})
    assert allowance["remaining_compact_records"] == 4096 - checks


def test_limit_refuses_4097th_record(tmp_path):
    output = tmp_path / "study"
    output.mkdir()
    item = projection()
    catalogue, reference_set = history._new_catalogue(item)
    raw = json_bytes(catalogue)
    path = output / history.STATIC_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    progress = {"resource_history": {"schema_version": 2, "legacy": None,
        "static_evidence": {"path": history.STATIC_PATH, "bytes": len(raw),
                            "sha256": digest_bytes(raw)},
        "records": [history._compact_record(item, n, reference_set) for n in range(4096)]}}
    with pytest.raises(ValueError, match="record bound"):
        history.append_resource_projection(output, progress, item, {"runner_commit": "e" * 40})


@pytest.mark.parametrize("mutation", ["archive", "manifest_hash", "count", "order",
                                      "latest", "static", "schema", "reference", "duplicate"])
def test_corruption_missing_order_duplicate_and_unknown_formats_are_rejected(tmp_path, mutation):
    output, old, payload, archive, catalogue = compact_fixture(tmp_path)
    progress_path = output / "checkpoint/progress_manifest.json"
    compact = read_json(progress_path)
    if mutation == "archive":
        (output / history.ATTEMPT / history.PREVIOUS_ARCHIVE).write_bytes(b"corrupt")
    elif mutation == "manifest_hash":
        compact["resource_history"]["legacy"]["progress_manifest_sha256"] = "0" * 64
    elif mutation == "count":
        compact["resource_history"]["legacy"]["resource_record_count"] -= 1
    elif mutation == "order":
        compact["resource_history"]["legacy"]["ordered_record_hashes_sha256"] = "0" * 64
    elif mutation == "latest":
        current = compact["resource_history"]["legacy"]["latest_action"]
        compact["resource_history"]["legacy"]["latest_action"] = "pause" if current == "continue" else "continue"
    elif mutation == "static":
        (output / history.STATIC_PATH).write_bytes(b"{}")
    elif mutation == "schema":
        compact["resource_history"]["schema_version"] = 99
    else:
        item = old["resource_history"][-1]
        cat = json.loads(catalogue)
        reference_set = next(iter(cat["reference_sets"]))
        record = history._compact_record(item, 190, reference_set)
        if mutation == "reference":
            record["static_reference_set"] = "0" * 64
        compact["resource_history"]["records"] = [record, deepcopy(record)] if mutation == "duplicate" else [record]
    if mutation not in {"archive", "static"}:
        progress_path.write_bytes(json_bytes(compact))
    with pytest.raises((ValueError, OSError)):
        history.verify_resource_history(output, require_latest_runtime=False)


def identities():
    baseline = {"runner_commit": history.BASELINE_EXECUTION_COMMIT, "name": "baseline"}
    old = {"runner_commit": history.OLD_CONTROL_COMMIT, "name": "pca"}
    new = {"runner_commit": "e" * 40, "name": "future"}
    runs = []
    for index in range(40):
        runs.append({"seed": 900_000 + index // 2, "rule": "a" if index % 2 == 0 else "b",
                     "status": "completed" if index == 0 else "interrupted" if index == 1 else "planned"})
    prior = {"identities": {baseline["runner_commit"]: baseline,
                            old["runner_commit"]: old},
             "runs": [{"seed": value["seed"], "rule": value["rule"],
                       "execution_commit": baseline["runner_commit"] if index == 0 else old["runner_commit"]}
                      for index, value in enumerate(runs)],
             "scientific_equivalence": {"sha256": "frozen"}}
    return baseline, old, new, {"runs": runs, "execution_identity_lineage": prior}


def test_three_level_lineage_preserves_started_runs_and_assigns_only_planned_runs():
    baseline, old, new, progress = identities()
    lineage = history._lineage(progress, new, {"sha256": "e5"})
    assert lineage["runs"][0]["execution_commit"] == baseline["runner_commit"]
    assert lineage["runs"][1]["execution_commit"] == old["runner_commit"]
    assert all(row["execution_commit"] == new["runner_commit"] for row in lineage["runs"][2:])
    assert set(lineage["identities"]) == {baseline["runner_commit"], old["runner_commit"], new["runner_commit"]}


def test_started_pca_cannot_be_rebound_as_planned():
    baseline, old, new, progress = identities()
    progress["runs"][1]["status"] = "planned"
    with pytest.raises(ValueError, match="three-level"):
        history._lineage(progress, new, {"sha256": "e5"})


def test_deterministic_receipt_bytes(tmp_path):
    intent = tmp_path / "intent.json"
    validation = tmp_path / "validation.json"
    write_json(intent, {"fixed": True})
    write_json(validation, {"fixed": True})
    old, payload = legacy_admin()
    archive = history._zip(payload)
    catalogue, _ = history._new_catalogue(old["resource_history"][-1])
    compact = json.loads(history.compact_legacy_progress(
        payload["checkpoint/progress_manifest.json"], archive, json_bytes(catalogue)))
    baseline, control, new, lineage_progress = identities()
    compact["execution_identity_lineage"] = history._lineage(lineage_progress, new, {"sha256": "e5"})
    runtime = projection()
    compact["resource_history"]["records"].append(
        history._compact_record(runtime, 190, next(iter(catalogue["reference_sets"]))))
    a = history._receipt(intent, new, validation, json_bytes(runtime), compact, runtime,
                         json_bytes(catalogue), payload)
    b = history._receipt(intent, new, validation, json_bytes(runtime), deepcopy(compact),
                         deepcopy(runtime), json_bytes(catalogue), payload)
    assert json_bytes(a) == json_bytes(b)


def test_archived_admin_rejects_intent_archive_hash_and_members(tmp_path):
    output = tmp_path / "study"
    folder = output / history.ATTEMPT
    folder.mkdir(parents=True)
    _, payload = legacy_admin()
    archive = history._zip(payload)
    write_json(folder / "intent.json", {
        "previous_archive_sha256": digest_bytes(archive),
        "previous_archive_bytes": len(archive), "previous_files": history._hashes(payload)})
    (folder / history.PREVIOUS_ARCHIVE).write_bytes(archive)
    assert history.archived_admin(output) == payload
    intent = read_json(folder / "intent.json")
    intent["previous_files"]["runtime.json"]["sha256"] = "0" * 64
    write_json(folder / "intent.json", intent)
    with pytest.raises(ValueError, match="file hash"):
        history.archived_admin(output)


def test_engineering_receipt_cleans_only_its_fixture_and_records_peak(tmp_path, monkeypatch):
    output = tmp_path / "study"
    output.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep").write_bytes(b"keep")

    def fake(command, **kwargs):
        base = Path(command[command.index("--basetemp") + 1])
        (base / "fixture").mkdir()
        (base / "fixture/data").write_bytes(b"x" * 5000)
        return subprocess.CompletedProcess(command, 0, "12 passed, 1 skipped in 0.1s\n", "")

    monkeypatch.setattr(subprocess, "run", fake)
    receipt = runner.verify_engineering_tests(ROOT, output, {"fixture": True})
    assert receipt["passed_count"] == 12 and receipt["skipped_count"] == 1
    assert receipt["temporary_peak_bytes"] >= 5000
    assert receipt["temporary_directory_removed"] is True
    assert not Path(receipt["temporary_directory"]).exists()
    assert (unrelated / "keep").read_bytes() == b"keep"
    assert receipt["long_term_retained_bytes"] == (output / "engineering_validation.json").stat().st_size


def test_cli_has_explicit_zero_science_repair_mode_and_rejects_resume(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("stage2c_history_cli", ROOT / "scripts/run_stage2c.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    parser = cli.parser()
    args = parser.parse_args(["--mode", "repair-resource-history", "--output-dir", str(tmp_path)])
    assert args.mode == "repair-resource-history" and args.resume is False
    with pytest.raises(SystemExit):
        cli.main(["--mode", "repair-resource-history", "--resume", "--output-dir", str(tmp_path)])
    for flag in ("--seed", "--rule", "--steps", "--n-ants"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--mode", "repair-resource-history", flag, "1"])


def test_default_plotting_backend_is_headless():
    assert os.environ.get("MPLBACKEND") == "Agg"


def test_rehearsal_refuses_formal_or_in_workspace_output():
    with pytest.raises(ValueError, match="outside"):
        history.rehearse_resource_history_migration(
            ROOT, ROOT / runner.DEFAULT_OUTPUT)


def test_production_repair_reports_zero_science_flags_without_running_simulation(tmp_path, monkeypatch):
    output = tmp_path / "study"
    output.mkdir()
    (output / ".runner.lock").touch()
    identity = {"runner_commit": "e" * 40, "runner_worktree_clean": True}
    monkeypatch.setattr(runner, "validate_output", lambda *args: None)
    monkeypatch.setattr(runner, "build_identity", lambda *args: identity)
    monkeypatch.setattr(history, "_require_committed", lambda *args: None)
    called = []

    def migrate(root, target, current, **kwargs):
        called.append(kwargs)
        return {"simulation_started": False, "simulation_steps_executed": 0,
                "scientific_metrics_generated": False, "pca_resumed": False,
                "other_seed_initialised": False,
                "final_scientific_conclusion_available": False, "action": "pause"}

    monkeypatch.setattr(history, "_migrate_locked", migrate)
    result = history.repair_resource_history(ROOT, output)
    assert result["simulation_steps_executed"] == 0 and result["action"] == "pause"
    assert called == [{"expectation": history.FORMAL_EXPECTATION, "rehearsal": False}]


def test_interrupted_run_without_resume_is_still_rejected(tmp_path):
    config = replace(runner.ColonyConfig.paper_scale(), n_ants=2, steps=2,
                     arena_size=10.0, seed=991337,
                     nest=SiteConfig((1.5, 5.0), 1.0),
                     food=SiteConfig((7.0, 5.0), 1.0),
                     snapshot_steps=(), agent_state_interval=1,
                     output_dir=str(tmp_path / "run"))
    entry = runner.new_progress({"fixture": True})["runs"][0]
    entry.update(seed=config.seed, rule=config.follower_direction_rule,
                 status="interrupted", reason="fixture")
    with pytest.raises(ValueError, match="requires --resume"):
        runner.run_one(config, Path(config.output_dir), {"fixture": True}, entry,
                       resume=False, persist=lambda: None,
                       resource_check=lambda: {"action": "continue"}, checkpoint_interval=1)


def small_config(tmp_path):
    return replace(runner.ColonyConfig.paper_scale(), n_ants=3, steps=8,
                   arena_size=10.0, seed=991337,
                   nest=SiteConfig((1.5, 5.0), 1.0),
                   food=SiteConfig((7.0, 5.0), 1.0),
                   snapshot_steps=(), agent_state_interval=2,
                   output_dir=str(tmp_path / "registered-route"))


def fixture_identity(commit):
    return {"preregistration_commit": "a" * 40,
            "stage2b_implementation_commit": "b" * 40,
            "protocol_input_commit": "c" * 40, "runner_commit": commit,
            "source_hash": "d" * 64, "input_hash": "e" * 64,
            "preregistration_hash": "f" * 64}


def test_old_identity_interrupt_admin_migration_resume_is_byte_exact(tmp_path):
    config = small_config(tmp_path)
    old_identity = fixture_identity(history.OLD_CONTROL_COMMIT)
    interrupted = runner.new_progress(old_identity)["runs"][1]
    interrupted.update(seed=config.seed, rule=config.follower_direction_rule)

    def stop(simulation, entry):
        if simulation.time == 5:
            raise KeyboardInterrupt

    paused = runner.run_one(
        config, tmp_path / "resumed", old_identity, interrupted, resume=False,
        persist=lambda: None, resource_check=lambda: {"action": "continue"},
        late_window=(6, 8), checkpoint_interval=2, boundary_observer=stop)
    assert paused is None and interrupted["time"] == 4
    # The only intervening operation is an administrative lineage assignment.
    baseline = fixture_identity(history.BASELINE_EXECUTION_COMMIT)
    new = fixture_identity("9" * 40)
    runs = [{"seed": 991336, "rule": "baseline", "status": "completed"},
            {"seed": config.seed, "rule": config.follower_direction_rule,
             "status": "interrupted"}]
    runs.extend({"seed": 991338 + n, "rule": "planned", "status": "planned"}
                for n in range(38))
    prior = {"identities": {baseline["runner_commit"]: baseline,
                            old_identity["runner_commit"]: old_identity},
             "runs": [{"seed": value["seed"], "rule": value["rule"],
                       "execution_commit": (baseline["runner_commit"] if n == 0
                                            else old_identity["runner_commit"])}
                      for n, value in enumerate(runs)],
             "scientific_equivalence": {"sha256": "fixed"}}
    migrated = history._lineage({"runs": runs, "execution_identity_lineage": prior},
                                new, {"sha256": "resource-only"})
    resume_identity = migrated["identities"][migrated["runs"][1]["execution_commit"]]
    assert resume_identity == old_identity
    resumed = runner.run_one(
        config, tmp_path / "resumed", resume_identity, interrupted, resume=True,
        persist=lambda: None, resource_check=lambda: {"action": "continue"},
        late_window=(6, 8), checkpoint_interval=2)
    fresh_entry = runner.new_progress(old_identity)["runs"][1]
    fresh_entry.update(seed=config.seed, rule=config.follower_direction_rule)
    fresh = runner.run_one(
        config, tmp_path / "fresh", old_identity, fresh_entry, resume=False,
        persist=lambda: None, resource_check=lambda: {"action": "continue"},
        late_window=(6, 8), checkpoint_interval=2)
    assert resumed == fresh
    def scientific_files(folder):
        return {item.relative_to(folder).as_posix(): item.read_bytes()
                for item in folder.rglob("*") if item.is_file() and item.name != "receipt.json"}
    assert scientific_files(tmp_path / "resumed/completed") == scientific_files(tmp_path / "fresh/completed")


def test_planned_run_starts_with_new_identity_and_checkpoint_rejects_old(tmp_path):
    config = small_config(tmp_path)
    old = fixture_identity(history.OLD_CONTROL_COMMIT)
    new = fixture_identity("9" * 40)
    entry = runner.new_progress(new)["runs"][2]
    entry.update(seed=config.seed, rule=config.follower_direction_rule)

    def stop(simulation, state):
        if simulation.time == 1:
            raise KeyboardInterrupt

    assert runner.run_one(
        config, tmp_path / "planned", new, entry, resume=False,
        persist=lambda: None, resource_check=lambda: {"action": "continue"},
        late_window=(6, 8), checkpoint_interval=1, boundary_observer=stop) is None
    assert entry["attempts"] == [{"start_time_step": 0, "status": "interrupted"}]
    checkpoint = tmp_path / "planned" / entry["checkpoint"]
    assert load_checkpoint(checkpoint, config, new,
                           expected_sha256=entry["checkpoint_sha256"]).time == 1
    with pytest.raises(ValueError, match="identity"):
        load_checkpoint(checkpoint, config, old,
                        expected_sha256=entry["checkpoint_sha256"])


@pytest.mark.parametrize("phase", ["intent", "previous", "prepared", "static",
                                   "root", "tests", "runtime", "progress", "receipt"])
def test_e5_transaction_atomic_boundaries_resume_same_intent(tmp_path, monkeypatch, phase):
    output = tmp_path / "study"
    output.mkdir()
    (output / ".runner.lock").touch()
    baseline, old, new, lineage_progress = identities()
    old.update(preregistration_hash="p", input_hash="i", source_hash="old-source",
               frozen_source_hashes={"f": "h"})
    new.update(preregistration_hash="p", input_hash="i", source_hash="new-source",
               frozen_source_hashes={"f": "h"})
    lineage_progress.update(identity=old, resource_history=[projection()],
                            elapsed_seconds=1.0, study_state="paused")
    lineage_progress["runs"][0].update(time=1)
    lineage_progress["runs"][1].update(time=0, checkpoint="checkpoint.zip",
                                        checkpoint_sha256="0" * 64)
    payload = {
        "checkpoint/progress_manifest.json": json_bytes(lineage_progress),
        "runtime.json": json_bytes(projection()),
        "config_manifest.json": json_bytes({"identity": old,
            "execution_identity_lineage": lineage_progress["execution_identity_lineage"]}),
        "storage_preflight.json": json_bytes({"source_hash": "old"}),
        "seed_manifest.json": b"{}\n", "engineering_validation.json": b"{}\n",
        "per_seed_metrics.csv": b"fixture\n", "paired_comparison.csv": b"fixture\n",
    }
    for name, raw in payload.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    inventory = history._inventory(output)
    admitted = {"payload": payload, "progress": lineage_progress,
                "runtime": projection(), "old_control": old,
                "proof": {"sha256": "resource-only"}, "inventory": inventory}
    monkeypatch.setattr(history, "_admit", lambda *args, **kwargs: deepcopy(admitted))
    monkeypatch.setattr(history, "control_equivalence", lambda *args, **kwargs: {"sha256": "resource-only"})
    def engineering(root, target, identity):
        path = target / "engineering_validation.json"
        if path.exists():
            return read_json(path)
        write_json(path, {"identity": identity, "passed": True, "exit_code": 0,
                   "passed_count": 1, "output": "1 passed in 0.1s\n",
                   "paper_scale_simulation_executed": False}, replace=False)
        return read_json(path)
    monkeypatch.setattr(runner, "verify_engineering_tests", engineering)
    monkeypatch.setattr(runner, "config_pair", lambda seed, target: (
        SimpleNamespace(output_dir=str(target / "baseline")),
        SimpleNamespace(output_dir=str(target / "pca"))))
    monkeypatch.setattr(history, "load_checkpoint", lambda *args, **kwargs: SimpleNamespace(time=0))

    def finalise(root, target, identity, previous, progress, intent, validation, catalogue):
        value = projection()
        candidate = deepcopy(progress)
        history.append_resource_projection(target, candidate, value, identity)
        runtime_raw = json_bytes(value)
        receipt = history._receipt(intent, identity, validation, runtime_raw,
                                   candidate, value, (target / history.STATIC_PATH).read_bytes(), previous)
        return runtime_raw, json_bytes(candidate), json_bytes(receipt), value

    monkeypatch.setattr(history, "_finalise_fixed_point", finalise)
    monkeypatch.setattr(history, "migration_context", lambda target, **kwargs: (True,)
                        if (target / history.ATTEMPT / "receipt.json").exists() else None)
    once, atomic = history._once, history.atomic_write
    interrupted = []

    def stop():
        if not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt("injected E5A boundary")

    def one(path, raw):
        once(path, raw)
        if ((phase == "intent" and path.name == "intent.json")
                or (phase == "previous" and path.name == history.PREVIOUS_ARCHIVE)
                or (phase == "prepared" and path.name == history.PREPARED_ARCHIVE)
                or (phase == "receipt" and path.name == "receipt.json")):
            stop()

    def write(path, raw, **kwargs):
        atomic(path, raw, **kwargs)
        if ((phase == "static" and path.as_posix().endswith(history.STATIC_PATH))
                or (phase == "root" and path == output / "config_manifest.json")
                or (phase == "runtime" and path == output / "runtime.json")
                or (phase == "progress" and path == output / "checkpoint/progress_manifest.json")):
            stop()

    original_tests = runner.verify_engineering_tests
    def tests(*args):
        value = original_tests(*args)
        if phase == "tests":
            stop()
        return value

    monkeypatch.setattr(history, "_once", one)
    monkeypatch.setattr(history, "atomic_write", write)
    monkeypatch.setattr(runner, "verify_engineering_tests", tests)
    with pytest.raises(KeyboardInterrupt):
        history._migrate_locked(ROOT, output, new, expectation={}, rehearsal=True)
    intent_bytes = (output / history.ATTEMPT / "intent.json").read_bytes()
    monkeypatch.setattr(history, "_once", once)
    monkeypatch.setattr(history, "atomic_write", atomic)
    monkeypatch.setattr(runner, "verify_engineering_tests", original_tests)
    if phase == "receipt":
        with pytest.raises(ValueError, match="must not be repeated"):
            history._migrate_locked(ROOT, output, new, expectation={}, rehearsal=True)
    else:
        result = history._migrate_locked(ROOT, output, new, expectation={}, rehearsal=True)
        assert result["simulation_steps_executed"] == 0
    assert (output / history.ATTEMPT / "intent.json").read_bytes() == intent_bytes
