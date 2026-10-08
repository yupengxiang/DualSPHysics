#!/usr/bin/env python3
"""Forward V9 JSON-only proof consumer with explicit provenance paths.

V8 correctly rejects absolute paths which are not under the relocated output
roots.  The V16 typed-only result also carries two paths to the old typed
product and its converter report as provenance.  Those paths must be declared
explicitly by the small producer report: they are recorded, never opened, and
cannot be used as a source fallback.  V9 adds that narrow declaration while
retaining every V8 identity, mass, time, censoring, SHA, and UNKNOWN check.

This module does not modify V8.  It patches only the in-process path-audit
callback while delegating the proof calculation and result validation to the
immutable V8 implementation.  A V9 request must contain
``provenance_source_report`` and ``provenance_path_declarations``; undeclared
absolute paths still fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V8_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V8_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
PRODUCER_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
MAX_METADATA_BYTES = 32 * 1024 * 1024


class V9ProofConsumerError(RuntimeError):
    """Raised when the explicit provenance contract is malformed."""


def _load_v8() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_fresh_v16_consumer_v8_for_v9", V8_SCRIPT)
    if spec is None or spec.loader is None:
        raise V9ProofConsumerError(f"cannot load immutable V8 consumer: {V8_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8 = _load_v8()


def _file(path: Any, role: str) -> Path:
    if not isinstance(path, str) or not path.startswith(os.sep):
        raise V9ProofConsumerError(f"{role} must be an absolute path")
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise V9ProofConsumerError(f"{role} is not a regular non-symlink file: {target}")
    return target


def _json(path: Any, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise V9ProofConsumerError(f"{role} exceeds metadata-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V9ProofConsumerError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V9ProofConsumerError(f"{role} must be an object")
    return target, value


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _derive_producer_paths(report: Mapping[str, Any]) -> set[str]:
    """Return only paths that the typed-only producer calls provenance.

    The result's two problematic fields are deliberately mapped to the
    producer report's typed-input fields.  We do not recursively trust every
    path in the report, since the report also contains actionable output and
    request paths which must never become an allow-list.
    """
    if report.get("schema") != PRODUCER_SCHEMA:
        raise V9ProofConsumerError("provenance source report schema differs")
    labels = report.get("labels")
    typed_input = report.get("typed_input")
    provenance = report.get("v37_provenance")
    if not isinstance(labels, Mapping) or not isinstance(typed_input, Mapping):
        raise V9ProofConsumerError("producer report typed-input provenance is missing")
    paths: set[str] = set()
    for key in ("path", "post_stat", "pre_stat"):
        value = typed_input.get(key)
        if isinstance(value, Mapping):
            value = value.get("path")
        if isinstance(value, str) and value.startswith(os.sep):
            paths.add(str(Path(value).expanduser().resolve()))
    converter = provenance.get("converter_report") if isinstance(provenance, Mapping) else None
    if isinstance(converter, Mapping):
        value = converter.get("path")
        if isinstance(value, str) and value.startswith(os.sep):
            paths.add(str(Path(value).expanduser().resolve()))
    if not paths:
        raise V9ProofConsumerError("producer report has no typed-input provenance paths")
    return paths


def _declared_paths(request: Mapping[str, Any]) -> set[str]:
    source = request.get("provenance_source_report")
    if not isinstance(source, Mapping):
        raise V9ProofConsumerError("provenance_source_report is required")
    source_path, report = _json(source.get("path"), "provenance source report")
    expected_sha = source.get("sha256")
    actual_sha = _sha_file(source_path)
    if expected_sha != actual_sha:
        raise V9ProofConsumerError("provenance source report SHA differs")
    canonical = V8.canonical_sha(report)
    if report.get("sha256") != canonical:
        raise V9ProofConsumerError("provenance source report canonical SHA differs")
    declarations = request.get("provenance_path_declarations")
    if not isinstance(declarations, list) or not declarations:
        raise V9ProofConsumerError("provenance_path_declarations is required")
    derived = _derive_producer_paths(report)
    declared: set[str] = set()
    for index, item in enumerate(declarations):
        if not isinstance(item, Mapping):
            raise V9ProofConsumerError(f"provenance declaration {index} is malformed")
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith(os.sep):
            raise V9ProofConsumerError(f"provenance declaration {index}.path is not absolute")
        normalized = str(Path(path).expanduser().resolve())
        if normalized not in derived:
            raise V9ProofConsumerError(
                f"provenance declaration {index} is not a typed-input path from the producer report")
        role = item.get("role")
        if not isinstance(role, str) or not role.startswith("typed_input"):
            raise V9ProofConsumerError(f"provenance declaration {index}.role is not typed-input provenance")
        declared.add(normalized)
    if declared != derived:
        raise V9ProofConsumerError("provenance declarations do not exactly cover producer typed-input paths")
    return declared


_DECLARED_PROVENANCE: set[str] = set()


def _path_audit_v9(value: Any, *, original_roots: Sequence[Path],
                   allowed_roots: Sequence[Path], context: tuple[str, ...] = ()) -> dict[str, Any]:
    """Audit absolute strings with an exact, non-opening provenance allow-list."""
    provenance: list[str] = []
    external: list[str] = []
    original_hits: list[str] = []

    def visit(item: Any, parents: tuple[str, ...]) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, parents + (str(key),))
            return
        if isinstance(item, list):
            for child in item:
                visit(child, parents)
            return
        if not isinstance(item, str) or not item.startswith(os.sep):
            return
        try:
            normalized = str(Path(item).expanduser().resolve())
        except OSError:
            normalized = item
        path = Path(normalized)
        if normalized in _DECLARED_PROVENANCE:
            # This is a string-level provenance record.  No stat/open/hash is
            # performed and it cannot become a fallback source input.
            provenance.append(normalized)
        elif any(V8._under(path, root) for root in original_roots):
            original_hits.append(normalized)
        elif not any(V8._under(path, root) for root in allowed_roots):
            external.append(normalized)

    visit(value, context)
    return {"provenance_paths": sorted(set(provenance)),
            "actionable_original_path_hits": sorted(set(original_hits)),
            "unbound_absolute_paths": sorted(set(external))}


def run(request_path: Path | str, output_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Run immutable V8 with the V9 explicit provenance audit."""
    request = V8._load_object(Path(request_path).expanduser().resolve())
    if request.get("schema") != V8_SCHEMA:
        raise V9ProofConsumerError("V9 forward requires a V8 request schema")
    global _DECLARED_PROVENANCE
    _DECLARED_PROVENANCE = _declared_paths(request)
    old_audit = V8._path_audit
    V8._path_audit = _path_audit_v9
    try:
        return V8.run(request_path, output_path, io_slot_approved=io_slot_approved,
                      parent_pid=parent_pid, max_wall_seconds=max_wall_seconds)
    finally:
        V8._path_audit = old_audit
        _DECLARED_PROVENANCE = set()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("preflight")
    prep.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        request = V8._load_object(args.request)
        if request.get("schema") != V8_SCHEMA:
            raise V9ProofConsumerError("V9 forward requires a V8 request schema")
        _declared_paths(request)
        if args.command == "preflight":
            value = V8.preflight(args.request)
        else:
            value = run(args.request, args.output, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
    except (V9ProofConsumerError, V8.ProofConsumerError, OSError, ValueError,
            TypeError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof consumer V9: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
