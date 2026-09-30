from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scalar_baseline.config import DecayConfig, half_life_to_rate, matched_cutoff_steps
from scalar_baseline.field import ScalarField
from scalar_baseline.stage3d import (
    ARMS,
    CUTOFF_STEPS,
    SEEDS,
    ArmConfiguration,
    ConfigurationError,
    EvidenceError,
    decay_single_change_audit,
    dry_run,
    fixture_config,
    formal_config,
    matched_lifetime_audit,
    pair_single_change_audit,
    restart_equivalence_audit,
    run_arm_atomic,
    schedule_identity_audit,
    validate_run_directory,
    validate_stage3c_reuse,
)
from scalar_baseline.stage3d_analysis import analyse_rows


ROOT = Path(__file__).resolve().parents[1]


def stable_identity(label: str = "fixture") -> dict:
    return {
        "schema": "test-identity",
        "git": {"head": label, "branch": "test", "tracked_clean": True, "tracked_status": []},
        "runtime": {"python_version": "test", "numpy_version": np.__version__},
        "files": {},
    }


def test_matched_cutoff_is_exactly_2000_steps():
    assert matched_cutoff_steps(1, 0.25, half_life_to_rate(1000)) == 2000
    assert matched_lifetime_audit()["pass"]
    assert CUTOFF_STEPS == 2000


def test_hard_cutoff_timer_refresh_and_expiry():
    field = ScalarField(4, 1, DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=3))
    point = (1.2, 1.2)
    field.deposit(point, 1)
    field.advance(2)
    assert field.sample(point) == 1
    field.deposit(point, 1)
    assert field.sample(point) == 2
    field.advance(4)
    assert field.sample(point) == 2
    field.advance(5)
    assert field.sample(point) == 0


def test_same_step_redeposit_occurs_after_exact_expiry():
    field = ScalarField(4, 1, DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=2))
    point = (1.2, 1.2)
    field.deposit(point, 1)
    field.advance(2)
    assert field.sample(point) == 0
    field.deposit(point, 1)
    assert field.sample(point) == 1
    field.advance(3)
    assert field.sample(point) == 1
    field.advance(4)
    assert field.sample(point) == 0


def test_zero_deposit_does_not_refresh_timer():
    field = ScalarField(4, 1, DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=2))
    point = (1.2, 1.2)
    field.deposit(point, 1)
    field.advance(1)
    field.deposit(point, 0)
    field.advance(2)
    assert field.sample(point) == 0


def test_formal_order_is_20_seeds_and_40_hard_cutoff_arms():
    configs = [formal_config(seed, arm) for seed in SEEDS for arm in ARMS]
    assert len(configs) == 40
    assert [(c.seed, c.arm) for c in configs[:4]] == [
        (2026092101, "B0"), (2026092101, "C"),
        (2026092102, "B0"), (2026092102, "C"),
    ]
    assert all(c.simulation.decay.mode == "hard_cutoff_cell_timer" for c in configs)
    assert all(c.simulation.decay.cutoff_steps == 2000 for c in configs)


def test_formal_config_rejects_seed_arm_and_mutation():
    with pytest.raises(ConfigurationError):
        formal_config(1, "B0")
    with pytest.raises(ConfigurationError):
        formal_config(SEEDS[0], "D")
    config = formal_config(SEEDS[0], "B0")
    changed = replace(config, simulation=replace(config.simulation, steps=17_999))
    from scalar_baseline.stage3d import validate_config
    with pytest.raises(ConfigurationError):
        validate_config(changed)


@pytest.mark.parametrize("arm", ARMS)
def test_decay_law_is_only_environment_change(arm):
    result = decay_single_change_audit(SEEDS[0], arm)
    assert result["pass"]
    assert result["exponential_decay"]["mode"] == "exponential"
    assert result["hard_cutoff_decay"]["mode"] == "hard_cutoff_cell_timer"


def test_recovery_is_only_within_cutoff_pair_change():
    assert all(pair_single_change_audit(seed)["pass"] for seed in SEEDS)


def test_treatment_neutral_schedules_match_exponential():
    audit = schedule_identity_audit(SEEDS[0], ant_ids=(0, 1, 99))
    assert audit["pass"]
    assert audit["simulation_steps_executed"] == 0


def test_deterministic_restart_matches_continuous_fixture():
    audit = restart_equivalence_audit(
        fixture_config(seed=32002, arm="C", steps=36, n_ants=3, relocation_step=18)
    )
    assert audit["pass"]
    assert audit["snapshots_equal"]
    assert audit["scientific_payload_sha256"] == audit["restarted_payload_sha256"]


def test_atomic_fixture_run_receipt_covers_every_file(tmp_path):
    identity = stable_identity()
    provider = lambda _: identity
    config = fixture_config(seed=32003, arm="C", steps=40, n_ants=3, relocation_step=20)
    validation = run_arm_atomic(tmp_path, config, ROOT, identity_provider=provider)
    run = tmp_path / "runs" / str(config.seed) / config.arm
    assert validation["pass"]
    receipt = json.loads((run / "completed_receipt.json").read_text())
    present = {str(p.relative_to(run)) for p in run.rglob("*") if p.is_file()}
    assert set(receipt["recursive_files_excluding_this_receipt"]) == present - {"completed_receipt.json"}
    assert validate_run_directory(run, config, expected_execution_identity=identity)["pass"]


def test_completed_fixture_is_reused_without_overwrite(tmp_path):
    identity = stable_identity()
    provider = lambda _: identity
    config = fixture_config(seed=32004, arm="B0", steps=30, n_ants=2, relocation_step=15)
    run_arm_atomic(tmp_path, config, ROOT, identity_provider=provider)
    receipt = tmp_path / "runs" / str(config.seed) / config.arm / "completed_receipt.json"
    before = hashlib.sha256(receipt.read_bytes()).hexdigest()
    run_arm_atomic(tmp_path, config, ROOT, identity_provider=provider)
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == before


def test_resume_requires_exact_seed_arm_config_and_identity(tmp_path):
    identity = stable_identity()
    provider = lambda _: identity
    config = fixture_config(seed=32005, arm="B0", steps=24, n_ants=2, relocation_step=12)
    parent = tmp_path / "runs" / str(config.seed)
    temporary = parent / f".{config.seed}-{config.arm}.tmp-test"
    temporary.mkdir(parents=True)
    from scalar_baseline.stage3d import _canonical_sha256
    resume = {
        "schema": "stage3d-resume-identity-v1", "seed": config.seed,
        "arm": config.arm, "config_sha256": _canonical_sha256(config.as_record()),
        "execution_identity_sha256": _canonical_sha256(identity),
        "policy": "restart unpublished deterministic arm from step zero",
    }
    (temporary / "resume_identity.json").write_text(json.dumps(resume))
    assert run_arm_atomic(tmp_path, config, ROOT, identity_provider=provider)["pass"]


def test_resume_rejects_identity_mismatch(tmp_path):
    identity = stable_identity()
    config = fixture_config(seed=32006, arm="B0", steps=24, n_ants=2, relocation_step=12)
    parent = tmp_path / "runs" / str(config.seed)
    temporary = parent / f".{config.seed}-{config.arm}.tmp-test"
    temporary.mkdir(parents=True)
    (temporary / "resume_identity.json").write_text(json.dumps({
        "schema": "stage3d-resume-identity-v1", "seed": config.seed,
        "arm": config.arm, "config_sha256": "wrong",
        "execution_identity_sha256": "wrong", "policy": "wrong",
    }))
    with pytest.raises(EvidenceError):
        run_arm_atomic(tmp_path, config, ROOT, identity_provider=lambda _: identity)


def test_corrupt_completed_artifact_is_rejected(tmp_path):
    identity = stable_identity()
    config = fixture_config(seed=32007, arm="B0", steps=24, n_ants=2, relocation_step=12)
    run_arm_atomic(tmp_path, config, ROOT, identity_provider=lambda _: identity)
    run = tmp_path / "runs" / str(config.seed) / config.arm
    (run / "summary.json").write_text("{}")
    with pytest.raises(EvidenceError):
        validate_run_directory(run, config, expected_execution_identity=identity)


def _analysis_rows(interactions: list[int] | None = None) -> list[dict]:
    interactions = interactions or [0] * 20
    rows = []
    for index, seed in enumerate(SEEDS):
        exp_b0, exp_c = 7000, 6500
        d_exp = exp_c - exp_b0
        d_cut = d_exp + interactions[index]
        cut_b0, cut_c = 7000, 7000 + d_cut
        rows.append({
            "seed": seed,
            "B0_exponential_capped_time": exp_b0,
            "C_exponential_capped_time": exp_c,
            "B0_cutoff_capped_time": cut_b0,
            "C_cutoff_capped_time": cut_c,
            "d_exp_C_minus_B0": d_exp,
            "d_cut_C_minus_B0": d_cut,
            "interaction_d_cut_minus_d_exp": interactions[index],
            "B0_exponential_non_delivery": False,
            "C_exponential_non_delivery": False,
            "B0_cutoff_non_delivery": False,
            "C_cutoff_non_delivery": False,
            "B0_cutoff_pre_A_deliveries": 2,
            "C_cutoff_pre_A_deliveries": 2,
        })
    return rows


def _stage3c_analysis() -> dict:
    return {
        "decision": "FAIL",
        "delta_time_C_minus_B0": [-500.0] * 20,
        "paired_bootstrap": {"confidence_interval_95": [-500.0, -500.0]},
    }


def test_interaction_and_bootstrap_are_reproducible():
    rows = _analysis_rows(list(range(-10, 10)))
    first, first_replicates = analyse_rows(rows, _stage3c_analysis())
    second, second_replicates = analyse_rows(rows, _stage3c_analysis())
    assert first == second
    assert np.array_equal(first_replicates, second_replicates)
    assert first["paired_bootstrap"]["seed"] == 2026092299
    assert first["paired_bootstrap"]["replicates"] == 10_000
    assert first["paired_bootstrap"]["percentile_method"] == "linear"


def test_negative_one_sided_interaction_is_detected_with_direction():
    result, _ = analyse_rows(_analysis_rows([-1000] * 20), _stage3c_analysis())
    assert result["classification"] == "INTERACTION_DETECTED"
    assert result["interaction"]["confidence_interval_95"] == [-1000.0, -1000.0]
    assert result["interaction"]["direction_if_detected"] == "hard cutoff makes C relatively more favourable"


def test_zero_interaction_is_no_clear_interaction():
    result, _ = analyse_rows(_analysis_rows(), _stage3c_analysis())
    assert result["classification"] == "NO_CLEAR_INTERACTION"
    assert result["interaction"]["confidence_interval_95"] == [0.0, 0.0]


def test_pre_a_guard_can_block_detected_interval():
    rows = _analysis_rows([-1000] * 20)
    for row in rows:
        row["B0_cutoff_pre_A_deliveries"] = 10
        row["C_cutoff_pre_A_deliveries"] = 1
    result, _ = analyse_rows(rows, _stage3c_analysis())
    assert result["thresholds"]["interaction_CI_entirely_on_one_side_of_zero"]
    assert not result["thresholds"]["hard_cutoff_pre_A_ratio_at_least_0_80"]
    assert result["classification"] == "NO_CLEAR_INTERACTION"


def test_analysis_refuses_missing_seed_and_mismatched_exponential_evidence():
    result, _ = analyse_rows(_analysis_rows()[:-1], _stage3c_analysis())
    assert result["classification"] == "INCONCLUSIVE"
    wrong = _stage3c_analysis()
    wrong["delta_time_C_minus_B0"][0] = 1
    result, _ = analyse_rows(_analysis_rows(), wrong)
    assert result["classification"] == "INCONCLUSIVE"


def test_stage3c_reuse_verification_is_read_only(tmp_path, monkeypatch):
    stage3c = tmp_path / "results" / "stage3c_confirmatory_recovery"
    stage3c.mkdir(parents=True)
    (stage3c / "confirmatory_analysis.json").write_text(json.dumps({"decision": "FAIL", "valid": True}))
    (stage3c / "prerun_engineering_audit.json").write_text(json.dumps({"execution_identity": stable_identity("stage3c")}))
    (stage3c / "sentinel.bin").write_bytes(b"unchanged")
    before = {p.name: p.read_bytes() for p in stage3c.iterdir()}
    monkeypatch.setattr(
        "scalar_baseline.stage3d.validate_stage3c_run_directory",
        lambda *args, **kwargs: {
            "resources": {"cpu_seconds": 0.025},
        },
    )
    monkeypatch.setattr(
        "scalar_baseline.stage3d.verify_stage3c_protection",
        lambda *args, **kwargs: {"pass": True},
    )
    receipt = validate_stage3c_reuse(tmp_path)
    after = {p.name: p.read_bytes() for p in stage3c.iterdir()}
    assert receipt["pass"] and receipt["runs_verified"] == 40
    assert before == after


def test_dry_run_executes_no_formal_seed_and_validates_40_configs(tmp_path):
    result = dry_run(tmp_path)
    assert result["pass"]
    assert result["configurations_validated"] == 40
    assert result["formal_simulation_steps_executed"] == 0
    assert result["simulation_initialised_for_formal_seed"] is False
    assert not (tmp_path / "results" / "stage3d_decay_law_ablation").exists()
