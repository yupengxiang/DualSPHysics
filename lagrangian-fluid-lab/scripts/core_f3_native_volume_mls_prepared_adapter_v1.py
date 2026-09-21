#!/usr/bin/env python3
"""Adapt a Core F3 prepared record for the frozen native MLS v2 runner.

The frozen ``f3_native_volume_mls_v2.py`` implementation predates the Core
source prepared-record schema and reads ``dp_m`` and ``candidate_definition``
at the top level.  Current source records keep those values under ``case`` or
``config`` and use ``generated_prefix`` for the XML.  This versioned adapter
normalizes only that input contract, records hashes of the original and
derived records, and then delegates numerical work unchanged to the frozen v2
runner.  It does not read future frames or alter source, seed, kernel, gate,
or integration semantics.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


SCHEMA = "core.f3.native_volume_mls.prepared_adapter.v1"
NORMALIZED_SCHEMA = "core.f3.cfd.native_volume_mls.source.v1.adapter_normalized"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _scalar(record: dict[str, Any], key: str, *, required: bool = True) -> Any:
    values: list[tuple[str, Any]] = []
    for container_name in ("case", "config"):
        container = record.get(container_name)
        if isinstance(container, dict) and key in container and container[key] is not None:
            values.append((container_name, container[key]))
    if key in record and record[key] is not None:
        values.append(("top_level", record[key]))
    if not values:
        if required:
            raise ValueError(f"prepared record has no {key!r} in case/config/top level")
        return None
    first_name, first = values[0]
    for name, value in values[1:]:
        if isinstance(first, (int, float)) and isinstance(value, (int, float)):
            if float(first) != float(value):
                raise ValueError(f"prepared {key} disagrees between {first_name} and {name}")
        elif value != first:
            raise ValueError(f"prepared {key} disagrees between {first_name} and {name}")
    return first


def _candidate_definition(record: dict[str, Any], prepared_path: Path) -> Path:
    explicit = record.get("candidate_definition")
    prefix = record.get("generated_prefix")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(str(explicit)))
    if prefix:
        candidates.append(Path(str(prefix)).with_suffix(".xml"))
    # A scheduler may relocate the record but keep its copied input files.
    if prefix:
        candidates.append(prepared_path.resolve().parent / (Path(str(prefix)).name + ".xml"))
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file():
            expected = (record.get("inputs") or {}).get(str(candidate))
            if expected is None:
                raise ValueError(f"candidate XML is not listed in prepared.inputs: {candidate}")
            actual = sha256_file(candidate)
            if actual != str(expected):
                raise ValueError(f"candidate XML hash mismatch: {candidate}")
            return candidate
    raise FileNotFoundError("prepared record has no existing inputs-bound candidate XML")


def normalize_prepared(original_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Create an immutable normalized record without changing the original."""
    original_path = Path(original_path).resolve()
    output_path = Path(output_path).resolve()
    original = json.loads(original_path.read_text(encoding="utf-8"))
    if not isinstance(original, dict):
        raise ValueError("prepared record must be a JSON object")
    dp_m = float(_scalar(original, "dp_m"))
    if not math.isfinite(dp_m) or dp_m <= 0:
        raise ValueError("prepared dp_m must be finite and positive")
    candidate = _candidate_definition(original, original_path)
    normalized = dict(original)
    normalized.update({
        "schema": NORMALIZED_SCHEMA,
        "dp_m": dp_m,
        "candidate_definition": str(candidate),
        "case_id": _scalar(original, "case_id", required=False),
        "recipe_id": _scalar(original, "recipe_id", required=False),
        "qualified": bool(_scalar(original, "qualified", required=False) or False),
        "formal_release": bool(_scalar(original, "formal_release", required=False) or False),
        "q": _scalar(original, "q", required=False),
        "drive_amplitude": _scalar(original, "drive_amplitude", required=False),
        "adapter_binding": {
            "schema": SCHEMA,
            "adapter_version": 1,
            "original_prepared_path": str(original_path),
            "original_prepared_sha256": sha256_file(original_path),
            "original_schema": original.get("schema"),
            "derived_fields": ["dp_m", "candidate_definition", "case_id", "recipe_id",
                                "qualified", "formal_release", "q", "drive_amplitude"],
            "candidate_definition_sha256": sha256_file(candidate),
            "numerical_backend_change": False,
            "future_state_access": False,
        },
    })
    serialized = json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_text(encoding="utf-8") != serialized:
            raise FileExistsError(f"normalized prepared output differs from existing file: {output_path}")
    else:
        partial = output_path.with_name(output_path.name + ".partial")
        partial.write_text(serialized, encoding="utf-8")
        partial.replace(output_path)
    normalized_sha = sha256_file(output_path)
    normalized["adapter_binding"]["normalized_prepared_sha256"] = normalized_sha
    # The normalized hash is intentionally recorded in the separate adapter
    # record; embedding it in the normalized JSON would be self-referential.
    return normalized


def _write_record(path: Path, record: dict[str, Any]) -> None:
    path = Path(path).resolve()
    serialized = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # A --resume invocation reconstructs the same adapter binding.  Keep
        # the first record's timestamp while rejecting any provenance drift.
        existing = json.loads(path.read_text(encoding="utf-8"))
        expected = dict(record)
        existing_created = existing.pop("created_at_utc", None)
        expected.pop("created_at_utc", None)
        if existing != expected or existing_created is None:
            raise FileExistsError(f"adapter record differs from existing file: {path}")
        return
    partial = path.with_name(path.name + ".partial")
    partial.write_text(serialized, encoding="utf-8")
    partial.replace(path)


def build_backend_argv(args: argparse.Namespace, normalized_path: Path) -> list[str]:
    command = [
        str(args.python), str(args.backend_script),
        "--source", str(args.source), "--prepared", str(normalized_path),
    ]
    for flag, value in (
        ("--frame-index-map", args.frame_index_map), ("--output", args.output),
        ("--audit-output", args.audit_output), ("--dp", args.dp),
        ("--seeds", args.seeds), ("--substeps", args.substeps),
        ("--stop-after", args.stop_after), ("--resume", args.resume),
        ("--kill-after-h5-append", args.kill_after_h5_append),
        ("--kill-after-generation", args.kill_after_generation),
        ("--audit-only", args.audit_only),
    ):
        if value is None or value is False:
            continue
        command.extend([flag] if value is True else [flag, str(value)])
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--backend-script", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--adapter-record-output", type=Path, required=True)
    parser.add_argument("--frame-index-map", type=Path)
    parser.add_argument("--dp", type=float)
    parser.add_argument("--seeds", type=int, default=512)
    parser.add_argument("--substeps", type=int, default=2)
    parser.add_argument("--stop-after", type=int, default=20)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--kill-after-h5-append", type=int)
    parser.add_argument("--kill-after-generation", type=int)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.audit_only and args.output is None:
        parser.error("--output is required unless --audit-only is used")
    if args.audit_output is None:
        parser.error("--audit-output is required")

    record_path = args.adapter_record_output.resolve()
    normalized_path = record_path.with_name(record_path.stem + ".normalized-prepared.json")
    normalized = normalize_prepared(args.prepared, normalized_path)
    record = {
        "schema": SCHEMA,
        "adapter_version": 1,
        "created_at_utc": utc_now(),
        "original_prepared": {"path": str(args.prepared.resolve()), "sha256": sha256_file(args.prepared)},
        "normalized_prepared": {"path": str(normalized_path), "sha256": sha256_file(normalized_path)},
        "candidate_definition": normalized["candidate_definition"],
        "candidate_definition_sha256": normalized["adapter_binding"]["candidate_definition_sha256"],
        "backend_script": {"path": str(args.backend_script.resolve()), "sha256": sha256_file(args.backend_script)},
        "source": {"path": str(args.source.resolve()), "sha256": sha256_file(args.source)},
        "derived_fields": normalized["adapter_binding"]["derived_fields"],
        "numerical_backend_change": False,
        "future_state_access": False,
        "central_ledger_mutation": 0,
        "gpu_started": False,
    }
    _write_record(record_path, record)
    command = build_backend_argv(args, normalized_path)
    # Directly invoking a script below a frozen snapshot puts only its
    # ``scripts`` directory on sys.path.  The backend imports the package as
    # ``scripts.*``, so prepend both the snapshot root and its scripts folder;
    # this also prevents the live checkout from satisfying that import.
    backend_root = args.backend_script.resolve().parents[1]
    backend_scripts = backend_root / "scripts"
    env = os.environ.copy()
    prior_pythonpath = env.get("PYTHONPATH", "")
    pythonpath = [str(backend_root), str(backend_scripts)]
    if prior_pythonpath:
        pythonpath.append(prior_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
