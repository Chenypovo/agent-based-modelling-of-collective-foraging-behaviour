"""Command-line interface for the Stage 1 experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from .experiment import ExperimentConfig, normalise_models, run_experiment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CPU-only Stage 1 single-ant SRW/FCRW/ZW experiments."
    )
    parser.add_argument("--model", choices=("all", "srw", "fcrw", "zw"), default="all")
    parser.add_argument("--steps", type=int, default=2_000)
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument("--step-size", type=float, default=None)
    size_group.add_argument(
        "--speed",
        type=float,
        default=None,
        help="constant speed; with the fixed unit time step this equals step size",
    )
    parser.add_argument("--theta-deg", type=float, default=60.0, help="maximum turn magnitude")
    parser.add_argument("--gamma", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=20_260_824)
    parser.add_argument("--repetitions", type=int, default=50)
    parser.add_argument(
        "--cell-size",
        type=float,
        default=None,
        help="coverage-grid side length; defaults to the step size",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("results/stage1"))
    return parser


def main(argv: list[str] | None = None, *, process_start: float | None = None) -> int:
    args = build_parser().parse_args(argv)
    step_size = 0.6
    if args.step_size is not None:
        step_size = args.step_size
    elif args.speed is not None:
        step_size = args.speed
    cell_size = step_size if args.cell_size is None else args.cell_size

    config = ExperimentConfig(
        models=normalise_models(args.model),
        steps=args.steps,
        step_size=step_size,
        theta_deg=args.theta_deg,
        gamma=args.gamma,
        seed=args.seed,
        repetitions=args.repetitions,
        cell_size=cell_size,
        output_dir=str(args.output_dir),
    )
    result = run_experiment(config, process_start=process_start)
    print(
        f"Stage 1 complete: {len(result.metrics)} trajectories in "
        f"{result.runtime_seconds:.3f} s; outputs: {result.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
