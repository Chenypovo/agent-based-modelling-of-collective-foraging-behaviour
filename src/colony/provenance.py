"""Stage 1 preservation manifest recorded before Stage 2A implementation."""

from __future__ import annotations

import hashlib
from pathlib import Path

STAGE1_BASELINE_SHA256 = {
    "docs/STAGE1_SPEC.md": "38c741d14ab0adbdc448a24424b08042679eaed8db645ed5c6fc7ea9626da3f3",
    "run_stage1.sh": "b2d5540708cb73ce54fa4016d5005b79b2bae74e34b8683de5e2e906bf7569a5",
    "scripts/run_stage1.py": "a4e09cd333c98b12c9d989343008cee6f06b5004e4585b235fc1456d6a7301e3",
    "src/ant_walks/__init__.py": "cc4cd63987bb28137859c7debab8f67d5487602e760478778e4d8fcbe5bd56fc",
    "src/ant_walks/cli.py": "b099b9d3d18789ab70f0b79fae4d1e2097fb03cf75f4778ba78d18729b93b710",
    "src/ant_walks/experiment.py": "c950a3eefaad950ec1455632654efb434225d69159c14d575fd7ad3470e2e1d7",
    "src/ant_walks/metrics.py": "1d898636fa74ec76f22011cd57b288eb3b9eccc4d2a9ff675dcdc41291cac14b",
    "src/ant_walks/models.py": "96589d8fd545cc98d3434f7d34201d537905fa3a561460f7f3e037f28915f0c4",
    "tests/conftest.py": "0a586e159d2b7889ffda8fb3d1b225d142b8f33875da9ab061d94b8fc6fea09c",
    "tests/test_metrics.py": "d33b90c224dd0bb36317d105cc1a92a27e86d0a1b8c06af443b6f614270e2691",
    "tests/test_models.py": "f1929b4f061286043c19bd976d300294c6fcdbef911dd57acacf9613a809256c",
    "results/stage1/REPORT.md": "dba514b3c150730a7618d428635beee02e5cbcdc96fee7079ef01ee2ecf33075",
    "results/stage1/config.json": "94a878200da36e427e140809bc52467e0e539e8df7ed636b61d99adaef8e11c6",
    "results/stage1/metrics_per_run.csv": "1eb4f8f270813281f77bc853bba16035466747da8d4dddcf6e41d51a3db554ed",
    "results/stage1/runtime.json": "35ea816e6a1e04bc9e13641d6b1d5234b82d6c81c1fb973d781ec96c393e93bf",
    "results/stage1/spatial_statistics.png": "1708cbda1b1ef9a8818b3a94abef05f89a0a2fd339ea94c2a8bb1c6ade819dc3",
    "results/stage1/summary.csv": "493a7bb85c78331f30b74eac6aa3195d433d445fec51991bb600bcbbb352b644",
    "results/stage1/trajectories.png": "8e9bcaa8577bd3cda1345099cc0a0f701cb5ccf5b4de1e6ce4e24fc0430a9cc0",
    "results/stage1/turning_statistics.png": "6a3066da12687f5dc8b66132d2dc15f2399512fe6889c877b3eff99c41a723dc",
}


def stage1_hash_manifest(project_root: Path) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    for relative_path, expected in STAGE1_BASELINE_SHA256.items():
        path = project_root / relative_path
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        files[relative_path] = {
            "baseline_sha256": expected,
            "current_sha256": current,
            "matches_baseline": current == expected,
        }
    return {
        "algorithm": "SHA-256",
        "recorded_before_stage2a": True,
        "all_match": all(entry["matches_baseline"] for entry in files.values()),
        "files": files,
    }
