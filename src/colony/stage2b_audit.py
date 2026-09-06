"""Stage 2B protected-file and single-configuration-change audits."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Mapping

PROTECTED_DIRECTORIES = (
    "results/stage1",
    "results/stage2_provisional",
    "results/stage2_diagnostic",
)
PROTECTED_FILES = (
    "docs/STAGE1_SPEC.md",
    "docs/STAGE2_SPEC.md",
    "Project Proposal.pdf",
    "_PH6780 Templates.docx",
    "_AY2627_T1_Briefing_updated.pdf",
    "references.bib",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def protected_sha256_manifest(project_root: Path) -> dict[str, object]:
    """Hash every file in the pre-registered protected scope."""

    root = project_root.resolve()
    paths: list[Path] = []
    for relative in PROTECTED_DIRECTORIES:
        directory = root / relative
        if not directory.is_dir():
            raise FileNotFoundError(f"missing protected directory: {relative}")
        paths.extend(path for path in directory.rglob("*") if path.is_file())
    for relative in PROTECTED_FILES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing protected file: {relative}")
        paths.append(path)
    entries = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix())
    }
    return {
        "algorithm": "SHA-256",
        "protected_directories": list(PROTECTED_DIRECTORIES),
        "protected_files": list(PROTECTED_FILES),
        "file_count": len(entries),
        "files": entries,
    }


def compare_protected_manifests(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, object]:
    before_files = dict(before.get("files", {}))
    after_files = dict(after.get("files", {}))
    paths = sorted(set(before_files) | set(after_files))
    checks = {
        path: {
            "before_sha256": before_files.get(path),
            "after_sha256": after_files.get(path),
            "match": before_files.get(path) == after_files.get(path),
        }
        for path in paths
    }
    return {
        "algorithm": "SHA-256",
        "before_file_count": len(before_files),
        "after_file_count": len(after_files),
        "all_match": bool(paths) and all(bool(item["match"]) for item in checks.values()),
        "files": checks,
    }


def _normalise_config(value: Mapping[str, object]) -> dict[str, object]:
    normalised = deepcopy(dict(value))
    normalised.setdefault("follower_direction_rule", "stored_cell_direction")
    normalised.pop("output_dir", None)
    return json.loads(json.dumps(normalised, sort_keys=True))


def _differences(left: object, right: object, prefix: str = "") -> list[dict[str, object]]:
    if isinstance(left, dict) and isinstance(right, dict):
        rows: list[dict[str, object]] = []
        for key in sorted(set(left) | set(right)):
            name = f"{prefix}.{key}" if prefix else str(key)
            if key not in left:
                rows.append({"field": name, "baseline": None, "stage2b": right[key]})
            elif key not in right:
                rows.append({"field": name, "baseline": left[key], "stage2b": None})
            else:
                rows.extend(_differences(left[key], right[key], name))
        return rows
    if left != right:
        return [{"field": prefix, "baseline": left, "stage2b": right}]
    return []


def single_change_audit(
    baseline_config: Mapping[str, object], stage2b_config: Mapping[str, object]
) -> dict[str, object]:
    """Confirm that the only behavioural config change is the follower rule."""

    baseline = _normalise_config(baseline_config)
    stage2b = _normalise_config(stage2b_config)
    differences = _differences(baseline, stage2b)
    expected = [
        {
            "field": "follower_direction_rule",
            "baseline": "stored_cell_direction",
            "stage2b": "local_weighted_pca_tangent",
        }
    ]
    return {
        "ignored_non_behavioural_fields": ["output_dir"],
        "differences": differences,
        "difference_count": len(differences),
        "only_follower_direction_rule_changed": differences == expected,
    }
