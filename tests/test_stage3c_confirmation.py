from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import importlib.util
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pytest

from scalar_baseline.stage3b import RECOVERY_DURATION, old_trail_mask, state_digest
import scalar_baseline.stage3c as stage3c
from scalar_baseline.stage3c import (
    ARMS,
    CAPPED_RECOVERY_TIME,
    CONFIRMATORY_SEEDS,
    OBSERVATION_END,
    RELOCATION_STEP,
    STAGE3B_PREFIX_STEPS,
    TOTAL_STEPS,
    ConfigurationError,
    EvidenceError,
    Stage3CB0Simulation,
    Stage3CRecoverySimulation,
    b0_replay_audit,
    compute_capped_recovery_time,
    confirmatory_config,
    create_first_pair_engineering_receipt,
    fixture_config,
    initialise_prerun_engineering_audit,
    initialise_study_protection,
    navigation_isolation_audit,
    pair_configuration_identity,
    pair_identity_audit,
    protected_snapshot,
    resource_limits_pass,
    run_arm_atomic,
    schedule_bundle,
    schedule_prefix_audit,
    single_change_audit,
    static_resource_estimate,
    validate_complete_study,
    validate_confirmatory_config,
    validate_first_pair_engineering_receipt,
    validate_run_directory,
    verify_protected_snapshot,
)
from scalar_baseline.stage3c_analysis import (
    analyse_pairs,
    rows_from_study,
    write_analysis,
)


ROOT = Path(__file__).resolve().parents[1]


def synthetic_rows(*, b0=10_000, candidate=7_000, pre_b0=10, pre_c=8):
    return [
        {
            "seed": seed,
            "B0_capped_recovery_time": b0,
            "C_capped_recovery_time": candidate,
            "B0_non_delivery": b0 == CAPPED_RECOVERY_TIME,
            "C_non_delivery": candidate == CAPPED_RECOVERY_TIME,
            "B0_pre_A_deliveries": pre_b0,
            "C_pre_A_deliveries": pre_c,
        }
        for seed in CONFIRMATORY_SEEDS
    ]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_synthetic_completed_run(root: Path, config, *, b0_time=10_000, c_time=7_000):
    """Create temporary synthetic evidence; never execute a formal simulation."""
    folder = root / "runs" / str(config.seed) / config.arm
    folder.mkdir(parents=True)
    capped = b0_time if config.arm == "B0" else c_time
    summary = {
        "evidence_status": "confirmatory" if config.formal else "engineering-fixture",
        "seed": config.seed,
        "arm": config.arm,
        "status": "complete",
        "steps_completed": config.simulation.steps,
        "capped_recovery_time": capped,
        "non_delivery": capped == CAPPED_RECOVERY_TIME,
        "pre_relocation_A_deliveries": 10 if config.arm == "B0" else 8,
    }
    data = {
        "config.json": config.as_record(),
        "summary.json": summary,
        "timeseries_100step.json": [],
        "ledger_events.json": [],
        "source_identity.json": stage3c._source_identity(ROOT),
        "resources.json": {
            "pass": True,
            "cpu_seconds": 0.1,
            "wall_seconds": 0.1,
            "peak_rss_bytes": 1,
            "temporary_output_bytes": 1,
        },
        "integrity.json": {"pass": True},
        "storage.json": {"synthetic_test_fixture": True},
    }
    if config.arm == "C":
        data["recovery_episodes.json"] = []
    for name, value in data.items():
        (folder / name).write_text(json.dumps(value, allow_nan=False) + "\n")
    np.savez_compressed(folder / "field_snapshots.npz", fixture=np.zeros((1, 1)))
    files = {
        str(path.relative_to(folder)): {"bytes": path.stat().st_size, "sha256": _hash(path)}
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }
    receipt = {
        "status": "complete",
        "seed": config.seed,
        "arm": config.arm,
        "formal": config.formal,
        "recursive_files_excluding_this_receipt": files,
    }
    (folder / "completed_receipt.json").write_text(json.dumps(receipt) + "\n")
    return folder


def test_exact_confirmatory_seed_set():
    assert CONFIRMATORY_SEEDS == tuple(range(2026092101, 2026092121))
    assert len(CONFIRMATORY_SEEDS) == len(set(CONFIRMATORY_SEEDS)) == 20


def test_formal_timeline_and_frozen_configuration():
    config = confirmatory_config(CONFIRMATORY_SEEDS[0], "B0")
    assert config.simulation.steps == TOTAL_STEPS == 18_000
    assert config.simulation.relocation_step == RELOCATION_STEP == 6_000
    assert OBSERVATION_END == 17_999 and CAPPED_RECOVERY_TIME == 12_000
    assert config.simulation.diffusion == 0
    assert config.simulation.decay.half_life_steps == pytest.approx(1000)


@pytest.mark.parametrize("seed", [0, 2026091701, 2026092121])
def test_formal_config_rejects_unknown_seed(seed):
    with pytest.raises(ConfigurationError):
        confirmatory_config(seed, "B0")


def test_formal_config_rejects_unknown_arm():
    with pytest.raises(ConfigurationError):
        confirmatory_config(CONFIRMATORY_SEEDS[0], "D")


def test_formal_config_rejects_modified_key_parameter():
    config = confirmatory_config(CONFIRMATORY_SEEDS[0], "B0")
    changed = replace(config, simulation=replace(config.simulation, steps=17_999))
    with pytest.raises(ConfigurationError):
        validate_confirmatory_config(changed)


def test_fixture_requires_nonformal_seed_and_label():
    with pytest.raises(ConfigurationError):
        fixture_config(seed=CONFIRMATORY_SEEDS[0])
    with pytest.raises(ConfigurationError):
        fixture_config(fixture_label="")


def test_pair_configuration_differs_only_by_treatment():
    b0 = confirmatory_config(CONFIRMATORY_SEEDS[0], "B0").as_record()
    candidate = confirmatory_config(CONFIRMATORY_SEEDS[0], "C").as_record()
    assert pair_configuration_identity(b0, candidate)["pass"]


def test_primary_endpoint_no_delivery_is_valid_cap():
    assert compute_capped_recovery_time(None) == (12_000, True)


@pytest.mark.parametrize(
    ("delivery", "expected"),
    [(6_000, (0, False)), (17_999, (11_999, False)), (18_000, (12_000, True))],
)
def test_primary_endpoint_off_by_one(delivery, expected):
    assert compute_capped_recovery_time(delivery) == expected


def test_primary_endpoint_rejects_pre_relocation_delivery():
    with pytest.raises(ValueError):
        compute_capped_recovery_time(5_999)


def test_schedule_prefix_is_byte_exact_for_all_streams():
    audit = schedule_prefix_audit()
    assert audit["pass"] and audit["simulation_steps_executed"] == 0


def test_schedule_deterministic_same_seed_and_arm():
    config = fixture_config(seed=31101, steps=80).simulation
    first = schedule_bundle(config, 0)
    second = schedule_bundle(config, 0)
    assert first["initial_heading"] == second["initial_heading"]
    for name in ("fcrw_turns", "follower_noise", "recovery_sides"):
        np.testing.assert_array_equal(first[name], second[name])


def test_pair_initial_state_and_treatment_independent_randomness():
    assert pair_identity_audit()["pass"]


def test_b0_never_reads_recovery_side_schedule_for_movement():
    config = fixture_config(seed=31102, steps=40, n_ants=2).simulation
    first, second = Stage3CB0Simulation(config), Stage3CB0Simulation(config)
    second._recovery_sides *= -1
    for _ in range(config.steps):
        first.step()
        second.step()
    assert state_digest(first) == state_digest(second)


def test_C_uses_side_only_after_recovery_branch_starts():
    source = inspect.getsource(stage3c.RecoverySimulation._move)
    assert "_start_recovery" in source
    assert "_recovery_sides" not in source
    assert "_recovery_sides" in inspect.getsource(stage3c.RecoverySimulation._start_recovery)


def test_recovery_remains_exactly_24_movements():
    config = fixture_config(
        seed=31103, arm="C", steps=40, n_ants=1, relocation_step=None
    ).simulation
    sim = Stage3CRecoverySimulation(config)
    ant, state = sim.ants[0], sim.recovery[0]
    ant.role, ant.heading, ant.low_steps = "follower", 0.0, 1
    state.last_reliable_heading = 0.0
    sim.time = 1
    sim._move(ant)
    for time_index in range(2, 25):
        sim.time = time_index
        sim._move(ant)
    assert not state.recovery_active
    assert sim.recovery_episodes[0]["duration"] == RECOVERY_DURATION == 24
    assert sim.recovery_episodes[0]["outcome"] == "timeout"


def test_single_change_and_navigation_isolation_audits_pass():
    assert single_change_audit()["pass"]
    isolation = navigation_isolation_audit()
    assert isolation["pass"] and isolation["offline_masks_used_by_movement"] is False


def test_B0_stage3b_prefix_replay_with_fixture_seed():
    result = b0_replay_audit(seed=31104, n_ants=1)
    assert result["pass"]
    assert result["compared_through_step"] == STAGE3B_PREFIX_STEPS
    assert result["confirmatory_seed_used"] is False


def test_offline_masks_do_not_change_dynamics_or_random_consumption():
    config = fixture_config(seed=31105, steps=30, n_ants=2).simulation
    measured, control = Stage3CRecoverySimulation(config), Stage3CRecoverySimulation(config)
    for _ in range(config.steps):
        measured.step()
        old_trail_mask(measured)
        stage3c._old_trail_ant_count(measured)
        control.step()
    assert state_digest(measured) == state_digest(control)


def test_food_A_cargo_remains_A_after_relocation():
    config = fixture_config(seed=31106, arm="C", steps=10, n_ants=1, relocation_step=2)
    sim = Stage3CRecoverySimulation(config.simulation)
    sim.ledger.pickup(0, "A", 1)
    sim.ants[0].role = "transporter"
    sim.environment.relocate(2, sim.ledger)
    sim.ledger.deliver(0, 3)
    assert sim.ledger.deliveries == {"A": 1, "B": 0}
    assert sim.ledger.carried_a_at_relocation == [0]


def test_atomic_publication_and_completed_validation(tmp_path):
    config = fixture_config(seed=31107, arm="C", steps=8, n_ants=1, relocation_step=4)
    result = run_arm_atomic(tmp_path, config, ROOT)
    final = tmp_path / "runs" / str(config.seed) / "C"
    assert final.is_dir() and not result["reused"]
    assert validate_run_directory(final, config)["pass"]
    assert (final / "recovery_episodes.json").is_file()
    assert not list(final.parent.glob("*.tmp-*"))


def test_completed_run_reuse_and_overwrite_refusal(tmp_path):
    config = fixture_config(seed=31108, steps=6, n_ants=1, relocation_step=3)
    run_arm_atomic(tmp_path, config, ROOT)
    assert run_arm_atomic(tmp_path, config, ROOT)["reused"]
    with pytest.raises(EvidenceError):
        run_arm_atomic(tmp_path, config, ROOT, reuse_completed=False)


def test_tampered_completed_evidence_is_rejected(tmp_path):
    config = fixture_config(seed=31109, steps=6, n_ants=1, relocation_step=3)
    run_arm_atomic(tmp_path, config, ROOT)
    final = tmp_path / "runs" / str(config.seed) / "B0"
    (final / "summary.json").write_text("{}\n")
    with pytest.raises(EvidenceError, match="hash mismatch"):
        validate_run_directory(final, config)


def test_incomplete_failure_is_preserved_and_blocks_retry(tmp_path, monkeypatch):
    config = fixture_config(seed=31110, steps=6, n_ants=1, relocation_step=3)

    def fail(_self):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(Stage3CB0Simulation, "step", fail)
    with pytest.raises(RuntimeError, match="fixture failure"):
        run_arm_atomic(tmp_path, config, ROOT)
    parent = tmp_path / "runs" / str(config.seed)
    assert not (parent / "B0").exists()
    assert len(list(parent.glob(f".{config.seed}-B0.incomplete-*"))) == 1
    with pytest.raises(EvidenceError, match="incomplete evidence"):
        run_arm_atomic(tmp_path, config, ROOT)


def test_first_pair_gate_refuses_missing_receipt(tmp_path):
    with pytest.raises(EvidenceError, match="requires"):
        validate_first_pair_engineering_receipt(tmp_path)


def test_first_pair_receipt_validates_synthetic_engineering_evidence(tmp_path):
    seed = CONFIRMATORY_SEEDS[0]
    initialise_study_protection(tmp_path, ROOT)
    initialise_prerun_engineering_audit(tmp_path, ROOT)
    for arm in ARMS:
        write_synthetic_completed_run(tmp_path, confirmatory_config(seed, arm))
    receipt = create_first_pair_engineering_receipt(tmp_path, ROOT)
    assert receipt["scientific_outcomes_inspected"] is False
    assert validate_first_pair_engineering_receipt(tmp_path, ROOT)["pass"]


def test_analyse_gate_refuses_incomplete_study(tmp_path):
    with pytest.raises(EvidenceError):
        validate_complete_study(tmp_path)
    with pytest.raises(EvidenceError):
        rows_from_study(tmp_path)


def test_analyse_gate_accepts_40_synthetic_completed_records(tmp_path):
    initialise_study_protection(tmp_path, ROOT)
    initialise_prerun_engineering_audit(tmp_path, ROOT)
    for seed in CONFIRMATORY_SEEDS:
        for arm in ARMS:
            write_synthetic_completed_run(tmp_path, confirmatory_config(seed, arm))
    assert validate_complete_study(tmp_path)["runs_verified"] == 40
    result = write_analysis(tmp_path)
    assert result["decision"] == "PASS"
    assert (tmp_path / "paired_primary.csv").is_file()
    assert (tmp_path / "confirmatory_analysis.json").is_file()


def test_synthetic_mechanism_PASS():
    result = analyse_pairs(synthetic_rows())
    assert result["decision"] == "PASS" and all(result["thresholds"].values())


def test_20_percent_threshold_just_below_fails():
    result = analyse_pairs(synthetic_rows(candidate=8_001))
    assert result["decision"] == "FAIL"
    assert not result["thresholds"]["mean_reduction_at_least_20_percent"]


def test_CI_upper_equal_zero_fails():
    result = analyse_pairs(synthetic_rows(b0=8_000, candidate=8_000))
    assert result["paired_bootstrap"]["confidence_interval_95"][1] == 0
    assert result["decision"] == "FAIL"
    assert not result["thresholds"]["paired_bootstrap_upper_strictly_below_zero"]


def test_pre_A_ratio_just_below_point_80_fails():
    rows = synthetic_rows(pre_b0=5, pre_c=4)
    rows[-1]["C_pre_A_deliveries"] = 3
    result = analyse_pairs(rows)
    assert result["pre_A_ratio"] == pytest.approx(0.79)
    assert result["decision"] == "FAIL"


def test_valid_non_delivery_is_analysed_not_inconclusive():
    result = analyse_pairs(synthetic_rows(b0=12_000, candidate=9_000))
    assert result["valid"] and result["decision"] == "PASS"
    assert result["B0"]["non_delivery_count"] == 20


def test_all_non_delivery_is_FAIL_not_inconclusive():
    result = analyse_pairs(synthetic_rows(b0=12_000, candidate=12_000))
    assert result["valid"] and result["decision"] == "FAIL"


def test_zero_baseline_pre_A_denominator_is_inconclusive():
    result = analyse_pairs(synthetic_rows(pre_b0=0, pre_c=0))
    assert result["decision"] == "INCONCLUSIVE"
    assert "denominator" in result["errors"][0]


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra", "corrupt"])
def test_missing_duplicate_additional_or_corrupt_rows_are_inconclusive(failure):
    rows = synthetic_rows()
    if failure == "missing":
        rows.pop()
    elif failure == "duplicate":
        rows[-1]["seed"] = rows[0]["seed"]
    elif failure == "extra":
        rows.append({**rows[-1], "seed": 99999999})
    else:
        rows[0]["B0_capped_recovery_time"] = float("nan")
    assert analyse_pairs(rows)["decision"] == "INCONCLUSIVE"


def test_unfavourable_complete_science_is_FAIL_not_inconclusive():
    result = analyse_pairs(synthetic_rows(b0=7_000, candidate=9_000))
    assert result["valid"] and result["decision"] == "FAIL"


def test_secondary_metrics_cannot_change_formal_decision():
    rows = synthetic_rows(b0=7_000, candidate=9_000)
    for row in rows:
        row["secondary_metric_claiming_large_benefit"] = -1_000_000
    result = analyse_pairs(rows)
    assert result["decision"] == "FAIL"
    assert result["secondary_metrics_used_for_decision"] is False


def test_bootstrap_is_deterministic_paired_and_linear():
    first = analyse_pairs(synthetic_rows())
    second = analyse_pairs(synthetic_rows())
    assert first["paired_bootstrap"] == second["paired_bootstrap"]
    assert first["paired_bootstrap"]["replicates"] == 10_000
    assert first["paired_bootstrap"]["seed"] == 2026092199
    assert first["paired_bootstrap"]["resampling_unit"] == "seed pair"
    assert first["paired_bootstrap"]["percentile_method"] == "linear"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wall_seconds", 600.0001),
        ("cpu_seconds", 600.0001),
        ("peak_rss_bytes", 2 * 1024**3 + 1),
        ("temporary_output_bytes", 512 * 1024**2 + 1),
        ("largest_file_bytes", 50 * 1024**2 + 1),
    ],
)
def test_each_resource_limit_is_enforced(field, value):
    record = {
        "wall_seconds": 600,
        "cpu_seconds": 600,
        "peak_rss_bytes": 2 * 1024**3,
        "temporary_output_bytes": 512 * 1024**2,
        "largest_file_bytes": 50 * 1024**2,
    }
    assert resource_limits_pass(record)
    record[field] = value
    assert not resource_limits_pass(record)


def test_static_resource_estimate_is_not_labelled_measurement():
    result = static_resource_estimate(
        ROOT / "results/stage3b_recovery_pilot/resource_summary.json"
    )
    assert result["within_limits"]
    assert "not an 18,000-step Stage 3C measurement" in result["evidence_status"]


def test_protected_snapshot_detects_mutation(tmp_path):
    protected = tmp_path / "protected"
    protected.mkdir()
    file = protected / "item.txt"
    file.write_text("before")
    snapshot = protected_snapshot([protected], tmp_path)
    assert verify_protected_snapshot(snapshot, tmp_path)["pass"]
    file.write_text("after")
    check = verify_protected_snapshot(snapshot, tmp_path)
    assert not check["pass"] and check["changed"] == ["protected/item.txt"]


def test_dry_run_initialises_no_simulation_and_creates_no_formal_results(monkeypatch):
    script = ROOT / "scripts/run_stage3c.py"
    spec = importlib.util.spec_from_file_location("stage3c_runner_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    def forbidden(_self, _config):
        raise AssertionError("dry-run initialised a simulation")

    monkeypatch.setattr(Stage3CB0Simulation, "__init__", forbidden)
    monkeypatch.setattr(Stage3CRecoverySimulation, "__init__", forbidden)
    result = module.dry_run()
    assert result["simulation_initialised"] is False
    assert result["simulation_steps_executed"] == 0
    assert result["confirmatory_seeds_run"] == 0
    assert not (ROOT / "results/stage3c_confirmatory_recovery").exists()


def test_formal_results_directory_absent_during_engineering_stage():
    assert not (ROOT / "results/stage3c_confirmatory_recovery").exists()
