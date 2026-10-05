#!/usr/bin/env python3
"""Bind completed Root142 typed metadata to disabled XMF/render requests.

This adapter is intentionally metadata-only.  It reads JSON receipts/reports,
checks that the producer H5 exists, and adopts ``conversion-report.json``'s
``output_sha256`` without opening or hashing the H5.  It never invokes a
runner, converter, XMF worker, renderer, NumPy, h5py, BI4 decoder, or solver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


CASES = [
    f"F7_OBSTACLE_QUINTIC_B08_A{number:03d}P5"
    for number in (30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 54, 59, 64)
]
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
RAW_SUFFIXES = (".bi4", ".csv", ".h5", ".hdf5", ".dat", ".ibi4")
VENV_PYTHON = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")
XMF_WORKER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py"
)
RENDERER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
)


class AdapterError(ValueError):
    """A producer or request contract is incomplete or inconsistent."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdapterError(f"JSON root is not an object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path, *, allow_payload: bool = False) -> str:
    resolved = path.resolve()
    if not allow_payload and resolved.name.lower().endswith(RAW_SUFFIXES):
        raise AdapterError(f"payload hashing is forbidden in fresh076: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise AdapterError(f"{label} does not exist: {resolved}")
    return resolved


def require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise AdapterError(f"{label} must be a 64-character hexadecimal digest")
    return value.lower()


def unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def source_paths(source_package: Path) -> tuple[Path, Path, Path]:
    if not VENV_PYTHON.is_file():
        raise AdapterError(f"integration venv interpreter is missing: {VENV_PYTHON}")
    if not XMF_WORKER.is_file():
        raise AdapterError(f"XMF worker is missing: {XMF_WORKER}")
    if not RENDERER.is_file():
        raise AdapterError(f"Root023 renderer is missing: {RENDERER}")
    for path in (source_package / "manifest.json", source_package / "README.md"):
        require_file(path, "fresh076 source package file")
    return VENV_PYTHON, XMF_WORKER, RENDERER


def check_typed_receipt(path: Path, case_id: str) -> tuple[dict[str, Any], str]:
    receipt_path = require_file(path, "typed receipt")
    receipt = load_json(receipt_path)
    if (receipt.get("status"), receipt.get("returncode")) != ("completed", 0):
        raise AdapterError(f"typed receipt is not completed/0: {receipt_path}")
    request = receipt.get("request")
    if isinstance(request, dict):
        if request.get("case_id") not in (None, case_id):
            raise AdapterError(f"typed receipt case mismatch: {receipt_path}")
        if request.get("family_id") not in (None, "F7"):
            raise AdapterError(f"typed receipt family mismatch: {receipt_path}")
        if request.get("expected_frames") not in (None, 601):
            raise AdapterError(f"typed receipt frame contract mismatch: {receipt_path}")
    return receipt, sha256_file(receipt_path)


def check_native_receipt(binding: dict[str, Any], case_id: str) -> tuple[Path, str]:
    native_path = require_file(Path(str(binding["native_receipt"])), "Root313 native receipt")
    native = load_json(native_path)
    if (native.get("status"), native.get("returncode")) != ("completed", 0):
        raise AdapterError(f"Root313 native receipt is not completed/0: {native_path}")
    request = native.get("request")
    if isinstance(request, dict) and request.get("case_id") not in (None, case_id):
        raise AdapterError(f"native receipt case mismatch: {native_path}")
    actual = sha256_file(native_path)
    declared = binding.get("native_receipt_sha256")
    if declared is not None and require_hex(declared, "fresh076 native_receipt_sha256") != actual:
        raise AdapterError(f"fresh076 native receipt digest is stale: {native_path}")
    return native_path, actual


def check_conversion_report(
    path: Path,
    case_id: str,
    xmf_binding: dict[str, Any],
) -> tuple[dict[str, Any], Path, str, str, str]:
    report_path = require_file(path, "typed conversion report")
    report = load_json(report_path)
    if report.get("conversion_status") != "completed":
        raise AdapterError(f"conversion report is not completed: {report_path}")
    if report.get("schema") != "ds-data-02.bi4-direct-conversion.v1":
        raise AdapterError(f"unexpected conversion report schema: {report.get('schema')!r}")
    if report.get("frames") != 601 or report.get("particles") != 70179:
        raise AdapterError(
            f"conversion report has wrong 601/70179 contract: {report.get('frames')!r}/"
            f"{report.get('particles')!r}"
        )
    output_hdf5_raw = report.get("output_hdf5")
    if not isinstance(output_hdf5_raw, str) or not output_hdf5_raw:
        raise AdapterError("conversion report output_hdf5 is missing")
    output_hdf5 = Path(output_hdf5_raw)
    if not output_hdf5.is_absolute():
        output_hdf5 = (report_path.parent / output_hdf5).resolve()
    output_hdf5 = require_file(output_hdf5, "producer H5 output")
    output_sha256 = require_hex(report.get("output_sha256"), "conversion report output_sha256")
    if report.get("coordinate_frame") != "DualSPHysics case Cartesian coordinates (x,y,z)":
        raise AdapterError("conversion report coordinate frame is not the native Cartesian contract")
    validation = report.get("partvtk_validation")
    if not isinstance(validation, dict) or validation.get("all_passed") is not True:
        raise AdapterError("conversion report PartVTK validation is not all_passed=true")
    scopes = report.get("hash_scopes")
    if not isinstance(scopes, dict):
        raise AdapterError("conversion report hash_scopes is missing")
    physical = scopes.get("physical_condition")
    if not isinstance(physical, dict):
        raise AdapterError("conversion report physical condition scope is missing")
    if physical.get("schema") != "ds-data-02.physical-binding.v1":
        raise AdapterError(f"conversion producer scope is not canonical v1: {physical.get('schema')!r}")
    producer_physical_sha = require_hex(
        scopes.get("physical_condition_sha256"),
        "conversion report physical_condition_sha256",
    )
    canonical_sha = require_hex(
        xmf_binding["canonical_owner"]["canonical_physical_binding_sha256"],
        "canonical owner physical binding hash",
    )
    if producer_physical_sha != canonical_sha:
        raise AdapterError(
            "producer physical hash differs from canonical owner; refusing to conflate it "
            f"with source-plan hash for {case_id}: {producer_physical_sha} != {canonical_sha}"
        )
    scoped_case = physical.get("physical_case_id")
    if scoped_case not in (None, case_id):
        raise AdapterError(f"conversion producer physical case mismatch: {scoped_case!r}")
    return report, output_hdf5, output_sha256, producer_physical_sha, sha256_file(report_path)


def update_command(command: list[Any], *, binding_path: Path | None = None, manifest_path: Path | None = None) -> list[Any]:
    result = [str(VENV_PYTHON) if item == "/usr/bin/python3.10" else item for item in command]
    if binding_path is not None:
        if "--binding" not in result:
            raise AdapterError("XMF command has no --binding argument")
        result[result.index("--binding") + 1] = str(binding_path)
    if manifest_path is not None:
        if "--manifest" not in result:
            raise AdapterError("Root023 command has no --manifest argument")
        result[result.index("--manifest") + 1] = str(manifest_path)
    return result


def prepare_input_closure(
    base_files: Iterable[Any],
    *,
    old_binding_paths: Iterable[Path],
    new_binding_paths: Iterable[Path],
    typed_receipt: Path,
    conversion_report: Path,
    native_receipt: Path,
    trajectory_h5: Path,
    trajectory_sha256: str,
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    old = {str(path.resolve()) for path in old_binding_paths}
    files: list[str] = []
    for raw in base_files:
        path = str(raw)
        if path == "/usr/bin/python3.10":
            path = str(VENV_PYTHON)
        if path in old:
            continue
        files.append(path)
    files.extend(str(path.resolve()) for path in new_binding_paths)
    files.extend((str(typed_receipt), str(conversion_report), str(native_receipt), str(trajectory_h5)))
    files = unique(files)
    hashes: dict[str, str] = {}
    provenance: dict[str, str] = {}
    h5_key = str(trajectory_h5)
    for raw in files:
        path = Path(raw)
        if raw == h5_key:
            hashes[raw] = trajectory_sha256
            provenance[raw] = "producer_attested:conversion_report.output_sha256; adapter_did_not_read_h5"
            continue
        if path.name.lower().endswith(RAW_SUFFIXES):
            raise AdapterError(f"unexpected scientific payload in downstream closure: {path}")
        require_file(path, "downstream input")
        hashes[raw] = sha256_file(path)
        provenance[raw] = "adapter_hashed_metadata_or_source"
    return files, hashes, provenance


def disable_request(request: dict[str, Any], reason: str) -> dict[str, Any]:
    request["launch"] = False
    request["launch_allowed"] = False
    request["execution_allowed"] = False
    request["disabled"] = True
    request["source_only"] = True
    request["future_hashes_null"] = True
    request["status"] = "actual_typed_bound_disabled_pending_root_review"
    request["disabled_reason"] = reason
    request["independent_case_count_increment"] = 0
    return request


def bind_case(
    source_package: Path,
    case_id: str,
    typed_receipt_path: Path,
    conversion_report_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if case_id not in CASES:
        raise AdapterError(f"unknown F7 case: {case_id}")
    source_paths(source_package)
    bindings = source_package / "bindings"
    requests = source_package / "requests"
    typed_binding_path = bindings / f"{case_id}.full601-typed-binding.json"
    xmf_binding_path = bindings / f"{case_id}.full601-xmf-binding.json"
    render_binding_path = bindings / f"{case_id}.full601-render-binding.json"
    base_xmf_request_path = requests / "xmf" / f"{case_id}.full601-normal-xmf-076.disabled-request.json"
    base_render_request_path = requests / "render" / f"{case_id}.full601-native023-render-076.disabled-request.json"
    for path in (typed_binding_path, xmf_binding_path, render_binding_path, base_xmf_request_path, base_render_request_path):
        require_file(path, "fresh076 source input")
    typed_binding = load_json(typed_binding_path)
    xmf_binding = load_json(xmf_binding_path)
    render_binding = load_json(render_binding_path)
    base_xmf_request = load_json(base_xmf_request_path)
    base_render_request = load_json(base_render_request_path)
    if base_xmf_request.get("disabled") is not True or base_render_request.get("disabled") is not True:
        raise AdapterError("fresh076 source request is not disabled")
    typed_receipt, typed_receipt_sha256 = check_typed_receipt(typed_receipt_path, case_id)
    native_receipt, native_receipt_sha256 = check_native_receipt(xmf_binding, case_id)
    report, trajectory_h5, trajectory_sha256, producer_physical_sha256, report_sha256 = check_conversion_report(
        conversion_report_path, case_id, xmf_binding
    )
    source_plan_sha256 = xmf_binding["canonical_owner"]["condition_hash_semantics"]["declared_source_hash"]
    source_plan_sha256 = require_hex(source_plan_sha256, "declared source-plan condition hash")
    producer_scope_schema = report["hash_scopes"]["physical_condition"]["schema"]
    producer_conversion_schema = report["schema"]
    suffix = case_id.rsplit("_", 1)[1].lower()
    xmf_attempt_id = f"root-stage1-f7-{suffix}-full601-normal-xmf-076"
    render_attempt_id = f"root-stage1-f7-{suffix}-full601-native023-render-076"
    case_root = DATA_ROOT / case_id
    xmf_manifest = case_root / xmf_attempt_id / "xdmf" / "manifest.json"
    xmf_path = case_root / xmf_attempt_id / "xdmf" / "case.xmf"
    render_root = case_root / render_attempt_id / "render"

    out = output_dir.resolve()
    try:
        out.relative_to(source_package)
    except ValueError:
        pass
    else:
        raise AdapterError("output directory must be outside the immutable fresh076 source package")
    out.mkdir(parents=True, exist_ok=True)
    out_bindings = out / "bindings"
    out_xmf_requests = out / "requests" / "xmf"
    out_render_requests = out / "requests" / "render"
    out_bindings.mkdir(parents=True, exist_ok=True)
    out_xmf_requests.mkdir(parents=True, exist_ok=True)
    out_render_requests.mkdir(parents=True, exist_ok=True)
    new_xmf_binding_path = out_bindings / f"{case_id}.full601-xmf-binding-076.actual-bound.json"
    new_render_binding_path = out_bindings / f"{case_id}.full601-render-binding-076.actual-bound.json"

    actual_meta = {
        "typed_receipt": str(typed_receipt_path.resolve()),
        "typed_receipt_sha256": typed_receipt_sha256,
        "conversion_report": str(conversion_report_path.resolve()),
        "conversion_report_sha256": report_sha256,
        "trajectory_h5": str(trajectory_h5),
        "trajectory_h5_sha256": trajectory_sha256,
        "trajectory_h5_sha_origin": "producer conversion-report.json output_sha256",
        "trajectory_h5_read_by_adapter": False,
        "native_receipt": str(native_receipt),
        "native_receipt_sha256": native_receipt_sha256,
        "producer_conversion_schema": producer_conversion_schema,
        "producer_scope_schema": producer_scope_schema,
        "producer_physical_condition_sha256": producer_physical_sha256,
        "canonical_physical_binding_sha256": xmf_binding["canonical_owner"]["canonical_physical_binding_sha256"],
        "declared_source_plan_condition_sha256": source_plan_sha256,
        "canonical_equals_source_plan_claim": False,
    }

    new_xmf_binding = dict(xmf_binding)
    new_xmf_binding.update(
        {
            "schema": "ds02.f7.fresh076.actual-typed.full601.xmf-binding.v1",
            "scope_id": "root_followup_076_actual_full601_typed_xmf_render_templates_v1",
            "typed_receipt": actual_meta["typed_receipt"],
            "typed_receipt_sha256": typed_receipt_sha256,
            "conversion_report": actual_meta["conversion_report"],
            "conversion_report_sha256": report_sha256,
            "trajectory_h5": actual_meta["trajectory_h5"],
            "trajectory_h5_sha256": trajectory_sha256,
            "producer_conversion_schema": producer_conversion_schema,
            "producer_scope_schema": producer_scope_schema,
            "producer_physical_condition_sha256": producer_physical_sha256,
            "producer_physical_condition_matches_canonical": True,
            "physical_condition_sha256": producer_physical_sha256,
            "canonical_physical_binding_sha256": xmf_binding["canonical_owner"]["canonical_physical_binding_sha256"],
            "native_receipt": actual_meta["native_receipt"],
            "native_receipt_sha256": native_receipt_sha256,
            "typed_status": "completed/0",
            "native_status": "completed/0",
            "source_plan_condition_sha256": source_plan_sha256,
            "future_hashes_null": True,
            "source_only": True,
            "trajectory_h5_read_only": True,
            "trajectory_h5_hash_origin": "producer_attested_conversion_report",
            "output_path_contract": f"{xmf_attempt_id}/xdmf/case.xmf and manifest.json",
        }
    )
    dump_json(new_xmf_binding_path, new_xmf_binding)
    new_xmf_binding_sha256 = sha256_file(new_xmf_binding_path)

    new_render_binding = dict(render_binding)
    new_render_binding.update(
        {
            "schema": "ds02.f7.fresh076.actual-typed.full601.render-binding.v1",
            "scope_id": "root_followup_076_actual_full601_typed_xmf_render_templates_v1",
            "typed_receipt": actual_meta["typed_receipt"],
            "typed_receipt_sha256": typed_receipt_sha256,
            "conversion_report": actual_meta["conversion_report"],
            "conversion_report_sha256": report_sha256,
            "trajectory_h5": actual_meta["trajectory_h5"],
            "trajectory_h5_sha256": trajectory_sha256,
            "native_receipt": actual_meta["native_receipt"],
            "native_receipt_sha256": native_receipt_sha256,
            "producer_conversion_schema": producer_conversion_schema,
            "producer_scope_schema": producer_scope_schema,
            "producer_physical_condition_sha256": producer_physical_sha256,
            "producer_physical_condition_matches_canonical": True,
            "physical_condition_sha256": producer_physical_sha256,
            "canonical_physical_binding_sha256": xmf_binding["canonical_owner"]["canonical_physical_binding_sha256"],
            "xmf_binding": str(new_xmf_binding_path),
            "xmf_binding_sha256": new_xmf_binding_sha256,
            "xdmf": str(xmf_path),
            "xdmf_sha256": None,
            "manifest": str(xmf_manifest),
            "manifest_sha256": None,
            "typed_status": "completed/0",
            "native_status": "completed/0",
            "source_plan_condition_sha256": source_plan_sha256,
            "future_hashes_null": True,
            "source_only": True,
            "trajectory_h5_read_only": True,
            "trajectory_h5_hash_origin": "producer_attested_conversion_report",
            "output_path_contract": f"{render_attempt_id}/render",
        }
    )
    dump_json(new_render_binding_path, new_render_binding)

    xmf_request = dict(base_xmf_request)
    xmf_request.update(
        {
            "schema": "ds02.f7.fresh076.actual-typed.full601.xmf-request.v1",
            "scope_id": "root_followup_076_actual_full601_typed_xmf_render_templates_v1",
            "attempt_id": xmf_attempt_id,
            "command": update_command(base_xmf_request["command"], binding_path=new_xmf_binding_path),
            "typed_dependency": actual_meta,
            "conversion_dependency": {
                "status": "completed/0",
                "report": actual_meta["conversion_report"],
                "report_sha256": report_sha256,
                "output_hdf5": actual_meta["trajectory_h5"],
                "output_sha256": trajectory_sha256,
                "output_sha_origin": "producer_attested",
            },
            "h5_input_provenance": "producer_attested_conversion_report.output_sha256; adapter did not read H5",
            "producer_conversion_schema": producer_conversion_schema,
            "producer_scope_schema": producer_scope_schema,
            "producer_physical_condition_sha256": producer_physical_sha256,
            "canonical_physical_binding_sha256": xmf_binding["canonical_owner"]["canonical_physical_binding_sha256"],
            "declared_source_plan_condition_sha256": source_plan_sha256,
            "future_outputs": {
                "execution_receipt": f"{{attempt_root}}/execution-receipt.json",
                "execution_receipt_sha256": None,
                "manifest": f"{{attempt_root}}/xdmf/manifest.json",
                "manifest_sha256": None,
                "xdmf": f"{{attempt_root}}/xdmf/case.xmf",
                "xdmf_sha256": None,
            },
        }
    )
    xmf_files, xmf_hashes, xmf_provenance = prepare_input_closure(
        base_xmf_request["input_files"],
        old_binding_paths=(xmf_binding_path,),
        new_binding_paths=(new_xmf_binding_path,),
        typed_receipt=Path(actual_meta["typed_receipt"]),
        conversion_report=Path(actual_meta["conversion_report"]),
        native_receipt=native_receipt,
        trajectory_h5=trajectory_h5,
        trajectory_sha256=trajectory_sha256,
    )
    xmf_request["input_files"] = xmf_files
    xmf_request["input_sha256"] = xmf_hashes
    xmf_request["input_hash_provenance"] = xmf_provenance
    disable_request(xmf_request, "Disabled until Root reviews actual typed metadata and runs the isolated XMF worker.")
    xmf_request_path = out_xmf_requests / f"{case_id}.full601-normal-xmf-076.actual-bound.disabled-request.json"
    dump_json(xmf_request_path, xmf_request)

    render_request = dict(base_render_request)
    render_request.update(
        {
            "schema": "ds02.f7.fresh076.actual-typed.full601.render-request.v1",
            "scope_id": "root_followup_076_actual_full601_typed_xmf_render_templates_v1",
            "attempt_id": render_attempt_id,
            "command": update_command(base_render_request["command"], manifest_path=xmf_manifest),
            "typed_dependency": actual_meta,
            "conversion_dependency": {
                "status": "completed/0",
                "report": actual_meta["conversion_report"],
                "report_sha256": report_sha256,
                "output_hdf5": actual_meta["trajectory_h5"],
                "output_sha256": trajectory_sha256,
                "output_sha_origin": "producer_attested",
            },
            "xmf_dependency": {
                "binding": str(new_xmf_binding_path),
                "binding_sha256": new_xmf_binding_sha256,
                "manifest": str(xmf_manifest),
                "manifest_sha256": None,
                "xdmf": str(xmf_path),
                "xdmf_sha256": None,
            },
            "h5_input_provenance": "producer_attested_conversion_report.output_sha256; adapter did not read H5",
            "producer_conversion_schema": producer_conversion_schema,
            "producer_scope_schema": producer_scope_schema,
            "producer_physical_condition_sha256": producer_physical_sha256,
            "canonical_physical_binding_sha256": xmf_binding["canonical_owner"]["canonical_physical_binding_sha256"],
            "declared_source_plan_condition_sha256": source_plan_sha256,
            "future_outputs": {
                "contact_pages": f"{{attempt_root}}/render/contact-page-*.png",
                "execution_receipt": f"{{attempt_root}}/execution-receipt.json",
                "execution_receipt_sha256": None,
                "render_manifest": f"{{attempt_root}}/render/paraview-full-animation-report.json",
                "render_manifest_sha256": None,
            },
        }
    )
    render_files, render_hashes, render_provenance = prepare_input_closure(
        base_render_request["input_files"],
        old_binding_paths=(render_binding_path, xmf_binding_path),
        new_binding_paths=(new_render_binding_path, new_xmf_binding_path),
        typed_receipt=Path(actual_meta["typed_receipt"]),
        conversion_report=Path(actual_meta["conversion_report"]),
        native_receipt=native_receipt,
        trajectory_h5=trajectory_h5,
        trajectory_sha256=trajectory_sha256,
    )
    render_request["input_files"] = render_files
    render_request["input_sha256"] = render_hashes
    render_request["input_hash_provenance"] = render_provenance
    disable_request(render_request, "Disabled until Root reviews the actual XMF manifest and runs Root023.")
    render_request_path = out_render_requests / f"{case_id}.full601-native023-render-076.actual-bound.disabled-request.json"
    dump_json(render_request_path, render_request)

    return {
        "case_id": case_id,
        "typed_receipt": actual_meta["typed_receipt"],
        "typed_receipt_sha256": typed_receipt_sha256,
        "conversion_report": actual_meta["conversion_report"],
        "conversion_report_sha256": report_sha256,
        "trajectory_h5": actual_meta["trajectory_h5"],
        "trajectory_h5_sha256": trajectory_sha256,
        "native_receipt": actual_meta["native_receipt"],
        "native_receipt_sha256": native_receipt_sha256,
        "producer_physical_condition_sha256": producer_physical_sha256,
        "source_plan_condition_sha256": source_plan_sha256,
        "xmf_binding": str(new_xmf_binding_path),
        "xmf_binding_sha256": new_xmf_binding_sha256,
        "xmf_request": str(xmf_request_path),
        "render_binding": str(new_render_binding_path),
        "render_binding_sha256": sha256_file(new_render_binding_path),
        "render_request": str(render_request_path),
        "xmf_output_sha256": None,
        "xmf_manifest_sha256": None,
        "render_output_sha256": None,
        "requests_disabled": True,
        "arrays_read": False,
        "h5_read": False,
    }


def read_case_map(path: Path) -> list[dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        rows = []
        for case_id, row in value.items():
            if not isinstance(row, dict):
                raise AdapterError(f"case-map entry is not an object: {case_id}")
            rows.append({"case_id": case_id, **{str(k): str(v) for k, v in row.items()}})
        return rows
    if isinstance(value, list):
        rows = []
        for row in value:
            if not isinstance(row, dict):
                raise AdapterError("case-map list entry is not an object")
            rows.append({str(k): str(v) for k, v in row.items()})
        return rows
    raise AdapterError("case-map must be an object or list")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--typed-receipt", type=Path)
    parser.add_argument("--conversion-report", type=Path)
    parser.add_argument("--case-map", type=Path)
    args = parser.parse_args()
    source_package = args.source_package.resolve()
    if args.case_map and any(value is not None for value in (args.case_id, args.typed_receipt, args.conversion_report)):
        raise SystemExit("--case-map cannot be combined with per-case arguments")
    if args.case_map:
        rows = read_case_map(args.case_map)
    else:
        if not all(value is not None for value in (args.case_id, args.typed_receipt, args.conversion_report)):
            raise SystemExit("per-case mode requires --case-id, --typed-receipt, and --conversion-report")
        rows = [{
            "case_id": args.case_id,
            "typed_receipt": str(args.typed_receipt),
            "conversion_report": str(args.conversion_report),
        }]
    results = []
    for row in rows:
        try:
            results.append(
                bind_case(
                    source_package,
                    row["case_id"],
                    Path(row["typed_receipt"]),
                    Path(row["conversion_report"]),
                    args.output_dir,
                )
            )
        except KeyError as exc:
            raise SystemExit(f"case-map row is missing {exc.args[0]!r}: {row}") from exc
    manifest = {
        "schema": "ds02.f7.fresh076.actual-typed-bound-manifest.v1",
        "scope_id": "root_followup_076_actual_full601_typed_xmf_render_templates_v1",
        "family_id": "F7",
        "cases": results,
        "case_count": len(results),
        "arrays_read": False,
        "h5_read": False,
        "jobs_started": False,
        "shared_state_written": False,
        "requests_disabled": True,
        "future_output_hashes_null": True,
    }
    dump_json(args.output_dir.resolve() / "actual-bound-manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
