#!/usr/bin/env python3
"""Forward source-closure ledger for the completed all-118 mechanism probe.

The v2 probe is immutable and already contains the native CSV/RunPARTs
comparisons for 117 cases.  F2-S1 was deliberately retained there as a
partial native reconciliation.  This forward consumer binds the completed
F2-S1 native-source-closure sidecar to that exact v2 report and writes an
additive v3 report.  It does not re-run PartVTKOut, open H5/BI4, or alter v2
CSV/report/receipt bytes.

The mass gate (0.003 of frozen initial whole-fluid mass) remains a screening
threshold.  A first-missing saved-record bracket cannot identify a physical
event, destination, repeated crossing, signed net flux, or a bounded
dynamical error.  Synthetic event patterns are emitted as explicit negative
controls so that those claims cannot be inferred from a single endpoint.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
PRIMARY_LAB_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
V2_REPORT_DEFAULT = DATA_ROOT / (
    "families/infra/STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V2/"
    "omission-mechanism-probe-v2-primary-001-v8-root/omission-mechanism-probe-v2.json"
)
V2_RECEIPT_DEFAULT = V2_REPORT_DEFAULT.parent / "execution-receipt.json"
V2_MANIFEST_DEFAULT = PRIMARY_LAB_ROOT / (
    "campaigns/ds-data-02/stage2/requests/omission-mechanism-probe-v2/"
    "omission-mechanism-probe-v2-manifest.json"
)
V2_REQUEST_DEFAULT = PRIMARY_LAB_ROOT / (
    "campaigns/ds-data-02/stage2/requests/omission-mechanism-probe-v2/"
    "omission-mechanism-probe-v2-request.json"
)
CLOSURE_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/evidence/"
    "f2-s1-native-source-closure-v1/f2-s1-native-source-closure.json"
)
OUTPUT_SCHEMA = "ds02.stage2.omission-mechanism-probe.v3"
MANIFEST_SCHEMA = "ds02.stage2.omission-mechanism-probe-manifest.v3"
V2_SCHEMA = "ds02.stage2.omission-mechanism-probe.v2"
V2_STATUS = "MECHANISM_PROBE_SOURCE_CLOSED_NO_H5"
CLOSURE_SCHEMA = "ds02.stage2.f2-s1-native-source-closure.v1"
CLOSURE_STATUS = "EXACT_NATIVE_SOURCE_CLOSED_WITH_PHYSICAL_FATE_UNKNOWN"
FAMILY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
F2_S1_KEY = "F2/scan-F2-S1-001"
MASS_GATE = 0.003
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".obi4", ".bi4"}


class MechanismProbeV3Error(RuntimeError):
    """Raised when an immutable v2 or F2 closure binding is not exact."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def forbidden(path: Path) -> bool:
    return path.suffix.lower() in FORBIDDEN_SUFFIXES or (
        path.name.startswith("Part_") and path.suffix.lower() == ".bi4"
    )


def require_file(value: Path | str, label: str, *, allow_raw_metadata: bool = False) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise MechanismProbeV3Error(f"{label} is missing: {path}")
    if forbidden(path) and not allow_raw_metadata:
        raise MechanismProbeV3Error(f"H5/BI4/raw input is forbidden: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MechanismProbeV3Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise MechanismProbeV3Error(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise MechanismProbeV3Error(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def binding(path: Path | str, label: str, expected: str | None = None) -> dict[str, Any]:
    path = require_file(path, label)
    digest = sha256(path)
    if expected is not None and digest != expected:
        raise MechanismProbeV3Error(f"{label} digest differs: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def validate_v2(report_path: Path, receipt_path: Path, manifest_path: Path,
                request_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    report_path, report = read_json(report_path, "completed v2 mechanism report")
    receipt_path, receipt = read_json(receipt_path, "completed v2 mechanism receipt")
    manifest_path, manifest = read_json(manifest_path, "v2 mechanism manifest")
    request_path, request = read_json(request_path, "v2 mechanism request")
    if report.get("schema") != V2_SCHEMA or report.get("status") != V2_STATUS:
        raise MechanismProbeV3Error("v2 report schema/status differs")
    if manifest.get("schema") != "ds02.stage2.omission-mechanism-probe-manifest.v2":
        raise MechanismProbeV3Error("v2 manifest schema differs")
    if request.get("schema") != "ds02.request.v1" or request.get("case_id") != "STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V2":
        raise MechanismProbeV3Error("v2 request identity differs")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise MechanismProbeV3Error("v2 receipt is not completed code 0")
    receipt_request = receipt.get("request", {})
    if receipt_request.get("case_id") != request.get("case_id") or receipt_request.get("attempt_id") != request.get("attempt_id"):
        raise MechanismProbeV3Error("v2 receipt request identity differs")
    if len(report.get("cases", [])) != 118 or report.get("coverage", {}).get("selected_case_counts") != FAMILY_COUNTS:
        raise MechanismProbeV3Error("v2 report coverage differs")
    if report.get("coverage", {}).get("selected_native_id_count") != 1328:
        raise MechanismProbeV3Error("v2 native ID count differs")
    policy = report.get("read_policy", {})
    for name in ("h5_opened", "trajectory_content_opened", "raw_partout_opened", "decoder_started", "solver_started", "cfd_or_model_run"):
        if policy.get(name) is not False:
            raise MechanismProbeV3Error(f"v2 read policy is not closed: {name}")
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    if not launch or launch != finish:
        raise MechanismProbeV3Error("v2 input hashes are not stable")
    for path_text in launch:
        path = require_file(path_text, "v2 receipt input")
        if forbidden(path):
            raise MechanismProbeV3Error(f"v2 receipt unexpectedly includes H5/BI4: {path}")
    expected_report = report.get("source_report", {})
    source_path = require_file(expected_report.get("path", ""), "v2 source report")
    if sha256(source_path) != expected_report.get("sha256"):
        raise MechanismProbeV3Error("v2 source report digest differs")
    return report, receipt, {"path": str(report_path), "sha256": sha256(report_path), "bytes": report_path.stat().st_size,
                             "receipt_path": str(receipt_path), "receipt_sha256": sha256(receipt_path), "receipt_bytes": receipt_path.stat().st_size,
                             "manifest_path": str(manifest_path), "manifest_sha256": sha256(manifest_path), "manifest_bytes": manifest_path.stat().st_size,
                             "request_path": str(request_path), "request_sha256": sha256(request_path), "request_bytes": request_path.stat().st_size}


def validate_closure(path: Path) -> dict[str, Any]:
    path, closure = read_json(path, "F2-S1 exact source closure")
    if closure.get("schema") != CLOSURE_SCHEMA or closure.get("status") != CLOSURE_STATUS:
        raise MechanismProbeV3Error("F2-S1 closure schema/status differs")
    if closure.get("case_key") != F2_S1_KEY or closure.get("family_id") != "F2":
        raise MechanismProbeV3Error("F2-S1 closure identity differs")
    current = closure.get("current", {})
    if current.get("sha256") != "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b":
        raise MechanismProbeV3Error("F2-S1 closure CURRENT digest differs")
    native = closure.get("native_result", {})
    if native.get("status") != "EXACT_SEMANTIC_MATCH" or native.get("joined_count") != 3:
        raise MechanismProbeV3Error("F2-S1 exact native result differs")
    if native.get("idp") != [403829, 397194, 404024] or native.get("motive_counts") != {"density": 0, "movement": 0, "position": 3}:
        raise MechanismProbeV3Error("F2-S1 native IDs/motives differ")
    source_bindings = closure.get("source_bindings", {})
    required = {"config_closure_manifest", "config_closure_report", "config_closure_receipt", "old_partvtkout_csv", "fresh_partvtkout_csv", "runout", "runparts"}
    # runout/runparts are named runout/runparts in the closure sidecar; all
    # other required fields are explicitly checked by the exact sidecar.
    missing = [name for name in required if name not in source_bindings]
    if missing:
        raise MechanismProbeV3Error(f"F2-S1 closure lacks bindings: {missing}")
    if source_bindings["old_partvtkout_csv"].get("sha256") != source_bindings["fresh_partvtkout_csv"].get("sha256"):
        raise MechanismProbeV3Error("F2-S1 old/fresh CSV digests differ")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "payload": closure}


def semantic_counterexamples() -> dict[str, Any]:
    """Return conservative synthetic controls for censoring claims."""
    repeated = {"idp": 17, "saved_states": ["inside", "outside", "inside", "outside"], "inferred_net_flux": "UNKNOWN"}
    cancellation = {"signed_crossings": [{"idp": 21, "sign": 1}, {"idp": 22, "sign": -1}], "inferred_net_flux": "UNKNOWN"}
    unknown_width = {"observed_lower_bound_fraction": 0.001, "unobserved_reentry_or_region_mass": "UNKNOWN", "inferred_upper_bound": "UNKNOWN"}
    material_region = {"native_zone_type": {"zone": 0, "type": 3}, "destination_material_region": "UNKNOWN", "legal_flux": "UNKNOWN_NOT_PROVEN"}
    return {
        "frozen_whole_initial_mass_gate_fraction": MASS_GATE,
        "gate_role": "screen_only; never a dynamics/QN/QE credit",
        "event_time_semantics": "first_missing and native PartOut values are saved-record observations/brackets; exact physical event time UNKNOWN",
        "repeated_crossing_control": repeated,
        "signed_net_flux_cancellation_control": cancellation,
        "unknown_width_control": unknown_width,
        "material_region_control": material_region,
        "all_controls_preserve_unknown": True,
        "claim_boundary": {
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
    }


def merged_cases(report: dict[str, Any], closure: dict[str, Any]) -> list[dict[str, Any]]:
    cases = copy.deepcopy(report["cases"])
    by_key = {str(case.get("case_key")): case for case in cases}
    if set(by_key) != {str(case.get("case_key")) for case in report["cases"]} or len(by_key) != 118:
        raise MechanismProbeV3Error("v2 case keys are not unique")
    f2 = by_key[F2_S1_KEY]
    if f2.get("source_closure", {}).get("status") != "PARTIAL_NATIVE_RECONCILIATION_ONLY":
        raise MechanismProbeV3Error("v2 F2-S1 is not the expected partial record")
    payload = closure["payload"]
    source_bindings = copy.deepcopy(payload.get("source_bindings", {}))
    if "raw_partout" in source_bindings:
        source_bindings["raw_partout"] = {**source_bindings["raw_partout"], "content_opened": False, "registered_as_input": False}
    f2["source_closure"] = {
        "status": "EXACT_NATIVE_SOURCE_CLOSED",
        "upgrade_basis": "completed config-closure case 030 and additive exact F2-S1 closure sidecar",
        "missing_inputs": [],
        "native_decoder": "official PartVTKOut exact semantic match to preserved three-row CSV",
        "converter_implementation": "UNKNOWN_NOT_BOUND_BY_CONVERTER_SOURCE_EXECUTION",
        "source_bindings": source_bindings,
        "physical_fate": "UNKNOWN",
    }
    f2["native_gate"]["credit"] = "exact official PartVTKOut/RunPARTs source closure; native numerical motive only; physical destination and legal flux UNKNOWN"
    f2["native_decoder_closure"] = {
        "status": "EXACT_SEMANTIC_MATCH",
        "joined_count": 3,
        "idp": [403829, 397194, 404024],
        "motive_counts": {"density": 0, "movement": 0, "position": 3},
        "csv_sha256": source_bindings["fresh_partvtkout_csv"].get("sha256"),
        "old_csv_bytes_preserved": True,
        "endpoint_reanalysis": "NOT_PERFORMED_BY_V3; v2 UNKNOWN endpoint fields remain UNKNOWN",
    }
    f2["source_closure_claim_boundary"] = "Source/decoder/CSV/RunPARTs identity is closed; this does not identify fate, repeated crossing, net flux, or dynamics"
    for case in cases:
        case.setdefault("source_closure", {
            "status": "V2_NATIVE_SOURCE_CLOSED",
            "upgrade_basis": "inherited unchanged from completed all-118 v2 report and receipt",
            "physical_fate": "UNKNOWN",
        })
    return cases


def audit(v2_report_path: Path, v2_receipt_path: Path, v2_manifest_path: Path,
          v2_request_path: Path, closure_path: Path, output_path: Path) -> dict[str, Any]:
    report, receipt, base = validate_v2(v2_report_path, v2_receipt_path, v2_manifest_path, v2_request_path)
    closure = validate_closure(closure_path)
    cases = merged_cases(report, closure)
    source_counts = {"EXACT_NATIVE_SOURCE_CLOSED": 1, "V2_NATIVE_SOURCE_CLOSED": 117}
    output = {
        "schema": OUTPUT_SCHEMA,
        "status": "MECHANISM_PROBE_SOURCE_CLOSED_F2_S1_UPGRADED_NO_H5",
        "base_v2": {
            "report": {"path": base["path"], "sha256": base["sha256"], "bytes": base["bytes"]},
            "execution_receipt": {"path": base["receipt_path"], "sha256": base["receipt_sha256"], "bytes": base["receipt_bytes"]},
            "manifest": {"path": base["manifest_path"], "sha256": base["manifest_sha256"], "bytes": base["manifest_bytes"]},
            "request": {"path": base["request_path"], "sha256": base["request_sha256"], "bytes": base["request_bytes"]},
            "report_bytes_and_cases_preserved": True,
        },
        "f2_s1_source_closure": closure["payload"],
        "coverage": {
            "selected_case_counts": dict(FAMILY_COUNTS),
            "selected_case_count": 118,
            "selected_native_id_count": 1328,
            "native_motive_case_counts": report["coverage"]["native_motive_case_counts"],
            "source_closure_case_counts": source_counts,
            "f2_s1_partial_upgraded": True,
        },
        "cases": cases,
        "censoring_semantics": semantic_counterexamples(),
        "claim_boundary": {
            "native_motive": "source-bound native motive/ID/CSV/RunPARTs only",
            "source_closure": "all 118 inherit v2 source closure; F2-S1 additionally has exact native-source/decoder closure",
            "mass": "source-visible lower bound only, normalized by frozen whole-initial mass where present",
            "material_region": "native MK/type labels do not identify destination material/region",
            "event_time": "saved-record bracket only",
            "repeated_crossing": "UNKNOWN",
            "signed_net_flux": "UNKNOWN",
            "unknown_width": "UNKNOWN upper width; no bounded dynamics claim",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "read_policy": {
            "h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False,
            "decoder_started": False, "solver_started": False, "cfd_or_model_run": False,
        },
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
    }
    atomic_json(output_path, output)
    return {"status": output["status"], "output": str(output_path.resolve()), "selected_case_count": 118,
            "selected_native_id_count": 1328, "f2_s1_upgraded": True, "h5_opened": False}


def prepare(output_dir: Path, *, v2_report_path: Path = V2_REPORT_DEFAULT,
            v2_receipt_path: Path = V2_RECEIPT_DEFAULT, v2_manifest_path: Path = V2_MANIFEST_DEFAULT,
            v2_request_path: Path = V2_REQUEST_DEFAULT, closure_path: Path = CLOSURE_DEFAULT,
            variant: str = "v3") -> dict[str, Any]:
    if not variant.startswith("v") or not variant[1:].isdigit():
        raise MechanismProbeV3Error(f"invalid variant: {variant}")
    report, receipt, base = validate_v2(v2_report_path, v2_receipt_path, v2_manifest_path, v2_request_path)
    closure = validate_closure(closure_path)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"omission-mechanism-probe-{variant}"
    manifest_path = output_dir / f"{name}-manifest.json"
    request_path = output_dir / f"{name}-request.json"
    if manifest_path.exists() or request_path.exists():
        raise MechanismProbeV3Error("refusing to overwrite existing v3 request files")

    # Carry forward the immutable v2 receipt input set.  The new v3 request
    # adds only the F2 closure sidecar and its small source bindings; the
    # receipt's source hashes are rechecked by the shared runtime after lease.
    old_inputs = receipt.get("input_hashes_after_run", {})
    inputs: dict[str, dict[str, Any]] = {}
    for path_text, expected in old_inputs.items():
        path = require_file(path_text, "v2 receipt source")
        if forbidden(path):
            raise MechanismProbeV3Error(f"v2 receipt source is forbidden: {path}")
        inputs[str(path)] = {"path": str(path), "sha256": str(expected), "bytes": path.stat().st_size, "digest_source": "completed_v2_receipt"}

    def add(path: Path | str, label: str, expected: str | None = None) -> None:
        item = binding(path, label, expected)
        previous = inputs.get(item["path"])
        if previous is not None and (previous["sha256"], previous["bytes"]) != (item["sha256"], item["bytes"]):
            raise MechanismProbeV3Error(f"conflicting source binding: {item['path']}")
        inputs[item["path"]] = {**item, "digest_source": "v3_prepare"}

    add(SCRIPT, "mechanism probe v3 script")
    add(v2_report_path, "completed v2 report")
    add(v2_receipt_path, "completed v2 execution receipt")
    add(v2_manifest_path, "v2 source manifest")
    add(v2_request_path, "v2 source request")
    add(closure_path, "F2-S1 exact source closure")
    closure_bindings = closure["payload"].get("source_bindings", {})
    omitted_raw: dict[str, Any] = {}
    for name_key, item in sorted(closure_bindings.items()):
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        if forbidden(path):
            omitted_raw[name_key] = {**item, "registered_as_input": False, "content_opened": False}
            continue
        add(path, f"F2-S1 closure {name_key}", str(item.get("sha256")) if item.get("digest_source") != "completed_guard_receipt" else None)

    # Bind the current v8/v6/v2 guard stack used by the parent scheduler.
    runtime = {
        "runtime_v8": PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v8.py",
        "runtime_v6_root": PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v6.py",
        "runtime_v2_base": PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v2.py",
        "dispatch_v8": PRIMARY_LAB_ROOT / "scripts/ds_data02_stage2_dispatch_v8.py",
        "strict_v8": PRIMARY_LAB_ROOT / "scripts/ds_data02_strict_dispatch_v8.py",
    }
    for label, path in runtime.items():
        add(path, label)
    add(VENV, "bound-python-interpreter")
    input_files = sorted(inputs)
    input_bytes = sum(item["bytes"] for item in inputs.values())
    selected = sorted(str(case["case_key"]) for case in report["cases"])
    launch_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ALL118_NATIVE_SOURCE_CLOSURE_V3_NO_H5",
        "selected_case_counts": dict(FAMILY_COUNTS),
        "selected_case_keys": selected,
        "selected_native_id_count": 1328,
        "v2_base_report": {"path": base["path"], "sha256": base["sha256"], "bytes": base["bytes"]},
        "v2_base_receipt": {"path": base["receipt_path"], "sha256": base["receipt_sha256"], "bytes": base["receipt_bytes"]},
        "f2_s1_closure": {"path": closure["path"], "sha256": closure["sha256"], "bytes": closure["bytes"]},
        "input_files": input_files,
        "input_sha256": {path: inputs[path]["sha256"] for path in input_files},
        "input_bytes": {path: inputs[path]["bytes"] for path in input_files},
        "omitted_raw_metadata": omitted_raw,
        "source_scope": {
            "v2_report_reused": True, "v2_csv_runparts_reused": True, "f2_s1_exact_decoder_closure_merged": True,
            "h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False,
            "decoder_started": False, "solver_started": False, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        },
        "censoring_semantics": semantic_counterexamples(),
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": "Additive v2 source closure with exact F2-S1 native decoder merge; no physical fate, net flux, repeated crossing, region destination, bounded dynamics, QN or QE credit",
    }
    atomic_json(manifest_path, manifest)
    inputs_with_manifest = dict(inputs)
    inputs_with_manifest[str(manifest_path)] = {"path": str(manifest_path), "sha256": sha256(manifest_path), "bytes": manifest_path.stat().st_size}
    input_files_request = sorted(inputs_with_manifest)
    request = {
        "schema": "ds02.request.v1", "family_id": "infra", "case_id": "STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V3",
        "physical_case_id": "F2_F4_F6_ALL118_NATIVE_SOURCE_CLOSURE_V3", "attempt_id": f"{name}-primary-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900,
        "estimated_storage_bytes": 64 * 1024 * 1024, "cwd": str(SCRIPT.parent), "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "audit", "--v2-report", str(v2_report_path), "--v2-receipt", str(v2_receipt_path), "--v2-manifest", str(v2_manifest_path), "--v2-request", str(v2_request_path), "--closure", str(closure_path), "--output", f"{{attempt_root}}/{name}.json"],
        "input_files": input_files_request, "input_sha256": {path: inputs_with_manifest[path]["sha256"] for path in input_files_request},
        "shared_runtime_version": "v8",
        "runtime_binding": {label: {"path": str(path), "sha256": sha256(path)} for label, path in runtime.items() if label.startswith("runtime_")},
        "dispatch_binding": {label: {"path": str(path), "sha256": sha256(path)} for label, path in runtime.items() if label.startswith("dispatch_")},
        "strict_dispatch_binding": {label: {"path": str(path), "sha256": sha256(path)} for label, path in runtime.items() if label.startswith("strict_")},
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "raw_partout_bytes_read": 0, "small_source_bytes_read": input_bytes, "runtime_pre_post_hash_bytes": 2 * input_bytes, "estimated_output_bytes": 64 * 1024 * 1024},
        "source_scope": {"selected_cases": dict(FAMILY_COUNTS), "native_ids": 1328, "v2_outcome_preserved": True, "f2_s1_exact_source_closure_merged": True, "h5_content_read": False, "trajectory_content_read": False, "raw_partout_content_read": False, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "censoring_semantics": semantic_counterexamples(),
        "canonical_ready": True, "launch": True, "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "primary_launch_owner": "root", "shared_lease_required": True, "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED", "launch_commit": launch_commit,
        "request_note": "Forward all-118 mechanism source-closure v3. Preserves completed v2 report/CSV/RunPARTs bytes and merges exact F2-S1 native-source closure case 030. No H5/trajectory/raw PartOut/BI4 content, decoder, solver, CFD or model. Repeated crossings, signed net flux, material/region destination, exact event times and unknown-width dynamics remain UNKNOWN; 0.003 is a screening gate only.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "selected_case_count": 118, "selected_native_id_count": 1328, "input_count": len(input_files_request), "input_bytes": input_bytes, "h5_opened": False, "launch_allowed": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--v2-report", type=Path, default=V2_REPORT_DEFAULT)
    prep.add_argument("--v2-receipt", type=Path, default=V2_RECEIPT_DEFAULT)
    prep.add_argument("--v2-manifest", type=Path, default=V2_MANIFEST_DEFAULT)
    prep.add_argument("--v2-request", type=Path, default=V2_REQUEST_DEFAULT)
    prep.add_argument("--closure", type=Path, default=CLOSURE_DEFAULT)
    prep.add_argument("--variant", default="v3")
    aud = sub.add_parser("audit")
    aud.add_argument("--v2-report", type=Path, required=True)
    aud.add_argument("--v2-receipt", type=Path, required=True)
    aud.add_argument("--v2-manifest", type=Path, required=True)
    aud.add_argument("--v2-request", type=Path, required=True)
    aud.add_argument("--closure", type=Path, required=True)
    aud.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.output_dir, v2_report_path=args.v2_report, v2_receipt_path=args.v2_receipt, v2_manifest_path=args.v2_manifest, v2_request_path=args.v2_request, closure_path=args.closure, variant=args.variant)
        else:
            result = audit(args.v2_report, args.v2_receipt, args.v2_manifest, args.v2_request, args.closure, args.output)
    except MechanismProbeV3Error as exc:
        raise SystemExit(f"MechanismProbeV3Error: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
