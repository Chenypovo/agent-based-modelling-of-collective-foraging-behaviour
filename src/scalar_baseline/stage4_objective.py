"""Frozen discrete Stage 4 sustained retrieval endpoint and candidate score."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Mapping

RELOCATION = 6000
POST_HORIZON = 12000
WINDOW = 600
PRE_START = 4800
PRE_END = 6000
STATIC_MINIMUM = 0.80


@dataclass(frozen=True)
class Endpoint:
    tau_rec: int
    non_recovery: bool
    pre_deliveries: int


def amended_endpoint(
    events: Iterable[Mapping], *, relocation: int = RELOCATION,
    post_horizon: int = POST_HORIZON, window: int = WINDOW,
) -> Endpoint:
    """Count delivery impulses using [pre_start, relocation) and (s-w,s]."""
    if relocation <= 0 or post_horizon < 2 * window or window <= 0:
        raise ValueError("invalid objective time constants")
    pre_start = relocation - relocation // 5
    deliveries = [e for e in events if e.get("event") == "delivery"]
    pre = sum(e.get("source") == "A" and pre_start <= e["time"] < relocation for e in deliveries)
    if pre == 0:
        return Endpoint(post_horizon, True, 0)
    end = relocation + post_horizon
    counts = [0] * (end + 1)
    for e in deliveries:
        if e.get("source") == "B" and relocation <= e["time"] <= end:
            counts[e["time"]] += 1
    prefix = [0] * (end + 2)
    for step, count in enumerate(counts):
        prefix[step + 1] = prefix[step] + count
    failed = [0] * (end + 2)
    for s in range(relocation + window, end + 1):
        b_count = prefix[s + 1] - prefix[s - window + 1]
        # b_count / window >= .8 * pre / pre_window, without floating error.
        failed[s + 1] = failed[s] + (5 * b_count * (relocation - pre_start) < 4 * pre * window)
    for t in range(relocation + window, end - window + 1):
        if failed[t + window + 1] - failed[t] == 0:
            return Endpoint(t - relocation, False, pre)
    return Endpoint(post_horizon, True, pre)


@dataclass(frozen=True)
class CandidateResult:
    seed_tau: tuple[int, ...]
    median_tau: float
    pre_deliveries: int
    static_efficiency_ratio: float
    score: float
    biological_target: bool


def candidate_result(endpoints: Iterable[Endpoint], baseline_pre_total: int,
                     baseline_median: float) -> CandidateResult:
    endpoints = tuple(endpoints)
    if not endpoints or baseline_pre_total <= 0:
        raise ValueError("INCONCLUSIVE_BASELINE")
    tau = tuple(e.tau_rec for e in endpoints)
    med = float(median(tau))
    pre = sum(e.pre_deliveries for e in endpoints)
    ratio = pre / baseline_pre_total
    score = (med if ratio >= STATIC_MINIMUM else
             POST_HORIZON + med + POST_HORIZON * (STATIC_MINIMUM - ratio) / STATIC_MINIMUM)
    return CandidateResult(tau, med, pre, ratio, score,
                           med <= .8 * baseline_median and ratio >= STATIC_MINIMUM)
