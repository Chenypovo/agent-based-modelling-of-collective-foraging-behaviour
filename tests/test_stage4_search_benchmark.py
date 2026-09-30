"""Stage 4A1 engineering fixtures only; no formal simulation or API request."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from scalar_baseline.stage4_llm import MockProvider, parse_proposal, propose
from scalar_baseline.stage4_objective import Endpoint, amended_endpoint, candidate_result
from scalar_baseline.stage4_search import (
    CAMPAIGN_SEEDS, DEVELOPMENT_SEEDS, FORMAL_ROOT, HELDOUT_SEEDS,
    EvaluationCache, EvidenceError, evaluate_seeds, random_candidate, run_campaign,
    tpe_candidate, validate_receipt,
    run_benchmark,
)
from scalar_baseline.stage4_space import BASELINE, Candidate


def event(time: int, source: str = "B", kind: str = "delivery") -> dict:
    return {"time": time, "source": source, "event": kind, "ant_id": 0}


def test_zero_reference_is_non_recovery_even_with_post_delivery():
    result = amended_endpoint([event(6600), event(7200)])
    assert result == Endpoint(12000, True, 0)


def test_window_edges_and_persistence_are_inclusive():
    events = [event(4799, "A"), event(4800, "A"), event(5999, "A"),
              event(6000, "A"), event(6600), event(7200)]
    assert amended_endpoint(events) == Endpoint(600, False, 2)
    assert amended_endpoint(events[:-1]) == Endpoint(12000, True, 2)
    assert amended_endpoint([event(4800, "A"), event(6600, "B", "pickup")]).non_recovery


def test_positive_reference_keeps_original_condition():
    events = [event(5999, "A"), event(6600), event(7200)]
    assert amended_endpoint(events).tau_rec == 600
    assert amended_endpoint(events[:-1]).tau_rec == 12000


def test_target_static_aggregate_and_penalty():
    endpoints = [Endpoint(600, False, 3), Endpoint(12000, True, 5)]
    result = candidate_result(endpoints, baseline_pre_total=10, baseline_median=12000)
    assert result.median_tau == 6300 and result.static_efficiency_ratio == .8
    assert result.score == 6300 and result.biological_target
    penalty = candidate_result([Endpoint(600, False, 7)], 10, 12000)
    assert penalty.score == pytest.approx(14100)
    assert not penalty.biological_target
    with pytest.raises(ValueError, match="INCONCLUSIVE_BASELINE"):
        candidate_result(endpoints, 0, 12000)


@pytest.mark.parametrize("key,value", [
    ("half_life_steps", 249), ("half_life_steps", 4001),
    ("signal_off", .09), ("signal_off", .41),
    ("loss_steps", 0), ("loss_steps", 7),
    ("recovery_duration", 13), ("recovery_duration", 60),
])
def test_space_bounds_reject(key, value):
    values = BASELINE.record()
    values[key] = value
    with pytest.raises(ValueError):
        Candidate.parse(values)


def test_space_bounds_and_candidate_hash_are_canonical():
    low = Candidate.parse({"half_life_steps": 250, "signal_off": .10,
                           "loss_steps": 1, "recovery_duration": 0})
    high = Candidate.parse({"half_life_steps": 4000, "signal_off": .40,
                            "loss_steps": 6, "recovery_duration": 48})
    assert low.digest() != high.digest()
    assert Candidate.parse({"recovery_duration": 0, "loss_steps": 1,
                            "signal_off": "0.1", "half_life_steps": "250.000"}).digest() == low.digest()
    with pytest.raises(ValueError):
        Candidate.parse({**low.record(), "fifth": 1})


def proposal(values=None, **extra) -> str:
    return json.dumps({"hypothesis": "local persistence", **(values or BASELINE.record()),
                       "expected_outcome": "earlier recovery", "brief_justification": "bounded test",
                       **extra})


def test_llm_schema_mock_and_one_repair():
    candidate, text = parse_proposal(proposal())
    assert candidate == BASELINE and text["hypothesis"] == "local persistence"
    mock = MockProvider(["{", proposal()])
    result = propose(mock, [])
    assert result["valid"] and result["repaired"] and len(mock.prompts) == 2
    assert mock.prompts[1]["repair_only"]
    missing = json.loads(proposal())
    del missing["signal_off"]
    mock = MockProvider([json.dumps(missing), proposal()])
    assert propose(mock, [])["valid"]
    out = json.loads(proposal())
    out["signal_off"] = 0.9
    mock = MockProvider([json.dumps(out), proposal()])
    assert propose(mock, [])["valid"]


def test_llm_second_failure_fifth_parameter_and_hypothesis_change():
    assert not propose(MockProvider(["{", "{"]), [])["valid"]
    fifth = json.loads(proposal())
    fifth["food_coordinate"] = [1, 2]
    mock = MockProvider([json.dumps(fifth)])
    assert not propose(mock, [])["valid"] and len(mock.prompts) == 1
    missing = json.loads(proposal())
    del missing["signal_off"]
    changed = json.loads(proposal())
    changed["hypothesis"] = "different mechanism"
    assert not propose(MockProvider([json.dumps(missing), json.dumps(changed)]), [])["valid"]


def fake_evaluator(candidate: dict, seed: int) -> dict:
    return {"endpoint": asdict(Endpoint(600 + seed % 3, False, 1)),
            "events": [event(4800, "A")], "resources": {"wall_seconds": 0}}


def test_cache_receipt_hash_and_duplicate_reuse(tmp_path):
    calls = []
    def evaluate(candidate, seed):
        calls.append(seed)
        return fake_evaluator(candidate, seed)
    cache = EvaluationCache(tmp_path / "cache", "source-a", evaluate)
    first = cache.evaluate(BASELINE, 101)
    assert cache.evaluate(BASELINE, 101) == first and calls == [101]
    directory = cache.root / cache.key(BASELINE, 101)
    validate_receipt(directory)
    with (directory / "evaluation.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(EvidenceError):
        cache.evaluate(BASELINE, 101)
    assert EvaluationCache(cache.root, "source-b", evaluate).key(BASELINE, 101) != cache.key(BASELINE, 101)


def test_random_reproducible_and_resume_equals_continuous(tmp_path):
    assert random_candidate(CAMPAIGN_SEEDS[0], 3) == random_candidate(CAMPAIGN_SEEDS[0], 3)
    assert random_candidate(CAMPAIGN_SEEDS[0], 3) != random_candidate(CAMPAIGN_SEEDS[0], 4)
    baseline = {"pre_deliveries": 2, "median_tau": 12000}
    cache = EvaluationCache(tmp_path / "cache", "source-a", fake_evaluator)
    kwargs = {"development_seeds": (101, 102), "heldout_seeds": (201,)}
    partial = run_campaign(tmp_path / "a" / "ledger.json", "random", CAMPAIGN_SEEDS[0],
                           cache, baseline, budget=6, **kwargs)
    assert len(partial["opportunities"]) == 6 and partial["winner"] is None
    assert not (cache.root / cache.key(BASELINE, 201)).exists()
    resumed = run_campaign(tmp_path / "a" / "ledger.json", "random", CAMPAIGN_SEEDS[0],
                           cache, baseline, **kwargs)
    continuous = run_campaign(tmp_path / "b" / "ledger.json", "random", CAMPAIGN_SEEDS[0],
                              cache, baseline, **kwargs)
    assert resumed == continuous and len(resumed["opportunities"]) == 12
    assert len({x["index"] for x in resumed["opportunities"]}) == 12
    assert "heldout" in resumed
    validate_receipt(tmp_path / "a")


def test_tpe_reproducible_when_frozen_dependency_available():
    pytest.importorskip("optuna")
    assert tpe_candidate(CAMPAIGN_SEEDS[0], []) == tpe_candidate(CAMPAIGN_SEEDS[0], [])
    history = [{"status": "complete", "candidate": BASELINE.record(), "result": {"score": 12000}}]
    assert tpe_candidate(CAMPAIGN_SEEDS[0], history) == tpe_candidate(CAMPAIGN_SEEDS[0], history)


def test_tpe_campaign_resume_equals_continuous(tmp_path):
    pytest.importorskip("optuna")
    baseline = {"pre_deliveries": 2, "median_tau": 12000}
    cache = EvaluationCache(tmp_path / "cache", "source-a", fake_evaluator)
    kwargs = {"development_seeds": (101, 102), "heldout_seeds": (201,)}
    run_campaign(tmp_path / "a" / "ledger.json", "tpe", CAMPAIGN_SEEDS[0],
                 cache, baseline, budget=5, **kwargs)
    resumed = run_campaign(tmp_path / "a" / "ledger.json", "tpe", CAMPAIGN_SEEDS[0],
                           cache, baseline, **kwargs)
    continuous = run_campaign(tmp_path / "b" / "ledger.json", "tpe", CAMPAIGN_SEEDS[0],
                              cache, baseline, **kwargs)
    assert resumed == continuous


def test_llm_opportunities_cache_reuse_and_prompt_isolation(tmp_path):
    calls = []
    def evaluate(candidate, seed):
        calls.append(seed)
        return fake_evaluator(candidate, seed)
    cache = EvaluationCache(tmp_path / "cache", "source-a", evaluate)
    baseline = {"pre_deliveries": 2, "median_tau": 12000}
    provider = MockProvider([proposal()] * 12)
    state = run_campaign(tmp_path / "a" / "ledger.json", "llm", CAMPAIGN_SEEDS[0],
                         cache, baseline, provider=provider, development_seeds=(101, 102),
                         heldout_seeds=(201,))
    assert len(state["opportunities"]) == 12 and len(calls) == 3
    assert provider.prompts[0]["history"] == []
    assert len(provider.prompts[11]["history"]) == 11
    other = MockProvider([proposal()] * 12)
    run_campaign(tmp_path / "b" / "ledger.json", "llm", CAMPAIGN_SEEDS[1], cache,
                 baseline, provider=other, development_seeds=(101, 102), heldout_seeds=(201,))
    assert other.prompts[0]["history"] == [] and len(calls) == 3


def test_invalid_llm_proposals_consume_opportunities_and_resume_identity(tmp_path):
    cache = EvaluationCache(tmp_path / "cache", "source-a", fake_evaluator)
    baseline = {"pre_deliveries": 2, "median_tau": 12000}
    provider = MockProvider(["{", "{"])
    path = tmp_path / "campaign" / "ledger.json"
    state = run_campaign(path, "llm", CAMPAIGN_SEEDS[0], cache, baseline,
                         provider=provider, development_seeds=(101, 102),
                         heldout_seeds=(201,), budget=1)
    assert len(state["opportunities"]) == 1
    assert state["opportunities"][0]["status"] == "invalid"
    assert not cache.root.exists()
    with pytest.raises(EvidenceError, match="resume identity"):
        run_campaign(path, "llm", CAMPAIGN_SEEDS[0], cache,
                     {"pre_deliveries": 3, "median_tau": 12000},
                     provider=MockProvider([proposal()]),
                     development_seeds=(101, 102), heldout_seeds=(201,), budget=2)


def test_formal_runner_rejects_missing_stage4b_gate(tmp_path):
    with pytest.raises(EvidenceError, match="approval"):
        run_benchmark(tmp_path, None, {"stage": "4A1", "approved": True})


def test_formal_plan_identity_has_no_overlap_and_no_results():
    assert not (set(DEVELOPMENT_SEEDS) & set(HELDOUT_SEEDS))
    assert not (set(DEVELOPMENT_SEEDS) & set(range(2026092101, 2026092121)))
    assert len(DEVELOPMENT_SEEDS) == 5 and len(HELDOUT_SEEDS) == 10
    assert len(CAMPAIGN_SEEDS) * 3 * 12 == 180
    root = Path(__file__).resolve().parents[1]
    assert not (root / FORMAL_ROOT).exists()
