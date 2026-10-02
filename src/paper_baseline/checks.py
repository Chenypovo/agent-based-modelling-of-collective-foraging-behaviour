"""The five static checks (docs/PAPER_BASELINE_PLAN.md Sec. 2): per-run metrics and pass rules."""

from __future__ import annotations

import math

import numpy as np

DISCOVERY_MAX = 4000
RECRUIT_WINDOW, RECRUIT_MIN = (4000, 12000), 0.5
TRAIL_TIME, TRAIL_WIDTH, TRAIL_MIN = 10000, 5.0, 0.5
TRANSPORT_WINDOW, TRANSPORT_MIN, R2_MIN = (6000, 12000), 100, 0.95
ORDER_WINDOW = (10000, 12000)
PHI_TARGET, PHI_TOL = math.pi / 4, 0.1
FULL = {"psi": 0.9, "foragers": 10}
BASIC = {"psi": 0.8, "psi_gain": 0.1, "foragers": 25}
SEED_SHARE = 0.8


def first_pickup(pickup_times: list[int], horizon: int) -> int:
    return min(pickup_times) if pickup_times else horizon


def recruitment_share(pickup_roles: list[tuple[int, str]], window=RECRUIT_WINDOW) -> float:
    roles = [role for t, role in pickup_roles if window[0] <= t < window[1]]
    return sum(role == "follower" for role in roles) / len(roles) if roles else 0.0


def segment_distance(points: np.ndarray, a, b) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    s = np.clip(((points - a) @ ab) / (ab @ ab), 0.0, 1.0)
    return np.linalg.norm(points - (a + s[:, None] * ab), axis=1)


def trail_share(concentration: np.ndarray, cell_size: float, nest, food, width: float = TRAIL_WIDTH) -> float:
    total = float(concentration.sum())
    if total <= 0:
        return 0.0
    n = concentration.shape[0]
    centres = (np.arange(n) + 0.5) * cell_size
    gx, gy = np.meshgrid(centres, centres, indexing="ij")  # concentration[ix, iy]
    near = segment_distance(np.column_stack((gx.ravel(), gy.ravel())), nest, food) <= width
    return float(concentration.ravel()[near].sum() / total)


def transport(delivery_times: list[int], window=TRANSPORT_WINDOW) -> tuple[int, float]:
    """Deliveries in [start, end) and R^2 of a line fitted to cumulative deliveries per step."""
    times = np.sort(np.asarray(delivery_times, dtype=float))
    steps = np.arange(window[0], window[1], dtype=float)
    cumulative = np.searchsorted(times, steps, side="right").astype(float)
    count = int(((times >= window[0]) & (times < window[1])).sum())
    if cumulative.std() == 0:
        return count, 0.0
    r = np.corrcoef(steps, cumulative)[0, 1]
    return count, float(r * r)


def window_means(phi: np.ndarray, psi: np.ndarray, counts: np.ndarray, window=ORDER_WINDOW) -> dict:
    """Series index i holds time i + 1; window covers times [start, end)."""
    sl = slice(window[0] - 1, window[1] - 1)
    return {"phi": float(phi[sl].mean()), "psi": float(psi[sl].mean()),
            "foragers": float(counts[sl, 0].mean()), "transporters": float(counts[sl, 1].mean()),
            "followers": float(counts[sl, 2].mean())}


def seed_checks(m: dict, psi_off: float | None) -> dict:
    """Per-seed booleans. ``m`` holds the run summary metrics; psi_off from the paired off-run."""
    phi_ok = abs(m["phi"] - PHI_TARGET) <= PHI_TOL
    basic5 = (m["psi"] >= BASIC["psi"] and psi_off is not None and m["psi"] >= psi_off + BASIC["psi_gain"]
              and phi_ok and m["foragers"] <= BASIC["foragers"])
    return {
        "c1": m["first_pickup"] <= DISCOVERY_MAX,
        "c2": m["recruitment"] >= RECRUIT_MIN,
        "c3": m["trail_share"] >= TRAIL_MIN,
        "c4": m["deliveries_window"] >= TRANSPORT_MIN and m["r2"] >= R2_MIN,
        "c5_full": m["psi"] >= FULL["psi"] and phi_ok and m["foragers"] <= FULL["foragers"],
        "c5_basic": bool(basic5),
    }


def condition_checks(runs: list[dict], off_psi: dict[int, float] | None) -> dict:
    """Condition-level pass: median meets the rule and >= 80% of seeds meet it.

    The median condition is applied to each metric of a check separately (e.g. check 4 needs the
    median count >= 100 and the median R^2 >= 0.95); the seed share uses the per-seed boolean.
    """
    per_seed = [seed_checks(r, None if off_psi is None else off_psi.get(r["seed"])) for r in runs]
    med = {k: float(np.median([r[k] for r in runs])) for k in
           ("first_pickup", "recruitment", "trail_share", "deliveries_window", "r2", "psi", "phi", "foragers")}
    gain = (float(np.median([r["psi"] - off_psi[r["seed"]] for r in runs]))
            if off_psi and all(r["seed"] in off_psi for r in runs) else float("nan"))
    phi_ok = abs(med["phi"] - PHI_TARGET) <= PHI_TOL
    median_ok = {
        "c1": med["first_pickup"] <= DISCOVERY_MAX,
        "c2": med["recruitment"] >= RECRUIT_MIN,
        "c3": med["trail_share"] >= TRAIL_MIN,
        "c4": med["deliveries_window"] >= TRANSPORT_MIN and med["r2"] >= R2_MIN,
        "c5_full": med["psi"] >= FULL["psi"] and phi_ok and med["foragers"] <= FULL["foragers"],
        "c5_basic": (med["psi"] >= BASIC["psi"] and gain >= BASIC["psi_gain"] and phi_ok
                     and med["foragers"] <= BASIC["foragers"]),
    }
    need = math.ceil(SEED_SHARE * len(runs) - 1e-9)
    out = {k: bool(median_ok[k] and sum(s[k] for s in per_seed) >= need) for k in median_ok}
    out["seeds_meeting"] = {k: int(sum(s[k] for s in per_seed)) for k in median_ok}
    out["medians"], out["median_psi_gain"] = med, gain
    base = out["c1"] and out["c2"] and out["c3"] and out["c4"]
    out["full_pass"], out["basic_pass"] = bool(base and out["c5_full"]), bool(base and out["c5_basic"])
    return out
