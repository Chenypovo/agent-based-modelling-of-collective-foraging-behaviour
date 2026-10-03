#!/usr/bin/env python3
"""Five-check tables per condition (docs/PAPER_BASELINE_PLAN.md Sec. 2); calib also writes selection.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from paper_baseline import checks  # noqa: E402
from paper_baseline_run import OUT, SEEDS  # noqa: E402

KEYS = ("c1", "c2", "c3", "c4", "c5_full", "c5_basic")


def load(step: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for p in sorted((OUT / step / "runs").glob("*.json")):
        r = json.loads(p.read_text())
        groups.setdefault(r["name"], []).append(r)
    return groups


def off_name(name: str, groups: dict) -> str | None:
    if name.endswith("off"):
        return None
    noise_off = name.split("_")[0] + "_off" if name.startswith("n") else None  # calib2: n{noise}_off
    for cand in (f"{name}_off", noise_off, "off"):
        if cand in groups:
            return cand
    return None


def evaluate(groups: dict) -> dict[str, dict]:
    out = {}
    for name, runs in groups.items():
        off = off_name(name, groups)
        off_psi = {r["seed"]: r["psi"] for r in groups[off]} if off else None
        res = checks.condition_checks(runs, off_psi)
        res["n"] = len(runs)
        res["deliveries_median"] = float(np.median([r["deliveries_window"] for r in runs]))
        res["config"] = {k: runs[0].get(k, d) for k, d in (("field", None), ("half_life", None), ("D", None),
                         ("thr", None), ("walk", None), ("deposit", None), ("layout", None), ("steps", None),
                         ("homing", "route"), ("noise", 0.0))}
        out[name] = res
    return out


def table(results: dict) -> str:
    lines = ["| condition | n | 1 first pickup | 2 recruit | 3 trail | 4 deliveries / R² | ψ | φ | foragers | ψ − ψ_off | "
             "checks passed (1,2,3,4,5full,5basic) | tier |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        m, s = r["medians"], r["seeds_meeting"]
        flags = " ".join(("✓" if r[k] else "✗") + f"{s[k]}" for k in KEYS)
        tier = "FULL" if r["full_pass"] else "basic" if r["basic_pass"] else "—"
        lines.append(f"| {name} | {r['n']} | {m['first_pickup']:.0f} | {m['recruitment']:.2f} | {m['trail_share']:.2f} | "
                     f"{m['deliveries_window']:.0f} / {m['r2']:.2f} | {m['psi']:.3f} | {m['phi']:.3f} | "
                     f"{m['foragers']:.0f} | {r['median_psi_gain']:.3f} | {flags} | {tier} |")
    return "\n".join(lines)


def select(results: dict, fallback: bool = False) -> dict | None:
    cells = {k: v for k, v in results.items() if not k.endswith("off")}
    for tier in ("full_pass", "basic_pass"):
        ok = {k: v for k, v in cells.items() if v[tier]}
        if ok:
            best = max(v["deliveries_median"] for v in ok.values())
            near = [(k, v) for k, v in ok.items() if v["deliveries_median"] >= 0.95 * best]
            near.sort(key=lambda kv: (kv[1]["config"]["D"], kv[1]["config"]["half_life"] != 1000,
                                      kv[1]["config"]["thr"] != "t50", -kv[1]["deliveries_median"]))
            name, v = near[0]
            return {"tier": tier, "name": name, "chosen": v["config"], "tied": [k for k, _ in near]}
    if fallback:  # Amendment B: no basic pass -> best of the cells passing checks 1-4; check 5 reported failed
        ok = {k: v for k, v in cells.items() if v["c1"] and v["c2"] and v["c3"] and v["c4"]}
        if ok:
            best = max(v["deliveries_median"] for v in ok.values())
            near = [(k, v) for k, v in ok.items() if v["deliveries_median"] >= 0.95 * best]
            near.sort(key=lambda kv: (kv[1]["config"]["D"], kv[1]["config"]["half_life"] != 1000,
                                      kv[1]["config"]["thr"] != "t50", -kv[1]["deliveries_median"]))
            name, v = near[0]
            return {"tier": "fallback_checks_1_to_4_only (check 5 FAILED)", "name": name, "chosen": v["config"],
                    "tied": [k for k, _ in near], "check5_medians": {k: v["medians"][k] for k in ("psi", "phi", "foragers")}}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=tuple(SEEDS))
    args = parser.parse_args()
    results = evaluate(load(args.step))
    text = [f"# Five static checks: step `{args.step}`", "",
            "Medians over seeds. Each check cell: ✓/✗ = condition-level pass (median meets it and ≥ 80% of "
            "seeds meet it), followed by the number of seeds meeting it.", "", table(results), ""]
    if args.step in ("calib", "calib2", "calib3"):
        sel = select(results, fallback=args.step == "calib3")
        text += ["## Selection", "", json.dumps(sel, indent=1) if sel else "No cell reached basic pass: stop."]
        (OUT / args.step / "selection.json").write_text(json.dumps(sel, indent=1) + "\n")
    (OUT / args.step / "summary.md").write_text("\n".join(text) + "\n")
    (OUT / args.step / "summary.json").write_text(json.dumps(results, indent=1, default=float) + "\n")
    print("\n".join(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
