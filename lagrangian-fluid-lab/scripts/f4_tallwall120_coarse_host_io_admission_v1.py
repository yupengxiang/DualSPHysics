#!/usr/bin/env python3
"""Build a diagnostic-only F4 Tallwall120 host-I/O admission projection.

This adapter is intentionally narrower than the F4 receipt-consistency audit.
It consumes only the committed F4 coarse proposal, the shared bounded
host-I/O probe receipt, and the current DEV_07 F4 job specification.  It
binds the F4 scope, the proposal's material-stage normalized argv and fresh
output namespace, the job's normalized CFD argv/cwd, and a declared resource
projection.  It does not consume collection/reader/DEV_07 diagnostic receipts
and therefore does not audit proposal/receipt drift.

The adapter reads bounded JSON only.  It never resolves, opens, hashes, or
interprets the large trajectory HDF5 named inside the proposal.  A passing
projection is still not root or scheduler authorization: the output is always
synthetic, diagnostic-only, non-formal, zero-credit, and fail-closed when the
required authorization receipts are absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # Support both ``python -m scripts...`` and direct script execution.
    from scripts import core_material_host_io_probe_v1 as host_io_probe
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI use.
    import core_material_host_io_probe_v1 as host_io_probe


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.material.f4.tallwall120.coarse.host_io_admission_projection.v1"
CREATED_AT = "2026-09-28"
MAX_JSON_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = {".h5", ".hdf5"}

PROPOSAL = Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
HOST_IO_RECEIPT = Path("reports/CORE-MATERIAL-HOST-IO-PROBE-2026-09-28.json")
JOB_SPEC = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/remaining-24/"
    "f4-tallwall120-production-dev-07.json"
)

DEFAULT_JSON = LAB_ROOT / (
    "reports/F4-TALLWALL120-COARSE-HOST-IO-ADMISSION-PROJECTION-2026-09-28.json"
)
DEFAULT_ZH_CN = LAB_ROOT / (
    "reports/F4-TALLWALL120-COARSE-HOST-IO-ADMISSION-PROJECTION-2026-09-28.zh-CN.md"
)

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = "F4_resting_pool_laminar_tallwall120_x_v1_DEV_07"
JOB_ID = "f4-tallwall120-production-dev-07"
OUTPUT_NAMESPACE = (
    "campaigns/core-v1/material/proposals/"
    "f4-tallwall120-production-dev-07/coarse-baseline24-s2-r001-source-6ae8ca70"
)
EXPECTED_JOB_RESOURCES = {
    "cpu_cores": 2,
    "ram_mib": 24576,
    "gpu_peak_mib": 6144,
    "io_weight": 2,
}

_EXECUTION_MUTATION_KEYS = (
    "registry_mutations",
    "completion_mutations",
    "ledger_mutations",
    "denominator_mutations",
    "gate_mutations",
)
_PROPOSAL_MUTATION_KEYS = (
    "registry_mutation",
    "completion_mutation",
    "ledger_mutation",
    "denominator_mutation",
    "gate_mutation",
)


def sha256_file(path: Path) -> str:
    """Hash one bounded JSON/source receipt; HDF5 is never passed here."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _relative_or_absolute(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _record(
    checks: dict[str, bool], reasons: list[str], name: str, value: bool, reason: str
) -> None:
    passed = bool(value)
    checks[name] = passed
    if not passed:
        reasons.append(reason)


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _safe_namespace(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _small_ref(root: Path, path: Path, role: str) -> dict[str, Any]:
    """Return a JSON receipt reference without ever opening an HDF5 path."""

    result: dict[str, Any] = {
        "path": _relative_or_absolute(root, path),
        "role": role,
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "read_allowed": path.suffix.lower() not in HDF5_SUFFIXES,
    }
    if path.suffix.lower() in HDF5_SUFFIXES:
        result["error"] = "hdf5_outside_json_only_boundary"
        return result
    if not path.is_file():
        result["error"] = "missing_file"
        return result
    try:
        size = path.stat().st_size
        result["bytes"] = size
        if size > MAX_JSON_BYTES:
            result["error"] = "json_file_exceeds_bound"
            return result
        result["sha256"] = sha256_file(path)
    except OSError as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in HDF5_SUFFIXES:
        raise ValueError(f"HDF5 is outside the JSON-only boundary: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"JSON input exceeds bound: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _proposal_material_argv(
    root: Path, proposal: Mapping[str, Any], namespace: str
) -> tuple[list[str], list[str]]:
    target = proposal.get("target")
    target = target if isinstance(target, Mapping) else {}
    parameters = proposal.get("parameter_contract")
    parameters = parameters if isinstance(parameters, Mapping) else {}
    source = f"{{lab_root}}/{target.get('source_hdf5', '')}"
    output = f"{{fresh_output_namespace}}/product/tallwall120_material.h5"
    diagnosis = f"{{fresh_output_namespace}}/product/tallwall120_material_diagnosis.json"
    q = format(float(parameters.get("q")), ".17g") if parameters.get("q") is not None else ""
    dp = str(parameters.get("dp_m", ""))
    seeds = str(parameters.get("seeds", ""))
    substeps = str(parameters.get("substeps", ""))
    neighbour_variant = str(parameters.get("neighbour_variant", ""))
    stop_after = str(parameters.get("stop_after_frame", ""))
    trace = [
        "{lab_root}/.venv/bin/python",
        "{lab_root}/scripts/f4_tallwall120_material.py",
        "--source",
        source,
        "--output",
        output,
        "--q",
        q,
        "--dp-m",
        dp,
        "--seeds",
        seeds,
        "--substeps",
        substeps,
        "--neighbour-variant",
        neighbour_variant,
        "--stop-after",
        stop_after,
    ]
    diagnosis_argv = [
        "{lab_root}/.venv/bin/python",
        "{lab_root}/scripts/f4_tallwall120_material_diagnosis.py",
        "--source",
        source,
        "--trace",
        output,
        "--output",
        diagnosis,
        "--q",
        q,
        "--dp-m",
        dp,
        "--substeps",
        substeps,
    ]
    # ``namespace`` is deliberately accepted as an explicit argument so the
    # caller cannot accidentally treat the proposal's namespace as implicit
    # authorization.  The placeholder contract remains the bound value.
    _ = namespace
    _ = root
    return trace, diagnosis_argv


def _normalise_job_argv(root: Path, argv: Any) -> list[str] | None:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return None
    root_text = str(root)
    normalized: list[str] = []
    for item in argv:
        if item == root_text:
            normalized.append("{lab_root}")
        elif item.startswith(root_text + "/"):
            normalized.append("{lab_root}" + item[len(root_text) :])
        else:
            normalized.append(item)
    return normalized


def _expected_job_argv() -> list[str]:
    return [
        "{lab_root}/.venv/bin/python",
        "{lab_root}/scripts/core_cfd.py",
        "--lab-root",
        "{lab_root}",
        "run",
        "--prepared",
        "{lab_root}/campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/remaining-24/case-07/prepared.json",
        "--output",
        "{attempt_dir}/product",
    ]


def _forbidden_job_argv_reasons(argv: Any) -> list[str]:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return ["job_spec.argv_not_string_list"]
    lowered = [item.lower() for item in argv]
    reasons: list[str] = []
    if "--gpu" in lowered or "--cuda" in lowered:
        reasons.append("job_spec.direct_gpu_override_forbidden")
    if any("cuda_visible_devices" in item for item in lowered):
        reasons.append("job_spec.cuda_visible_devices_override_forbidden")
    if any(token in item for item in lowered for token in ("--resume", "--force", "--kill-after")):
        reasons.append("job_spec.resume_or_force_mutation_forbidden")
    return reasons


def _proposal_checks(
    root: Path,
    proposal: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    target = proposal.get("target")
    target = target if isinstance(target, Mapping) else {}
    state_ok = (
        proposal.get("schema") == "core.material.f4.tallwall120.coarse_proposal.v1"
        and proposal.get("status") == "blocked_fail_closed"
        and proposal.get("proposal_only") is True
        and proposal.get("diagnostic_only") is True
        and proposal.get("formal_eligible") is False
    )
    _record(checks, reasons, "proposal_state", state_ok, "proposal state")

    scope_ok = (
        target.get("family") == FAMILY
        and target.get("scope_id") == SCOPE_ID
        and target.get("case_id") == CASE_ID
        and target.get("physical_case_id") == CASE_ID
        and target.get("lineage_group_id") == CASE_ID
    )
    _record(checks, reasons, "f4_scope_binding", scope_ok, "proposal F4 scope/case")

    qualification = proposal.get("qualification")
    qualification = qualification if isinstance(qualification, Mapping) else {}
    qualification_closed = (
        qualification.get("T1") is False
        and qualification.get("T2") is False
        and qualification.get("credit") == 0
        and qualification.get("qualification_credit") == 0
        and qualification.get("material_labels_created") is False
        and all(qualification.get(key) == 0 for key in _PROPOSAL_MUTATION_KEYS)
    )
    _record(
        checks,
        reasons,
        "proposal_qualification_closed",
        qualification_closed,
        "proposal qualification/credit/mutation boundary",
    )

    planned = proposal.get("planned_output_namespace")
    planned = planned if isinstance(planned, Mapping) else {}
    policy = planned.get("namespace_policy")
    # The committed proposal receipt stores these policy fields at the
    # planned-output top level; the planner's raw projection may nest them.
    policy = policy if isinstance(policy, Mapping) else planned
    output_values = {
        "namespace": planned.get("namespace"),
        "material_h5": planned.get("material_h5"),
        "material_result_json": planned.get("material_result_json"),
        "diagnosis_json": planned.get("diagnosis_json"),
        "checkpoint_manifest": planned.get("checkpoint_manifest"),
        "log": planned.get("log"),
    }
    expected_outputs = {
        "namespace": OUTPUT_NAMESPACE,
        "material_h5": f"{OUTPUT_NAMESPACE}/product/tallwall120_material.h5",
        "material_result_json": f"{OUTPUT_NAMESPACE}/product/tallwall120_material.json",
        "diagnosis_json": f"{OUTPUT_NAMESPACE}/product/tallwall120_material_diagnosis.json",
        "checkpoint_manifest": f"{OUTPUT_NAMESPACE}/product/tallwall120_material.h5.checkpoint.json",
        "log": f"{OUTPUT_NAMESPACE}/logs/material-trace.log",
    }
    namespace_contract = (
        output_values == expected_outputs
        and _safe_namespace(planned.get("namespace"))
        and policy.get("must_be_absent_before_admission") is True
        and policy.get("overwrite_allowed") is False
        and policy.get("resume_allowed") is False
        and policy.get("historical_trace_reuse", planned.get("historical_trace_reuse")) is False
    )
    _record(
        checks,
        reasons,
        "fresh_output_namespace_contract",
        namespace_contract,
        "proposal planned output namespace/policy",
    )
    namespace_path = root / OUTPUT_NAMESPACE
    namespace_fresh = namespace_contract and not namespace_path.exists()
    _record(
        checks,
        reasons,
        "fresh_output_namespace_absent",
        namespace_fresh,
        "fresh output namespace must remain absent",
    )

    argv_contract = proposal.get("argv_contract")
    argv_contract = argv_contract if isinstance(argv_contract, Mapping) else {}
    expected_trace, expected_diagnosis = _proposal_material_argv(
        root, proposal, OUTPUT_NAMESPACE
    )
    actual_trace = argv_contract.get("material_trace")
    actual_diagnosis = argv_contract.get("diagnosis")
    material_argv_ok = (
        actual_trace == expected_trace
        and actual_diagnosis == expected_diagnosis
        and argv_contract.get("execution_order") == ["material_trace", "diagnosis"]
        and isinstance(argv_contract.get("forbidden_mutations"), list)
        and all("resume" not in str(item).lower() or "namespace" in str(item).lower() for item in argv_contract["forbidden_mutations"])
    )
    _record(
        checks,
        reasons,
        "proposal_material_normalized_argv",
        material_argv_ok,
        "proposal material-stage normalized argv",
    )

    proposal_valid = all(
        checks.get(name) is True
        for name in (
            "proposal_state",
            "f4_scope_binding",
            "proposal_qualification_closed",
            "fresh_output_namespace_contract",
            "fresh_output_namespace_absent",
            "proposal_material_normalized_argv",
        )
    )
    _record(checks, reasons, "proposal_contract_valid", proposal_valid, "proposal contract")
    return {
        "schema": proposal.get("schema"),
        "status": proposal.get("status"),
        "proposal_only": proposal.get("proposal_only"),
        "diagnostic_only": proposal.get("diagnostic_only"),
        "formal_eligible": proposal.get("formal_eligible"),
        "target": {
            "family": target.get("family"),
            "scope_id": target.get("scope_id"),
            "case_id": target.get("case_id"),
            "physical_case_id": target.get("physical_case_id"),
            "lineage_group_id": target.get("lineage_group_id"),
        },
        "qualification": {
            "T1": qualification.get("T1"),
            "T2": qualification.get("T2"),
            "credit": qualification.get("credit"),
            "qualification_credit": qualification.get("qualification_credit"),
            "material_labels_created": qualification.get("material_labels_created"),
            "mutation_counts": {
                key: qualification.get(key) for key in _PROPOSAL_MUTATION_KEYS
            },
        },
        "material_normalized_argv": {
            "observed": actual_trace,
            "expected": expected_trace,
            "diagnosis_observed": actual_diagnosis,
            "diagnosis_expected": expected_diagnosis,
            "execution_order": argv_contract.get("execution_order"),
        },
        "fresh_output_namespace": {
            "namespace": planned.get("namespace"),
            "namespace_path_exists": namespace_path.exists(),
            "must_be_absent_before_admission": policy.get("must_be_absent_before_admission"),
            "overwrite_allowed": policy.get("overwrite_allowed"),
            "resume_allowed": policy.get("resume_allowed"),
            "historical_trace_reuse": policy.get(
                "historical_trace_reuse", planned.get("historical_trace_reuse")
            ),
        },
    }


def _host_checks(
    receipt: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    validation_errors = list(host_io_probe.validate_report(receipt))
    probe = receipt.get("probe") if isinstance(receipt.get("probe"), Mapping) else {}
    request = receipt.get("request") if isinstance(receipt.get("request"), Mapping) else {}
    projection = (
        receipt.get("owned_io_projection")
        if isinstance(receipt.get("owned_io_projection"), Mapping)
        else {}
    )
    io = receipt.get("io_measurement") if isinstance(receipt.get("io_measurement"), Mapping) else {}
    boundary = (
        receipt.get("authorization_boundary")
        if isinstance(receipt.get("authorization_boundary"), Mapping)
        else {}
    )
    controls = (
        receipt.get("execution_controls")
        if isinstance(receipt.get("execution_controls"), Mapping)
        else {}
    )

    _record(checks, reasons, "host_io_receipt_schema", receipt.get("schema") == host_io_probe.SCHEMA, "host-I/O schema")
    _record(checks, reasons, "host_io_receipt_valid", not validation_errors, "host-I/O receipt validation")
    _record(checks, reasons, "host_probe_pass", probe.get("probe_pass") is True, "host probe pass")
    _record(checks, reasons, "host_measurement_complete", probe.get("measurement_complete") is True, "host measurement complete")
    _record(checks, reasons, "host_probe_contract_valid", probe.get("contract_valid") is True, "host probe contract")
    _record(checks, reasons, "host_probe_diagnostic_status", receipt.get("status") == "diagnostic_pass", "host probe diagnostic status")
    family_scope = request.get("family_scope")
    _record(
        checks,
        reasons,
        "host_f4_scope",
        isinstance(family_scope, list) and FAMILY in family_scope,
        "host-I/O family scope must include F4",
    )
    _record(
        checks,
        reasons,
        "host_probe_is_not_authorization",
        boundary.get("probe_is_authorization") is False
        and boundary.get("worker_launch_authorized") is False
        and boundary.get("formal_admission") is False
        and boundary.get("qualification_credit") == 0,
        "host-I/O authorization boundary",
    )
    controls_closed = (
        controls.get("probe_only") is True
        and controls.get("production_hdf5_opened") is False
        and controls.get("material_worker_started") is False
        and controls.get("solver_started") is False
        and controls.get("gpu_initialized") is False
        and controls.get("queue_or_scheduler_started") is False
        and all(controls.get(key) == 0 for key in _EXECUTION_MUTATION_KEYS)
    )
    _record(checks, reasons, "host_execution_boundary_closed", controls_closed, "host-I/O execution boundary")
    return {
        "schema": receipt.get("schema"),
        "status": receipt.get("status"),
        "validation_errors": validation_errors,
        "probe": {
            "probe_pass": probe.get("probe_pass"),
            "contract_valid": probe.get("contract_valid"),
            "measurement_complete": probe.get("measurement_complete"),
        },
        "request": {
            "family_scope": family_scope,
            "concurrency": request.get("concurrency"),
            "owned_io_bytes_per_worker": request.get("owned_io_bytes_per_worker"),
            "probe_bytes": request.get("probe_bytes"),
            "minimum_free_disk_bytes": request.get("minimum_free_disk_bytes"),
        },
        "projection": {
            "concurrency": projection.get("concurrency"),
            "owned_io_bytes_per_worker": projection.get("owned_io_bytes_per_worker"),
            "projected_owned_io_bytes": projection.get("projected_owned_io_bytes"),
            "probe_write_bytes": projection.get("probe_write_bytes"),
            "probe_read_bytes": projection.get("probe_read_bytes"),
            "projected_total_io_bytes": projection.get("projected_total_io_bytes"),
            "observed": projection.get("observed"),
            "scheduler_owned_io_verified": projection.get("scheduler_owned_io_verified"),
        },
        "io_measurement": {
            "bytes_requested": io.get("bytes_requested"),
            "bytes_written": io.get("bytes_written"),
            "bytes_read": io.get("bytes_read"),
            "readback_sha256_match": io.get("readback_sha256_match"),
        },
        "disk_after": (
            dict(receipt.get("disk", {}).get("after", {}))
            if isinstance(receipt.get("disk"), Mapping)
            else {}
        ),
        "authorization_boundary": {
            "root_authorization_required": boundary.get("root_authorization_required"),
            "scheduler_authorization_required": boundary.get("scheduler_authorization_required"),
            "worker_launch_authorized": boundary.get("worker_launch_authorized"),
            "formal_admission": boundary.get("formal_admission"),
            "qualification_credit": boundary.get("qualification_credit"),
        },
    }


def _job_checks(
    root: Path,
    job: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    identity_ok = (
        job.get("schema") == "core.cfd.job.v1"
        and job.get("job_id") == JOB_ID
        and job.get("logical_id") == JOB_ID
        and job.get("family") == FAMILY
        and job.get("scope_id") == SCOPE_ID
        and job.get("prepared_case_id") == CASE_ID
        and job.get("production_index") == 7
        and job.get("batch_status") == "remaining_24"
        and job.get("split") == "train"
        and job.get("qualification_only") is False
        and job.get("qualification_claim") == "none; production evidence pending"
    )
    _record(checks, reasons, "f4_job_spec_identity", identity_ok, "F4 DEV_07 job identity/scope")

    resources = job.get("resources")
    resources_ok = resources == EXPECTED_JOB_RESOURCES
    _record(checks, reasons, "f4_job_spec_resources", resources_ok, "F4 job declared resources")

    actual_argv = job.get("argv")
    normalized_argv = _normalise_job_argv(root, actual_argv)
    expected_argv = _expected_job_argv()
    normalized_ok = normalized_argv == expected_argv and not _forbidden_job_argv_reasons(actual_argv)
    _record(checks, reasons, "f4_job_normalized_argv", normalized_ok, "F4 job normalized argv")

    cwd_ok = job.get("cwd") == str(root) and job.get("source_lab") == str(root)
    _record(checks, reasons, "f4_job_cwd", cwd_ok, "F4 job cwd/source_lab")
    output_index = actual_argv.index("--output") if isinstance(actual_argv, list) and "--output" in actual_argv else -1
    output_ok = (
        output_index >= 0
        and output_index + 1 < len(actual_argv)
        and actual_argv[output_index + 1] == "{attempt_dir}/product"
    )
    _record(checks, reasons, "f4_job_fresh_attempt_output", output_ok, "F4 job fresh attempt output")

    job_valid = all(
        checks.get(name) is True
        for name in (
            "f4_job_spec_identity",
            "f4_job_spec_resources",
            "f4_job_normalized_argv",
            "f4_job_cwd",
            "f4_job_fresh_attempt_output",
        )
    )
    _record(checks, reasons, "f4_job_contract_valid", job_valid, "F4 job contract")
    return {
        "schema": job.get("schema"),
        "job_id": job.get("job_id"),
        "logical_id": job.get("logical_id"),
        "family": job.get("family"),
        "scope_id": job.get("scope_id"),
        "prepared_case_id": job.get("prepared_case_id"),
        "production_index": job.get("production_index"),
        "batch_status": job.get("batch_status"),
        "qualification_only": job.get("qualification_only"),
        "qualification_claim": job.get("qualification_claim"),
        "cwd": job.get("cwd"),
        "source_lab": job.get("source_lab"),
        "resources": dict(resources) if isinstance(resources, Mapping) else resources,
        "normalized_argv": {
            "observed": normalized_argv,
            "expected": expected_argv,
        },
        "attempt_output": "{attempt_dir}/product",
    }


def _resource_projection(
    root: Path,
    host: Mapping[str, Any],
    job: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    request = host.get("request", {})
    request = request if isinstance(request, Mapping) else {}
    projection = host.get("projection", {})
    projection = projection if isinstance(projection, Mapping) else {}
    disk_after = host.get("disk_after", {})
    disk_after = disk_after if isinstance(disk_after, Mapping) else {}
    resources = job.get("resources", {})
    resources = resources if isinstance(resources, Mapping) else {}

    concurrency = request.get("concurrency")
    owned_per_worker = request.get("owned_io_bytes_per_worker")
    projected_owned = projection.get("projected_owned_io_bytes")
    probe_write = projection.get("probe_write_bytes")
    probe_read = projection.get("probe_read_bytes")
    projected_total = projection.get("projected_total_io_bytes")
    arithmetic_ok = (
        _is_positive_int(concurrency)
        and _is_nonnegative_int(owned_per_worker)
        and _is_nonnegative_int(projected_owned)
        and _is_nonnegative_int(probe_write)
        and _is_nonnegative_int(probe_read)
        and _is_nonnegative_int(projected_total)
        and projected_owned == concurrency * owned_per_worker
        and projected_total == projected_owned + probe_write + probe_read
    )
    host_job_shape = (
        resources == EXPECTED_JOB_RESOURCES
        and concurrency == resources.get("cpu_cores")
        and projection.get("concurrency") == concurrency
        and projection.get("observed") is False
        and projection.get("scheduler_owned_io_verified") is False
        and arithmetic_ok
    )
    _record(checks, reasons, "resource_projection_shape", host_job_shape, "F4 job/host-I/O resource projection")

    disk_shape = (
        _is_nonnegative_int(disk_after.get("free_bytes"))
        and _is_nonnegative_int(request.get("minimum_free_disk_bytes"))
        and disk_after.get("free_bytes") >= request.get("minimum_free_disk_bytes")
    )
    _record(checks, reasons, "resource_disk_headroom_observed", disk_shape, "generic probe disk headroom")

    gpu_shape = (
        resources.get("gpu_peak_mib") == EXPECTED_JOB_RESOURCES["gpu_peak_mib"]
        and _is_positive_int(resources.get("gpu_peak_mib"))
    )
    _record(checks, reasons, "resource_gpu_declaration_shape", gpu_shape, "F4 declared GPU resource")

    return {
        "scope_id": SCOPE_ID,
        "job_resources": dict(resources),
        "host_probe_request": {
            "concurrency": concurrency,
            "owned_io_bytes_per_worker": owned_per_worker,
            "minimum_free_disk_bytes": request.get("minimum_free_disk_bytes"),
        },
        "declared_io_projection": {
            "concurrency": projection.get("concurrency"),
            "projected_owned_io_bytes": projected_owned,
            "probe_write_bytes": probe_write,
            "probe_read_bytes": probe_read,
            "projected_total_io_bytes": projected_total,
            "observed": projection.get("observed"),
            "scheduler_owned_io_verified": projection.get("scheduler_owned_io_verified"),
        },
        "disk_after_free_bytes": disk_after.get("free_bytes"),
        "gpu": {
            "declared_peak_mib": resources.get("gpu_peak_mib"),
            "allocation_observed": False,
            "scheduler_authorized": False,
            "gpu_started_by_adapter": False,
        },
        "ram_mib": resources.get("ram_mib"),
        "io_weight": resources.get("io_weight"),
        "capacity_or_authorization_claim": False,
        "root": str(root),
    }


def _authorization_boundary(
    host: Mapping[str, Any], checks: dict[str, bool], reasons: list[str]
) -> dict[str, Any]:
    boundary = host.get("authorization_boundary", {})
    boundary = boundary if isinstance(boundary, Mapping) else {}
    root_required = boundary.get("root_authorization_required") is True
    scheduler_required = boundary.get("scheduler_authorization_required") is True
    _record(checks, reasons, "root_authorization_required", root_required, "root authorization requirement")
    _record(checks, reasons, "scheduler_authorization_required", scheduler_required, "scheduler authorization requirement")

    # No authorization receipt is an input to this projection.  The generic
    # probe is deliberately not accepted as either root or scheduler proof.
    reasons.extend(("fresh_root_authorization_missing", "scheduler_authorization_missing"))
    _record(checks, reasons, "authorization_missing", True, "authorization must remain absent")
    return {
        "root_authorization_required": root_required,
        "scheduler_authorization_required": scheduler_required,
        "root_authorization_present": False,
        "scheduler_authorization_present": False,
        "authorization_missing": True,
        "probe_is_authorization": False,
        "scheduler_owned_io_verified": False,
        "gpu_allocation_authorized": False,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "formal": False,
        "formal_eligible": False,
        "credit": 0,
        "qualification_credit": 0,
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "adapter_only": True,
        "json_inputs_only": True,
        "large_hdf5_opened": False,
        "large_hdf5_hashed": False,
        "large_hdf5_content_read": False,
        "worker_started": False,
        "solver_started": False,
        "native_started": False,
        "gpu_initialized": False,
        "queue_or_scheduler_started": False,
        "registry_mutations": 0,
        "completion_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
    }


def build_projection(
    root: str | Path = LAB_ROOT,
    *,
    proposal_path: str | Path | None = None,
    host_io_receipt_path: str | Path | None = None,
    job_spec_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the bounded projection without launching or mutating anything."""

    root = Path(root).resolve()
    proposal_file = _resolve(root, proposal_path or PROPOSAL)
    host_file = _resolve(root, host_io_receipt_path or HOST_IO_RECEIPT)
    job_file = _resolve(root, job_spec_path or JOB_SPEC)
    input_refs = {
        "proposal": _small_ref(root, proposal_file, "F4 coarse proposal JSON"),
        "host_io_receipt": _small_ref(root, host_file, "generic bounded host-I/O receipt"),
        "job_spec": _small_ref(root, job_file, "F4 DEV_07 job specification JSON"),
    }

    errors: dict[str, str | None] = {"proposal": None, "host_io_receipt": None, "job_spec": None}
    try:
        proposal = _read_json(proposal_file)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        proposal = {}
        errors["proposal"] = f"{type(error).__name__}: {error}"
    try:
        host_receipt = _read_json(host_file)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        host_receipt = {}
        errors["host_io_receipt"] = f"{type(error).__name__}: {error}"
    try:
        job_spec = _read_json(job_file)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        job_spec = {}
        errors["job_spec"] = f"{type(error).__name__}: {error}"

    checks: dict[str, bool] = {}
    reasons: list[str] = [
        f"{name}_read_failed:{error}" for name, error in errors.items() if error
    ]
    proposal_observation = _proposal_checks(root, proposal, checks, reasons)
    host_observation = _host_checks(host_receipt, checks, reasons)
    job_observation = _job_checks(root, job_spec, checks, reasons)
    resource_observation = _resource_projection(
        root, host_observation, job_spec, checks, reasons
    )
    authorization = _authorization_boundary(host_observation, checks, reasons)
    execution_controls = _execution_controls()

    for name, reference in input_refs.items():
        _record(
            checks,
            reasons,
            f"{name}_file_binding",
            reference.get("exists") is True
            and reference.get("read_allowed") is True
            and reference.get("sha256") is not None,
            f"{name} JSON binding",
        )

    contract_names = (
        "proposal_contract_valid",
        "host_io_receipt_schema",
        "host_io_receipt_valid",
        "host_probe_pass",
        "host_measurement_complete",
        "host_probe_contract_valid",
        "host_probe_diagnostic_status",
        "host_f4_scope",
        "host_probe_is_not_authorization",
        "host_execution_boundary_closed",
        "f4_job_contract_valid",
        "resource_projection_shape",
        "resource_disk_headroom_observed",
        "resource_gpu_declaration_shape",
        "proposal_file_binding",
        "host_io_receipt_file_binding",
        "job_spec_file_binding",
    )
    input_contract_valid = all(checks.get(name) is True for name in contract_names)
    _record(checks, reasons, "input_contract_valid", input_contract_valid, "projection input contract")

    reasons = _unique(reasons)
    status = "diagnostic_admission_blocked" if input_contract_valid else "failed_closed"
    decision = {
        "input_contract_valid": input_contract_valid,
        "f4_scope_bound": checks.get("f4_scope_binding", False),
        "proposal_normalized_argv_valid": checks.get("proposal_material_normalized_argv", False),
        "job_normalized_argv_valid": checks.get("f4_job_normalized_argv", False),
        "cwd_valid": checks.get("f4_job_cwd", False),
        "fresh_output_namespace_valid": checks.get("fresh_output_namespace_absent", False),
        "resource_projection_valid": checks.get("resource_projection_shape", False),
        "root_authorization_present": False,
        "scheduler_authorization_present": False,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "formal": False,
        "formal_eligible": False,
        "credit": 0,
        "qualification_credit": 0,
    }
    return {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "status": status,
        "projection_kind": "synthetic_json_only_non_authorizing",
        "synthetic_only": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "credit": 0,
        "qualification_credit": 0,
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "job_id": JOB_ID,
        },
        "input_boundary": {
            "json_only": True,
            "large_hdf5_named_in_proposal_resolved": False,
            "large_hdf5_opened": False,
            "large_hdf5_hashed": False,
            "large_hdf5_content_read": False,
            "worker_solver_native_gpu_queue_started": False,
            "registry_completion_ledger_denominator_gate_mutated": False,
        },
        "input_bindings": input_refs,
        "input_errors": errors,
        "proposal_observation": proposal_observation,
        "host_io_observation": host_observation,
        "job_spec_observation": job_observation,
        "fresh_output_namespace": proposal_observation.get("fresh_output_namespace", {}),
        "normalized_launch": {
            "proposal_material_stage": proposal_observation.get("material_normalized_argv", {}),
            "f4_job_stage": job_observation.get("normalized_argv", {}),
            "cwd": job_observation.get("cwd"),
        },
        "resource_projection": resource_observation,
        "authorization_boundary": authorization,
        "checks": checks,
        "decision": decision,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "execution_controls": execution_controls,
        "blocking_reasons": reasons,
        "diagnostic_errors": {
            "proposal": errors["proposal"],
            "host_io_receipt": errors["host_io_receipt"],
            "job_spec": errors["job_spec"],
            "host_io_validation": host_observation.get("validation_errors", []),
        },
        "next_safe_action": (
            "Obtain separate fresh root and scheduler authorization receipts bound to "
            "the exact F4 scope, normalized argv/cwd, fresh namespace, and declared "
            "resource projection; this diagnostic projection cannot launch a worker."
        ),
    }


def validate_projection(value: Mapping[str, Any]) -> list[str]:
    """Validate the serialized fail-closed/non-authorizing projection."""

    errors: list[str] = []
    if value.get("schema") != SCHEMA:
        errors.append("schema")
    if value.get("status") not in {"diagnostic_admission_blocked", "failed_closed"}:
        errors.append("status")
    if value.get("projection_kind") != "synthetic_json_only_non_authorizing":
        errors.append("projection_kind")
    for key, expected in (
        ("synthetic_only", True),
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("credit", 0),
        ("qualification_credit", 0),
        ("launch_admitted", False),
        ("worker_launch_authorized", False),
    ):
        if value.get(key) != expected:
            errors.append(key)

    decision = value.get("decision")
    if not isinstance(decision, Mapping):
        errors.append("decision")
    else:
        for key, expected in (
            ("root_authorization_present", False),
            ("scheduler_authorization_present", False),
            ("launch_admitted", False),
            ("worker_launch_authorized", False),
            ("formal", False),
            ("formal_eligible", False),
            ("credit", 0),
            ("qualification_credit", 0),
        ):
            if decision.get(key) != expected:
                errors.append(f"decision.{key}")

    scope = value.get("scope")
    if not isinstance(scope, Mapping):
        errors.append("scope")
    else:
        for key, expected in (
            ("family", FAMILY),
            ("scope_id", SCOPE_ID),
            ("case_id", CASE_ID),
            ("job_id", JOB_ID),
        ):
            if scope.get(key) != expected:
                errors.append(f"scope.{key}")

    boundary = value.get("authorization_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("authorization_boundary")
    else:
        for key, expected in (
            ("authorization_missing", True),
            ("root_authorization_present", False),
            ("scheduler_authorization_present", False),
            ("probe_is_authorization", False),
            ("gpu_allocation_authorized", False),
            ("launch_admitted", False),
            ("worker_launch_authorized", False),
            ("formal", False),
            ("formal_eligible", False),
            ("credit", 0),
            ("qualification_credit", 0),
        ):
            if boundary.get(key) != expected:
                errors.append(f"authorization_boundary.{key}")

    input_boundary = value.get("input_boundary")
    if not isinstance(input_boundary, Mapping):
        errors.append("input_boundary")
    else:
        for key in (
            "json_only",
            "large_hdf5_resolved",
            "large_hdf5_opened",
            "large_hdf5_hashed",
            "large_hdf5_content_read",
        ):
            # ``large_hdf5_named_in_proposal_resolved`` is the actual field;
            # the alias below only keeps the loop readable.
            actual = (
                "large_hdf5_named_in_proposal_resolved"
                if key == "large_hdf5_resolved"
                else key
            )
            expected = True if key == "json_only" else False
            if input_boundary.get(actual) != expected:
                errors.append(f"input_boundary.{actual}")
        if input_boundary.get("worker_solver_native_gpu_queue_started") is not False:
            errors.append("input_boundary.worker_solver_native_gpu_queue_started")
        if input_boundary.get("registry_completion_ledger_denominator_gate_mutated") is not False:
            errors.append("input_boundary.registry_completion_ledger_denominator_gate_mutated")

    controls = value.get("execution_controls")
    if not isinstance(controls, Mapping):
        errors.append("execution_controls")
    else:
        for key in (
            "large_hdf5_opened",
            "large_hdf5_hashed",
            "large_hdf5_content_read",
            "worker_started",
            "solver_started",
            "native_started",
            "gpu_initialized",
            "queue_or_scheduler_started",
        ):
            if controls.get(key) is not False:
                errors.append(f"execution_controls.{key}")
        for key in _EXECUTION_MUTATION_KEYS:
            if controls.get(key) != 0:
                errors.append(f"execution_controls.{key}")

    checks = value.get("checks")
    if not isinstance(checks, Mapping):
        errors.append("checks")
    elif value.get("status") == "diagnostic_admission_blocked" and checks.get("input_contract_valid") is not True:
        errors.append("checks.input_contract_valid")

    projection = value.get("resource_projection")
    if not isinstance(projection, Mapping):
        errors.append("resource_projection")
    else:
        if projection.get("capacity_or_authorization_claim") is not False:
            errors.append("resource_projection.capacity_or_authorization_claim")
        if projection.get("gpu", {}).get("allocation_observed") is not False:
            errors.append("resource_projection.gpu.allocation_observed")
        if projection.get("gpu", {}).get("scheduler_authorized") is not False:
            errors.append("resource_projection.gpu.scheduler_authorized")

    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_projection(value)
    if errors:
        raise ValueError("refusing to write invalid F4 projection: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def render_zh_cn(value: Mapping[str, Any]) -> str:
    checks = value.get("checks", {})
    decision = value.get("decision", {})
    scope = value.get("scope", {})
    projection = value.get("resource_projection", {})
    gpu = projection.get("gpu", {}) if isinstance(projection, Mapping) else {}
    reasons = value.get("blocking_reasons", [])
    lines = [
        "# F4 Tallwall120 coarse host-I/O admission projection",
        "",
        f"- Schema：`{value.get('schema')}`",
        f"- 状态：`{value.get('status')}`",
        f"- Scope：`{scope.get('scope_id')}`",
        f"- Case：`{scope.get('case_id')}`",
        "",
        "## 投影决策",
        "",
        f"- 输入合同：`{decision.get('input_contract_valid')}`",
        f"- F4 scope：`{decision.get('f4_scope_bound')}`",
        f"- proposal/job normalized argv：`{decision.get('proposal_normalized_argv_valid')}` / `{decision.get('job_normalized_argv_valid')}`",
        f"- cwd：`{decision.get('cwd_valid')}`；fresh namespace：`{decision.get('fresh_output_namespace_valid')}`",
        f"- resource projection：`{decision.get('resource_projection_valid')}`",
        f"- launch admitted：`{decision.get('launch_admitted')}`；worker authorized：`{decision.get('worker_launch_authorized')}`",
        f"- formal：`{decision.get('formal')}`；credit：`{decision.get('credit')}`",
        "",
        "该结果是 JSON-only synthetic diagnostic projection。generic host-I/O probe 不是 root/scheduler authorization，因此本报告不授予 worker launch、formal admission、T2 或 credit。",
        "",
        "## 资源投影",
        "",
        f"- declared CPU/RAM/GPU：`{projection.get('job_resources', {}).get('cpu_cores')}` / `{projection.get('ram_mib')}` MiB / `{gpu.get('declared_peak_mib')}` MiB",
        f"- declared owned I/O：`{projection.get('declared_io_projection', {}).get('projected_owned_io_bytes')}` bytes",
        f"- declared total probe I/O：`{projection.get('declared_io_projection', {}).get('projected_total_io_bytes')}` bytes",
        f"- scheduler-owned I/O verified：`{projection.get('declared_io_projection', {}).get('scheduler_owned_io_verified')}`",
        f"- GPU allocation observed/authorized：`{gpu.get('allocation_observed')}` / `{gpu.get('scheduler_authorized')}`",
        "",
        "## 边界",
        "",
        "只读取 coarse proposal、generic host-I/O receipt 和 DEV_07 F4 job spec。未解析、打开、哈希或读取 proposal 指向的大体积 HDF5；未启动 worker、solver、native、GPU、queue；未修改 registry、completion、ledger、denominator 或 gate。",
        "",
        "## 阻塞原因",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in reasons)
    lines.append("")
    return "\n".join(lines)


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_projection(value)
    if errors:
        raise ValueError("refusing to write invalid F4 projection: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zh_cn(value), encoding="utf-8")
    return path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--proposal", type=Path, default=None)
    parser.add_argument("--host-io-receipt", type=Path, default=None)
    parser.add_argument("--job-spec", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--zh-cn-output", type=Path, default=DEFAULT_ZH_CN)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    value = build_projection(
        args.root,
        proposal_path=args.proposal,
        host_io_receipt_path=args.host_io_receipt,
        job_spec_path=args.job_spec,
    )
    write_report(value, args.output)
    write_zh_cn(value, args.zh_cn_output)
    print(json.dumps({"status": value["status"], "report": str(args.output)}, sort_keys=True))
    return 0 if value["status"] == "diagnostic_admission_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
