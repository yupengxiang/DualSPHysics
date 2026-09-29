#!/usr/bin/env python3
"""Bounded, non-authorizing readiness projection for F3 coarse s2/s4.

The existing root/scheduler intake is the source of truth for the future
fresh-root and scheduler-owned host-I/O receipts.  This sidecar only makes
the coarse s2/s4 choice explicit and current-bound: it checks both small job
specifications, the exact source-hash claim, normalized argv/cwd, and the
current scheduler-owned ``core_runtime`` entry points.  Missing external
receipts remain a hard, fail-closed blocker.

No production HDF5 content is opened, read, or rehashed.  The sidecar never
starts, stops, restarts, or queues a worker, solver, GPU, or runtime, and it
never mutates registry, ledger, denominator, gate, completion, or PLAN state.
Even a complete future receipt pair would remain a diagnostic, zero-credit
readiness observation.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_material_coarse_root_scheduler_intake_v1 as intake


LAB_ROOT = Path(__file__).resolve().parents[1]
CREATED_AT = "2026-09-29"

SCHEMA = "core.material.f3.coarse.s2_s4.readiness.v1"
RECORD_ID = "f3-material-coarse-s2-s4-readiness-v1"
STATUS_BLOCKED = "blocked_fail_closed"
STATUS_READY = "ready_non_authorizing"

S2_SPEC = intake.JOB_SPEC
S4_SPEC = Path("campaigns/core-v1/material/jobs/core-f3-material-coarse-s4.json")
DEFAULT_REPORT = Path(
    "reports/F3-MATERIAL-COARSE-S2-S4-READINESS-2026-09-29-RERUN1.json"
)
DEFAULT_ZH_CN = Path(
    "reports/F3-MATERIAL-COARSE-S2-S4-READINESS-2026-09-29-RERUN1.zh-CN.md"
)

S2_JOB_ID = "core-f3-material-coarse-s2"
S4_JOB_ID = "core-f3-material-coarse-s4"
S2_LOGICAL_ID = "CORE-F3-MATERIAL-COARSE-s2"
S4_LOGICAL_ID = "CORE-F3-MATERIAL-COARSE-s4"

HASH_KEYS = tuple(intake.HASH_KEYS)
SHA256 = intake.SHA256


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dedupe(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in result:
            result.append(text)
    return result


def _read_spec(
    root: Path, path: Path, *, role: str
) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None]:
    value, reference, error = intake._read_json_document(
        root, intake._resolve(root, path), role=role
    )
    return value, reference, error


def _normalize_argv(root: Path, spec: Mapping[str, Any], label: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    argv = spec.get("argv")
    expected_python = str(root / ".venv/bin/python")
    expected_script = str(root / "scripts/core_material.py")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        return {}, [f"{label}.argv"]
    if len(argv) < 2 or argv[0] != expected_python or argv[1] != expected_script:
        errors.append(f"{label}.argv.entrypoint")
    normalized = [expected_python, "-m", "scripts.core_material", *argv[2:]]
    substeps_index = normalized.index("--substeps") + 1 if "--substeps" in normalized else -1
    substeps = normalized[substeps_index] if substeps_index > 0 and substeps_index < len(normalized) else None
    if substeps not in {"2", "4"}:
        errors.append(f"{label}.argv.substeps")
    if "--source" not in normalized or "--output" not in normalized:
        errors.append(f"{label}.argv.required_flags")
    else:
        source_index = normalized.index("--source") + 1
        output_index = normalized.index("--output") + 1
        if source_index >= len(normalized) or output_index >= len(normalized):
            errors.append(f"{label}.argv.flag_values")
        elif normalized[output_index] != "{attempt_dir}/material.h5":
            errors.append(f"{label}.argv.output")
    result = {
        "cwd": spec.get("cwd"),
        "argv": normalized,
        "resume_argv_same_attempt": [*normalized, "--resume"],
        "full_native_window": True,
        "stop_after": None,
        "output": "{attempt_dir}/material.h5",
        "substeps": int(substeps) if substeps in {"2", "4"} else None,
    }
    if result["cwd"] != str(root):
        errors.append(f"{label}.cwd")
    return result, errors


def _source_input(root: Path, spec: Mapping[str, Any], label: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    expected_path = str(root / intake.SOURCE_H5)
    items = spec.get("input_files")
    if not isinstance(items, list):
        return {}, [f"{label}.input_files"]
    matches = [item for item in items if isinstance(item, Mapping) and item.get("path") == expected_path]
    if len(matches) != 1:
        return {}, [f"{label}.source_input_count"]
    item = matches[0]
    source = {
        "path": item.get("path"),
        "sha256": item.get("sha256"),
        "opened_as_hdf5": False,
        "read": False,
        "hash_recomputed": False,
    }
    if source["sha256"] != _mapping(item).get("sha256") or not isinstance(source["sha256"], str):
        errors.append(f"{label}.source_input_sha256")
    if not isinstance(source["sha256"], str) or SHA256.fullmatch(source["sha256"]) is None:
        errors.append(f"{label}.source_input_sha256_format")
    return source, errors


def _runtime_scheduler_contract(root: Path, current_ref: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check only bounded source text for the scheduler-owned entry surface."""

    errors: list[str] = []
    path = intake._resolve(root, intake.CORE_RUNTIME)
    try:
        raw, metadata = intake._read_bounded(
            path,
            label="current scheduler-owned core_runtime",
            limit=intake.MAX_SMALL_FILE_BYTES,
        )
        source = raw.decode("utf-8", errors="strict")
        tree = ast.parse(source, filename=str(path))
    except (ValueError, SyntaxError, UnicodeDecodeError, OSError) as error:
        return {
            "path": str(intake.CORE_RUNTIME),
            "sha256": current_ref.get("sha256"),
            "bytes": current_ref.get("bytes"),
            "read_bounded_source": False,
            "entrypoints": {},
            "markers": {},
            "checks": {"bounded_parse": False, "current_hash_bound": False, "scheduler_owned_entry_surface": False},
            "error": f"{type(error).__name__}:{error}",
        }, ["scheduler_entry_contract.parse"]

    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(source, node)
            functions[node.name] = segment or ""

    required_entrypoints = (
        "choose_resources",
        "scheduler_binding",
        "validate_scheduler_binding",
        "consume_scheduler_reservation",
        "prepare_launch",
        "launch",
    )
    required_markers = (
        "SCHEDULER_BINDING_SCHEMA",
        "RESERVATION_CONSUME_SCHEMA",
        "consume_scheduler_reservation",
        "check_runtime_identity=True",
        "_reservation_id",
        "_host_hostname",
        "_host_boot_id",
    )
    entrypoints = {name: name in functions for name in required_entrypoints}
    markers = {marker: marker in source for marker in required_markers}
    checks = {
        "bounded_parse": True,
        "current_hash_bound": current_ref.get("sha256") == metadata.get("sha256"),
        "scheduler_owned_entry_surface": all(entrypoints.values()) and all(markers.values()),
        "prepare_consumes_one_shot": "consume_scheduler_reservation" in functions.get("prepare_launch", ""),
        "worker_revalidates_runtime_identity": "check_runtime_identity=True" in functions.get("worker", ""),
    }
    if checks["current_hash_bound"] is not True:
        errors.append("scheduler_entry_contract.current_hash")
    if checks["scheduler_owned_entry_surface"] is not True:
        errors.append("scheduler_entry_contract.entry_surface")
    if checks["prepare_consumes_one_shot"] is not True:
        errors.append("scheduler_entry_contract.one_shot_consume")
    if checks["worker_revalidates_runtime_identity"] is not True:
        errors.append("scheduler_entry_contract.runtime_identity")
    return {
        "path": str(intake.CORE_RUNTIME),
        "sha256": current_ref.get("sha256"),
        "bytes": current_ref.get("bytes"),
        "read_bounded_source": True,
        "entrypoints": entrypoints,
        "markers": markers,
        "checks": checks,
        "metadata_sha256": metadata.get("sha256"),
    }, errors


def _spec_projection(
    root: Path,
    s2: Mapping[str, Any] | None,
    s2_ref: Mapping[str, Any],
    s4: Mapping[str, Any] | None,
    s4_ref: Mapping[str, Any],
    base: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    s2 = s2 if isinstance(s2, Mapping) else {}
    s4 = s4 if isinstance(s4, Mapping) else {}
    s2_norm, s2_argv_errors = _normalize_argv(root, s2, "s2")
    s4_norm, s4_argv_errors = _normalize_argv(root, s4, "s4")
    errors.extend(s2_argv_errors)
    errors.extend(s4_argv_errors)
    s2_source, s2_source_errors = _source_input(root, s2, "s2")
    s4_source, s4_source_errors = _source_input(root, s4, "s4")
    errors.extend(s2_source_errors)
    errors.extend(s4_source_errors)

    base_projection = _mapping(base.get("binding_projection"))
    base_hashes = _mapping(base_projection.get("hashes"))
    expected_source_sha = base_hashes.get("source_sha256")
    expected_resources = intake._resource_request(s2)
    expected_common = {
        "category": "material_qualification_diagnostic",
        "host": "ada",
        "cwd": str(root),
        "resources": expected_resources,
        "seeds": "512",
        "neighbour_variant": "baseline24",
    }

    checks = {
        "s2_spec_contract_valid": (
            s2.get("job_id") == S2_JOB_ID
            and s2.get("logical_id") == S2_LOGICAL_ID
            and all(s2.get(key) == value for key, value in expected_common.items() if key != "seeds" and key != "neighbour_variant")
            and s2_norm.get("substeps") == 2
            and "--seeds" in s2_norm.get("argv", [])
            and s2_norm["argv"][s2_norm["argv"].index("--seeds") + 1] == "512"
            and "--neighbour-variant" in s2_norm.get("argv", [])
            and s2_norm["argv"][s2_norm["argv"].index("--neighbour-variant") + 1] == "baseline24"
        ),
        "s4_spec_contract_valid": (
            s4.get("job_id") == S4_JOB_ID
            and s4.get("logical_id") == S4_LOGICAL_ID
            and all(s4.get(key) == value for key, value in expected_common.items() if key != "seeds" and key != "neighbour_variant")
            and s4_norm.get("substeps") == 4
            and "--seeds" in s4_norm.get("argv", [])
            and s4_norm["argv"][s4_norm["argv"].index("--seeds") + 1] == "512"
            and "--neighbour-variant" in s4_norm.get("argv", [])
            and s4_norm["argv"][s4_norm["argv"].index("--neighbour-variant") + 1] == "baseline24"
        ),
        "shared_source_binding_valid": (
            s2_source.get("path") == str(root / intake.SOURCE_H5)
            and s4_source.get("path") == s2_source.get("path")
            and s2_source.get("sha256") == s4_source.get("sha256") == expected_source_sha
            and s2_source.get("opened_as_hdf5") is False
            and s4_source.get("opened_as_hdf5") is False
            and s2_source.get("read") is False
            and s4_source.get("read") is False
            and s2_source.get("hash_recomputed") is False
            and s4_source.get("hash_recomputed") is False
        ),
        "shared_cwd_valid": s2_norm.get("cwd") == s4_norm.get("cwd") == str(root),
        "normalized_s2_argv_cwd_valid": s2_norm.get("cwd") == str(root)
        and s2_norm.get("substeps") == 2
        and s2_norm.get("argv") == _mapping(base_projection.get("normalized_launch")).get("argv"),
        "normalized_s4_argv_cwd_valid": s4_norm.get("cwd") == str(root)
        and s4_norm.get("substeps") == 4,
        "s2_s4_coarse_lineage_valid": (
            s2.get("input_files") == s4.get("input_files")
            and s2.get("resources") == s4.get("resources")
            and s2.get("cwd") == s4.get("cwd")
            and s2_norm.get("argv", [])[: s2_norm.get("argv", []).index("--substeps")] == s4_norm.get("argv", [])[: s4_norm.get("argv", []).index("--substeps")]
        ),
    }
    for key, value in checks.items():
        if value is not True:
            errors.append(f"s2_s4.{key}")
    projection = {
        "s2": {
            "path": s2_ref.get("path"),
            "bytes": s2_ref.get("bytes"),
            "sha256": s2_ref.get("sha256"),
            "job_id": s2.get("job_id"),
            "logical_id": s2.get("logical_id"),
            "normalized_launch": s2_norm,
            "source": s2_source,
        },
        "s4": {
            "path": s4_ref.get("path"),
            "bytes": s4_ref.get("bytes"),
            "sha256": s4_ref.get("sha256"),
            "job_id": s4.get("job_id"),
            "logical_id": s4.get("logical_id"),
            "normalized_launch": s4_norm,
            "source": s4_source,
        },
        "shared_source_sha256": expected_source_sha,
        "shared_resource_request": expected_resources,
        "checks": checks,
    }
    return projection, errors


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "qualification_credit": 0,
        "T2_credit": 0,
        "credit": 0,
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "bounded_metadata_only": True,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "worker_started": False,
        "solver_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    s4_spec_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the current-bound s2/s4 readiness report without launching anything."""

    root_path = Path(os.path.abspath(os.fspath(root)))
    base = intake.build_report(root_path)
    base_errors = list(intake.validate_report(base))
    s2, s2_ref, s2_error = _read_spec(root_path, S2_SPEC, role="current F3 coarse s2 job specification")
    s4_path = Path(s4_spec_path) if s4_spec_path is not None else S4_SPEC
    s4, s4_ref, s4_error = _read_spec(root_path, s4_path, role="current F3 coarse s4 job specification")
    s2_s4_projection, s2_s4_errors = _spec_projection(
        root_path, s2, s2_ref, s4, s4_ref, base
    )
    runtime_contract, runtime_errors = _runtime_scheduler_contract(
        root_path, _mapping(base.get("input_bindings")).get("current_core_runtime", {})
    )

    base_validation = _mapping(base.get("validation"))
    base_checks = _mapping(base_validation.get("checks"))
    base_blockers = base_validation.get("blockers", [])
    if not isinstance(base_blockers, list):
        base_blockers = []
    blockers: list[str] = []
    blockers.extend(f"base_intake:{item}" for item in base_errors)
    blockers.extend(f"base_intake:{item}" for item in base_blockers)
    if s2_error:
        blockers.append(f"s2_spec:{s2_error}")
    if s4_error:
        blockers.append(f"s4_spec:{s4_error}")
    blockers.extend(s2_s4_errors)
    blockers.extend(runtime_errors)

    fresh_observation = _mapping(base.get("receipt_observations")).get("fresh_root", {})
    scheduler_observation = _mapping(base.get("receipt_observations")).get("scheduler", {})
    namespace_projection = _mapping(base.get("binding_projection"))
    proposal_namespace = _mapping(namespace_projection.get("proposal_namespace_contract"))
    fresh_namespace = {
        "required": True,
        "single_use_required": True,
        "historical_reuse_forbidden": proposal_namespace.get("historical_attempt_reuse_forbidden") is True,
        "proposal_namespace": dict(proposal_namespace),
        "receipt_namespace": dict(namespace_projection.get("fresh_attempt_namespace", {})),
        "receipt_namespace_sha256": namespace_projection.get("fresh_attempt_namespace_sha256"),
        "present": _mapping(fresh_observation).get("present") is True,
        "valid": base_checks.get("fresh_attempt_namespace_valid") is True,
    }
    host_io = {
        "required": True,
        "admission_contract_valid": base_checks.get("host_io_admission_contract_valid") is True,
        "scheduler_receipt_path": _mapping(base.get("input_bindings")).get("scheduler_host_io_reservation", {}).get("path"),
        "scheduler_receipt_present": _mapping(scheduler_observation).get("present") is True,
        "scheduler_reservation_valid": base_checks.get("scheduler_owned_host_io_reservation_valid") is True,
        "scheduler_owned_io_verified": namespace_projection.get("scheduler_owned_host_io_verified") is True,
        "resource_request": s2_s4_projection.get("shared_resource_request", {}),
        "reservation": dict(_mapping(scheduler_observation).get("scheduler_reservation", {})),
    }

    current_bindings = _mapping(base.get("input_bindings"))
    root_intake_ref = current_bindings.get("scheduler_host_io_reservation", {})
    root_report_path = intake.DEFAULT_REPORT
    root_report_file = root_path / root_report_path
    try:
        _, root_report_metadata = intake._read_bounded(
            root_report_file,
            label="current root/scheduler intake report",
            limit=intake.MAX_JSON_BYTES,
        )
        root_report_ref = {
            "path": str(root_report_path),
            "exists": True,
            "bytes": root_report_metadata["bytes"],
            "sha256": root_report_metadata["sha256"],
        }
    except intake.IntakeError as error:
        root_report_ref = {
            "path": str(root_report_path),
            "exists": False,
            "bytes": None,
            "sha256": None,
            "error": error.code,
        }

    checks = {
        "base_root_scheduler_intake_valid": base_checks.get("intake_contract_valid") is True and not base_errors,
        "s2_s4_spec_contract_valid": all(
            s2_s4_projection.get("checks", {}).get(key) is True
            for key in (
                "s2_spec_contract_valid",
                "s4_spec_contract_valid",
                "shared_source_binding_valid",
                "shared_cwd_valid",
                "normalized_s2_argv_cwd_valid",
                "normalized_s4_argv_cwd_valid",
                "s2_s4_coarse_lineage_valid",
            )
        ),
        "scheduler_entry_contract_valid": all(runtime_contract.get("checks", {}).values()),
        "current_source_sha_bound": isinstance(s2_s4_projection.get("shared_source_sha256"), str)
        and SHA256.fullmatch(str(s2_s4_projection.get("shared_source_sha256"))) is not None,
        "normalized_argv_cwd_bound": s2_s4_projection.get("checks", {}).get("normalized_s2_argv_cwd_valid") is True
        and s2_s4_projection.get("checks", {}).get("normalized_s4_argv_cwd_valid") is True,
        "fresh_one_shot_namespace_verified": fresh_namespace["valid"],
        "scheduler_host_io_reservation_verified": host_io["scheduler_reservation_valid"],
    }
    checks["readiness_contract_valid"] = all(checks.values())
    if checks["fresh_one_shot_namespace_verified"] is not True:
        blockers.append("fresh_one_shot_namespace_missing_or_unverified")
    if checks["scheduler_host_io_reservation_verified"] is not True:
        blockers.append("scheduler_owned_host_io_reservation_missing_or_unverified")
    if not checks["base_root_scheduler_intake_valid"]:
        blockers.append("base_root_scheduler_intake_not_bound")

    blockers = _dedupe(blockers)
    status = STATUS_READY if checks["readiness_contract_valid"] else STATUS_BLOCKED
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "status": status,
        "candidate": {
            "family": "F3",
            "source_role": "coarse",
            "s2_job_id": S2_JOB_ID,
            "s4_job_id": S4_JOB_ID,
            "preferred_first_candidate": S2_LOGICAL_ID,
        },
        "input_bindings": {
            "root_scheduler_intake": root_report_ref,
            "s2_job_spec": dict(s2_ref),
            "s4_job_spec": dict(s4_ref),
            "core_material": dict(current_bindings.get("current_core_material", {})),
            "core_runtime": dict(current_bindings.get("current_core_runtime", {})),
            "source_h5": dict(current_bindings.get("source_h5", {})),
            "host_io_admission": dict(current_bindings.get("host_io_admission", {})),
            "scheduler_host_io_reservation": dict(current_bindings.get("scheduler_host_io_reservation", {})),
        },
        "base_intake": {
            "path": str(root_report_path),
            "status": base.get("status"),
            "validation_checks": dict(base_checks),
            "blockers": list(base_blockers),
        },
        "spec_projection": s2_s4_projection,
        "scheduler_entry_contract": runtime_contract,
        "fresh_one_shot_namespace": fresh_namespace,
        "host_io_reservation": host_io,
        "validation": {
            "checks": checks,
            "blockers": blockers,
            "base_intake_errors": base_errors,
            "s2_spec_error": s2_error,
            "s4_spec_error": s4_error,
        },
        "authorization": _authorization(),
        "execution_controls": _execution_controls(),
        "next_safe_action": (
            "Obtain a real fresh root admission receipt and a scheduler-owned host-I/O reservation, "
            "cross-bind both to the current source SHA, s2 argv/cwd, and a new one-shot attempt namespace, "
            "then rerun the existing root/scheduler intake before any worker launch."
        ),
    }


def validate_report(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_top = {
        "schema",
        "record_id",
        "created_at",
        "status",
        "candidate",
        "input_bindings",
        "base_intake",
        "spec_projection",
        "scheduler_entry_contract",
        "fresh_one_shot_namespace",
        "host_io_reservation",
        "validation",
        "authorization",
        "execution_controls",
        "next_safe_action",
    }
    if not isinstance(value, Mapping) or set(value) != expected_top:
        return ["report.fields"]
    if value.get("schema") != SCHEMA:
        errors.append("schema")
    if value.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if value.get("created_at") != CREATED_AT:
        errors.append("created_at")
    if value.get("status") not in {STATUS_BLOCKED, STATUS_READY}:
        errors.append("status")
    if dict(_mapping(value.get("authorization"))) != _authorization():
        errors.append("authorization.fail_closed")
    if dict(_mapping(value.get("execution_controls"))) != _execution_controls():
        errors.append("execution_controls.boundary")

    bindings = _mapping(value.get("input_bindings"))
    expected_binding_names = {
        "root_scheduler_intake",
        "s2_job_spec",
        "s4_job_spec",
        "core_material",
        "core_runtime",
        "source_h5",
        "host_io_admission",
        "scheduler_host_io_reservation",
    }
    if set(bindings) != expected_binding_names:
        errors.append("input_bindings.fields")
    for name in expected_binding_names:
        ref = _mapping(bindings.get(name))
        if not isinstance(ref.get("path"), str) or not ref.get("path"):
            errors.append(f"input_bindings.{name}.path")
        if ref.get("exists") is True:
            if not isinstance(ref.get("bytes"), int) or ref.get("bytes") < 1:
                errors.append(f"input_bindings.{name}.bytes")
            if not isinstance(ref.get("sha256"), str) or SHA256.fullmatch(ref.get("sha256")) is None:
                errors.append(f"input_bindings.{name}.sha256")

    source = _mapping(bindings.get("source_h5"))
    for key in ("opened_as_hdf5", "read", "hash_recomputed"):
        if source.get(key) is not False:
            errors.append(f"input_bindings.source_h5.{key}")
    if not isinstance(source.get("sha256"), str) or SHA256.fullmatch(source.get("sha256")) is None:
        errors.append("input_bindings.source_h5.sha256")

    projection = _mapping(value.get("spec_projection"))
    if set(projection) != {"s2", "s4", "shared_source_sha256", "shared_resource_request", "checks"}:
        errors.append("spec_projection.fields")
    for name in ("s2", "s4"):
        row = _mapping(projection.get(name))
        for key in ("path", "bytes", "sha256", "job_id", "logical_id", "normalized_launch", "source"):
            if key not in row:
                errors.append(f"spec_projection.{name}.{key}")
    if not isinstance(projection.get("shared_source_sha256"), str) or SHA256.fullmatch(projection.get("shared_source_sha256")) is None:
        errors.append("spec_projection.shared_source_sha256")
    spec_checks = _mapping(projection.get("checks"))
    required_spec_checks = {
        "s2_spec_contract_valid",
        "s4_spec_contract_valid",
        "shared_source_binding_valid",
        "shared_cwd_valid",
        "normalized_s2_argv_cwd_valid",
        "normalized_s4_argv_cwd_valid",
        "s2_s4_coarse_lineage_valid",
    }
    if set(spec_checks) != required_spec_checks or any(type(spec_checks.get(key)) is not bool for key in required_spec_checks):
        errors.append("spec_projection.checks")

    runtime = _mapping(value.get("scheduler_entry_contract"))
    runtime_checks = _mapping(runtime.get("checks"))
    required_runtime_checks = {
        "bounded_parse",
        "current_hash_bound",
        "scheduler_owned_entry_surface",
        "prepare_consumes_one_shot",
        "worker_revalidates_runtime_identity",
    }
    if set(runtime_checks) != required_runtime_checks or any(type(runtime_checks.get(key)) is not bool for key in required_runtime_checks):
        errors.append("scheduler_entry_contract.checks")
    if not isinstance(runtime.get("sha256"), str) or SHA256.fullmatch(runtime.get("sha256")) is None:
        errors.append("scheduler_entry_contract.sha256")

    namespace = _mapping(value.get("fresh_one_shot_namespace"))
    for key in (
        "required",
        "single_use_required",
        "historical_reuse_forbidden",
        "proposal_namespace",
        "receipt_namespace",
        "receipt_namespace_sha256",
        "present",
        "valid",
    ):
        if key not in namespace:
            errors.append(f"fresh_one_shot_namespace.{key}")
    if namespace.get("required") is not True or namespace.get("single_use_required") is not True:
        errors.append("fresh_one_shot_namespace.required")
    if namespace.get("historical_reuse_forbidden") is not True:
        errors.append("fresh_one_shot_namespace.reuse_policy")
    if namespace.get("valid") is True and not namespace.get("present") is True:
        errors.append("fresh_one_shot_namespace.present")

    host_io = _mapping(value.get("host_io_reservation"))
    for key in (
        "required",
        "admission_contract_valid",
        "scheduler_receipt_path",
        "scheduler_receipt_present",
        "scheduler_reservation_valid",
        "scheduler_owned_io_verified",
        "resource_request",
        "reservation",
    ):
        if key not in host_io:
            errors.append(f"host_io_reservation.{key}")
    if host_io.get("required") is not True:
        errors.append("host_io_reservation.required")
    if host_io.get("scheduler_reservation_valid") is True and host_io.get("scheduler_receipt_present") is not True:
        errors.append("host_io_reservation.present")

    validation = _mapping(value.get("validation"))
    if set(validation) != {"checks", "blockers", "base_intake_errors", "s2_spec_error", "s4_spec_error"}:
        errors.append("validation.fields")
    checks = _mapping(validation.get("checks"))
    required_checks = {
        "base_root_scheduler_intake_valid",
        "s2_s4_spec_contract_valid",
        "scheduler_entry_contract_valid",
        "current_source_sha_bound",
        "normalized_argv_cwd_bound",
        "fresh_one_shot_namespace_verified",
        "scheduler_host_io_reservation_verified",
        "readiness_contract_valid",
    }
    if set(checks) != required_checks or any(type(checks.get(key)) is not bool for key in required_checks):
        errors.append("validation.checks")
    for key in ("blockers", "base_intake_errors"):
        if not isinstance(validation.get(key), list) or any(not isinstance(item, str) for item in validation.get(key, [])):
            errors.append(f"validation.{key}")
    for key in ("s2_spec_error", "s4_spec_error"):
        if validation.get(key) is not None and not isinstance(validation.get(key), str):
            errors.append(f"validation.{key}")
    if value.get("status") == STATUS_READY:
        if checks.get("readiness_contract_valid") is not True or validation.get("blockers") != []:
            errors.append("status.ready_contract")
    else:
        if checks.get("readiness_contract_valid") is not False or not validation.get("blockers"):
            errors.append("status.blocked_contract")
    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid readiness report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def render_zh_cn(value: Mapping[str, Any]) -> str:
    checks = _mapping(_mapping(value.get("validation")).get("checks"))
    namespace = _mapping(value.get("fresh_one_shot_namespace"))
    host_io = _mapping(value.get("host_io_reservation"))
    projection = _mapping(value.get("spec_projection"))
    s2 = _mapping(projection.get("s2"))
    s4 = _mapping(projection.get("s4"))
    blockers = _mapping(value.get("validation")).get("blockers", [])
    lines = [
        "# F3 material coarse s2/s4 readiness",
        "",
        f"- Schema：`{value.get('schema')}`",
        f"- 状态：`{value.get('status')}`",
        f"- 首选顺序：`{_mapping(value.get('candidate')).get('preferred_first_candidate')}`",
        "",
        "## 当前绑定",
        "",
        f"- s2 spec：`{s2.get('path')}`，sha256=`{s2.get('sha256')}`，substeps=`{_mapping(s2.get('normalized_launch')).get('substeps')}`",
        f"- s4 spec：`{s4.get('path')}`，sha256=`{s4.get('sha256')}`，substeps=`{_mapping(s4.get('normalized_launch')).get('substeps')}`",
        f"- shared source SHA：`{projection.get('shared_source_sha256')}`；source content opened/read/rehash=`False/False/False`",
        f"- argv/cwd binding：`{checks.get('normalized_argv_cwd_bound')}`",
        f"- scheduler-owned core_runtime entry：`{checks.get('scheduler_entry_contract_valid')}`",
        "",
        "## 未满足的外部条件",
        "",
        f"- fresh one-shot namespace：present=`{namespace.get('present')}`，verified=`{namespace.get('valid')}`",
        f"- scheduler host-I/O reservation：present=`{host_io.get('scheduler_receipt_present')}`，verified=`{host_io.get('scheduler_reservation_valid')}`",
        "",
        "本 sidecar 只做 bounded metadata/preflight；不铸造 launch capability，不增加 T1/T2 或 formal credit。",
        "未启动、停止或重启 worker/solver/GPU/queue；未写 registry、ledger、denominator、gate、completion 或 PLAN。",
        "",
        "## 阻塞原因",
        "",
    ]
    lines.extend(f"- `{item}`" for item in blockers)
    lines.append("")
    return "\n".join(lines)


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid readiness report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zh_cn(value), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--s4-spec", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-cn-output", type=Path, default=DEFAULT_ZH_CN)
    args = parser.parse_args(argv)
    report = build_report(args.root, s4_spec_path=args.s4_spec)
    write_report(report, args.output)
    write_zh_cn(report, args.zh_cn_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 0 if report["status"] == STATUS_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
