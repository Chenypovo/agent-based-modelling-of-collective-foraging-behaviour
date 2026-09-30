from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import importlib.util
import inspect
import io
import json
import math
from pathlib import Path
import subprocess
from contextlib import redirect_stdout

import numpy as np
import pytest

from scalar_baseline.stage3b import RECOVERY_DURATION, old_trail_mask, state_digest
import scalar_baseline.stage3c as stage3c
from scalar_baseline.stage3c import (
    ARMS,
    CAPPED_RECOVERY_TIME,
    CONFIRMATORY_SEEDS,
    EXECUTION_IDENTITY_FILES,
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
    expected_expansion_authorisation,
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
    validate_expansion_authorisation,
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
STABLE_EXECUTION_IDENTITY = stage3c._source_identity(ROOT)
STABLE_EXECUTION_IDENTITY["git"]["tracked_clean"] = True
STABLE_EXECUTION_IDENTITY["git"]["tracked_status"] = []


def stable_identity(_repository_root: Path) -> dict:
    return deepcopy(STABLE_EXECUTION_IDENTITY)


def write_synthetic_prerun(root: Path, identity: dict | None = None) -> Path:
    path = root / "prerun_engineering_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pass": True,
                "execution_identity": identity or stable_identity(ROOT),
                "scope": {
                    "formal_simulation_steps_executed": 0,
                    "confirmatory_seeds_run": 0,
                },
            }
        )
        + "\n"
    )
    return path


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


def _recursive_file_snapshot(path: Path) -> list[tuple[str, int, str]] | None:
    """Return byte-sensitive state, while preserving absence as a distinct state."""
    if not path.exists():
        return None
    return [
        (item.relative_to(path).as_posix(), item.stat().st_size, _hash(item))
        for item in sorted(path.rglob("*"))
        if item.is_file()
    ]


def write_synthetic_completed_run(
    root: Path,
    config,
    *,
    b0_time=10_000,
    c_time=7_000,
    execution_identity: dict | None = None,
):
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
    identity = execution_identity or stable_identity(ROOT)
    identity_record = stage3c._arm_identity_record(identity, identity, identity)
    data = {
        "config.json": config.as_record(),
        "summary.json": summary,
        "timeseries_100step.json": [],
        "ledger_events.json": [],
        "source_identity.json": identity_record,
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
    assert final.is_dir() and result["engineering_status"] == "PASS"
    assert "summary" not in result and "validation" not in result
    assert validate_run_directory(final, config)["pass"]
    assert (final / "recovery_episodes.json").is_file()
    assert not list(final.parent.glob("*.tmp-*"))


def test_completed_run_reuse_and_overwrite_refusal(tmp_path):
    config = fixture_config(seed=31108, steps=6, n_ants=1, relocation_step=3)
    run_arm_atomic(tmp_path, config, ROOT)
    assert run_arm_atomic(tmp_path, config, ROOT)["complete"] is True
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
    write_synthetic_prerun(tmp_path)
    for arm in ARMS:
        write_synthetic_completed_run(tmp_path, confirmatory_config(seed, arm))
    receipt = create_first_pair_engineering_receipt(
        tmp_path, ROOT, identity_provider=stable_identity
    )
    assert "scientific_outcomes_inspected" not in receipt
    assert receipt["prerun_audit_sha256"] == _hash(
        tmp_path / "prerun_engineering_audit.json"
    )
    for arm in ARMS:
        assert receipt["arms"][arm]["completed_receipt_sha256"] == _hash(
            tmp_path / "runs" / str(seed) / arm / "completed_receipt.json"
        )
    assert validate_first_pair_engineering_receipt(
        tmp_path, ROOT, identity_provider=stable_identity
    )["pass"]


def test_execution_identity_covers_git_runtime_platform_and_20_files():
    identity = stage3c._source_identity(ROOT)
    assert identity["schema"] == "stage3c-execution-identity-v1"
    assert identity["git"]["head"] and identity["git"]["branch"]
    assert set(identity["runtime"]) == {
        "python_version",
        "python_implementation",
        "numpy_version",
        "platform",
    }
    assert tuple(identity["files"]) == EXECUTION_IDENTITY_FILES
    assert len(identity["files"]) == 20
    assert all(record["bytes"] >= 0 and len(record["sha256"]) == 64
               for record in identity["files"].values())


def _git(repo: Path, *args: str) -> None:
    subprocess.run(("git", "-C", str(repo), *args), check=True, capture_output=True)


def test_git_identity_ignores_untracked_and_ignored_but_rejects_tracked_change(tmp_path):
    repo = tmp_path / "identity-repo"
    repo.mkdir()
    for relative in EXECUTION_IDENTITY_FILES:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture:{relative}\n")
    (repo / ".gitignore").write_text("ignored/\n")
    _git(repo, "init", "-b", "identity-test")
    _git(repo, "config", "user.name", "Stage3C Test")
    _git(repo, "config", "user.email", "stage3c@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "identity fixture")

    frozen = stage3c._source_identity(repo)
    assert frozen["git"]["tracked_clean"] is True
    for relative in (
        ".tmp_progress_report/item.txt",
        "from_prof/item.txt",
        "output/item.txt",
        "reports/item.txt",
        "results/stage2c_multiseed_confirmation/item.txt",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("untracked\n")
    (repo / "ignored/item.txt").parent.mkdir(parents=True, exist_ok=True)
    (repo / "ignored/item.txt").write_text("ignored\n")
    assert stage3c._source_identity(repo) == frozen

    (repo / "requirements.txt").write_text("tracked mutation\n")
    dirty = stage3c._source_identity(repo)
    assert dirty["git"]["tracked_clean"] is False
    with pytest.raises(EvidenceError, match="clean tracked"):
        initialise_prerun_engineering_audit(tmp_path / "study", repo)

    audit_root = tmp_path / "frozen-audit"
    write_synthetic_prerun(audit_root, frozen)
    _git(repo, "add", "requirements.txt")
    _git(repo, "commit", "-m", "change execution identity")
    assert stage3c._source_identity(repo)["git"]["head"] != frozen["git"]["head"]
    with pytest.raises(EvidenceError, match="source changed"):
        stage3c.validate_prerun_engineering_audit(audit_root, repo)


def test_arm_publication_fails_if_identity_changes_during_execution(tmp_path):
    identities = [stable_identity(ROOT), stable_identity(ROOT)]
    identities[1]["git"]["head"] = "f" * 40

    def changing_identity(_repository_root):
        return deepcopy(identities.pop(0))

    config = fixture_config(seed=31111, steps=5, n_ants=1, relocation_step=2)
    with pytest.raises(EvidenceError, match="changed during"):
        run_arm_atomic(
            tmp_path, config, ROOT, identity_provider=changing_identity
        )
    assert not (tmp_path / "runs" / str(config.seed) / config.arm).exists()


def test_first_pair_rejects_B0_C_execution_identity_mismatch(tmp_path):
    seed = CONFIRMATORY_SEEDS[0]
    write_synthetic_prerun(tmp_path)
    write_synthetic_completed_run(tmp_path, confirmatory_config(seed, "B0"))
    changed = stable_identity(ROOT)
    changed["runtime"]["numpy_version"] = "identity-mismatch-fixture"
    write_synthetic_completed_run(
        tmp_path,
        confirmatory_config(seed, "C"),
        execution_identity=changed,
    )
    with pytest.raises(EvidenceError, match="execution identity"):
        create_first_pair_engineering_receipt(
            tmp_path, ROOT, identity_provider=stable_identity
        )


def _load_runner():
    script = ROOT / "scripts/run_stage3c.py"
    spec = importlib.util.spec_from_file_location("stage3c_runner_e1_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _assert_outcome_blind(value) -> None:
    encoded = json.dumps(value, sort_keys=True).lower()
    forbidden = (
        "summary",
        "discover",
        "deliver",
        "capped",
        "non_delivery",
        "pre_relocation",
        "old_food",
        "obsolete_trail",
        "recovery_",
        "role",
        "pickup",
        "scientific_outcomes_inspected",
    )
    assert not [term for term in forbidden if term in encoded]


def test_actual_first_pair_return_receipt_and_cli_stdout_are_outcome_blind(
    tmp_path, monkeypatch
):
    module = _load_runner()
    seed = 31112
    configs = {
        arm: fixture_config(
            seed=seed, arm=arm, steps=6, n_ants=1, relocation_step=3,
            fixture_label="first-pair-output-blinding-fixture",
        )
        for arm in ARMS
    }
    result = module.first_pair(
        tmp_path, pair_configs=configs, identity_provider=stable_identity
    )
    receipt = json.loads((tmp_path / "first_pair_engineering_receipt.json").read_text())
    _assert_outcome_blind(result)
    _assert_outcome_blind(receipt)
    for arm in ARMS:
        run_dir = tmp_path / "runs" / str(seed) / arm
        assert (run_dir / "summary.json").is_file()
        completed = json.loads((run_dir / "completed_receipt.json").read_text())
        assert "summary.json" in completed["recursive_files_excluding_this_receipt"]

    monkeypatch.setattr(module, "first_pair", lambda _study_root: result)
    output = io.StringIO()
    with redirect_stdout(output):
        assert module.main(["first-pair", "--study-root", str(tmp_path / "cli")]) == 0
    cli_json = json.loads(output.getvalue())
    assert cli_json == result
    _assert_outcome_blind(cli_json)


def _prepare_synthetic_first_pair(root: Path) -> None:
    seed = CONFIRMATORY_SEEDS[0]
    initialise_study_protection(root, ROOT)
    write_synthetic_prerun(root)
    for arm in ARMS:
        write_synthetic_completed_run(root, confirmatory_config(seed, arm))
    create_first_pair_engineering_receipt(
        root, ROOT, identity_provider=stable_identity
    )


def test_expansion_authorisation_fails_closed_and_exact_gate_passes(
    tmp_path, monkeypatch
):
    _prepare_synthetic_first_pair(tmp_path)
    path = tmp_path / stage3c.EXPANSION_AUTHORISATION_FILENAME
    with pytest.raises(EvidenceError, match="requires Stage 3C-F"):
        validate_expansion_authorisation(
            tmp_path, ROOT, identity_provider=stable_identity
        )
    path.write_text("{not-json\n")
    with pytest.raises(EvidenceError, match="corrupt"):
        validate_expansion_authorisation(
            tmp_path, ROOT, identity_provider=stable_identity
        )

    expected = expected_expansion_authorisation(
        tmp_path, ROOT, identity_provider=stable_identity
    )
    mutations = (
        ("first_pair_engineering_receipt_sha256", "0" * 64),
        ("first_pair_B0_completed_receipt_sha256", "1" * 64),
        ("frozen_execution_git_head", "2" * 40),
        ("frozen_prerun_audit_sha256", "3" * 64),
        ("seeds", [2026092102]),
        ("arm_order", ["C", "B0"]),
    )
    for field, value in mutations:
        candidate = deepcopy(expected)
        candidate[field] = value
        path.write_text(json.dumps(candidate) + "\n")
        with pytest.raises(EvidenceError, match="does not match"):
            validate_expansion_authorisation(
                tmp_path, ROOT, identity_provider=stable_identity
            )

    changed_identity = stable_identity(ROOT)
    changed_identity["git"]["head"] = "4" * 40
    path.write_text(json.dumps(expected) + "\n")
    with pytest.raises(EvidenceError, match="source changed"):
        validate_expansion_authorisation(
            tmp_path, ROOT, identity_provider=lambda _root: deepcopy(changed_identity)
        )

    monkeypatch.setattr(
        Stage3CB0Simulation,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("authorisation validation started a simulation")
        ),
    )
    gate = validate_expansion_authorisation(
        tmp_path, ROOT, identity_provider=stable_identity
    )
    assert gate["engineering_status"] == "PASS"
    assert gate["seeds"] == list(CONFIRMATORY_SEEDS[1:])


def test_remaining_refuses_before_simulation_without_authorisation(tmp_path, monkeypatch):
    module = _load_runner()
    calls = []
    monkeypatch.setattr(module, "run_arm_atomic", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(EvidenceError, match="Stage 3C-F"):
        module.remaining(tmp_path)
    assert calls == []


def test_analyse_gate_refuses_incomplete_study(tmp_path):
    with pytest.raises(EvidenceError):
        validate_complete_study(tmp_path)
    with pytest.raises(EvidenceError):
        rows_from_study(tmp_path)


def test_analyse_gate_accepts_40_synthetic_completed_records(tmp_path, monkeypatch):
    initialise_study_protection(tmp_path, ROOT)
    write_synthetic_prerun(tmp_path)
    for seed in CONFIRMATORY_SEEDS:
        for arm in ARMS:
            write_synthetic_completed_run(tmp_path, confirmatory_config(seed, arm))
    assert validate_complete_study(
        tmp_path, ROOT, identity_provider=stable_identity
    )["runs_verified"] == 40
    import scalar_baseline.stage3c_analysis as analysis_module

    original_gate = analysis_module.validate_complete_study
    monkeypatch.setattr(
        analysis_module,
        "validate_complete_study",
        lambda study_root: original_gate(
            study_root, ROOT, identity_provider=stable_identity
        ),
    )
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
    formal_results = ROOT / "results/stage3c_confirmatory_recovery"
    before = _recursive_file_snapshot(formal_results)
    result = module.dry_run()
    assert result["simulation_initialised"] is False
    assert result["simulation_steps_executed"] == 0
    assert result["confirmatory_seeds_run"] == 0
    assert _recursive_file_snapshot(formal_results) == before


def test_formal_results_snapshot_distinguishes_absent_and_existing_states(tmp_path):
    formal_results = tmp_path / "results/stage3c_confirmatory_recovery"
    assert _recursive_file_snapshot(formal_results) is None

    artifact = formal_results / "runs/fixture/completed_receipt.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"immutable formal evidence\n")
    before = _recursive_file_snapshot(formal_results)
    assert before == [
        (
            "runs/fixture/completed_receipt.json",
            len(b"immutable formal evidence\n"),
            hashlib.sha256(b"immutable formal evidence\n").hexdigest(),
        )
    ]
    assert _recursive_file_snapshot(formal_results) == before
