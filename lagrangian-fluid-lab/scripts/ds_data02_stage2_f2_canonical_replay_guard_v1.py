#!/usr/bin/env python3
"""Build a source-hashed, fail-closed prime request for canonical F2 row 65.

The consumed F2 v14/v15 operator is a historical row-78 operator.  It is
useful as a source dependency, but its identity checks cannot be silently
relabelled as the canonical CURRENT row 65.  This additive wrapper therefore
requires an explicit canonical semantics adapter and a complete copied
converter -> reader -> restorer -> label -> portable/scorer graph.  It hashes
only bounded source/code files and JSON metadata.  Raw BI4, OBI4/IBI4,
CSV, HDF5, and typed/label payloads remain parent-guard work.

The emitted request is a prime input to a later reserved parent.  A successful
build means that the namespace and source graph are sealed; it does not mean
that conversion, label production, or scientific qualification has run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-canonical-replay-prime-request.v1"
REBOUND_SCHEMA = "ds02.stage2.f2-canonical-raw-anchor-rebound.v1"
CANONICAL_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
HISTORICAL_ALIAS_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
PENDING = "PENDING_PARENT_GUARD_CONTENT_SHA256"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
PIPELINE_ROLES = (
    "canonical_adapter", "raw_converter", "reader", "restorer", "label_producer",
    "worker", "portable_scorer",
)
ACTIONABLE_KEYS = frozenset({
    "path", "output_root", "cwd", "worktree_root", "data_root", "source_root",
    "target_root", "trajectory_h5", "input_files", "source_files", "motion_engine_sources",
    "producer_receipts", "current_binding", "source_code_binding", "copy_roles",
})


class PrimeError(ValueError):
    """The canonical prime request is not safe to bind."""


def _json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise PrimeError(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise PrimeError(f"{role} exceeds the bounded JSON limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PrimeError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PrimeError(f"{role} must be a JSON object")
    return value


def _sha_file(path: Path, role: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise PrimeError(f"{role} must be a regular non-symlink file: {path}")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise PrimeError(f"{role} exceeds the bounded source limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode("utf-8")).hexdigest()


def _inside(path: Path, namespace: Path) -> bool:
    try:
        path.relative_to(namespace)
    except ValueError:
        return False
    return True


def _target(value: Any, role: str, namespace: Path) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PrimeError(f"{role}.path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PrimeError(f"{role}.path must be absolute")
    if path.is_symlink():
        raise PrimeError(f"{role}.path cannot be a symlink")
    resolved = path.resolve(strict=False)
    if not _inside(resolved, namespace) or resolved == namespace:
        raise PrimeError(f"{role}.path escapes the copied namespace: {path}")
    if not resolved.is_file():
        raise PrimeError(f"{role}.path is not a regular file: {resolved}")
    return resolved


def _declared_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise PrimeError(f"{role}.sha256 must be a lowercase SHA-256")
    return value


def _audit_old_operator(path: Path, role: str) -> dict[str, Any]:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise PrimeError(f"{role} exceeds source audit limit")
    text = path.read_text(encoding="utf-8")
    alias = HISTORICAL_ALIAS_ID in text or "RX056_RY014_FILL080_ROT090" in text
    row78 = ("case_index" in text and "78" in text) or ("current_case_index" in text and "78" in text)
    inherits_v14 = "ds_data02_stage2_f2_replay_v14" in text
    return {
        "role": role,
        "path": str(path),
        "sha256": _sha_file(path, role),
        "historical_alias_literal": alias,
        "row78_gate_literal": row78,
        "inherits_v14_source": inherits_v14,
        "canonical65_compatible_without_adapter": False if (alias or row78 or inherits_v14) else "UNPROVEN",
    }


def _assert_no_old_actionable(value: Any, namespace: Path, *, key: str = "") -> None:
    if isinstance(value, Mapping):
        for name, item in value.items():
            _assert_no_old_actionable(item, namespace, key=str(name))
    elif isinstance(value, list):
        for item in value:
            _assert_no_old_actionable(item, namespace, key=key)
    elif isinstance(value, str) and key in ACTIONABLE_KEYS and value.startswith("/"):
        path = Path(value).expanduser().resolve(strict=False)
        if not _inside(path, namespace):
            raise PrimeError(f"request retains actionable path outside copied namespace: {path}")


def _pipeline_entries(path: Path, namespace: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    value = _json(path, "pipeline binding")
    if value.get("schema") != "ds02.stage2.f2-canonical-pipeline-binding.v1":
        raise PrimeError("pipeline binding schema is unsupported")
    entries = value.get("roles")
    if not isinstance(entries, list):
        raise PrimeError("pipeline binding roles are missing")
    by_role: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise PrimeError("pipeline role is malformed")
        role = str(item["role"])
        if role not in PIPELINE_ROLES or role in by_role:
            raise PrimeError(f"pipeline role is unsupported or repeated: {role}")
        target = _target(item.get("path"), role, namespace)
        declared = _declared_sha(item.get("sha256"), role)
        actual = _sha_file(target, role)
        if declared != actual:
            raise PrimeError(f"{role} source SHA differs from target")
        by_role[role] = {"role": role, "path": str(target), "sha256": actual,
                         "bytes": target.stat().st_size, "content_status": "SOURCE_SHA_OBSERVED"}
    missing = [role for role in PIPELINE_ROLES if role not in by_role]
    if missing:
        raise PrimeError(f"pipeline roles missing: {missing}")
    if len({item["path"] for item in by_role.values()}) != len(by_role):
        raise PrimeError("pipeline stages must bind distinct copied files")
    return [by_role[role] for role in PIPELINE_ROLES], by_role


def build_prime(*, rebound_path: Path, pipeline_path: Path, output_dir: Path) -> dict[str, Any]:
    rebound = _json(rebound_path, "rebound request")
    if rebound.get("schema") != REBOUND_SCHEMA:
        raise PrimeError("input is not canonical rebound v1")
    namespace_value = rebound.get("execution", {}).get("bound_namespace_root")
    if not isinstance(namespace_value, str):
        raise PrimeError("rebound request has no bound namespace")
    namespace = Path(namespace_value).expanduser().resolve(strict=False)
    if not namespace.is_absolute() or not namespace.is_dir():
        raise PrimeError("bound namespace must be an existing directory")
    identity = rebound.get("case_identity")
    current = rebound.get("current_binding")
    if not isinstance(identity, Mapping) or not isinstance(current, Mapping):
        raise PrimeError("rebound canonical identity is missing")
    if (identity.get("current_case_index") != 65 or identity.get("physical_case_id") != CANONICAL_ID or
            identity.get("manifest_physical_case_id") != CANONICAL_ID):
        raise PrimeError("rebound request is not canonical CURRENT row 65")
    if identity.get("physical_case_id") == HISTORICAL_ALIAS_ID or current.get("case_index") == 78:
        raise PrimeError("historical row-78 alias cannot enter canonical prime")
    if current.get("sha256") not in (CURRENT_SHA, None):
        raise PrimeError("CURRENT binding is not the pinned df7e source")
    if rebound.get("source_hashes_preverified_by_parent") is not False:
        raise PrimeError("prime must retain deferred parent source hashes")
    raw = rebound.get("raw_binding")
    if not isinstance(raw, Mapping) or raw.get("expected_raw_tree_sha256") != PENDING:
        raise PrimeError("prime requires deferred raw-tree content hash")
    v15 = rebound.get("v15_request")
    if not isinstance(v15, Mapping) or v15.get("source_fallback") not in {"REJECT", "FORBIDDEN"}:
        raise PrimeError("v15 source fallback must be forbidden")
    _assert_no_old_actionable(rebound, namespace)
    pipeline, by_role = _pipeline_entries(pipeline_path, namespace)

    module_values = rebound.get("modules")
    if not isinstance(module_values, Mapping):
        raise PrimeError("rebound module closure is missing")
    module_audit: list[dict[str, Any]] = []
    for role in ("raw_converter", "v14_operator", "v15_operator", "v16_operator", "worker"):
        item = module_values.get(role)
        if not isinstance(item, Mapping):
            raise PrimeError(f"rebound module role missing: {role}")
        target = _target(item.get("path"), role, namespace)
        declared = _declared_sha(item.get("sha256"), role)
        actual = _sha_file(target, role)
        if declared != actual:
            raise PrimeError(f"{role} source SHA differs from target")
        module_audit.append(_audit_old_operator(target, role) if role in {"v14_operator", "v15_operator"}
                            else {"role": role, "path": str(target), "sha256": actual})

    request = {
        "schema": SCHEMA,
        "request_id": "f2-s1-canonical-replay-prime-v1-root-forward-pending",
        "status": "PENDING_PARENT_GUARD_AND_CANONICAL_SEMANTICS",
        "role": "DEVELOPMENT",
        "case_identity": {
            "current_case_index": 65, "family_id": "F2", "physical_case_id": CANONICAL_ID,
            "historical_alias_rejected": HISTORICAL_ALIAS_ID,
            "identity_key": "(Zone,Idp)",
        },
        "source_binding": {
            "rebound_request_path": str(rebound_path.expanduser().resolve()),
            "rebound_request_sha256": _sha_file(rebound_path, "rebound request"),
            "current_sha256": CURRENT_SHA,
            "namespace_root": str(namespace),
            "old_root_open": "FORBIDDEN",
            "source_hash_phase": "AFTER_PARENT_RESERVATION",
        },
        "pipeline": {
            "schema": "ds02.stage2.f2-canonical-pipeline-binding.v1",
            "binding_path": str(pipeline_path.expanduser().resolve()),
            "roles": pipeline,
            "order": ["canonical_adapter", "raw_converter", "reader", "restorer",
                       "worker", "label_producer", "portable_scorer"],
            "raw_payload_read_by_builder": False,
        },
        "legacy_operator_audit": {
            "historical_alias": HISTORICAL_ALIAS_ID,
            "row78": 78,
            "modules": module_audit,
            "canonical_adapter_required": True,
            "legacy_operator_can_be_called_as_canonical": False,
        },
        "execution": {
            "python_policy": "literal_pinned_venv_argv0",
            "command_template": [
                "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
                "-B", "-I", "<copied-worker>", "run", "--request", "<prime-request>",
                "--output-dir", "<fresh-attempt-root>", "--io-slot-approved",
            ],
            "phase_order": ["parent_source_guard", "raw_converter", "canonical_reader",
                            "canonical_restorer", "typed_label", "portable_scorer"],
            "owned_scratch": "parent-attempt namespace only",
            "bounded_logs": True,
            "parent_death_cleanup": True,
            "no_original_path_fallback": True,
        },
        "scientific_contract": {
            "raw_tree_sha256": PENDING,
            "typed_output": "PENDING_PARENT_GUARD",
            "labels": "PENDING_CANONICAL_SEMANTICS_AND_PARENT_GUARD",
            "model_invoked": False, "cfd_invoked": False,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_closure": {
            "modules": module_audit,
            "pipeline": pipeline,
            "required_source_roles": ["current_catalog", "generated_xml", "motion_dat",
                                       "initial_csv", "native_partout", "native_runparts",
                                       "owner_metadata", "gencase_receipt", "solver_receipt"],
            "scientific_sources_are_parent_bound": False,
        },
        "limits": {"max_wall_seconds": 3600, "cpu_threads": 1,
                   "qualification_credit": "NONE_UNTIL_ACTUAL_CANONICAL_CHAIN"},
    }
    request["sha256"] = _canonical(request)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = output_dir / "f2-s1-canonical-replay-prime-request-v1.json"
    if request_path.exists():
        raise PrimeError(f"refusing to overwrite {request_path}")
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "schema": "ds02.stage2.f2-canonical-replay-prime-report.v1",
        "status": request["status"], "metadata_only": True,
        "request": {"path": str(request_path), "sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                     "schema": SCHEMA},
        "canonical": {"current_index": 65, "physical_case_id": CANONICAL_ID,
                      "historical_alias_rejected": HISTORICAL_ALIAS_ID},
        "pipeline_roles": [item["role"] for item in pipeline],
        "legacy_operator_audit": request["legacy_operator_audit"],
        "raw_payload_read_by_builder": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    report["sha256"] = _canonical(report)
    report_path = output_dir / "f2-s1-canonical-replay-prime-report-v1.json"
    if report_path.exists():
        raise PrimeError(f"refusing to overwrite {report_path}")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def validate_prime(path: Path | str) -> dict[str, Any]:
    """Recheck a built prime request using only copied code and JSON metadata."""
    request_path = Path(path).expanduser()
    request = _json(request_path, "prime request")
    if request.get("schema") != SCHEMA:
        raise PrimeError("request is not canonical replay prime v1")
    if request.get("status") != "PENDING_PARENT_GUARD_AND_CANONICAL_SEMANTICS":
        raise PrimeError("prime request status is not deferred")
    if request.get("sha256") != _canonical(request):
        raise PrimeError("prime request canonical SHA is invalid")
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or identity.get("current_case_index") != 65 or identity.get("physical_case_id") != CANONICAL_ID:
        raise PrimeError("prime request identity is not canonical row 65")
    source_binding = request.get("source_binding")
    if not isinstance(source_binding, Mapping) or source_binding.get("current_sha256") != CURRENT_SHA:
        raise PrimeError("prime current source binding is not pinned")
    namespace_value = source_binding.get("namespace_root")
    if not isinstance(namespace_value, str):
        raise PrimeError("prime namespace root is missing")
    namespace = Path(namespace_value).expanduser().resolve(strict=False)
    if not namespace.is_dir():
        raise PrimeError("prime namespace root is not present")
    if request.get("scientific_contract", {}).get("raw_tree_sha256") != PENDING:
        raise PrimeError("prime raw content must remain parent-deferred")
    pipeline = request.get("pipeline", {}).get("roles")
    if not isinstance(pipeline, list) or [item.get("role") for item in pipeline if isinstance(item, Mapping)] != list(PIPELINE_ROLES):
        raise PrimeError("prime pipeline role order is invalid")
    verified_paths: list[str] = []
    for item in pipeline:
        if not isinstance(item, Mapping):
            raise PrimeError("prime pipeline entry is malformed")
        target = _target(item.get("path"), str(item.get("role")), namespace)
        expected = _declared_sha(item.get("sha256"), str(item.get("role")))
        if _sha_file(target, str(item.get("role"))) != expected:
            raise PrimeError(f"prime pipeline source changed: {item.get('role')}")
        verified_paths.append(str(target))
    modules = request.get("source_closure", {}).get("modules")
    if not isinstance(modules, list) or not modules:
        raise PrimeError("prime source closure is missing")
    for item in modules:
        if not isinstance(item, Mapping):
            raise PrimeError("prime module source record is malformed")
        target = _target(item.get("path"), str(item.get("role")), namespace)
        expected = _declared_sha(item.get("sha256"), str(item.get("role")))
        if _sha_file(target, str(item.get("role"))) != expected:
            raise PrimeError(f"prime module source changed: {item.get('role')}")
    rebound_path = source_binding.get("rebound_request_path")
    rebound_sha = source_binding.get("rebound_request_sha256")
    if not isinstance(rebound_path, str) or not isinstance(rebound_sha, str):
        raise PrimeError("prime rebound source binding is incomplete")
    rebound = Path(rebound_path).expanduser()
    if _sha_file(rebound, "rebound request") != rebound_sha:
        raise PrimeError("rebound request source changed")
    return {
        "schema": "ds02.stage2.f2-canonical-replay-prime-validation.v1",
        "status": "PRIME_VALIDATED_SOURCE_ONLY_PARENT_GUARD_REQUIRED",
        "request_path": str(request_path.resolve()),
        "request_sha256": request["sha256"],
        "verified_pipeline_paths": verified_paths,
        "raw_payload_read_by_validator": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--rebound", type=Path, required=True)
    build.add_argument("--pipeline", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "validate":
            result = validate_prime(args.request)
            print(json.dumps(result, sort_keys=True))
            return 0
        report = build_prime(rebound_path=args.rebound, pipeline_path=args.pipeline,
                             output_dir=args.output_dir)
    except (OSError, PrimeError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": report["schema"], "status": report["status"],
                      "request_path": report["request"]["path"],
                      "request_sha256": report["request"]["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
