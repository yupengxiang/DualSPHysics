#!/usr/bin/env python3
"""Bind the disabled F5 B071 bed-audit request after actual XMF190.

This source-only binder reads JSON/XML metadata and hashes XML/JSON/source files.
It registers the immutable H5 using the completed converter digest and never
opens BI4, H5, or CSV scientific arrays.  The generated Root201 request stays
disabled until Root enables it through the strict dispatcher.  It keeps the
GenCase receipt attempt root separate from its ``prepared/`` XML directory.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Mapping

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FRESH079_ROOT = PACKAGE_ROOT.parent / "root_followup_079_stage1_f5_b071_post_conversion_pipeline_v1"
FRESH079_ASSEMBLER = FRESH079_ROOT / "scripts/assemble_post_conversion_pipeline.py"
FAMILY_ID = "F5"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071"
PHYSICAL_CASE_ID = "F5_COMPACT_STILL_WATER_RUNUP_REPAIR_B_CENTRAL_SUPPORT_V1"
PACKAGE_ID = "root_followup_081_stage1_f5_b071_bed_audit_binding_repair_v1"
BED_ATTEMPT = "root-stage1-f5-b071-short-native-bed-audit-binding-repair-201"
BINDING_SCHEMA = "ds02.f5.b071.short-event-bed-audit-binding.fresh081.v1"
REPORT_SCHEMA = "ds02.f5.b071.fresh081.bed-audit-binding.v1"
CANONICAL_PHYSICAL_CONDITION_SHA256 = "d791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f"
SOURCE_PLAN_PHYSICAL_CONDITION_SHA256 = "e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72"
SOURCE_H5_PHYSICAL_CONDITION_SHA256 = "efa8c9822ee12f6400e36e09e6b1edaebb760882f3354adabb6113a72f380047"
SOURCE_H5_SCOPE_SCHEMA = "legacy-owner-scope.v0"
SOURCE_H5_SCOPE_STATUS = "legacy_incomplete; no cross-resolution physical claim"
EXPECTED_FRAMES = 51
EXPECTED_PARTICLES = 174896
EXPECTED_FIXED = 130392
EXPECTED_MOVING = 3794
EXPECTED_FLUID = 40710
WORKER = PACKAGE_ROOT / "workers/bed_audit_axis_repaired.py"
NATIVE_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/"
    "root-stage1-f5-b071-short-native-qualification-187/execution-receipt.json"
)
H5_SUFFIXES = {".h5", ".hdf5", ".bi4", ".csv"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("fresh079_assembler", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import fresh079 assembler: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FRESH079 = load_module(FRESH079_ASSEMBLER)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalized(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def load_json(path: str | Path) -> dict[str, Any]:
    resolved = normalized(path)
    with resolved.open(encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"JSON object required: {resolved}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    require(path.suffix.lower() not in {".h5", ".hdf5", ".bi4", ".csv"}, f"array digest forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_digest(path: Path, known_h5_sha256: str | None = None) -> str:
    path = normalized(path)
    require(path.is_file(), f"input missing: {path}")
    suffix = path.suffix.lower()
    if suffix in H5_SUFFIXES:
        require(suffix in {".h5", ".hdf5"}, f"BI4/CSV input forbidden: {path}")
        require(isinstance(known_h5_sha256, str) and HEX64.fullmatch(known_h5_sha256),
                f"H5 must use converter digest: {path}")
        return known_h5_sha256
    require("resource-ledger.json" not in str(path).lower(), f"live ledger input forbidden: {path}")
    return sha256_file(path)


def add_input(inputs: dict[str, str], path: Path, known_h5_sha256: str | None = None) -> None:
    path = normalized(path)
    digest = input_digest(path, known_h5_sha256)
    previous = inputs.get(str(path))
    require(previous in (None, digest), f"conflicting digest for {path}")
    inputs[str(path)] = digest


def canonical_owner_provenance(typed: Mapping[str, Any]) -> dict[str, Any]:
    owner = typed["canonical_owner_provenance"]
    require(owner["physical_condition_sha256"] == CANONICAL_PHYSICAL_CONDITION_SHA256,
            "canonical owner hash mismatch")
    require(owner["source_plan_physical_condition_sha256"] == SOURCE_PLAN_PHYSICAL_CONDITION_SHA256,
            "source plan hash mismatch")
    return copy.deepcopy(owner)


def make_semantics(typed: Mapping[str, Any]) -> dict[str, Any]:
    scope = typed["report_physical_condition_scope"]
    require(scope["schema"] == SOURCE_H5_SCOPE_SCHEMA, "typed legacy scope schema mismatch")
    require(scope["semantic_binding_status"] == SOURCE_H5_SCOPE_STATUS, "typed legacy scope status mismatch")
    require(typed["report_physical_condition_sha256"] == SOURCE_H5_PHYSICAL_CONDITION_SHA256,
            "typed H5 legacy hash mismatch")
    return {
        "canonical_owner_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
        "source_h5_sha256": SOURCE_H5_PHYSICAL_CONDITION_SHA256,
        "source_h5_scope_schema": SOURCE_H5_SCOPE_SCHEMA,
        "source_h5_scope_status": SOURCE_H5_SCOPE_STATUS,
        "relation": "distinct; H5 attribute is checked against producer legacy scope and never substituted for canonical owner",
    }


def resolve_native_receipt(typed: Mapping[str, Any]) -> Path:
    """Resolve the actual native187 receipt, without trusting a missing path.

    Root189's request schema carries the native receipt path in its nested
    bindings in current executions, while older receipts only retain its
    digest.  The canonical producer path is therefore an explicit final
    fallback; it is accepted only when the file exists and has the immutable
    Root187 receipt digest.
    """
    candidates = [
        typed.get("request", {}).get("actual_bindings", {}).get("short_solver_receipt"),
        typed.get("receipt", {}).get("request", {}).get("actual_bindings", {}).get("short_solver_receipt"),
        str(NATIVE_RECEIPT_PATH),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = normalized(str(candidate))
        if path.is_file():
            require(sha256_file(path) == FRESH079.NATIVE_RECEIPT_SHA256,
                    f"native187 receipt digest mismatch: {path}")
            return path
    raise ValueError("actual native187 receipt path is missing")


def bind(args: argparse.Namespace) -> dict[str, Any]:
    typed = FRESH079.verify_typed_conversion(normalized(args.typed_receipt), normalized(args.conversion_report))
    xmf = FRESH079.verify_xmf_receipt(normalized(args.xmf_receipt), normalized(args.xmf_dir), typed)
    native_receipt = resolve_native_receipt(typed)
    require(xmf["request"].get("attempt_id") == "root-stage1-f5-b071-short-native-xmf-190",
            "XMF dependency is not actual Root190")
    require(xmf["manifest"].get("frames") == EXPECTED_FRAMES and xmf["manifest"].get("particles") == EXPECTED_PARTICLES,
            "XMF axis mismatch")
    require(xmf["manifest"].get("physical_condition_sha256") == CANONICAL_PHYSICAL_CONDITION_SHA256,
            "XMF canonical physical owner mismatch")

    template_binding = load_json(PACKAGE_ROOT / "short-bed-audit-binding-template.json")
    output_dir = normalized(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    case_root = Path(typed["typed_root"]).parent
    bed_output_root = case_root / BED_ATTEMPT
    binding_path = output_dir / "bed-audit-binding.json"
    report_scope = typed["report_physical_condition_scope"]
    semantics = make_semantics(typed)
    worker_sha = sha256_file(WORKER)
    owner = canonical_owner_provenance(typed)
    gencase_receipt = load_json(owner["gencase_receipt"]["path"])
    require(gencase_receipt.get("status") == "completed" and gencase_receipt.get("returncode") == 0,
            "actual GenCase163 receipt is not completed/0")
    gencase_receipt_output_root = normalized(gencase_receipt.get("output_root", ""))
    gencase_prepared_output_root = normalized(owner["generated_xml"]["path"]).parent
    require(gencase_receipt_output_root.is_dir(), "actual GenCase163 receipt output root is missing")
    try:
        gencase_prepared_output_root.relative_to(gencase_receipt_output_root)
    except ValueError as exc:
        raise ValueError("actual GenCase163 prepared XML is outside its receipt output root") from exc
    binding = copy.deepcopy(template_binding)
    binding.update({
        "schema": BINDING_SCHEMA,
        "bound_status": "actual_typed189_xmf190_fresh081_root_binding_repair_disabled",
        "package_id": PACKAGE_ID,
        "worker_source": str(WORKER),
        "worker_source_sha256": worker_sha,
        "attempt_id": BED_ATTEMPT,
        "case_id": CASE_ID,
        "family_id": FAMILY_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "expected_dimension": 3,
        "expected_frames": EXPECTED_FRAMES,
        "expected_particle_axis": EXPECTED_PARTICLES,
        "expected_fixed_particles": EXPECTED_FIXED,
        "expected_moving_particles": EXPECTED_MOVING,
        "expected_fluid_particles": EXPECTED_FLUID,
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "physical_condition_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
        "source_plan_physical_condition_sha256": SOURCE_PLAN_PHYSICAL_CONDITION_SHA256,
        "source_h5_physical_condition_sha256": SOURCE_H5_PHYSICAL_CONDITION_SHA256,
        "physical_condition_hash_semantics": semantics,
        "conversion_report_physical_hash_scope": report_scope,
        "conversion_report_physical_hash_is_canonical": False,
        "canonical_owner_provenance": owner,
        "canonical_generated_xml": owner["generated_xml"]["path"],
        "canonical_generated_xml_sha256": owner["generated_xml"]["sha256"],
        "canonical_gencase_receipt": owner["gencase_receipt"]["path"],
        "canonical_gencase_receipt_sha256": owner["gencase_receipt"]["sha256"],
        "native187_request_sha256": owner["native187_request_sha256"],
        "native187_receipt_sha256": owner["native187_receipt_sha256"],
        "gencase_receipt": owner["gencase_receipt"]["path"],
        "gencase_receipt_sha256": owner["gencase_receipt"]["sha256"],
        "gencase_output_root": str(gencase_receipt_output_root),
        "gencase_receipt_output_root": str(gencase_receipt_output_root),
        "gencase_prepared_output_root": str(gencase_prepared_output_root),
        "native_conversion_report": str(typed["report_path"]),
        "native_conversion_report_sha256": typed["report_sha256"],
        "trajectory_h5": str(typed["trajectory_h5"]),
        "trajectory_h5_sha256": typed["trajectory_h5_sha256"],
        "short_solver_receipt": str(native_receipt),
        "short_solver_receipt_sha256": FRESH079.NATIVE_RECEIPT_SHA256,
        "xdmf": str(xmf["xmf_path"]),
        "xdmf_sha256": xmf["xmf_sha256"],
        "xmf_manifest": str(xmf["manifest_path"]),
        "xmf_manifest_sha256": xmf["manifest_sha256"],
        "typed_receipt": str(typed["receipt_path"]),
        "typed_receipt_sha256": typed["receipt_sha256"],
        "conversion_report": str(typed["report_path"]),
        "conversion_report_sha256": typed["report_sha256"],
        "full16_authorized": False,
        "full801_authorized": False,
        "repair_success": "unknown_until_actual_short_framewise_audit",
        "source_h5_read_only": True,
    })
    # Prefer the actual native binding path from the conversion request.
    binding["short_solver_output_root"] = str(Path(binding["short_solver_receipt"]).parent)
    write_json(binding_path, binding)

    python_path = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
    runtime_path = FRESH079.RUNTIME_PATH
    strict_path = FRESH079.STRICT_PATH
    command = [str(python_path), str(WORKER), "--binding", str(binding_path),
               "--trajectory-h5", str(typed["trajectory_h5"]), "--xdmf", str(xmf["xmf_path"]),
               "--output-dir", "{attempt_root}/audit-output"]
    inputs: dict[str, str] = {}
    metadata_paths = [
        python_path, WORKER, binding_path, runtime_path, strict_path,
        typed["receipt_path"], typed["report_path"],
        Path(owner["generated_xml"]["path"]), Path(owner["gencase_receipt"]["path"]),
        Path(typed["request"]["actual_bindings"]["initial_qa_receipt"]),
        Path(typed["request"]["actual_bindings"]["initial_qa_report"]),
        Path(typed["request"]["actual_bindings"]["root185_coverage_receipt"]),
        Path(typed["request"]["actual_bindings"]["root185_coverage_report"]),
        native_receipt,
        normalized(args.xmf_receipt), xmf["xmf_path"], xmf["manifest_path"],
    ]
    for path in metadata_paths:
        add_input(inputs, path)
    add_input(inputs, typed["trajectory_h5"], typed["trajectory_h5_sha256"])
    input_files = sorted(inputs)
    input_sha256 = {path: inputs[path] for path in input_files}

    base_request = load_json(PACKAGE_ROOT / "short-bed-audit-request.json")
    request = FRESH079.update_common_request(
        copy.deepcopy(base_request),
        attempt_id=BED_ATTEMPT,
        task_kind="audit",
        depends_on=xmf["request"]["attempt_id"],
        source_root=PACKAGE_ROOT,
        output_root=bed_output_root,
        command=command,
        input_files=input_files,
        input_sha256=input_sha256,
    )
    request.update({
        "package_id": PACKAGE_ID,
        "family_id": FAMILY_ID,
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "condition_id": "F5_RUNUP_DP020_EQUILIBRIUM_ROOT050_B_SURFACE_FULL_AUTOFILL_071",
        "worker_source": str(WORKER),
        "worker_source_sha256": worker_sha,
        "expected_dimension": 3,
        "expected_frames": EXPECTED_FRAMES,
        "expected_particle_axis": EXPECTED_PARTICLES,
        "expected_fixed_particles": EXPECTED_FIXED,
        "expected_moving_particles": EXPECTED_MOVING,
        "expected_fluid_particles": EXPECTED_FLUID,
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "physical_condition_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
        "source_plan_physical_condition_sha256": SOURCE_PLAN_PHYSICAL_CONDITION_SHA256,
        "source_h5_physical_condition_sha256": SOURCE_H5_PHYSICAL_CONDITION_SHA256,
        "physical_condition_hash_semantics": semantics,
        "conversion_report_physical_hash_scope": report_scope,
        "conversion_report_physical_hash_is_canonical": False,
        "canonical_owner_provenance": owner,
        "typed_receipt": str(typed["receipt_path"]),
        "typed_receipt_sha256": typed["receipt_sha256"],
        "native_conversion_report": str(typed["report_path"]),
        "native_conversion_report_sha256": typed["report_sha256"],
        "trajectory_h5": str(typed["trajectory_h5"]),
        "trajectory_h5_sha256": typed["trajectory_h5_sha256"],
        "xdmf": str(xmf["xmf_path"]),
        "xdmf_sha256": xmf["xmf_sha256"],
        "xmf_manifest": str(xmf["manifest_path"]),
        "xmf_manifest_sha256": xmf["manifest_sha256"],
        "actual_bindings": {
            "typed_receipt": str(typed["receipt_path"]),
            "typed_receipt_sha256": typed["receipt_sha256"],
            "conversion_report": str(typed["report_path"]),
            "conversion_report_sha256": typed["report_sha256"],
            "xmf_receipt": str(xmf["receipt_path"]),
            "xmf_receipt_sha256": xmf["receipt_sha256"],
            "xmf_manifest": str(xmf["manifest_path"]),
            "xmf_manifest_sha256": xmf["manifest_sha256"],
            "native187_receipt_sha256": owner["native187_receipt_sha256"],
            "native187_request_sha256": owner["native187_request_sha256"],
            "canonical_generated_xml_sha256": owner["generated_xml"]["sha256"],
            "canonical_gencase_receipt_sha256": owner["gencase_receipt"]["sha256"],
            "gencase_receipt_output_root": str(gencase_receipt_output_root),
            "gencase_prepared_output_root": str(gencase_prepared_output_root),
        },
        "gencase_output_root": str(gencase_receipt_output_root),
        "gencase_receipt_output_root": str(gencase_receipt_output_root),
        "gencase_prepared_output_root": str(gencase_prepared_output_root),
        "genuine_gencase_required": True,
        "actual_initial_qa_required": True,
        "actual_root185_coverage_required": True,
        "native_conversion_required": True,
        "xmf_required": True,
        "diagnostic_only": True,
        "solver_allowed": False,
        "execution_allowed": False,
        "launch_allowed": False,
        "full16_authorized": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "old_attempt_modification_forbidden": True,
        "output_contract": {
            "required_outputs": ["audit-output/b071-short-event-bed-footprint-audit.json"],
            "all_51_frames_scanned": True,
            "frame_indices": list(range(51)),
            "particle_axis_count": EXPECTED_PARTICLES,
            "fixed_particles": EXPECTED_FIXED,
            "moving_particles": EXPECTED_MOVING,
            "fluid_particles": EXPECTED_FLUID,
            "native_bed_marker_mk": 50,
            "source_bed_marker_mkbound": 40,
            "bed_x_domain_m": [-0.2, 4.8],
            "bed_y_domain_m": [-0.15, 0.15],
            "depth_tolerances_m": [0.02, 0.04],
            "penetration_thresholds_diagnostic_only": True,
            "uid_loss_nonfinite_unexplained": True,
            "future_sha256": None,
        },
        "future_inputs": {
            "all_51_frames_required": True,
            "trajectory_h5": str(typed["trajectory_h5"]),
            "trajectory_h5_sha256": typed["trajectory_h5_sha256"],
            "xdmf": str(xmf["xmf_path"]),
            "xdmf_sha256": xmf["xmf_sha256"],
            "xmf_manifest": str(xmf["manifest_path"]),
            "xmf_manifest_sha256": xmf["manifest_sha256"],
        },
    })
    FRESH079.verify_registered_request(request, "fresh081 bed request", allow_h5=True)
    request_path = output_dir / "bed-audit-request.json"
    write_json(request_path, request)
    report = {
        "schema": REPORT_SCHEMA,
        "source_only": True,
        "arrays_opened": False,
        "jobs_started": False,
        "execution_allowed": False,
        "launch_allowed": False,
        "full801_authorized": False,
        "native_particle_axis": EXPECTED_PARTICLES,
        "fixed_particles": EXPECTED_FIXED,
        "moving_particles": EXPECTED_MOVING,
        "fluid_particles": EXPECTED_FLUID,
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "canonical_physical_condition_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
        "source_h5_physical_condition_sha256": SOURCE_H5_PHYSICAL_CONDITION_SHA256,
        "worker_source_sha256": worker_sha,
        "typed_receipt_sha256": typed["receipt_sha256"],
        "xmf_receipt_sha256": xmf["receipt_sha256"],
        "xmf_manifest_sha256": xmf["manifest_sha256"],
        "binding": str(binding_path),
        "request": str(request_path),
    }
    write_json(output_dir / "binding-report.json", report)
    return {"binding": binding_path, "request": request_path, "report": output_dir / "binding-report.json", "worker_sha256": worker_sha}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--typed-receipt", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--xmf-receipt", type=Path, required=True)
    parser.add_argument("--xmf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = bind(args)
    print(json.dumps({"schema": REPORT_SCHEMA, "source_only": True,
                      "arrays_opened": False, "jobs_started": False,
                      "outputs": {key: str(value) for key, value in result.items() if key != "worker_sha256"},
                      "worker_sha256": result["worker_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
