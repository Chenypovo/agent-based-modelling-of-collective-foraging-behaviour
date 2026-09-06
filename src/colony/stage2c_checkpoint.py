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
import time
import zipfile
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .agents import Ant, Role
from .config import ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig
from .environment import SquareEnvironment
from .movement import build_turn_schedules, initial_headings
from .pheromone import PheromoneField
from .simulation import FollowerDirectionDecision
from .stage2c_streaming import StreamingSimulation
from .stage2c_storage import (
    HistoryStore, canonical_json_bytes, deterministic_npz_bytes, sha256_file,
)
from .transitions import TransitionRecord

SCHEMA_VERSION = 2
SHARED_SCHEMA_VERSION = 1
MAX_FILE_BYTES = 100_000_000
STORAGE_FIXTURE_SEED = 991337
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


def paired_storage_config(config: ColonyConfig) -> dict:
    """Configuration identity common to the two rules for one seed."""
    values = behavioural_config(config)
    values.pop("follower_direction_rule")
    return values


def _identity_binding(identity: dict) -> dict:
    keys = ("preregistration_commit", "stage2b_implementation_commit",
            "protocol_input_commit", "runner_commit", "source_hash",
            "input_hash", "preregistration_hash")
    return {key: identity[key] for key in keys if key in identity}


def turn_schedule_identity(schedules: np.ndarray) -> str:
    schedules = np.ascontiguousarray(schedules)
    return hash_value({"dtype": schedules.dtype.str, "shape": list(schedules.shape),
                       "data_sha256": digest_bytes(schedules.tobytes())})


def ant_state_identity(ants: list[Ant]) -> str:
    codec = StateCodec()
    packed = codec.pack(ants)
    return hash_value({"ants": packed,
                       "arrays": {name: digest_bytes(data) for name, data in codec.arrays.items()}})


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
            stored = np.asarray(value)
            descriptor = {"type": "array", "name": name}
            if stored.dtype == np.dtype(np.float64) and stored.size:
                # Lossless bitwise transform: nearby floating-point path values
                # share leading bits, while high-entropy arrays remain exact.
                bits = np.ascontiguousarray(stored).reshape(-1).view(np.uint64)
                encoded = np.empty_like(bits)
                encoded[0] = bits[0]
                encoded[1:] = np.bitwise_xor(bits[1:], bits[:-1])
                stored = encoded
                descriptor.update(encoding="float64_xor_v1",
                                  shape=list(value.shape), dtype=value.dtype.str)
            buffer = io.BytesIO()
            np.save(buffer, stored, allow_pickle=False)
            self.arrays[name] = buffer.getvalue()
            return descriptor
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
            if value.get("encoding") == "float64_xor_v1":
                if array.dtype != np.uint64:
                    raise ValueError("invalid XOR checkpoint array")
                bits = np.bitwise_xor.accumulate(array.reshape(-1))
                array = bits.view(np.dtype(value["dtype"])).reshape(value["shape"])
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
    initial = ant_state_identity(simulation.ants)
    schedule_hash = turn_schedule_identity(simulation.turn_schedules)
    return {"initial_state_hash": initial, "turn_schedule_hash": schedule_hash,
            "rng_state": simulation.rng_state}


def _archive_bytes(metadata: dict, arrays: dict[str, bytes], *,
                   compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        def write(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = compression
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)

        write("metadata.json", json_bytes(metadata))
        for name, data in arrays.items():
            write(name, data)
    return buffer.getvalue()


def save_shared_seed_artifact(path: Path, simulation: StreamingSimulation,
                              identity: dict) -> tuple[str, dict]:
    """Save initial state and turn schedule once for both rules of one seed."""
    if simulation.time != 0:
        raise ValueError("shared seed artifact requires a time-zero simulation")
    initial = initial_identity(simulation)
    codec = StateCodec()
    payload = codec.pack({"ants": simulation.ants,
                          "turn_schedules": np.ascontiguousarray(simulation.turn_schedules)})
    metadata = {
        "schema_version": SHARED_SCHEMA_VERSION,
        "identity_hash": hash_value(_identity_binding(identity)),
        "identity_binding": _identity_binding(identity),
        "seed": simulation.config.seed,
        "pair_config_hash": hash_value(paired_storage_config(simulation.config)),
        "initial_identity": initial,
        "payload": payload,
        "array_hashes": {name: digest_bytes(data) for name, data in codec.arrays.items()},
    }
    data = _archive_bytes(metadata, codec.arrays)
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("shared seed artifact already exists with different bytes")
    else:
        atomic_write(path, data, replace=False)
    return digest_bytes(data), initial


def load_shared_seed_artifact(path: Path, config: ColonyConfig, identity: dict,
                              *, expected_sha256: str | None = None) -> dict:
    data = Path(path).read_bytes()
    checksum = digest_bytes(data)
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError("shared seed artifact checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        metadata = json.loads(archive.read("metadata.json"),
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if metadata.get("schema_version") != SHARED_SCHEMA_VERSION:
            raise ValueError("shared seed artifact schema mismatch")
        if metadata.get("identity_hash") != hash_value(_identity_binding(identity)):
            raise ValueError("shared seed artifact identity mismatch")
        if metadata.get("seed") != config.seed:
            raise ValueError("shared seed artifact seed mismatch")
        if metadata.get("pair_config_hash") != hash_value(paired_storage_config(config)):
            raise ValueError("shared seed artifact configuration mismatch")
        codec = StateCodec()
        for name, expected in metadata["array_hashes"].items():
            raw = archive.read(name)
            if digest_bytes(raw) != expected:
                raise ValueError("shared seed artifact array checksum mismatch")
            codec.arrays[name] = raw
        payload = codec.unpack(metadata["payload"])
    if ant_state_identity(payload["ants"]) != metadata["initial_identity"]["initial_state_hash"]:
        raise ValueError("shared initial state identity mismatch")
    if turn_schedule_identity(payload["turn_schedules"]) != metadata["initial_identity"]["turn_schedule_hash"]:
        raise ValueError("shared turn schedule identity mismatch")
    return {"sha256": checksum, "initial_identity": metadata["initial_identity"],
            "ants": payload["ants"], "turn_schedules": payload["turn_schedules"]}


HISTORY_ATTRIBUTES = {
    "_metric_rows", "_agent_state_rows", "_event_records", "_snapshots",
    "_pheromone_snapshots", "role_rows", "completed_transport",
}


def _relative_reference(checkpoint: Path, artifact: Path) -> str:
    return os.path.relpath(Path(artifact).resolve(), start=Path(checkpoint).resolve().parent)


def _resolve_reference(checkpoint: Path, reference: str) -> Path:
    return (Path(checkpoint).resolve().parent / reference).resolve()


def save_field_artifact(path: Path, field: PheromoneField) -> str:
    data = deterministic_npz_bytes({"intensity": field.intensity,
                                    "direction_sum": field.direction_sum})
    atomic_write(path, data, replace=False)
    return digest_bytes(data)


def load_field_artifact(path: Path, config: ColonyConfig, *, expected_sha256: str) -> PheromoneField:
    data = Path(path).read_bytes()
    if digest_bytes(data) != expected_sha256:
        raise ValueError("external pheromone field checksum mismatch")
    with np.load(io.BytesIO(data), allow_pickle=False) as arrays:
        intensity = np.asarray(arrays["intensity"]).copy()
        direction_sum = np.asarray(arrays["direction_sum"]).copy()
    field = PheromoneField(config.arena_size, config.pheromone,
                           food_position=np.asarray(config.food.center, dtype=float))
    if intensity.shape != field.intensity.shape or direction_sum.shape != field.direction_sum.shape:
        raise ValueError("external pheromone field shape mismatch")
    if (not np.isfinite(intensity).all() or not np.isfinite(direction_sum).all()
            or np.any(intensity < 0.0)):
        raise ValueError("external pheromone field contains invalid values")
    field.intensity = intensity
    field.direction_sum = direction_sum
    return field


def _compact_state(simulation: StreamingSimulation, *, external_field: bool = False) -> dict:
    state = dict(vars(simulation))
    for name in HISTORY_ATTRIBUTES | {"config", "environment", "turn_schedules", "runtime_counters"}:
        state.pop(name, None)
    if external_field:
        state.pop("field", None)
    return state


def checkpoint_bytes_from_state(state: dict, metadata: dict, *, completed: bool = False) -> bytes:
    """Stable, lossless ZIP; only completed checkpoints pay the LZMA cost.

    Member payloads, hashes and schema are identical to the DEFLATE format.
    ZIP member headers identify the compression method to the common reader.
    """
    codec = StateCodec()
    packed = codec.pack(state)
    complete = dict(metadata, state=packed,
                    array_hashes={name: digest_bytes(data) for name, data in codec.arrays.items()})
    return _archive_bytes(complete, codec.arrays,
                          compression=zipfile.ZIP_LZMA if completed else zipfile.ZIP_DEFLATED)


def save_checkpoint(path: Path, simulation: StreamingSimulation, identity: dict, *,
                    shared_artifact: Path | None = None,
                    history_manifest: Path | None = None,
                    initial: dict | None = None,
                    external_field: Path | None = None,
                    completed: bool = False) -> str:
    if simulation._observing_ant is not None or simulation._observed_decision is not None:
        raise ValueError("checkpoint only at a complete step boundary")
    simulation._assert_invariants()
    compact = shared_artifact is not None or history_manifest is not None
    if compact and (shared_artifact is None or history_manifest is None or initial is None):
        raise ValueError("compact checkpoint requires shared artifact, history manifest and initial identity")
    if completed and (not compact or external_field is None or simulation.time != simulation.config.steps):
        raise ValueError("completed compression requires final state and all retained artifact references")
    path = Path(path)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "storage_layout": "compact_referenced_v2" if compact else "embedded_compatibility_v1",
        "identity": identity if not compact else None,
        "identity_binding": _identity_binding(identity),
        "identity_hash": hash_value(_identity_binding(identity)),
        "config_hash": hash_value(behavioural_config(simulation.config)),
        "seed": simulation.config.seed,
        "rule": simulation.config.follower_direction_rule,
        "time": simulation.time,
    }
    if compact:
        shared_checksum = sha256_file(shared_artifact)
        if initial["turn_schedule_hash"] != turn_schedule_identity(simulation.turn_schedules):
            raise ValueError("live turn schedule differs from shared identity")
        history_checksum = sha256_file(history_manifest)
        metadata.update({
            "initial_identity": initial,
            "shared_artifact": {"reference": _relative_reference(path, shared_artifact),
                                "sha256": shared_checksum},
            "history_manifest": {"reference": _relative_reference(path, history_manifest),
                                 "sha256": history_checksum},
        })
        if external_field is not None:
            metadata["external_field"] = {
                "reference": _relative_reference(path, external_field),
                "sha256": sha256_file(external_field),
            }
        state = _compact_state(simulation, external_field=external_field is not None)
    else:
        state = dict(vars(simulation))
    data = checkpoint_bytes_from_state(state, metadata, completed=completed)
    atomic_write(path, data)
    return digest_bytes(data)


def _read_checkpoint_state(data: bytes, config: ColonyConfig, identity: dict,
                           *, expected_sha256: str | None = None) -> tuple[dict, dict]:
    """Common verified decoder for DEFLATE/LZMA and storage-only timing."""
    if expected_sha256 is not None and digest_bytes(data) != expected_sha256:
        raise ValueError("checkpoint checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 1_000_000_000:
            raise ValueError("checkpoint expands beyond the local format bound")
        metadata = json.loads(archive.read("metadata.json"),
                              parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if metadata["schema_version"] != SCHEMA_VERSION:
            raise ValueError("checkpoint schema mismatch")
        compact = metadata.get("storage_layout") == "compact_referenced_v2"
        if metadata.get("identity_hash") != hash_value(_identity_binding(identity)):
            raise ValueError("checkpoint code, input or preregistration identity mismatch")
        if not compact and metadata.get("identity") != identity:
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
        return metadata, codec.unpack(metadata["state"])


def load_checkpoint(path: Path, config: ColonyConfig, identity: dict,
                    *, expected_sha256: str | None = None,
                    shared_artifact: Path | None = None,
                    history_manifest: Path | None = None) -> StreamingSimulation:
    path = Path(path)
    metadata, state = _read_checkpoint_state(
        path.read_bytes(), config, identity, expected_sha256=expected_sha256)
    compact = metadata.get("storage_layout") == "compact_referenced_v2"
    restored = object.__new__(StreamingSimulation)
    restored.__dict__.update(state)
    if compact:
        shared_artifact = Path(shared_artifact) if shared_artifact is not None else _resolve_reference(
            path, metadata["shared_artifact"]["reference"])
        history_manifest = Path(history_manifest) if history_manifest is not None else _resolve_reference(
            path, metadata["history_manifest"]["reference"])
        shared = load_shared_seed_artifact(
            shared_artifact, config, identity,
            expected_sha256=metadata["shared_artifact"]["sha256"])
        if shared["initial_identity"] != metadata["initial_identity"]:
            raise ValueError("checkpoint shared initial identity mismatch")
        restored.config = config
        restored.environment = SquareEnvironment(config.arena_size)
        restored.turn_schedules = np.asarray(shared["turn_schedules"]).copy()
        if "external_field" in metadata:
            field_path = _resolve_reference(path, metadata["external_field"]["reference"])
            restored.field = load_field_artifact(
                field_path, config, expected_sha256=metadata["external_field"]["sha256"])
        restored.runtime_counters = {"elapsed_seconds": 0.0, "checkpoint_seconds": 0.0,
                                     "checkpoint_count": 0, "peak_storage_bytes": 0}
        restored._observing_ant = None
        restored._observed_decision = None
        HistoryStore(history_manifest.parent.parent).restore(
            restored, history_manifest,
            expected_sha256=metadata["history_manifest"]["sha256"])
    if behavioural_config(restored.config) != behavioural_config(config) or restored.time != metadata["time"]:
        raise ValueError("checkpoint state/config mismatch")
    restored.config = config  # Administrative output routing may differ.
    restored._assert_invariants()
    if len(restored._metric_rows) != restored.time + 1 or len(restored.role_rows) != restored.time + 1:
        raise ValueError("checkpoint metric timeline mismatch")
    if restored._metric_rows[-1]["cumulative_deliveries"] != restored.cumulative_deliveries:
        raise ValueError("checkpoint delivery counter mismatch")
    return restored


def _storage_fixture_state(config: ColonyConfig, ants: list[Ant], field: PheromoneField,
                           *, time_step: int) -> dict:
    return {
        "late_window": (9000, 10000),
        "axis_angle": float(np.pi / 4),
        "sensing_steps": int(time_step * config.n_ants),
        "hit_count": int(time_step * config.n_ants // 2),
        "miss_count": int(time_step * config.n_ants - time_step * config.n_ants // 2),
        "hit_axis_sum": float(time_step),
        "continuity_sum": float(time_step / 2),
        "continuity_count": int(time_step * config.n_ants // 3),
        "previous_sensing": {ant.ant_id: (time_step - 1, True, ant.heading) for ant in ants},
        "_observing_ant": None,
        "_observed_decision": None,
        "active_transport": {
            ant.ant_id: {"ant_id": ant.ant_id, "start_time": 0,
                         "departure": ant.travel_path[0].copy(),
                         "distance": float(time_step * config.movement.step_size)}
            for ant in ants
        },
        "first_recruitment_time": 1,
        "late_sums": {"phi": 100.0, "psi": 100.0,
                      "follower_phi": 100.0, "follower_psi": 100.0},
        "late_count": 1001,
        "follower_late_count": 1001,
        "follower_sufficient_count": 1001,
        "rng_state": {"policy": "frozen_pre_generated_turn_schedules",
                      "seed": int(config.seed), "live_generator_state": None},
        "ants": ants,
        "field": field,
        "time": int(time_step),
        "cumulative_deliveries": int(time_step),
        "first_food_discovery_time": 1,
        "first_delivery_time": 2,
        "transition_counts": {
            "forager_to_transporter": int(time_step),
            "forager_to_follower": int(time_step),
            "transporter_to_follower": int(time_step),
            "follower_to_transporter": int(time_step),
        },
    }


def storage_only_measurement(config: ColonyConfig, identity: dict, directory: Path) -> dict:
    """Serialise full-shape non-scientific fixtures without advancing one step."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fixture = replace(config, seed=STORAGE_FIXTURE_SEED,
                      output_dir=str(directory / "not-scientific"))
    fixture_identity = {}
    for key, value in _identity_binding(identity).items():
        length = len(str(value))
        token = digest_bytes(("stage2c-storage-fixture-" + key).encode())
        fixture_identity[key] = (token * (length // len(token) + 1))[:length]
    nest = np.asarray(fixture.nest.center, dtype=float)
    headings = initial_headings(fixture)
    ants = [Ant(index, nest.copy(), float(headings[index]), Role.FORAGER,
                travel_path=[nest.copy()]) for index in range(fixture.n_ants)]
    schedules = build_turn_schedules(fixture)
    surrogate = SimpleNamespace(
        time=0, ants=ants, turn_schedules=schedules, config=fixture,
        rng_state={"policy": "frozen_pre_generated_turn_schedules",
                   "seed": STORAGE_FIXTURE_SEED, "live_generator_state": None})
    shared_path = directory / "shared_seed_artifact.zip"
    shared_sha, initial = save_shared_seed_artifact(shared_path, surrogate, fixture_identity)

    blank_manifest = {
        "schema_version": 1, "format": "incremental_json_chunks",
        "generation": 1, "time": 0,
        "streams": {name: [] for name in (
            "metrics", "agent_states", "events", "role_specific_observations",
            "completed_transport")},
        "counts": {name: 0 for name in (
            "metrics", "agent_states", "events", "role_specific_observations",
            "completed_transport")},
        "columns": {name: [] for name in (
            "metrics", "agent_states", "events", "role_specific_observations",
            "completed_transport")},
        "pheromone_snapshots": [],
    }
    manifest_data = canonical_json_bytes(blank_manifest)
    manifest_path = directory / "history" / "manifests" / "history-00000001.json"
    atomic_write(manifest_path, manifest_data, replace=False)

    initial_field = PheromoneField(
        fixture.arena_size, fixture.pheromone,
        food_position=np.asarray(fixture.food.center, dtype=float))
    initial_state = _storage_fixture_state(fixture, [ant.clone() for ant in ants],
                                           initial_field, time_step=0)
    base_metadata = {
        "schema_version": SCHEMA_VERSION,
        "storage_layout": "compact_referenced_v2",
        "identity": None,
        "identity_binding": _identity_binding(fixture_identity),
        "identity_hash": hash_value(_identity_binding(fixture_identity)),
        "config_hash": hash_value(behavioural_config(fixture)),
        "seed": fixture.seed,
        "rule": fixture.follower_direction_rule,
        "time": 0,
        "initial_identity": initial,
        "shared_artifact": {"reference": "shared_seed_artifact.zip", "sha256": shared_sha},
        "history_manifest": {"reference": "history/manifests/history-00000001.json",
                             "sha256": digest_bytes(manifest_data)},
    }
    initial_checkpoint = checkpoint_bytes_from_state(initial_state, base_metadata)

    # A deliberately non-zero, high-entropy bounded random-walk fixture avoids
    # using easy all-zero compression as evidence for active-state size.
    rng = np.random.Generator(np.random.PCG64(STORAGE_FIXTURE_SEED + 1))
    maximal_ants = []
    total_path_points = 0
    total_route_points = 0
    for ant in ants:
        angles = rng.uniform(-np.pi, np.pi, fixture.steps)
        increments = fixture.movement.step_size * np.column_stack((np.cos(angles), np.sin(angles)))
        raw = nest + np.vstack((np.zeros((1, 2)), np.cumsum(increments, axis=0)))
        folded = np.mod(raw, 2.0 * fixture.arena_size)
        path = np.where(folded <= fixture.arena_size, folded,
                        2.0 * fixture.arena_size - folded)
        route = path[::fixture.memory_stride][::-1].copy()
        maximal_ant = Ant(
            ant.ant_id, path[-1], float(angles[-1]), Role.TRANSPORTER,
            return_waypoints=route, return_waypoint_index=1,
            movement_cursor=fixture.steps, last_path_distance=fixture.movement.step_size,
            last_displacement=fixture.movement.step_size)
        # Storage codec accepts the same dense numeric content without creating
        # a million tiny Python array objects for this non-executed fixture.
        maximal_ant.travel_path = path
        maximal_ants.append(maximal_ant)
        total_path_points += len(path)
        total_route_points += len(route)
    maximal_field = PheromoneField(
        fixture.arena_size, fixture.pheromone,
        food_position=np.asarray(fixture.food.center, dtype=float))
    maximal_field.intensity = rng.uniform(0.1, 1000.0, maximal_field.intensity.shape)
    maximal_field.direction_sum = rng.normal(size=maximal_field.direction_sum.shape)
    maximal_state = _storage_fixture_state(
        fixture, maximal_ants, maximal_field, time_step=fixture.steps)
    active_metadata = dict(base_metadata, time=fixture.steps)
    active_checkpoint = checkpoint_bytes_from_state(maximal_state, active_metadata)
    final_field = deterministic_npz_bytes({
        "intensity": maximal_field.intensity,
        "direction_sum": maximal_field.direction_sum})
    final_metadata = dict(active_metadata, external_field={
        "reference": "final_pheromone.npz", "sha256": digest_bytes(final_field)})
    final_state = dict(maximal_state)
    final_state.pop("field")
    # Both formats use the same production writer/verified decoder. The fixture
    # has no scientific timeline, so time only archive decoding, not simulation
    # restoration or endpoint calculation. Reference restoration is tested with
    # bounded engineering runs separately.
    timings = {}
    checkpoints = {}
    for name, completed in (("legacy_deflate", False), ("completed_lzma", True)):
        started = time.perf_counter()
        data = checkpoint_bytes_from_state(final_state, final_metadata, completed=completed)
        timings[name + "_encode_seconds"] = time.perf_counter() - started
        checksum = digest_bytes(data)
        started = time.perf_counter()
        _, decoded_state = _read_checkpoint_state(
            data, fixture, fixture_identity, expected_sha256=checksum)
        timings[name + "_read_seconds"] = time.perf_counter() - started
        if ant_state_identity(decoded_state["ants"]) != ant_state_identity(maximal_ants):
            raise ValueError("storage fixture ant state did not round trip losslessly")
        checkpoints[name] = data
    final_checkpoint = checkpoints["completed_lzma"]
    with zipfile.ZipFile(io.BytesIO(checkpoints["legacy_deflate"])) as old_archive, \
            zipfile.ZipFile(io.BytesIO(final_checkpoint)) as new_archive:
        if old_archive.namelist() != new_archive.namelist() or any(
                old_archive.read(name) != new_archive.read(name) for name in old_archive.namelist()):
            raise ValueError("completed compression changed checkpoint member content")
        member_sizes = [{"name": item.filename, "raw_bytes": item.file_size,
                         "legacy_deflate_bytes": old_archive.getinfo(item.filename).compress_size,
                         "completed_lzma_bytes": item.compress_size}
                        for item in new_archive.infolist()]

    uncompressed = {
        "turn_schedule": int(schedules.nbytes),
        "travel_paths": int(total_path_points * 2 * 8),
        "return_routes": int(total_route_points * 2 * 8),
        "pheromone_intensity_and_direction": int(
            maximal_field.intensity.nbytes + maximal_field.direction_sum.nbytes),
    }
    return {
        "measurement_status": "storage_only_measured_non_scientific_fixture",
        "simulation_steps_executed": 0,
        "scientific_seed_used": False,
        "storage_fixture_seed": STORAGE_FIXTURE_SEED,
        "identity_fixture": "fixed_non-secret_hash-shaped_values_for_stable_size_measurement",
        "compression_credit_assumed": False,
        "shared_seed_artifact_bytes": shared_path.stat().st_size,
        "history_manifest_bytes": len(manifest_data),
        "initial_checkpoint_bytes": len(initial_checkpoint),
        "synthetic_max_active_checkpoint_bytes": len(active_checkpoint),
        "synthetic_max_completed_checkpoint_bytes": len(final_checkpoint),
        "legacy_completed_checkpoint_bytes": len(checkpoints["legacy_deflate"]),
        "completed_checkpoint_compression": "deterministic_zip_lzma",
        "completed_checkpoint_members": member_sizes,
        "completed_checkpoint_timing": dict(timings,
            read_scope="whole_archive_sha256_metadata_identity_array_hashes_and_state_decode",
            allowance_seconds=timings["completed_lzma_encode_seconds"]
                              + timings["completed_lzma_read_seconds"]),
        "completed_checkpoint_members_byte_exact": True,
        "completed_fixture_arrays_all_nonzero": all(
            np.all(ant.travel_path != 0) and np.all(ant.return_waypoints != 0)
            for ant in maximal_ants) and bool(np.all(maximal_field.intensity != 0))
            and bool(np.all(maximal_field.direction_sum != 0)),
        "synthetic_dense_final_field_bytes": len(final_field),
        "active_checkpoint_overlap_bytes": 2 * len(active_checkpoint),
        "uncompressed_numeric_bytes": uncompressed,
        "assumptions": [
            "fixture uses the paper-scale shapes but a non-registered seed",
            "every ant carries a full non-zero random-walk path and one-third return route",
            "the pheromone intensity and direction arrays are dense non-zero random values",
            "hash-shaped identity fixture values preserve production field lengths without depending on the current source hash",
            "measured ZIP sizes are reported, but the projection does not claim a future compression ratio",
            "no ant dynamics step, pilot, full run or scientific metric was executed",
        ],
    }
