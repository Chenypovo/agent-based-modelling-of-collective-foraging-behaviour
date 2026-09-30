"""Stage 4 search ledger, reproducible proposers, isolation and checked cache."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
from statistics import median
import subprocess
import sys
import tempfile
import time
from typing import Callable

import numpy as np

from .config import B0Config, DecayConfig
from .stage3c import _formal_simulation_config
from .stage3b import PairedB0Simulation, RecoverySimulation
from .stage4_llm import Provider, propose
from .stage4_objective import Endpoint, amended_endpoint, candidate_result
from .stage4_space import BASELINE, Candidate

DEVELOPMENT_SEEDS = tuple(range(2026100101, 2026100106))
HELDOUT_SEEDS = tuple(range(2026100201, 2026100211))
CAMPAIGN_SEEDS = tuple(range(2026101001, 2026101006))
METHODS = ("random", "tpe", "llm")
OPPORTUNITIES = 12
FORMAL_ROOT = Path("results/stage4_search_benchmark")
IDENTITY_FILES = (
    "requirements.txt", "docs/STAGE4_OBJECTIVE_AMENDMENT.md",
    "docs/STAGE4_SEARCH_BENCHMARK_PREREGISTRATION.md", "docs/STAGE4_ENGINEERING_SPEC.md",
    "src/ant_walks/models.py", "src/scalar_baseline/config.py",
    "src/scalar_baseline/environment.py", "src/scalar_baseline/field.py",
    "src/scalar_baseline/functional_validation.py", "src/scalar_baseline/navigation.py",
    "src/scalar_baseline/sensing.py", "src/scalar_baseline/simulation.py",
    "src/scalar_baseline/stage3b.py", "src/scalar_baseline/stage3c.py",
    "src/scalar_baseline/stage4_objective.py", "src/scalar_baseline/stage4_space.py",
    "src/scalar_baseline/stage4_search.py", "src/scalar_baseline/stage4_llm.py",
    "scripts/run_stage4.py", "run_stage4.sh",
)


class EvidenceError(RuntimeError):
    pass


def canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data: object) -> str:
    return hashlib.sha256(canonical(data)).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
    os.replace(temp, path)


def source_identity(root: Path, *, require_clean: bool = True) -> dict:
    try:
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "-uno"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError("Git identity unavailable") from exc
    if require_clean and status:
        raise EvidenceError("formal source identity requires a clean tracked worktree")
    try:
        optuna_version = version("optuna")
    except PackageNotFoundError:
        optuna_version = None
    if require_clean and optuna_version != "4.4.0":
        raise EvidenceError("formal execution requires Optuna 4.4.0")
    files = {}
    for name in IDENTITY_FILES:
        path = root / name
        if not path.is_file():
            raise EvidenceError(f"source identity file missing: {name}")
        files[name] = {"bytes": path.stat().st_size, "sha256": file_hash(path)}
    return {"schema": "stage4-source-v1", "head": head, "tracked_status": status,
            "python": platform.python_version(), "numpy": np.__version__,
            "optuna": optuna_version, "files": files}


def recursive_manifest(directory: Path) -> dict:
    return {str(p.relative_to(directory)): {"bytes": p.stat().st_size, "sha256": file_hash(p)}
            for p in sorted(directory.rglob("*")) if p.is_file() and p.relative_to(directory) != Path("completed_receipt.json")}


def validate_receipt(directory: Path, expected: dict | None = None) -> dict:
    path = directory / "completed_receipt.json"
    if not path.is_file():
        raise EvidenceError("completed receipt missing")
    receipt = json.loads(path.read_text())
    if receipt.get("status") != "complete" or receipt.get("files") != recursive_manifest(directory):
        raise EvidenceError("receipt file coverage, byte count or hash mismatch")
    if expected is not None:
        for key, value in expected.items():
            if receipt.get(key) != value:
                raise EvidenceError(f"receipt {key} identity mismatch")
    return receipt


def seal(directory: Path, metadata: dict) -> dict:
    receipt = {"status": "complete", **metadata, "files": recursive_manifest(directory)}
    write_json(directory / "completed_receipt.json", receipt)
    return validate_receipt(directory, metadata)


def protected_snapshot(root: Path) -> dict:
    protected = [root / p for p in (
        "results/stage1", "results/stage2_diagnostic", "results/stage2_provisional",
        "results/stage2b_local_geometry", "results/stage2c_multiseed_confirmation",
        "results/stage3a_functional_validation", "results/stage3a_scalar_baseline",
        "results/stage3b_recovery_pilot", "results/stage3c_confirmatory_recovery",
        "results/stage3d_decay_law_ablation", ".tmp_progress_report", "from_prof",
        "output", "reports", "Project Proposal.pdf", "_PH6780 Templates.docx",
        "_AY2627_T1_Briefing_updated.pdf")]
    files = {}
    for item in protected:
        if item.is_file():
            files[str(item.relative_to(root))] = {"bytes": item.stat().st_size, "sha256": file_hash(item)}
        elif item.is_dir():
            for p in sorted(item.rglob("*")):
                if p.is_file():
                    files[str(p.relative_to(root))] = {"bytes": p.stat().st_size, "sha256": file_hash(p)}
    return {"schema": "stage4-protection-v1", "files": files, "sha256": digest(files)}


def random_candidate(seed: int, index: int) -> Candidate:
    rng = random.Random(f"stage4-random:{seed}:{index}")
    return Candidate.parse({
        "half_life_steps": math.exp(rng.uniform(math.log(250), math.log(4000))),
        "signal_off": rng.uniform(.10, .40), "loss_steps": rng.randint(1, 6),
        "recovery_duration": rng.choice((0, 12, 24, 36, 48)),
    })


def tpe_candidate(seed: int, history: list[dict]) -> Candidate:
    try:
        import optuna
    except ImportError as exc:
        raise EvidenceError("Optuna is required for TPE; install frozen dependencies") from exc
    optuna.logging.disable_default_handler()
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=seed + len(history)))
    distributions = {
        "half_life_steps": optuna.distributions.FloatDistribution(250, 4000, log=True),
        "signal_off": optuna.distributions.FloatDistribution(.10, .40),
        "loss_steps": optuna.distributions.IntDistribution(1, 6),
        "recovery_duration": optuna.distributions.CategoricalDistribution([0, 12, 24, 36, 48]),
    }
    for row in history:
        if row.get("status") != "complete":
            continue
        values = row["candidate"]
        params = {"half_life_steps": float(values["half_life_steps"]),
                  "signal_off": float(values["signal_off"]),
                  "loss_steps": values["loss_steps"],
                  "recovery_duration": values["recovery_duration"]}
        study.add_trial(optuna.trial.create_trial(params=params, distributions=distributions,
                                                 value=float(row["result"]["score"])))
    trial = study.ask()
    return Candidate.parse({
        "half_life_steps": trial.suggest_float("half_life_steps", 250, 4000, log=True),
        "signal_off": trial.suggest_float("signal_off", .10, .40),
        "loss_steps": trial.suggest_int("loss_steps", 1, 6),
        "recovery_duration": trial.suggest_categorical("recovery_duration", [0, 12, 24, 36, 48]),
    })


def simulation_config(candidate: Candidate, seed: int):
    base = _formal_simulation_config(seed)
    navigation = replace(base.navigation, signal_off=float(candidate.signal_off),
                         loss_steps=candidate.loss_steps)
    return replace(base, navigation=navigation,
                   decay=DecayConfig(half_life_steps=float(candidate.half_life_steps)))


class Stage4RecoverySimulation(RecoverySimulation):
    def __init__(self, config, duration: int):
        self.recovery_duration = duration
        super().__init__(config)


def simulate(candidate_record: dict, seed: int) -> dict:
    """Only the runner calls this for an authorised formal evaluation."""
    candidate = Candidate.parse(candidate_record)
    config = simulation_config(candidate, seed)
    sim = (PairedB0Simulation(config) if candidate.recovery_duration == 0 else
           Stage4RecoverySimulation(config, candidate.recovery_duration))
    wall, cpu = time.perf_counter(), time.process_time()
    sim.run()
    sim.validate()
    events = list(sim.ledger.events)
    endpoint = amended_endpoint(events)
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"endpoint": asdict(endpoint), "events": events,
            "resources": {"wall_seconds": time.perf_counter() - wall,
                          "cpu_seconds": time.process_time() - cpu,
                          "peak_rss_bytes": int(raw if sys.platform == "darwin" else raw * 1024)}}


class EvaluationCache:
    def __init__(self, root: Path, source_sha256: str,
                 evaluator: Callable[[dict, int], dict] = simulate):
        self.root, self.source_sha256, self.evaluator = root, source_sha256, evaluator

    def key(self, candidate: Candidate, seed: int) -> str:
        return digest({"schema": "stage4-cache-v1", "candidate": candidate.record(),
                       "seed": seed, "source_identity_sha256": self.source_sha256,
                       "simulation_config": asdict(simulation_config(candidate, seed))})

    def evaluate(self, candidate: Candidate, seed: int) -> dict:
        key = self.key(candidate, seed)
        directory = self.root / key
        expected = {"cache_key": key, "candidate_sha256": candidate.digest(),
                    "seed": seed, "source_identity_sha256": self.source_sha256}
        if directory.exists():
            validate_receipt(directory, expected)
            record = json.loads((directory / "evaluation.json").read_text())
            if record["candidate"] != candidate.record() or record["seed"] != seed:
                raise EvidenceError("cached evaluation identity mismatch")
            return record
        self.root.mkdir(parents=True, exist_ok=True)
        if list(self.root.glob(f".{key}.tmp-*")):
            raise EvidenceError("incomplete cached evaluation requires review")
        temporary = Path(tempfile.mkdtemp(prefix=f".{key}.tmp-", dir=self.root))
        try:
            payload = self.evaluator(candidate.record(), seed)
            record = {"candidate": candidate.record(), "seed": seed, **payload}
            write_json(temporary / "evaluation.json", record)
            seal(temporary, expected)
            os.replace(temporary, directory)
            return record
        except BaseException:
            # Preserve incomplete evidence for inspection; never silently reuse it.
            raise


def evaluate_seeds(cache: EvaluationCache, candidate: Candidate, seeds: tuple[int, ...],
                   baseline_pre_total: int | None = None,
                   baseline_median: float | None = None,
                   workers: int = 1) -> dict:
    if workers not in (1, 2):
        raise ValueError("at most two simulation workers")
    if workers == 1:
        records = [cache.evaluate(candidate, seed) for seed in seeds]
    else:
        # Each seed has a distinct content address. Never dispatch the same key twice.
        with ProcessPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(cache.evaluate, (candidate,) * len(seeds), seeds))
    endpoints = [Endpoint(**record["endpoint"]) for record in records]
    if baseline_pre_total is None:
        return {"seed_tau": [e.tau_rec for e in endpoints],
                "median_tau": float(median(e.tau_rec for e in endpoints)),
                "pre_deliveries": sum(e.pre_deliveries for e in endpoints)}
    return asdict(candidate_result(endpoints, baseline_pre_total, baseline_median))


def _load_or_create_campaign(path: Path, method: str, seed: int, identity_sha256: str,
                             baseline: dict, development_seeds: tuple[int, ...],
                             heldout_seeds: tuple[int, ...]) -> dict:
    fixed = {"method": method, "seed": seed, "identity_sha256": identity_sha256,
             "baseline_sha256": digest(baseline),
             "development_seeds": list(development_seeds), "heldout_seeds": list(heldout_seeds)}
    if path.exists():
        value = json.loads(path.read_text())
        if any(value.get(key) != val for key, val in fixed.items()):
            raise EvidenceError("campaign resume identity mismatch")
        return value
    value = {"schema": "stage4-campaign-v1", **fixed, "opportunities": [], "winner": None}
    write_json(path, value)
    return value


def run_campaign(path: Path, method: str, seed: int, cache: EvaluationCache,
                 baseline: dict, *, provider: Provider | None = None,
                 development_seeds: tuple[int, ...] = DEVELOPMENT_SEEDS,
                 heldout_seeds: tuple[int, ...] = HELDOUT_SEEDS,
                 budget: int = OPPORTUNITIES, workers: int = 1) -> dict:
    if method not in METHODS or seed not in CAMPAIGN_SEEDS or budget < 1 or budget > OPPORTUNITIES:
        raise ValueError("campaign identity or budget invalid")
    state = _load_or_create_campaign(path, method, seed, cache.source_sha256,
                                     baseline, development_seeds, heldout_seeds)
    if baseline["pre_deliveries"] == 0:
        raise EvidenceError("INCONCLUSIVE_BASELINE")
    if len(state["opportunities"]) > budget:
        raise EvidenceError("ledger exceeds budget")
    def finish_pending(row: dict) -> None:
        candidate = Candidate.parse(row["candidate"]) if row["candidate"] else None
        if candidate is None:
            row["status"] = "invalid"
        else:
            row["result"] = evaluate_seeds(cache, candidate, development_seeds,
                                          baseline["pre_deliveries"], baseline["median_tau"], workers)
            row["status"] = "complete"
        write_json(path, state)

    for row in state["opportunities"]:
        if row["status"] == "pending":
            finish_pending(row)
    for index in range(len(state["opportunities"]), budget):
        history = [dict(item) for item in state["opportunities"]]
        candidate = None
        proposal = None
        if method == "random":
            candidate = random_candidate(seed, index)
        elif method == "tpe":
            candidate = tpe_candidate(seed, history)
        else:
            if provider is None:
                raise EvidenceError("LLM provider missing")
            visible_history = [{"index": item["index"], "status": item["status"],
                                "candidate": item["candidate"], "result": item.get("result"),
                                "hypothesis": (item.get("proposal") or {}).get("text", {}).get("hypothesis")}
                               for item in history]
            proposal = propose(provider, visible_history)
            candidate = proposal.get("candidate")
        row = {"index": index, "status": "pending", "candidate": candidate.record() if candidate else None,
               "candidate_sha256": candidate.digest() if candidate else None,
               "proposal": {k: v for k, v in proposal.items() if k != "candidate"} if proposal else None}
        state["opportunities"].append(row)
        write_json(path, state)
        finish_pending(row)
    if budget != OPPORTUNITIES:
        return state  # no winner or held-out access before the full budget
    if state["winner"] is None:
        valid = [x for x in state["opportunities"] if x["status"] == "complete"]
        if valid:
            winner = min(valid, key=lambda x: (x["result"]["score"], x["index"]))
            state["winner"] = {"index": winner["index"], "candidate": winner["candidate"],
                               "candidate_sha256": winner["candidate_sha256"]}
        else:
            state["winner"] = {"index": None, "candidate": None}
        write_json(path, state)  # winner frozen before held-out data are read
    if state["winner"]["candidate"] is not None and "heldout" not in state:
        heldout_baseline = evaluate_seeds(cache, BASELINE, heldout_seeds, workers=workers)
        if heldout_baseline["pre_deliveries"] == 0:
            state["heldout"] = {"status": "INCONCLUSIVE_BASELINE"}
        else:
            state["heldout"] = evaluate_seeds(
                cache, Candidate.parse(state["winner"]["candidate"]), heldout_seeds,
                heldout_baseline["pre_deliveries"], heldout_baseline["median_tau"], workers)
        write_json(path, state)
    if "heldout" in state or state["winner"]["candidate"] is None:
        receipt_path = path.parent / "completed_receipt.json"
        metadata = {"method": method, "seed": seed, "identity_sha256": cache.source_sha256,
                    "opportunities": OPPORTUNITIES}
        if receipt_path.exists():
            validate_receipt(path.parent, metadata)
        else:
            seal(path.parent, metadata)
    return json.loads(path.read_text())


def run_benchmark(repository_root: Path, provider: Provider | None,
                  authorisation: dict, *, workers: int = 2) -> dict:
    """Stage 4B entry point, inert until all master and resource gates are met."""
    required = ("api_provider", "model_name_version", "api_key_env", "temperature",
                "model_seed_support", "campaign_token_cap", "total_cost_cap")
    if (authorisation.get("stage") != "4B" or authorisation.get("approved") is not True
            or authorisation.get("resource_adjustment_approved") is not True
            or any(authorisation.get(key) is None for key in required)):
        raise EvidenceError("Stage 4B master, API, or resource approval is incomplete")
    if provider is None:
        raise EvidenceError("Stage 4B provider adapter is not configured")
    if workers not in (1, 2):
        raise ValueError("at most two local simulation workers")
    before = source_identity(repository_root)
    source_sha = digest(before)
    protected_before = protected_snapshot(repository_root)
    root = repository_root / FORMAL_ROOT
    pre_path = root / "prerun_identity.json"
    if pre_path.exists():
        pre = json.loads(pre_path.read_text())
        if pre != {"source": before, "protected": protected_before}:
            raise EvidenceError("resume source or protected evidence differs")
    else:
        if root.exists() and any(root.iterdir()):
            raise EvidenceError("formal results root exists without pre-run identity")
        write_json(pre_path, {"source": before, "protected": protected_before})
    cache = EvaluationCache(root / "cache", source_sha)
    baseline = evaluate_seeds(cache, BASELINE, DEVELOPMENT_SEEDS, workers=workers)
    if baseline["pre_deliveries"] == 0:
        write_json(root / "benchmark_status.json", {"status": "INCONCLUSIVE_BASELINE"})
        return {"status": "INCONCLUSIVE_BASELINE"}
    write_json(root / "development_baseline.json", baseline)
    campaigns = []
    for method in METHODS:
        for seed in CAMPAIGN_SEEDS:
            path = root / "campaigns" / method / str(seed) / "ledger.json"
            campaigns.append(run_campaign(path, method, seed, cache, baseline,
                                          provider=provider if method == "llm" else None,
                                          workers=workers))
            if source_identity(repository_root) != before:
                raise EvidenceError("formal source identity changed during campaign")
            if protected_snapshot(repository_root) != protected_before:
                raise EvidenceError("protected evidence changed during campaign")
    if source_identity(repository_root) != before:
        raise EvidenceError("post-run source identity mismatch")
    protected_after = protected_snapshot(repository_root)
    if protected_after != protected_before:
        raise EvidenceError("post-run protected evidence mismatch")
    write_json(root / "postrun_identity.json", {"source": before, "protected": protected_after})
    write_json(root / "benchmark_status.json", {"status": "complete", "campaigns": 15,
                                                  "opportunities": 180})
    seal(root, {"stage": "4B", "source_identity_sha256": source_sha,
                "campaigns": 15, "opportunities": 180})
    return {"status": "complete", "campaigns": campaigns}
