#!/usr/bin/env python3
"""Bind completed fresh077 typed metadata to disabled F7 XMF/render requests.

The adapter is deliberately metadata-only.  It reads producer JSON receipts and
reports, checks paths with stat, and adopts conversion-report.json's
output_sha256 as an attested H5 digest without opening or hashing H5/BI4/CSV/DAT
payloads.  It never invokes a solver, converter, XMF worker, renderer, NumPy,
h5py, or shared runner.
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
SCOPE_SCHEMA = "ds-data-02.physical-binding.v1"
CONVERSION_SCHEMA = "ds-data-02.bi4-direct-conversion.v1"
VENV_PYTHON = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")
TEMPLATE_PACKAGE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/"
    "root_followup_076_actual_full601_typed_xmf_render_templates_v1"
)
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
    """A producer or downstream request contract is incomplete."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdapterError(f"JSON root is not an object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    resolved = path.resolve()
    if resolved.name.lower().endswith(RAW_SUFFIXES):
        raise AdapterError(f"payload hashing is forbidden in fresh077: {resolved}")
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


def template_paths(source_package: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    for path in (
        source_package / "manifest.json",
        source_package / "README.md",
        TEMPLATE_PACKAGE / "manifest.json",
        TEMPLATE_PACKAGE / "README.md",
        VENV_PYTHON,
        XMF_WORKER,
        RENDERER,
    ):
        require_file(path, "fresh077 source input")
    bindings = TEMPLATE_PACKAGE / "bindings"
    requests = TEMPLATE_PACKAGE / "requests"
    return (
        bindings / "{case}.full601-typed-binding.json",
        bindings / "{case}.full601-xmf-binding.json",
        bindings / "{case}.full601-render-binding.json",
        requests / "xmf" / "{case}.full601-normal-xmf-076.disabled-request.json",
        requests / "render" / "{case}.full601-native023-render-076.disabled-request.json",
        source_package / "metadata" / "source-validation-report.json",
    )


def check_typed_receipt(path: Path, case_id: str) -> tuple[dict[str, Any], str]:
    receipt_path = require_file(path, "typed execution receipt")
    receipt = load_json(receipt_path)
    if (receipt.get("status"), receipt.get("returncode")) != ("completed", 0):
        raise AdapterError(f"typed receipt is not completed/0: {receipt_path}")
    request = receipt.get("request")
    if isinstance(request, dict):
        checks = (
            ("case_id", case_id),
            ("family_id", "F7"),
            ("kind", "cpu"),
            ("cpu_task_kind", "conversion"),
            ("expected_frames", 601),
            ("expected_native_frames", 601),
            ("expected_particles", 70179),
            ("expected_dimension", 3),
        )
        for key, expected in checks:
            if key in request and request[key] != expected:
                raise AdapterError(f"typed receipt request {key} mismatch: {receipt_path}")
        if request.get("attempt_id") not in (None, f"root-stage1-f7-{case_id.rsplit('_', 1)[1].lower()}-full601-typed-nvme-077"):
            raise AdapterError(f"typed receipt attempt mismatch: {receipt_path}")
        counts = request.get("expected_counts")
        if counts is not None:
            expected_counts = {"total": 70179, "fixed": 27495, "moving": 1984, "fluid": 40700, "floating": 0, "dimension": 3}
            if counts != expected_counts:
                raise AdapterError(f"typed receipt expected_counts mismatch: {receipt_path}")
    for key in ("input_hashes_at_launch", "input_hashes_after_run"):
        if key in receipt and not isinstance(receipt[key], dict):
            raise AdapterError(f"typed receipt {key} is not an object: {receipt_path}")
    if isinstance(receipt.get("input_hashes_at_launch"), dict) and isinstance(receipt.get("input_hashes_after_run"), dict):
        if receipt["input_hashes_at_launch"] != receipt["input_hashes_after_run"]:
            raise AdapterError(f"typed input hashes changed during run: {receipt_path}")
    return receipt, sha256_file(receipt_path)


def check_native_receipt(template_binding: dict[str, Any], case_id: str) -> tuple[Path, str]:
    native_path = require_file(Path(str(template_binding["native_receipt"])), "actual native receipt")
    native = load_json(native_path)
    if (native.get("status"), native.get("returncode")) != ("completed", 0):
        raise AdapterError(f"native receipt is not completed/0: {native_path}")
    request = native.get("request")
    if isinstance(request, dict):
        if request.get("case_id") not in (None, case_id):
            raise AdapterError(f"native receipt case mismatch: {native_path}")
        if request.get("expected_frames") not in (None, 601):
            raise AdapterError(f"native receipt frame mismatch: {native_path}")
        if request.get("expected_particles") not in (None, 70179):
            raise AdapterError(f"native receipt particle mismatch: {native_path}")
    declared = template_binding.get("native_receipt_sha256")
    actual = sha256_file(native_path)
    if declared is not None and require_hex(declared, "template native receipt SHA") != actual:
        raise AdapterError(f"template native receipt SHA is stale: {native_path}")
    return native_path, actual


def check_conversion_report(
    path: Path, case_id: str, canonical_sha: str
) -> tuple[dict[str, Any], Path, str, str, str]:
    report_path = require_file(path, "typed conversion report")
    report = load_json(report_path)
    if report.get("conversion_status") != "completed":
        raise AdapterError(f"conversion report is not completed: {report_path}")
    if report.get("schema") != CONVERSION_SCHEMA:
        raise AdapterError(f"unexpected conversion report schema: {report.get('schema')!r}")
    if report.get("frames") != 601 or report.get("particles") != 70179:
        raise AdapterError(f"conversion report has wrong 601/70179 contract: {report_path}")
    if report.get("solver_dimension") not in (None, 3):
        raise AdapterError(f"conversion report is not 3-D: {report_path}")
    counts = report.get("counts") or report.get("particle_counts") or report.get("expected_counts")
    if counts is not None:
        expected = {"total": 70179, "fixed": 27495, "moving": 1984, "fluid": 40700, "floating": 0}
        for key, value in expected.items():
            if key in counts and counts[key] != value:
                raise AdapterError(f"conversion report count {key} mismatch: {report_path}")
    output_raw = report.get("output_hdf5")
    if not isinstance(output_raw, str) or not output_raw:
        raise AdapterError("conversion report output_hdf5 is missing")
    output_path = Path(output_raw)
    if not output_path.is_absolute():
        output_path = (report_path.parent / output_path).resolve()
    require_file(output_path, "producer H5 output")
    output_sha = require_hex(report.get("output_sha256"), "producer output_sha256")
    if report.get("coordinate_frame") not in (
        None,
        "DualSPHysics case Cartesian coordinates (x,y,z)",
    ):
        raise AdapterError(f"conversion report coordinate frame is not native Cartesian: {report_path}")
    validation = report.get("partvtk_validation")
    if not isinstance(validation, dict) or validation.get("all_passed") is not True:
        raise AdapterError(f"PartVTK validation is not all_passed=true: {report_path}")
    scopes = report.get("hash_scopes")
    physical = scopes.get("physical_condition") if isinstance(scopes, dict) else None
    if not isinstance(physical, dict) or physical.get("schema") != SCOPE_SCHEMA:
        raise AdapterError(f"producer physical scope is not {SCOPE_SCHEMA}: {report_path}")
    producer_sha = require_hex(
        scopes.get("physical_condition_sha256"),
        "producer physical_condition_sha256",
    )
    if producer_sha != canonical_sha:
        raise AdapterError(
            f"producer canonical scope mismatch for {case_id}: {producer_sha} != {canonical_sha}"
        )
    if physical.get("physical_case_id") not in (None, case_id):
        raise AdapterError(f"producer physical case mismatch: {report_path}")
    return report, output_path, output_sha, producer_sha, sha256_file(report_path)


def replace_command(
    command: list[Any], *, binding_path: Path | None = None, manifest_path: Path | None = None
) -> list[str]:
    result = [str(VENV_PYTHON) if item == "/usr/bin/python3.10" else str(item) for item in command]
    if binding_path is not None:
        if "--binding" not in result:
            raise AdapterError("template XMF command has no --binding")
        result[result.index("--binding") + 1] = str(binding_path)
    if manifest_path is not None:
        if "--manifest" not in result:
            raise AdapterError("template renderer command has no --manifest")
        result[result.index("--manifest") + 1] = str(manifest_path)
    return result


def future077(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("-076", "-077")
    if isinstance(value, list):
        return [future077(item) for item in value]
    if isinstance(value, dict):
        return {str(key): future077(item) for key, item in value.items()}
    return value


def prepare_input_closure(
    base_files: Iterable[Any],
    *,
    remove_paths: Iterable[Path],
    add_paths: Iterable[Path],
    typed_receipt: Path,
    conversion_report: Path,
    native_receipt: Path,
    trajectory_h5: Path,
    trajectory_sha256: str,
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    removed = {str(path.resolve()) for path in remove_paths}
    files: list[str] = []
    for raw in base_files:
        path = str(raw)
        if path == "/usr/bin/python3.10":
            path = str(VENV_PYTHON)
        if Path(path).resolve().as_posix() in removed:
            continue
        files.append(path)
    files.extend(str(path.resolve()) for path in add_paths)
    files.extend(
        str(path.resolve())
        for path in (typed_receipt, conversion_report, native_receipt, trajectory_h5)
    )
    files = unique(files)
    hashes: dict[str, str] = {}
    provenance: dict[str, str] = {}
    h5_key = str(trajectory_h5.resolve())
    for raw in files:
        path = Path(raw)
        if str(path.resolve()) == h5_key:
            hashes[raw] = trajectory_sha256
            provenance[raw] = "producer_attested:conversion-report.output_sha256; adapter_did_not_read_h5"
            continue
        if path.name.lower().endswith(RAW_SUFFIXES):
            raise AdapterError(f"scientific payload entered input closure: {path}")
        require_file(path, "downstream metadata input")
        hashes[raw] = sha256_file(path)
        provenance[raw] = "adapter_hashed_bounded_metadata_or_source"
    if set(files) != set(hashes):
        raise AdapterError("input_files and input_sha256 sets are not equal")
    return files, hashes, provenance


def disabled(request: dict[str, Any], reason: str) -> dict[str, Any]:
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
    (
        typed_binding_template_path,
        xmf_binding_template_path,
        render_binding_template_path,
        xmf_request_template_path,
        render_request_template_path,
        validation_path,
    ) = template_paths(source_package)
    owner_path = require_file(
        source_package / "owners" / f"{case_id}.converter-owner.json",
        "corrected converter owner",
    )
    owner = load_json(owner_path)
    if owner.get("case_id") != case_id or owner.get("schema") != "ds02.f7.fresh077.converter-owner.v1":
        raise AdapterError(f"corrected owner schema/case mismatch: {owner_path}")
    canonical_sha = require_hex(owner.get("canonical_physical_binding_sha256"), "corrected owner canonical hash")
    if owner.get("physical_condition_sha256") != canonical_sha:
        raise AdapterError("corrected owner physical_condition_sha256 does not equal converter hash")
    source_plan_sha = require_hex(
        owner.get("condition_hash_semantics", {}).get("declared_source_hash"),
        "fresh074 source-plan hash",
    )
    if source_plan_sha == canonical_sha:
        raise AdapterError("source-plan hash was conflated with corrected converter hash")
    template_typed = load_json(typed_binding_template_path.format(case=case_id))
    template_xmf = load_json(xmf_binding_template_path.format(case=case_id))
    template_render = load_json(render_binding_template_path.format(case=case_id))
    template_xmf_request = load_json(xmf_request_template_path.format(case=case_id))
    template_render_request = load_json(render_request_template_path.format(case=case_id))
    if not template_xmf_request.get("disabled") or not template_render_request.get("disabled"):
        raise AdapterError("immutable fresh076 XMF/render templates must remain disabled")
    typed_receipt, typed_receipt_sha = check_typed_receipt(typed_receipt_path, case_id)
    native_receipt, native_receipt_sha = check_native_receipt(template_xmf, case_id)
    report, trajectory_h5, trajectory_sha, producer_sha, report_sha = check_conversion_report(
        conversion_report_path, case_id, canonical_sha
    )
    suffix = case_id.rsplit("_", 1)[1].lower()
    xmf_attempt_id = f"root-stage1-f7-{suffix}-full601-normal-xmf-077"
    render_attempt_id = f"root-stage1-f7-{suffix}-full601-native023-render-077"
    case_root = DATA_ROOT / case_id
    xmf_manifest = case_root / xmf_attempt_id / "xdmf" / "manifest.json"
    xmf_path = case_root / xmf_attempt_id / "xdmf" / "case.xmf"
    render_root = case_root / render_attempt_id / "render"
    out = output_dir.resolve()
    if out.is_relative_to(source_package):
        raise AdapterError("output directory must be outside the immutable fresh077 source package")
    out_bindings = out / "bindings"
    out_xmf = out / "requests" / "xmf"
    out_render = out / "requests" / "render"
    out_bindings.mkdir(parents=True, exist_ok=True)
    out_xmf.mkdir(parents=True, exist_ok=True)
    out_render.mkdir(parents=True, exist_ok=True)
    old_owner_path = Path(str(template_xmf["canonical_owner"]["owner_path"])).resolve()
    legacy_owner_sha = require_hex(template_xmf["canonical_owner"]["owner_sha256"], "legacy owner SHA")
    if sha256_file(old_owner_path) != legacy_owner_sha:
        raise AdapterError(f"legacy source owner SHA is stale: {old_owner_path}")
    old_binding_paths = [
        typed_binding_template_path.format(case=case_id),
        xmf_binding_template_path.format(case=case_id),
        render_binding_template_path.format(case=case_id),
    ]
    new_xmf_binding_path = out_bindings / f"{case_id}.full601-xmf-binding-077.actual-bound.json"
    new_render_binding_path = out_bindings / f"{case_id}.full601-render-binding-077.actual-bound.json"
    actual = {
        "typed_receipt": str(typed_receipt_path.resolve()),
        "typed_receipt_sha256": typed_receipt_sha,
        "conversion_report": str(conversion_report_path.resolve()),
        "conversion_report_sha256": report_sha,
        "trajectory_h5": str(trajectory_h5),
        "trajectory_h5_sha256": trajectory_sha,
        "trajectory_h5_hash_origin": "producer conversion-report.json output_sha256",
        "trajectory_h5_read_by_adapter": False,
        "native_receipt": str(native_receipt),
        "native_receipt_sha256": native_receipt_sha,
        "producer_conversion_schema": CONVERSION_SCHEMA,
        "producer_scope_schema": SCOPE_SCHEMA,
        "producer_physical_condition_sha256": producer_sha,
        "canonical_physical_binding_sha256": canonical_sha,
        "declared_source_plan_condition_sha256": source_plan_sha,
        "legacy_source_owner": str(old_owner_path),
        "legacy_source_owner_sha256": legacy_owner_sha,
        "canonical_equals_source_plan_claim": False,
    }
    canonical_owner = {
        "owner_path": str(owner_path.resolve()),
        "owner_sha256": sha256_file(owner_path),
        "canonical_physical_binding_sha256": canonical_sha,
        "source_plan_condition_sha256": source_plan_sha,
        "condition_hash_semantics": owner["condition_hash_semantics"],
        "legacy_source_owner_path": str(old_owner_path),
        "legacy_source_owner_sha256": legacy_owner_sha,
    }
    xmf_binding = dict(template_xmf)
    xmf_binding.update({
        "schema": "ds02.f7.fresh077.actual-typed.full601.xmf-binding.v1",
        "scope_id": "root_followup_077_actual_converter_scope_root142_adapter_v1",
        "canonical_owner": canonical_owner,
        "canonical_physical_binding_sha256": canonical_sha,
        "physical_condition_sha256": canonical_sha,
        "source_plan_condition_sha256": source_plan_sha,
        "producer_physical_condition_sha256": producer_sha,
        "producer_physical_condition_matches_canonical": producer_sha == canonical_sha,
        "producer_scope_schema": SCOPE_SCHEMA,
        "typed_receipt": actual["typed_receipt"],
        "typed_receipt_sha256": typed_receipt_sha,
        "conversion_report": actual["conversion_report"],
        "conversion_report_sha256": report_sha,
        "trajectory_h5": actual["trajectory_h5"],
        "trajectory_h5_sha256": trajectory_sha,
        "trajectory_h5_read_by_adapter": False,
        "native_receipt": actual["native_receipt"],
        "native_receipt_sha256": native_receipt_sha,
        "typed_status": "completed/0",
        "native_status": "completed/0",
        "future_hashes_null": True,
        "source_only": True,
        "physical_condition_scope_repair": owner["condition_hash_semantics"],
        "output_path_contract": f"{xmf_attempt_id}/xdmf/case.xmf and manifest.json",
    })
    dump_json(new_xmf_binding_path, xmf_binding)
    new_xmf_binding_sha = sha256_file(new_xmf_binding_path)
    render_binding = dict(template_render)
    render_binding.update({
        "schema": "ds02.f7.fresh077.actual-typed.full601.render-binding.v1",
        "scope_id": "root_followup_077_actual_converter_scope_root142_adapter_v1",
        "canonical_owner": canonical_owner,
        "canonical_physical_binding_sha256": canonical_sha,
        "physical_condition_sha256": canonical_sha,
        "source_plan_condition_sha256": source_plan_sha,
        "producer_physical_condition_sha256": producer_sha,
        "producer_physical_condition_matches_canonical": producer_sha == canonical_sha,
        "producer_scope_schema": SCOPE_SCHEMA,
        "typed_receipt": actual["typed_receipt"],
        "typed_receipt_sha256": typed_receipt_sha,
        "conversion_report": actual["conversion_report"],
        "conversion_report_sha256": report_sha,
        "trajectory_h5": actual["trajectory_h5"],
        "trajectory_h5_sha256": trajectory_sha,
        "native_receipt": actual["native_receipt"],
        "native_receipt_sha256": native_receipt_sha,
        "xmf_binding": str(new_xmf_binding_path),
        "xmf_binding_sha256": new_xmf_binding_sha,
        "xdmf": str(xmf_path),
        "xdmf_sha256": None,
        "manifest": str(xmf_manifest),
        "manifest_sha256": None,
        "typed_status": "completed/0",
        "native_status": "completed/0",
        "future_hashes_null": True,
        "source_only": True,
        "output_path_contract": f"{render_attempt_id}/render",
    })
    dump_json(new_render_binding_path, render_binding)
    base_xmf = future077(dict(template_xmf_request))
    base_render = future077(dict(template_render_request))
    xmf_request = dict(base_xmf)
    xmf_request.update({
        "schema": "ds02.f7.fresh077.actual-typed.full601.xmf-request.v1",
        "scope_id": "root_followup_077_actual_converter_scope_root142_adapter_v1",
        "attempt_id": xmf_attempt_id,
        "command": replace_command(base_xmf["command"], binding_path=new_xmf_binding_path),
        "typed_dependency": actual,
        "conversion_dependency": {
            "status": "completed/0",
            "report": actual["conversion_report"],
            "report_sha256": report_sha,
            "output_hdf5": actual["trajectory_h5"],
            "output_sha256": trajectory_sha,
            "output_sha_origin": "producer_attested",
        },
        "producer_conversion_schema": CONVERSION_SCHEMA,
        "producer_scope_schema": SCOPE_SCHEMA,
        "producer_physical_condition_sha256": producer_sha,
        "canonical_physical_binding_sha256": canonical_sha,
        "declared_source_plan_condition_sha256": source_plan_sha,
        "h5_input_provenance": "producer_attested conversion-report.output_sha256; adapter did not read H5",
        "future_outputs": {
            "execution_receipt": f"{{attempt_root}}/execution-receipt.json",
            "execution_receipt_sha256": None,
            "manifest": f"{{attempt_root}}/xdmf/manifest.json",
            "manifest_sha256": None,
            "xdmf": f"{{attempt_root}}/xdmf/case.xmf",
            "xdmf_sha256": None,
        },
    })
    source_files = [
        owner_path,
        validation_path,
        TEMPLATE_PACKAGE / "manifest.json",
        TEMPLATE_PACKAGE / "README.md",
    ]
    remove = old_binding_paths + [old_owner_path]
    xmf_files, xmf_hashes, xmf_provenance = prepare_input_closure(
        base_xmf["input_files"],
        remove_paths=remove,
        add_paths=[new_xmf_binding_path, owner_path, validation_path],
        typed_receipt=typed_receipt_path,
        conversion_report=conversion_report_path,
        native_receipt=native_receipt,
        trajectory_h5=trajectory_h5,
        trajectory_sha256=trajectory_sha,
    )
    xmf_request["input_files"] = xmf_files
    xmf_request["input_sha256"] = xmf_hashes
    xmf_request["input_hash_provenance"] = xmf_provenance
    disabled(xmf_request, "Disabled until Root reviews actual typed metadata and explicitly enables Root105 XMF.")
    xmf_request_path = out_xmf / f"{case_id}.full601-normal-xmf-077.actual-bound.disabled-request.json"
    dump_json(xmf_request_path, xmf_request)
    render_request = dict(base_render)
    render_request.update({
        "schema": "ds02.f7.fresh077.actual-typed.full601.render-request.v1",
        "scope_id": "root_followup_077_actual_converter_scope_root142_adapter_v1",
        "attempt_id": render_attempt_id,
        "command": replace_command(base_render["command"], manifest_path=xmf_manifest),
        "typed_dependency": actual,
        "conversion_dependency": {
            "status": "completed/0",
            "report": actual["conversion_report"],
            "report_sha256": report_sha,
            "output_hdf5": actual["trajectory_h5"],
            "output_sha256": trajectory_sha,
            "output_sha_origin": "producer_attested",
        },
        "xmf_dependency": {
            "binding": str(new_xmf_binding_path),
            "binding_sha256": new_xmf_binding_sha,
            "manifest": str(xmf_manifest),
            "manifest_sha256": None,
            "xdmf": str(xmf_path),
            "xdmf_sha256": None,
        },
        "producer_conversion_schema": CONVERSION_SCHEMA,
        "producer_scope_schema": SCOPE_SCHEMA,
        "producer_physical_condition_sha256": producer_sha,
        "canonical_physical_binding_sha256": canonical_sha,
        "declared_source_plan_condition_sha256": source_plan_sha,
        "h5_input_provenance": "producer_attested conversion-report.output_sha256; adapter did not read H5",
        "future_outputs": {
            "contact_pages": f"{{attempt_root}}/render/contact-page-*.png",
            "execution_receipt": f"{{attempt_root}}/execution-receipt.json",
            "execution_receipt_sha256": None,
            "render_manifest": f"{{attempt_root}}/render/paraview-full-animation-report.json",
            "render_manifest_sha256": None,
        },
    })
    render_files, render_hashes, render_provenance = prepare_input_closure(
        base_render["input_files"],
        remove_paths=remove,
        add_paths=[new_render_binding_path, new_xmf_binding_path, owner_path, validation_path],
        typed_receipt=typed_receipt_path,
        conversion_report=conversion_report_path,
        native_receipt=native_receipt,
        trajectory_h5=trajectory_h5,
        trajectory_sha256=trajectory_sha,
    )
    render_request["input_files"] = render_files
    render_request["input_sha256"] = render_hashes
    render_request["input_hash_provenance"] = render_provenance
    disabled(render_request, "Disabled until Root reviews the actual XMF manifest and explicitly enables Root023.")
    render_request_path = out_render / f"{case_id}.full601-native023-render-077.actual-bound.disabled-request.json"
    dump_json(render_request_path, render_request)
    return {
        "case_id": case_id,
        "typed_receipt": actual["typed_receipt"],
        "typed_receipt_sha256": typed_receipt_sha,
        "conversion_report": actual["conversion_report"],
        "conversion_report_sha256": report_sha,
        "trajectory_h5": actual["trajectory_h5"],
        "trajectory_h5_sha256": trajectory_sha,
        "native_receipt": actual["native_receipt"],
        "native_receipt_sha256": native_receipt_sha,
        "producer_physical_condition_sha256": producer_sha,
        "canonical_physical_binding_sha256": canonical_sha,
        "source_plan_condition_sha256": source_plan_sha,
        "xmf_binding": str(new_xmf_binding_path),
        "xmf_binding_sha256": new_xmf_binding_sha,
        "xmf_request": str(xmf_request_path),
        "render_binding": str(new_render_binding_path),
        "render_binding_sha256": sha256_file(new_render_binding_path),
        "render_request": str(render_request_path),
        "xmf_manifest_sha256": None,
        "render_output_sha256": None,
        "requests_disabled": True,
        "arrays_read": False,
        "h5_read": False,
    }


def read_case_map(path: Path) -> list[dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    if isinstance(value, dict):
        for case_id, row in value.items():
            if not isinstance(row, dict):
                raise AdapterError(f"case-map entry is not an object: {case_id}")
            rows.append({"case_id": case_id, **{str(k): str(v) for k, v in row.items()}})
    elif isinstance(value, list):
        for row in value:
            if not isinstance(row, dict):
                raise AdapterError("case-map list entry is not an object")
            rows.append({str(k): str(v) for k, v in row.items()})
    else:
        raise AdapterError("case-map must be an object or list")
    return rows


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
        rows = [{"case_id": args.case_id, "typed_receipt": str(args.typed_receipt), "conversion_report": str(args.conversion_report)}]
    if not rows:
        raise SystemExit("case-map is empty")
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
        "schema": "ds02.f7.fresh077.actual-typed-bound-manifest.v1",
        "scope_id": "root_followup_077_actual_converter_scope_root142_adapter_v1",
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

