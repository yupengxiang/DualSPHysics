#!/usr/bin/env python3
"""Execute the ROOT242 V14 recursive source closure.

V14 is the executable successor to the metadata-only recursive preflight.
The outer parent still owns reservation, post-copy hashing, charging, and
release.  After that reservation this process delegates the established V13
copy/OS-open-guard/V8/V12/scorer path, while supplying the same exact
directory rebinding rules used by the V14 preflight.  Every discovered role
is therefore copied from its sealed source into the fresh attempt namespace;
historical paths and the live ledger remain provenance only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import os
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V13_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v13.py"
V14_PREFLIGHT_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_recursive_source_preflight_v14.py"
V14_SCHEMA = "ds02.stage2.f2-root242-v14-recursive-source-binding.v1"
V14_PREFLIGHT_SCHEMA = "ds02.stage2.f2-root242-v14-recursive-source-preflight.v1"
V14_REPORT_SCHEMA = "ds02.stage2.f2-root242-portable-typed-executor-report.v14"
V14_EXECUTOR_ROLE = "v14_executor"
V14_REPORT_ROLE = "v14_recursive_preflight_report"
MAX_METADATA_BYTES = 32 * 1024 * 1024


def _load(path: Path, name: str) -> Any:
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V13 = _load(V13_SCRIPT, "ds02_root242_v13_executor_for_v14")
PREFLIGHT = _load(V14_PREFLIGHT_SCRIPT, "ds02_root242_v14_preflight_for_executor")
V2 = V13.V2


class Root242V14ExecutorError(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> str:
    return V13._canonical(value)


def _json(path: Path, label: str) -> dict[str, Any]:
    return V13._json(path, label)


def _hash(path: Path, *, maximum: int = 4 * 1024 * 1024 * 1024) -> tuple[str, int]:
    return V13._hash(path, maximum=maximum)


def _absolute(value: Any, label: str) -> Path:
    return V13._absolute(value, label)


def _safe_relative(value: Any, label: str) -> str:
    return V13._safe_relative(value, label)


def _directory_rebind_v14(parts: tuple[str, ...], root: Path) -> Path | None:
    """Mirror the preflight's generated-directory policy at runtime."""
    if tuple(str(item) for item in parts) == ("v12_forward", "output_root_rebind_v14"):
        return root / "products"
    lower = [str(item).lower() for item in parts]
    if "decoder_scratch" in lower and "cleanup" in lower:
        return root / "runtime" / "scratch"
    if any(item in {"trace", "expected_artifacts", "home_receipt",
                    "finalization_sidecar"} for item in lower):
        return root / "runtime" / "generated"
    if "filesystem_headroom" in lower:
        label = next((item for item in reversed(lower)
                      if item in {"home", "external", "nvme", "scratch"}), "policy")
        return root / "runtime" / "filesystem-headroom" / label
    if "source_bindings" in lower or "source_binding" in lower:
        label = "".join(char if char.isalnum() or char in "._-" else "_"
                        for char in lower[-1])
        return root / "evidence" / "source-bindings" / (label or "binding")
    return V13._ORIGINAL_DIRECTORY_REBIND(parts, root)


def _report_binding(request: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    binding = request.get("root242_v14_preflight_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != V14_PREFLIGHT_SCHEMA:
        raise Root242V14ExecutorError("V14 preflight binding is missing")
    report_path = _absolute(binding.get("path"), "V14 preflight report")
    report = _json(report_path, "V14 preflight report")
    if report.get("schema") != V14_PREFLIGHT_SCHEMA:
        raise Root242V14ExecutorError("V14 preflight report schema differs")
    if report.get("status") != "READY_FOR_PARENT_GUARD_METADATA_ONLY":
        raise Root242V14ExecutorError("V14 preflight is not ready for parent guard")
    if report.get("unbound_actionable_paths") or report.get("graph_errors"):
        raise Root242V14ExecutorError("V14 preflight contains unbound graph paths")
    rewrite = report.get("rewrite")
    if not isinstance(rewrite, Mapping) or rewrite.get("errors"):
        raise Root242V14ExecutorError("V14 preflight contains rewrite errors")
    actual_sha, _ = _hash(report_path, maximum=MAX_METADATA_BYTES)
    if binding.get("file_sha256") != actual_sha:
        raise Root242V14ExecutorError("V14 preflight report SHA differs")
    roles = (contract.get("root242_source_binding") or {}).get("roles")
    if not isinstance(roles, list):
        raise Root242V14ExecutorError("V14 source role table is missing")
    report_role = next((row for row in roles
                        if isinstance(row, Mapping)
                        and row.get("logical_role") == V14_REPORT_ROLE), None)
    if not isinstance(report_role, Mapping) or report_role.get("source_sha256") != actual_sha:
        raise Root242V14ExecutorError("V14 report role is not sealed to the bound report")
    return report_path, report


def _validate_v14(request_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path, dict[str, Any]]:
    # V13 remains the complete base admission gate, including its V11 role
    # digest, literal interpreter, and output-slot provenance checks.
    outer, contract, contract_path = V13.V11._outer(request_path)
    # The request is built against the primary source checkout, while this
    # isolated launcher can be imported from a consumer worktree during
    # validation.  Temporarily bind V13's identity check to the sealed V13
    # source path; the SHA and role join are still verified by that gate.
    v13_source_binding = outer.get("root242_v13_source_binding")
    v13_source_path = (_absolute(v13_source_binding.get("path"), "V13 executor source")
                       if isinstance(v13_source_binding, Mapping) else None)
    previous_v13_script = V13.SCRIPT
    if v13_source_path is not None:
        V13.SCRIPT = v13_source_path
    try:
        V13.validate_request(request_path, contract_path)
    finally:
        V13.SCRIPT = previous_v13_script
    source = outer.get("root242_v14_source_binding")
    if not isinstance(source, Mapping) or source.get("schema") != V14_SCHEMA:
        raise Root242V14ExecutorError("V14 executor source binding is missing")
    source_path = _absolute(source.get("path"), "V14 executor source")
    if source_path != SCRIPT:
        raise Root242V14ExecutorError("V14 executor source is not this additive launcher")
    source_sha, _ = _hash(source_path, maximum=MAX_METADATA_BYTES)
    if source.get("sha256") != source_sha:
        raise Root242V14ExecutorError("V14 executor source SHA differs")
    report_path, report = _report_binding(outer, contract)
    roles = (contract.get("root242_source_binding") or {}).get("roles")
    if not isinstance(roles, list):
        raise Root242V14ExecutorError("V14 source role table is absent")
    if len(roles) != int(report.get("role_count", -1)) + 2:
        raise Root242V14ExecutorError("V14 role count does not include executor/report roles")
    if not any(row.get("logical_role") == V14_EXECUTOR_ROLE for row in roles if isinstance(row, Mapping)):
        raise Root242V14ExecutorError("V14 executor role is absent")
    if not any(row.get("logical_role") == V14_REPORT_ROLE for row in roles if isinstance(row, Mapping)):
        raise Root242V14ExecutorError("V14 preflight report role is absent")
    plan = outer.get("v14_copy_plan")
    if not isinstance(plan, Mapping) or plan.get("source_fallback") != "REJECT":
        raise Root242V14ExecutorError("V14 copy plan permits source fallback")
    if outer.get("scope", {}).get("original_path_fallback") != "REJECT":
        raise Root242V14ExecutorError("V14 request permits original path fallback")
    root = _absolute(outer.get("storage_scope", {}).get("external_filesystem"),
                     "V14 external filesystem")
    return outer, contract, contract_path, root, report


def _write_report(root: Path, request_path: Path, base: Mapping[str, Any],
                  report_path: Path, report: Mapping[str, Any], role_count: int) -> Path:
    output = root / "reports" / "root242-v14-recursive-executor-report.json"
    if output.exists() or output.is_symlink():
        raise Root242V14ExecutorError("refusing existing V14 executor report")
    base_report = root / "reports" / "root242-v13-output-slot-report.json"
    result = {
        "schema": V14_REPORT_SCHEMA,
        "status": "COMPLETE_ROOT242_V14_RECURSIVE_SOURCE_CLOSURE",
        "request": {"path": str(request_path), "file_sha256": _hash(request_path)[0]},
        "base_v13": {"status": base.get("status"),
                     "report_path": str(base_report),
                     "report_file_sha256": _hash(base_report)[0] if base_report.is_file() else None},
        "recursive_preflight": {
            "path": str(report_path), "file_sha256": _hash(report_path, maximum=MAX_METADATA_BYTES)[0],
            "schema": report.get("schema"), "document_count": report.get("document_count"),
            "role_count": report.get("role_count"),
            "actionable_reference_count": report.get("actionable_reference_count"),
            "nested_rewrite_documents": len((report.get("rewrite") or {}).get("documents", [])),
        },
        "role_count": role_count,
        "execution": {
            "source_copy_after_parent_reservation": True,
            "source_posthash_and_stat": True,
            "recursive_metadata_rewrite_after_copy": True,
            "v8_validator": True, "v12_validator": True, "typed_scorer": True,
            "model_invoked": False, "cfd_invoked": False,
            "original_path_fallback": "REJECT",
            "historical_provenance_is_not_actionable": True,
            "live_ledger_copied": False, "ledger_mutated": False,
            "raw_opened": False, "scientific_hdf5_or_bi4_array_decode": False,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "ledger_mutated": False,
    }
    result["sha256"] = _canonical(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True,
                                 ensure_ascii=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    return output


def run(*, request: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    request_path = Path(request).expanduser().absolute()
    outer, contract, contract_path, root, report = _validate_v14(request_path)
    if root != Path(output_root).expanduser().absolute():
        raise Root242V14ExecutorError("V14 output root differs from parent-bound root")
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        raise Root242V14ExecutorError("refusing non-empty or symlink V14 fresh root")
    # V13.run installs its own exact output-slot map.  Replace that callable
    # for the duration of the call so the copied V2 sees every generated
    # directory class that passed the V14 recursive preflight.  Restoration is
    # mandatory because parent workers can import this module repeatedly.
    original = V13._directory_rebind_v13
    V13._directory_rebind_v13 = _directory_rebind_v14
    try:
        base = V13.run(request=request_path, output_root=root, parent_pid=parent_pid,
                       max_wall_seconds=max_wall_seconds)
    finally:
        V13._directory_rebind_v13 = original
    report_path = _absolute(outer["root242_v14_preflight_binding"]["path"],
                            "V14 preflight report")
    output = _write_report(root, request_path, base, report_path, report,
                           len((contract.get("root242_source_binding") or {}).get("roles", [])))
    return {
        "schema": V14_REPORT_SCHEMA,
        "status": "COMPLETE_ROOT242_V14_RECURSIVE_SOURCE_CLOSURE",
        "base_v13": base,
        "report": {"path": str(output), "file_sha256": _hash(output)[0]},
        "source_fallback": "REJECT", "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }


def validate_request(request: Path | str, contract: Path | str) -> dict[str, Any]:
    request_path = Path(request).expanduser().absolute()
    outer, actual_contract, contract_path, _root, report = _validate_v14(request_path)
    requested_contract = Path(contract).expanduser().absolute()
    if requested_contract != contract_path:
        raise Root242V14ExecutorError("V14 contract argument differs from request binding")
    return {"schema": V14_SCHEMA,
            "status": "ROOT242_V14_METADATA_VALIDATED_READY_FOR_PARENT",
            "role_count": len((actual_contract.get("root242_source_binding") or {}).get("roles", [])),
            "preflight_role_count": report.get("role_count"),
            "payload_read": False, "ledger_mutated": False,
            "launch_performed": False,
            "request_path": str(request_path),
            "contract_path": str(contract_path),
            "attempt_id": outer.get("attempt_id")}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--contract", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-root", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    run_parser.add_argument("--max-wall-seconds", type=float, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_request(args.request, args.contract)
        else:
            result = run(request=args.request, output_root=args.output_root,
                         parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242V14ExecutorError, V13.Root242V13ExecutorError,
            V13.V11.Root242V11ExecutorError, V13.V2.PortableRebindV2Error,
            V13.V11.V9.V1.PortableRebindError, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"ROOT242 V14 executor: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
