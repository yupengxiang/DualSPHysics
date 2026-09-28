#!/usr/bin/env python3
"""Build a source-bound, diagnostic-only admission envelope for F3 coarse s2.

This adapter joins the committed F3 coarse proposal with the committed bounded
host-I/O receipt.  It verifies the byte identity of the proposal, receipt,
current material/runtime sources, the source HDF5 (by bytes only), and the
historical job specification.  It never opens HDF5 as a container and never
calls ``core_runtime``.  A passing host-I/O probe is an observation, not root
or scheduler authorization, so this adapter can never admit a worker or grant
formal credit.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # Allow both ``python -m scripts...`` and direct script execution.
    from scripts import core_material_host_io_probe_v1 as host_io_probe
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI form.
    import core_material_host_io_probe_v1 as host_io_probe


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.material.f3.coarse.host_io_admission.v1"
CREATED_AT = "2026-09-28"

CANDIDATE_ID = "CORE-F3-MATERIAL-COARSE-s2"
JOB_ID = "core-f3-material-coarse-s2"

PROPOSAL = Path("reports/F3-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
HOST_IO_RECEIPT = Path("reports/CORE-MATERIAL-HOST-IO-PROBE-2026-09-28.json")
CORE_MATERIAL = Path("scripts/core_material.py")
CORE_RUNTIME = Path("scripts/core_runtime.py")
SOURCE_H5 = Path(
    "campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5"
)
JOB_SPEC = Path("campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json")

DEFAULT_JSON = LAB_ROOT / (
    "reports/F3-MATERIAL-COARSE-HOST-IO-ADMISSION-2026-09-28.json"
)
DEFAULT_ZH_CN = LAB_ROOT / (
    "reports/F3-MATERIAL-COARSE-HOST-IO-ADMISSION-2026-09-28.zh-CN.md"
)

_MUTATION_KEYS = (
    "registry_mutations",
    "completion_mutations",
    "ledger_mutations",
    "denominator_mutations",
    "gate_mutations",
    "plan_mutations",
)


def sha256_file(path: Path) -> str:
    """Hash bytes without interpreting the file format.

    In particular, the source HDF5 is handled only through this byte stream;
    this module intentionally has no HDF5 dependency or reader call.
    """

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _relative_or_absolute(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _empty_document_ref(root: Path, path: Path, role: str) -> dict[str, Any]:
    return {
        "path": _relative_or_absolute(root, path),
        "role": role,
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "expected_sha256": None,
        "sha256_match": False,
    }


def _bind(
    root: Path,
    path: Path,
    role: str,
    *,
    expected_sha256: str | None = None,
    hash_only: bool = False,
) -> dict[str, Any]:
    """Return a non-authorizing byte binding, including missing-file errors."""

    ref = _empty_document_ref(root, path, role)
    ref["expected_sha256"] = expected_sha256
    ref["hash_only"] = hash_only
    if hash_only:
        ref["opened_as_hdf5"] = False
    if not path.is_file():
        ref["error"] = "missing_file"
        return ref
    try:
        ref["bytes"] = path.stat().st_size
        ref["sha256"] = sha256_file(path)
        ref["sha256_match"] = (
            expected_sha256 is None or ref["sha256"] == expected_sha256
        )
    except (OSError, ValueError) as exc:
        ref["error"] = f"{type(exc).__name__}: {exc}"
    return ref


def _binding_value(document: Mapping[str, Any], name: str, key: str) -> Any:
    value = document.get("input_bindings", {}).get(name, {})
    return value.get(key) if isinstance(value, Mapping) else None


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _record(
    checks: dict[str, bool], reasons: list[str], name: str, value: bool, reason: str
) -> None:
    result = bool(value)
    checks[name] = result
    if not result:
        reasons.append(reason)


def _is_finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def _expected_argv(root: Path, source: Path, *, resume: bool = False) -> list[str]:
    argv = [
        str(root / ".venv/bin/python"),
        "-m",
        "scripts.core_material",
        "--source",
        str(source),
        "--output",
        "{attempt_dir}/material.h5",
        "--seeds",
        "512",
        "--substeps",
        "2",
        "--neighbour-variant",
        "baseline24",
    ]
    if resume:
        argv.append("--resume")
    return argv


def _forbidden_argv_reasons(argv: Any, root: Path) -> list[str]:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return ["argv_not_string_list"]
    values = [item.lower() for item in argv]
    reasons: list[str] = []
    if any(value.endswith("/scripts/core_material.py") for value in values):
        reasons.append("raw_script_path_forbidden")
    if "-m" not in values or "scripts.core_material" not in values:
        reasons.append("module_entry_required")
    if any(
        token in value
        for value in values
        for token in ("--gpu", "--cuda", "cuda_visible_devices")
    ):
        reasons.append("gpu_launch_or_override_forbidden")
    if any(
        token in value for value in values for token in ("--stop-after", "--kill-after")
    ):
        reasons.append("partial_or_kill_hook_forbidden")
    if any(
        token in value
        for value in values
        for token in ("row30", "--retry-row30", "--force-retry")
    ):
        reasons.append("row30_retry_forbidden")
    return reasons


def _validate_host_receipt(value: Mapping[str, Any]) -> list[str]:
    try:
        return list(host_io_probe.validate_report(value))
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"host_io_validator_error:{type(exc).__name__}:{exc}"]


def _proposal_checks(
    proposal: Mapping[str, Any],
    root: Path,
    source: Path,
    job_spec: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    candidate = proposal.get("candidate")
    state = proposal.get("proposal_state")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    state = state if isinstance(state, Mapping) else {}

    expected_candidate = {
        "configuration_id": CANDIDATE_ID,
        "job_id": JOB_ID,
        "family": "F3",
        "source_role": "coarse",
        "substeps": 2,
        "seeds": 512,
        "neighbour_variant": "baseline24",
    }
    candidate_checks: dict[str, bool] = {}
    for key, expected in expected_candidate.items():
        ok = candidate.get(key) == expected
        candidate_checks[key] = ok
        if not ok:
            reasons.append(f"proposal.candidate.{key}")

    expected_state = {
        "proposal_only": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "launch_admitted": False,
    }
    state_checks: dict[str, bool] = {}
    for key, expected in expected_state.items():
        ok = state.get(key) == expected
        state_checks[key] = ok
        if not ok:
            reasons.append(f"proposal.proposal_state.{key}")

    _record(
        checks,
        reasons,
        "proposal_schema",
        proposal.get("schema") == "core.material.f3.coarse.proposal.v1",
        "proposal.schema",
    )
    _record(
        checks,
        reasons,
        "proposal_status",
        proposal.get("status") == "proposal_only_fail_closed",
        "proposal.status",
    )
    _record(
        checks,
        reasons,
        "proposal_candidate_fields",
        all(candidate_checks.values()),
        "proposal.candidate_fields",
    )
    _record(
        checks,
        reasons,
        "proposal_state_fields",
        all(state_checks.values()),
        "proposal.proposal_state_fields",
    )

    source_contract = proposal.get("source_manifest_contract")
    source_window = source_contract.get("window") if isinstance(source_contract, Mapping) else {}
    source_contract_ok = (
        isinstance(source_contract, Mapping)
        and source_contract.get("source_role") == "coarse"
        and source_contract.get("case_id") == "R0081818-NOMINAL"
        and source_contract.get("formal_release") is False
        and source_contract.get("qualified") is False
        and source_contract.get("launch_allowed") is False
        and isinstance(source_window, Mapping)
        and source_window.get("native_frame_count") == 836
        and source_window.get("hdf5_structure_opened_by_proposal") is False
    )
    _record(
        checks,
        reasons,
        "proposal_source_contract",
        source_contract_ok,
        "proposal.source_manifest_contract",
    )

    bindings = proposal.get("input_bindings")
    bindings = bindings if isinstance(bindings, Mapping) else {}
    binding_paths_ok = {
        "core_material": _binding_value(proposal, "core_material", "path") == str(CORE_MATERIAL),
        "source_h5": _binding_value(proposal, "source_h5", "path") == str(SOURCE_H5),
        "job_spec": _binding_value(proposal, "job_spec", "path") == str(JOB_SPEC),
        "current_frozen_worker": _binding_value(proposal, "current_frozen_worker", "path")
        == str(CORE_RUNTIME),
    }
    for name, ok in binding_paths_ok.items():
        if not ok:
            reasons.append(f"proposal.input_bindings.{name}.path")
    _record(
        checks,
        reasons,
        "proposal_binding_paths",
        all(binding_paths_ok.values()),
        "proposal.input_bindings.paths",
    )

    source_binding = bindings.get("source_h5", {})
    source_hash_only_ok = (
        isinstance(source_binding, Mapping)
        and source_binding.get("hash_only") is True
        and source_binding.get("opened_as_hdf5") is False
        and source_binding.get("sha256") == _binding_value(proposal, "source_h5", "sha256")
    )
    _record(
        checks,
        reasons,
        "proposal_source_hash_only",
        source_hash_only_ok,
        "proposal.source_h5 must be hash-only",
    )

    fresh = proposal.get("fresh_attempt_namespace")
    fresh = fresh if isinstance(fresh, Mapping) else {}
    expected_attempt_root = f"campaigns/core-v1/runtime/attempts/{JOB_ID}"
    fresh_ok = (
        fresh.get("created") is False
        and fresh.get("attempt_root") == expected_attempt_root
        and fresh.get("namespace_template") == expected_attempt_root + "/<fresh-attempt-id>"
        and fresh.get("same_attempt_resume_only") is True
        and fresh.get("historical_attempt_reuse_forbidden") is True
        and fresh.get("proposal_created_path") is None
    )
    _record(
        checks,
        reasons,
        "fresh_attempt_namespace",
        fresh_ok,
        "proposal.fresh_attempt_namespace",
    )

    normalized = proposal.get("normalized_launch")
    normalized = normalized if isinstance(normalized, Mapping) else {}
    cli = proposal.get("cli_contract")
    cli = cli if isinstance(cli, Mapping) else {}
    expected = _expected_argv(root, source)
    expected_resume = _expected_argv(root, source, resume=True)
    argv_ok = (
        normalized.get("argv") == expected
        and normalized.get("resume_argv_same_attempt") == expected_resume
        and normalized.get("full_native_window") is True
        and normalized.get("stop_after") is None
        and normalized.get("output") == "{attempt_dir}/material.h5"
        and not _forbidden_argv_reasons(normalized.get("argv"), root)
    )
    cwd_ok = (
        normalized.get("cwd") == str(root)
        and cli.get("cwd") == str(root)
        and job_spec.get("cwd") == str(root)
    )
    _record(checks, reasons, "normalized_argv", argv_ok, "proposal.normalized_launch.argv")
    _record(checks, reasons, "launch_cwd", cwd_ok, "proposal/job_spec cwd")

    proposal_resources = proposal.get("resource_admission")
    proposal_resources = (
        proposal_resources if isinstance(proposal_resources, Mapping) else {}
    )
    job_fields_ok = (
        job_spec.get("job_id") == JOB_ID
        and job_spec.get("logical_id") == CANDIDATE_ID
        and job_spec.get("qualification_claim") == "none; diagnostic matrix only"
        and job_spec.get("resources") == proposal_resources.get("resource_request")
    )
    _record(checks, reasons, "job_spec_fields", job_fields_ok, "job_spec candidate/resources")

    resource_policy_ok = (
        proposal_resources.get("status") == "not_measured_proposal_only"
        and proposal_resources.get("measured_admission_required") is True
        and proposal_resources.get("cpu_only") is True
        and proposal_resources.get("gpu_forbidden") is True
        and proposal_resources.get("gpu_vram_headroom_is_not_admission") is True
        and proposal_resources.get("snapshot_collected_by_proposal") is False
        and isinstance(proposal_resources.get("resource_request"), Mapping)
        and proposal_resources["resource_request"].get("gpu_peak_mib") == 0
    )
    _record(
        checks,
        reasons,
        "proposal_resource_policy",
        resource_policy_ok,
        "proposal.resource_admission policy",
    )

    proposal_valid = all(
        checks.get(name, False)
        for name in (
            "proposal_schema",
            "proposal_status",
            "proposal_candidate_fields",
            "proposal_state_fields",
            "proposal_source_contract",
            "proposal_binding_paths",
            "proposal_source_hash_only",
            "fresh_attempt_namespace",
            "normalized_argv",
            "launch_cwd",
            "job_spec_fields",
            "proposal_resource_policy",
        )
    )
    _record(checks, reasons, "proposal_contract_valid", proposal_valid, "proposal contract")

    return {
        "candidate": dict(candidate),
        "proposal_state": dict(state),
        "fresh_attempt_namespace": dict(fresh),
        "normalized_launch": {
            "cwd": normalized.get("cwd"),
            "argv": normalized.get("argv"),
            "resume_argv_same_attempt": normalized.get("resume_argv_same_attempt"),
            "full_native_window": normalized.get("full_native_window"),
            "stop_after": normalized.get("stop_after"),
            "output": normalized.get("output"),
        },
        "cli_contract": {
            "module": cli.get("module"),
            "python": cli.get("python"),
            "cwd": cli.get("cwd"),
            "observed_raw_script_path": cli.get("observed_raw_script_path"),
            "normalization_required": cli.get("normalization_required"),
        },
        "resource_request": proposal_resources.get("resource_request", {}),
        "cpu_only": proposal_resources.get("cpu_only"),
        "gpu_forbidden": proposal_resources.get("gpu_forbidden"),
        "blocking_reasons": list(proposal.get("blocking_reasons", []))
        if isinstance(proposal.get("blocking_reasons", []), list)
        else [],
    }


def _host_checks(
    receipt: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> tuple[list[str], dict[str, Any]]:
    validation_errors = _validate_host_receipt(receipt)
    probe = receipt.get("probe") if isinstance(receipt.get("probe"), Mapping) else {}
    request = receipt.get("request") if isinstance(receipt.get("request"), Mapping) else {}
    projection = (
        receipt.get("owned_io_projection")
        if isinstance(receipt.get("owned_io_projection"), Mapping)
        else {}
    )
    io = (
        receipt.get("io_measurement")
        if isinstance(receipt.get("io_measurement"), Mapping)
        else {}
    )
    boundary = (
        receipt.get("authorization_boundary")
        if isinstance(receipt.get("authorization_boundary"), Mapping)
        else {}
    )

    _record(
        checks,
        reasons,
        "host_io_receipt_schema",
        receipt.get("schema") == host_io_probe.SCHEMA,
        "host_io_receipt.schema",
    )
    _record(
        checks,
        reasons,
        "host_io_receipt_valid",
        not validation_errors,
        "host_io_receipt.validation",
    )
    _record(
        checks,
        reasons,
        "probe_pass",
        probe.get("probe_pass") is True,
        "host_io_receipt.probe.probe_pass",
    )
    _record(
        checks,
        reasons,
        "measurement_complete",
        probe.get("measurement_complete") is True,
        "host_io_receipt.probe.measurement_complete",
    )
    _record(
        checks,
        reasons,
        "probe_contract_valid",
        probe.get("contract_valid") is True,
        "host_io_receipt.probe.contract_valid",
    )
    _record(
        checks,
        reasons,
        "probe_diagnostic_status",
        receipt.get("status") == "diagnostic_pass",
        "host_io_receipt.status",
    )
    family_scope = request.get("family_scope")
    _record(
        checks,
        reasons,
        "host_family_scope",
        isinstance(family_scope, list) and "F3" in family_scope,
        "host_io_receipt.request.family_scope must include F3",
    )
    _record(
        checks,
        reasons,
        "probe_is_not_authorization",
        boundary.get("probe_is_authorization") is False,
        "host_io_receipt.authorization_boundary.probe_is_authorization",
    )
    return validation_errors, {
        "schema": receipt.get("schema"),
        "status": receipt.get("status"),
        "probe": {
            "probe_pass": probe.get("probe_pass"),
            "contract_valid": probe.get("contract_valid"),
            "measurement_complete": probe.get("measurement_complete"),
            "checks": dict(probe.get("checks", {}))
            if isinstance(probe.get("checks"), Mapping)
            else {},
        },
        "request": {
            "family_scope": request.get("family_scope"),
            "probe_bytes": request.get("probe_bytes"),
            "concurrency": request.get("concurrency"),
            "owned_io_bytes_per_worker": request.get("owned_io_bytes_per_worker"),
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
            "fsync_count": io.get("fsync_count"),
            "readback_sha256_match": io.get("readback_sha256_match"),
            "elapsed_seconds": io.get("elapsed_seconds"),
        },
        "authorization_boundary": {
            "root_authorization_required": boundary.get("root_authorization_required"),
            "scheduler_authorization_required": boundary.get(
                "scheduler_authorization_required"
            ),
            "probe_is_authorization": boundary.get("probe_is_authorization"),
            "worker_launch_authorized": boundary.get("worker_launch_authorized"),
            "formal_admission": boundary.get("formal_admission"),
            "qualification_credit": boundary.get("qualification_credit"),
        },
        "validation_errors": validation_errors,
    }


def _resource_projection(
    proposal: Mapping[str, Any],
    job_spec: Mapping[str, Any],
    receipt: Mapping[str, Any],
    host_observation: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    request = host_observation.get("request", {})
    projection = host_observation.get("projection", {})
    io = host_observation.get("io_measurement", {})
    resources = proposal.get("resource_request", {})
    resources = resources if isinstance(resources, Mapping) else {}
    job_resources = job_spec.get("resources", {})
    job_resources = job_resources if isinstance(job_resources, Mapping) else {}
    disk = receipt.get("disk") if isinstance(receipt.get("disk"), Mapping) else {}
    disk_after = disk.get("after") if isinstance(disk.get("after"), Mapping) else {}
    cpu = receipt.get("cpu") if isinstance(receipt.get("cpu"), Mapping) else {}
    ram = receipt.get("ram") if isinstance(receipt.get("ram"), Mapping) else {}
    cpu_after = cpu.get("after") if isinstance(cpu.get("after"), Mapping) else {}
    ram_after = ram.get("after") if isinstance(ram.get("after"), Mapping) else {}

    resources_match = resources == job_resources
    _record(
        checks,
        reasons,
        "resource_request_matches_job_spec",
        resources_match,
        "proposal.resource_admission.resource_request vs job_spec.resources",
    )
    projection_owned = projection.get("projected_owned_io_bytes")
    projection_total = projection.get("projected_total_io_bytes")
    projection_write = projection.get("probe_write_bytes")
    projection_read = projection.get("probe_read_bytes")
    projection_arithmetic_ok = (
        isinstance(projection_owned, int)
        and isinstance(projection_total, int)
        and isinstance(projection_write, int)
        and isinstance(projection_read, int)
        and projection_total == projection_owned + projection_write + projection_read
    )
    projection_shape = (
        request.get("concurrency") == resources.get("cpu_cores")
        and request.get("concurrency") == projection.get("concurrency")
        and isinstance(request.get("concurrency"), int)
        and request.get("concurrency") > 0
        and isinstance(projection.get("owned_io_bytes_per_worker"), int)
        and projection.get("owned_io_bytes_per_worker") > 0
        and projection.get("projected_owned_io_bytes")
        == request.get("concurrency") * projection.get("owned_io_bytes_per_worker")
        and projection_arithmetic_ok
        and projection.get("observed") is False
        and projection.get("scheduler_owned_io_verified") is False
    )
    _record(
        checks,
        reasons,
        "resource_projection_shape",
        projection_shape,
        "host_io_receipt.owned_io_projection",
    )
    io_shape = (
        io.get("bytes_requested") == request.get("probe_bytes")
        and io.get("bytes_written") == io.get("bytes_requested")
        and io.get("bytes_read") == io.get("bytes_requested")
        and io.get("fsync_count") == 1
        and io.get("readback_sha256_match") is True
        and _is_finite_nonnegative(io.get("elapsed_seconds"))
    )
    _record(checks, reasons, "io_measurement_shape", io_shape, "host_io_receipt.io_measurement")
    snapshot_shape = (
        _is_finite_nonnegative(disk_after.get("free_bytes"))
        and disk_after.get("free_bytes") >= 20 * 1024**3
        and _is_finite_nonnegative(cpu_after.get("logical_cpu_count"))
        and cpu_after.get("logical_cpu_count") >= 1
        and _is_finite_nonnegative(cpu_after.get("affinity_cpu_count"))
        and cpu_after.get("affinity_cpu_count") >= 1
        and _is_finite_nonnegative(ram_after.get("total_bytes"))
        and _is_finite_nonnegative(ram_after.get("available_bytes"))
        and ram_after.get("available_bytes") <= ram_after.get("total_bytes")
    )
    _record(
        checks,
        reasons,
        "resource_snapshot_shape",
        snapshot_shape,
        "host_io_receipt resource snapshots",
    )

    return {
        "proposal_request": dict(resources) if isinstance(resources, Mapping) else {},
        "job_spec_request": dict(job_resources) if isinstance(job_resources, Mapping) else {},
        "probe_request": dict(request),
        "probe_projection": dict(projection),
        "io_measurement": dict(io),
        "disk_after": dict(disk_after),
        "cpu_after": dict(cpu_after),
        "ram_after": dict(ram_after),
        "cpu_only": resources.get("gpu_peak_mib") == 0,
        "gpu_forbidden": proposal.get("gpu_forbidden") is True,
        "scheduler_owned_io_verified": projection.get("scheduler_owned_io_verified") is True,
        "diagnostic_projection_only": True,
    }


def _authorization_boundary(
    proposal: Mapping[str, Any],
    receipt: Mapping[str, Any],
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    proposal_auth = proposal.get("authorization")
    proposal_auth = proposal_auth if isinstance(proposal_auth, Mapping) else {}
    receipt_auth = receipt.get("authorization_boundary")
    receipt_auth = receipt_auth if isinstance(receipt_auth, Mapping) else {}

    root_required = proposal_auth.get("fresh_root_authorization_required") is True and receipt_auth.get(
        "root_authorization_required"
    ) is True
    scheduler_required = receipt_auth.get("scheduler_authorization_required") is True
    _record(checks, reasons, "root_authorization_required", root_required, "root authorization requirement")
    _record(
        checks,
        reasons,
        "scheduler_authorization_required",
        scheduler_required,
        "scheduler authorization requirement",
    )

    # No root/scheduler receipt is an input to this adapter.  Even a proposal
    # claiming ``status=granted`` cannot manufacture the missing receipt.
    root_present = False
    scheduler_present = False
    reasons.append("fresh_root_authorization_missing")
    reasons.append("scheduler_authorization_missing")
    if proposal_auth.get("status") != "not_granted":
        reasons.append("untrusted_authorization_claim_not_accepted")
    _record(
        checks,
        reasons,
        "authorization_missing",
        not root_present and not scheduler_present,
        "root/scheduler authorization must be absent for fail-closed diagnostic",
    )

    return {
        "proposal_status": proposal_auth.get("status"),
        "root_authorization_required": root_required,
        "scheduler_authorization_required": scheduler_required,
        "root_authorization_present": root_present,
        "scheduler_authorization_present": scheduler_present,
        "authorization_missing": True,
        "probe_is_authorization": False,
        "runtime_spec_ready_is_not_authorization": proposal_auth.get(
            "runtime_spec_ready_for_root_queue_is_not_authorization"
        )
        is True,
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
        "source_hdf5_hash_only": True,
        "source_hdf5_opened_as_hdf5": False,
        "production_hdf5_opened": False,
        "material_worker_started": False,
        "solver_started": False,
        "gpu_initialized": False,
        "queue_or_scheduler_started": False,
        "core_runtime_called": False,
        "historical_receipt_rewritten": False,
        **{key: 0 for key in _MUTATION_KEYS},
    }


def build_admission(
    root: str | Path = LAB_ROOT,
    *,
    proposal_path: str | Path | None = None,
    host_io_receipt_path: str | Path | None = None,
    source_h5_path: str | Path | None = None,
    job_spec_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the adapter receipt without launching or mutating a campaign."""

    root = Path(root).resolve()
    proposal_file = _resolve(root, proposal_path or PROPOSAL)
    host_file = _resolve(root, host_io_receipt_path or HOST_IO_RECEIPT)

    proposal_ref = _bind(root, proposal_file, "committed F3 coarse proposal JSON")
    host_ref = _bind(root, host_file, "committed bounded host-I/O diagnostic receipt")
    try:
        proposal = _read_json(proposal_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        proposal = {}
        proposal_error = f"{type(exc).__name__}: {exc}"
    else:
        proposal_error = None
    try:
        host_receipt = _read_json(host_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        host_receipt = {}
        host_error = f"{type(exc).__name__}: {exc}"
    else:
        host_error = None

    source_file = _resolve(root, source_h5_path or SOURCE_H5)
    job_file = _resolve(root, job_spec_path or JOB_SPEC)
    core_material_file = _resolve(root, CORE_MATERIAL)
    core_runtime_file = _resolve(root, CORE_RUNTIME)
    expected_source_sha = _binding_value(proposal, "source_h5", "sha256")
    expected_job_sha = _binding_value(proposal, "job_spec", "sha256")
    expected_material_sha = _binding_value(proposal, "core_material", "sha256")
    expected_runtime_sha = _binding_value(
        proposal, "current_frozen_worker", "sha256"
    )

    source_ref = _bind(
        root,
        source_file,
        "read-only coarse native source; byte hash only",
        expected_sha256=expected_source_sha
        if isinstance(expected_source_sha, str)
        else None,
        hash_only=True,
    )
    job_ref = _bind(
        root,
        job_file,
        "historical coarse job specification SHA binding",
        expected_sha256=expected_job_sha if isinstance(expected_job_sha, str) else None,
    )
    material_ref = _bind(
        root,
        core_material_file,
        "current scripts/core_material.py",
        expected_sha256=expected_material_sha
        if isinstance(expected_material_sha, str)
        else None,
    )
    runtime_ref = _bind(
        root,
        core_runtime_file,
        "current scripts/core_runtime.py",
        expected_sha256=expected_runtime_sha
        if isinstance(expected_runtime_sha, str)
        else None,
    )

    try:
        job_spec = _read_json(job_file)
        job_error = None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        job_spec = {}
        job_error = f"{type(exc).__name__}: {exc}"

    checks: dict[str, bool] = {}
    reasons: list[str] = []
    if proposal_error:
        reasons.append(f"proposal_read_failed:{proposal_error}")
    if host_error:
        reasons.append(f"host_io_receipt_read_failed:{host_error}")
    if job_error:
        reasons.append(f"job_spec_read_failed:{job_error}")

    proposal_observation = _proposal_checks(
        proposal, root, source_file, job_spec, checks, reasons
    )
    reasons.extend(proposal_observation.get("blocking_reasons", []))
    host_validation_errors, host_observation = _host_checks(
        host_receipt, checks, reasons
    )
    resource_observation = _resource_projection(
        proposal_observation,
        job_spec,
        host_receipt,
        host_observation,
        checks,
        reasons,
    )

    for name, ref in (
        ("source_h5_binding", source_ref),
        ("job_spec_binding", job_ref),
        ("core_material_binding", material_ref),
        ("core_runtime_binding", runtime_ref),
    ):
        _record(
            checks,
            reasons,
            name,
            ref.get("exists") is True and ref.get("sha256_match") is True,
            name,
        )
    _record(
        checks,
        reasons,
        "proposal_file_present",
        proposal_ref.get("exists") is True and proposal_ref.get("sha256") is not None,
        "proposal JSON binding",
    )
    _record(
        checks,
        reasons,
        "host_io_receipt_file_present",
        host_ref.get("exists") is True and host_ref.get("sha256") is not None,
        "host-I/O receipt binding",
    )

    authorization = _authorization_boundary(proposal, host_receipt, checks, reasons)
    execution_controls = _execution_controls()

    contract_names = (
        "proposal_contract_valid",
        "host_io_receipt_schema",
        "host_io_receipt_valid",
        "probe_pass",
        "measurement_complete",
        "probe_contract_valid",
        "probe_diagnostic_status",
        "probe_is_not_authorization",
        "resource_request_matches_job_spec",
        "resource_projection_shape",
        "io_measurement_shape",
        "resource_snapshot_shape",
        "source_h5_binding",
        "job_spec_binding",
        "core_material_binding",
        "core_runtime_binding",
        "proposal_file_present",
        "host_io_receipt_file_present",
    )
    contract_valid = all(checks.get(name) is True for name in contract_names)
    _record(checks, reasons, "admission_contract_valid", contract_valid, "adapter contract")

    # The adapter itself is permanently non-authorizing.  A complete probe only
    # makes the diagnostic contract valid; it cannot make this decision true.
    status = "diagnostic_admission_blocked" if contract_valid else "failed_closed"
    reasons = _unique(reasons)
    return {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "status": status,
        "candidate": {
            "configuration_id": CANDIDATE_ID,
            "job_id": JOB_ID,
            "family": "F3",
            "source_role": "coarse",
            "substeps": 2,
            "seeds": 512,
            "neighbour_variant": "baseline24",
        },
        "input_bindings": {
            "proposal": proposal_ref,
            "host_io_receipt": host_ref,
            "core_material": material_ref,
            "core_runtime": runtime_ref,
            "source_h5": source_ref,
            "job_spec": job_ref,
        },
        "checks": checks,
        "proposal_observation": proposal_observation,
        "host_io_observation": host_observation,
        "resource_projection": resource_observation,
        "authorization_boundary": authorization,
        "decision": {
            "probe_pass": checks.get("probe_pass", False),
            "measurement_complete": checks.get("measurement_complete", False),
            "proposal_contract_valid": checks.get("proposal_contract_valid", False),
            "fresh_namespace_valid": checks.get("fresh_attempt_namespace", False),
            "argv_valid": checks.get("normalized_argv", False),
            "cwd_valid": checks.get("launch_cwd", False),
            "resource_projection_valid": checks.get(
                "resource_projection_shape", False
            ),
            "root_authorization_present": False,
            "scheduler_authorization_present": False,
            "launch_admitted": False,
            "worker_launch_authorized": False,
            "formal": False,
            "formal_eligible": False,
            "credit": 0,
            "qualification_credit": 0,
        },
        # Top-level aliases make the fail-closed boundary easy for simple
        # consumers to inspect without weakening the nested decision object.
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "formal": False,
        "formal_eligible": False,
        "credit": 0,
        "qualification_credit": 0,
        "execution_controls": execution_controls,
        "blocking_reasons": reasons,
        "diagnostic_errors": {
            "proposal": proposal_error,
            "host_io_receipt": host_error,
            "job_spec": job_error,
            "host_io_validation": host_validation_errors,
        },
        "next_safe_action": (
            "Obtain separate fresh root and scheduler authorization receipts bound to "
            "these exact hashes, normalized module argv/cwd, and a scheduler-owned "
            "resource reservation; do not launch from this diagnostic envelope."
        ),
    }


def validate_admission(value: Mapping[str, Any]) -> list[str]:
    """Validate that a serialized adapter report remains fail-closed."""

    errors: list[str] = []
    if value.get("schema") != SCHEMA:
        errors.append("schema")
    if value.get("status") not in {"diagnostic_admission_blocked", "failed_closed"}:
        errors.append("status")
    candidate = value.get("candidate", {})
    if not isinstance(candidate, Mapping) or candidate.get("configuration_id") != CANDIDATE_ID:
        errors.append("candidate.configuration_id")
    for key, expected in (
        ("launch_admitted", False),
        ("worker_launch_authorized", False),
        ("formal", False),
        ("formal_eligible", False),
        ("credit", 0),
        ("qualification_credit", 0),
    ):
        if value.get(key) != expected:
            errors.append(key)
    decision = value.get("decision", {})
    boundary = value.get("authorization_boundary", {})
    if not isinstance(decision, Mapping):
        errors.append("decision")
    else:
        for key, expected in (
            ("launch_admitted", False),
            ("worker_launch_authorized", False),
            ("formal", False),
            ("formal_eligible", False),
            ("credit", 0),
            ("qualification_credit", 0),
            ("root_authorization_present", False),
            ("scheduler_authorization_present", False),
        ):
            if decision.get(key) != expected:
                errors.append(f"decision.{key}")
    if not isinstance(boundary, Mapping) or boundary.get("authorization_missing") is not True:
        errors.append("authorization_boundary.authorization_missing")
    source = value.get("input_bindings", {}).get("source_h5", {})
    if not isinstance(source, Mapping):
        errors.append("input_bindings.source_h5")
    else:
        if source.get("hash_only") is not True:
            errors.append("input_bindings.source_h5.hash_only")
        if source.get("opened_as_hdf5") is not False:
            errors.append("input_bindings.source_h5.opened_as_hdf5")
    controls = value.get("execution_controls", {})
    if not isinstance(controls, Mapping):
        errors.append("execution_controls")
    else:
        for key in (
            "source_hdf5_opened_as_hdf5",
            "production_hdf5_opened",
            "material_worker_started",
            "solver_started",
            "gpu_initialized",
            "queue_or_scheduler_started",
            "core_runtime_called",
            "historical_receipt_rewritten",
        ):
            if controls.get(key) is not False:
                errors.append(f"execution_controls.{key}")
        for key in _MUTATION_KEYS:
            if controls.get(key) != 0:
                errors.append(f"execution_controls.{key}")
    checks = value.get("checks", {})
    if not isinstance(checks, Mapping):
        errors.append("checks")
    elif value.get("status") == "diagnostic_admission_blocked" and checks.get(
        "admission_contract_valid"
    ) is not True:
        errors.append("checks.admission_contract_valid")
    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_admission(value)
    if errors:
        raise ValueError("refusing to write invalid admission report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_zh_cn(value: Mapping[str, Any]) -> str:
    """Render a short human-readable report without adding new authority."""

    bindings = value.get("input_bindings", {})
    checks = value.get("checks", {})
    decision = value.get("decision", {})
    projection = value.get("resource_projection", {})
    reasons = value.get("blocking_reasons", [])
    lines = [
        "# F3 coarse material host-I/O diagnostic admission",
        "",
        f"- Schema: `{value.get('schema')}`",
        f"- 状态：`{value.get('status')}`",
        f"- 候选：`{value.get('candidate', {}).get('configuration_id')}`",
        "",
        "## 决策",
        "",
        f"- `probe_pass`: `{decision.get('probe_pass')}`",
        f"- `measurement_complete`: `{decision.get('measurement_complete')}`",
        f"- `proposal_contract_valid`: `{decision.get('proposal_contract_valid')}`",
        f"- `fresh_namespace_valid`: `{decision.get('fresh_namespace_valid')}`",
        f"- `argv_valid/cwd_valid`: `{decision.get('argv_valid')}` / `{decision.get('cwd_valid')}`",
        f"- `resource_projection_valid`: `{decision.get('resource_projection_valid')}`",
        f"- `launch_admitted`: `{decision.get('launch_admitted')}`",
        f"- `worker_launch_authorized`: `{decision.get('worker_launch_authorized')}`",
        f"- `formal`: `{decision.get('formal')}`, `credit`: `{decision.get('credit')}`",
        "",
        "即使 bounded host-I/O probe 通过，它也不是 root/scheduler authorization；本适配器因此保持 launch、worker、formal 和 credit 全部关闭。",
        "",
        "## Source-bound 输入",
        "",
    ]
    for name in ("proposal", "host_io_receipt", "core_material", "core_runtime", "source_h5", "job_spec"):
        ref = bindings.get(name, {})
        lines.append(
            f"- `{name}`: `{ref.get('path')}`, SHA256 `{ref.get('sha256')}`, "
            f"match=`{ref.get('sha256_match')}`"
        )
    lines.extend(
        [
            "",
            "## 资源投影",
            "",
            f"- CPU-only: `{projection.get('cpu_only')}`；GPU forbidden: `{projection.get('gpu_forbidden')}`",
            f"- projected owned I/O: `{projection.get('probe_projection', {}).get('projected_owned_io_bytes')}` bytes",
            f"- projected total I/O: `{projection.get('probe_projection', {}).get('projected_total_io_bytes')}` bytes",
            f"- scheduler-owned I/O verified: `{projection.get('scheduler_owned_io_verified')}`",
            "",
            "## 阻塞原因",
            "",
        ]
    )
    lines.extend(f"- `{reason}`" for reason in reasons)
    lines.extend(
        [
            "",
            "## 执行边界",
            "",
            "本适配器只读取 JSON/源码并对 source HDF5 做字节哈希；未打开 HDF5 结构，未启动 material worker、solver、GPU、queue，未改写 registry/completion/ledger/denominator/gate/PLAN 或历史 receipt。",
            "",
        ]
    )
    return "\n".join(lines)


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    if validate_admission(value):
        raise ValueError("refusing to write invalid admission report")
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
    parser.add_argument("--source-h5", type=Path, default=None)
    parser.add_argument("--job-spec", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--zh-cn-output", type=Path, default=DEFAULT_ZH_CN)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_admission(
        args.root,
        proposal_path=args.proposal,
        host_io_receipt_path=args.host_io_receipt,
        source_h5_path=args.source_h5,
        job_spec_path=args.job_spec,
    )
    write_report(report, args.output)
    write_zh_cn(report, args.zh_cn_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 0 if report["status"] == "diagnostic_admission_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
