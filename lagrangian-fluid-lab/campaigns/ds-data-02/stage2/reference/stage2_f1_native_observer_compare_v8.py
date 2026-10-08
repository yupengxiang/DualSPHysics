#!/usr/bin/env python3
"""Prepare and run the bounded F1 native-observer comparison (v8).

This forward-only worker consumes the five already completed selected-native
observer JSON sidecars and their small RunPARTs/receipt/XML provenance.  It
does not open H5/BI4 data and it never starts a solver.  The two comparisons
are kept separate:

* F1-S1 compares the actual same-CFL and half-CFL saved-time brackets.
* F1-S2 compares the actual coarse, medium, and fine spatial products.

The underlying v1 comparison worker reports endpoint differences.  This
wrapper adds the frozen task scales and tolerance contract, keeps the event
time scale UNKNOWN until an event is declared, and preserves scientific
qualification as UNKNOWN.  Unequal endpoint times remain
``UNKNOWN_TIME_ALIGNMENT``; no field interpolation or adjacent-grid truth is
introduced.

``--build`` creates immutable contract/manifest/request files.  It is meant
to be run after this source is committed, so the generated request binds the
exact source digest.  ``--run`` is the command submitted through the shared
Stage2 v8 CPU guard by the parent process.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f1-native-observer-compare.v8"
CONTRACT_SCHEMA = "ds02.stage2.f1-observer-task-calibration-contract.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-native-observer-compare-manifest.v8"
REQUEST_SCHEMA = "ds02.request.v1"
OBSERVER_SCHEMA = "ds02.stage2.native-physical-observer.v2"
ENFORCER_SCHEMA = "ds02.stage2.native-physical-observer-enforcer.v2"

REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_RESOLVED = PYTHON.resolve()

RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
COMPARE_WORKER = REFERENCE / "stage2_native_observer_empirical_compare_v1.py"
QUALITY = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
S1_AUDIT = REFERENCE / "stage2_f1_s1_geometry_semantics_audit_v2.json"
S2_CONTRACT = REFERENCE / "stage2_f1_s2_reference_contract_v5.json"
ROOT_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_FIVE_NATIVE_OBSERVERS_ACTUAL_INDEPENDENT_VERIFICATION_001.json"

REQUEST_ROOT = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-native-observer-v8-root"
OUTPUT_ROOT = REFERENCE / "stage2-f1-native-observer-compare-v8"
CONTRACT_PATH = OUTPUT_ROOT / "stage2_f1_observer_task_calibration_contract_v1.json"
MANIFEST_PATH = OUTPUT_ROOT / "stage2_f1_native_observer_compare_v8_manifest.json"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-native-observer-compare-v8"


REPORTS: dict[str, Path] = {
    "f1_s1_same_cfl": DATA_ROOT / "families/F1/F1_S1_DP010_SAME_CFL_SELECTED_NATIVE_OBSERVER_V1_CANONICAL_SNAPSHOT_V5/f1_s1_dp010_same_cfl_selected_native_observer_v1-canonical-snapshot-v5-parent-001-root-v8-001/observer/f1_s1_dp010_same_cfl_selected_native_observer_v1_canonical_snapshot_v5.json",
    "f1_s1_half_cfl": DATA_ROOT / "families/F1/F1_S1_DP010_HALF_CFL_SELECTED_NATIVE_OBSERVER_V1_CANONICAL_SNAPSHOT_V5/f1_s1_dp010_half_cfl_selected_native_observer_v1-canonical-snapshot-v5-parent-001-root-v8-001/observer/f1_s1_dp010_half_cfl_selected_native_observer_v1_canonical_snapshot_v5.json",
    "f1_s2_coarse": DATA_ROOT / "families/F1/F1_S2_COARSE_DP0225_SELECTED_NATIVE_OBSERVER_V3_CANONICAL_SNAPSHOT_V5/f1_s2_coarse_dp0225_selected_native_observer_v3-canonical-snapshot-v5-parent-001-root-v8-001/observer/f1_s2_coarse_dp0225_selected_native_observer_v3_canonical_snapshot_v5.json",
    "f1_s2_medium": DATA_ROOT / "families/F1/F1_S2_MEDIUM_DP020_SELECTED_NATIVE_OBSERVER_V2_CANONICAL_SNAPSHOT_V2/f1-s2-medium-dp020-selected-native-observer-v2-canonical-snapshot-v2-parent-001-root-v8-001/observer/f1_s2_medium_dp020_selected_native_observer_v2_canonical_snapshot_v2.json",
    "f1_s2_fine": DATA_ROOT / "families/F1/F1_S2_FINE_DP017_SELECTED_NATIVE_OBSERVER_V2_CANONICAL_SNAPSHOT_V5/f1_s2_fine_dp017_selected_native_observer_v2-canonical-snapshot-v5-parent-001-root-v8-001/observer/f1_s2_fine_dp017_selected_native_observer_v2_canonical_snapshot_v5.json",
}

ROOT_REQUESTS: dict[str, Path] = {
    "f1_s1_same_cfl": REQUEST_ROOT / "f1_s1_dp010_same_cfl_selected_native_observer_v1_canonical_snapshot_v5.json",
    "f1_s1_half_cfl": REQUEST_ROOT / "f1_s1_dp010_half_cfl_selected_native_observer_v1_canonical_snapshot_v5.json",
    "f1_s2_coarse": REQUEST_ROOT / "f1_s2_coarse_dp0225_selected_native_observer_v3_canonical_snapshot_v5.json",
    "f1_s2_fine": REQUEST_ROOT / "f1_s2_fine_dp017_selected_native_observer_v2_canonical_snapshot_v5.json",
    "f1_s2_medium": REQUEST_ROOT / "f1_s2_medium_dp020_selected_native_observer_v2_canonical_snapshot_v2.json",
}

EXPECTED_MANIFESTS: dict[str, Path] = {
    "f1_s1_same_cfl": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-native-observer-canonical-v5-final/f1_s1_dp010_same_cfl_selected_native_observer_v1_expected_source_manifest_v1.json",
    "f1_s1_half_cfl": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-native-observer-canonical-v5-final/f1_s1_dp010_half_cfl_selected_native_observer_v1_expected_source_manifest_v1.json",
    "f1_s2_coarse": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-native-observer-canonical-v5-final/f1_s2_coarse_dp0225_selected_native_observer_v3_expected_source_manifest_v1.json",
    "f1_s2_fine": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-native-observer-canonical-v5-final/f1_s2_fine_dp017_selected_native_observer_v2_expected_source_manifest_v1.json",
    "f1_s2_medium": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s2-medium-observer-canonical-v2/f1_s2_medium_dp020_selected_native_observer_v2_expected_source_manifest_v2.json",
}

RUNPARTS: dict[str, Path] = {
    "f1_s1_same_cfl": DATA_ROOT / "families/F1/F1_S1_ORIGINAL_SAMECFL_DENSE_SAVEDT_V2/f1-s1-samecfl-dense-savedt-v2-primary-001-v5/solver_output/RunPARTs.csv",
    "f1_s1_half_cfl": DATA_ROOT / "families/F1/F1_S1_ORIGINAL_HALFCFL_DENSE_SAVEDT_V2/f1-s1-halfcfl-dense-savedt-v2-primary-001-v5/solver_output/RunPARTs.csv",
    "f1_s2_coarse": DATA_ROOT / "families/F1/F1_S2_SPATIAL_COARSE_DP0p022500_FULL4S_SAMECFL_SAVEDT/f1-s2-coarse-dp0225-samecfl-full4s-savedt-v6-primary-001/solver_output/RunPARTs.csv",
    "f1_s2_fine": DATA_ROOT / "families/F1/F1_S2_INTERVAL_DP0p017_FULL4S_SAMECFL_SAVEDT_DENSE/f1-s2-fine-dp017-samecfl-full4s-savedt-v5-primary-001/solver_output/RunPARTs.csv",
    "f1_s2_medium": DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-physical-endpoint-full-native-gpu-lease-retry-034/solver_output/RunPARTs.csv",
}

GENERATED_XML: dict[str, Path] = {
    "f1_s1_same_cfl": DATA_ROOT / "families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE.xml",
    "f1_s1_half_cfl": DATA_ROOT / "families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE.xml",
    "f1_s2_coarse": DATA_ROOT / "families/F1/F1_S2_SPATIAL_COARSE_DP0p022500/f1-s2-spatial-coarse-dp0p022500-v5-primary-001/generated.xml",
    "f1_s2_fine": DATA_ROOT / "families/F1/F1_S2_SPATIAL_INTERVAL_DP0p017000/f1-s2-spatial-interval-dp0p017000-v2-primary-001/generated.xml",
    "f1_s2_medium": DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml",
}

SOLVER_RECEIPTS: dict[str, Path] = {
    label: path.parent.parent / "execution-receipt.json" for label, path in RUNPARTS.items()
}

def gencase_receipt_for(xml: Path) -> Path:
    """Resolve both prepared/XML and generated/XML producer layouts."""
    direct = xml.parent / "execution-receipt.json"
    if direct.is_file():
        return direct
    return xml.parent.parent / "execution-receipt.json"


GENCASE_RECEIPTS: dict[str, Path] = {
    label: gencase_receipt_for(xml) for label, xml in GENERATED_XML.items()
}

GROUPS: dict[str, dict[str, Any]] = {
    "f1_s1_same_half": {
        "sentinel_id": "F1-S1",
        "family_id": "F1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "labels": ["f1_s1_same_cfl", "f1_s1_half_cfl"],
        "query_times_s": [0.0, 0.4, 0.8, 1.2, 1.6],
        "common_saved_time_intersection_s": [0.0, 1.600039573589642],
        "characteristic_length": {
            "value_m": 0.67,
            "basis": "F1-S1 owner continuous fluid box maximum span from exact owner binding size [0.4,0.67,0.15] m",
            "event_local_geometry_m": 0.12,
            "event_local_geometry_status": "DIAGNOSTIC_ONLY_UNTIL_EVENT_DECLARATION",
        },
        "initial_fluid_sample_mass_target_kg": 40.2,
        "continuous_mass_status": "OWNER_AUTHORITY_40P2_KG; PARTICLE_SUM_IS_DISCRETE_OBSERVABLE",
        "controls": {
            "source_xml": "same exact CURRENT XML and referenced motion/control inputs",
            "same_cfl": 0.2,
            "half_cfl": 0.1,
            "savedt_all": 1,
            "savedt_interval_s": 0.005,
            "physical_window_s": [0.0, 1.6],
            "actual_saved_endpoint_policy": "Use RunPARTs endpoint; query 1.6 is bracketed when not an exact saved row",
        },
        "event_characteristic_time": "UNKNOWN_UNTIL_EVENT_DECLARATION",
        "output_time_policy": "actual RunPARTs brackets only; no interpolation",
    },
    "f1_s2_three_grid": {
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "labels": ["f1_s2_coarse", "f1_s2_medium", "f1_s2_fine"],
        "query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0],
        "common_saved_time_intersection_s": [0.0, 4.000039181464766],
        "characteristic_length": {
            "value_m": 0.98,
            "basis": "F1-S2 source fluid box maximum span [0.98,0.98,0.32] m; continuous-mass authority remains separate",
            "global_channel_span_m": 3.3,
            "divider_size_m": [0.8, 0.8, 0.8],
        },
        "initial_fluid_sample_mass_target_kg": 340.0,
        "continuous_mass_status": "UNKNOWN_CONTINUOUS_AUTHORITY; 340_KG_IS_SOURCE_DISCRETE_SAMPLE_TARGET",
        "controls": {
            "source_xml": "same mother geometry/fill/motion/control semantics; intentional dp/h/mass/count vary by grid",
            "same_cfl": 0.2,
            "savedt_all": 1,
            "savedt_interval_s": 0.005,
            "medium_native_output_interval_s": 0.01,
            "physical_window_s": [0.0, 4.0],
            "actual_saved_endpoint_policy": "Use each RunPARTs endpoint; query 4.0 may be exact/bracketed depending on actual saved rows",
        },
        "spatial_grid_roles": {
            "coarse": {"dp_m": 0.0225, "role": "actual coarse source; mass target audit remains separate"},
            "medium": {"dp_m": 0.02, "role": "actual CURRENT source"},
            "fine": {"dp_m": 0.017, "role": "actual fine source; mass target audit remains separate"},
        },
        "event_characteristic_time": "UNKNOWN_UNTIL_EVENT_DECLARATION",
        "output_time_policy": "actual RunPARTs brackets only; medium output cadence differs and is diagnostic, not truth",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def xml_control_summary(path: Path) -> dict[str, Any]:
    """Parse only the small generated XML; never open native particle data."""
    import xml.etree.ElementTree as ET

    root = ET.parse(regular_file(path, "generated XML")).getroot()
    local = lambda tag: tag.rsplit("}", 1)[-1]
    definition = next((node for node in root.iter() if local(node.tag) == "definition"), None)
    particles = next((node for node in root.iter() if local(node.tag) == "particles"), None)
    parameters = {
        node.get("key"): node.get("value")
        for node in root.iter()
        if local(node.tag) == "parameter" and node.get("key")
    }
    fluid_blocks = []
    if particles is not None:
        for node in particles:
            if local(node.tag) != "fluid":
                continue
            fluid_blocks.append({key: node.get(key) for key in ("mkfluid", "mk", "begin", "count", "massfluid")})
    return {
        "definition_dp_m": float(definition.get("dp")) if definition is not None and definition.get("dp") else None,
        "fluid_blocks": fluid_blocks,
        "parameters": {
            key: parameters.get(key)
            for key in ("TimeMax", "TimeOut", "DtMin", "DtFixed", "DtAllParticles", "Kernel", "ViscoTreatment", "DensityDT", "Shifting")
            if key in parameters
        },
    }


def actual_manifest_for(label: str, report: dict[str, Any]) -> dict[str, Any]:
    manifest = read_json(EXPECTED_MANIFESTS[label], "expected source manifest")
    expected = {
        "family_id": "F1",
        "sentinel_id": "F1-S1" if label.startswith("f1_s1") else "F1-S2",
        "physical_case_id": GROUPS["f1_s1_same_half" if label.startswith("f1_s1") else "f1_s2_three_grid"]["physical_case_id"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"{label}: expected manifest {key} mismatch")
    selected = manifest.get("selected_native_frame_ids")
    if selected != report.get("source", {}).get("selected_frames"):
        raise ValueError(f"{label}: manifest/report selected-frame mismatch")
    integrity = report.get("source_integrity")
    if not isinstance(integrity, dict) or integrity.get("schema") != ENFORCER_SCHEMA:
        raise ValueError(f"{label}: missing enforcer v2 source integrity")
    if integrity.get("status") != "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT":
        raise ValueError(f"{label}: source enforcer is not PASS")
    if integrity.get("pre_post_sha_and_stat_equal") is not True or integrity.get("cross_decode_stat_boundaries_equal") is not True:
        raise ValueError(f"{label}: source pre/post digest/stat gate is not PASS")
    expected_path = str(EXPECTED_MANIFESTS[label].resolve())
    if str(integrity.get("expected_manifest")) != expected_path:
        raise ValueError(f"{label}: report expected-manifest path mismatch")
    return manifest


def validate_report(label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    report = read_json(REPORTS[label], "native observer report")
    if report.get("schema") != OBSERVER_SCHEMA or report.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"{label}: observer report is not a decoded selected-native PASS")
    scope = report.get("scope")
    if not isinstance(scope, dict):
        raise ValueError(f"{label}: observer scope is absent")
    for key in ("full_native_tree_scanned", "hdf5_read", "typed_conversion", "particle_field_interpolation"):
        if key == "full_native_tree_scanned" and scope.get(key) is not False:
            raise ValueError(f"{label}: full native tree scan was not false")
        if key == "hdf5_read" and scope.get(key) is not False:
            raise ValueError(f"{label}: H5 read scope is not false")
        if key in {"typed_conversion", "particle_field_interpolation"} and scope.get(key) not in {"NOT_PERFORMED", "NOT_PERFORMED_BY_WORKER"}:
            raise ValueError(f"{label}: unexpected conversion/interpolation scope: {scope.get(key)}")
    manifest = actual_manifest_for(label, report)
    report_runparts = report.get("source", {}).get("runparts", {})
    if report_runparts.get("path") != str(RUNPARTS[label].resolve()):
        raise ValueError(f"{label}: report RunPARTs path mismatch")
    if report_runparts.get("sha256") != sha256(RUNPARTS[label]):
        raise ValueError(f"{label}: report RunPARTs digest mismatch")
    if report.get("source", {}).get("generated_xml", {}).get("path") != str(GENERATED_XML[label].resolve()):
        raise ValueError(f"{label}: report generated XML path mismatch")
    return report, manifest


def overlay_xml_paths(solver_receipt: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            path_value = value.get("path")
            if isinstance(path_value, str) and path_value.lower().endswith(".xml"):
                paths.append(Path(path_value))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(solver_receipt.get("request", {}))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if str(resolved) not in seen:
            seen.add(str(resolved))
            unique.append(resolved)
    return unique


def build_contract() -> dict[str, Any]:
    return {
        "schema": CONTRACT_SCHEMA,
        "status": "PREREGISTERED_CALIBRATION_ONLY",
        "preparation_source_commit": git_head(),
        "quality_source": str(QUALITY.resolve()),
        "quality_source_semantics": {
            "position_macro_rmse": "<= 2% characteristic L",
            "event_position": "<= 5% characteristic L",
            "velocity_or_ke": "<= 5% fixed nonzero scale",
            "whole_initial_region_mass_or_flux": "<= 0.03 fraction of whole initial source mass (three percentage points)",
            "event_time": "<= 1% task-specific characteristic T; T is UNKNOWN until event declaration",
            "time_budget_share": "at most one quarter of the corresponding task gate; budget share, not automatic pass/fail",
            "output_reconstruction_budget_share": "at most one quarter of the corresponding task gate; budget share, not automatic pass/fail",
        },
        "comparison_policy": {
            "field_interpolation": "NOT_PERFORMED",
            "query_alignment": "only exact actual saved-time endpoints are aligned; unequal endpoint times are UNKNOWN_TIME_ALIGNMENT",
            "adjacent_grid_as_truth": "FORBIDDEN",
            "common_time_axis_is_event_time": False,
            "event_characteristic_time": "UNKNOWN_UNTIL_EVENT_DECLARATION",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "velocity_scale_method": {
            "formula": "sqrt(abs(g_m_per_s2) * L_position_m)",
            "gravity_m_per_s2": -9.81,
            "status": "REGISTERED_SCALE_ONLY_NOT_EVALUATED",
        },
        "groups": {
            group_id: {
                "sentinel_id": spec["sentinel_id"],
                "physical_case_id": spec["physical_case_id"],
                "query_times_s": spec["query_times_s"],
                "common_saved_time_intersection_s": spec["common_saved_time_intersection_s"],
                "characteristic_length": spec["characteristic_length"],
                "event_characteristic_time": spec["event_characteristic_time"],
                "initial_fluid_sample_mass_target_kg": spec["initial_fluid_sample_mass_target_kg"],
                "continuous_mass_status": spec["continuous_mass_status"],
                "controls": spec["controls"],
                "output_time_policy": spec["output_time_policy"],
                "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            }
            for group_id, spec in GROUPS.items()
        },
    }


def build_manifest(contract: dict[str, Any]) -> tuple[dict[str, Any], list[Path]]:
    runs: dict[str, Any] = {}
    input_paths: list[Path] = []
    for label, report_path in REPORTS.items():
        report, expected_manifest = validate_report(label)
        solver_receipt = read_json(SOLVER_RECEIPTS[label], "solver receipt")
        gencase_receipt = read_json(GENCASE_RECEIPTS[label], "GenCase receipt")
        root_request = read_json(ROOT_REQUESTS[label], "root v8 observer request")
        expected_group = GROUPS["f1_s1_same_half" if label.startswith("f1_s1") else "f1_s2_three_grid"]
        if root_request.get("physical_case_id") != expected_group["physical_case_id"]:
            raise ValueError(f"{label}: root request physical identity mismatch")
        if root_request.get("selected_native_frame_ids") != expected_manifest.get("selected_native_frame_ids"):
            raise ValueError(f"{label}: root request/manifest frame mismatch")
        if root_request.get("query_times_s") != expected_group["query_times_s"]:
            raise ValueError(f"{label}: root request/query axis mismatch")
        overlay_paths = overlay_xml_paths(solver_receipt)
        for path in overlay_paths:
            regular_file(path, "solver control overlay XML")
        runs[label] = {
            "label": label,
            "physical_case_id": expected_group["physical_case_id"],
            "observer_report": record(report_path, "observer report"),
            "root_v8_request": record(ROOT_REQUESTS[label], "root v8 request"),
            "expected_source_manifest": record(EXPECTED_MANIFESTS[label], "expected source manifest"),
            "runparts": record(RUNPARTS[label], "RunPARTs"),
            "solver_receipt": record(SOLVER_RECEIPTS[label], "solver receipt"),
            "gencase_receipt": record(GENCASE_RECEIPTS[label], "GenCase receipt"),
            "generated_xml": record(GENERATED_XML[label], "generated XML"),
            "control_overlay_xml": [record(path, "solver control overlay XML") for path in overlay_paths],
            "xml_control_summary": xml_control_summary(GENERATED_XML[label]),
            "selected_native_frame_ids": expected_manifest["selected_native_frame_ids"],
            "query_times_s": expected_manifest.get("selected_native_frame_ids") and expected_group["query_times_s"],
            "last_saved_time_s": root_request["source_binding"]["last_saved_time_s"],
            "selected_native_metadata_only": {
                "records": report["source"].get("selected_part_records", []),
                "read_policy": "metadata copied from completed observer sidecar; this compare does not open/stat/hash BI4",
            },
            "enforcer_v2": {
                "schema": report["source_integrity"]["schema"],
                "status": report["source_integrity"]["status"],
                "pre_post_sha_and_stat_equal": report["source_integrity"].get("pre_post_sha_and_stat_equal"),
                "cross_decode_stat_boundaries_equal": report["source_integrity"].get("cross_decode_stat_boundaries_equal"),
                "full_raw_tree_scan": False,
                "hdf5_read": False,
            },
            "solver_effective_control_source": {
                "receipt_request_effective_conditions": solver_receipt.get("request", {}).get("effective_conditions", solver_receipt.get("request", {}).get("dt_contract", "UNKNOWN")),
                "receipt_command": solver_receipt.get("request", {}).get("command"),
                "status": solver_receipt.get("status"),
                "returncode": solver_receipt.get("returncode"),
                "source_control_credit": "receipt/overlay/XML bound; scientific qualification remains UNKNOWN",
            },
            "mass_semantics": report.get("mass_semantics"),
        }
        input_paths.extend([report_path, ROOT_REQUESTS[label], EXPECTED_MANIFESTS[label], RUNPARTS[label], SOLVER_RECEIPTS[label], GENCASE_RECEIPTS[label], GENERATED_XML[label], *overlay_paths])
    input_paths.extend([S1_AUDIT, S2_CONTRACT, QUALITY, ROOT_PROOF])
    input_paths = list(dict.fromkeys(path.expanduser().resolve() for path in input_paths))
    for path in input_paths:
        regular_file(path, "manifest input")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ACTUAL_V8_SELECTED_NATIVE_COMPARE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "preparation_source_commit": git_head(),
        "contract": record(CONTRACT_PATH, "task calibration contract"),
        "root_independent_verification": record(ROOT_PROOF, "root independent verification"),
        "scope": {
            "observer_reports": 5,
            "groups": {group_id: {"labels": spec["labels"], "physical_case_id": spec["physical_case_id"], "query_times_s": spec["query_times_s"]} for group_id, spec in GROUPS.items()},
            "runparts_revalidated_by_worker": True,
            "hdf5_read": False,
            "bi4_read": False,
            "native_source_tree_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "field_interpolation": "NOT_PERFORMED",
            "adjacent_grid_as_truth": False,
        },
        "runs": runs,
        "input_path_policy": "Only JSON/CSV/XML/receipt/proof sidecars listed as inputs; BI4/H5 are metadata-only path records in existing sidecars and are never opened by this worker",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return manifest, input_paths


def make_request(group_id: str, contract: dict[str, Any], input_paths: list[Path]) -> dict[str, Any]:
    spec = GROUPS[group_id]
    short = "s1" if group_id == "f1_s1_same_half" else "s2"
    case_id = f"F1_{short.upper()}_NATIVE_OBSERVER_EMPIRICAL_COMPARE_V8"
    attempt_id = f"f1-{short}-native-observer-empirical-compare-v8-root-001"
    output_name = f"{group_id}_empirical_compare_v8.json"
    all_inputs = [
        Path(__file__), COMPARE_WORKER, CONTRACT_PATH, MANIFEST_PATH,
        RUNNER, STRICT, RUNTIME, V6_RUNTIME, PYTHON_RESOLVED,
        S1_AUDIT, S2_CONTRACT, QUALITY, ROOT_PROOF,
        *input_paths,
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in all_inputs:
        resolved = path.expanduser().resolve()
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        if resolved.suffix.lower() in {".bi4", ".h5", ".hdf5"}:
            raise ValueError(f"native/H5 data cannot be a compare input: {resolved}")
        regular_file(resolved, "compare request input")
        unique.append(resolved)
    output = f"{{attempt_root}}/comparison/{output_name}"
    command = [
        str(PYTHON), str(Path(__file__).resolve()), "--run",
        "--comparison-id", group_id,
        "--manifest", str(MANIFEST_PATH.resolve()),
        "--contract", str(CONTRACT_PATH.resolve()),
        "--output", output,
    ]
    return {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": spec["family_id"],
        "sentinel_id": spec["sentinel_id"],
        "physical_case_id": spec["physical_case_id"],
        "case_id": case_id,
        "attempt_id": attempt_id,
        "command": command,
        "cwd": str(MAIN.resolve()),
        "worktree_root": str(MAIN.resolve()),
        "input_files": [str(path) for path in unique],
        "input_hashes": {str(path): sha256(path) for path in unique},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_native_read_bytes": 0,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": output,
            "scope": "small comparison JSON only",
        },
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "cfd_invoked": False,
        "hdf5_read": False,
        "bi4_read": False,
        "deferred_input_files": [],
        "source_binding": {
            "manifest": str(MANIFEST_PATH.resolve()),
            "contract": str(CONTRACT_PATH.resolve()),
            "group_id": group_id,
            "observer_labels": spec["labels"],
            "query_times_s": spec["query_times_s"],
            "common_saved_time_intersection_s": spec["common_saved_time_intersection_s"],
            "field_interpolation": "NOT_PERFORMED",
            "unequal_saved_times": "UNKNOWN_TIME_ALIGNMENT",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(RUNNER.resolve()),
            "strict_guard": str(STRICT.resolve()),
            "runtime": str(RUNTIME.resolve()),
            "v6_runtime": str(V6_RUNTIME.resolve()),
            "parent_cpu_guard_required": True,
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
        },
        "qualification_stage": "stage2_actual_selected_native_empirical_compare_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "comparison_contract": {
            "characteristic_length_m": contract["groups"][group_id]["characteristic_length"]["value_m"],
            "event_characteristic_time": "UNKNOWN_UNTIL_EVENT_DECLARATION",
            "tolerance_source": str(QUALITY.resolve()),
            "time_and_output_are_budget_shares_not_pass_fail": True,
        },
    }


def build() -> dict[str, Any]:
    if OUTPUT_ROOT.exists() and any(OUTPUT_ROOT.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty output directory: {OUTPUT_ROOT}")
    if REQUEST_DIR.exists() and any(REQUEST_DIR.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty request directory: {REQUEST_DIR}")
    contract = build_contract()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(CONTRACT_PATH, contract)
    manifest, input_paths = build_manifest(contract)
    # The manifest binds the already written contract; no circular request data is used.
    atomic_json(MANIFEST_PATH, manifest)
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    request_paths: list[str] = []
    requests: dict[str, Any] = {}
    for group_id in GROUPS:
        request = make_request(group_id, contract, input_paths)
        path = REQUEST_DIR / f"{group_id}_empirical_compare_v8.json"
        atomic_json(path, request)
        request_paths.append(str(path.resolve()))
        requests[group_id] = {"path": str(path.resolve()), "sha256": sha256(path)}
    index = {
        "schema": "ds02.stage2.f1-native-observer-compare-v8-index",
        "status": "PREPARED_PARENT_V8_CPU_AUDIT_REQUESTS",
        "contract": record(CONTRACT_PATH, "task calibration contract"),
        "manifest": record(MANIFEST_PATH, "comparison manifest"),
        "requests": requests,
        "scope": "No solver/GPU/H5/BI4; actual observer sidecars and small provenance only",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_DIR / "index.json", index)
    return {"contract": str(CONTRACT_PATH), "manifest": str(MANIFEST_PATH), "requests": request_paths}


def import_worker():
    module_name = "ds02_stage2_native_observer_empirical_compare_v1_runtime"
    spec = importlib.util.spec_from_file_location(module_name, COMPARE_WORKER)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load comparison worker: {COMPARE_WORKER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def verify_manifest_records(manifest: dict[str, Any], expected_contract_path: Path) -> None:
    contract_record = manifest.get("contract")
    if not isinstance(contract_record, dict) or contract_record.get("path") != str(expected_contract_path.resolve()):
        raise ValueError("manifest contract binding is wrong")
    for record_group in manifest.get("runs", {}).values():
        for key in ("observer_report", "root_v8_request", "expected_source_manifest", "runparts", "solver_receipt", "gencase_receipt", "generated_xml"):
            item = record_group.get(key)
            if not isinstance(item, dict):
                raise ValueError(f"manifest run is missing record {key}")
            path = regular_file(Path(item["path"]), f"manifest {key}")
            if sha256(path) != item.get("sha256") or path.stat().st_size != item.get("bytes") or path.stat().st_mtime_ns != item.get("mtime_ns"):
                raise ValueError(f"manifest input changed: {path}")
        for item in record_group.get("control_overlay_xml", []):
            path = regular_file(Path(item["path"]), "manifest control overlay")
            if sha256(path) != item.get("sha256") or path.stat().st_size != item.get("bytes") or path.stat().st_mtime_ns != item.get("mtime_ns"):
                raise ValueError(f"manifest control overlay changed: {path}")


def run_compare(group_id: str, manifest_path: Path, contract_path: Path, output: Path) -> dict[str, Any]:
    if group_id not in GROUPS:
        raise ValueError(f"unknown comparison group: {group_id}")
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable comparison: {output}")
    manifest = read_json(manifest_path, "comparison manifest")
    contract = read_json(contract_path, "task calibration contract")
    if manifest.get("schema") != MANIFEST_SCHEMA or contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("comparison manifest/contract schema mismatch")
    verify_manifest_records(manifest, contract_path)
    spec = GROUPS[group_id]
    labels = spec["labels"]
    run_records = manifest.get("runs", {})
    observer_paths = []
    for label in labels:
        if label not in run_records:
            raise ValueError(f"manifest lacks group run: {label}")
        observer_paths.append(Path(run_records[label]["observer_report"]["path"]))
        # This validates current sidecar status, expected manifest identity, and
        # RunPARTs digest without opening any native frame.
        validate_report(label)
    worker = import_worker()
    if output.parent.exists() and any(output.parent.iterdir()):
        # Existing output is the only immutable product that matters; other
        # parent files (stdout/receipt) are created by the shared runtime.
        pass
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + f".staging-{os.getpid()}")
    if staging.exists():
        raise FileExistsError(f"staging output already exists: {staging}")
    result = worker.build_report(observer_paths, staging,
                                 characteristic_length_m=spec["characteristic_length"]["value_m"],
                                 characteristic_time_s=None,
                                 expected_physical_case_id=spec["physical_case_id"])
    staging.unlink(missing_ok=True)
    result["schema"] = SCHEMA
    result["status"] = "PASS_EMPIRICAL_BRACKETED_COMPARISON_SCIENTIFIC_QUALIFICATION_UNKNOWN"
    result["comparison_group"] = group_id
    result["task_tolerance_contract"] = contract["groups"][group_id]
    result["frozen_quality_budget"] = contract["quality_source_semantics"]
    result["comparison_scope"].update({
        "source_manifest_records": {label: run_records[label]["expected_source_manifest"] for label in labels},
        "root_v8_request_records": {label: run_records[label]["root_v8_request"] for label in labels},
        "actual_solver_receipt_records": {label: run_records[label]["solver_receipt"] for label in labels},
        "actual_generated_xml_records": {label: run_records[label]["generated_xml"] for label in labels},
        "actual_query_policy": "RunPARTs-backed EXACT/EXACT_OR_LEFT/BRACKETED only",
        "event_characteristic_time": "UNKNOWN_UNTIL_EVENT_DECLARATION",
        "time_and_output_budget_semantics": "budget shares only; not evaluated by this worker",
        "native_source_mutation_gate": "already PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT in each input observer sidecar",
    })
    result["source_control_binding"] = {
        label: run_records[label]["solver_effective_control_source"] for label in labels
    }
    result["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    atomic_json(output, result)
    return result


def self_test() -> dict[str, Any]:
    worker = import_worker()
    worker_result = worker.manufactured_self_test()
    assert worker_result["status"] == "PASS"
    assert all(Path(path).suffix.lower() not in {".bi4", ".h5", ".hdf5"} for path in [str(COMPARE_WORKER), str(CONTRACT_PATH)])
    return {
        "status": "PASS",
        "comparison_worker_manufactured_semantics": worker_result,
        "native_source_read": False,
        "hdf5_read": False,
        "bi4_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--comparison-id", choices=tuple(GROUPS))
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.build:
        print(json.dumps(build(), ensure_ascii=False, indent=2))
        return 0
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.comparison_id is None or args.output is None:
        parser.error("--run requires --comparison-id and --output")
    result = run_compare(args.comparison_id, args.manifest, args.contract, args.output)
    print(json.dumps({"status": result["status"], "comparison_group": args.comparison_id,
                      "output": str(args.output.resolve()), "comparison_count": len(result["comparisons"]),
                      "hdf5_read": False, "bi4_read": False, "scientific_qualification": result["scientific_qualification"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
