#!/usr/bin/env python3
"""Stage 2C entry point. No default execution mode and no model/seed overrides."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ["MPLBACKEND"] = "Agg"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from colony.stage2c import DEFAULT_OUTPUT, Study, dry_run, study_lock, validate_output
from colony.stage2c_checkpoint import json_bytes
from colony.stage2c_repair import repair_preflight


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--mode", required=True, choices=(
        "pilot", "full", "analyse", "dry-run", "repair-preflight",
        "repair-resource-amendment", "repair-resource-history"))
    command.add_argument("--resume", action="store_true", help="resume the same incomplete seed; completed runs are verified and reused")
    command.add_argument("--output-dir", type=Path, help="administrative output location; dry-run requires a temporary directory")
    return command


def main(argv=None) -> int:
    command = parser()
    args = command.parse_args(argv)
    if args.resume and args.mode not in ("pilot", "full"):
        command.error("--resume applies only to pilot or full")
    if args.mode == "dry-run":
        result = dry_run(PROJECT_ROOT, args.output_dir)
    elif args.mode == "repair-resource-history":
        from colony.stage2c_resource_history import repair_resource_history
        result = repair_resource_history(
            PROJECT_ROOT, args.output_dir or PROJECT_ROOT / DEFAULT_OUTPUT)
    elif args.mode == "repair-resource-amendment":
        from colony.stage2c_amendment import repair_resource_amendment
        result = repair_resource_amendment(PROJECT_ROOT, args.output_dir or PROJECT_ROOT / DEFAULT_OUTPUT)
    elif args.mode == "repair-preflight":
        result = repair_preflight(PROJECT_ROOT, args.output_dir or PROJECT_ROOT / DEFAULT_OUTPUT)
    else:
        output = args.output_dir or PROJECT_ROOT / DEFAULT_OUTPUT
        output = output.resolve()
        try:
            validate_output(PROJECT_ROOT, output)
        except ValueError as error:
            command.error(str(error))
        if args.mode == "analyse" and not (output / "checkpoint/progress_manifest.json").is_file():
            command.error("analyse requires an existing completed study")
        previous_handler = signal.getsignal(signal.SIGTERM)

        def interrupted(signum, frame):
            raise KeyboardInterrupt("SIGTERM")

        signal.signal(signal.SIGTERM, interrupted)
        try:
            with study_lock(output):
                study = Study(PROJECT_ROOT, output)
                result = study.analyse() if args.mode == "analyse" else study.execute(args.mode, resume=args.resume)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
    print(json_bytes(result).decode(), end="")
    return 2 if result.get("status") == "paused" or result.get("action") == "pause" else 0


if __name__ == "__main__":
    raise SystemExit(main())
