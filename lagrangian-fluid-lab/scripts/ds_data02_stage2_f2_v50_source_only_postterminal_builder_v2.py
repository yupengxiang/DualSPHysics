#!/usr/bin/env python3
"""Strict source-only runtime closure for the V50 post-terminal hand-off.

V1 can build a bounded closure when callers provide role paths, but the V50
request has two separate small source registries: ``runtime_sources`` and
``source_entries`` (with a third registry in the parent request's
``static_bindings``).  This additive wrapper cross-checks every actionable
role against those registries or an explicit expected SHA.  It does not copy
or read payloads.  The target paths must already be materialized by the
parent after reservation; this module only stats and hashes bounded code/JSON
files.

The resulting closure keeps the V1 closure schema fields and adds a v2 schema
and per-role source provenance.  The v2 evaluator adapter accepts both
schemas.  An external pinned ``.venv/bin/python`` remains the only path
outside the copied runtime root, with its literal invocation path preserved.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v1.py"
CLOSURE_SCHEMA = "ds02.stage2.f2-postterminal-evaluator-runtime-closure.v2"
CLOSURE_STATUS = "READY_FOR_PARENT_EVALUATOR_GUARD"
MAX_METADATA_BYTES = 8 * 1024 * 1024


class StrictClosureError(RuntimeError):
    pass


def _load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_v50_source_only_builder_v1_for_v2", V1_SCRIPT)
    if spec is None or spec.loader is None:
        raise StrictClosureError(f"cannot load V1 builder: {V1_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V1.canonical_sha(value)


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise StrictClosureError(f"{role} must be a lowercase SHA-256")
    return value


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = V1._file(path, role, max_bytes=MAX_METADATA_BYTES)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StrictClosureError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise StrictClosureError(f"{role} must be an object")
    return target, value


def _sha_file(path: Path, role: str) -> str:
    if path.stat().st_size > V1.MAX_CODE_BYTES:
        raise StrictClosureError(f"refusing oversized {role}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise StrictClosureError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _source_rows(executor: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Collect all small declared source registries without opening payloads."""
    known: dict[str, list[dict[str, Any]]] = {}

    def add(role: Any, row: Any, kind: str) -> None:
        if not isinstance(role, str) or not isinstance(row, Mapping):
            return
        sha = row.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            return
        known.setdefault(role, []).append({
            "kind": kind, "role": role, "sha256": sha,
            "declared_path": row.get("path"),
            "target_relative_path": row.get("target_relative_path"),
            "bytes": row.get("bytes"),
        })

    for row in executor.get("runtime_sources", []):
        if isinstance(row, Mapping):
            add(row.get("role"), row, "executor.runtime_sources")
    for row in executor.get("source_entries", []):
        if isinstance(row, Mapping):
            add(row.get("role"), row, "executor.source_entries")
    for row in parent.get("static_bindings", []):
        if isinstance(row, Mapping):
            add(row.get("role"), row, "parent.static_bindings")
    return known


ALIASES: dict[str, tuple[str, ...]] = {
    # V4 is the actionable wrapper copied as v2_worker; it loads the old V2
    # worker from runtime/native, so both source rows must be closed.
    "raw_reconstruction_worker": ("v2_worker", "raw_worker_v2"),
    "raw_worker_v2": ("raw_worker_v2",),
    "raw_converter": ("raw_converter",),
    "v14_operator": ("v14_operator",),
    "v15_operator": ("v15_operator",),
    "v16_operator": ("v16_operator",),
    "proof_consumer_v11": ("fresh_v16_proof_consumer_v11",),
    "proof_consumer_v10": ("fresh_v16_proof_consumer_v10",),
    "proof_consumer_v9": ("fresh_v16_proof_consumer_v9",),
    "proof_consumer_v8": ("fresh_v16_proof_consumer_v8",),
    "v47_terminal_sealer_v1": ("terminal_sealer_v1",),
    "v47_fresh_product_interface_v1": ("fresh_product_interface_v1",),
}


def _parse_expected(rows: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in rows:
        if "=" not in item:
            raise StrictClosureError("--expected-source must be role=sha256")
        role, value = item.split("=", 1)
        if not role or role in result:
            raise StrictClosureError(f"duplicate explicit expected source: {role}")
        result[role] = _sha(value, f"expected source {role}")
    return result


def _resolve_expected(role: str, observed: str, known: Mapping[str, list[dict[str, Any]]],
                      explicit: Mapping[str, str]) -> dict[str, Any]:
    if role in explicit:
        expected = explicit[role]
        if observed != expected:
            raise StrictClosureError(f"runtime role {role} SHA differs from explicit expected source")
        return {"kind": "explicit_expected_source", "role": role, "sha256": expected}
    candidates: list[dict[str, Any]] = []
    for source_role in ALIASES.get(role, (role,)):
        candidates.extend(known.get(source_role, []))
    # Direct role names are useful for evaluator_v2/v3/v4 and the pinned
    # interpreter.  Aliases above cover the roles whose registry names differ.
    if not candidates:
        candidates.extend(known.get(role, []))
    matches = [row for row in candidates if row["sha256"] == observed]
    if not matches:
        if candidates:
            expected = sorted({row["sha256"] for row in candidates})
            raise StrictClosureError(f"runtime role {role} SHA is not one of declared source SHAs: {expected}")
        raise StrictClosureError(
            f"runtime role {role} has no declared source SHA; supply --expected-source {role}=<sha>")
    # Multiple matching aliases are retained as provenance rather than making
    # an ungrounded choice between the V4 wrapper and V2 worker.
    return {"kind": "declared_source_registry", "role": role,
            "source_candidates": matches, "sha256": observed}


def build_runtime_closure(*, executor_request: Path | str, parent_request: Path | str,
                          runtime_root: Path | str, output: Path | str,
                          role_bindings: Sequence[str], pinned_sources: Sequence[str],
                          abi_smoke: Path | str,
                          expected_sources: Sequence[str] = ()) -> dict[str, Any]:
    executor_path, executor = _json(executor_request, "executor request")
    parent_path, parent = _json(parent_request, "parent request")
    if executor.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise StrictClosureError("executor request is not V50-compatible v34")
    if parent.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise StrictClosureError("parent request is not parent-v3")
    if executor.get("sha256") != canonical_sha(executor) or parent.get("sha256") != canonical_sha(parent):
        raise StrictClosureError("executor/parent canonical SHA differs")
    explicit = _parse_expected(expected_sources)
    known = _source_rows(executor, parent)
    base_output = Path(output).expanduser()
    # V1 validates the pinned interpreter exception and all normal copied-role
    # paths.  It writes a fresh file, which this additive wrapper then enriches
    # with strict source-registry provenance.
    result = V1.build_runtime_closure(
        executor_request=executor_path, runtime_root=runtime_root, output=base_output,
        role_bindings=role_bindings, pinned_sources=pinned_sources, abi_smoke=abi_smoke)
    closure_path, closure = _json(base_output, "V1 runtime closure")
    rows = closure.get("roles")
    if not isinstance(rows, list):
        raise StrictClosureError("V1 runtime closure roles are missing")
    enriched: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("role"), str):
            raise StrictClosureError("V1 runtime closure contains malformed role")
        role = str(raw["role"])
        observed = _sha(raw.get("sha256"), f"runtime role {role}.sha256")
        if role == "interpreter_abi_smoke":
            provenance = {"kind": "generated_abi_smoke", "role": role, "sha256": observed}
        else:
            provenance = _resolve_expected(role, observed, known, explicit)
        row = dict(raw)
        row["source_provenance"] = provenance
        row["source_fallback"] = "FORBIDDEN"
        enriched.append(row)
    closure["schema"] = CLOSURE_SCHEMA
    closure["roles"] = enriched
    closure["source_closure"] = {
        "executor_request": {"path": str(executor_path), "sha256": _sha_file(executor_path, "executor request")},
        "parent_request": {"path": str(parent_path), "sha256": _sha_file(parent_path, "parent request")},
        "registry_kinds": ["executor.runtime_sources", "executor.source_entries", "parent.static_bindings"],
        "declared_source_registry_count": sum(len(value) for value in known.values()),
        "explicit_expected_source_roles": sorted(explicit),
        "content_scope": "small code/JSON/stat only; no HDF5/BI4/raw/typed/result payload",
        "original_path_fallback": "FORBIDDEN",
    }
    closure["sha256"] = canonical_sha(closure)
    # The V1 output is a newly created file owned by this additive invocation;
    # rewrite it only after all strict checks have passed.
    with closure_path.open("w", encoding="utf-8") as stream:
        json.dump(closure, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return {"schema": CLOSURE_SCHEMA, "status": CLOSURE_STATUS,
            "closure": str(closure_path), "sha256": closure["sha256"],
            "strict_source_roles": len(enriched), "payload_read": False,
            "qualification": dict(V1.UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-request", type=Path, required=True)
    parser.add_argument("--parent-request", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role-binding", action="append", default=[])
    parser.add_argument("--pinned-source", action="append", default=[])
    parser.add_argument("--expected-source", action="append", default=[])
    parser.add_argument("--abi-smoke", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_runtime_closure(
            executor_request=args.executor_request, parent_request=args.parent_request,
            runtime_root=args.runtime_root, output=args.output,
            role_bindings=args.role_binding, pinned_sources=args.pinned_source,
            abi_smoke=args.abi_smoke, expected_sources=args.expected_source)
    except (StrictClosureError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V50 strict source-only closure: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
