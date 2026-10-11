#!/usr/bin/env python3
"""Run semantic negative checks against the completed portable M2 bundle.

The build and relocation workers already prove that the original package is
portable.  This worker checks the production validator's rejection path on
the actual produced package as well.  Each negative is run in a disposable
copy: the HDF5 trajectory and the source bundle are never opened read-write,
the labels file is copied, and immutable files are hard-linked when the NAS
permits it.  Only the copied manifest's labels binding is rehashed, so an
artifact-hash-only check cannot hide a semantic mismatch.

Two small reports survive the disposable scratch tree:

* ``identity`` changes one actual ``particle_id`` label;
* ``destination_position`` changes one actual destination coordinate.

Both cases must be rejected by the bundled ``runtime/portable_bundle.py``
validator.  No solver or decoder is started and no source payload is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable

import h5py


SCHEMA = "ds-data-02.m2.portable-tamper-validation.v1"
PORTABLE_SCHEMA = "ds-data-02.m2.portable-bundle.v1"
CHUNK_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_BYTES = 1_500_000_000
DEFAULT_MAX_WALL_SECONDS = 1800.0

NEGATIVES: tuple[dict[str, str], ...] = (
    {
        "name": "identity",
        "dataset": "particle_id",
        "expected_error": "transport labels changed particle IDs",
    },
    {
        "name": "destination_position",
        "dataset": "destination_position_m",
        "expected_error": "destination transport positions do not match final frame",
    },
)


class TamperValidationError(RuntimeError):
    """Raised when the negative validation contract is not met."""


def _deadline(max_wall_seconds: float) -> float:
    if not isinstance(max_wall_seconds, (int, float)) or max_wall_seconds <= 0:
        raise TamperValidationError("max-wall-seconds must be positive")
    return time.monotonic() + float(max_wall_seconds)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise TamperValidationError("tamper validation wall limit exceeded")


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


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise TamperValidationError(f"{label} is not a regular file: {path}")
    return path


def _walk_regular_files(root: Path, *, deadline: float) -> list[tuple[Path, int]]:
    if root.is_symlink() or not root.is_dir():
        raise TamperValidationError(f"source bundle is not a regular directory: {root}")
    records: list[tuple[Path, int]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        _check_deadline(deadline)
        current_path = Path(current)
        for name in sorted(directories):
            directory = current_path / name
            if directory.is_symlink() or not directory.is_dir():
                raise TamperValidationError(f"bundle contains a non-directory entry: {directory}")
        for name in sorted(files):
            file_path = current_path / name
            _regular_file(file_path, "bundle entry")
            records.append((file_path, file_path.stat().st_size))
    records.sort(key=lambda item: item[0].relative_to(root).as_posix())
    return records


def _load_manifest(source: Path, *, deadline: float) -> tuple[dict[str, Any], list[tuple[Path, int]]]:
    manifest_path = _regular_file(source / "manifest.json", "manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TamperValidationError("portable manifest is not readable JSON") from exc
    if manifest.get("schema") != PORTABLE_SCHEMA:
        raise TamperValidationError("portable manifest schema is not the production schema")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise TamperValidationError("portable manifest has no artifact bindings")
    records = _walk_regular_files(source, deadline=deadline)
    record_map = {path.relative_to(source).as_posix(): (path, size) for path, size in records}
    for key, binding in artifacts.items():
        if not isinstance(binding, dict):
            raise TamperValidationError(f"artifact binding {key!r} is not an object")
        relative = binding.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise TamperValidationError(f"artifact binding {key!r} has an unsafe path")
        if relative not in record_map:
            raise TamperValidationError(f"manifest artifact is absent from bundle: {relative}")
        path, size = record_map[relative]
        if binding.get("bytes") != size:
            raise TamperValidationError(f"manifest byte count disagrees for {relative}")
        actual = _sha256(path, deadline=deadline)
        if binding.get("sha256") != actual:
            raise TamperValidationError(f"manifest hash disagrees for {relative}")
    return manifest, records


def _copy_or_link(source: Path, destination: Path, *, mutable: bool, deadline: float) -> None:
    _check_deadline(deadline)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mutable:
        shutil.copy2(source, destination)
        return
    try:
        # This is safe because immutable files are never opened read-write.
        os.link(source, destination)
    except OSError:
        # NAS and an attempt directory can occasionally be on different
        # devices.  The bounded fallback preserves correctness at the cost of
        # a real copy, still below the request's 1.5e9-byte ceiling.
        shutil.copy2(source, destination)


def _copy_disposable_bundle(
    source: Path,
    destination: Path,
    records: Iterable[tuple[Path, int]],
    *,
    deadline: float,
) -> int:
    if destination.exists() or destination.is_symlink():
        raise TamperValidationError(f"disposable destination already exists: {destination}")
    destination.mkdir(parents=True)
    copied_bytes = 0
    for source_path, size in records:
        _check_deadline(deadline)
        relative = source_path.relative_to(source)
        # The copied manifest and labels are the only files changed by this
        # worker.  Hard-linking either would mutate the original package.
        mutable = relative.as_posix() in {"manifest.json", "labels.h5"}
        _copy_or_link(source_path, destination / relative, mutable=mutable, deadline=deadline)
        copied_bytes += size
    return copied_bytes


def _tamper_labels(case_root: Path, negative: dict[str, str]) -> dict[str, Any]:
    labels_path = _regular_file(case_root / "labels.h5", "copied labels")
    dataset_name = negative["dataset"]
    mutation: dict[str, Any] = {"dataset": dataset_name}
    with h5py.File(labels_path, "r+") as handle:
        if dataset_name not in handle:
            raise TamperValidationError(f"production labels lack dataset {dataset_name}")
        dataset = handle[dataset_name]
        if dataset.shape[0] < 1:
            raise TamperValidationError(f"production labels dataset is empty: {dataset_name}")
        if dataset_name == "particle_id":
            old = int(dataset[0])
            new = old + 1
            dataset[0] = new
        else:
            old = float(dataset[0, 0])
            new = old + 0.125
            dataset[0, 0] = new
        handle.flush()
    mutation.update({"old": old, "new": new, "labels_sha256": _sha256(labels_path)})

    manifest_path = _regular_file(case_root / "manifest.json", "copied manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TamperValidationError("copied manifest became unreadable") from exc
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get("labels"), dict):
        raise TamperValidationError("copied manifest lacks labels artifact binding")
    binding = artifacts["labels"]
    binding["bytes"] = labels_path.stat().st_size
    binding["sha256"] = mutation["labels_sha256"]
    # Keep the manifest contract valid at the artifact layer; the production
    # validator must then reject the semantic identity/position mismatch.
    with manifest_path.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    mutation["manifest_rehashed_labels_only"] = True
    mutation["manifest_sha256"] = _sha256(manifest_path)
    return mutation


def _invoke_production_validator(
    case_root: Path,
    *,
    python_path: Path,
    deadline: float,
) -> dict[str, Any]:
    validator = _regular_file(case_root / "runtime" / "portable_bundle.py", "bundled production validator")
    remaining = max(1.0, deadline - time.monotonic())
    command = [
        str(python_path),
        str(validator),
        "validate",
        "--bundle-root",
        str(case_root),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired as exc:
        raise TamperValidationError("production validator exceeded worker wall limit") from exc
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    return {
        "argv": command,
        "returncode": completed.returncode,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "validator_sha256": _sha256(validator, deadline=deadline),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise TamperValidationError(f"refusing to overwrite report: {path}")
    partial = path.with_name(path.name + f".partial-{os.getpid()}")
    if partial.exists() or partial.is_symlink():
        raise TamperValidationError(f"stale partial report exists: {partial}")
    try:
        with partial.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def run(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_bundle).resolve()
    output = Path(args.output).absolute()
    output_resolved = output.resolve()
    if output_resolved == source or output_resolved.is_relative_to(source):
        raise TamperValidationError("output must be outside the immutable source bundle")
    python_path = Path(args.python).absolute()
    if not python_path.is_file() or python_path.is_symlink():
        raise TamperValidationError(f"Python runtime is not a regular file: {python_path}")
    if output.exists() or output.is_symlink():
        raise TamperValidationError(f"fresh output is required: {output}")
    deadline = _deadline(args.max_wall_seconds)
    manifest, records = _load_manifest(source, deadline=deadline)
    total_bytes = sum(size for _, size in records)
    if total_bytes > args.max_bytes:
        raise TamperValidationError(
            f"source bundle path bytes {total_bytes} exceed max-bytes {args.max_bytes}"
        )

    source_snapshot_paths = [
        source / "manifest.json",
        source / "labels.h5",
        source / "trajectory.h5",
    ]
    source_snapshot = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path, deadline=deadline)}
        for path in source_snapshot_paths
    }
    output.mkdir(parents=True)
    reports_dir = output / "reports"
    reports_dir.mkdir()
    report_rows: list[dict[str, Any]] = []
    scratch = output / "scratch"
    scratch.mkdir()
    try:
        for negative in NEGATIVES:
            _check_deadline(deadline)
            case_root = scratch / negative["name"]
            copied_bytes = _copy_disposable_bundle(
                source,
                case_root,
                records,
                deadline=deadline,
            )
            mutation = _tamper_labels(case_root, negative)
            validation = _invoke_production_validator(
                case_root,
                python_path=python_path,
                deadline=deadline,
            )
            combined = (validation["stderr_tail"] + "\n" + validation["stdout_tail"]).strip()
            expected_error = negative["expected_error"]
            if validation["returncode"] == 0:
                raise TamperValidationError(
                    f"production validator accepted tampered {negative['name']} bundle"
                )
            if expected_error not in combined:
                raise TamperValidationError(
                    f"tampered {negative['name']} bundle failed for an unexpected reason: {combined[-1000:]}"
                )
            row = {
                "schema": "ds-data-02.m2.portable-tamper-rejection.v1",
                "status": "rejected_as_expected",
                "negative": negative["name"],
                "tampered_artifact": "labels.h5",
                "copied_path_bytes": copied_bytes,
                "mutation": mutation,
                "expected_error": expected_error,
                "production_validator": validation,
                "source_bundle_unchanged_checked_after_run": True,
            }
            _write_json(reports_dir / f"{negative['name']}.json", row)
            report_rows.append(row)
            # The next case gets a fresh copy.  Never leave a modified HDF5
            # or a rehashed manifest in the output package.
            shutil.rmtree(case_root)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)

    after_snapshot = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path, deadline=deadline)}
        for path in source_snapshot_paths
    }
    if after_snapshot != source_snapshot:
        raise TamperValidationError("source portable bundle changed during negative validation")
    final = {
        "schema": SCHEMA,
        "status": "completed",
        "source_bundle": str(source),
        "source_manifest_schema": manifest.get("schema"),
        "source_manifest_sha256": source_snapshot["manifest.json"]["sha256"],
        "source_snapshot": source_snapshot,
        "source_snapshot_after": after_snapshot,
        "source_unchanged": True,
        "negative_count": len(report_rows),
        "negative_reports": [str(reports_dir / f"{row['negative']}.json") for row in report_rows],
        "production_validator": "bundle/runtime/portable_bundle.py",
        "scratch_removed_after_each_case": True,
        "hardlink_immutable_files_when_available": True,
    }
    _write_json(output / "tamper-validation.json", final)
    return final


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (OSError, TamperValidationError, ValueError, RuntimeError) as exc:
        print(f"portable tamper validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
