"""Bounded engineering tests only; no paper-scale pilot or scientific dataset."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import struct
import sys
import zipfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from colony.agents import Ant, Role
from colony.config import ColonyConfig, MovementConfig, SiteConfig
from colony.diagnostics import DiagnosticSimulation, axial_angle_error, pheromone_concentration_rows
from colony.pheromone import PheromoneField
from colony.simulation import ColonySimulation
from colony.stage2c import (
    IMPLEMENTATION_COMMIT, PREREGISTRATION_COMMIT, SAFETY_FACTOR, Study,
    audit_pair, config_pair, dry_run, new_progress, resource_projection, run_one, transition,
    validate_output, verify_engineering_tests,
)
from colony.stage2c_analysis import (
    BOOTSTRAP_REPETITIONS, BOOTSTRAP_SEED, METRICS, RULES, SEEDS, analyse_rows,
    bootstrap_indices, index_rows, paired_bootstrap, paired_rows, planned_rows,
    seed_manifest, write_comparison_figures, write_metric_tables,
)
from colony.stage2c_checkpoint import (
    STORAGE_FIXTURE_SEED, _archive_bytes, atomic_write, behavioural_config,
    digest_bytes, hash_value, initial_identity, json_bytes,
    load_checkpoint, read_json, save_checkpoint, state_fingerprint,
)
from colony.stage2c_streaming import StreamingSimulation, measurement
from colony.stage2c_storage import HistoryStore, sha256_file

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = {"preregistration_commit": PREREGISTRATION_COMMIT,
            "stage2b_implementation_commit": IMPLEMENTATION_COMMIT,
            "source_hash": "small-test-code", "input_hash": "small-test-inputs"}


@pytest.fixture(autouse=True)
def forbid_paper_scale(monkeypatch):
    original = ColonySimulation.__init__

    def guarded(self, config, **kwargs):
        assert config.seed not in SEEDS, "registered scientific seeds are forbidden in tests"
        assert not (config.n_ants >= 100 and config.steps >= 10000), "paper-scale run is forbidden in tests"
        return original(self, config, **kwargs)

    monkeypatch.setattr(ColonySimulation, "__init__", guarded)


@pytest.fixture
def small(tmp_path):
    return ColonyConfig(n_ants=6, arena_size=10.0, steps=80, seed=STORAGE_FIXTURE_SEED,
                        nest=SiteConfig((1.5, 5.0), 1.0), food=SiteConfig((7.0, 5.0), 1.0),
                        movement=MovementConfig(theta_deg=0.0), snapshot_steps=(20, 60, 80),
                        agent_state_interval=5, output_dir=str(tmp_path / "small-output"))


def fixture_progress():
    """Reuse the progress schema with isolated, non-registered engineering seeds."""
    progress = new_progress(IDENTITY)
    for entry in progress["runs"]:
        entry["seed"] = STORAGE_FIXTURE_SEED
    return progress


def artificial_start(config):
    return [Ant(i, np.array([1.5, 4.25 + i * 0.3]), 0.0, Role.FORAGER) for i in range(config.n_ants)]


def simulation(config, cls=StreamingSimulation, *, artificial=False):
    extra = {"initial_agents": artificial_start(config), "turn_schedules": np.zeros((config.n_ants, config.steps))} if artificial else {}
    if cls is StreamingSimulation:
        extra["late_window"] = (60, 80)
    return cls(config, **extra)


def frame_bytes(result):
    return {name: getattr(result, name).to_csv(index=False, lineterminator="\n").encode()
            for name in ("metrics", "agent_states", "final_agents", "events")}


def completed_bytes(folder):
    return {str(path.relative_to(folder)): path.read_bytes()
            for path in folder.rglob("*") if path.is_file() and path.name != "receipt.json"}


def test_seed_manifest_exact_and_no_exploratory():
    manifest = seed_manifest()
    assert manifest["confirmatory_seeds"] == list(range(20260901, 20260921))
    assert manifest["exploratory_seed"] == 20260824
    assert manifest["exploratory_in_confirmatory_statistics"] is False
    assert manifest["pilot_in_confirmatory_statistics"] is True
    assert manifest["planned_runs"] == [{"seed": s, "rule": r} for s in SEEDS for r in RULES]


@pytest.mark.parametrize("seed", [SEEDS[0], SEEDS[9], SEEDS[-1]])
def test_pair_only_rule_changes(seed, tmp_path):
    baseline, pca = config_pair(seed, tmp_path)
    assert audit_pair(baseline, pca)["difference_count"] == 1
    assert baseline.n_ants == pca.n_ants == 100
    assert baseline.steps == pca.steps == 10000
    assert baseline.output_dir != pca.output_dir
    assert hash_value(behavioural_config(baseline)) == hash_value(behavioural_config(replace(baseline, output_dir="elsewhere")))
    with pytest.raises(ValueError):
        audit_pair(baseline, replace(pca, memory_stride=4))


def test_exploratory_and_replaced_seeds_rejected(tmp_path):
    with pytest.raises(ValueError):
        config_pair(20260824, tmp_path)
    rows = planned_rows()
    rows[0]["seed"] = 20260824
    with pytest.raises(ValueError):
        analyse_rows(rows)


def test_initial_state_schedule_same_pair_and_reproducible_different_seed(small):
    first = initial_identity(simulation(small))
    pca = initial_identity(simulation(replace(small, follower_direction_rule=RULES[1])))
    repeat = initial_identity(simulation(small))
    other = initial_identity(simulation(replace(small, seed=STORAGE_FIXTURE_SEED + 1, movement=MovementConfig())))
    assert first == pca == repeat
    assert other["initial_state_hash"] != first["initial_state_hash"]
    # Nonzero turns are needed to check the stochastic schedule rather than a constant fixture.
    a = initial_identity(simulation(replace(small, movement=MovementConfig())))
    assert other["turn_schedule_hash"] != a["turn_schedule_hash"]
    assert first["rng_state"]["live_generator_state"] is None


@pytest.mark.parametrize("rule", RULES)
def test_streaming_matches_full_diagnostics_and_default_outputs(small, rule):
    config = replace(small, follower_direction_rule=rule)
    full = simulation(config, DiagnosticSimulation, artificial=True)
    streamed = simulation(config, artificial=True)
    plain = simulation(config, ColonySimulation, artificial=True)
    full_result, stream_result, plain_result = full.run(), streamed.run(), plain.run()
    assert frame_bytes(full_result) == frame_bytes(stream_result) == frame_bytes(plain_result)
    np.testing.assert_array_equal(streamed.field.intensity, full.field.intensity)
    np.testing.assert_array_equal(streamed.field.direction_sum, full.field.direction_sum)
    records = pd.DataFrame(full.sensing_records).sort_values(["ant_id", "time"])
    assert len(records) > 0 and records["sensing_hit"].sum() > 0
    hits = records.loc[records.sensing_hit]
    hit_errors = np.degrees(axial_angle_error(hits.heading_after_move.to_numpy(), full.axis_angle))
    changes = []
    for _, group in records.groupby("ant_id"):
        previous = None
        for record in group.itertuples():
            if previous is not None and record.time == previous.time + 1 and record.sensing_hit and previous.sensing_hit:
                changes.append(float(np.degrees(axial_angle_error([record.chosen_direction_rad], previous.chosen_direction_rad)[0])))
            previous = record
    assert len(changes) > 0
    assert streamed.sensing_steps == len(records)
    assert streamed.hit_count == len(hits)
    assert streamed.miss_count == int(records.sensing_miss.sum())
    assert streamed.hit_axis_sum == pytest.approx(sum(hit_errors), abs=1e-10)
    assert streamed.continuity_sum == pytest.approx(sum(changes), abs=1e-10)
    assert streamed.continuity_count == len(changes)
    metrics = streamed.endpoint_metrics()
    window = full_result.metrics.query("60 <= time <= 80")
    for key, column in (("phi", "orientation_order_phi"), ("psi", "nematic_order_psi")):
        assert metrics["late_window_mean_" + key]["value"] == pytest.approx(window[column].mean(), abs=1e-14)
    role_frame = pd.DataFrame(full.role_order_records)
    for row in streamed.role_rows:
        for role in Role:
            expected = role_frame.loc[(role_frame.time == row["time"]) & (role_frame.role == role.value)].iloc[0]
            assert row[role.value + "_count"] == expected.sample_count
            for key, column in (("phi", "orientation_order_phi"), ("psi", "nematic_order_psi")):
                if expected.sample_count:
                    assert row[role.value + "_" + key] == expected[column]
                else:
                    assert row[role.value + "_" + key] is None
    completed = [r for r in full.transport_records if r["status"] == "completed_delivery"]
    assert completed
    np.testing.assert_allclose([r["efficiency"] for r in streamed.completed_transport],
                               [r["actual_return_path_efficiency"] for r in completed], rtol=0, atol=1e-15)
    concentration = pheromone_concentration_rows(full.field.intensity, cell_size=config.pheromone.cell_size,
        nest=config.nest.center, food=config.food.center, nest_radius=config.nest.radius,
        food_radius=config.food_detection_distance, time=config.steps)[0]
    assert metrics["main_channel_width_90"]["value"] == concentration["main_channel_width_90"]
    assert metrics["active_pheromone_area_fraction"]["value"] == concentration["active_area_fraction"]
    assert metrics["cumulative_deliveries"]["value"] == full.cumulative_deliveries
    assert streamed.transition_counts == full.transition_counts
    assert not hasattr(streamed, "sensing_records")
    assert len(streamed.previous_sensing) <= config.n_ants
    json_bytes(metrics)


@pytest.mark.parametrize("rule", RULES)
def test_no_extra_randomness_or_sense_calls(small, rule, monkeypatch):
    config = replace(small, follower_direction_rule=rule)
    counts = {"plain": 0, "stream": 0}
    active_counts = dict(counts)
    current = ["plain"]
    original = PheromoneField.sense
    original_active = PheromoneField.active_cells_near

    def count_sense(self, *args, **kwargs):
        counts[current[0]] += 1
        return original(self, *args, **kwargs)

    def count_active(self, *args, **kwargs):
        active_counts[current[0]] += 1
        return original_active(self, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("instrumentation requested randomness")

    monkeypatch.setattr(PheromoneField, "sense", count_sense)
    monkeypatch.setattr(PheromoneField, "active_cells_near", count_active)
    monkeypatch.setattr(np.random, "default_rng", forbidden)
    monkeypatch.setattr(np.random, "SeedSequence", forbidden)
    monkeypatch.setattr(np.random, "random", forbidden)
    plain = simulation(config, ColonySimulation, artificial=True)
    plain_result = plain.run()
    current[0] = "stream"
    streamed = simulation(config, artificial=True)
    streamed_result = streamed.run()
    assert counts["plain"] == counts["stream"]
    assert active_counts["plain"] == active_counts["stream"]
    assert frame_bytes(plain_result) == frame_bytes(streamed_result)


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("interrupt_at", [23, 61])
def test_checkpoint_resume_byte_exact(small, tmp_path, rule, interrupt_at, monkeypatch):
    config = replace(small, follower_direction_rule=rule)
    uninterrupted = simulation(config, artificial=True)
    expected = uninterrupted.run()
    interrupted = simulation(config, artificial=True)
    for _ in range(interrupt_at):
        interrupted.step()
    checkpoint = tmp_path / "checkpoint.zip"
    checksum = save_checkpoint(checkpoint, interrupted, IDENTITY)

    def forbidden(*args, **kwargs):
        raise AssertionError("checkpoint restoration reinitialised randomness")

    monkeypatch.setattr(np.random, "default_rng", forbidden)
    monkeypatch.setattr(np.random, "SeedSequence", forbidden)
    restored = load_checkpoint(checkpoint, config, IDENTITY, expected_sha256=checksum)
    assert restored.time == interrupt_at
    actual = restored.run()
    assert frame_bytes(actual) == frame_bytes(expected)
    assert state_fingerprint(restored) == state_fingerprint(uninterrupted)
    assert json_bytes(restored.endpoint_metrics()) == json_bytes(uninterrupted.endpoint_metrics())
    assert restored.cumulative_deliveries == len(restored.completed_transport)
    assert actual.metrics.time.tolist() == list(range(config.steps + 1))
    assert actual.events.to_csv(index=False) == expected.events.to_csv(index=False)
    for t in expected.snapshots:
        assert actual.snapshots[t].to_csv(index=False) == expected.snapshots[t].to_csv(index=False)
        for a, b in zip(actual.pheromone_snapshots[t], expected.pheromone_snapshots[t]):
            assert a.tobytes() == b.tobytes()


@pytest.mark.parametrize("changed", ["source_hash", "input_hash", "preregistration_commit"])
def test_checkpoint_identity_mismatch_refused(small, tmp_path, changed):
    sim = simulation(small)
    path = tmp_path / "checkpoint.zip"
    save_checkpoint(path, sim, IDENTITY)
    wrong = dict(IDENTITY, **{changed: "changed"})
    with pytest.raises(ValueError, match="identity mismatch"):
        load_checkpoint(path, small, wrong)


def test_config_corruption_and_timeline_mismatch_refused(small, tmp_path):
    sim = simulation(small)
    path = tmp_path / "checkpoint.zip"
    save_checkpoint(path, sim, IDENTITY)
    with pytest.raises(ValueError, match="configuration mismatch"):
        load_checkpoint(path, replace(small, seed=STORAGE_FIXTURE_SEED + 1), IDENTITY)
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_checkpoint(path, small, IDENTITY, expected_sha256="wrong")
    sim._metric_rows.append(sim._metric_rows[0])
    save_checkpoint(path, sim, IDENTITY)
    with pytest.raises(ValueError, match="timeline mismatch"):
        load_checkpoint(path, small, IDENTITY)


def test_atomic_checkpoint_failure_preserves_old_file(small, tmp_path, monkeypatch):
    sim = simulation(small)
    path = tmp_path / "checkpoint.zip"
    save_checkpoint(path, sim, IDENTITY)
    before = path.read_bytes()
    sim.step()

    def failed_replace(*args):
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, "replace", failed_replace)
    with pytest.raises(OSError):
        save_checkpoint(path, sim, IDENTITY)
    assert path.read_bytes() == before
    assert load_checkpoint(path, small, IDENTITY).time == 0


def run_fixture(config, directory, entry, **kwargs):
    statuses = []
    result = run_one(config, directory, IDENTITY, entry,
                     persist=lambda: statuses.append(entry["status"]),
                     resource_check=lambda: {"action": "continue"}, late_window=(60, 80),
                     checkpoint_interval=10, **kwargs)
    return result, statuses


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("interrupt_at", [23, 61])
def test_runner_status_resume_no_duplicate_or_overwrite(small, tmp_path, rule, interrupt_at):
    config = replace(small, follower_direction_rule=rule)
    index = RULES.index(rule)
    entry = fixture_progress()["runs"][index]

    def interrupt(sim, state):
        if sim.time == interrupt_at:
            raise KeyboardInterrupt

    first, statuses = run_fixture(config, tmp_path / "resume", entry, resume=False, boundary_observer=interrupt)
    assert first is None and entry["status"] == "interrupted"
    assert "running" in statuses and "interrupted" in statuses
    assert entry["time"] == interrupt_at // 10 * 10
    with pytest.raises(ValueError, match="--resume"):
        run_fixture(config, tmp_path / "resume", entry, resume=False)
    resumed, statuses = run_fixture(config, tmp_path / "resume", entry, resume=True)
    fresh_entry = fixture_progress()["runs"][index]
    fresh, _ = run_fixture(config, tmp_path / "straight", fresh_entry, resume=False)
    assert resumed == fresh
    assert entry["status"] == "completed" and statuses[-1] == "completed"
    assert completed_bytes(tmp_path / "straight/completed") == completed_bytes(
        tmp_path / "resume/completed")
    final = tmp_path / "resume/completed/final_checkpoint.zip"
    with zipfile.ZipFile(final) as archive:
        assert all(item.compress_type == zipfile.ZIP_LZMA for item in archive.infolist())
    assert final.read_bytes() == (tmp_path / "straight/completed/final_checkpoint.zip").read_bytes()
    snapshot = {str(p.relative_to(tmp_path / "resume/completed")): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in (tmp_path / "resume/completed").rglob("*") if p.is_file()}
    reused, _ = run_fixture(config, tmp_path / "resume", entry, resume=True)
    assert reused == resumed
    assert snapshot == {
        str(p.relative_to(tmp_path / "resume/completed")): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in (tmp_path / "resume/completed").rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        transition(entry, "running", "attempted overwrite")


def test_pair_shares_one_seed_artifact_without_republication(small, tmp_path):
    seed_root = tmp_path / "runs" / str(small.seed)
    entries = fixture_progress()["runs"][:2]
    identities = []
    shared_snapshot = None
    for rule, entry in zip(RULES, entries):
        config = replace(small, follower_direction_rule=rule)
        row, _ = run_fixture(config, seed_root / rule, entry, resume=False)
        identities.append(row["initial_identity"])
        shared = seed_root / "shared_seed_artifact.zip"
        current = (shared.read_bytes(), shared.stat().st_mtime_ns)
        if shared_snapshot is None:
            shared_snapshot = current
        else:
            assert current == shared_snapshot
        receipt = read_json(seed_root / rule / "completed/receipt.json")
        assert receipt["shared_seed_artifact_sha256"] == sha256_file(shared)
    assert identities[0] == identities[1]
    assert len(list(seed_root.glob("shared_seed_artifact.zip"))) == 1


def test_shared_artifact_hash_mismatch_refuses_resume(small, tmp_path):
    entry = fixture_progress()["runs"][0]

    def interrupt(sim, state):
        if sim.time == 23:
            raise KeyboardInterrupt

    run_dir = tmp_path / "runs" / str(small.seed) / RULES[0]
    run_fixture(small, run_dir, entry, resume=False, boundary_observer=interrupt)
    shared = run_dir.parent / "shared_seed_artifact.zip"
    shared.write_bytes(shared.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="shared seed artifact checksum mismatch"):
        load_checkpoint(run_dir / entry["checkpoint"], small, IDENTITY,
                        expected_sha256=entry["checkpoint_sha256"])


def test_chunk_corruption_refuses_resume(small, tmp_path):
    entry = fixture_progress()["runs"][0]

    def interrupt(sim, state):
        if sim.time == 23:
            raise KeyboardInterrupt

    run_dir = tmp_path / "corrupt-chunk"
    run_fixture(small, run_dir, entry, resume=False, boundary_observer=interrupt)
    chunk = next((run_dir / "history/chunks/metrics").glob("*.json"))
    chunk.write_bytes(chunk.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="history chunk checksum mismatch"):
        load_checkpoint(run_dir / entry["checkpoint"], small, IDENTITY,
                        expected_sha256=entry["checkpoint_sha256"])


def test_incremental_chunks_resume_without_duplicate_or_missing_rows(small, tmp_path):
    entry = fixture_progress()["runs"][0]

    def interrupt(sim, state):
        if sim.time == 37:
            raise KeyboardInterrupt

    run_dir = tmp_path / "chunk-resume"
    run_fixture(small, run_dir, entry, resume=False, boundary_observer=interrupt)
    row, _ = run_fixture(small, run_dir, entry, resume=True)
    receipt = read_json(run_dir / "completed/receipt.json")
    manifest = run_dir / "completed" / receipt["history_manifest"]
    frames = HistoryStore(manifest.parent.parent).frames(manifest)
    assert frames["metrics"].time.tolist() == list(range(small.steps + 1))
    assert frames["role_specific_observations"].time.tolist() == list(range(small.steps + 1))
    assert not frames["metrics"].duplicated("time").any()
    assert len(frames["events"]) == sum(row["transition_counts"].values())
    assert frames["events"].time.is_monotonic_increasing
    assert row["status"] == "completed"


def test_completed_final_checkpoint_restores_complete_state(small, tmp_path):
    entry = fixture_progress()["runs"][0]
    expected, _ = run_fixture(small, tmp_path / "final-checkpoint", entry, resume=False)
    checkpoint = tmp_path / "final-checkpoint" / entry["checkpoint"]
    restored = load_checkpoint(
        checkpoint, small, IDENTITY, expected_sha256=entry["checkpoint_sha256"])
    assert restored.time == small.steps
    assert restored.endpoint_metrics() == expected["metrics"]
    assert len(restored._metric_rows) == small.steps + 1
    assert len(list((tmp_path / "final-checkpoint/completed").glob("final_checkpoint.zip"))) == 1


@pytest.mark.parametrize("compression", [zipfile.ZIP_DEFLATED, zipfile.ZIP_LZMA])
def test_completed_formats_keep_all_integrity_and_size_checks(small, tmp_path, compression):
    entry = fixture_progress()["runs"][0]
    run_dir = tmp_path / "formats"
    expected, _ = run_fixture(small, run_dir, entry, resume=False)
    checkpoint = run_dir / entry["checkpoint"]
    current = checkpoint.read_bytes()
    with zipfile.ZipFile(io.BytesIO(current)) as archive:
        metadata = json.loads(archive.read("metadata.json"))
        arrays = {name: archive.read(name) for name in metadata["array_hashes"]}
    # The old production DEFLATE writer has exactly these members and headers.
    data = _archive_bytes(metadata, arrays, compression=compression)
    checkpoint.write_bytes(data)
    checksum = digest_bytes(data)

    def load(**kwargs):
        return load_checkpoint(checkpoint, small, IDENTITY,
                               expected_sha256=sha256_file(checkpoint), **kwargs)

    restored = load()
    assert restored.time == small.steps and restored.endpoint_metrics() == expected["metrics"]
    reencoded = tmp_path / "formats/completed/reencoded.zip"
    save_checkpoint(reencoded, restored, IDENTITY,
                    shared_artifact=run_dir.parent / "shared_seed_artifact.zip",
                    history_manifest=run_dir / entry["history_manifest"],
                    initial=entry["initial_identity"],
                    external_field=run_dir / "completed/final_pheromone.npz", completed=True)
    # Restoring from either format and re-saving retains every state/member bit.
    assert reencoded.read_bytes() == current

    checkpoint.write_bytes(data + b"corrupt")
    with pytest.raises(ValueError, match="checkpoint checksum mismatch"):
        load_checkpoint(checkpoint, small, IDENTITY, expected_sha256=checksum)
    checkpoint.write_bytes(data)
    for key in ("source_hash", "input_hash", "preregistration_commit"):
        with pytest.raises(ValueError, match="identity mismatch"):
            load_checkpoint(checkpoint, small, dict(IDENTITY, **{key: "changed"}),
                            expected_sha256=checksum)
    with pytest.raises(ValueError, match="configuration mismatch"):
        load_checkpoint(checkpoint, replace(small, memory_stride=4), IDENTITY,
                        expected_sha256=checksum)

    for key, replacement, message in (
            ("seed", small.seed + 1, "seed/rule mismatch"),
            ("rule", RULES[1], "seed/rule mismatch"),
            ("array_hashes", dict(metadata["array_hashes"], **{next(iter(arrays)): "0" * 64}),
             "array checksum mismatch")):
        checkpoint.write_bytes(_archive_bytes(dict(metadata, **{key: replacement}), arrays,
                                              compression=compression))
        with pytest.raises(ValueError, match=message):
            load()
    # Corrupt a payload while preserving valid ZIP CRC and whole-archive SHA.
    bad_arrays = dict(arrays)
    name = next(iter(arrays))
    bad_arrays[name] = arrays[name][:-1] + bytes([arrays[name][-1] ^ 1])
    checkpoint.write_bytes(_archive_bytes(metadata, bad_arrays, compression=compression))
    with pytest.raises(ValueError, match="array checksum mismatch"):
        load()

    # Forged central-directory size exercises the 1 GB guard without allocating
    # a huge decompression fixture. The whole-file hash is deliberately valid.
    oversized = bytearray(data)
    central_header = oversized.rfind(b"PK\x01\x02")
    assert central_header >= 0
    struct.pack_into("<I", oversized, central_header + 24, 1_000_000_001)
    checkpoint.write_bytes(oversized)
    with pytest.raises(ValueError, match="expands beyond the local format bound"):
        load()
    checkpoint.write_bytes(data)

    for path, message in (
            (run_dir.parent / "shared_seed_artifact.zip", "shared seed artifact checksum mismatch"),
            (run_dir / entry["history_manifest"], "history manifest checksum mismatch"),
            (run_dir / "completed/final_pheromone.npz", "external pheromone field checksum mismatch"),
            (run_dir / "completed/events.csv", "completed history artifact checksum mismatch")):
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"corrupt")
            with pytest.raises(ValueError, match=message):
                load()
        finally:
            path.write_bytes(original)
    assert load().endpoint_metrics() == expected["metrics"]


def test_engineering_failure_distinguished_and_same_seed_recovery(small, tmp_path):
    entry = fixture_progress()["runs"][0]

    def broken(sim, state):
        if sim.time == 13:
            raise RuntimeError("injected observation error")

    with pytest.raises(RuntimeError):
        run_fixture(small, tmp_path / "failed", entry, resume=False, boundary_observer=broken)
    assert entry["status"] == "engineering_failed" and entry["seed"] == STORAGE_FIXTURE_SEED
    assert entry["time"] == 10
    row, _ = run_fixture(small, tmp_path / "failed", entry, resume=True)
    assert row["status"] == "completed"
    assert [attempt["status"] for attempt in entry["attempts"]] == ["engineering_failed", "completed"]


def test_scientific_zero_delivery_is_completed_not_engineering_failure(small, tmp_path):
    config = replace(small, food=SiteConfig((9.5, 9.5), 0.01), movement=MovementConfig(theta_deg=0), n_ants=1)
    entry = fixture_progress()["runs"][0]
    row, _ = run_fixture(config, tmp_path / "zero", entry, resume=False)
    assert entry["status"] == "completed" and row["engineering_valid"]
    assert row["metrics"]["first_pheromone_recruitment_time"]["value"] is None
    assert row["metrics"]["follower_hit_step_mean_axis_error_deg"]["availability"] == "unavailable"
    assert row["metrics"]["first_pheromone_recruitment_time"]["observed"] is False
    assert row["metrics"]["first_pheromone_recruitment_time"]["censoring_horizon"] == 80
    json_bytes(row)


def test_output_context_and_candidate_audit(small, tmp_path):
    entry = fixture_progress()["runs"][0]
    row, _ = run_fixture(small, tmp_path / "context", entry, resume=False)
    folder = tmp_path / "context/completed"
    metrics = pd.read_csv(folder / "metrics.csv")
    expected = metrics.loc[metrics.time == 80, "cumulative_deliveries"].iloc[0] - metrics.loc[metrics.time == 59, "cumulative_deliveries"].iloc[0]
    assert row["late_window_delivery_increment"] == expected
    events = pd.read_csv(folder / "events.csv")
    assert sum(row["late_window_transition_counts"].values()) == events.time.between(60, 80).sum()
    planned = paired_rows(planned_rows())[0]
    assert planned["baseline_candidate_checks"]["passed"] is None
    assert planned["baseline_engineering_valid"] is None
    rows = synthetic_complete_rows()
    summary = analyse_rows(rows)
    assert summary["candidate_counts"] == {rule: 0 for rule in RULES}
    assert len(summary["directional_contrasts"]) == 9
    rows[0]["metrics"]["cumulative_deliveries"] = measurement(0, count=1)
    reason = analyse_rows(rows)["mechanism_check_reasons"]["median_per_seed_delivery_ratio_at_least_0_80"]
    assert reason == "unresolved_required_measurements"


def test_planned_tables_40_rows_explicit_missing_no_verdict(tmp_path):
    rows = planned_rows()
    assert len(index_rows(rows)) == 40
    assert all(item["value"] is None and item["reason"] == "planned_not_run" for row in rows for item in row["metrics"].values())
    write_metric_tables(tmp_path, rows)
    frame = pd.read_csv(tmp_path / "per_seed_metrics.csv")
    assert len(frame) == 40 and frame.status.eq("planned").all()
    assert frame.late_window_mean_psi.isna().all()
    assert len(pd.read_csv(tmp_path / "paired_comparison.csv")) == 20
    summary = analyse_rows(rows)
    assert summary["final_verdict_available"] is False
    assert "mechanism_improvement" not in summary and "scientific_conclusion" not in summary


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_json_and_measurement_rejected(bad):
    with pytest.raises(ValueError):
        json_bytes({"bad": bad})
    with pytest.raises(ValueError):
        measurement(bad, count=1)


def test_bootstrap_matches_fixed_pair_resampling_and_percentile():
    assert BOOTSTRAP_SEED == 20260999 and BOOTSTRAP_REPETITIONS == 10000
    expected_indices = np.random.Generator(np.random.PCG64(20260999)).integers(0, 20, size=(10000, 20), dtype=np.int64)
    np.testing.assert_array_equal(bootstrap_indices(), expected_indices)
    baseline = np.linspace(-100, 100, 20)
    delta = np.linspace(-0.2, 0.4, 20)
    pca = baseline + delta
    interval = paired_bootstrap(baseline, pca)
    expected = np.quantile((pca - baseline)[expected_indices].mean(axis=1), [0.025, 0.975], method="linear")
    np.testing.assert_array_equal([interval["lower"], interval["upper"]], expected)
    # Perfect within-pair association cancels arbitrary between-seed offsets.
    constant = paired_bootstrap(np.arange(20.0) * 100, np.arange(20.0) * 100 + 0.25)
    assert constant["lower"] == constant["upper"] == 0.25
    assert interval["unit"] == "seed_pair" and interval["quantile_method"] == "linear"


def synthetic_complete_rows():
    """Invented numbers solely to exercise decision code, never simulated evidence."""
    rows = planned_rows()
    for row in rows:
        pca = row["rule"] == RULES[1]
        row.update(status="completed", engineering_valid=True,
                   initial_identity={"seed": row["seed"], "test_fixture": True},
                   transition_counts={"follower_to_transporter": 10, "transporter_to_follower": 10})
        values = {name: 1.0 for name in METRICS}
        values.update(late_window_mean_psi=0.71 if pca else 0.60,
            follower_late_window_mean_psi=0.71 if pca else 0.60,
            late_window_mean_phi=0.2 if pca else 0.1,
            absolute_late_phi_distance=abs((0.2 if pca else 0.1) - np.pi / 4),
            follower_hit_step_mean_axis_error_deg=30.0 if pca else 40.0,
            follower_local_continuity_mean_axis_change_deg=10.0 if pca else 20.0,
            follower_sensing_miss_rate=0.01 if pca else 0.02,
            cumulative_deliveries=110 if pca else 100,
            completed_transporter_mean_path_efficiency=0.7 if pca else 0.6,
            main_channel_width_90=90.0 if pca else 100.0)
        row["metrics"] = {m: measurement(v, count=1001) for m, v in values.items()}
    return rows


def test_synthetic_pass_fail_mixed_and_ratio_not_pooled():
    rows = synthetic_complete_rows()
    passed = analyse_rows(rows)
    assert passed["mechanism_improvement"] == passed["scientific_conclusion"] == "PASS"
    assert passed["fig4_candidate"] == "FAIL"
    assert passed["metrics"]["late_window_mean_psi"]["counts"]["improved"] == 20
    for row in rows:
        if row["rule"] == RULES[1]:
            row["metrics"]["cumulative_deliveries"]["value"] = 1
    mixed = analyse_rows(rows)
    assert mixed["mechanism_improvement"] == "FAIL" and mixed["scientific_conclusion"] == "MIXED"
    equal = synthetic_complete_rows()
    for i in range(0, 40, 2):
        equal[i + 1]["metrics"] = deepcopy(equal[i]["metrics"])
    failed = analyse_rows(equal)
    assert failed["mechanism_improvement"] == failed["scientific_conclusion"] == "FAIL"
    assert failed["metrics"]["late_window_mean_psi"]["counts"]["equal"] == 20
    rows = synthetic_complete_rows()
    for i in range(20):
        rows[2*i]["metrics"]["cumulative_deliveries"]["value"] = 1 if i < 19 else 10000
        rows[2*i+1]["metrics"]["cumulative_deliveries"]["value"] = 1
    result = analyse_rows(rows)
    assert result["delivery_ratio"]["median"] == 1.0
    assert result["mechanism_checks"]["median_per_seed_delivery_ratio_at_least_0_80"]


def test_zero_denominator_missing_samples_and_partial_no_final_verdict():
    rows = synthetic_complete_rows()
    rows[0]["metrics"]["cumulative_deliveries"]["value"] = 0
    assert paired_rows(rows)[0]["delivery_ratio"] is None
    assert paired_rows(rows)[0]["delivery_ratio_reason"] == "zero_baseline_deliveries"
    summary = analyse_rows(rows)
    assert summary["mechanism_improvement"] == "FAIL" and summary["scientific_conclusion"] == "MIXED"
    rows[1]["metrics"]["follower_hit_step_mean_axis_error_deg"] = measurement(None, count=0, reason="no_sensing_hits")
    assert analyse_rows(rows)["mechanism_improvement"] == "FAIL"
    rows[-1]["status"] = "interrupted"
    partial = analyse_rows(rows)
    assert not partial["final_verdict_available"] and "scientific_conclusion" not in partial
    rows = synthetic_complete_rows()
    rows[-1]["initial_identity"] = {"wrong": True}
    assert analyse_rows(rows)["status"] == "invalid"


def test_resource_projection_fixed_factor_and_all_costs():
    assert SAFETY_FACTOR == 1.5
    estimate = resource_projection(elapsed_seconds=100, stored_bytes=1000, remaining_runs=38,
        run_seconds=120, retained_completed_run_bytes=1_000_000,
        retained_checkpoint_bytes_per_completed_run=2_000_000,
        shared_seed_artifact_bytes=500_000, remaining_shared_seed_artifacts=19,
        active_checkpoint_overlap_bytes=3_000_000,
        completion_publication_overlap_bytes=250_000,
        analysis_seconds=20, final_analysis_allowance_bytes=2000)
    assert estimate["projected_total_seconds"] == 100 + 1.5 * 38 * 120 + 20
    assert estimate["projected_peak_additional_bytes"] == (
        1000 + 1.5 * 38 * 3_000_000 + 19 * 500_000 + 3_000_000 + 250_000 + 2000)
    assert estimate["action"] == "continue"
    assert estimate["current_machine_pilot_observed"] is False
    assert estimate["safety_factor"] == 1.5


@pytest.mark.parametrize("overhead", [10.0, 100.0, None, float("nan"), -1.0])
def test_completed_compression_time_cannot_bypass_resource_gate(overhead):
    result = resource_projection(
        elapsed_seconds=100, stored_bytes=0, remaining_runs=40, run_seconds=150,
        completed_checkpoint_seconds=overhead,
        retained_completed_run_bytes=1, retained_checkpoint_bytes_per_completed_run=1,
        shared_seed_artifact_bytes=1, remaining_shared_seed_artifacts=20,
        active_checkpoint_overlap_bytes=1)
    if overhead is not None and np.isfinite(overhead) and overhead >= 0:
        assert result["projected_total_seconds"] == 100 + 1.5 * 40 * (150 + overhead) + 600
        assert result["action"] == ("pause" if overhead == 100 else "continue")
    else:
        assert result["projected_total_seconds"] is None
        assert "projection_unresolved" in result["reasons"]


def test_transient_checkpoint_overlap_is_included_once_not_per_run():
    arguments = dict(
        elapsed_seconds=0, stored_bytes=100, remaining_runs=40, run_seconds=1,
        retained_completed_run_bytes=1000,
        retained_checkpoint_bytes_per_completed_run=2000,
        shared_seed_artifact_bytes=3000, remaining_shared_seed_artifacts=20,
        final_analysis_allowance_bytes=4000,
        completion_publication_overlap_bytes=5000)
    first = resource_projection(**arguments, active_checkpoint_overlap_bytes=6000)
    second = resource_projection(**arguments, active_checkpoint_overlap_bytes=6001)
    assert second["projected_peak_additional_bytes"] - first["projected_peak_additional_bytes"] == 1
    assert first["projected_peak_additional_bytes"] == (
        100 + 1.5 * 40 * (1000 + 2000) + 20 * 3000 + 6000 + 5000 + 4000)


def test_completed_retention_is_checkpoint_plus_long_term_artifacts():
    result = resource_projection(
        elapsed_seconds=0, stored_bytes=0, remaining_runs=2, run_seconds=1,
        retained_completed_run_bytes=7, retained_checkpoint_bytes_per_completed_run=11,
        shared_seed_artifact_bytes=0, remaining_shared_seed_artifacts=0,
        active_checkpoint_overlap_bytes=0, final_analysis_allowance_bytes=0)
    assert result["projected_peak_additional_bytes"] == 1.5 * 2 * (7 + 11)
    assert "retained_completed_run_bytes" in result["calculation_formula"]


@pytest.mark.parametrize("seconds,bytes_,reason", [
    (300, 1, "four_hour_limit"), (1, 40_000_000, "two_gb_limit"),
    (None, None, "projection_unresolved")])
def test_resource_pause_without_scope_change(seconds, bytes_, reason):
    result = resource_projection(
        elapsed_seconds=0, stored_bytes=0, remaining_runs=40, run_seconds=seconds,
        retained_completed_run_bytes=bytes_,
        retained_checkpoint_bytes_per_completed_run=0 if bytes_ is not None else None,
        shared_seed_artifact_bytes=0 if bytes_ is not None else None,
        remaining_shared_seed_artifacts=20,
        active_checkpoint_overlap_bytes=0 if bytes_ is not None else None)
    assert result["action"] == "pause" and reason in result["reasons"]
    assert result["remaining_runs"] == 40 and result["external_costs"] == 0
    assert result["autodl_used"] is False


def test_resource_pause_preserves_valid_checkpoint(small, tmp_path):
    entry = fixture_progress()["runs"][0]

    def resource():
        return {"action": "pause" if entry["time"] >= 10 else "continue"}

    row = run_one(small, tmp_path / "paused", IDENTITY, entry, resume=False, persist=lambda: None,
                  resource_check=resource, late_window=(60, 80), checkpoint_interval=10)
    assert row is None and entry["status"] == "interrupted" and entry["reason"] == "resource_pause"
    resumed = load_checkpoint(tmp_path / "paused" / entry["checkpoint"], small, IDENTITY,
                              expected_sha256=entry["checkpoint_sha256"])
    assert resumed.time == 10
    slots = sorted((tmp_path / "paused").glob("checkpoint-*.zip"))
    assert len(slots) == 2
    with zipfile.ZipFile(tmp_path / "paused" / entry["checkpoint"]) as archive:
        metadata = json.loads(archive.read("metadata.json"))
        assert all(item.compress_type == zipfile.ZIP_DEFLATED for item in archive.infolist())
    assert metadata["storage_layout"] == "compact_referenced_v2"
    assert "turn_schedules" not in [item[0] for item in metadata["state"]["items"]]


def test_dry_run_no_simulation_or_initialisation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run started or initialised a simulation")
    monkeypatch.setattr(ColonySimulation, "run", forbidden)
    monkeypatch.setattr(ColonySimulation, "__init__", forbidden)
    monkeypatch.setattr(ColonySimulation, "step", forbidden)
    monkeypatch.setattr(StreamingSimulation, "__init__", forbidden)
    monkeypatch.setattr(StreamingSimulation, "endpoint_metrics", forbidden)
    result = dry_run(ROOT, tmp_path / "dry-run")
    assert not result["simulation_started"] and not result["scientific_metrics_generated"]
    assert result["runtime"]["current_machine_pilot_observed"] is False
    assert not (tmp_path / "dry-run/summary.json").exists()
    assert not (ROOT / "results/stage2c_multiseed_confirmation").exists()
    assert len(pd.read_csv(tmp_path / "dry-run/per_seed_metrics.csv")) == 40
    manifest = read_json(tmp_path / "dry-run/config_manifest.json")
    assert manifest["identity"]["preregistration_commit"] == PREREGISTRATION_COMMIT
    assert manifest["identity"]["stage2b_implementation_commit"] == IMPLEMENTATION_COMMIT
    runtime = result["runtime"]
    required = {
        "retained_completed_run_bytes",
        "retained_checkpoint_bytes_per_completed_run",
        "shared_seed_artifact_bytes",
        "active_checkpoint_overlap_bytes",
        "final_analysis_allowance_bytes",
        "remaining_runs", "safety_factor", "projected_peak_additional_bytes",
        "storage_limit_bytes", "calculation_formula", "assumptions",
        "measurement_status",
    }
    assert required <= runtime.keys()
    preflight = runtime["storage_only_preflight"]
    assert preflight["simulation_steps_executed"] == 0
    assert preflight["scientific_seed_used"] is False
    assert preflight["storage_fixture_seed"] == STORAGE_FIXTURE_SEED == 991337
    assert preflight["completed_fixture_arrays_all_nonzero"]
    assert preflight["completed_checkpoint_members_byte_exact"]
    assert preflight["legacy_completed_checkpoint_bytes"] == 19_684_283
    assert preflight["synthetic_max_completed_checkpoint_bytes"] <= 17_000_000
    assert runtime["projected_peak_additional_bytes"] <= 1_975_000_000
    assert runtime["projected_total_seconds"] < 14_400
    assert runtime["action"] == "continue"
    timing = preflight["completed_checkpoint_timing"]
    assert runtime["completed_checkpoint_seconds_allowance"] == (
        timing["completed_lzma_encode_seconds"] + timing["completed_lzma_read_seconds"])
    assert timing["completed_lzma_encode_seconds"] > 0
    assert timing["completed_lzma_read_seconds"] > 0
    planned = pd.read_csv(tmp_path / "dry-run/per_seed_metrics.csv")
    assert planned.status.eq("planned").all() and planned.late_window_mean_psi.isna().all()
    assert not (tmp_path / "dry-run/runs").exists()
    assert preflight["synthetic_max_active_checkpoint_bytes"] > preflight["initial_checkpoint_bytes"]
    assert preflight["uncompressed_numeric_bytes"]["travel_paths"] > 0
    assert runtime["safety_factor"] == 1.5


def test_cli_dry_run_only(tmp_path):
    output = tmp_path / "cli-dry-run"
    result = subprocess.run([str(ROOT / "run_stage2c.sh"), "--mode", "dry-run", "--output-dir", str(output)],
                            cwd=ROOT, text=True, capture_output=True, check=True,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    evidence = json.loads(result.stdout)
    assert evidence["mode"] == "dry-run" and evidence["planned_runs"] == 40
    assert not evidence["final_verdict_available"]
    assert not (output / "runs").exists()


def test_runner_always_forces_matplotlib_agg():
    python_entry = (ROOT / "scripts/run_stage2c.py").read_text()
    shell_entry = (ROOT / "run_stage2c.sh").read_text()
    assert 'os.environ["MPLBACKEND"] = "Agg"' in python_entry
    assert 'export MPLBACKEND=Agg' in shell_entry


def test_analyse_refuses_incomplete_study_without_running(tmp_path, monkeypatch):
    output = tmp_path / "incomplete"
    dry_run(ROOT, output)
    study = Study(ROOT, output)
    monkeypatch.setattr(ColonySimulation, "run", lambda *a, **k: pytest.fail("analysis ran simulation"))
    with pytest.raises(ValueError, match="all 20"):
        study.analyse()
    assert not (output / "summary.json").exists()


def test_four_figures_on_synthetic_fixture_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    rows = synthetic_complete_rows()
    summary = analyse_rows(rows)
    write_comparison_figures(tmp_path, rows, summary, test_fixture=True)
    assert len(list(tmp_path.glob("*.png"))) == 4
    assert all(p.stat().st_size > 1000 for p in tmp_path.glob("*.png"))


def test_default_stage2a_small_replay_against_frozen_commit(small, tmp_path):
    """Compare an isolated frozen source checkout, without a full-size replay."""
    frozen = tmp_path / "frozen"
    files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", IMPLEMENTATION_COMMIT, "src"], cwd=ROOT, text=True).splitlines()
    for name in files:
        path = frozen / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subprocess.check_output(["git", "show", f"{IMPLEMENTATION_COMMIT}:{name}"], cwd=ROOT))
    config_path = tmp_path / "config.json"
    config_path.write_bytes(json_bytes(small.to_dict()))
    code = """
import hashlib,json,sys
from colony.config import ColonyConfig,MovementConfig,PheromoneConfig,SiteConfig
from colony.simulation import ColonySimulation
d=json.load(open(sys.argv[1]))
d['movement']=MovementConfig(**d['movement']);d['pheromone']=PheromoneConfig(**d['pheromone'])
d['nest']=SiteConfig(tuple(d['nest']['center']),d['nest']['radius']);d['food']=SiteConfig(tuple(d['food']['center']),d['food']['radius'])
d['snapshot_steps']=tuple(d['snapshot_steps'])
assert d['n_ants'] < 100 and d['steps'] < 10000
assert d['seed'] not in range(20260901, 20260921)
s=ColonySimulation(ColonyConfig(**d));r=s.run()
h={n:hashlib.sha256(getattr(r,n).to_csv(index=False,lineterminator='\\n').encode()).hexdigest() for n in ['metrics','agent_states','final_agents','events']}
h['intensity']=hashlib.sha256(s.field.intensity.tobytes()).hexdigest();h['direction_sum']=hashlib.sha256(s.field.direction_sum.tobytes()).hexdigest()
print(json.dumps(h))
"""
    result = subprocess.run([sys.executable, "-B", "-c", code, str(config_path)], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(frozen / "src"), PYTHONDONTWRITEBYTECODE="1"),
                            text=True, capture_output=True, check=True)
    expected = json.loads(result.stdout)
    current = simulation(small)
    actual_result = current.run()
    actual = {n: hashlib.sha256(b).hexdigest() for n, b in frame_bytes(actual_result).items()}
    actual["intensity"] = hashlib.sha256(current.field.intensity.tobytes()).hexdigest()
    actual["direction_sum"] = hashlib.sha256(current.field.direction_sum.tobytes()).hexdigest()
    assert actual == expected


def test_follower_late_window_eligibility_and_mean_match_full(small):
    config = replace(small, food=SiteConfig((9.9, 9.9), 0.01))
    agents = artificial_start(config)
    for ant in agents:
        ant.role = Role.FOLLOWER
    kwargs = {"initial_agents": agents, "turn_schedules": np.zeros((6, 80))}
    full = DiagnosticSimulation(config, **kwargs)
    observed = StreamingSimulation(config, late_window=(60, 80), **kwargs)
    full.run()
    observed.run()
    selected = pd.DataFrame(full.role_order_records).query("role == 'follower' and 60 <= time <= 80")
    assert selected.sample_count.eq(6).all()
    for key in ("phi", "psi"):
        expected_column = "orientation_order_phi" if key == "phi" else "nematic_order_psi"
        item = observed.endpoint_metrics()["follower_late_window_mean_" + key]
        assert item["availability"] == "available" and item["count"] == 21
        assert item["value"] == pytest.approx(selected[expected_column].mean(), abs=1e-14)
    observed.follower_sufficient_count -= 1
    assert observed.endpoint_metrics()["follower_late_window_mean_psi"]["value"] is None


def test_paired_initial_mismatch_stops_before_first_step(small, tmp_path, monkeypatch):
    entry = fixture_progress()["runs"][0]
    monkeypatch.setattr(ColonySimulation, "step", lambda *a: pytest.fail("mismatched initialisation reached a step"))
    with pytest.raises(ValueError, match="before first step"):
        run_one(small, tmp_path / "mismatch", IDENTITY, entry, resume=False,
                persist=lambda: None, resource_check=lambda: {"action": "continue"},
                late_window=(60, 80), expected_initial={"wrong": True})
    assert entry["status"] == "engineering_failed" and entry["time"] == 0


@pytest.mark.parametrize("relative", [".", ".git", "src/colony", "reports", "results/stage2b_local_geometry"])
def test_outputs_cannot_overlap_protected_paths(relative):
    with pytest.raises(ValueError):
        validate_output(ROOT, ROOT / relative)


def test_unidentified_output_not_overwritten(tmp_path):
    path = tmp_path / "unidentified"
    path.mkdir()
    (path / "keep.txt").write_text("existing")
    with pytest.raises(FileExistsError):
        dry_run(ROOT, path)
    assert (path / "keep.txt").read_text() == "existing"


def test_completed_receipt_tampering_refused(small, tmp_path):
    entry = fixture_progress()["runs"][0]
    run_fixture(small, tmp_path / "complete", entry, resume=False)
    path = tmp_path / "complete/completed/events.csv"
    path.write_bytes(path.read_bytes() + b"tampered\n")
    with pytest.raises(ValueError, match="artifacts changed"):
        run_fixture(small, tmp_path / "complete", entry, resume=True)


def test_completed_receipt_recovers_crash_without_rerun(small, tmp_path, monkeypatch):
    entry = fixture_progress()["runs"][0]
    expected, _ = run_fixture(small, tmp_path / "complete", entry, resume=False)
    entry["status"] = "running"  # Simulate rename succeeded but progress publication was lost.
    monkeypatch.setattr(StreamingSimulation, "__init__", lambda *a, **k: pytest.fail("completed run was restarted"))
    actual, _ = run_fixture(small, tmp_path / "complete", entry, resume=True)
    assert actual == expected and entry["status"] == "completed"


def test_engineering_receipt_is_bound_and_failure_stops(tmp_path, monkeypatch):
    monkeypatch.setattr("colony.stage2c.tempfile.tempdir", str(tmp_path))
    output = tmp_path / "validation"
    output.mkdir()
    calls = []

    def fake_tests(command, **kwargs):
        calls.append(command)
        assert "--basetemp" in command and "no:cacheprovider" in command
        return subprocess.CompletedProcess(command, 0, "101 passed in 1.0s\n", "")

    monkeypatch.setattr(subprocess, "run", fake_tests)
    receipt = verify_engineering_tests(ROOT, output, IDENTITY)
    assert receipt["passed"] and receipt["passed_count"] == 101
    assert verify_engineering_tests(ROOT, output, IDENTITY) == receipt and len(calls) == 1
    with pytest.raises(ValueError):
        verify_engineering_tests(ROOT, output, {"changed": True})
    failure = tmp_path / "failed_validation"
    failure.mkdir()
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "1 failed\n", ""))
    with pytest.raises(RuntimeError, match="no confirmatory simulation"):
        verify_engineering_tests(ROOT, failure, IDENTITY)
