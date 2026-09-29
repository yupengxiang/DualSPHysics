#!/usr/bin/env python3
"""Audit the read-only F8 R008 preflight-to-Core diagnostic boundary.

The CPU/native preflight is an immutable, zero-credit one-shot.  This module
does not consume it as a solver run and does not manufacture a trajectory from
the initial BI4/native decode.  It only verifies the existing receipts and
static bridge contracts, measures observed diagnostic artifact coverage, and
returns a fail-closed coverage report.

No native executable, solver, worker, queue, GPU, HDF5, or BI4 parser is
called here.  The small artifact references below are checked by size and
SHA-256; binary payloads are not interpreted.  The report writer is additive
and writes only its explicitly supplied report paths.  It never writes the
formal registry, ledger, gate, denominator, or PLAN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Sequence


LAB = Path(__file__).resolve().parents[1]
CASE_REL = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008"
)
PREFLIGHT_REL = CASE_REL / "cpu-native-preflight-v3/receipt.json"
POSTRUN_AUDIT_REL = CASE_REL / "cpu-native-postrun-audit-v1/receipt.json"
SYSCALL_SELECTOR_REL = Path("reports/F8-R008-SYSCALL-SELECTOR-DOMAIN-V1.json")
SYSCALL_CLOSURE_REL = Path("reports/F8-R008-SYSCALL-STATIC-CLOSURE-V1.json")
TRAJECTORY_FILENAME = "core-trajectory-v1.h5"
TABLE_FILENAME = "native-fluid-frame-table-v2.h5"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCHEMA = "core.cfd.f8.r008_preflight_diagnostic_coverage_audit.v1"
REPORT_RECORD_ID = "f8-r008-preflight-diagnostic-coverage-audit-v1"
REPORT_DATE = "2026-09-29"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class CoverageAuditError(ValueError):
    """The immutable preflight-to-diagnostic boundary is malformed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CoverageAuditError(message)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise CoverageAuditError("audit value is not canonical JSON") from error


def _strict_json(raw: bytes, label: str) -> Any:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES,
             f"{label} is outside the bounded JSON size")

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value}")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise CoverageAuditError(f"{label} is not strict UTF-8 JSON") from error
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def _resolve(root: Path, relative: str | os.PathLike[str]) -> tuple[Path, str]:
    root = Path(root).resolve()
    candidate = Path(relative)
    _require(not candidate.is_absolute(), f"audit path must be relative: {relative}")
    resolved = (root / candidate).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise CoverageAuditError(f"audit path escapes the laboratory root: {relative}") from error
    return resolved, resolved.relative_to(root).as_posix()


def _regular_file(path: Path, label: str, *, max_bytes: int | None = None) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise CoverageAuditError(f"{label} cannot be inspected") from error
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
             f"{label} must be a single-link regular file")
    if max_bytes is not None:
        _require(info.st_size <= max_bytes,
                 f"{label} exceeds the bounded read size")
    return info


def _hash_file(path: Path, label: str, *, max_bytes: int | None = None) -> dict[str, Any]:
    info = _regular_file(path, label, max_bytes=max_bytes)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = _regular_file(path, label, max_bytes=max_bytes)
    _require(
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        f"{label} changed while being hashed",
    )
    return {
        "path": path.as_posix(),
        "bytes": info.st_size,
        "sha256": digest.hexdigest(),
    }


def _load_json(root: Path, relative: str | os.PathLike[str], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path, normalized = _resolve(root, relative)
    _regular_file(path, label, max_bytes=MAX_JSON_BYTES)
    raw = path.read_bytes()
    value = _strict_json(raw, label)
    reference = _hash_file(path, label, max_bytes=MAX_JSON_BYTES)
    reference["path"] = normalized
    return value, reference


def _actual_reference(root: Path, relative: str | os.PathLike[str], label: str,
                      *, max_bytes: int | None = None) -> dict[str, Any]:
    path, normalized = _resolve(root, relative)
    reference = _hash_file(path, label, max_bytes=max_bytes)
    reference["path"] = normalized
    return reference


def _declared_reference(root: Path, item: Any, label: str,
                        *, max_bytes: int | None = None) -> dict[str, Any]:
    _require(isinstance(item, Mapping), f"{label} is not an artifact reference")
    path_value = item.get("path")
    _require(type(path_value) is str and path_value and not Path(path_value).is_absolute(),
             f"{label} path is not a safe laboratory-relative path")
    actual = _actual_reference(root, path_value, label, max_bytes=max_bytes)
    _require(type(item.get("bytes")) is int and not isinstance(item.get("bytes"), bool)
             and item["bytes"] == actual["bytes"],
             f"{label} byte binding differs from the immutable file")
    _require(type(item.get("sha256")) is str and SHA256_RE.fullmatch(item["sha256"])
             and item["sha256"] == actual["sha256"],
             f"{label} SHA-256 binding differs from the immutable file")
    result = dict(actual)
    if isinstance(item.get("role"), str):
        result["role"] = item["role"]
    return result


def _source_reference(root: Path, relative: str, label: str) -> dict[str, Any]:
    return _actual_reference(root, relative, label, max_bytes=MAX_SOURCE_BYTES)


def _read_source(root: Path, relative: str, label: str) -> tuple[str, dict[str, Any]]:
    path, normalized = _resolve(root, relative)
    _regular_file(path, label, max_bytes=MAX_SOURCE_BYTES)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CoverageAuditError(f"{label} is not UTF-8 source") from error
    reference = _hash_file(path, label, max_bytes=MAX_SOURCE_BYTES)
    reference["path"] = normalized
    return text, reference


def _reference_key(reference: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return reference.get("path"), reference.get("bytes"), reference.get("sha256")


def _validate_execution_controls(receipt: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "cpu_gencase_invocation_attempted": True,
        "cpu_gencase_invoked": True,
        "denominator_mutation": 0,
        "gpu_invoked": False,
        "ledger_mutation": 0,
        "native_decode_invocation_attempted": True,
        "native_decode_invoked": True,
        "qualification_credit": 0,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "solver_invoked": False,
        "training_started": False,
        "worker_started": False,
    }
    observed = receipt.get("execution_controls")
    _require(observed == expected, "R008 preflight execution_controls changed")
    return dict(observed)


def _validate_resource_scope(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = receipt.get("resource_scope")
    _require(isinstance(value, Mapping), "R008 preflight resource_scope is missing")
    _require(value.get("cpu_only") is True and value.get("gpu") is False
             and value.get("max_concurrent_native_processes") == 1
             and value.get("memory_max_bytes") == 4 * 1024**3
             and value.get("cap_pressure_or_oom_fails_preflight") is True,
             "R008 preflight resource boundary is not the reviewed CPU-only envelope")
    return {
        "cpu_only": value["cpu_only"],
        "gpu": value["gpu"],
        "max_concurrent_native_processes": value["max_concurrent_native_processes"],
        "memory_max_bytes": value["memory_max_bytes"],
        "cap_pressure_or_oom_fails_preflight": value["cap_pressure_or_oom_fails_preflight"],
    }


def _validate_preflight(
    root: Path,
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    _require(receipt.get("schema") == "core.cfd.f8.r008_cpu_native_preflight.v1",
             "unexpected R008 CPU/native preflight schema")
    _require(receipt.get("scope_id") == SCOPE_ID
             and receipt.get("status") == "cpu_native_preflight_passed_zero_credit"
             and receipt.get("qualification_claim") == "none"
             and receipt.get("qualification_credit") == 0,
             "R008 preflight is not the immutable passed zero-credit state")
    controls = _validate_execution_controls(receipt)
    resource = _validate_resource_scope(receipt)
    _require(request.get("schema") == "core.cfd.f8.r008_cpu_native_preflight_request.v3",
             "R008 preflight request is not the immutable v3 request")
    target = request.get("target_case")
    _require(isinstance(target, Mapping)
             and type(target.get("case_id")) is str
             and target.get("qualification_only") is True,
             "R008 preflight request target case is malformed")
    case_id = target["case_id"]
    inputs = receipt.get("input")
    _require(isinstance(inputs, Mapping), "R008 preflight input bindings are missing")
    evidence: list[dict[str, Any]] = []
    for name in ("definition", "control"):
        expected = target.get(name)
        observed = inputs.get(name)
        _require(isinstance(expected, Mapping) and isinstance(observed, Mapping),
                 f"R008 preflight {name} binding is missing")
        _require(
            (observed.get("path"), observed.get("bytes"), observed.get("sha256"))
            == (expected.get("path"), expected.get("bytes"), expected.get("sha256")),
            f"R008 preflight {name} binding differs from the immutable request",
        )
        evidence.append(_declared_reference(root, observed, f"preflight {name}"))

    generated = receipt.get("generated_audit")
    native = receipt.get("native_audit")
    _require(isinstance(generated, Mapping) and generated.get("pass") is True
             and generated.get("missing_artifacts") == [],
             "R008 generated-geometry audit is not a closed pass")
    _require(isinstance(native, Mapping) and native.get("pass") is True,
             "R008 native initial audit is not a closed pass")
    required_artifacts = generated.get("required_artifacts")
    _require(isinstance(required_artifacts, Mapping),
             "R008 generated artifact inventory is missing")
    for name, item in required_artifacts.items():
        evidence.append(_declared_reference(root, item, f"preflight generated artifact {name}"))
    native_refs = native.get("native", {})
    _require(isinstance(native_refs, Mapping)
             and isinstance(native_refs.get("boundary_normals"), Mapping),
             "R008 native boundary-normal reference is missing")
    evidence.append(_declared_reference(
        root, native_refs["boundary_normals"], "preflight boundary normals",
    ))

    for stage_name in ("gencase", "native_decode"):
        stage = receipt.get(stage_name)
        _require(isinstance(stage, Mapping)
                 and stage.get("resource_gate_pass") is True
                 and stage.get("native_return_code") == 0
                 and stage.get("scope_process_tree_clean") is True
                 and stage.get("timed_out") is False,
                 f"R008 preflight {stage_name} stage is not a closed pass")
        for ref_name in ("log", "metrics_receipt"):
            evidence.append(_declared_reference(
                root, stage[ref_name], f"preflight {stage_name} {ref_name}",
            ))

    for ref_name in ("request", "authorization", "one_shot_lock"):
        evidence.append(_declared_reference(
            root, receipt[ref_name], f"preflight {ref_name}",
        ))
    return case_id, {
        "schema": receipt["schema"],
        "status": receipt["status"],
        "qualification_claim": receipt["qualification_claim"],
        "qualification_credit": receipt["qualification_credit"],
        "execution_controls": controls,
        "resource_scope": resource,
        "generated_geometry_pass": generated["pass"],
        "native_initial_pass": native["pass"],
        "fluid_particles": native["native"].get("fluid_particles"),
        "total_particles": native["native"].get("total_particles"),
        "native_initial_root": native["native"].get("decoded_arrays"),
    }, evidence


def _validate_postrun_audit(
    root: Path,
    audit: Mapping[str, Any],
    preflight_reference: Mapping[str, Any],
) -> dict[str, Any]:
    _require(audit.get("schema") == "core.cfd.f8.r008_cpu_native_postrun_audit.v1"
             and audit.get("status")
             == "cpu_native_preflight_verified_zero_credit_no_solver_authorized"
             and audit.get("qualification_claim") == "none"
             and audit.get("qualification_credit") == 0,
             "R008 postrun audit is not the immutable zero-credit closure")
    source = audit.get("source_receipt")
    _require(isinstance(source, Mapping)
             and _reference_key(source) == _reference_key(preflight_reference),
             "R008 postrun audit does not bind the immutable preflight receipt")
    boundary = audit.get("execution_boundary")
    _require(isinstance(boundary, Mapping)
             and boundary.get("gencase_invocations_confirmed") == 1
             and boundary.get("native_decode_invocations_confirmed") == 1
             and boundary.get("solver_invoked") is False
             and boundary.get("worker_started") is False
             and boundary.get("gpu_invoked") is False
             and boundary.get("registry_mutation") == 0
             and boundary.get("ledger_mutation") == 0
             and boundary.get("queue_mutation") == 0
             and boundary.get("denominator_mutation") == 0
             and boundary.get("same_input_retry_forbidden") is True,
             "R008 postrun execution boundary is not fail-closed")
    return {
        "schema": audit["schema"],
        "status": audit["status"],
        "qualification_credit": audit["qualification_credit"],
        "execution_boundary": dict(boundary),
        "verified_reference_count": audit.get("verified_reference_count"),
    }


def _source_contracts(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    paths = {
        "trajectory_adapter": "scripts/f8_r008_core_trajectory_adapter_v1.py",
        "postrun_case_bridge": "scripts/f8_r008_postrun_case_worker_v1.py",
        "postrun_matrix_bridge": "scripts/f8_r008_postrun_matrix_worker_v1.py",
        "native_table_contract": "scripts/f8_r008_native_fluid_table_v2.py",
        "observation_selector": "scripts/f8_observation_window_parser_v2.py",
    }
    source_data: dict[str, str] = {}
    references: list[dict[str, Any]] = []
    for name, relative in paths.items():
        source_data[name], reference = _read_source(root, relative, name)
        references.append(reference)

    trajectory = source_data["trajectory_adapter"]
    case_bridge = source_data["postrun_case_bridge"]
    matrix_bridge = source_data["postrun_matrix_bridge"]
    table_contract = source_data["native_table_contract"]
    selector = source_data["observation_selector"]
    preflight_tokens = ("cpu-native-preflight-v3", "cpu_native_preflight")
    contracts = {
        "trajectory_adapter": {
            "schema": "core.cfd.f8.r008_core_trajectory_adapter.v1",
            "requires_verified_native_fluid_table": "verify_native_fluid_table_fd" in trajectory,
            "requires_raw_source_frame_factory": "source_frames_factory" in trajectory
            and "NativeSourceFrame" in trajectory,
            "requires_at_least_two_time_rows": "2 <= time_count" in trajectory,
            "preflight_receipt_consumer": any(token in trajectory for token in preflight_tokens),
            "formal_eligible_hard_false": '"formal_eligible": False' in trajectory,
            "qualification_credit_hard_zero": '"qualification_credit": 0' in trajectory,
        },
        "postrun_case_bridge": {
            "requires_b_c_d_roots": 'STAGES = ("B", "C", "D")' in case_bridge
            and "bundle_roots" in case_bridge,
            "delegates_to_trajectory_adapter": "trajectory_adapter.materialize_diagnostic_core_trajectory_v1_at" in case_bridge,
            "preflight_receipt_consumer": any(token in case_bridge for token in preflight_tokens),
            "formal_eligible_hard_false": '"formal_eligible": False' in case_bridge,
            "qualification_credit_hard_zero": '"qualification_credit": 0' in case_bridge,
        },
        "postrun_matrix_bridge": {
            "fixed_case_count_15": "CASE_COUNT = 15" in matrix_bridge,
            "requires_case_inputs": "case_inputs" in matrix_bridge,
            "preflight_receipt_consumer": any(token in matrix_bridge for token in preflight_tokens),
            "qualification_credit_hard_zero": '"qualification_credit": 0' in matrix_bridge,
        },
        "native_fluid_table_contract": {
            "requires_c_raw_bi4_source_frame": "read_native_source_frame_fd" in table_contract,
            "requires_verified_v2_root_attributes": "ROOT_ATTRIBUTE_NAMES" in table_contract,
            "requires_table_time_axis": '"time"' in table_contract,
        },
        "observation_window_selector": {
            "exact_native_rows_only": "never interpolates or extrapolates" in selector,
            "requires_at_least_two_native_rows": "len(times) < 2" in selector,
            "inclusive_three_period_contract": "cycles * output_samples_per_period + 1" in selector,
        },
    }
    _require(contracts["trajectory_adapter"]["requires_verified_native_fluid_table"],
             "trajectory adapter no longer binds the v2 table verifier")
    _require(contracts["trajectory_adapter"]["requires_raw_source_frame_factory"],
             "trajectory adapter no longer binds raw source frames")
    _require(contracts["trajectory_adapter"]["requires_at_least_two_time_rows"],
             "trajectory adapter lost its minimum time-row guard")
    _require(not contracts["trajectory_adapter"]["preflight_receipt_consumer"],
             "trajectory adapter unexpectedly consumes the one-shot preflight namespace")
    _require(not contracts["postrun_case_bridge"]["preflight_receipt_consumer"],
             "postrun case bridge unexpectedly consumes the one-shot preflight namespace")
    _require(not contracts["postrun_matrix_bridge"]["preflight_receipt_consumer"],
             "postrun matrix bridge unexpectedly consumes the one-shot preflight namespace")
    return contracts, references


def _case_ids_from_registry(root: Path) -> tuple[str, ...]:
    """Load the already-frozen denominator without writing any accounting state."""
    import sys

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from scripts import f8_r008_native_integrity_registry_v1 as registry

        case_ids = tuple(registry.frozen_qualification_case_ids())
    except Exception as error:
        raise CoverageAuditError(
            f"frozen R008 qualification denominator could not be read: {error}"
        ) from error
    _require(len(case_ids) == 15 and len(set(case_ids)) == 15,
             "frozen R008 qualification denominator is not exactly 15 unique cases")
    return case_ids


def _relative_files(root: Path, relative: Path) -> list[str]:
    path, normalized = _resolve(root, relative)
    _require(path.is_dir(), f"artifact namespace is not a directory: {normalized}")
    result: list[str] = []
    for item in sorted(path.rglob("*")):
        if item.is_file() and not item.is_symlink():
            result.append(item.relative_to(path).as_posix())
    return result


def _observed_trajectory_cases(root: Path, case_ids: Sequence[str]) -> tuple[list[str], list[dict[str, Any]]]:
    case_root, _ = _resolve(root, CASE_REL)
    observed: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    for path in sorted(case_root.rglob(TRAJECTORY_FILENAME)):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        artifacts.append(_actual_reference(root, relative, "observed Core trajectory"))
        for case_id in case_ids:
            if case_id in path.parts:
                observed.add(case_id)
    return sorted(observed), artifacts


def _selector_report(root: Path, case_ids: Sequence[str], preflight_case_id: str) -> dict[str, Any]:
    observed_case_ids, artifacts = _observed_trajectory_cases(root, case_ids)
    missing = [case_id for case_id in case_ids if case_id not in observed_case_ids]
    _require(preflight_case_id in case_ids,
             "preflight target case is outside the frozen qualification selector")
    return {
        "selector_kind": "frozen_r008_qualification_case_selector",
        "denominator_case_count": len(case_ids),
        "denominator_case_ids": list(case_ids),
        "preflight_selected_case_id": preflight_case_id,
        "preflight_selected_case_count": 1,
        "preflight_selected_case_is_in_denominator": True,
        "observed_diagnostic_trajectory_case_ids": observed_case_ids,
        "observed_diagnostic_trajectory_case_count": len(observed_case_ids),
        "missing_diagnostic_trajectory_case_ids": missing,
        "observed_trajectory_artifacts": artifacts,
        "coverage_fraction": {
            "numerator": len(observed_case_ids),
            "denominator": len(case_ids),
        },
        "static_matrix_selector_supports_exact_denominator": True,
        "status": "static_exact_selector_available_but_no_observed_core_trajectory"
        if not observed_case_ids
        else "observed_trajectory_coverage_is_partial_or_complete",
    }


def _syscall_selector_report(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value, reference = _load_json(root, SYSCALL_SELECTOR_REL, "F8 syscall selector domain")
    closure, closure_reference = _load_json(root, SYSCALL_CLOSURE_REL, "F8 syscall static closure")
    raw_domain = value.get("raw_nr_domain", {})
    abi = value.get("selector_abi", {})
    policy = value.get("policy_state", {})
    validation = closure.get("validation", {})
    report = {
        "selector_kind": "linux_x86_64_syscall_selector_domain",
        "domain_manifest": reference,
        "static_closure_manifest": closure_reference,
        "domain_status": value.get("status"),
        "raw_nr_partition_complete": raw_domain.get("partition_complete") is True,
        "native_source_interval_count": next((
            row.get("count") for row in raw_domain.get("partition", [])
            if isinstance(row, Mapping) and row.get("selector_class") == "native_source_table_interval"
        ), None),
        "native_per_number_dispositions_complete": policy.get("native_per_number_dispositions_complete") is True,
        "native_per_number_predicates_complete": policy.get("native_per_number_predicates_complete") is True,
        "runtime_conformance_passed": policy.get("syscall_runtime_conformance_passed") is True,
        "target_kernel_build_pinned": policy.get("target_kernel_build_pinned") is True,
        "target_kernel_config_pinned": policy.get("target_kernel_config_pinned") is True,
        "x32_runtime_rejection_verified": abi.get("x32_runtime_rejection_verified") is True,
        "nr_minus_one_attribution_verified": abi.get("nr_minus_one_is_attributable_to_tracer_from_selector_alone") is True,
        "static_default_deny": policy.get("all_unclassified_selectors_default_deny") is True,
        "readiness_pass": policy.get("readiness_pass") is True,
        "qualification_credit": policy.get("qualification_credit"),
        "closure_validation": {
            key: validation.get(key) for key in (
                "baseline_rows_bound", "native_rows_complete",
                "per_number_dispositions_complete", "per_number_predicates_complete",
                "selector_conditions_complete", "target_kernel_pin_complete",
                "runtime_conformance_verified", "fail_closed",
            )
        },
        "status": "static_partition_fail_closed_runtime_authority_missing",
    }
    _require(report["raw_nr_partition_complete"],
             "F8 syscall selector domain lost its complete static partition")
    _require(report["static_default_deny"],
             "F8 syscall selector domain lost its default-deny boundary")
    return report, [reference, closure_reference]


def build_audit(root: Path = LAB) -> dict[str, Any]:
    """Build a read-only, non-authorizing current-state audit."""
    root = Path(root).resolve()
    preflight, preflight_reference = _load_json(root, PREFLIGHT_REL, "R008 preflight receipt")
    request_path = preflight.get("request", {}).get("path")
    _require(type(request_path) is str, "R008 preflight receipt lacks its request reference")
    request, request_reference = _load_json(root, request_path, "R008 v3 preflight request")
    preflight_case_id, preflight_projection, preflight_evidence = _validate_preflight(
        root, preflight, request,
    )
    postrun, postrun_reference = _load_json(root, POSTRUN_AUDIT_REL, "R008 CPU/native postrun audit")
    postrun_projection = _validate_postrun_audit(root, postrun, preflight_reference)
    contracts, source_references = _source_contracts(root)
    case_ids = _case_ids_from_registry(root)
    case_selector = _selector_report(root, case_ids, preflight_case_id)
    syscall_selector, selector_references = _syscall_selector_report(root)

    preflight_output_rel = CASE_REL / "cpu-native-preflight-v3"
    preflight_files = _relative_files(root, preflight_output_rel)
    preflight_has_table = TABLE_FILENAME in preflight_files
    preflight_has_trajectory = TRAJECTORY_FILENAME in preflight_files
    _require(not preflight_has_table and not preflight_has_trajectory,
             "one-shot preflight namespace unexpectedly contains a Core/table output")

    blockers = [
        {
            "code": "preflight_has_initial_native_decode_only",
            "severity": "high",
            "detail": (
                "The immutable preflight proves one GenCase and one native decode of the initial BI4; "
                "it does not prove solver frames or a time-indexed native-fluid table."
            ),
        },
        {
            "code": "trajectory_adapter_requires_verified_b_c_d_table_chain",
            "severity": "high",
            "detail": (
                "The existing adapter requires the v2 table verifier, raw source-frame factory, "
                "and at least two time rows; no preflight receipt input edge exists."
            ),
        },
        {
            "code": "no_observed_diagnostic_core_trajectory",
            "severity": "high",
            "detail": (
                "The R008 campaign namespace contains no observed core-trajectory-v1.h5; "
                "the fixed 15-case matrix bridge is a capability, not execution evidence."
            ),
        },
        {
            "code": "trusted_external_execution_authority_missing",
            "severity": "high",
            "detail": (
                "Trusted worker/supervisor identity, source/build/runtime identity, terminal completion, "
                "native-integrity adjudication, and the real 15-case provenance matrix remain absent."
            ),
        },
        {
            "code": "selector_runtime_conformance_and_target_pin_missing",
            "severity": "high",
            "detail": (
                "The syscall selector has a complete static partition/default-deny rule, but per-number "
                "policy, target-kernel pin, x32/nr=-1 runtime behavior, and ptrace/seccomp conformance remain open."
            ),
        },
    ]
    evidence = [preflight_reference, postrun_reference, request_reference]
    evidence.extend(preflight_evidence)
    evidence.extend(source_references)
    evidence.extend(selector_references)
    deduplicated: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for item in evidence:
        deduplicated[_reference_key(item)] = dict(item)

    return {
        "schema": SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": "preflight_verified_diagnostic_core_selector_coverage_blocked",
        "scope_id": SCOPE_ID,
        "audit_date": REPORT_DATE,
        "audit_mode": "read_only_additive_no_execution_no_formal_accounting_mutation",
        "authority_boundary": {
            "diagnostic_only": True,
            "execution_authority": False,
            "formal_admission": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "readiness_pass": False,
            "qualification_credit": 0,
            "safe_fail_closed": True,
        },
        "preflight": preflight_projection,
        "postrun_audit": postrun_projection,
        "namespace_observation": {
            "preflight_relative_root": preflight_output_rel.as_posix(),
            "preflight_file_count": len(preflight_files),
            "preflight_files": preflight_files,
            "preflight_contains_native_fluid_table": preflight_has_table,
            "preflight_contains_core_trajectory": preflight_has_trajectory,
            "observed_core_trajectory_artifact_count": len(case_selector["observed_trajectory_artifacts"]),
        },
        "static_bridge_contracts": contracts,
        "case_selector_coverage": case_selector,
        "syscall_selector_coverage": syscall_selector,
        "blockers": blockers,
        "external_authority_evidence_missing": [
            "trusted authority issuer and worker/supervisor runtime identity",
            "source/build/loaded-module identity bound to a real solver attempt",
            "provenance-verified real 15-case B/C/D/terminal result matrix",
            "native finite/integrity and effective timestep adjudication",
            "trusted terminal/final-fput completion observation",
            "target kernel build/config pin and runtime syscall/fanotify conformance",
        ],
        "side_effects": {
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "gate_mutation": 0,
            "denominator_mutation": 0,
            "plan_mutation": 0,
            "preflight_namespace_reused": False,
        },
        "evidence": sorted(deduplicated.values(), key=lambda item: item["path"]),
    }


def _write_noreplace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def render_markdown(report: Mapping[str, Any], json_relative: str) -> str:
    selector = report["case_selector_coverage"]
    syscall = report["syscall_selector_coverage"]
    lines = [
        "# F8 R008 preflight → diagnostic Core / selector coverage audit V1",
        "",
        f"- 日期：{report['audit_date']}",
        f"- JSON：`{json_relative}`",
        f"- 状态：`{report['status']}`",
        "",
        "## 结论",
        "",
        "已完成的 CPU/native preflight 证据闭合为一次 zero-credit 的 GenCase + 初始 BI4/native decode。它没有产生 solver 时间序列、verified native-fluid table 或 Core trajectory，因此不能直接计入 diagnostic trajectory coverage，也不能成为 T1 证据。现有 trajectory/case/matrix bridge 均保持 fail-closed。",
        "",
        "本审计没有启动 solver、worker、queue 或 GPU，没有重用 preflight namespace，也没有写 formal registry、ledger、gate、denominator 或 PLAN。",
        "",
        "## 证据链",
        "",
        "| 边界 | 当前证据 | 结论 |",
        "| --- | --- | --- |",
        f"| CPU/native preflight | `{report['preflight']['status']}`；GenCase/native decode 均通过；credit={report['preflight']['qualification_credit']} | 已验证，但仅为初始输入/几何诊断 |",
        "| preflight → native-fluid table | preflight namespace 无 `native-fluid-frame-table-v2.h5` | 未闭合；缺 solver frames/B/C/D |",
        "| native-fluid table → Core trajectory | adapter 要求 v2 table、raw source-frame factory、至少两帧 | 静态能力存在，当前没有 observed artifact |",
        f"| Core trajectory selector | 静态固定分母 {selector['denominator_case_count']} cases；observed={selector['observed_diagnostic_trajectory_case_count']} | coverage={selector['coverage_fraction']['numerator']}/{selector['coverage_fraction']['denominator']} |",
        "| syscall selector | signed-int32 partition/default-deny 静态闭合；runtime/pin 未闭合 | 不是可执行 authority |",
        "",
        "## Case selector coverage",
        "",
        f"preflight 选择的 case 是 `{selector['preflight_selected_case_id']}`，属于冻结 15-case 分母；但当前 R008 campaign 下 observed `core-trajectory-v1.h5` 为 {selector['observed_diagnostic_trajectory_case_count']} 个，缺少 {len(selector['missing_diagnostic_trajectory_case_ids'])} 个 case。现有 15-case matrix worker 只能说明输入键集和 fail-closed 编排能力，不能替代实际 provenance-verified 输出。",
        "",
        "## Syscall selector coverage",
        "",
        f"静态 manifest 状态为 `{syscall['domain_status']}`；raw selector partition complete={syscall['raw_nr_partition_complete']}，native interval count={syscall['native_source_interval_count']}，default-deny={syscall['static_default_deny']}。但 per-number policy、runtime conformance、target-kernel build/config pin 均未完成，x32 rejection 与 nr=-1 attribution 也未得到 runtime authority 证明。",
        "",
        "## 仍缺失的外部权威证据",
        "",
    ]
    lines.extend(f"- {item}" for item in report["external_authority_evidence_missing"])
    lines.extend([
        "",
        "## 安全边界",
        "",
        "- `diagnostic_only=true`、`formal_eligible=false`、`T1_numerical=false`、`readiness_pass=false`、`qualification_credit=0`。",
        "- 本报告只读取 bounded JSON、源码和 artifact size/SHA；不解释 BI4/HDF5 内容，不调用 native tool。",
        "- 失败或缺失继续保持 fail-closed；不得通过改 manifest、复用 namespace 或补写 formal accounting 来提升 coverage。",
        "",
        "## 验证入口",
        "",
        "- `tests/test_f8_r008_preflight_diagnostic_coverage_audit_v1.py`",
        "- `scripts/f8_r008_preflight_diagnostic_coverage_audit_v1.py`",
    ])
    return "\n".join(lines) + "\n"


def write_reports(
    *,
    root: Path = LAB,
    json_output: Path | None = None,
    markdown_output: Path | None = None,
) -> dict[str, Any]:
    report = build_audit(root)
    json_output = json_output or root / f"reports/F8-R008-PREFLIGHT-DIAGNOSTIC-CORE-TRAJECTORY-COVERAGE-AUDIT-V1-{REPORT_DATE}.json"
    markdown_output = markdown_output or root / f"reports/F8-R008-PREFLIGHT-DIAGNOSTIC-CORE-TRAJECTORY-COVERAGE-AUDIT-V1-{REPORT_DATE}.zh-CN.md"
    json_relative = Path(json_output).resolve().relative_to(Path(root).resolve()).as_posix()
    payload = _canonical_json(report) + b"\n"
    markdown = render_markdown(report, json_relative).encode("utf-8")
    _write_noreplace(Path(json_output), payload)
    try:
        _write_noreplace(Path(markdown_output), markdown)
    except BaseException:
        # The JSON report is intentionally immutable.  Do not remove it on a
        # second-output failure; callers must inspect the explicit state.
        raise
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args(argv)
    report = write_reports(
        root=args.root.resolve(),
        json_output=args.json_output.resolve() if args.json_output else None,
        markdown_output=args.markdown_output.resolve() if args.markdown_output else None,
    )
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "observed_diagnostic_trajectory_case_count": report["case_selector_coverage"]["observed_diagnostic_trajectory_case_count"],
        "qualification_credit": report["authority_boundary"]["qualification_credit"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CoverageAuditError", "LAB", "SCHEMA", "build_audit", "render_markdown",
    "write_reports",
]
