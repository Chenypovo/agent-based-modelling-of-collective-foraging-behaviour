"""Atomic, non-executable checkpoint format: JSON metadata and NumPy arrays.

No pickle or dynamic class import is used. Restoration bypasses initialisation,
so the saved turn schedules and observations are reused without random draws.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from dataclasses import fields, is_dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .agents import Ant, Role
from .config import ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig
from .environment import SquareEnvironment
from .pheromone import PheromoneField
from .simulation import FollowerDirectionDecision
from .stage2c_streaming import StreamingSimulation
from .transitions import TransitionRecord

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 100_000_000
CLASSES = {cls.__name__: cls for cls in (
    Ant, ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig,
    SquareEnvironment, PheromoneField, FollowerDirectionDecision, TransitionRecord,
)}


def json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_value(value) -> str:
    return digest_bytes(json_bytes(value))


def atomic_write(path: Path, data: bytes, *, replace: bool = True) -> None:
    path = Path(path)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("new output exceeds the 100 MB per-file bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if replace:
        os.replace(temporary, path)
    else:
        # Atomic no-clobber publication, including another process racing us.
        os.link(temporary, path)
        os.unlink(temporary)
    directory_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_json(path: Path, value, *, replace: bool = True) -> None:
    atomic_write(path, json_bytes(value), replace=replace)


def read_json(path: Path):
    def invalid(value):
        raise ValueError("non-standard JSON constant: " + value)
    return json.loads(Path(path).read_text(), parse_constant=invalid)


def behavioural_config(config: ColonyConfig) -> dict:
    values = config.to_dict()
    values.pop("output_dir")
    return json.loads(json_bytes(values))


class StateCodec:
    def __init__(self):
        self.arrays = {}

    def pack(self, value):
        if isinstance(value, Role):
            return {"type": "Role", "value": value.value}
        if isinstance(value, np.ndarray):
            if value.dtype.hasobject or not np.isfinite(value).all():
                raise ValueError("checkpoint arrays must contain finite numeric state")
            name = f"arrays/{len(self.arrays):06d}.npy"
            buffer = io.BytesIO()
            np.save(buffer, value, allow_pickle=False)
            self.arrays[name] = buffer.getvalue()
            return {"type": "array", "name": name}
        if isinstance(value, np.generic):
            return self.pack(value.item())
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, pd.DataFrame):
            return {"type": "frame", "columns": list(value.columns),
                    "index": list(value.index), "dtypes": [str(x) for x in value.dtypes],
                    "rows": self.pack(value.to_numpy().tolist())}
        if isinstance(value, dict):
            return {"type": "dict", "items": [[self.pack(k), self.pack(v)] for k, v in value.items()]}
        if isinstance(value, (list, tuple)):
            return {"type": "tuple" if isinstance(value, tuple) else "list",
                    "items": [self.pack(v) for v in value]}
        name = type(value).__name__
        if name not in CLASSES or type(value) is not CLASSES[name]:
            raise TypeError("unsupported checkpoint state type: " + name)
        attributes = {f.name: getattr(value, f.name) for f in fields(value)} if is_dataclass(value) else vars(value)
        attributes = dict(attributes)
        if isinstance(value, Ant):
            # One dense array, not thousands of tiny per-vertex archive entries.
            attributes["travel_path"] = np.asarray(value.travel_path, dtype=float)
        return {"type": "object", "class": name, "attributes": self.pack(attributes)}

    def unpack(self, value):
        if not isinstance(value, dict):
            return value
        kind = value["type"]
        if kind == "Role":
            return Role(value["value"])
        if kind == "array":
            array = np.load(io.BytesIO(self.arrays[value["name"]]), allow_pickle=False)
            if array.dtype.hasobject or not np.isfinite(array).all():
                raise ValueError("invalid checkpoint array")
            return array
        if kind == "dict":
            return {self.unpack(k): self.unpack(v) for k, v in value["items"]}
        if kind in ("list", "tuple"):
            result = [self.unpack(v) for v in value["items"]]
            return tuple(result) if kind == "tuple" else result
        if kind == "frame":
            frame = pd.DataFrame(self.unpack(value["rows"]), columns=value["columns"])
            for column, dtype in zip(value["columns"], value["dtypes"]):
                frame[column] = frame[column].astype(dtype)
            if value["index"] != list(range(len(frame))):
                frame.index = value["index"]
            return frame
        if kind == "object":
            cls = CLASSES[value["class"]]
            attributes = self.unpack(value["attributes"])
            if cls is Ant:
                attributes["travel_path"] = [row.copy() for row in attributes["travel_path"]]
            obj = object.__new__(cls)
            obj.__dict__.update(attributes)
            return obj
        raise ValueError("unsupported checkpoint node")


def state_fingerprint(simulation: StreamingSimulation) -> str:
    """Deterministic state identity excluding wall-clock bookkeeping."""
    codec = StateCodec()
    state = dict(vars(simulation))
    state.pop("runtime_counters")
    packed = codec.pack(state)
    return hash_value({"state": packed,
                       "arrays": {k: digest_bytes(v) for k, v in codec.arrays.items()}})


def initial_identity(simulation: StreamingSimulation) -> dict:
    """Accept a simulation at time zero; never initialise one implicitly."""
    if simulation.time != 0:
        raise ValueError("initial identity requires time zero")
    codec = StateCodec()
    packed = codec.pack(simulation.ants)
    initial = hash_value({"ants": packed, "arrays": {k: digest_bytes(v) for k, v in codec.arrays.items()}})
    schedules = np.ascontiguousarray(simulation.turn_schedules)
    schedule_hash = hash_value({"dtype": schedules.dtype.str, "shape": list(schedules.shape),
                               "data_sha256": digest_bytes(schedules.tobytes())})
    return {"initial_state_hash": initial, "turn_schedule_hash": schedule_hash,
            "rng_state": simulation.rng_state}


def save_checkpoint(path: Path, simulation: StreamingSimulation, identity: dict) -> str:
    if simulation._observing_ant is not None or simulation._observed_decision is not None:
        raise ValueError("checkpoint only at a complete step boundary")
    simulation._assert_invariants()
    codec = StateCodec()
    packed = codec.pack(vars(simulation))
    metadata = {"schema_version": SCHEMA_VERSION, "identity": identity,
                "config_hash": hash_value(behavioural_config(simulation.config)),
                "seed": simulation.config.seed, "rule": simulation.config.follower_direction_rule,
                "time": simulation.time, "state": packed,
                "array_hashes": {name: digest_bytes(data) for name, data in codec.arrays.items()}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json_bytes(metadata))
        for name, data in codec.arrays.items():
            archive.writestr(name, data)
    data = buffer.getvalue()
    atomic_write(path, data)
    return digest_bytes(data)


def load_checkpoint(path: Path, config: ColonyConfig, identity: dict,
                    *, expected_sha256: str | None = None) -> StreamingSimulation:
    data = Path(path).read_bytes()
    if expected_sha256 is not None and digest_bytes(data) != expected_sha256:
        raise ValueError("checkpoint checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 1_000_000_000:
            raise ValueError("checkpoint expands beyond the local format bound")
        metadata = json.loads(archive.read("metadata.json"),
                              parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if metadata["schema_version"] != SCHEMA_VERSION or metadata["identity"] != identity:
            raise ValueError("checkpoint code, input or preregistration identity mismatch")
        if metadata["config_hash"] != hash_value(behavioural_config(config)):
            raise ValueError("checkpoint configuration mismatch")
        if metadata["seed"] != config.seed or metadata["rule"] != config.follower_direction_rule:
            raise ValueError("checkpoint seed/rule mismatch")
        codec = StateCodec()
        for name, expected in metadata["array_hashes"].items():
            raw = archive.read(name)
            if digest_bytes(raw) != expected:
                raise ValueError("checkpoint array checksum mismatch")
            codec.arrays[name] = raw
        restored = object.__new__(StreamingSimulation)
        restored.__dict__.update(codec.unpack(metadata["state"]))
    if behavioural_config(restored.config) != behavioural_config(config) or restored.time != metadata["time"]:
        raise ValueError("checkpoint state/config mismatch")
    restored.config = config  # Administrative output routing may differ.
    restored._assert_invariants()
    if len(restored._metric_rows) != restored.time + 1 or len(restored.role_rows) != restored.time + 1:
        raise ValueError("checkpoint metric timeline mismatch")
    if restored._metric_rows[-1]["cumulative_deliveries"] != restored.cumulative_deliveries:
        raise ValueError("checkpoint delivery counter mismatch")
    return restored
