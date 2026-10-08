#!/usr/bin/env python3
"""Forward V5 typed-only parent with an explicit import/source closure.

The consumed V4 builder used the V3 parent as its replacement role.  That
made the request appear to contain the complete parent chain even though the
V3 and V2-current-bound files which are imported at runtime had been removed
by the role replacement.  V5 keeps V4 byte-for-byte unchanged and appends a
literal closure for those imports and for the shared runtime/batch wrappers.

This module is a metadata builder/runner adapter only.  It does not read H5,
BI4, CSV, or a typed result while building a request.  A V5 request remains
development-only with QI/QN/QE UNKNOWN and is intended for the existing V4
parent guard after a new request has been independently reviewed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V4_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v4_current_bound.py"
SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v2"
FORWARD_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-v5-current-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class TypedParentV5CurrentError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentV5CurrentError(f"cannot load V4 parent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V4 = _load(V4_SCRIPT, "ds02_bound_typed_only_evaluator_parent_v4_current_bound_for_v5")
P1 = V4.P1


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V4.canonical_sha(value)


def _file(value: Any, role: str) -> Path:
    return V4._file(value, role)


def _stat(path: Path, role: str) -> dict[str, Any]:
    return P1._static(path, role)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return V4._write_new(path, value)


def _append_unique(bindings: list[dict[str, Any]], path: Path, role: str) -> None:
    if any(isinstance(item, Mapping) and item.get("role") == role for item in bindings):
        raise TypedParentV5CurrentError(f"duplicate V5 static role: {role}")
    bindings.append(_stat(path, role))


def _closure_paths() -> list[tuple[str, Path]]:
    """Return every source reached by the V5 parent/runtime import edges.

    The two ``*_current_bound`` parent files are deliberately separate from
    the V4 wrapper role.  The runtime closure follows runtime_v6 -> runtime_v2
    and batch_runner_v6 -> batch_runner.  Dispatch wrappers are included as
    well because a parent request may use the same runtime through the v6
    dispatch entrypoint; they are small code sources and do not imply a solver
    launch.
    """
    v3 = V4.BASE_SCRIPT
    v2_current = V4.BASE.BASE_SCRIPT
    values = [
        ("typed_only_parent_v5_current_bound", SCRIPT),
        ("typed_only_parent_v4_current_bound", V4_SCRIPT),
        ("typed_only_parent_v3_current_bound", v3),
        ("typed_only_parent_v2_current_bound", v2_current),
        ("shared_runtime_v6", SCRIPT_DIR / "ds_data02_runtime_v6.py"),
        ("shared_runtime_v2", SCRIPT_DIR / "ds_data02_runtime_v2.py"),
        ("shared_batch_runner_v6", SCRIPT_DIR / "ds_data02_batch_runner_v6.py"),
        ("shared_batch_runner_base", SCRIPT_DIR / "ds_data02_batch_runner.py"),
        ("shared_dispatch_v6", SCRIPT_DIR / "ds_data02_stage2_dispatch_v6.py"),
        ("shared_strict_dispatch_v6", SCRIPT_DIR / "ds_data02_strict_dispatch_v6.py"),
    ]
    result: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for role, raw in values:
        path = Path(raw).expanduser()
        if not path.is_file():
            raise TypedParentV5CurrentError(f"V5 closure source is missing: {role}: {path}")
        key = str(path.resolve())
        if role in seen:
            raise TypedParentV5CurrentError(f"V5 closure role repeated: {role}")
        seen.add(role)
        result.append((role, path))
    return result


def build_forward_request(*, base_request: Path | str, current_binding: Path | str,
                          output: Path | str, parent_attempt_id: str,
                          supervisor_output_root: Path | str, home_receipt: Path | str,
                          max_wall_seconds: float | None = None,
                          trace_path: Path | str | None = None,
                          allow_missing_parent: bool | None = None) -> dict[str, Any]:
    """Build a V5 request through V4, then append the complete source closure."""
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise TypedParentV5CurrentError(f"refusing existing V5 request: {target}")
    # V4 writes a canonical temporary request.  We intentionally use the
    # existing builder so all V4 reservation/source semantics stay unchanged.
    with tempfile.TemporaryDirectory(prefix="ds02-v5-builder-") as tmp:
        intermediate = Path(tmp) / "v4-request.json"
        result = V4.build_forward_request(
            base_request=base_request, current_binding=current_binding,
            output=intermediate, parent_attempt_id=parent_attempt_id,
            supervisor_output_root=supervisor_output_root,
            home_receipt=home_receipt, max_wall_seconds=max_wall_seconds,
            trace_path=trace_path, allow_missing_parent=allow_missing_parent)
        value = json.loads(intermediate.read_text(encoding="utf-8"))

    if value.get("schema") != SCHEMA or value.get("sha256") != canonical_sha(value):
        raise TypedParentV5CurrentError("V4 intermediate request is not canonical")
    existing = value.get("static_bindings")
    if not isinstance(existing, list):
        raise TypedParentV5CurrentError("V4 static bindings are missing")
    # V4 called its own wrapper ``typed_only_parent_v3_current_bound``.  Fix
    # that role only in the new request: the exact V4 and V3 sources are now
    # distinct and the old V4 request remains immutable.
    replace_roles = {
        "typed_only_parent_v3_current_bound",
        "typed_only_parent_v2_current_bound",
        "typed_only_parent_v5_current_bound", "shared_runtime_v6",
        "typed_only_parent_v4_current_bound",
        "shared_runtime_v2", "shared_batch_runner_v6", "shared_batch_runner_base",
        "shared_dispatch_v6", "shared_strict_dispatch_v6",
    }
    bindings = [dict(item) for item in existing
                if isinstance(item, Mapping) and item.get("role") not in replace_roles]
    closure = _closure_paths()
    for role, path in closure:
        _append_unique(bindings, path, role)
    value["static_bindings"] = bindings
    value.setdefault("execution", {})["import_closure"] = {
        "parent": [
            "typed_only_parent_v5_current_bound",
            "typed_only_parent_v4_current_bound",
            "typed_only_parent_v3_current_bound",
            "typed_only_parent_v2_current_bound",
            "typed_only_parent_v2_base",
            "typed_only_parent_v1_base",
        ],
        "shared_runtime": [
            "shared_runtime_v6", "shared_runtime_v2",
            "shared_dispatch_v6", "shared_strict_dispatch_v6",
            "shared_batch_runner_v6", "shared_batch_runner_base",
        ],
        "static_roles_are_literal_paths": True,
        "original_path_fallback": "FORBIDDEN",
    }
    value["v5_current_forward"] = {
        "schema": FORWARD_SCHEMA,
        "base_v4_request": {
            "path": str(Path(base_request).expanduser().resolve()),
            "sha256": value.get("v4_current_forward", {}).get("base_request", {}).get("sha256"),
        },
        "v4_builder": {"path": str(V4_SCRIPT), "sha256": V4._sha_file(V4_SCRIPT)},
        "parent_import_closure": [
            {"role": role, "path": str(path.resolve()), "sha256": V4._sha_file(path)}
            for role, path in closure[:4]
        ],
        "runtime_import_closure": [
            {"role": role, "path": str(path.resolve()), "sha256": V4._sha_file(path)}
            for role, path in closure[4:]
        ],
        "runtime_v6_import_edges": {
            "ds_data02_runtime_v6.py": ["ds_data02_runtime_v2.py"],
            "ds_data02_batch_runner_v6.py": ["ds_data02_batch_runner.py"],
            "ds_data02_batch_runner.py": ["ds_data02_runtime_v2.py"],
            "ds_data02_stage2_dispatch_v6.py": ["ds_data02_strict_dispatch_v6.py"],
            "ds_data02_strict_dispatch_v6.py": ["ds_data02_runtime_v6.py"],
        },
        "source_content_read_during_build": False,
        "scientific_payload_read_during_build": False,
        "same_parent_ledger": True,
        "new_ledger_owner": False,
        "qualification": dict(UNKNOWN),
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "V5 is additive: V4/V3/V2-current-bound requests remain immutable.",
        "The explicit parent/runtime closure is a source-binding correction; it does not by itself prove a relocated subprocess run.",
        "H5, BI4, CSV, and typed-result content are not read by this builder.",
    ]
    value["sha256"] = canonical_sha(value)
    _write_new(target, value)
    return {"status": "READY_V5_CURRENT_BOUND_IMPORT_CLOSURE", "schema": SCHEMA,
            "request": str(target), "sha256": value["sha256"],
            "static_role_count": len(bindings), "hdf5_or_bi4_read": False,
            "payload_read": False, "qualification": dict(UNKNOWN),
            "v5_forward_schema": FORWARD_SCHEMA}


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    return V4._validate_request(path, verify_static_content=verify_static_content)


def _run_fixed(path: Path | str, *, io_slot_approved: bool = False,
               parent_pid: int | None = None) -> dict[str, Any]:
    return V4._run_fixed(path, io_slot_approved=io_slot_approved, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--base-request", type=Path, required=True)
    build.add_argument("--current-binding", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--parent-attempt-id", required=True)
    build.add_argument("--supervisor-output-root", type=Path, required=True)
    build.add_argument("--home-receipt", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float)
    build.add_argument("--trace-path", type=Path)
    group = build.add_mutually_exclusive_group()
    group.add_argument("--allow-missing-parent", dest="allow_missing_parent", action="store_true")
    group.add_argument("--disallow-missing-parent", dest="allow_missing_parent", action="store_false")
    build.set_defaults(allow_missing_parent=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_forward_request(
                base_request=args.base_request, current_binding=args.current_binding,
                output=args.output, parent_attempt_id=args.parent_attempt_id,
                supervisor_output_root=args.supervisor_output_root,
                home_receipt=args.home_receipt, max_wall_seconds=args.max_wall_seconds,
                trace_path=args.trace_path, allow_missing_parent=args.allow_missing_parent)
        else:
            raise TypedParentV5CurrentError("only build-request is exposed; run through the reviewed V4 parent")
    except (TypedParentV5CurrentError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent V5: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
