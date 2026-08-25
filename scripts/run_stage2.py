#!/usr/bin/env python3
"""Run the fixed Stage 2A pilot and/or paper-scale CPU experiment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from colony.config import ColonyConfig  # noqa: E402
from colony.experiment import run_experiment, summarise_output  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CPU-only provisional Stage 2A ant-colony simulation."
    )
    parser.add_argument("--preset", choices=("suite", "pilot", "paper"), default="suite")
    parser.add_argument("--model", choices=("srw", "fcrw", "zw"), default="zw")
    parser.add_argument("--seed", type=int, default=20_260_824)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/stage2_provisional")
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="skip the pre-run pytest gate (not recommended for the suite preset)",
    )
    return parser


def run_tests() -> str:
    environment = os.environ.copy()
    cache_root = Path(environment.get("TMPDIR", "/tmp")) / "ant-colony-stage2-cache"
    environment.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    environment.setdefault("XDG_CACHE_HOME", str(cache_root))
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if completed.returncode != 0:
        print(output, file=sys.stderr)
        raise RuntimeError("automated tests failed; Stage 2A runs were not started")
    summary = next((line for line in reversed(output.splitlines()) if line.strip()), "tests passed")
    print(summary)
    return summary


def configured(base: ColonyConfig, *, model: str, seed: int) -> ColonyConfig:
    return replace(base, seed=seed, movement=replace(base.movement, model=model))


def pilot_gate(summary: dict[str, object]) -> bool:
    transitions = summary["transition_counts"]
    assert isinstance(transitions, dict)
    return bool(
        summary["first_food_discovery_time"] is not None
        and summary["first_delivery_time"] is not None
        and int(summary["cumulative_deliveries"]) >= 1
        and int(transitions["transporter_to_follower"]) >= 1
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = args.output_dir
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    test_summary = "tests skipped by explicit CLI option"
    if not args.skip_tests:
        test_summary = run_tests()

    suite_start = time.perf_counter()
    if args.preset == "pilot":
        config = configured(
            ColonyConfig.pilot(output_dir=output_root / "pilot"),
            model=args.model,
            seed=args.seed,
        )
        output = run_experiment(config, test_summary=test_summary)
        print(json.dumps(summarise_output(output), indent=2, sort_keys=True))
        return 0

    if args.preset == "paper":
        config = configured(
            ColonyConfig.paper_scale(output_dir=output_root), model=args.model, seed=args.seed
        )
        output = run_experiment(config, test_summary=test_summary)
        print(json.dumps(summarise_output(output), indent=2, sort_keys=True))
        return 0

    pilot_config = configured(
        ColonyConfig.pilot(output_dir=output_root / "pilot"), model=args.model, seed=args.seed
    )
    pilot_output = run_experiment(pilot_config, test_summary=test_summary)
    pilot_summary = summarise_output(pilot_output)
    if not pilot_gate(pilot_summary):
        print(json.dumps(pilot_summary, indent=2, sort_keys=True), file=sys.stderr)
        raise RuntimeError("small pilot gate failed; paper-scale run was not started")

    paper_config = configured(
        ColonyConfig.paper_scale(output_dir=output_root), model=args.model, seed=args.seed
    )
    paper_output = run_experiment(
        paper_config,
        test_summary=test_summary,
        pilot_summary=pilot_summary,
    )
    paper_summary = summarise_output(paper_output)
    suite_runtime = {
        "test_summary": test_summary,
        "pilot": pilot_summary,
        "paper_scale": paper_summary,
        "suite_total_seconds": time.perf_counter() - suite_start,
        "cpu_only": True,
        "gpu_used": False,
        "autodl_used": False,
    }
    (output_root / "suite_runtime.json").write_text(
        json.dumps(suite_runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(suite_runtime, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
