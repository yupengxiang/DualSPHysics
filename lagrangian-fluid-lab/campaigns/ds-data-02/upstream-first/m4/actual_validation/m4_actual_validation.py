#!/usr/bin/env python3
"""Prepare and run an actual M4 relocation and artifact-negative audit.

This worker is deliberately downstream of the frozen M4 producer.  It accepts
an actual completed enrichment receipt and a completed portable bundle, copies
the bundle into a fresh NAS attempt directory, and invokes the existing
``m4_isolated_validate.py`` wrapper.  The wrapper masks the original source
paths and runs the adapter copied into the relocated bundle.

Two semantic negatives are then run one at a time against a bounded private
copy of that relocated bundle:

* an endpoint ``particle_zone`` value is changed while the root typed axis is
  left unchanged;
* one valid endpoint destination coordinate is changed while displacement is
  left unchanged.

Each private copy rehashes its HDF5, interface, reader manifest, and bundle
manifest bindings before the bundled production validator is invoked.  A
digest-only validator therefore cannot make either mutation pass.  The source
bundle is read-only throughout and every private copy is removed after its
report is written.  This module never starts a solver, decoder, or converter.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np


M4_ROOT = Path(__file__).resolve().parents[1]
if str(M4_ROOT) not in sys.path:
    sys.path.insert(0, str(M4_ROOT))

import m4_portable_adapter as portable  # noqa: E402


SCHEMA = "ds-data-02.m4.actual-validation.v1"
REQUEST_SCHEMA = "ds-data-02.runner.request.v1"
ENRICHMENT_RECEIPT_SCHEMA = "ds-data-02.m4.direct-enrichment-receipt.v1"
BUNDLE_RECEIPT_SCHEMA = "ds-data-02.m4.actual-source-bundle-receipt.v1"
BUNDLE_SCHEMA = "ds-data-02.m4.portable-bundle.v1"
CHUNK_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_WALL_SECONDS = 3600.0
DEFAULT_HEADROOM_BYTES = 256 * 1024 * 1024

NEGATIVES: tuple[dict[str, str], ...] = (
    {
        "name": "typed_identity_endpoint_label",
        "dataset_role": "particle_zone_dataset",
        "expected_error": "endpoint identity labels changed the initial typed axis",
        "purpose": "rehashed endpoint Zone identity must still match the root (Zone,Idp) axis",
    },
    {
        "name": "destination_position",
        "dataset_role": "destination_position_dataset",
        "expected_error": "displacement is not the keyed source-to-destination difference",
        "purpose": "rehashed destination coordinates must remain consistent with displacement",
    },
)


class ActualValidationError(RuntimeError):
    """Raised when an actual M4 relocation or semantic negative is unsafe."""


def _deadline(max_wall_seconds: float) -> float:
    if not isinstance(max_wall_seconds, (int, float)) or max_wall_seconds <= 0:
        raise ActualValidationError("max-wall-seconds must be positive")
    return time.monotonic() + float(max_wall_seconds)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ActualValidationError("M4 actual-validation wall limit exceeded")


def _sha256(path: Path, *, deadline: float | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            if deadline is not None:
                _check_deadline(deadline)
            block = stream.read(CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise ActualValidationError(f"{label} is a symlink: {raw}")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise ActualValidationError(f"{label} is not a regular file: {resolved}")
    return resolved


def _directory(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise ActualValidationError(f"{label} is a symlink: {raw}")
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise ActualValidationError(f"{label} is not a regular directory: {resolved}")
    return resolved


def _load_json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActualValidationError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ActualValidationError(f"{label} must be a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ActualValidationError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + f".partial-{os.getpid()}")
    if partial.exists() or partial.is_symlink():
        raise ActualValidationError(f"stale partial report exists: {partial}")
    try:
        with partial.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _rewrite_json(path: Path, value: Mapping[str, Any]) -> None:
    path = _regular(path, f"mutable JSON artifact {path.name}")
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise ActualValidationError(f"stale partial JSON artifact exists: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _binding(path: Path, *, relative: str | None = None, deadline: float | None = None) -> dict[str, Any]:
    path = _regular(path, "artifact")
    return {
        "path": relative or str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path, deadline=deadline),
    }


def _resolve_binding(value: Any, *, base: Path, label: str, deadline: float | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ActualValidationError(f"{label} is not an artifact binding")
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ActualValidationError(f"{label}.path is missing")
    path = Path(raw_path)
    if not path.is_absolute():
        path = base / path
    actual = _binding(path, deadline=deadline)
    if type(value.get("bytes")) is not int or value["bytes"] != actual["bytes"]:
        raise ActualValidationError(f"{label}.bytes does not match {path}")
    if value.get("sha256") != actual["sha256"]:
        raise ActualValidationError(f"{label}.sha256 does not match {path}")
    return {"path": str(path), "bytes": actual["bytes"], "sha256": actual["sha256"]}


def _walk_regular_files(root: Path, *, deadline: float) -> list[tuple[Path, int, str]]:
    root = _directory(root, "source bundle")
    records: list[tuple[Path, int, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        _check_deadline(deadline)
        current_path = Path(current)
        for name in sorted(directories):
            directory = current_path / name
            if directory.is_symlink() or not directory.is_dir():
                raise ActualValidationError(f"bundle contains a non-directory entry: {directory}")
        for name in sorted(files):
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise ActualValidationError(f"bundle contains a non-regular entry: {path}")
            records.append((path, path.stat().st_size, _sha256(path, deadline=deadline)))
    records.sort(key=lambda row: row[0].relative_to(root).as_posix())
    if not records:
        raise ActualValidationError(f"source bundle is empty: {root}")
    return records


def _validate_manifest_bindings(
    root: Path,
    records: Sequence[tuple[Path, int, str]],
    *,
    deadline: float,
) -> dict[str, Any]:
    manifest_path = _regular(root / "manifest.json", "bundle manifest")
    manifest = _load_json(manifest_path, "bundle manifest")
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise ActualValidationError(f"unsupported source bundle schema: {manifest.get('schema')!r}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ActualValidationError("source bundle has no artifact bindings")
    record_map = {path.relative_to(root).as_posix(): (path, size, digest) for path, size, digest in records}
    for name, value in artifacts.items():
        if not isinstance(value, Mapping):
            raise ActualValidationError(f"bundle artifact {name!r} is not an object")
        relative = value.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ActualValidationError(f"bundle artifact {name!r} has an unsafe path")
        if relative not in record_map:
            raise ActualValidationError(f"bundle artifact {name!r} is absent: {relative}")
        path, size, digest = record_map[relative]
        if value.get("bytes") != size or value.get("sha256") != digest:
            raise ActualValidationError(f"bundle artifact {name!r} does not match {relative}")
    return manifest


def _source_receipt(receipt_path: Path, *, case_id: str, deadline: float) -> dict[str, Any]:
    receipt_path = _regular(receipt_path, "completed source receipt")
    receipt = _load_json(receipt_path, "completed source receipt")
    if receipt.get("schema") not in {ENRICHMENT_RECEIPT_SCHEMA, BUNDLE_RECEIPT_SCHEMA}:
        raise ActualValidationError(f"unsupported source completion receipt: {receipt.get('schema')!r}")
    if receipt.get("status") != "completed":
        raise ActualValidationError("source completion receipt is not completed")
    if receipt.get("case_id") != case_id:
        raise ActualValidationError("source completion receipt case_id disagrees with bundle")
    if receipt.get("credit_status") not in (None, "not_credited"):
        raise ActualValidationError("source completion receipt grants unapproved credit")
    if receipt.get("physical_fate_inferred") not in (None, False):
        raise ActualValidationError("source completion receipt infers physical fate")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, Mapping):
        outputs = receipt.get("artifacts")
    if not isinstance(outputs, Mapping):
        raise ActualValidationError("source completion receipt lacks output bindings")
    required = ("interface", "enriched_hdf5")
    for key in required:
        if key not in outputs:
            raise ActualValidationError(f"source completion receipt lacks outputs.{key}")
        _resolve_binding(outputs[key], base=receipt_path.parent, label=f"source receipt outputs.{key}", deadline=deadline)
    return {
        "path": str(receipt_path),
        "bytes": receipt_path.stat().st_size,
        "sha256": _sha256(receipt_path, deadline=deadline),
        "schema": receipt["schema"],
        "status": receipt["status"],
        "case_id": case_id,
        "outputs": {
            key: _resolve_binding(outputs[key], base=receipt_path.parent, label=f"source receipt outputs.{key}", deadline=deadline)
            for key in required
        },
    }


def _bundle_source(source: Path, *, deadline: float) -> tuple[dict[str, Any], list[tuple[Path, int, str]], dict[str, Any]]:
    source = _directory(source, "source bundle")
    records = _walk_regular_files(source, deadline=deadline)
    manifest = _validate_manifest_bindings(source, records, deadline=deadline)
    try:
        checked = portable.validate_bundle(source, run_semantic_negatives=True)
    except (portable.M4Error, OSError, ValueError, KeyError) as exc:
        raise ActualValidationError(f"source portable bundle failed production validation: {exc}") from exc
    if checked.get("portable") is not True or checked.get("source_paths_redacted") is not True:
        raise ActualValidationError("source portable bundle did not pass the production portability contract")
    return manifest, records, checked


def _copy_file(source: Path, destination: Path, *, expected_size: int, expected_hash: str, deadline: float) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    digest = hashlib.sha256()
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        while True:
            _check_deadline(deadline)
            block = input_stream.read(CHUNK_BYTES)
            if not block:
                break
            output_stream.write(block)
            digest.update(block)
            copied += len(block)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    if copied != expected_size or digest.hexdigest() != expected_hash:
        raise ActualValidationError(f"source changed during copy: {source}")
    shutil.copystat(source, destination, follow_symlinks=False)
    return copied


def _copy_bundle(
    source: Path,
    destination: Path,
    records: Sequence[tuple[Path, int, str]],
    *,
    max_bytes: int,
    deadline: float,
) -> dict[str, Any]:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ActualValidationError("max-bytes must be a positive integer")
    total = sum(size for _, size, _ in records)
    if total > max_bytes:
        raise ActualValidationError(f"bundle bytes {total} exceed max-bytes {max_bytes}")
    source = source.resolve()
    destination = destination.absolute()
    if destination == source or destination.is_relative_to(source):
        raise ActualValidationError("destination must be outside the immutable source bundle")
    if destination.exists() or destination.is_symlink():
        raise ActualValidationError(f"fresh destination is required: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise ActualValidationError(f"stale relocation partial exists: {temporary}")
    temporary.mkdir()
    copied_bytes = 0
    try:
        for path, size, digest in records:
            _check_deadline(deadline)
            copied_bytes += _copy_file(path, temporary / path.relative_to(source), expected_size=size, expected_hash=digest, deadline=deadline)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "source_bundle": str(source),
        "destination_bundle": str(destination),
        "file_count": len(records),
        "bytes": copied_bytes,
        "copy_mode": "full_regular_file_copy",
    }


def _load_module(path: Path, name: str) -> Any:
    path = _regular(path, name)
    spec = importlib.util.spec_from_file_location(f"m4_actual_validation_{name}", path)
    if spec is None or spec.loader is None:
        raise ActualValidationError(f"cannot load {name}: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_isolated_replay(
    *,
    wrapper_path: Path,
    relocated_bundle: Path,
    python_path: Path,
    output: Path,
    denied_paths: Sequence[Path],
    mask_paths: Sequence[Path],
    max_wall_seconds: float,
) -> dict[str, Any]:
    python_path = python_path.expanduser().absolute()
    if not python_path.is_file():
        raise ActualValidationError(f"Python runtime is not a regular file: {python_path}")
    wrapper = _load_module(wrapper_path, "m4_isolated_validate")
    old_masks = tuple(getattr(wrapper, "DEFAULT_MASK_PATHS", ()))
    merged_masks = list(old_masks)
    for path in mask_paths:
        path = path.expanduser().absolute()
        # The existing wrapper always masks /tmp.  Adding a nested mount after
        # that tmpfs would fail because the nested source path no longer
        # exists inside the namespace.
        if path == Path("/tmp") or path.is_relative_to(Path("/tmp")):
            continue
        if not any(path == existing or path.is_relative_to(existing) for existing in merged_masks):
            merged_masks.append(path)
    wrapper.DEFAULT_MASK_PATHS = tuple(merged_masks)
    args = argparse.Namespace(
        bundle_root=relocated_bundle,
        python=python_path,
        output=output,
        max_wall_seconds=max_wall_seconds,
        denied_path=[str(path) for path in denied_paths],
    )
    try:
        result = wrapper._run(args)
    except Exception as exc:
        raise ActualValidationError(f"isolated M4 relocation replay failed: {exc}") from exc
    finally:
        wrapper.DEFAULT_MASK_PATHS = old_masks
    _write_json(output, result)
    return result


def _invoke_bundled_validator(case_root: Path, *, python_path: Path, deadline: float) -> dict[str, Any]:
    validator = _regular(case_root / "runtime" / "m4_portable_adapter.py", "bundled production validator")
    remaining = max(1.0, deadline - time.monotonic())
    command = [str(python_path), str(validator), "validate", "--bundle-root", str(case_root)]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        raise ActualValidationError("bundled production validator exceeded the wall limit") from exc
    return {
        "argv": command,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout.strip()[-4000:],
        "stderr_tail": completed.stderr.strip()[-4000:],
        "validator_sha256": _sha256(validator, deadline=deadline),
    }


def _write_rehashed_bindings(case_root: Path, *, deadline: float) -> dict[str, Any]:
    interface_path = _regular(case_root / "interface.json", "copied interface")
    manifest_path = _regular(case_root / "manifest.json", "copied manifest")
    reader_path = _regular(case_root / "reader-manifest.json", "copied reader manifest")
    interface = _load_json(interface_path, "copied interface")
    normalized = interface.get("normalized_hdf5")
    if not isinstance(normalized, Mapping) or normalized.get("path") != "normalized.h5":
        raise ActualValidationError("copied interface does not bind normalized.h5")
    normalized_path = _regular(case_root / "normalized.h5", "copied normalized HDF5")
    normalized_binding = _binding(normalized_path, relative="normalized.h5", deadline=deadline)
    interface["normalized_hdf5"] = normalized_binding
    _rewrite_json(interface_path, interface)
    interface_binding = _binding(interface_path, relative="interface.json", deadline=deadline)

    reader = _load_json(reader_path, "copied reader manifest")
    cases = reader.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], dict):
        raise ActualValidationError("copied reader manifest lacks one case")
    cases[0]["hdf5"] = "normalized.h5"
    cases[0]["bytes"] = normalized_binding["bytes"]
    cases[0]["sha256"] = normalized_binding["sha256"]
    _rewrite_json(reader_path, reader)
    reader_binding = _binding(reader_path, relative="reader-manifest.json", deadline=deadline)

    manifest = _load_json(manifest_path, "copied manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ActualValidationError("copied manifest lacks artifacts")
    for key, binding in (
        ("normalized_hdf5", normalized_binding),
        ("interface", interface_binding),
        ("reader_manifest", reader_binding),
    ):
        if key not in artifacts:
            raise ActualValidationError(f"copied manifest lacks {key} artifact")
        artifacts[key] = binding
    _rewrite_json(manifest_path, manifest)
    return {
        "normalized_hdf5": normalized_binding,
        "interface": interface_binding,
        "reader_manifest": reader_binding,
        "manifest_sha256": _sha256(manifest_path, deadline=deadline),
    }


def _integer_mutation(dataset: h5py.Dataset, index: int) -> tuple[int, int]:
    old = int(dataset[index])
    if dataset.dtype.kind not in "iu":
        raise ActualValidationError("typed endpoint identity dataset is not integer-valued")
    limits = np.iinfo(dataset.dtype)
    new = old + 1 if old < int(limits.max) else old - 1
    if new == old or new < int(limits.min) or new > int(limits.max):
        raise ActualValidationError("typed endpoint identity cannot be changed within its dtype")
    dataset[index] = new
    return old, new


def _tamper_artifact(case_root: Path, name: str, *, deadline: float) -> dict[str, Any]:
    interface = _load_json(case_root / "interface.json", "tamper interface")
    endpoints = interface.get("endpoint_transport")
    if not isinstance(endpoints, Mapping):
        raise ActualValidationError("tamper interface lacks endpoint_transport")
    hdf5_path = _regular(case_root / "normalized.h5", "tamper normalized HDF5")
    if name == "typed_identity_endpoint_label":
        zone_path = endpoints.get("particle_zone_dataset")
        if not isinstance(zone_path, str):
            raise ActualValidationError("tamper interface lacks particle_zone_dataset")
        index = 0
        with h5py.File(hdf5_path, "r+") as handle:
            try:
                dataset = handle[zone_path]
            except KeyError as exc:
                raise ActualValidationError(f"missing endpoint zone dataset: {zone_path}") from exc
            if not isinstance(dataset, h5py.Dataset) or dataset.ndim != 1 or dataset.shape[0] == 0:
                raise ActualValidationError("endpoint zone dataset is empty or malformed")
            old, new = _integer_mutation(dataset, index)
            handle.flush()
        rehashed = _write_rehashed_bindings(case_root, deadline=deadline)
        return {
            "name": name,
            "dataset": zone_path,
            "index": index,
            "old": old,
            "new": new,
            "semantic_target": "endpoint typed (Zone,Idp) identity",
            "rehashed": rehashed,
        }
    if name == "destination_position":
        valid_path = endpoints.get("destination_valid_dataset")
        position_path = endpoints.get("destination_position_dataset")
        if not isinstance(valid_path, str) or not isinstance(position_path, str):
            raise ActualValidationError("tamper interface lacks destination endpoint datasets")
        with h5py.File(hdf5_path, "r+") as handle:
            try:
                valid = np.asarray(handle[valid_path][:], dtype=bool)
                dataset = handle[position_path]
            except KeyError as exc:
                raise ActualValidationError("destination endpoint dataset is missing") from exc
            if not isinstance(dataset, h5py.Dataset) or dataset.shape != (len(valid), 3):
                raise ActualValidationError("destination position dataset has an unexpected shape")
            values = np.asarray(dataset[:], dtype=np.float64)
            candidates = np.flatnonzero(valid & np.isfinite(values).all(axis=1))
            if len(candidates) == 0:
                raise ActualValidationError("actual product has no valid destination endpoint to tamper")
            index = int(candidates[0])
            old = values[index].copy()
            new = old.copy()
            new[0] += 0.125
            if not np.isfinite(new).all() or np.array_equal(old, new):
                raise ActualValidationError("destination position mutation did not change finite data")
            dataset[index] = new.astype(dataset.dtype, copy=False)
            handle.flush()
        rehashed = _write_rehashed_bindings(case_root, deadline=deadline)
        return {
            "name": name,
            "dataset": position_path,
            "index": index,
            "old": old.tolist(),
            "new": new.tolist(),
            "semantic_target": "valid destination position/displacement consistency",
            "rehashed": rehashed,
        }
    raise ActualValidationError(f"unsupported tamper case: {name}")


def _copy_private_bundle(
    source: Path,
    destination: Path,
    records: Sequence[tuple[Path, int, str]],
    *,
    max_bytes: int,
    deadline: float,
) -> int:
    total = sum(size for _, size, _ in records)
    if total > max_bytes:
        raise ActualValidationError(f"private tamper copy bytes {total} exceed max-bytes {max_bytes}")
    if destination.exists() or destination.is_symlink():
        raise ActualValidationError(f"fresh private tamper destination is required: {destination}")
    destination.mkdir(parents=True)
    copied = 0
    try:
        for path, size, digest in records:
            _check_deadline(deadline)
            copied += _copy_file(path, destination / path.relative_to(source), expected_size=size, expected_hash=digest, deadline=deadline)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return copied


def _snapshot_against_records(records: Sequence[tuple[Path, int, str]], *, deadline: float) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path, expected_size, expected_hash in records:
        _check_deadline(deadline)
        actual_size = path.stat().st_size
        actual_hash = _sha256(path, deadline=deadline)
        result[str(path)] = {"bytes": actual_size, "sha256": actual_hash, "matches": actual_size == expected_size and actual_hash == expected_hash}
    return result


def run_actual_validation(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    source = _directory(Path(args.source_bundle), "source bundle")
    receipt_path = _regular(Path(args.source_receipt), "completed source receipt")
    relocated = Path(args.relocated_bundle).expanduser().absolute()
    output = Path(args.output).expanduser().absolute()
    if relocated == source or relocated.is_relative_to(source):
        raise ActualValidationError("relocated bundle must be outside the immutable source bundle")
    if output == source or output.is_relative_to(source):
        raise ActualValidationError("validation output must be outside the immutable source bundle")
    if relocated.exists() or relocated.is_symlink():
        raise ActualValidationError(f"fresh relocated bundle is required: {relocated}")
    if output.exists() or output.is_symlink():
        raise ActualValidationError(f"fresh validation output is required: {output}")
    deadline = _deadline(args.max_wall_seconds)
    manifest, records, source_validation = _bundle_source(source, deadline=deadline)
    interface_path = _regular(source / "interface.json", "source interface")
    interface = _load_json(interface_path, "source interface")
    case_id = interface.get("case_id")
    if not isinstance(case_id, str):
        raise ActualValidationError("source interface lacks case_id")
    completion = _source_receipt(receipt_path, case_id=case_id, deadline=deadline)
    source_snapshot = _snapshot_against_records(records, deadline=deadline)
    relocation = _copy_bundle(source, relocated, records, max_bytes=args.max_bytes, deadline=deadline)
    output.mkdir(parents=True)
    isolated_path = output / "relocated-isolated-validation.json"
    denied_paths = [source, receipt_path.parent]
    isolated = _run_isolated_replay(
        wrapper_path=Path(args.isolation_wrapper),
        relocated_bundle=relocated,
        python_path=Path(args.python),
        output=isolated_path,
        denied_paths=denied_paths,
        mask_paths=denied_paths,
        max_wall_seconds=max(1.0, deadline - time.monotonic()),
    )
    scratch = output / "scratch"
    reports = output / "reports"
    scratch.mkdir()
    reports.mkdir()
    rows: list[dict[str, Any]] = []
    try:
        relocated_records = _walk_regular_files(relocated, deadline=deadline)
        _validate_manifest_bindings(relocated, relocated_records, deadline=deadline)
        for negative in NEGATIVES:
            _check_deadline(deadline)
            case_root = scratch / negative["name"]
            copied_bytes = _copy_private_bundle(relocated, case_root, relocated_records, max_bytes=args.max_bytes, deadline=deadline)
            mutation = _tamper_artifact(case_root, negative["name"], deadline=deadline)
            validation = _invoke_bundled_validator(case_root, python_path=Path(args.python).absolute(), deadline=deadline)
            combined = (validation["stderr_tail"] + "\n" + validation["stdout_tail"]).strip()
            if validation["returncode"] == 0:
                raise ActualValidationError(f"production validator accepted tampered {negative['name']} artifact")
            if negative["expected_error"] not in combined:
                raise ActualValidationError(
                    f"tampered {negative['name']} artifact failed for an unexpected reason: {combined[-1200:]}"
                )
            row = {
                "schema": "ds-data-02.m4.actual-semantic-negative.v1",
                "status": "rejected_as_expected",
                "negative": negative["name"],
                "copied_path_bytes": copied_bytes,
                "mutation": mutation,
                "expected_error": negative["expected_error"],
                "production_validator": validation,
                "artifact_layer_rehashed": True,
                "source_bundle_untouched": True,
            }
            _write_json(reports / f"{negative['name']}.json", row)
            rows.append(row)
            shutil.rmtree(case_root)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
    after_snapshot = _snapshot_against_records(records, deadline=deadline)
    if not all(item["matches"] for item in after_snapshot.values()):
        raise ActualValidationError("source portable bundle changed during actual validation")
    final = {
        "schema": SCHEMA,
        "status": "completed",
        "case_id": case_id,
        "source_completion_receipt": completion,
        "source_bundle": {
            "path": str(source),
            "manifest_sha256": _sha256(source / "manifest.json", deadline=deadline),
            "file_count": len(records),
            "bytes": sum(size for _, size, _ in records),
            "production_validation": {
                "portable": source_validation.get("portable"),
                "summary": source_validation.get("summary"),
            },
        },
        "source_snapshot": source_snapshot,
        "source_snapshot_after": after_snapshot,
        "source_unchanged": True,
        "relocation": relocation,
        "isolated_replay": {
            "report": str(isolated_path),
            "schema": isolated.get("schema"),
            "portable": isolated.get("validation", {}).get("portable"),
            "source_paths_redacted": isolated.get("validation", {}).get("source_paths_redacted"),
            "denied_probes_passed": isolated.get("namespace", {}).get("denied_probes_passed"),
            "masked_source_paths": [str(path) for path in denied_paths],
        },
        "semantic_negatives": {
            "count": len(rows),
            "passed": len(rows) == len(NEGATIVES) and all(row["status"] == "rejected_as_expected" for row in rows),
            "reports": [str(reports / f"{row['negative']}.json") for row in rows],
            "scratch_removed_after_each_case": True,
        },
        "production_validator": "bundle/runtime/m4_portable_adapter.py",
        "launches": {"solver": False, "decoder": False, "converter": False},
        "elapsed_seconds": time.monotonic() - started,
    }
    _write_json(output / "actual-validation-receipt.json", final)
    return final


def _template_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActualValidationError(f"{label} is empty")
    path = Path(value)
    if path.is_absolute() or "{attempt_root}" in value:
        return value
    raise ActualValidationError(f"{label} must be an absolute path or use {{attempt_root}}")


def prepare_request(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    source = _directory(Path(args.source_bundle), "source bundle")
    receipt_path = _regular(Path(args.source_receipt), "completed source receipt")
    wrapper = _regular(Path(args.isolation_wrapper), "M4 isolated validation wrapper")
    python_path = Path(args.python).expanduser().absolute()
    if not python_path.is_file():
        raise ActualValidationError(f"Python runtime is not a regular file: {python_path}")
    relocation_template = _template_path(args.relocated_bundle_template, "relocated bundle template")
    output_template = _template_path(args.output_template, "validation output template")
    deadline = _deadline(args.max_wall_seconds)
    manifest, records, checked = _bundle_source(source, deadline=deadline)
    interface = _load_json(source / "interface.json", "source interface")
    case_id = interface.get("case_id")
    if not isinstance(case_id, str) or not case_id.startswith("UF_F1_"):
        raise ActualValidationError("source interface case_id is outside F1")
    completion = _source_receipt(receipt_path, case_id=case_id, deadline=deadline)
    total_bytes = sum(size for _, size, _ in records)
    source_files = [str(path) for path, _, _ in records]
    worker = Path(__file__).resolve()
    input_files = [str(receipt_path), str(source / "manifest.json"), *source_files, str(wrapper), str(python_path), str(worker)]
    deduped_inputs = list(dict.fromkeys(input_files))
    output_request = Path(args.output_request).expanduser().resolve()
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "prepared_after_completed_source_receipt",
        "family_id": "F1",
        "case_id": case_id,
        "attempt_id": "m4-actual-validation-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": args.max_wall_seconds,
        "output_storage": "upstream_nas",
        "worktree_root": str(M4_ROOT.parents[4]),
        "cwd": str(M4_ROOT.parents[4]),
        "requires_completed_source_receipt": True,
        "requires_bubblewrap": True,
        "source_completion_receipt": completion,
        "source_bundle": {
            "path": str(source),
            "manifest_sha256": _sha256(source / "manifest.json", deadline=deadline),
            "file_count": len(records),
            "bytes": total_bytes,
            "production_validation": {
                "portable": checked.get("portable"),
                "source_paths_redacted": checked.get("source_paths_redacted"),
            },
        },
        "command": [
            str(python_path),
            str(worker),
            "run",
            "--source-receipt",
            str(receipt_path),
            "--source-bundle",
            str(source),
            "--relocated-bundle",
            relocation_template,
            "--output",
            output_template,
            "--isolation-wrapper",
            str(wrapper),
            "--python",
            str(python_path),
            "--max-bytes",
            str(total_bytes),
            "--max-wall-seconds",
            str(args.max_wall_seconds),
        ],
        "input_files": deduped_inputs,
        "destination_contract": {
            "relocated_bundle": relocation_template,
            "validation_output": output_template,
            "fresh_second_absolute_nas_attempt_root": "runner substitutes {attempt_root} with a fresh absolute NAS attempt root",
            "source_bundle_is_read_only": True,
        },
        "source_paths_hidden_during_replay": [str(source), str(receipt_path.parent)],
        "tamper_cases": [
            {
                "name": item["name"],
                "dataset_role": item["dataset_role"],
                "expected_error": item["expected_error"],
                "purpose": item["purpose"],
                "copy_policy": "one bounded private full-bundle copy at a time; delete before next case",
                "rehash_policy": "normalized HDF5, interface, reader-manifest, and bundle-manifest bindings are refreshed",
            }
            for item in NEGATIVES
        ],
        "storage_reservation": {
            "relocation_copy_bytes": total_bytes,
            "one_semantic_negative_peak_bytes": total_bytes,
            "headroom_bytes": DEFAULT_HEADROOM_BYTES,
            "estimated_new_bytes_upper_bound": total_bytes * 2 + DEFAULT_HEADROOM_BYTES,
            "no_concurrent_tamper_copies": True,
        },
        "launch_authorization": "root-controlled shared-runner submission only; request preparation does not launch",
        "scientific_scope": "relocation and data-engineering audit only; no solver, decoder, converter, or physical-fate inference",
        "prepared_at_monotonic_seconds": time.monotonic() - started,
    }
    _write_json(output_request, request)
    return request


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-request", help="bind a completed source receipt and build a root-reviewed request")
    prepare.add_argument("--source-receipt", required=True, type=Path)
    prepare.add_argument("--source-bundle", required=True, type=Path)
    prepare.add_argument("--output-request", required=True, type=Path)
    prepare.add_argument("--relocated-bundle-template", default="{attempt_root}/m4-actual-validation/relocated/UF_M4_CASE")
    prepare.add_argument("--output-template", default="{attempt_root}/m4-actual-validation/results")
    prepare.add_argument("--isolation-wrapper", required=True, type=Path)
    prepare.add_argument("--python", required=True, type=Path)
    prepare.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)

    run = commands.add_parser("run", help="relocate and execute the actual M4 audit; root runner only")
    run.add_argument("--source-receipt", required=True, type=Path)
    run.add_argument("--source-bundle", required=True, type=Path)
    run.add_argument("--relocated-bundle", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--isolation-wrapper", required=True, type=Path)
    run.add_argument("--python", required=True, type=Path)
    run.add_argument("--max-bytes", required=True, type=int)
    run.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare-request":
            result = prepare_request(args)
        else:
            result = run_actual_validation(args)
    except (ActualValidationError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"m4-actual-validation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": result["schema"], "status": result["status"], "case_id": result.get("case_id")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
