#!/usr/bin/env python3
"""Read-only code/protection audit; write evidence only to the Stage 3A root."""

from __future__ import annotations

import ast
from dataclasses import asdict
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["MPLBACKEND"] = "Agg"
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/stage3a_scalar_baseline"
sys.path.insert(0, str(ROOT / "src"))

from scalar_baseline.config import SimulationConfig, matched_cutoff_steps
from scalar_baseline.field import ScalarField
from scalar_baseline.navigation import navigate
from scalar_baseline.simulation import Simulation
import scalar_baseline.navigation as navigation
import scalar_baseline.sensing as sensing


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def write(name: str, data: dict) -> None:
    (OUT / name).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def audit() -> bool:
    before = json.loads((OUT / "protected_sha256_before.json").read_text())
    start = time.perf_counter()
    after, missing = {}, []
    for name in before["files"]:
        path = ROOT / name
        if not path.is_file():
            missing.append(name)
        else:
            after[name] = digest(path)
    changed = [name for name, sha in after.items() if sha != before["files"][name]]
    # Strict membership comparison for every old result/material directory.
    strict_roots = [".tmp_progress_report", "from_prof", "reports"]
    strict_roots += [str(p.relative_to(ROOT)) for p in (ROOT / "results").iterdir()
                     if p.is_dir() and p != OUT]
    added = sorted(str(p.relative_to(ROOT)) for name in strict_roots
                   for p in (ROOT / name).rglob("*")
                   if p.is_file() and str(p.relative_to(ROOT)) not in before["files"])
    protected = {"pass": not (missing or changed or added), "files_checked": len(after),
                 "missing": missing, "changed": changed, "unexpected_protected_files": added,
                 "strict_membership_roots": strict_roots, "seconds": time.perf_counter() - start,
                 "base_head": before["base_head"], "files": after}
    write("protected_sha256_check.json", protected)

    prohibited = {"food_a", "food_b", "food_contact", "environment", "ledger", "cargo",
                  "direction_sum", "mean_direction", "argmax", "gradient"}
    identifiers = {}
    for module in (navigation, sensing):
        tree = ast.parse(inspect.getsource(module))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        identifiers[module.__name__] = sorted(names & prohibited)
    move_source = inspect.getsource(Simulation._move)
    isolation = {"pass": not any(identifiers.values()) and not any(word in move_source for word in ("environment", "food_a", "food_b", "ledger")),
                 "navigation_parameters": list(inspect.signature(navigate).parameters),
                 "prohibited_identifier_hits": identifiers,
                 "food_coordinates_owned_by": "ContactEnvironment; configuration/reporting only elsewhere",
                 "cargo_identity_owned_by": "Ledger; never supplied to navigation",
                 "dynamic_evidence": ["test_changing_food_positions_cannot_change_noncontact_navigation",
                                      "test_move_has_no_contact_environment_dependency",
                                      "test_sensor_only_two_queries_and_left_geometry"],
                 "limitations": "AST checks are scoped structural evidence, supported by perturbation and poisoned-environment tests; not formal information-flow proof"}
    write("food_coordinate_isolation_audit.json", isolation)
    config = SimulationConfig()
    expected_slots = {"concentration", "last_deposit", "time", "arena_size", "cell_size", "decay"}
    configuration = {"pass": set(ScalarField.__slots__) == expected_slots and config.diffusion == 0,
                     "default_config": asdict(config), "field_slots": list(ScalarField.__slots__),
                     "event_order": "decay/expiry; relocation; all movement/local sensing; contacts; deposition",
                     "deposition_footprint": "one containing cell, no automatic spread",
                     "matching": {"q": config.deposit_q, "threshold": config.navigation.signal_on,
                                  "cutoff_steps": matched_cutoff_steps(config.deposit_q, config.navigation.signal_on, config.decay.decay_rate),
                                  "rounding": "ceil; integer snap absolute tolerance 1e-12"},
                     "roles": ["fcrw", "follower", "transporter"], "recovery_C": False,
                     "provisional_rules": "all new settings and behaviours listed in STAGE3A_SCALAR_DECAY_BASELINE_SPEC.md; no biological calibration",
                     "scientific_decay_comparison": False}
    write("config_audit.json", configuration)
    source_paths = sorted((ROOT / "src/scalar_baseline").glob("*.py"))
    source_paths += [ROOT / name for name in ("scripts/run_stage3a_pilot.py", "scripts/audit_stage3a.py",
                     "tests/test_stage3a_scalar_baseline.py", "docs/STAGE3A_SCALAR_DECAY_BASELINE_SPEC.md")]
    write("stage3a_source_sha256.json", {str(p.relative_to(ROOT)): digest(p) for p in source_paths})
    result = {"protected": protected["pass"], "isolation": isolation["pass"], "config": configuration["pass"],
              "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()}
    print(json.dumps(result, indent=2))
    return all(result[key] for key in ("protected", "isolation", "config"))


if __name__ == "__main__":
    raise SystemExit(0 if audit() else 1)
