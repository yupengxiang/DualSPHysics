#!/usr/bin/env python3
"""Read-only intake for the F3 material coarse scheduler terminal result.

This module consumes one already completed scheduler attempt.  It binds the
attempt's ``result.json``, ``spec.json``, ``material.json`` and the artifact
hashes recorded by the scheduler, then checks the execution and material
summary contracts.  It never edits the attempt directory and never opens the
native source HDF5; the source is represented by the SHA claims already
present in the scheduler spec/result/material binding.

The observed run is deliberately a negative diagnostic: its execution receipt
is successful, mass is closed, unknown fractions are monotone, and coverage is
reported, but the maximum unknown fraction is above the 1% gate.  This intake
therefore cannot mint T1/T2 qualification or credit.  The runtime attempt is
ignored by git and is referenced here as a scheduler-owned runtime receipt,
not as a portable static formal receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.material.f3.coarse.terminal_result_intake.v1"
REPORT_SCHEMA = "core.material.f3.coarse.terminal_result_intake_report.v1"
RECORD_ID = "f3-material-coarse-terminal-result-intake-2026-09-29-rerun1"

ATTEMPT_RELATIVE = Path(
    "campaigns/core-v1/runtime/attempts/core-f3-material-coarse-s2-rerun1/"
    "20260929T122016-16ac698caed1"
)
ATTEMPT_ID = ATTEMPT_RELATIVE.name
ATTEMPT_ROOT_ID = ATTEMPT_RELATIVE.parent.name
JOB_ID = "core-f3-material-coarse-s2-rerun1"
LOGICAL_ID = "CORE-F3-MATERIAL-COARSE-s2-RERUN1"
EXPECTED_SOURCE_SNAPSHOT_SHA256 = "1ce54606f2922ac4a2aeb3b04dc97e4d4f70b09541ffd77f2515bdfce5d56e69"
EXPECTED_SOURCE_INPUT_SHA256 = "3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575"
EXPECTED_SOURCE_SNAPSHOT_PATH_SUFFIX = (
    "/campaigns/core-v1/runtime/snapshots/"
    "1ce54606f2922ac4a2aeb3b04dc97e4d4f70b09541ffd77f2515bdfce5d56e69/"
    "lagrangian-fluid-lab"
)
EXPECTED_FRAME_COUNT = 836
EXPECTED_TRANSITION_COUNT = 835
UNKNOWN_LIMIT = 0.01
MASS_CLOSURE_ERROR_LIMIT = 1.0e-12
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

REQUIRED_JSON_FILES = ("result.json", "spec.json", "material.json")
REQUIRED_ARTIFACTS = (
    "material.h5",
    "material.json",
    "material.h5.checkpoint.npz",
    "material.h5.checkpoint.json",
)

DEFAULT_REPORT = Path(
    "reports/F3-MATERIAL-COARSE-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F3-MATERIAL-COARSE-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.zh-CN.md"
)


class IntakeError(ValueError):
    """Raised for malformed bounded intake input."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _reject_constant(token: str) -> Any:
    raise IntakeError(f"non-finite JSON number: {token}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntakeError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and "" not in path.parts


def _assert_no_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError as error:
            raise FileNotFoundError(current) from error
        if os.path.islink(current):
            raise IntakeError(f"symlink component is forbidden: {current}")
        if current != root and current != root / relative and part != relative.parts[-1] and not os.path.isdir(current):
            raise IntakeError(f"non-directory path component: {current}")


def _stable_bytes(path: Path, *, limit: int) -> tuple[bytes | None, dict[str, Any], str | None]:
    """Read one regular file and reject a replacement during the read."""

    try:
        before = os.lstat(path)
    except OSError as error:
        return None, {"path": str(path), "exists": False, "bytes": None, "sha256": None}, f"lstat:{type(error).__name__}"
    if not os.path.isfile(path) or os.path.islink(path):
        return None, {"path": str(path), "exists": True, "bytes": before.st_size, "sha256": None}, "not_a_regular_non_symlink_file"
    if before.st_size > limit:
        return None, {"path": str(path), "exists": True, "bytes": before.st_size, "sha256": None}, "file_exceeds_bound"

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb", closefd=True) as stream:
            raw = stream.read(limit + 1)
            descriptor = os.fstat(stream.fileno())
    except OSError as error:
        return None, {"path": str(path), "exists": True, "bytes": before.st_size, "sha256": None}, f"read:{type(error).__name__}"
    if len(raw) > limit:
        return None, {"path": str(path), "exists": True, "bytes": len(raw), "sha256": None}, "file_exceeds_bound"
    try:
        after = os.lstat(path)
    except OSError as error:
        return None, {"path": str(path), "exists": True, "bytes": len(raw), "sha256": None}, f"post_lstat:{type(error).__name__}"
    stable = (
        descriptor.st_dev == before.st_dev
        and descriptor.st_ino == before.st_ino
        and descriptor.st_size == before.st_size == len(raw)
        and after.st_dev == before.st_dev
        and after.st_ino == before.st_ino
        and after.st_size == before.st_size
        and after.st_mtime_ns == before.st_mtime_ns
        and after.st_ctime_ns == before.st_ctime_ns
    )
    reference = {
        "path": str(path),
        "exists": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_read": True,
    }
    if not stable:
        reference["stable_read"] = False
        return None, reference, "path_changed_during_read"
    reference["stable_read"] = True
    return raw, reference, None


def _read_json(path: Path) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None]:
    raw, reference, error = _stable_bytes(path, limit=MAX_JSON_BYTES)
    if error is not None or raw is None:
        return None, reference, error
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, IntakeError) as exc:
        return None, reference, f"json:{type(exc).__name__}:{exc}"
    if not isinstance(value, Mapping):
        return None, reference, "json:top_level_not_object"
    return value, reference, None


def _attempt_path(root: Path, attempt: str | Path) -> tuple[Path, str]:
    relative = Path(attempt)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise IntakeError("attempt path must be a safe repository-relative path")
    return root / relative, relative.as_posix()


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }


def _required_ref_shape(value: Any, label: str, errors: list[str]) -> None:
    ref = _mapping(value)
    for key in ("path", "bytes", "sha256"):
        if key not in ref:
            errors.append(f"{label}.{key}")
    if not isinstance(ref.get("path"), str) or not ref.get("path"):
        errors.append(f"{label}.path")
    if not isinstance(ref.get("bytes"), int) or isinstance(ref.get("bytes"), bool) or ref.get("bytes", -1) < 0:
        errors.append(f"{label}.bytes")
    if not _sha256(ref.get("sha256")):
        errors.append(f"{label}.sha256")


def _normalize_result_argv(argv: Any, attempt_root: Path) -> list[str] | None:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return None
    output_path = str(attempt_root / "material.h5")
    normalized = ["{attempt_dir}/material.h5" if item == output_path else item for item in argv]
    return normalized


def _source_binding(spec: Mapping[str, Any], result: Mapping[str, Any], material: Mapping[str, Any]) -> dict[str, Any]:
    spec_snapshot = _mapping(spec.get("source_snapshot"))
    result_snapshot = _mapping(result.get("source_snapshot"))
    inputs = spec.get("input_files")
    source_inputs = [
        item for item in inputs if isinstance(item, Mapping) and item.get("role") == "read_only_coarse_native_source"
    ] if isinstance(inputs, list) else []
    source_input = source_inputs[0] if len(source_inputs) == 1 else {}
    material_binding = _mapping(material.get("binding"))
    return {
        "source_snapshot": {
            "path": spec_snapshot.get("path"),
            "sha256": spec_snapshot.get("sha256"),
            "result_path": result_snapshot.get("path"),
            "result_sha256": result_snapshot.get("sha256"),
        },
        "source_input": {
            "path": source_input.get("path"),
            "sha256": source_input.get("sha256"),
            "role": source_input.get("role"),
            "opened": False,
            "read": False,
            "hash_recomputed": False,
        },
        "material_binding_source_sha256": material_binding.get("source_sha256"),
        "input_files": [
            {
                "path": item.get("path"),
                "role": item.get("role"),
                "sha256": item.get("sha256"),
                "hash_recomputed": False,
            }
            for item in inputs
            if isinstance(item, Mapping)
        ] if isinstance(inputs, list) else [],
    }


def _validate_source_binding(
    spec: Mapping[str, Any], result: Mapping[str, Any], material: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    binding = _source_binding(spec, result, material)
    snapshot = binding["source_snapshot"]
    source = binding["source_input"]
    material_sha = binding["material_binding_source_sha256"]
    spec_argv = spec.get("argv")
    result_argv = result.get("argv")
    source_argv_paths = []
    for argv in (spec_argv, result_argv):
        if isinstance(argv, list) and "--source" in argv:
            index = argv.index("--source") + 1
            source_argv_paths.append(argv[index] if index < len(argv) else None)
        else:
            source_argv_paths.append(None)
    checks = [
        _check(
            "source_snapshot_sha_bound",
            snapshot["sha256"] == snapshot["result_sha256"] == EXPECTED_SOURCE_SNAPSHOT_SHA256,
            "result and spec must bind the same current scheduler source snapshot SHA",
            observed={"spec": snapshot["sha256"], "result": snapshot["result_sha256"]},
            expected=EXPECTED_SOURCE_SNAPSHOT_SHA256,
        ),
        _check(
            "source_snapshot_path_bound",
            isinstance(snapshot["path"], str)
            and snapshot["path"] == snapshot["result_path"]
            and snapshot["path"].endswith(EXPECTED_SOURCE_SNAPSHOT_PATH_SUFFIX),
            "result and spec must point at the snapshot directory identified by the snapshot SHA",
            observed={"spec": snapshot["path"], "result": snapshot["result_path"]},
            expected=EXPECTED_SOURCE_SNAPSHOT_PATH_SUFFIX,
        ),
        _check(
            "source_input_sha_bound",
            source["sha256"] == material_sha == EXPECTED_SOURCE_INPUT_SHA256,
            "spec input claim and material binding must retain the native source SHA",
            observed={"spec_input": source["sha256"], "material": material_sha},
            expected=EXPECTED_SOURCE_INPUT_SHA256,
        ),
        _check(
            "source_input_read_boundary",
            source["opened"] is False and source["read"] is False and source["hash_recomputed"] is False,
            "the native source HDF5 is represented by its existing claim only",
            observed={k: source[k] for k in ("opened", "read", "hash_recomputed")},
            expected={"opened": False, "read": False, "hash_recomputed": False},
        ),
        _check(
            "source_input_role_exact",
            source["role"] == "read_only_coarse_native_source",
            "the source input must be the read-only coarse native source",
            observed=source["role"],
            expected="read_only_coarse_native_source",
        ),
        _check(
            "source_input_path_bound",
            source["path"] == source_argv_paths[0] == source_argv_paths[1],
            "the read-only native source path must be identical in the spec input and both argv records",
            observed={"input": source["path"], "spec_argv": source_argv_paths[0], "result_argv": source_argv_paths[1]},
            expected="one identical source path",
        ),
        _check(
            "input_sha_claims_well_formed",
            bool(binding["input_files"])
            and all(_sha256(item.get("sha256")) for item in binding["input_files"]),
            "every scheduler input claim must carry a well-formed SHA-256 without being rehashed here",
            observed=[item.get("sha256") for item in binding["input_files"]],
            expected="64 lowercase hexadecimal characters per input",
        ),
    ]
    return binding, checks


def _validate_execution(
    result: Mapping[str, Any], spec: Mapping[str, Any], attempt_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    required_outputs = spec.get("required_outputs")
    result_outputs = result.get("outputs")
    result_argv = _normalize_result_argv(result.get("argv"), attempt_root)
    spec_argv = spec.get("argv")
    checks = [
        _check(
            "execution_receipt_success",
            result.get("schema") == "core.execution_receipt.v1"
            and result.get("execution_status") == "succeeded"
            and result.get("returncode") == 0
            and result.get("error") is None
            and result.get("timeout") is False
            and result.get("missing_outputs") == [],
            "scheduler execution receipt must be a successful, non-timeout, zero-return run",
            observed={
                "schema": result.get("schema"),
                "execution_status": result.get("execution_status"),
                "returncode": result.get("returncode"),
                "error": result.get("error"),
                "timeout": result.get("timeout"),
                "missing_outputs": result.get("missing_outputs"),
            },
            expected={"schema": "core.execution_receipt.v1", "execution_status": "succeeded", "returncode": 0},
        ),
        _check(
            "scheduler_job_identity",
            result.get("job_id") == spec.get("job_id") == JOB_ID,
            "result and spec must carry the registered scheduler job identity",
            observed={"result_job_id": result.get("job_id"), "spec_job_id": spec.get("job_id")},
            expected=JOB_ID,
        ),
        _check(
            "scheduler_attempt_identity",
            ATTEMPT_ID == ATTEMPT_RELATIVE.name
            and ATTEMPT_ROOT_ID == ATTEMPT_RELATIVE.parent.name
            and _mapping(spec.get("namespace")).get("attempt_id_source") == "scheduler_generated"
            and _mapping(spec.get("namespace")).get("attempt_root") == ATTEMPT_RELATIVE.parent.as_posix()
            and _mapping(spec.get("namespace")).get("template") == ATTEMPT_RELATIVE.parent.as_posix() + "/<fresh-attempt-id>"
            and _mapping(spec.get("namespace")).get("fresh_required") is True
            and _mapping(spec.get("namespace")).get("historical_reuse_forbidden") is True,
            "the intake must point to the scheduler-generated attempt directory, not a static output namespace",
            observed={"attempt_id": ATTEMPT_ID, "attempt_root": _mapping(spec.get("namespace")).get("attempt_root"), "namespace": _mapping(spec.get("namespace"))},
            expected={"attempt_root": ATTEMPT_RELATIVE.parent.as_posix(), "attempt_id_source": "scheduler_generated", "fresh_required": True},
        ),
        _check(
            "required_outputs_complete",
            isinstance(required_outputs, list)
            and set(required_outputs) == set(REQUIRED_ARTIFACTS)
            and isinstance(result_outputs, list)
            and {item.get("path") for item in result_outputs if isinstance(item, Mapping)} >= set(REQUIRED_ARTIFACTS),
            "the spec and successful result must retain every required material artifact",
            observed={"spec_required_outputs": required_outputs, "result_output_paths": result_outputs},
            expected=list(REQUIRED_ARTIFACTS),
        ),
        _check(
            "argv_cwd_bound",
            result_argv is not None
            and spec_argv == result_argv
            and spec.get("cwd") == str(LAB_ROOT)
            and result_argv[0] == str(LAB_ROOT / ".venv/bin/python"),
            "result argv must normalize exactly to the scheduler spec and current lab cwd",
            observed={"spec_argv": spec_argv, "result_argv_normalized": result_argv, "cwd": spec.get("cwd")},
            expected={"cwd": str(LAB_ROOT), "output": "{attempt_dir}/material.h5"},
        ),
    ]
    execution = {
        "schema": result.get("schema"),
        "status": result.get("execution_status"),
        "returncode": result.get("returncode"),
        "timeout": result.get("timeout"),
        "missing_outputs": result.get("missing_outputs"),
        "job_id": result.get("job_id"),
        "attempt_id": ATTEMPT_ID,
        "logical_id": spec.get("logical_id"),
        "argv": result_argv,
        "cwd": spec.get("cwd"),
        "scientific_status": result.get("scientific_status"),
    }
    return execution, checks


def _material_projection(material: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    by_source = material.get("by_source")
    rows = by_source if isinstance(by_source, list) else []
    row_projection: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, row_value in enumerate(rows):
        row = _mapping(row_value)
        categories = _mapping(row.get("terminal_categories"))
        category_values = {key: categories.get(key) for key in ("left", "right", "unknown")}
        category_sum = sum(float(value) for value in category_values.values()) if all(_finite_number(value) for value in category_values.values()) else None
        row_projection.append(
            {
                "source": row.get("source"),
                "initial_mass_fraction": row.get("initial_mass_fraction"),
                "mass_closure_fraction": row.get("mass_closure_fraction"),
                "mass_closure_error": row.get("mass_closure_error"),
                "terminal_categories": category_values,
                "terminal_category_sum": category_sum,
                "unknown_fraction": row.get("unknown_fraction"),
                "unknown_fraction_max": row.get("unknown_fraction_max"),
                "unknown_first_passage_fraction_max": row.get("unknown_first_passage_fraction_max"),
                "unknown_fraction_monotone": row.get("unknown_fraction_monotone"),
                "reliable_path_coverage": row.get("reliable_path_coverage"),
                "terminal_mass_vector_length": len(row.get("terminal", [])) if isinstance(row.get("terminal"), list) else None,
                "terminal_upper_vector_length": len(row.get("terminal_upper", [])) if isinstance(row.get("terminal_upper"), list) else None,
            }
        )
        if row.get("source") != index:
            errors.append(f"source_row_{index}.source")

    source_ids = [row.get("source") for row in row_projection]
    mass_rows_valid = len(row_projection) == 2 and source_ids == [0, 1]
    per_source_mass = all(
        _finite_number(row.get("mass_closure_fraction"))
        and abs(float(row["mass_closure_fraction"]) - 1.0) <= MASS_CLOSURE_ERROR_LIMIT
        and _finite_number(row.get("mass_closure_error"))
        and abs(float(row["mass_closure_error"])) <= MASS_CLOSURE_ERROR_LIMIT
        and _finite_number(row.get("terminal_category_sum"))
        and abs(float(row["terminal_category_sum"]) - 1.0) <= MASS_CLOSURE_ERROR_LIMIT
        and row.get("terminal_mass_vector_length") == 2
        and row.get("terminal_upper_vector_length") == 2
        for row in row_projection
    )
    unknown_values = [row.get("unknown_fraction_max") for row in row_projection]
    unknown_values_valid = bool(unknown_values) and all(_finite_number(value) and 0.0 <= float(value) <= 1.0 for value in unknown_values)
    unknown_max = max((float(value) for value in unknown_values), default=None) if unknown_values_valid else None
    coverage_values = [row.get("reliable_path_coverage") for row in row_projection]
    coverage_valid = bool(coverage_values) and all(_finite_number(value) and 0.0 <= float(value) <= 1.0 for value in coverage_values)
    coverage_max = max((float(value) for value in coverage_values), default=None) if coverage_valid else None
    weights = [row.get("initial_mass_fraction") for row in row_projection]
    weighted_coverage = (
        sum(float(weight) * float(row["reliable_path_coverage"]) for weight, row in zip(weights, row_projection))
        if coverage_valid and all(_finite_number(weight) for weight in weights)
        else None
    )
    top_coverage = material.get("common_reliable_path_coverage")
    projection = {
        "schema": material.get("binding", {}).get("schema") if isinstance(material.get("binding"), Mapping) else None,
        "status": material.get("status"),
        "material_reliability": material.get("material_reliability"),
        "qualification_claim": material.get("qualification_claim"),
        "qualified_T2_macro": material.get("qualified_T2_macro"),
        "qualified_T2_path": material.get("qualified_T2_path"),
        "native_frame_count": material.get("native_frame_count"),
        "committed_frame": material.get("committed_frame"),
        "transition_count": material.get("native_frame_count") - 1 if isinstance(material.get("native_frame_count"), int) else None,
        "committed_transition": material.get("committed_frame"),
        "committed_time_s": material.get("committed_time_s"),
        "source_count": len(row_projection),
        "sources": row_projection,
        "unknown_fraction_max": unknown_max,
        "unknown_fraction_limit": UNKNOWN_LIMIT,
        "common_reliable_path_coverage": top_coverage,
        "coverage_weighted_from_sources": weighted_coverage,
        "coverage_max_by_source": coverage_max,
        "mass_closed": material.get("mass_closed"),
        "unknown_fraction_monotone": material.get("unknown_fraction_monotone"),
        "unknown_gate_pass": material.get("unknown_gate_pass"),
    }
    checks = [
        _check(
            "material_status_completed",
            material.get("status") == "completed",
            "material sidecar must be terminally completed",
            observed=material.get("status"),
            expected="completed",
        ),
        _check(
            "full_frame_transition_semantics",
            material.get("native_frame_count") == EXPECTED_FRAME_COUNT
            and material.get("committed_frame") == EXPECTED_TRANSITION_COUNT
            and material.get("native_frame_count") - 1 == EXPECTED_TRANSITION_COUNT,
            "the terminal result must preserve all 836 native frames and 835 transitions",
            observed={"native_frame_count": material.get("native_frame_count"), "committed_frame": material.get("committed_frame")},
            expected={"native_frame_count": EXPECTED_FRAME_COUNT, "transition_count": EXPECTED_TRANSITION_COUNT},
        ),
        _check(
            "mass_closure",
            material.get("mass_closed") is True and mass_rows_valid and per_source_mass,
            "top-level and per-source terminal masses must close within the diagnostic bound",
            observed={"mass_closed": material.get("mass_closed"), "rows": row_projection},
            expected={"mass_closed": True, "absolute_error_max": MASS_CLOSURE_ERROR_LIMIT},
        ),
        _check(
            "unknown_monotonicity",
            material.get("unknown_fraction_monotone") is True
            and bool(row_projection)
            and all(row.get("unknown_fraction_monotone") is True for row in row_projection),
            "top-level and every source must explicitly report monotone unknown accumulation",
            observed={"top": material.get("unknown_fraction_monotone"), "per_source": [row.get("unknown_fraction_monotone") for row in row_projection]},
            expected=True,
        ),
        _check(
            "unknown_gate",
            unknown_values_valid
            and material.get("unknown_gate_pass") is (unknown_max is not None and unknown_max <= UNKNOWN_LIMIT),
            "the 1% unknown gate must be internally consistent with the observed maximum",
            observed={"max": unknown_max, "limit": UNKNOWN_LIMIT, "declared_pass": material.get("unknown_gate_pass")},
            expected={"max_at_most": UNKNOWN_LIMIT, "declared_pass": False},
        ),
        _check(
            "coverage",
            _finite_number(top_coverage)
            and 0.0 <= float(top_coverage) <= 1.0
            and coverage_valid
            and weighted_coverage is not None
            and abs(float(top_coverage) - weighted_coverage) <= MASS_CLOSURE_ERROR_LIMIT,
            "common reliable coverage must be bounded and agree with the source-mass-weighted coverage",
            observed={"top": top_coverage, "weighted_from_sources": weighted_coverage, "per_source": coverage_values},
            expected="finite [0,1] and weighted aggregate",
        ),
        _check(
            "diagnostic_non_qualification_boundary",
            material.get("qualification_claim") == "none"
            and material.get("qualified_T2_macro") is False
            and material.get("qualified_T2_path") is False,
            "the worker result must not claim T2 qualification",
            observed={"qualification_claim": material.get("qualification_claim"), "qualified_T2_macro": material.get("qualified_T2_macro"), "qualified_T2_path": material.get("qualified_T2_path")},
            expected={"qualification_claim": "none", "qualified_T2_macro": False, "qualified_T2_path": False},
        ),
    ]
    errors.extend(
        check["check"] for check in checks if not check["passed"] and check["check"] not in {"unknown_gate"}
    )
    return projection, checks, errors


def _artifact_projection(
    root: Path, attempt_root: Path, result: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    entries = result.get("artifact_index")
    if not isinstance(entries, list):
        return [], [], ["artifact_index.not_list"]
    declared_paths: set[str] = set()
    projection: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, entry_value in enumerate(entries):
        entry = _mapping(entry_value)
        path_value = entry.get("path")
        path = Path(path_value) if isinstance(path_value, str) else Path("__invalid__")
        if not isinstance(path_value, str) or not _safe_relative(path_value) or path_value in declared_paths:
            errors.append(f"artifact_index[{index}].path")
            continue
        declared_paths.add(path_value)
        actual_path = attempt_root / path
        raw, actual, read_error = _stable_bytes(actual_path, limit=MAX_ARTIFACT_BYTES)
        declared_bytes = entry.get("bytes")
        declared_sha = entry.get("sha256")
        actual_match = (
            read_error is None
            and raw is not None
            and declared_bytes == actual.get("bytes")
            and declared_sha == actual.get("sha256")
            and _sha256(declared_sha)
        )
        projection.append(
            {
                "path": path_value,
                "declared_bytes": declared_bytes,
                "declared_sha256": declared_sha,
                "actual_bytes": actual.get("bytes"),
                "actual_sha256": actual.get("sha256"),
                "stable_read": actual.get("stable_read") is True,
                "read_error": read_error,
                "hash_match": actual_match,
            }
        )
        if not actual_match:
            errors.append(f"artifact_index[{index}].hash")
    required_present = {item["path"] for item in projection} >= set(REQUIRED_ARTIFACTS)
    checks = [
        _check(
            "artifact_hashes_bound",
            bool(entries) and not errors and required_present and all(item["hash_match"] for item in projection),
            "every scheduler artifact-index hash must match the stable read of the existing attempt artifact",
            observed={"artifact_count": len(projection), "required_present": required_present, "errors": errors},
            expected={"required_artifacts": list(REQUIRED_ARTIFACTS)},
        )
    ]
    return projection, checks, errors


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "launch_admitted": False,
        "qualification": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "credit": 0,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "attempt_opened_for_write": False,
        "attempt_mutations": 0,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "artifact_hashes_recomputed": True,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
    }


def build_report(root: Path = LAB_ROOT, attempt: str | Path = ATTEMPT_RELATIVE) -> dict[str, Any]:
    root = Path(root).resolve()
    try:
        attempt_root, attempt_relative = _attempt_path(root, attempt)
    except (IntakeError, OSError) as error:
        attempt_root = root / ATTEMPT_RELATIVE
        attempt_relative = ATTEMPT_RELATIVE.as_posix()
        path_error = f"{type(error).__name__}:{error}"
    else:
        path_error = None

    values: dict[str, Mapping[str, Any]] = {}
    file_refs: dict[str, dict[str, Any]] = {}
    load_errors: list[str] = []
    for name in REQUIRED_JSON_FILES:
        value, reference, error = _read_json(attempt_root / name)
        reference = dict(reference)
        reference["path"] = _relative(root, attempt_root / name)
        reference["role"] = f"scheduler_attempt_{name.removesuffix('.json')}"
        file_refs[name] = reference
        if value is None:
            load_errors.append(f"{name}:{error or 'missing'}")
        else:
            values[name] = value

    result = values.get("result.json", {})
    spec = values.get("spec.json", {})
    material = values.get("material.json", {})
    source_binding, source_checks = _validate_source_binding(spec, result, material)
    execution, execution_checks = _validate_execution(result, spec, attempt_root)
    material_projection, material_checks, material_errors = _material_projection(material)
    artifacts, artifact_checks, artifact_errors = _artifact_projection(root, attempt_root, result)
    all_checks = source_checks + execution_checks + artifact_checks + material_checks
    all_errors = load_errors + material_errors + artifact_errors
    all_passed_except_expected_negative = all(check["passed"] for check in all_checks if check["check"] != "unknown_gate")
    unknown_check = next((check for check in material_checks if check["check"] == "unknown_gate"), {"passed": False})
    unknown_max = material_projection.get("unknown_fraction_max")
    unknown_negative = (
        unknown_max is not None
        and float(unknown_max) > UNKNOWN_LIMIT
        and unknown_check.get("passed") is True
        and material.get("unknown_gate_pass") is False
    )
    if not all_passed_except_expected_negative or not unknown_negative or path_error is not None:
        status = "blocked_fail_closed"
    else:
        status = "negative_diagnostic"
    if not unknown_negative:
        all_errors.append("unknown_gate.negative_diagnostic_missing_or_inconsistent")

    report = {
        "schema": REPORT_SCHEMA,
        "record_id": RECORD_ID,
        "created_at": "2026-09-29",
        "status": status,
        "scope": {
            "family": "F3",
            "direction": "material",
            "candidate": "CORE-F3-MATERIAL-COARSE-s2-RERUN1",
            "job_id": JOB_ID,
            "logical_id": LOGICAL_ID,
            "attempt_id": ATTEMPT_ID,
            "attempt_root_id": ATTEMPT_ROOT_ID,
        },
        "runtime_reference": {
            "attempt_path": attempt_relative,
            "scheduler_owned": True,
            "repository_tracked": False,
            "portable_artifact": False,
            "static_formal_receipt": False,
            "classification": "scheduler_owned_runtime_receipt_reference_not_static_formal_receipt",
            "path_is_metadata_only_for_this_report": True,
            "historical_attempt_reused": False,
            "attempt_opened_for_write": False,
        },
        "input_bindings": {
            "result_json": file_refs.get("result.json", {"path": _relative(root, attempt_root / "result.json")}),
            "spec_json": file_refs.get("spec.json", {"path": _relative(root, attempt_root / "spec.json")}),
            "material_json": file_refs.get("material.json", {"path": _relative(root, attempt_root / "material.json")}),
            "source": source_binding,
        },
        "artifact_hashes": {
            "scheduler_artifact_index": artifacts,
            "hashes_recomputed_from_existing_attempt": True,
            "source_hdf5_hash_recomputed": False,
        },
        "scheduler_identity": {
            "attempt_id": ATTEMPT_ID,
            "attempt_root_id": ATTEMPT_ROOT_ID,
            "job_id": execution.get("job_id"),
            "spec_job_id": spec.get("job_id"),
            "logical_id": execution.get("logical_id"),
            "attempt_id_source": _mapping(spec.get("namespace")).get("attempt_id_source"),
            "attempt_role": spec.get("attempt_role"),
            "host": spec.get("host"),
        },
        "execution_receipt": execution,
        "material_terminal": material_projection,
        "validation": {
            "checks": all_checks,
            "errors": list(dict.fromkeys(all_errors)),
            "unknown_gate_negative_diagnostic": {
                "recorded": unknown_negative,
                "observed_unknown_fraction_max": unknown_max,
                "limit": UNKNOWN_LIMIT,
                "above_one_percent": bool(unknown_max is not None and float(unknown_max) > UNKNOWN_LIMIT),
                "message": "unknown_fraction_max exceeds 1%; retain as negative diagnostic and do not promote.",
            },
            "path_error": path_error,
        },
        "authorization": _authorization(),
        "execution_controls": _execution_controls(),
        "next_safe_action": "Use the negative diagnostic to refine the F3 material coarse setup; do not promote this receipt or mutate Core state.",
    }
    return report


def validate_report(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return ["report.not_object"]
    if value.get("schema") != REPORT_SCHEMA:
        errors.append("report.schema")
    if value.get("record_id") != RECORD_ID:
        errors.append("report.record_id")
    if value.get("status") not in {"negative_diagnostic", "blocked_fail_closed"}:
        errors.append("report.status")
    scope = _mapping(value.get("scope"))
    if (
        scope.get("family") != "F3"
        or scope.get("direction") != "material"
        or scope.get("job_id") != JOB_ID
        or scope.get("attempt_id") != ATTEMPT_ID
        or scope.get("attempt_root_id") != ATTEMPT_ROOT_ID
    ):
        errors.append("report.scope")
    runtime = _mapping(value.get("runtime_reference"))
    expected_runtime = {
        "scheduler_owned": True,
        "repository_tracked": False,
        "portable_artifact": False,
        "static_formal_receipt": False,
        "classification": "scheduler_owned_runtime_receipt_reference_not_static_formal_receipt",
        "historical_attempt_reused": False,
        "attempt_opened_for_write": False,
    }
    for key, expected in expected_runtime.items():
        if runtime.get(key) != expected:
            errors.append(f"report.runtime_reference.{key}")
    if runtime.get("attempt_path") != ATTEMPT_RELATIVE.as_posix():
        errors.append("report.runtime_reference.attempt_path")
    bindings = _mapping(value.get("input_bindings"))
    for name in ("result_json", "spec_json", "material_json"):
        _required_ref_shape(bindings.get(name), f"input_bindings.{name}", errors)
        ref = _mapping(bindings.get(name))
        filename = name.replace("_json", ".json")
        if ref.get("path") != (ATTEMPT_RELATIVE / filename).as_posix():
            errors.append(f"input_bindings.{name}.path_binding")
        if ref.get("content_read") is not True or ref.get("stable_read") is not True:
            errors.append(f"input_bindings.{name}.stable_read")
    source = _mapping(bindings.get("source"))
    snapshot = _mapping(source.get("source_snapshot"))
    source_input = _mapping(source.get("source_input"))
    if snapshot.get("sha256") != snapshot.get("result_sha256") or snapshot.get("sha256") != EXPECTED_SOURCE_SNAPSHOT_SHA256:
        errors.append("input_bindings.source.snapshot_sha256")
    if source_input.get("sha256") != source.get("material_binding_source_sha256") or source_input.get("sha256") != EXPECTED_SOURCE_INPUT_SHA256:
        errors.append("input_bindings.source.input_sha256")
    if any(source_input.get(key) is not False for key in ("opened", "read", "hash_recomputed")):
        errors.append("input_bindings.source.read_boundary")
    artifacts = _mapping(value.get("artifact_hashes"))
    artifact_rows = artifacts.get("scheduler_artifact_index")
    if not isinstance(artifact_rows, list) or not artifact_rows:
        errors.append("artifact_hashes.scheduler_artifact_index")
    else:
        seen: set[str] = set()
        for index, row_value in enumerate(artifact_rows):
            row = _mapping(row_value)
            path = row.get("path")
            if not _safe_relative(path) or path in seen:
                errors.append(f"artifact_hashes[{index}].path")
            seen.add(path)
            if row.get("hash_match") is not True or row.get("stable_read") is not True:
                errors.append(f"artifact_hashes[{index}].hash_match")
            if row.get("declared_bytes") != row.get("actual_bytes") or row.get("declared_sha256") != row.get("actual_sha256"):
                errors.append(f"artifact_hashes[{index}].declared_actual")
            if not _sha256(row.get("declared_sha256")):
                errors.append(f"artifact_hashes[{index}].sha256")
        if set(REQUIRED_ARTIFACTS) - seen:
            errors.append("artifact_hashes.required_artifacts")
    execution_controls = _mapping(value.get("execution_controls"))
    for key in (
        "attempt_opened_for_write", "source_hdf5_opened", "source_hdf5_read", "source_hdf5_hash_recomputed",
        "solver_started", "worker_started", "gpu_started", "queue_started",
    ):
        if execution_controls.get(key) is not False:
            errors.append(f"execution_controls.{key}")
    for key in ("attempt_mutations", "registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "completion_mutations"):
        if execution_controls.get(key) != 0:
            errors.append(f"execution_controls.{key}")
    authorization = _mapping(value.get("authorization"))
    for key, expected in _authorization().items():
        if authorization.get(key) != expected:
            errors.append(f"authorization.{key}")
    validation = _mapping(value.get("validation"))
    material = _mapping(value.get("material_terminal"))
    if material.get("native_frame_count") != EXPECTED_FRAME_COUNT:
        errors.append("material_terminal.native_frame_count")
    if material.get("committed_frame") != EXPECTED_TRANSITION_COUNT:
        errors.append("material_terminal.committed_frame")
    if material.get("transition_count") != EXPECTED_TRANSITION_COUNT:
        errors.append("material_terminal.transition_count")
    if material.get("committed_transition") != EXPECTED_TRANSITION_COUNT:
        errors.append("material_terminal.committed_transition")
    if material.get("unknown_fraction_limit") != UNKNOWN_LIMIT:
        errors.append("material_terminal.unknown_fraction_limit")
    material_unknown = material.get("unknown_fraction_max")
    if not _finite_number(material_unknown) or float(material_unknown) <= UNKNOWN_LIMIT:
        errors.append("material_terminal.unknown_fraction_max")
    material_coverage = material.get("common_reliable_path_coverage")
    if not _finite_number(material_coverage) or not 0.0 <= float(material_coverage) <= 1.0:
        errors.append("material_terminal.common_reliable_path_coverage")
    checks = validation.get("checks")
    if not isinstance(checks, list):
        errors.append("validation.checks")
        checks = []
    check_map = {item.get("check"): item for item in checks if isinstance(item, Mapping)}
    required_true = (
        "source_snapshot_sha_bound", "source_snapshot_path_bound", "source_input_sha_bound", "source_input_read_boundary", "source_input_role_exact", "source_input_path_bound", "input_sha_claims_well_formed",
        "execution_receipt_success", "scheduler_job_identity", "scheduler_attempt_identity", "required_outputs_complete",
        "argv_cwd_bound", "artifact_hashes_bound", "material_status_completed", "full_frame_transition_semantics",
        "mass_closure", "unknown_monotonicity", "coverage", "diagnostic_non_qualification_boundary",
    )
    for name in required_true:
        if _mapping(check_map.get(name)).get("passed") is not True:
            errors.append(f"validation.checks.{name}")
    unknown_check = _mapping(check_map.get("unknown_gate"))
    unknown_negative = _mapping(validation.get("unknown_gate_negative_diagnostic"))
    if unknown_check.get("passed") is not True:
        errors.append("validation.checks.unknown_gate_contract")
    if unknown_negative.get("recorded") is not True or unknown_negative.get("above_one_percent") is not True:
        errors.append("validation.unknown_gate_negative_diagnostic")
    observed_unknown = unknown_negative.get("observed_unknown_fraction_max")
    if not _finite_number(observed_unknown) or float(observed_unknown) <= UNKNOWN_LIMIT:
        errors.append("validation.unknown_gate_negative_diagnostic.value")
    if validation.get("errors") and value.get("status") == "negative_diagnostic":
        errors.append("report.negative_diagnostic_has_unexpected_errors")
    if value.get("status") == "negative_diagnostic" and validation.get("path_error") is not None:
        errors.append("report.path_error")
    return list(dict.fromkeys(errors))


def render_zh_cn(value: Mapping[str, Any]) -> str:
    material = _mapping(value.get("material_terminal"))
    negative = _mapping(_mapping(value.get("validation")).get("unknown_gate_negative_diagnostic"))
    execution = _mapping(value.get("execution_receipt"))
    return "\n".join(
        [
            "# F3 material coarse terminal-result intake RERUN1",
            "",
            f"- 状态：`{value.get('status')}`（仅诊断；不授予 T1/T2/credit）。",
            f"- scheduler job：`{execution.get('job_id')}`；attempt：`{execution.get('attempt_id')}`。",
            f"- execution receipt：`{execution.get('status')}`，return code=`{execution.get('returncode')}`。",
            f"- 完整时域：`{material.get('native_frame_count')}` native frames / `{material.get('committed_frame')}` transitions。",
            f"- mass closure：`{next((item.get('passed') for item in _mapping(value.get('validation')).get('checks', []) if item.get('check') == 'mass_closure'), False)}`。",
            f"- unknown monotonicity：`{next((item.get('passed') for item in _mapping(value.get('validation')).get('checks', []) if item.get('check') == 'unknown_monotonicity'), False)}`。",
            f"- unknown gate：最大 unknown=`{negative.get('observed_unknown_fraction_max')}`，阈值=`{negative.get('limit')}`；明确记录为 `negative diagnostic`（超过 1%）。",
            f"- common reliable coverage：`{material.get('common_reliable_path_coverage')}`。",
            "",
            "该路径位于 git 忽略的 scheduler runtime 下；本报告只是 scheduler-owned runtime receipt 引用，不是可携带的静态 formal receipt。",
            "本 intake 只读绑定 result/spec/material JSON 与 scheduler artifact hashes；未读取或重算 native source HDF5，未修改 runtime attempt、历史 receipt、registry、ledger、denominator、gate 或 completion。",
            "",
        ]
    )


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("invalid terminal-result intake: " + ", ".join(errors))
    path = Path(output)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("invalid terminal-result intake: " + ", ".join(errors))
    path = Path(output)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zh_cn(value), encoding="utf-8")
    return path


def _load_report(path: Path) -> Mapping[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    if not isinstance(value, Mapping):
        raise ValueError("report must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, default=ATTEMPT_RELATIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        errors = validate_report(_load_report(args.verify))
        if errors:
            for error in errors:
                print(error)
            return 2
        print(f"valid: {args.verify}")
        return 0
    report = build_report(LAB_ROOT, args.attempt)
    write_report(report, args.output)
    write_zh_cn(report, args.zh_output)
    print(f"wrote {args.output}")
    print(f"wrote {args.zh_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
