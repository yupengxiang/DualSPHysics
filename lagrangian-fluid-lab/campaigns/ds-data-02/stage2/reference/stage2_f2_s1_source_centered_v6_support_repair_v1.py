#!/usr/bin/env python3
"""Prepare a bounded F2-S1 GenCase support/mass repair probe.

The consumed V4/V5 candidates showed that ``setboxlimitmode inner`` did not
keep the fluid centres inside the three frozen source boxes: the generated
product had 37 x 27 x (10, 10, 11) fluid points and a +11.806% whole-owner
mass error.  This forward candidate keeps the source boxes, controls, motion,
and particle mass unchanged, but applies the official ``actual | fluid``
shape-mode mask only while the three fluid boxes are drawn.  The lattice phase
is deliberately retained from the failed V4 product so that a guarded
GenCase-only result isolates shape-mode semantics from phase changes.

This module only writes a new Def/motion copy, a static source-evidence
manifest, and a CPU GenCase request.  It never runs GenCase, a solver, or a
native/HDF5 reader.  The predicted 37 x 25 x 10 count is a diagnostic
expectation; generated.xml/VTK and the parent receipt remain authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.source-centered-v6-support-repair.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
TEMPLATE = REPO / "doc/xml_format/GenCase_CaseTemplate.xml"
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
SOURCE_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_"
    "rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-"
    "gencase-source801-root804/prepared/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010_Def.xml"
)
SOURCE_MOTION = SOURCE_DEF.parent / (
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010_motion.dat"
)
CURRENT_V4_REPORT = DATA_ROOT / (
    "families/F2/F2_S1_SOURCE_CENTERED_INNER_DP0088_NATIVE_GEOMETRY_AUDIT_V4/"
    "f2-s1-source-centered-inner-dp0088-native-geometry-audit-v4-root-forward-001-"
    "root-forward-030-001/report/f2_s1_inner_dp0088_native_geometry_audit_v4.json"
)
INPUT_ROOT = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_inputs/F2_S1/dp0p0088"
CANDIDATE_ID = "F2_S1_SOURCE_CENTERED_V6_ACTUAL_FLUID_DP0P0088"
CANDIDATE_DEF = INPUT_ROOT / f"{CANDIDATE_ID}_Def.xml"
CANDIDATE_MOTION = INPUT_ROOT / SOURCE_MOTION.name
MANIFEST_PATH = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_manifest_v1.json"
AUDIT_PATH = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_audit_v1.json"
REQUEST_DIR = STAGE2 / "requests/stage2-f2-s1-source-centered-v6-support-repair-v1"
REQUEST_PATH = REQUEST_DIR / "f2_s1_source_centered_v6_actual_fluid_dp0p0088_gencase.json"
REQUEST_REPORT = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_request_v1.json"

PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
DP_M = 0.0088
POINTREF = (0.0013, 0.0, 0.0004)
OWNER_LAYER_SIZE = (0.325, 0.22, 0.088)
OWNER_LAYER_COUNT = 3
OWNER_MASS_KG = 18.876
PREDICTED_COUNTS = (37, 25, 10)
PREDICTED_FLUID_COUNT = 3 * PREDICTED_COUNTS[0] * PREDICTED_COUNTS[1] * PREDICTED_COUNTS[2]
PREDICTED_MASS_KG = 1000.0 * DP_M**3 * PREDICTED_FLUID_COUNT


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256(path),
    }


def atomic_bytes(path: Path, payload: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def candidate_bytes() -> bytes:
    source = regular(SOURCE_DEF).read_text(encoding="utf-8")
    if source.count('<definition dp="0.01">') != 1 or "<pointref" in source:
        raise ValueError("unexpected frozen F2 source definition")
    if source.count("<setshapemode>dp | bound</setshapemode>") != 1:
        raise ValueError("expected one frozen boundary shape mode")
    if source.count('<setmkfluid mk="') != 3:
        raise ValueError("expected exactly three frozen fluid draw operations")
    if "<setboxlimitmode" in source:
        raise ValueError("source already contains a box-limit operation")

    value = source.replace(
        '<definition dp="0.01">',
        '<definition dp="0.0088">\n        <pointref x="0.0013" y="0.0000" z="0.0004" />',
        1,
    )
    marker = '          <setmkfluid mk="0" />'
    if value.count(marker) != 1:
        raise ValueError("cannot locate first fluid draw operation")
    value = value.replace(
        marker,
        '          <setshapemode>actual | fluid</setshapemode>\n'
        '          <setboxlimitmode mode="inner" />\n' + marker,
        1,
    )
    close = "        </mainlist>"
    if value.count(close) != 1:
        raise ValueError("expected one mainlist close")
    value = value.replace(
        close,
        '          <setboxlimitmode mode="full" />\n'
        '          <setshapemode>dp | bound</setshapemode>\n' + close,
        1,
    )

    # Prove the new source differs only in the declared dp/pointref and the
    # fluid-local shape/box mode pair.  This is a byte-level source audit, not
    # a claim about the binary's resulting rasterisation.
    normalized_source = source.replace('dp="0.01"', 'dp="<DP>"', 1)
    normalized = value.replace('dp="0.0088"', 'dp="<DP>"', 1)
    normalized = normalized.replace(
        '\n        <pointref x="0.0013" y="0.0000" z="0.0004" />', "", 1
    )
    normalized = normalized.replace(
        '          <setshapemode>actual | fluid</setshapemode>\n'
        '          <setboxlimitmode mode="inner" />\n', "", 1
    )
    normalized = normalized.replace(
        '          <setboxlimitmode mode="full" />\n'
        '          <setshapemode>dp | bound</setshapemode>\n', "", 1
    )
    if normalized != normalized_source:
        raise ValueError("candidate changed frozen source outside declared representation edits")
    ET.fromstring(value)
    return value.encode("utf-8")


def prepare_inputs() -> dict[str, Any]:
    for path in (SOURCE_DEF, SOURCE_MOTION, GENCASE, GENCASE_CONFIG, TEMPLATE, CURRENT_V4_REPORT):
        regular(path)
    atomic_bytes(CANDIDATE_DEF, candidate_bytes())
    atomic_bytes(CANDIDATE_MOTION, regular(SOURCE_MOTION).read_bytes())

    current_v4 = json.loads(CURRENT_V4_REPORT.read_text(encoding="utf-8"))
    if current_v4.get("mass_audit", {}).get("classification") != "HARDFAIL_OVER_TWO_PERCENT":
        raise ValueError("the bound V4 failure report no longer has the expected hard-fail classification")
    observed = current_v4["definition"]
    boxes = current_v4["draw_operations"]
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_V6_ACTUAL_FLUID_SUPPORT_REPAIR_PROBE",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source_def": record(SOURCE_DEF),
        "source_motion": record(SOURCE_MOTION),
        "candidate_def": record(CANDIDATE_DEF),
        "candidate_motion": record(CANDIDATE_MOTION),
        "official_inputs": {
            "gencase_binary": record(GENCASE),
            "gencase_config": record(GENCASE_CONFIG),
            "xml_template": record(TEMPLATE),
            "supported_shape_tokens": ["actual", "real", "dp", "all", "bound", "fluid", "void", "null"],
            "official_help_option": "-threads:<int>",
            "implementation_source": "GenCase implementation source is not present in this checkout; binary symbols/disassembly and official template are bound evidence.",
        },
        "continuous_owner": {
            "layer_low_m": [[0.05, -0.11, 0.70], [0.05, -0.11, 0.788], [0.05, -0.11, 0.876]],
            "layer_size_m": list(OWNER_LAYER_SIZE),
            "layer_count": OWNER_LAYER_COUNT,
            "volume_m3": 0.018876,
            "mass_kg": OWNER_MASS_KG,
            "authority": "frozen CURRENT source fluid drawboxes; candidate does not edit point/size or controls",
        },
        "observed_v4_failure": {
            "report": record(CURRENT_V4_REPORT),
            "dp_m": observed["dp_m"],
            "pointref_m": observed["pointref_m"],
            "fluid_count": observed["fluid_count"],
            "actual_sample_mass_kg": current_v4["mass_audit"]["actual_sample_mass_kg"],
            "relative_error_percent": current_v4["mass_audit"]["relative_error_percent"],
            "axis_counts": [
                current_v4["fluid_blocks"][0]["axis"][axis]["unique_count"] for axis in "xyz"
            ],
            "per_layer_z_counts": [block["axis"]["z"]["unique_count"] for block in current_v4["fluid_blocks"]],
            "outside_closed_box_counts": [block["box_relation"]["outside_closed_count"] for block in current_v4["fluid_blocks"]],
            "outside_reason": "inner box limit did not remove cell-envelope points; y=±0.1144 exceeded ±0.11 and MK3 z=0.9684 exceeded 0.964",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "binary_shape_mode_evidence": {
            "binary": record(GENCASE),
            "read_xml_symbol": "JSpaceDrawOp_SetShapeMode::ReadXml @ 0x6b40c0 calls JMaskText::Eval",
            "run_symbol": "JSpaceDrawOp_SetShapeMode::Run @ 0x6975f0 calls JSpaceDraw::SetShapeMode(int)",
            "setter_symbol": "JSpaceDraw::SetShapeMode(int) @ 0x6ca600 stores the parsed mask",
            "parser_token_masks": {
                "actual": 1,
                "real": 1,
                "dp": 2,
                "bound": 4,
                "fluid": 8,
                "void": 16,
                "all": 28,
                "null": 0,
            },
            "scope": "This proves parser/setter support for actual|fluid in the bound v5.4 binary. It does not prove the resulting particle count or support semantics; the new GenCase receipt must decide those.",
        },
        "candidate_representation": {
            "dp_m": DP_M,
            "pointref_m": list(POINTREF),
            "fluid_shape_mode": "actual | fluid",
            "fluid_box_limit_mode": "inner",
            "restored_shape_mode": "dp | bound",
            "restored_box_limit_mode": "full",
            "drawboxes_unchanged": True,
            "motion_unchanged": True,
            "execution_controls_unchanged": True,
            "mass_rescale": False,
            "phase_isolation": "Retain V4 pointref so any count change is attributable to the fluid-local shape mode, not an unbounded phase sweep.",
        },
        "predicted_diagnostic_only": {
            "axis_counts": list(PREDICTED_COUNTS),
            "per_layer_count": PREDICTED_COUNTS[0] * PREDICTED_COUNTS[1] * PREDICTED_COUNTS[2],
            "fluid_count": PREDICTED_FLUID_COUNT,
            "massfluid_kg": 1000.0 * DP_M**3,
            "sample_mass_kg": PREDICTED_MASS_KG,
            "relative_to_owner_percent": 100.0 * (PREDICTED_MASS_KG / OWNER_MASS_KG - 1.0),
            "status": "PREDICTED_NOT_ACTUAL",
            "authority": "generated.xml, generated_Fluid.vtk, and parent receipt after guarded GenCase",
        },
        "acceptance_and_failure": {
            "preferred_whole_initial_mass_fraction": 0.01,
            "hard_whole_initial_mass_fraction": 0.02,
            "must_check": [
                "actual generated fluid counts and massfluid",
                "per-MK counts/masses and all fluid centres inside the frozen closed boxes",
                "fluid-fluid overlap, boundary identity, and source motion/control hashes",
            ],
            "hard_fail_if": [
                "whole initial mass error exceeds 2%",
                "any fluid centre remains outside a frozen fluid box",
                "candidate changes continuous box coordinates, motion, execution control, or rescales mass",
            ],
            "qualification_until_followup": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "scope": {
            "solver_started": False,
            "gencase_started_by_worker": False,
            "native_payload_read": False,
            "hdf5_read": False,
            "vtk_read": False,
            "source_mutation": False,
        },
    }
    atomic_json(MANIFEST_PATH, manifest)

    audit = {
        "schema": "ds02.stage2.f2-s1.source-centered-v6-support-repair-audit.v1",
        "status": "STATIC_SUPPORT_AND_PHASE_ISOLATION_AUDIT",
        "candidate_manifest": record(MANIFEST_PATH),
        "candidate_def": record(CANDIDATE_DEF),
        "official_binary": record(GENCASE),
        "official_template": record(TEMPLATE),
        "source_def": record(SOURCE_DEF),
        "observed_v4_report": record(CURRENT_V4_REPORT),
        "conclusion": "actual|fluid is accepted by the bound official parser, but exact rasterisation and support remain UNKNOWN until the parent-guarded GenCase-only probe; no CFD eligibility is granted.",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "resource_scope": {"cpu_only": True, "solver_launch": False, "native_read": False, "hdf5_read": False},
    }
    atomic_json(AUDIT_PATH, audit)
    return manifest


def build_request(launch_commit: str) -> dict[str, Any]:
    if not CANDIDATE_DEF.is_file() or not MANIFEST_PATH.is_file() or not AUDIT_PATH.is_file():
        raise FileNotFoundError("run --prepare-inputs before --build-request")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    static = [
        Path(__file__), MANIFEST_PATH, AUDIT_PATH, CANDIDATE_DEF, CANDIDATE_MOTION,
        SOURCE_DEF, SOURCE_MOTION, GENCASE, GENCASE_CONFIG, TEMPLATE,
        DISPATCH, STRICT, RUNTIME,
    ]
    static = list(dict.fromkeys(regular(path) for path in static))
    records = {str(path): record(path) for path in static}
    case_id = CANDIDATE_ID
    attempt_id = "f2-s1-source-centered-v6-actual-fluid-dp0088-gencase-root-forward-001"
    output_root = DATA_ROOT / "families/F2" / case_id / attempt_id
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "launch_commit": launch_commit,
        "command": [str(GENCASE), str(CANDIDATE_DEF.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(CANDIDATE_DEF.parent),
        "worktree_root": str(REPO),
        "input_files": list(records),
        "input_hashes": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "deferred_input_files": [],
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()),
        "estimated_storage_bytes": 512 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": True,
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "output_root": str(output_root),
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "source_binding": {
            "schema": "ds02.stage2.f2-s1.source-centered-v6-support-repair-binding.v1",
            "source_def": records[str(SOURCE_DEF)],
            "source_motion": records[str(SOURCE_MOTION)],
            "candidate_def": records[str(CANDIDATE_DEF)],
            "candidate_motion": records[str(CANDIDATE_MOTION)],
            "official_binary": records[str(GENCASE)],
            "official_config": records[str(GENCASE_CONFIG)],
            "static_audit": records[str(AUDIT_PATH)],
            "observed_v4_failure": manifest["observed_v4_failure"],
            "continuous_owner": manifest["continuous_owner"],
            "candidate_representation": manifest["candidate_representation"],
            "predicted_diagnostic_only": manifest["predicted_diagnostic_only"],
            "post_gencase_required": [
                "generated.xml and execution-receipt.json with stable pre/post SHA/stat",
                "generated_Fluid.vtk or equivalent exact fluid position evidence",
                "per-MK mass/count and closed-box support audit",
            ],
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "native_or_hdf5_read": "forbidden",
            "new_attempt_tree_only": True,
            "refuse_existing_output": True,
        },
        "qualification_stage": "stage2_f2_s1_v6_support_repair_gencase_only_pending_actual_mass_and_support",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_PATH, request)
    report = {
        "schema": "ds02.stage2.f2-s1.source-centered-v6-support-repair-request.v1",
        "status": "PREPARED_GENCЕASE_ONLY_NO_LAUNCH_BY_AGENT",
        "launch_commit": launch_commit,
        "request": record(REQUEST_PATH),
        "candidate": record(CANDIDATE_DEF),
        "manifest": record(MANIFEST_PATH),
        "audit": record(AUDIT_PATH),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_REPORT, report)
    return report


def self_test() -> dict[str, Any]:
    assert PREDICTED_FLUID_COUNT == 27_750
    assert abs(PREDICTED_MASS_KG / OWNER_MASS_KG - 1.0) < 0.01
    assert SOURCE_DEF.is_file() and SOURCE_MOTION.is_file() and TEMPLATE.is_file()
    value = candidate_bytes()
    root = ET.fromstring(value)
    modes = [node.text.strip() for node in root.findall(".//geometry/commands/mainlist/setshapemode")]
    assert modes == ["dp | bound", "actual | fluid", "dp | bound"]
    limits = [node.get("mode") for node in root.findall(".//geometry/commands/mainlist/setboxlimitmode")]
    assert limits == ["inner", "full"]
    return {
        "status": "PASS",
        "candidate_source": "valid_xml",
        "shape_mode_sequence": modes,
        "box_limit_sequence": limits,
        "predicted_fluid_count": PREDICTED_FLUID_COUNT,
        "predicted_mass_kg": PREDICTED_MASS_KG,
        "predicted_status": "NOT_ACTUAL",
        "gencase_started": False,
        "solver_started": False,
        "native_payload_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-inputs", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    selected = sum((args.self_test, args.prepare_inputs, args.build_request))
    if selected != 1:
        parser.error("choose exactly one of --self-test, --prepare-inputs, --build-request")
    if args.self_test:
        value = self_test()
    elif args.prepare_inputs:
        value = prepare_inputs()
    else:
        if not args.launch_commit:
            parser.error("--build-request requires --launch-commit")
        value = build_request(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": value["status"], "path": str(REQUEST_PATH if args.build_request else MANIFEST_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
