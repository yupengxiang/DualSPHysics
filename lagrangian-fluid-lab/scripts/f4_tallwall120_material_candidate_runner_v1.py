#!/usr/bin/env python3
"""Bounded F4 Tallwall120 material candidate runner/receipt bridge.

The existing F4 tracer is a real diagnostic runner, while the current
DEV_07 source-bound proposal is not executable: the collection path and reader
receipt drift, the material diagnostic is short-window/right-censored, and no
fresh root/scheduler authorization exists.  This module is the narrow bridge
between those observations and a future authorized sidecar producer.

It intentionally performs no material trace.  It reads bounded JSON, calls
the existing JSON-only root/scheduler intake, lstat-checks the trajectory via
that intake, and observes GPU/RAM/disk capacity.  It never imports h5py,
opens or hashes the trajectory, creates the fresh output namespace, starts a
solver/worker/GPU/queue, or writes a material sidecar.  The only output it
may write is its own bounded receipt report.  Every scientific and
qualification marker is fail-closed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f4_tallwall120_material_root_scheduler_intake_v1 as root_intake


SCHEMA = "core.material.f4.tallwall120.candidate_runner_receipt.v1"
RECORD_ID = "f4-tallwall120-material-candidate-runner-receipt-v1"
CREATED_AT = "2026-09-28"
FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = f"{SCOPE_ID}_DEV_07"
SOURCE_HDF5 = root_intake.SOURCE_HDF5
SOURCE_SHA256 = root_intake.SOURCE_SHA256
SOURCE_BYTES = root_intake.SOURCE_BYTES
EXPECTED_Q = 0.23437500000000008
EXPECTED_DP_M = 0.0075
EXPECTED_SEEDS = 512
EXPECTED_SUBSTEPS = 2
EXPECTED_NEIGHBOUR_VARIANT = "baseline24"
REQUIRED_EVENT_WINDOW_S = 8.68
UNKNOWN_FRACTION_MAX = 0.01
RELIABLE_COVERAGE_MIN = 1.0
GPU_PEAK_MIB = 6144
RAM_REQUIRED_MIB = 24576
DISK_REQUIRED_BYTES = 8 * 1024**3
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_NVIDIA_LINES = 16

ROOT_INTAKE_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.json"
)
DIAGNOSTIC_REPORT = Path(
    "reports/F4-TALLWALL120-DEV07-MATERIAL-BASELINE24-DIAGNOSTIC-2026-09-28.json"
)
DEFAULT_OUTPUT = Path(
    "reports/F4-TALLWALL120-MATERIAL-CANDIDATE-RUNNER-RECEIPT-V1-2026-09-28.json"
)
PLANNED_NAMESPACE = Path(root_intake.DEFAULT_OUTPUT_NAMESPACE)
PLANNED_SIDECAR = PLANNED_NAMESPACE / "product/material_case_sidecar.json"
PLANNED_SIDECAR_SCHEMA = "core.material.f4.tallwall120.material_case_sidecar.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_json(root: Path, relative: str | Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    path = (root / Path(relative)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return {}, {"role": role, "path": str(relative), "exists": False}, "path_escape"
    reference: dict[str, Any] = {
        "role": role,
        "path": path.relative_to(root.resolve()).as_posix(),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "content_read": False,
        "content_hash_recomputed": False,
    }
    if not path.is_file():
        return {}, reference, "missing_file"
    size = path.stat().st_size
    reference["bytes"] = size
    if size > MAX_JSON_BYTES:
        return {}, reference, "file_exceeds_bounded_limit"
    try:
        data = path.read_bytes()
        reference.update(
            {
                "sha256": _sha256(data),
                "content_read": True,
                "content_hash_recomputed": True,
            }
        )
        payload = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, reference, "invalid_json"
    if not isinstance(payload, dict):
        return {}, reference, "json_not_object"
    return payload, reference, None


def _safe_int(value: str) -> int | None:
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _gpu_snapshot() -> dict[str, Any]:
    """Observe nvidia-smi without initializing a CUDA context or selecting a GPU."""

    query = (
        "index,name,memory.total,memory.used,memory.free,utilization.gpu"
    )
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={query}",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "observed": False,
            "shared_gpu_policy": "existing_gpu_occupancy_is_allowed;_free_vram_is_the_only_capacity_gate",
            "required_peak_mib": GPU_PEAK_MIB,
            "devices": [],
            "max_free_mib": None,
            "capacity_pass": False,
            "error": type(error).__name__,
        }

    devices: list[dict[str, Any]] = []
    lines = completed.stdout.splitlines()[:MAX_NVIDIA_LINES]
    for line in lines:
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 6:
            continue
        index = _safe_int(fields[0])
        total = _safe_int(fields[2])
        used = _safe_int(fields[3])
        free = _safe_int(fields[4])
        utilization = _safe_int(fields[5])
        if None in (index, total, used, free, utilization):
            continue
        devices.append(
            {
                "index": index,
                "name": fields[1],
                "memory_total_mib": total,
                "memory_used_mib": used,
                "memory_free_mib": free,
                "utilization_gpu_percent": utilization,
            }
        )
    max_free = max((item["memory_free_mib"] for item in devices), default=None)
    return {
        "observed": completed.returncode == 0 and bool(devices),
        "shared_gpu_policy": "existing_gpu_occupancy_is_allowed;_free_vram_is_the_only_capacity_gate",
        "required_peak_mib": GPU_PEAK_MIB,
        "devices": devices,
        "device_count": len(devices),
        "max_free_mib": max_free,
        "capacity_pass": max_free is not None and max_free >= GPU_PEAK_MIB,
        "command_returncode": completed.returncode,
        "stderr_present": bool(completed.stderr.strip()),
    }


def _ram_snapshot() -> dict[str, Any]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines()[:128]:
            fields = line.split()
            if len(fields) >= 2 and fields[0].rstrip(":") in {"MemTotal", "MemAvailable"}:
                parsed = _safe_int(fields[1])
                if parsed is not None:
                    values[fields[0].rstrip(":")] = parsed * 1024
    except OSError:
        values = {}
    available = values.get("MemAvailable")
    total = values.get("MemTotal")
    return {
        "observed": available is not None and total is not None,
        "total_bytes": total,
        "available_bytes": available,
        "required_available_bytes": RAM_REQUIRED_MIB * 1024**2,
        "capacity_pass": available is not None and available >= RAM_REQUIRED_MIB * 1024**2,
    }


def _disk_snapshot(root: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(root)
    except OSError as error:
        return {
            "observed": False,
            "free_bytes": None,
            "total_bytes": None,
            "required_free_bytes": DISK_REQUIRED_BYTES,
            "capacity_pass": False,
            "error": type(error).__name__,
        }
    return {
        "observed": True,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "required_free_bytes": DISK_REQUIRED_BYTES,
        "capacity_pass": usage.free >= DISK_REQUIRED_BYTES,
    }


def _resource_snapshot(root: Path) -> dict[str, Any]:
    gpu = _gpu_snapshot()
    ram = _ram_snapshot()
    disk = _disk_snapshot(root)
    return {
        "observed_at_utc": _utc_now(),
        "gpu": gpu,
        "ram": ram,
        "disk": disk,
        "capacity_observed": bool(
            gpu.get("observed") and ram.get("observed") and disk.get("observed")
        ),
        "capacity_pass": bool(
            gpu.get("capacity_pass")
            and ram.get("capacity_pass")
            and disk.get("capacity_pass")
        ),
    }


def _diagnostic_observation(diagnostic: Mapping[str, Any], reference: Mapping[str, Any], error: str | None) -> dict[str, Any]:
    source = diagnostic.get("source") if isinstance(diagnostic.get("source"), Mapping) else {}
    identity = source.get("case_identity") if isinstance(source.get("case_identity"), Mapping) else {}
    params = diagnostic.get("parameters") if isinstance(diagnostic.get("parameters"), Mapping) else {}
    trace = diagnostic.get("trace") if isinstance(diagnostic.get("trace"), Mapping) else {}
    decision = diagnostic.get("decision") if isinstance(diagnostic.get("decision"), Mapping) else {}
    trace_output = trace.get("output") if isinstance(trace.get("output"), Mapping) else {}
    checks = {
        "report_readable": error is None,
        "schema": diagnostic.get("schema") == "core.f4.tallwall120.material_diagnostic_receipt.v1",
        "case_identity": (
            identity.get("case_id") == CASE_ID
            and identity.get("frames") == 218
            and identity.get("transitions") == 217
        ),
        "source_identity": (
            source.get("repo_relative_path") == SOURCE_HDF5
            and source.get("before_after_match") is True
            and (source.get("after") or {}).get("sha256") == SOURCE_SHA256
            and (source.get("after") or {}).get("size_bytes") == SOURCE_BYTES
        ),
        "parameter_binding": (
            params.get("q") == EXPECTED_Q
            and params.get("dp_m") == EXPECTED_DP_M
            and params.get("seeds") == EXPECTED_SEEDS
            and params.get("substeps") == EXPECTED_SUBSTEPS
            and params.get("neighbour_variant") == EXPECTED_NEIGHBOUR_VARIANT
        ),
        "trace_short_window_complete": (
            trace.get("status") == "completed"
            and trace.get("committed_frame") == 217
            and trace.get("frame_count") == 218
            and trace.get("transition_count") == 217
        ),
        "event_window_complete": trace.get("event_window_complete") is True,
        "unknown_gate": trace.get("unknown_gate_pass") is True
        and isinstance(trace.get("unknown_fraction_max"), (int, float))
        and float(trace.get("unknown_fraction_max")) <= UNKNOWN_FRACTION_MAX,
        "reliable_coverage": isinstance(trace.get("common_reliable_path_coverage"), (int, float))
        and float(trace.get("common_reliable_path_coverage")) >= RELIABLE_COVERAGE_MIN,
        "diagnostic_only": diagnostic.get("diagnostic_only") is True,
        "formal_admission_closed": (decision.get("formal_admission")) is False
        and decision.get("T1") is False
        and decision.get("T2") is False
        and decision.get("credit") == 0,
    }
    return {
        "reference": dict(reference),
        "status": diagnostic.get("status", "missing"),
        "schema": diagnostic.get("schema"),
        "source": {
            "repo_relative_path": source.get("repo_relative_path"),
            "sha256": (source.get("after") or {}).get("sha256"),
            "bytes": (source.get("after") or {}).get("size_bytes"),
        },
        "parameters": {
            key: params.get(key)
            for key in ("q", "dp_m", "seeds", "substeps", "neighbour_variant")
        },
        "trace": {
            "output_path": trace_output.get("path"),
            "status": trace.get("status"),
            "committed_frame": trace.get("committed_frame"),
            "frame_count": trace.get("frame_count"),
            "transition_count": trace.get("transition_count"),
            "event_window_complete": trace.get("event_window_complete"),
            "event_window_status": trace.get("event_window_status"),
            "unknown_fraction_max": trace.get("unknown_fraction_max"),
            "common_reliable_path_coverage": trace.get("common_reliable_path_coverage"),
        },
        "checks": checks,
        "error": error,
    }


def _root_observation(
    intake: Mapping[str, Any],
    reference: Mapping[str, Any],
    validation_errors: Sequence[str],
) -> dict[str, Any]:
    validation = intake.get("validation") if isinstance(intake.get("validation"), Mapping) else {}
    checks = validation.get("checks") if isinstance(validation.get("checks"), Mapping) else {}
    source = intake.get("binding_projection", {}).get("source_identity", {}) if isinstance(intake.get("binding_projection"), Mapping) else {}
    collection = source.get("collection") if isinstance(source, Mapping) and isinstance(source.get("collection"), Mapping) else {}
    reader = source.get("reader") if isinstance(source, Mapping) and isinstance(source.get("reader"), Mapping) else {}
    namespace = intake.get("binding_projection", {}).get("fresh_output_namespace", {}) if isinstance(intake.get("binding_projection"), Mapping) else {}
    authorization = intake.get("authorization") if isinstance(intake.get("authorization"), Mapping) else {}
    return {
        "reference": dict(reference),
        "status": intake.get("status"),
        "intake_contract_valid": checks.get("intake_contract_valid") is True,
        "validation_errors": list(validation_errors),
        "blockers": list(validation.get("blockers", [])) if isinstance(validation.get("blockers"), list) else [],
        "checks": {
            "source_identity_contract_valid": checks.get("source_identity_contract_valid") is True,
            "collection_path_exact": collection.get("path_exact") is True,
            "reader_manifest_sha_exact": reader.get("manifest_sha_exact") is True,
            "fresh_namespace_valid": checks.get("fresh_output_namespace_valid") is True,
            "fresh_root_receipt_valid": checks.get("future_root_receipt_valid") is True,
            "scheduler_receipt_valid": checks.get("future_scheduler_receipt_valid") is True,
            "scheduler_owned_host_io_valid": checks.get("scheduler_owned_host_io_reservation_valid") is True,
        },
        "source_identity": {
            "collection_path": collection.get("declared_hdf5"),
            "expected_path": SOURCE_HDF5,
            "path_exact": collection.get("path_exact"),
            "reader_manifest_sha_exact": reader.get("manifest_sha_exact"),
        },
        "fresh_namespace": {
            "namespace": namespace.get("namespace", root_intake.DEFAULT_OUTPUT_NAMESPACE),
            "path_exists": namespace.get("namespace_path_exists"),
            "must_be_absent": namespace.get("must_be_absent_before_admission") is True,
        },
        "authorization": {
            "launch_admitted": authorization.get("launch_admitted") is True,
            "worker_launch_authorized": authorization.get("worker_launch_authorized") is True,
            "root_authorization_present": authorization.get("root_authorization_present") is True,
            "scheduler_authorization_present": authorization.get("scheduler_authorization_present") is True,
        },
    }


def build_report(root: str | Path = LAB_ROOT, *, resource_snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a fail-closed single-case candidate receipt without launching work."""

    root = Path(root).resolve()
    intake = root_intake.build_report(root)
    intake_errors = root_intake.validate_report(intake)
    intake_ref = _read_json(root, ROOT_INTAKE_REPORT, role="existing_root_scheduler_intake_report")
    diagnostic, diagnostic_ref, diagnostic_error = _read_json(
        root, DIAGNOSTIC_REPORT, role="existing_DEV_07_material_diagnostic"
    )
    resources = dict(resource_snapshot) if resource_snapshot is not None else _resource_snapshot(root)
    diagnostic_observation = _diagnostic_observation(diagnostic, diagnostic_ref, diagnostic_error)
    root_observation = _root_observation(intake, intake_ref[1], intake_errors)

    namespace_path = root / PLANNED_NAMESPACE
    namespace_absent = not namespace_path.exists()
    resource_checks = {
        "gpu_vram_headroom": resources.get("gpu", {}).get("capacity_pass") is True,
        "ram_headroom": resources.get("ram", {}).get("capacity_pass") is True,
        "disk_headroom": resources.get("disk", {}).get("capacity_pass") is True,
        "resource_snapshot_complete": resources.get("capacity_observed") is True,
    }
    checks = {
        "root_scheduler_intake_closed": (
            root_observation["intake_contract_valid"] is False
            and root_observation["authorization"]["launch_admitted"] is False
            and root_observation["authorization"]["worker_launch_authorized"] is False
        ),
        "fresh_namespace_absent": namespace_absent,
        "collection_source_path_exact": root_observation["checks"]["collection_path_exact"],
        "reader_manifest_sha_exact": root_observation["checks"]["reader_manifest_sha_exact"],
        "diagnostic_source_identity": diagnostic_observation["checks"]["source_identity"],
        "diagnostic_parameter_binding": diagnostic_observation["checks"]["parameter_binding"],
        "diagnostic_full_event_window": diagnostic_observation["checks"]["event_window_complete"],
        "diagnostic_unknown_gate": diagnostic_observation["checks"]["unknown_gate"],
        "diagnostic_reliable_coverage": diagnostic_observation["checks"]["reliable_coverage"],
        **resource_checks,
    }
    blockers: list[str] = []
    if not checks["collection_source_path_exact"]:
        blockers.append("collection_source_path_drift")
    if not checks["reader_manifest_sha_exact"]:
        blockers.append("reader_manifest_sha_drift")
    if not root_observation["checks"]["fresh_root_receipt_valid"]:
        blockers.append("missing_or_invalid_fresh_root_receipt")
    if not root_observation["checks"]["scheduler_receipt_valid"]:
        blockers.append("missing_or_invalid_scheduler_host_io_receipt")
    if not root_observation["checks"]["scheduler_owned_host_io_valid"]:
        blockers.append("scheduler_owned_host_io_not_verified")
    if not checks["diagnostic_parameter_binding"]:
        blockers.append("existing_diagnostic_parameter_drift")
    if not checks["diagnostic_full_event_window"]:
        blockers.append("diagnostic_event_window_incomplete_or_right_censored")
    if not checks["diagnostic_unknown_gate"]:
        blockers.append("diagnostic_unknown_gate_failed")
    if not checks["diagnostic_reliable_coverage"]:
        blockers.append("diagnostic_reliable_coverage_failed")
    for name, reason in (
        ("resource_snapshot_complete", "resource_snapshot_incomplete"),
        ("gpu_vram_headroom", "gpu_vram_headroom_insufficient"),
        ("ram_headroom", "ram_headroom_insufficient"),
        ("disk_headroom", "disk_headroom_insufficient"),
    ):
        if not checks[name]:
            blockers.append(reason)
    if not checks["fresh_namespace_absent"]:
        blockers.append("fresh_output_namespace_already_exists")
    blockers.extend(f"root_intake:{item}" for item in root_observation["validation_errors"])
    blockers.extend(root_observation["blockers"])
    blockers = list(dict.fromkeys(str(item) for item in blockers if item))

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "observed_at_utc": _utc_now(),
        "status": "blocked_fail_closed",
        "decision": "diagnostic_only_bounded_candidate_runner_receipt_bridge",
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "split": "train",
        },
        "source": {
            "hdf5": SOURCE_HDF5,
            "sha256": SOURCE_SHA256,
            "bytes": SOURCE_BYTES,
            "trajectory_access": "lstat_only_via_root_scheduler_intake",
        },
        "planned_sidecar": {
            "schema": PLANNED_SIDECAR_SCHEMA,
            "namespace": root_intake.DEFAULT_OUTPUT_NAMESPACE,
            "path": PLANNED_SIDECAR.as_posix(),
            "produced": False,
            "reason": "candidate runner is blocked before authorized material execution",
        },
        "checks": checks,
        "blockers": blockers,
        "observations": {
            "root_scheduler_intake": root_observation,
            "existing_material_diagnostic": diagnostic_observation,
            "resources": resources,
        },
        "authorization": {
            "diagnostic_only": True,
            "proposal_only": True,
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1": False,
            "T2": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": 0,
            "T2_credit": 0,
            "credit": 0,
            "launch_admitted": False,
            "worker_launch_authorized": False,
        },
        "execution_controls": {
            "runner_invoked_material_trace": False,
            "runner_invoked_diagnosis": False,
            "source_hdf5_opened": False,
            "source_hdf5_read": False,
            "source_hdf5_hash_recomputed": False,
            "sidecar_written": False,
            "fresh_namespace_created": False,
            "solver_started": False,
            "worker_started": False,
            "native_started": False,
            "gpu_initialized": False,
            "queue_or_scheduler_started": False,
            "registry_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "gate_mutations": 0,
            "completion_mutations": 0,
            "plan_mutations": 0,
        },
        "validation": {
            "contract_valid": True,
            "blocked": True,
            "blockers_nonempty": bool(blockers),
            "root_scheduler_validate_errors": intake_errors,
        },
        "next_safe_action": (
            "修正 collection/reader source identity drift，取得绑定当前 hashes、normalized argv/cwd、"
            "fresh namespace nonce 的 root receipt 与 scheduler-owned host-I/O receipt；随后重新运行本 bridge。"
            "在 trusted execution authorization 与完整 8.68 s 输入仍未闭合前，不得启动 material trace 或写 material sidecar。"
        ),
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema", "record_id", "created_at", "observed_at_utc", "status", "decision", "scope",
        "source", "planned_sidecar", "checks", "blockers", "observations", "authorization",
        "execution_controls", "validation", "next_safe_action",
    }
    if not isinstance(report, Mapping) or set(report) != required:
        return ["report.fields"]
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if report.get("created_at") != CREATED_AT:
        errors.append("created_at")
    if report.get("status") != "blocked_fail_closed":
        errors.append("status")
    if report.get("decision") != "diagnostic_only_bounded_candidate_runner_receipt_bridge":
        errors.append("decision")
    scope = report.get("scope")
    if scope != {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "split": "train"}:
        errors.append("scope")
    source = report.get("source")
    if not isinstance(source, Mapping) or source.get("hdf5") != SOURCE_HDF5 or source.get("sha256") != SOURCE_SHA256 or source.get("bytes") != SOURCE_BYTES:
        errors.append("source")
    claims = report.get("authorization")
    expected_claims = {
        "diagnostic_only": True, "proposal_only": True, "formal": False,
        "formal_eligible": False, "qualification": False, "T1": False,
        "T2": False, "T2_macro": False, "T2_path": False,
        "qualification_credit": 0, "T2_credit": 0, "credit": 0,
        "launch_admitted": False, "worker_launch_authorized": False,
    }
    if claims != expected_claims:
        errors.append("authorization.fail_closed")
    execution = report.get("execution_controls")
    if not isinstance(execution, Mapping):
        errors.append("execution_controls.fields")
    else:
        for key, expected in {
            "runner_invoked_material_trace": False, "runner_invoked_diagnosis": False,
            "source_hdf5_opened": False, "source_hdf5_read": False,
            "source_hdf5_hash_recomputed": False, "sidecar_written": False,
            "fresh_namespace_created": False, "solver_started": False,
            "worker_started": False, "native_started": False, "gpu_initialized": False,
            "queue_or_scheduler_started": False, "registry_mutations": 0,
            "ledger_mutations": 0, "denominator_mutations": 0, "gate_mutations": 0,
            "completion_mutations": 0, "plan_mutations": 0,
        }.items():
            if execution.get(key) != expected:
                errors.append(f"execution_controls.{key}")
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or not all(isinstance(value, bool) for value in checks.values()):
        errors.append("checks")
    if not isinstance(report.get("blockers"), list) or not report.get("blockers"):
        errors.append("blockers")
    planned = report.get("planned_sidecar")
    if not isinstance(planned, Mapping) or planned.get("produced") is not False or planned.get("schema") != PLANNED_SIDECAR_SCHEMA:
        errors.append("planned_sidecar")
    validation = report.get("validation")
    if not isinstance(validation, Mapping) or validation.get("blocked") is not True or validation.get("blockers_nonempty") is not True:
        errors.append("validation")
    if not isinstance(report.get("next_safe_action"), str) or not report.get("next_safe_action"):
        errors.append("next_safe_action")
    return errors


def write_report(report: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(report)
    if errors:
        raise ValueError("refusing to write invalid candidate runner receipt: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = build_report(args.root)
    write_report(report, args.output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
