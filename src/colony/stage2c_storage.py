"""Auditable incremental history storage for the Stage 2C runner.

The behavioural simulation continues to own its in-memory observations.  This
module only publishes immutable history chunks at checkpoint boundaries and
restores those observations after interruption.  A checkpoint therefore binds
to a manifest hash instead of embedding every earlier output row again.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .transitions import TransitionRecord


HISTORY_SCHEMA_VERSION = 1
STREAM_ATTRIBUTES = {
    "metrics": "_metric_rows",
    "agent_states": "_agent_state_rows",
    "events": "_event_records",
    "role_specific_observations": "role_rows",
    "completed_transport": "completed_transport",
}


def _normalise(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    return value


def canonical_json_bytes(value) -> bytes:
    return (json.dumps(_normalise(value), sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def deterministic_npz_bytes(arrays: dict[str, np.ndarray]) -> bytes:
    """Lossless NPZ with stable member order and timestamps."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(arrays):
            raw = io.BytesIO()
            np.save(raw, np.asarray(arrays[name]), allow_pickle=False)
            info = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw.getvalue())
    return output.getvalue()


def _atomic_write(path: Path, data: bytes, *, replace: bool) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp",
                                     dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            os.unlink(temporary)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _publish_immutable(path: Path, data: bytes) -> None:
    """Publish once; an identical orphan from a lost pointer is reusable."""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("immutable history chunk already exists with different bytes")
        return
    _atomic_write(path, data, replace=False)


def _rows(simulation, stream: str) -> list[dict]:
    values = getattr(simulation, STREAM_ATTRIBUTES[stream])
    if stream == "events":
        return [value.to_dict() for value in values]
    return [_normalise(value) for value in values]


def _blank_manifest(generation: int, time_step: int) -> dict:
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "format": "incremental_json_chunks",
        "generation": int(generation),
        "time": int(time_step),
        "streams": {name: [] for name in STREAM_ATTRIBUTES},
        "counts": {name: 0 for name in STREAM_ATTRIBUTES},
        "columns": {name: [] for name in STREAM_ATTRIBUTES},
        "pheromone_snapshots": [],
    }


class HistoryStore:
    """Immutable chunks plus one immutable manifest per checkpoint generation."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _read_manifest(self, path: Path) -> dict:
        raw = Path(path).read_bytes()
        manifest = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if manifest.get("schema_version") != HISTORY_SCHEMA_VERSION:
            raise ValueError("history manifest schema mismatch")
        self._verify_entries(manifest)
        return manifest

    def _verify_entries(self, manifest: dict) -> None:
        if manifest["format"] == "completed_csv":
            for name in STREAM_ATTRIBUTES:
                entry = manifest["streams"][name]
                path = self.root / entry["path"]
                if not path.is_file() or sha256_file(path) != entry["sha256"]:
                    raise ValueError("completed history artifact checksum mismatch")
                if entry["rows"] != manifest["counts"][name]:
                    raise ValueError("completed history row count mismatch")
            snapshot = manifest["pheromone_snapshots"]
            path = self.root / snapshot["path"]
            if not path.is_file() or sha256_file(path) != snapshot["sha256"]:
                raise ValueError("completed pheromone snapshot checksum mismatch")
            return
        for name in STREAM_ATTRIBUTES:
            expected_start = 0
            for entry in manifest["streams"][name]:
                if entry["start"] != expected_start or entry["end"] <= entry["start"]:
                    raise ValueError("history chunk sequence has a gap, overlap or empty chunk")
                path = self.root / entry["path"]
                if not path.is_file() or sha256_file(path) != entry["sha256"]:
                    raise ValueError("history chunk checksum mismatch")
                expected_start = entry["end"]
            if expected_start != manifest["counts"][name]:
                raise ValueError("history manifest count mismatch")
        seen = set()
        for entry in manifest["pheromone_snapshots"]:
            if entry["time"] in seen:
                raise ValueError("duplicate pheromone snapshot time")
            seen.add(entry["time"])
            path = self.root / entry["path"]
            if not path.is_file() or sha256_file(path) != entry["sha256"]:
                raise ValueError("pheromone snapshot checksum mismatch")

    def commit(self, simulation, generation: int,
               previous_manifest: Path | None = None) -> tuple[Path, str, dict]:
        if previous_manifest is None:
            manifest = _blank_manifest(generation, simulation.time)
        else:
            manifest = self._read_manifest(previous_manifest)
            manifest = json.loads(canonical_json_bytes(manifest))
            manifest["generation"] = int(generation)
            manifest["time"] = int(simulation.time)

        for name in STREAM_ATTRIBUTES:
            rows = _rows(simulation, name)
            if rows and not manifest["columns"][name]:
                manifest["columns"][name] = list(rows[0])
            start = int(manifest["counts"][name])
            if start > len(rows):
                raise ValueError("checkpoint history is shorter than its committed prefix")
            if start:
                committed = self._load_stream(manifest, name)
                if canonical_json_bytes(committed) != canonical_json_bytes(rows[:start]):
                    raise ValueError("checkpoint history prefix differs from immutable chunks")
            if start == len(rows):
                continue
            payload = {"schema_version": HISTORY_SCHEMA_VERSION, "stream": name,
                       "start": start, "end": len(rows), "rows": rows[start:]}
            data = canonical_json_bytes(payload)
            relative = Path("chunks") / name / f"{start:08d}-{len(rows):08d}.json"
            _publish_immutable(self.root / relative, data)
            manifest["streams"][name].append({
                "path": relative.as_posix(), "start": start, "end": len(rows),
                "rows": len(rows) - start, "bytes": len(data), "sha256": sha256_bytes(data),
            })
            manifest["counts"][name] = len(rows)

        existing_times = {entry["time"] for entry in manifest["pheromone_snapshots"]}
        for time_step in sorted(simulation._pheromone_snapshots):
            if time_step in existing_times:
                continue
            centres, strengths, directions = simulation._pheromone_snapshots[time_step]
            data = deterministic_npz_bytes({
                "centres": centres, "strengths": strengths, "directions": directions})
            relative = Path("snapshots") / f"pheromone-{int(time_step):08d}.npz"
            _publish_immutable(self.root / relative, data)
            manifest["pheromone_snapshots"].append({
                "time": int(time_step), "path": relative.as_posix(),
                "bytes": len(data), "sha256": sha256_bytes(data),
            })
        manifest["pheromone_snapshots"].sort(key=lambda entry: entry["time"])

        manifest_path = self.root / "manifests" / f"history-{int(generation):08d}.json"
        data = canonical_json_bytes(manifest)
        _publish_immutable(manifest_path, data)
        return manifest_path, sha256_bytes(data), manifest

    def _load_stream(self, manifest: dict, name: str) -> list[dict]:
        if manifest["format"] == "completed_csv":
            entry = manifest["streams"][name]
            if entry["rows"] == 0 and not manifest["columns"][name]:
                return []
            frame = pd.read_csv(self.root / entry["path"], float_precision="round_trip")
            if list(frame.columns) != manifest["columns"][name] or len(frame) != entry["rows"]:
                raise ValueError("completed history table schema or row count mismatch")
            frame = frame.astype(object).where(pd.notna(frame), None)
            return frame.to_dict(orient="records")
        rows = []
        for entry in manifest["streams"][name]:
            payload = json.loads((self.root / entry["path"]).read_bytes(),
                                 parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if (payload.get("schema_version") != HISTORY_SCHEMA_VERSION
                    or payload.get("stream") != name
                    or payload.get("start") != len(rows)
                    or payload.get("end") != len(rows) + len(payload.get("rows", []))):
                raise ValueError("history chunk metadata mismatch")
            rows.extend(payload["rows"])
        columns = manifest["columns"][name]
        if columns:
            rows = [{column: row[column] for column in columns} for row in rows]
        return rows

    def load(self, manifest_path: Path, *, expected_sha256: str | None = None) -> dict:
        manifest_path = Path(manifest_path)
        if expected_sha256 is not None and sha256_file(manifest_path) != expected_sha256:
            raise ValueError("history manifest checksum mismatch")
        manifest = self._read_manifest(manifest_path)
        result = {name: self._load_stream(manifest, name) for name in STREAM_ATTRIBUTES}
        result["pheromone_snapshots"] = {}
        if manifest["format"] == "completed_csv":
            snapshot = manifest["pheromone_snapshots"]
            with np.load(self.root / snapshot["path"], allow_pickle=False) as arrays:
                for time_step in snapshot["times"]:
                    prefix = f"t{int(time_step)}_"
                    result["pheromone_snapshots"][time_step] = tuple(
                        np.asarray(arrays[prefix + name]).copy()
                        for name in ("centres", "strengths", "directions"))
        else:
            for entry in manifest["pheromone_snapshots"]:
                with np.load(self.root / entry["path"], allow_pickle=False) as arrays:
                    result["pheromone_snapshots"][entry["time"]] = tuple(
                        np.asarray(arrays[name]).copy()
                        for name in ("centres", "strengths", "directions"))
        result["manifest"] = manifest
        return result

    def restore(self, simulation, manifest_path: Path, *, expected_sha256: str) -> dict:
        history = self.load(manifest_path, expected_sha256=expected_sha256)
        simulation._metric_rows = history["metrics"]
        simulation._agent_state_rows = history["agent_states"]
        simulation._event_records = [TransitionRecord(**row) for row in history["events"]]
        simulation.role_rows = history["role_specific_observations"]
        simulation.completed_transport = history["completed_transport"]
        simulation._snapshots = {}
        for time_step in simulation.config.snapshot_steps:
            rows = [row for row in simulation._agent_state_rows if row["time"] == time_step]
            if rows:
                simulation._snapshots[time_step] = pd.DataFrame(rows)
        simulation._pheromone_snapshots = history["pheromone_snapshots"]
        return history["manifest"]

    def frames(self, manifest_path: Path) -> dict[str, pd.DataFrame]:
        history = self.load(manifest_path)
        return {
            "metrics": pd.DataFrame(history["metrics"]),
            "agent_states": pd.DataFrame(history["agent_states"]),
            "events": pd.DataFrame(history["events"], columns=(
                "time", "ant_id", "from_role", "to_role", "reason", "x", "y")),
            "role_specific_observations": pd.DataFrame(history["role_specific_observations"]),
            "completed_transport": pd.DataFrame(history["completed_transport"]),
        }

    @classmethod
    def write_completed(cls, stage: Path, simulation, generation: int) -> tuple[Path, str]:
        """Consolidate immutable scientific history without retaining chunk copies."""
        stage = Path(stage)
        frames = {
            "metrics": pd.DataFrame(simulation._metric_rows),
            "agent_states": pd.DataFrame(simulation._agent_state_rows),
            "events": pd.DataFrame(
                [record.to_dict() for record in simulation._event_records],
                columns=("time", "ant_id", "from_role", "to_role", "reason", "x", "y")),
            "role_specific_observations": pd.DataFrame(simulation.role_rows),
            "completed_transport": pd.DataFrame(simulation.completed_transport),
        }
        names = {
            "metrics": "metrics.csv", "agent_states": "agent_states.csv",
            "events": "events.csv", "role_specific_observations": "role_specific_order.csv",
            "completed_transport": "completed_transport.csv",
        }
        manifest = _blank_manifest(generation, simulation.time)
        manifest["format"] = "completed_csv"
        manifest["streams"] = {}
        for name, frame in frames.items():
            data = frame.to_csv(index=False, lineterminator="\n").encode()
            path = stage / names[name]
            _atomic_write(path, data, replace=False)
            manifest["streams"][name] = {
                "path": "../" + names[name], "rows": len(frame),
                "bytes": len(data), "sha256": sha256_bytes(data),
            }
            manifest["counts"][name] = len(frame)
            manifest["columns"][name] = list(frame.columns)

        arrays = {}
        for time_step, values in sorted(simulation._pheromone_snapshots.items()):
            for name, value in zip(("centres", "strengths", "directions"), values):
                arrays[f"t{int(time_step)}_{name}"] = value
        snapshot_data = deterministic_npz_bytes(arrays)
        snapshot_path = stage / "pheromone_snapshots.npz"
        _atomic_write(snapshot_path, snapshot_data, replace=False)
        manifest["pheromone_snapshots"] = {
            "path": "../pheromone_snapshots.npz",
            "times": sorted(int(value) for value in simulation._pheromone_snapshots),
            "bytes": len(snapshot_data), "sha256": sha256_bytes(snapshot_data),
        }
        manifest_path = stage / "history" / "manifests" / f"history-{int(generation):08d}.json"
        data = canonical_json_bytes(manifest)
        _publish_immutable(manifest_path, data)
        return manifest_path, sha256_bytes(data)
