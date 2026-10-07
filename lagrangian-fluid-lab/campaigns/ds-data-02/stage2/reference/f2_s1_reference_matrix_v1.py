#!/usr/bin/env python3
"""Prepare a source-bound F2-S1 reference reuse matrix.

The matrix is a bounded preparation/audit artifact.  It reads exact existing
XML, RunPARTs, conversion reports, native frame-zero files, and the existing
dense-save telemetry.  It records the typed HDF5 producer SHA and stat without
rehashing the large HDF5.  Existing RV4EQ candidates are kept as reusable
evidence with their configuration differences visible; they are never
relabelled as strict F2-S1 matches.

No GenCase, solver, PartVTK, full-time HDF5 read, or observer result is run by
this module.  Gap requests are parent-review templates with launch disabled.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Mapping


SCHEMA = "ds02.stage2.f2-s1.reference-matrix.v1"
GAP_SCHEMA = "ds02.stage2.f2-s1.reference-gap-request.v2"
REQUEST_SCHEMA = "ds02.request.v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
VENV_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
REFERENCE_PLAN = Path(__file__).resolve().parents[1] / "../families/F2/integration_save_plan.json"
LEGACY_MATRIX = Path(__file__).resolve().parents[1] / "../families/F2/definitions/reference_matrix.json"
QUALITY_LABELS = Path(__file__).resolve().parents[1] / "review-source/QUALITY_LABEL_SPLIT_ZH.md"
PREFLIGHT_SCRIPT = Path(__file__).with_name("f2_s1_gencase_preflight_v1.py")
PREFLIGHT_INPUT_ROOT = Path(__file__).with_name("f2_s1_preflight_inputs")
PREFLIGHT_MANIFEST = PREFLIGHT_INPUT_ROOT / "manifest.json"
PREFLIGHT_REQUEST_DIR = Path(__file__).resolve().parents[1] / "requests/f2-s1-gencase-preflight-v3"
INITIAL_OUTPUT = DATA_ROOT / "families/F2/F2_S1_INITIAL_FRAME_EQUIV_V2_3/initial-frame-equivalence-v2-3-001/initial-frame-check.json"
INITIAL_RECEIPT = DATA_ROOT / "families/F2/F2_S1_INITIAL_FRAME_EQUIV_V2_3/initial-frame-equivalence-v2-3-001/execution-receipt.json"

F2_ROOT = DATA_ROOT / "families/F2"
CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "resolution": "coarse",
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
        "xml": F2_ROOT / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010.xml",
        "report": F2_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-matched-spatial-fulltyped-nvme-003/conversion-report.json",
        "observations": F2_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-labels-v2-012/f2-v6-observations.json",
        "rigid_state": F2_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-pose-v1-011/rigid-body-state.json",
        "dense_save_report": None,
    },
    {
        "resolution": "medium",
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
        "xml": F2_ROOT / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010.xml",
        "report": F2_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-matched-spatial-fulltyped-nvme-003/conversion-report.json",
        "observations": F2_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-labels-v2-012/f2-v6-observations.json",
        "rigid_state": F2_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-pose-v1-011/rigid-body-state.json",
        "dense_save_report": None,
    },
    {
        "resolution": "fine",
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
        "xml": F2_ROOT / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.xml",
        "report": F2_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005/conversion-report.json",
        "observations": F2_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/root-offset-fine-actual-native-labels-v1-015/f2-v6-observations.json",
        "rigid_state": F2_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/root-offset-fine-actual-native-pose-v1-013/rigid-body-state.json",
        "dense_save_report": None,
    },
    {
        "resolution": "fine_dense_save001",
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001",
        "xml": F2_ROOT / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.xml",
        "report": F2_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-dense-full4001-typed-nvme-conversion-020/conversion-report.json",
        "observations": F2_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-full4001-frozen-events-native-weights-025/observations.json",
        "rigid_state": F2_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-full4001-actual-pose-13-bitwise-payload-singlecopy-022/pose-payload-report.json",
        "dense_save_report": F2_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-dense-full4001-native-save-allocation-021/native-save-report.json",
    },
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def file_record(path: Path, *, digest: bool = True) -> dict[str, Any]:
    require_file(path, "source")
    stat = path.stat()
    result: dict[str, Any] = {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if digest:
        result["sha256"] = sha256_file(path)
    return result


def scalar(element: ET.Element) -> Any:
    value = element.get("v")
    if value is None:
        return None
    tag = element.tag.split("}")[-1].lower()
    if tag in {"bool", "boolean"}:
        return value.lower() in {"1", "true", "yes"}
    if tag in {"int", "uint", "int32", "uint32", "int64", "uint64", "long", "ullong", "llong"}:
        try:
            return int(value)
        except ValueError:
            return value
    if tag in {"float", "double", "real"}:
        try:
            return float(value)
        except ValueError:
            return value
    return value


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    constants = {child.tag.split("}")[-1]: dict(child.attrib) for child in root.findall(".//execution/constants/*")}
    parameters = {
        child.attrib["key"]: child.attrib.get("value")
        for child in root.findall(".//execution/parameters/parameter")
        if child.attrib.get("key")
    }
    blocks = []
    for child in root.findall(".//execution/particles/*"):
        if child.tag.split("}")[-1] == "_summary":
            continue
        blocks.append({"tag": child.tag.split("}")[-1], **dict(child.attrib)})
    return {"constants": constants, "parameters": parameters, "particle_blocks": blocks}


def _attrs(element: ET.Element | None) -> dict[str, str]:
    return dict(element.attrib) if element is not None else {}


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def physical_condition_xml(path: Path) -> dict[str, Any]:
    """Extract the physical draw/fill/motion recipe without reading particle data."""
    root = ET.parse(path).getroot()
    casedef = root.find("casedef")
    geometry = casedef.find("geometry") if casedef is not None else None
    definition = geometry.find("definition") if geometry is not None else None
    commands = geometry.find("commands/mainlist") if geometry is not None else None
    boundary_draws: list[dict[str, Any]] = []
    fluid_draws: list[dict[str, Any]] = []
    active_kind: str | None = None
    active_mk: str | None = None
    if commands is not None:
        for command in commands:
            tag = command.tag.split("}")[-1]
            if tag == "setmkbound":
                active_kind, active_mk = "bound", command.attrib.get("mk")
                continue
            elif tag == "setmkfluid":
                active_kind, active_mk = "fluid", command.attrib.get("mk")
                continue
            elif tag != "drawbox":
                continue
            boxfill = command.find("boxfill")
            point = command.find("point")
            size = command.find("size")
            layers = command.find("layers")
            record = {
                "mk": active_mk,
                "fill": _text(boxfill),
                "point": _attrs(point),
                "size": _attrs(size),
                "layers": _attrs(layers),
            }
            (boundary_draws if active_kind == "bound" else fluid_draws).append(record)
    motion = casedef.find("motion") if casedef is not None else None
    begin = motion.find("objreal/begin") if motion is not None else None
    rotation = motion.find("objreal/mvrotfile") if motion is not None else None
    axis1 = rotation.find("axisp1") if rotation is not None else None
    axis2 = rotation.find("axisp2") if rotation is not None else None
    motion_contract = {
        "reference": motion.find("objreal").attrib.get("ref") if motion is not None and motion.find("objreal") is not None else None,
        "begin": _attrs(begin),
        "rotation": {
            "id": rotation.attrib.get("id") if rotation is not None else None,
            "duration": rotation.attrib.get("duration") if rotation is not None else None,
            "anglesunits": rotation.attrib.get("anglesunits") if rotation is not None else None,
            "file_name": rotation.find("file").attrib.get("name") if rotation is not None and rotation.find("file") is not None else None,
            "axis_p1": _attrs(axis1),
            "axis_p2": _attrs(axis2),
        },
    }
    particles = root.find("execution/particles")
    summary = particles.find("_summary") if particles is not None else None
    fluid_blocks = [
        {"mkfluid": node.attrib.get("mkfluid"), "mk": node.attrib.get("mk"), "begin": node.attrib.get("begin"), "count": node.attrib.get("count")}
        for node in (particles.findall("fluid") if particles is not None else [])
    ]
    return {
        "geometry_definition": {
            "dp": definition.attrib.get("dp") if definition is not None else None,
            "pointmin": _attrs(definition.find("pointmin") if definition is not None else None),
            "pointmax": _attrs(definition.find("pointmax") if definition is not None else None),
        },
        "boundary_draws": boundary_draws,
        "fluid_fill_draws": fluid_draws,
        "motion": motion_contract,
        "particle_initialization": {
            "summary": {
                key: summary.find(key).attrib if summary is not None and summary.find(key) is not None else None
                for key in ("positions", "fixed", "moving", "fluid")
            },
            "fluid_blocks": fluid_blocks,
        },
    }


def physical_control_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    constants = {child.tag.split("}")[-1]: dict(child.attrib) for child in root.findall(".//execution/constants/*")}
    parameters = {
        child.attrib["key"]: child.attrib.get("value")
        for child in root.findall(".//execution/parameters/parameter")
        if child.attrib.get("key")
    }
    return {
        "gravity": constants.get("gravity"),
        "rhop0": constants.get("rhop0"),
        "gamma": constants.get("gamma"),
        "cflnumber": constants.get("cflnumber"),
        "boundary": parameters.get("Boundary"),
        "slip_mode": parameters.get("SlipMode"),
        "step_algorithm": parameters.get("StepAlgorithm"),
        "kernel": parameters.get("Kernel"),
        "visco_treatment": parameters.get("ViscoTreatment"),
        "visco": parameters.get("Visco"),
        "density_dt": parameters.get("DensityDT"),
        "rigid_algorithm": parameters.get("RigidAlgorithm"),
        "time_max_s": parameters.get("TimeMax"),
        "time_out_s": parameters.get("TimeOut"),
    }


def motion_file_from_receipt(gencase_receipt: Path) -> Path | None:
    receipt = load_json(gencase_receipt)
    candidates = []
    for value in receipt.get("request", {}).get("input_files", []):
        path = Path(value)
        if path.name.endswith("_motion.dat") and path.is_file():
            candidates.append(path)
    if len(candidates) == 1:
        return candidates[0]
    return candidates[0] if candidates else None


def read_runparts(path: Path) -> dict[str, Any]:
    require_file(path, "RunPARTs")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    rows = list(csv.DictReader(lines, delimiter=";"))
    if not rows:
        raise ValueError(f"RunPARTs has no rows: {path}")
    times = [float(row["TimeStep [s]"]) for row in rows]
    positive_dt_min = [float(row["DtMin [s]"]) for row in rows if float(row["DtMin [s]"]) > 0]
    positive_dt_max = [float(row["DtMax [s]"]) for row in rows if float(row["DtMax [s]"]) > 0]
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "saved_rows": len(rows),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "minimum_positive_dt_s": min(positive_dt_min) if positive_dt_min else None,
        "maximum_positive_dt_s": max(positive_dt_max) if positive_dt_max else None,
        "initial_row": rows[0],
        "last_row": rows[-1],
    }


def resolve_case_paths(report: Mapping[str, Any], xml: Path) -> dict[str, Path | None]:
    source = report.get("source_provenance", {})
    raw_root = Path(source["data_root"])
    gencase_receipt = Path(source["gencase_receipt"]["path"])
    motion = motion_file_from_receipt(gencase_receipt)
    if motion is None:
        fallback = gencase_receipt.parent / f"{xml.stem}_motion.dat"
        motion = fallback if fallback.is_file() else None
    return {
        "raw_root": raw_root,
        "native_frame0": raw_root / "Part_0000.bi4",
        "runparts": raw_root.parent / "RunPARTs.csv",
        "trajectory": Path(report["output_hdf5"]),
        "gencase_receipt": gencase_receipt,
        "solver_receipt": Path(source["solver_receipt"]["path"]),
        "motion": motion if motion.is_file() else None,
    }


def h5_producer_record(report: Mapping[str, Any], path: Path) -> dict[str, Any]:
    require_file(path, "typed HDF5")
    stat = path.stat()
    return {
        "path": str(path),
        "producer_declared_sha256": report.get("output_sha256"),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "full_rehash": "OMITTED_BY_SCOPE",
    }


def condition_comparison(candidate: Mapping[str, Any], target: Mapping[str, Any], *, candidate_motion_sha: str | None, target_motion_sha: str | None) -> dict[str, Any]:
    target_geometry = target["physical_condition"]
    candidate_geometry = candidate["physical_condition"]
    target_control = target["physical_control"]
    candidate_control = candidate["physical_control"]
    boundary_equal = candidate_geometry["boundary_draws"] == target_geometry["boundary_draws"]
    fill_equal = candidate_geometry["fluid_fill_draws"] == target_geometry["fluid_fill_draws"]
    domain_equal = candidate_geometry["geometry_definition"]["pointmin"] == target_geometry["geometry_definition"]["pointmin"] and candidate_geometry["geometry_definition"]["pointmax"] == target_geometry["geometry_definition"]["pointmax"]
    candidate_motion = dict(candidate_geometry["motion"])
    target_motion = dict(target_geometry["motion"])
    candidate_rotation = dict(candidate_motion.get("rotation", {}))
    target_rotation = dict(target_motion.get("rotation", {}))
    candidate_rotation.pop("file_name", None)
    target_rotation.pop("file_name", None)
    candidate_motion["rotation"] = candidate_rotation
    target_motion["rotation"] = target_rotation
    motion_contract_equal = candidate_motion == target_motion
    motion_file_equal = candidate_motion_sha is not None and candidate_motion_sha == target_motion_sha
    control_equal = candidate_control == target_control
    particle_blocks_equal = candidate_geometry["particle_initialization"] == target_geometry["particle_initialization"]
    physical_mismatches = []
    if not boundary_equal:
        physical_mismatches.append("boundary_draw_geometry_receiver_or_open_rim")
    if not fill_equal:
        physical_mismatches.append("continuous_fluid_fill_draw_geometry")
    if not domain_equal:
        physical_mismatches.append("simulation_geometry_domain")
    if not motion_contract_equal:
        physical_mismatches.append("motion_contract_axis_or_duration")
    if not motion_file_equal:
        physical_mismatches.append("motion_input_file_bytes_or_binding")
    if not control_equal:
        physical_mismatches.append("physical_solver_controls")
    return {
        "physical_conditions": {
            "boundary_geometry_equal": boundary_equal,
            "fluid_fill_geometry_equal": fill_equal,
            "geometry_domain_equal": domain_equal,
            "motion_contract_equal": motion_contract_equal,
            "motion_file_equal": motion_file_equal,
            "physical_control_equal": control_equal,
            "particle_initialization_equal": particle_blocks_equal,
            "mismatch_dimensions": physical_mismatches,
            "status": "MATCH" if not physical_mismatches else "MISMATCH",
        },
        "intentional_resolution_variation": {
            "dp_m": {"target": target["signature"]["dp_m"], "candidate": candidate["signature"]["dp_m"]},
            "h_m": {"target": target["signature"]["h_m"], "candidate": candidate["signature"]["h_m"]},
            "massbound_kg": {"target": target["signature"]["massbound_kg"], "candidate": candidate["signature"]["massbound_kg"]},
            "massfluid_kg": {"target": target["signature"]["massfluid_kg"], "candidate": candidate["signature"]["massfluid_kg"]},
            "particle_initialization": {
                "target": target_geometry["particle_initialization"],
                "candidate": candidate_geometry["particle_initialization"],
                "meaning": "resolution/count/initial lattice phase is an intentional grid factor; it does not establish continuous-region equivalence",
            },
            "hashes": {
                "geometry_sha256": {
                    "target": target["signature"]["geometry_sha256"],
                    "candidate": candidate["signature"]["geometry_sha256"],
                    "interpretation": "producer hash differs; inspect expanded XML geometry above before assigning physical mismatch",
                },
                "control_reference_sha256": {
                    "target": target["signature"]["control_reference_sha256"],
                    "candidate": candidate["signature"]["control_reference_sha256"],
                    "interpretation": "producer hash differs; discretization-derived B/mass and source binding are recorded separately",
                },
            },
        },
    }


def candidate_record(spec: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    xml = require_file(Path(spec["xml"]), "generated XML")
    report_path = require_file(Path(spec["report"]), "conversion report")
    report = load_json(report_path)
    paths = resolve_case_paths(report, xml)
    for key in ("native_frame0", "runparts", "trajectory", "gencase_receipt", "solver_receipt"):
        require_file(Path(paths[key]), key)
    xml_meta = parse_xml(xml)
    physical_condition = physical_condition_xml(xml)
    physical_control = physical_control_xml(xml)
    runparts = read_runparts(Path(paths["runparts"]))
    native_record = file_record(Path(paths["native_frame0"]))
    motion_record = file_record(Path(paths["motion"])) if paths["motion"] is not None else {"status": "UNKNOWN"}
    source = report.get("source_provenance", {})
    numerical = report.get("hash_scopes", {}).get("numerical_parameters", {})
    window = {
        "nominal_time_max_s": float(xml_meta["parameters"].get("TimeMax", "nan")),
        "xml_save_interval_s": float(xml_meta["parameters"].get("TimeOut", "nan")),
        "report_frames": report.get("frames"),
        "report_first_s": report.get("time_evidence", {}).get("first_s"),
        "report_last_s": report.get("time_evidence", {}).get("last_s"),
        "runparts_first_s": runparts["first_time_s"],
        "runparts_last_s": runparts["last_time_s"],
        "actual_window_delta_from_target_s": runparts["last_time_s"] - target["window"]["runparts_last_s"],
    }
    candidate_signature = {
        "geometry_sha256": source.get("geometry_sha256"),
        "control_reference_sha256": source.get("control_reference_sha256"),
        "dp_m": float(xml_meta["constants"].get("dp", {}).get("value", "nan")),
        "h_m": float(xml_meta["constants"].get("h", {}).get("value", "nan")),
        "massbound_kg": float(xml_meta["constants"].get("massbound", {}).get("value", "nan")),
        "massfluid_kg": float(xml_meta["constants"].get("massfluid", {}).get("value", "nan")),
        "time_max_s": window["nominal_time_max_s"],
        "time_out_s": window["xml_save_interval_s"],
        "particle_blocks": xml_meta["particle_blocks"],
    }
    candidate_base = {
        "signature": candidate_signature,
        "physical_condition": physical_condition,
        "physical_control": physical_control,
    }
    comparison = condition_comparison(
        candidate_base,
        target,
        candidate_motion_sha=motion_record.get("sha256"),
        target_motion_sha=target["source"].get("motion", {}).get("sha256"),
    )
    mismatch_dimensions = list(comparison["physical_conditions"]["mismatch_dimensions"])
    if candidate_signature["time_max_s"] != target["signature"]["time_max_s"]:
        mismatch_dimensions.append("time_window_control")
    if candidate_signature["time_out_s"] != target["signature"]["time_out_s"]:
        mismatch_dimensions.append("nominal_output_cadence_control")
    dense = None
    if spec.get("dense_save_report"):
        dense_path = require_file(Path(spec["dense_save_report"]), "dense-save report")
        dense = file_record(dense_path)
        dense.update(load_json(dense_path))
    observers = {}
    for label in ("observations", "rigid_state"):
        path = Path(spec[label])
        observers[label] = file_record(path) if path.is_file() else {"status": "UNKNOWN", "path": str(path)}
    return {
        "resolution": spec["resolution"],
        "case_id": spec["case_id"],
        "strict_match_to_f2_s1": not mismatch_dimensions,
        "reuse_class": "STRICT_MATCH" if not mismatch_dimensions else "MIXED_CONFIGURATION_CANDIDATE",
        "mismatch_dimensions": mismatch_dimensions,
        "physical_condition": physical_condition,
        "physical_control": physical_control,
        "comparison": comparison,
        "continuous_initial_equivalence": {
            "status": "UNKNOWN",
            "reason": "continuous initial file is available, but XML draw/fill and discretized lattice comparison does not prove equivalent continuous region",
        },
        "source": {
            "generated_xml": file_record(xml),
            "conversion_report": file_record(report_path),
            "gencase_receipt": file_record(Path(paths["gencase_receipt"])),
            "solver_receipt": file_record(Path(paths["solver_receipt"])),
            "motion": motion_record,
            "runparts": runparts,
            "native_frame0": native_record,
        },
        "controls": {
            "constants": xml_meta["constants"],
            "parameters": xml_meta["parameters"],
            "numerical_parameters_sha256": numerical.get("numerical_parameters_sha256"),
            "control_reference_sha256": source.get("control_reference_sha256"),
            "actual_solver_command": dense.get("actual_solver_command") if dense else report.get("hash_scopes", {}).get("numerical_parameters", {}).get("solver_command"),
        },
        "continuous_initial_state": {
            "status": "FILE_AVAILABLE_ONLY" if report.get("conversion_status") == "completed" else "UNKNOWN",
            "equivalence_status": "UNKNOWN",
            "equivalence_basis": "source XML draw/fill/motion and particle initialization are recorded separately; no continuous-region equivalence is inferred",
            "raw_data_root": str(paths["raw_root"]),
            "native_frame0": str(paths["native_frame0"]),
            "typed_hdf5": h5_producer_record(report, Path(paths["trajectory"])),
            "frames": report.get("frames"),
            "particles": report.get("particles"),
            "initial_exclusion_count": report.get("typed_identity", {}).get("initial_exclusion_ledger", {}).get("count"),
            "identity_key": report.get("typed_identity", {}).get("key", "UNKNOWN"),
        },
        "window": window,
        "dense_save_telemetry": dense,
        "existing_observer_evidence": observers,
        "quality": {"QI": report.get("q_i_status"), "QN": report.get("q_n_status"), "QE": "NOT_ASSESSED"},
    }


def target_record(current_path: Path, provenance_index_path: Path, initial_output_path: Path) -> dict[str, Any]:
    current = load_json(current_path)
    rows = [row for row in current.get("cases", []) if row.get("physical_case_id") == CURRENT_CASE]
    if len(rows) != 1:
        raise ValueError(f"expected one target CURRENT row, got {len(rows)}")
    row = rows[0]
    report_path = require_file(Path(row["conversion_report"]["path"]), "target conversion report")
    report = load_json(report_path)
    xml = require_file(Path(row["source_bindings"]["generated_xml"]["path"]), "target generated XML")
    paths = resolve_case_paths(report, xml)
    for key in ("native_frame0", "runparts", "trajectory", "gencase_receipt", "solver_receipt"):
        require_file(Path(paths[key]), key)
    xml_meta = parse_xml(xml)
    physical_condition = physical_condition_xml(xml)
    physical_control = physical_control_xml(xml)
    runparts = read_runparts(Path(paths["runparts"]))
    motion_record = file_record(Path(paths["motion"])) if paths["motion"] is not None else {"status": "UNKNOWN"}
    target = {
        "physical_case_id": CURRENT_CASE,
        "runtime_case_alias": row.get("runtime_case_alias"),
        "source": {
            "current336": file_record(current_path),
            "generated_xml": file_record(xml),
            "conversion_report": file_record(report_path),
            "gencase_receipt": file_record(Path(paths["gencase_receipt"])),
            "solver_receipt": file_record(Path(paths["solver_receipt"])),
            "motion": motion_record,
            "runparts": runparts,
            "native_frame0": file_record(Path(paths["native_frame0"])),
            "initial_frame_audit": file_record(initial_output_path),
            "initial_frame_receipt": file_record(INITIAL_RECEIPT),
        },
        "controls": {"constants": xml_meta["constants"], "parameters": xml_meta["parameters"]},
        "physical_condition": physical_condition,
        "physical_control": physical_control,
        "window": {
            "nominal_time_max_s": float(xml_meta["parameters"].get("TimeMax", "nan")),
            "xml_save_interval_s": float(xml_meta["parameters"].get("TimeOut", "nan")),
            "report_frames": report.get("frames"),
            "report_first_s": report.get("time_evidence", {}).get("first_s"),
            "report_last_s": report.get("time_evidence", {}).get("last_s"),
            "runparts_first_s": runparts["first_time_s"],
            "runparts_last_s": runparts["last_time_s"],
        },
        "signature": {
            "geometry_sha256": report.get("source_provenance", {}).get("geometry_sha256"),
            "control_reference_sha256": report.get("source_provenance", {}).get("control_reference_sha256"),
            "dp_m": float(xml_meta["constants"].get("dp", {}).get("value", "nan")),
            "h_m": float(xml_meta["constants"].get("h", {}).get("value", "nan")),
            "massbound_kg": float(xml_meta["constants"].get("massbound", {}).get("value", "nan")),
            "massfluid_kg": float(xml_meta["constants"].get("massfluid", {}).get("value", "nan")),
            "time_max_s": float(xml_meta["parameters"].get("TimeMax", "nan")),
            "time_out_s": float(xml_meta["parameters"].get("TimeOut", "nan")),
            "particle_blocks": xml_meta["particle_blocks"],
        },
        "continuous_initial_state": {
            "status": "FILE_AVAILABLE_ONLY",
            "equivalence_status": "TARGET_SOURCE_BOUND; continuous-region equivalence is not inferred from particle blocks",
            "equivalence_basis": "target generated XML draw/fill/motion contract and typed/native frame-zero receipt are recorded",
            "raw_data_root": str(paths["raw_root"]),
            "native_frame0": str(paths["native_frame0"]),
            "typed_hdf5": h5_producer_record(report, Path(paths["trajectory"])),
            "frames": report.get("frames"),
            "particles": report.get("particles"),
            "initial_exclusion_count": report.get("typed_identity", {}).get("initial_exclusion_ledger", {}).get("count"),
            "identity_key": report.get("typed_identity", {}).get("key", "UNKNOWN"),
        },
    }
    return target


def second_sentinel_scope(provenance_index_path: Path) -> dict[str, Any]:
    index = load_json(provenance_index_path)
    entries = [entry for entry in index.get("cases", []) if entry.get("family_id") == "F2" and entry.get("sentinel_id") == "F2-S2"]
    if len(entries) != 1:
        return {
            "sentinel_id": "F2-S2",
            "status": "UNKNOWN",
            "unmet_requirements": ["v2.3 provenance entry is not uniquely available"],
        }
    entry = entries[0]
    output = DATA_ROOT / "families/F2/F2_S2_INITIAL_FRAME_EQUIV_V2_3/initial-frame-equivalence-v2-3-001/initial-frame-check.json"
    result = {
        "sentinel_id": entry["sentinel_id"],
        "family_id": entry["family_id"],
        "physical_case_id": entry["physical_case_id"],
        "runtime_case_alias": entry.get("runtime_case_alias"),
        "frame_zero_v2_3": file_record(output) if output.is_file() else {"status": "UNKNOWN", "path": str(output)},
        "source_bindings": entry.get("source_bindings", {}),
        "status_for_f2_s1_matrix": "OUT_OF_SCOPE",
        "unmet_requirements": [
            "F2-S2 physical recipe is RX065/P03 and is not F2-S1 RX056; no cross-sentinel credit is assigned",
            "no source-bound three-resolution F2-S2 XML/continuous-fill/control matrix is prepared in this artifact",
            "no F2-S2 same-CFL/half-CFL dense time-output pair is prepared in this artifact",
            "no F2-S2 observer calibration result is admitted",
        ],
    }
    return result


def gap_requests(target: Mapping[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    manifest = load_json(require_file(PREFLIGHT_MANIFEST, "F2-S1 GenCase preflight manifest"))
    output: list[dict[str, Any]] = []
    for record in manifest.get("cases", []):
        case_id = str(record["case_id"])
        request_path = PREFLIGHT_REQUEST_DIR / f"{case_id.lower()}.json"
        request = load_json(require_file(request_path, "F2-S1 GenCase preflight request"))
        receipt_path = DATA_ROOT / "families/F2" / case_id / request["attempt_id"] / "execution-receipt.json"
        if receipt_path.is_file():
            receipt = file_record(receipt_path)
            receipt_json = load_json(receipt_path)
            receipt["status"] = receipt_json.get("status", "UNKNOWN")
            output_root = receipt_path.parent
            gencase_outputs = {
                "generated_xml": file_record(output_root / "generated.xml") if (output_root / "generated.xml").is_file() else {"status": "UNKNOWN"},
                "native_frame0": file_record(output_root / "generated.bi4") if (output_root / "generated.bi4").is_file() else {"status": "UNKNOWN"},
            }
        else:
            receipt = {"status": "PENDING_GUARDED_RUN", "path": str(receipt_path)}
            gencase_outputs = {"status": "PENDING_GUARDED_RUN"}
        item = {
            "schema": GAP_SCHEMA,
            "status": "READY_FOR_GUARDED_GENCASE_PREFLIGHT" if receipt.get("status") == "PENDING_GUARDED_RUN" else "GENCASE_PREFLIGHT_RECEIPT_AVAILABLE",
            "launch_allowed": True,
            "review_gate": "bounded CPU GenCase only; parent reviews receipt before any solver request",
            "family_id": "F2",
            "case_id": case_id,
            "physical_case_id": CURRENT_CASE,
            "resolution": record["label"],
            "requested_dp_m": record["dp_m"],
            "requested_cfl": record["cfl"],
            "requested_save_interval_s": record["requested_save_interval_s"],
            "requested_time_window_s": [0.0, target["window"]["nominal_time_max_s"]],
            "physical_control_source": {
                "target_current336": target["source"]["current336"],
                "target_generated_xml": target["source"]["generated_xml"],
                "target_geometry_sha256": target["signature"]["geometry_sha256"],
                "target_control_reference_sha256": target["signature"]["control_reference_sha256"],
                "control_rule": "preserve F2-S1 generated draw/fill geometry, receiver x=0.56 m, initial fluid bands, rotation axis (0,-1,0.65)-(0,1,0.65), duration 4 s; vary only declared dp/CFL and later solver save cadence",
            },
            "actual_inputs": {
                "preflight_script": file_record(PREFLIGHT_SCRIPT),
                "manifest": file_record(PREFLIGHT_MANIFEST),
                "request": file_record(request_path),
                "definition": record["derived_inputs"]["definition"],
                "motion": record["derived_inputs"]["motion"],
            },
            "execution_receipt": receipt,
            "gencase_outputs": gencase_outputs,
            "required_followups_after_gencase": [
                "bind actual generated XML/GenCase receipt and native Part_0000",
                "bind typed conversion report with producer HDF5 SHA/stat without rehashing full HDF5 in this scope",
                "freeze consumer observer calibration tolerances before any new solver result",
            ],
            "resource": {
                "solver_start": "FORBIDDEN_BY_THIS_REQUEST",
                "cpu_threads": request["cpu_threads"],
                "max_wall_seconds": request["max_wall_seconds"],
                "estimated_storage_bytes": request["estimated_storage_bytes"],
                "estimated_particle_count": record["expected_particle_count_estimate"],
                "storage_estimate_policy": record["estimate_policy"],
                "parent_cpu_binding": "required through stage2 guard",
                "do_not_use_gpu6": True,
                "gpu_uuid_lease": "none",
                "do_not_start_solver_from_this_request": True,
            },
            "observer_budget_ref": "matrix.pre_registered_error_budget",
        }
        atomic_json(output_dir / f"{case_id.lower()}.json", item)
        output.append(item)
    return output


def build_matrix(current_path: Path, provenance_index_path: Path, initial_output_path: Path, output_path: Path, gap_dir: Path) -> dict[str, Any]:
    require_file(provenance_index_path, "sentinel provenance index")
    target = target_record(current_path, provenance_index_path, initial_output_path)
    candidates = [candidate_record(spec, target) for spec in CANDIDATES]
    pre_registered = {
        "status": "PRE_REGISTERED_BEFORE_OBSERVER_RESULTS",
        "adopted_label_split": file_record(QUALITY_LABELS),
        "legacy_save_plan_reference": file_record(REFERENCE_PLAN),
        "position_macro_relative_rmse": 0.02,
        "position_event_max_relative": 0.05,
        "velocity_and_kinetic_energy_nonzero_scale_relative": 0.05,
        "region_mass_absolute_proportion": 0.03,
        "event_time_characteristic_fraction": 0.01,
        "time_error_fraction_of_total_gate": 0.25,
        "output_reconstruction_error_fraction_of_total_gate": 0.25,
        "time_output_rule": "time and output/reconstruction each consume at most one quarter of the corresponding total tolerance; actual dt brackets and clamp events must be reported",
        "frame_zero_field_tolerances": {
            "position": 1.0e-6,
            "velocity": 1.0e-6,
            "density": 1.0e-3,
            "mass": 1.0e-7,
            "pressure": 5.0e-2,
            "time": 5.0e-5,
        },
        "observer_calibration_owner": "consumer independent manufacturing/parser task",
        "observer_results_admitted": False,
        "freeze_condition": "consumer calibration must complete and this budget must remain unchanged before any new solver result",
    }
    gaps = gap_requests(target, gap_dir)
    gencase_complete = all(item.get("execution_receipt", {}).get("status") == "completed" for item in gaps)
    matrix = {
        "schema": SCHEMA,
        "status": "PREPARED_WITH_BOUNDED_GENCASE_PREFLIGHT" if gencase_complete else "PREPARED_AWAITING_GENCASE_PREFLIGHT",
        "family_id": "F2",
        "target": target,
        "second_sentinel": second_sentinel_scope(provenance_index_path),
        "strict_match_rule": "compare continuous draw/fill/domain/motion/control semantics first; record dp/h/mass/count and lattice phase as intentional resolution factors; save cadence and actual dt are separate factors",
        "existing_candidates": candidates,
        "pre_registered_error_budget": pre_registered,
        "reuse_conclusion": {
            "strict_f2_s1_three_resolution_set_available": False,
            "exact_f2_s1_actual_dp010_save010_available": True,
            "rv4eq_coarse_medium_fine_are_reusable_evidence": True,
            "rv4eq_scope_difference": "MIXED_CONFIGURATION_UNKNOWN_FOR_F2_S1; do not treat as strict convergence evidence",
            "dense_output_available": True,
            "dense_output_scope": "RV4EQ_DP005 mixed-configuration candidate; save cadence is diagnostic only. Required time/output pair is target dp=.01 at CFL=.2 and CFL=.1 with dense output",
            "fine_dp008_dense_candidate": "NOT_USED; wrong spatial recipe for target time/output separation",
        },
        "gap_requests": gaps,
        "scope": {
            "solver_started": False,
            "gencase_started": gencase_complete,
            "partvtk_started": False,
            "full_time_hdf5_read": False,
            "full_hdf5_rehash": False,
            "observer_calibration_run": False,
            "QI_QN_QE": "NOT_ASSESSED",
        },
    }
    atomic_json(output_path, matrix)
    return matrix


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("repository root not found")


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root(), check=True, capture_output=True, text=True).stdout.strip()


def request_inputs(current_path: Path, provenance_index_path: Path, initial_output_path: Path) -> list[Path]:
    root = repo_root()
    result = [
        root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        current_path,
        provenance_index_path,
        initial_output_path,
        INITIAL_RECEIPT,
        REFERENCE_PLAN,
        LEGACY_MATRIX,
        QUALITY_LABELS,
        PREFLIGHT_SCRIPT,
        PREFLIGHT_MANIFEST,
    ]
    for path in sorted(PREFLIGHT_REQUEST_DIR.glob("*.json")):
        result.append(path)
    preflight_manifest = load_json(PREFLIGHT_MANIFEST)
    for record in preflight_manifest.get("cases", []):
        request_path = PREFLIGHT_REQUEST_DIR / f"{record['case_id'].lower()}.json"
        request = load_json(request_path)
        attempt_root = DATA_ROOT / "families/F2" / record["case_id"] / request["attempt_id"]
        for path in (attempt_root / "execution-receipt.json", attempt_root / "generated.xml", attempt_root / "generated.bi4"):
            if path.is_file():
                result.append(path)
    for spec in CANDIDATES:
        report = load_json(Path(spec["report"]))
        paths = resolve_case_paths(report, Path(spec["xml"]))
        result.extend([
            Path(spec["xml"]), Path(spec["report"]), Path(paths["native_frame0"]),
            Path(paths["runparts"]), Path(paths["gencase_receipt"]), Path(paths["solver_receipt"]),
        ])
        if paths["motion"] is not None:
            result.append(Path(paths["motion"]))
        for key in ("observations", "rigid_state", "dense_save_report"):
            if spec.get(key) and Path(spec[key]).is_file():
                result.append(Path(spec[key]))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in result:
        resolved = path.resolve()
        if str(resolved) not in seen:
            require_file(resolved, "request input")
            seen.add(str(resolved))
            unique.append(resolved)
    return unique


def emit_request(current_path: Path, provenance_index_path: Path, initial_output_path: Path, output_path: Path) -> dict[str, Any]:
    inputs = request_inputs(current_path, provenance_index_path, initial_output_path)
    root = repo_root()
    script = Path(__file__).resolve()
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F2",
        "case_id": "F2_S1_REFERENCE_MATRIX_V2",
        "attempt_id": "f2-s1-reference-matrix-v2-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 16777216,
        "worktree_root": str(root),
        "cwd": str(root),
        "command": [
            VENV_PYTHON,
            str(script),
            "--run",
            "--current", str(current_path.resolve()),
            "--provenance-index", str(provenance_index_path.resolve()),
            "--initial-output", str(initial_output_path.resolve()),
            "--output", "{attempt_root}/f2-s1-reference-matrix-v2.json",
            "--gap-dir", "{attempt_root}/gap-requests",
        ],
        "input_files": [str(path) for path in inputs],
        "input_hashes": {str(path): sha256_file(path) for path in inputs},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "estimated_cpu_core_hours": 2 * 300 / 3600,
            "estimated_new_storage_bytes": 16777216,
            "full_hdf5_hash": "forbidden_by_scope",
        },
        "scope": {
            "target": CURRENT_CASE,
            "reads": "exact small XML/report/RunPARTs/Part_0000 and HDF5 stat only",
            "solver_started": False,
            "full_time_hdf5_read": False,
            "observer_calibration": False,
        },
    }
    atomic_json(output_path, request)
    return request


def failure(error: Exception) -> dict[str, Any]:
    return {"schema": SCHEMA, "status": "FAILED", "error_type": type(error).__name__, "error": str(error)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-request", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--provenance-index", type=Path, required=True)
    parser.add_argument("--initial-output", type=Path, default=INITIAL_OUTPUT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gap-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.emit_request is not None:
            request = emit_request(args.current, args.provenance_index, args.initial_output, args.emit_request)
            print(json.dumps({"status": "PASS", "request": str(args.emit_request), "inputs": len(request["input_files"])}, ensure_ascii=False), flush=True)
            return 0
        if not args.run or args.gap_dir is None:
            raise ValueError("--run requires --gap-dir")
        matrix = build_matrix(args.current, args.provenance_index, args.initial_output, args.output, args.gap_dir)
        print(json.dumps({"status": "PASS", "output": str(args.output), "candidates": len(matrix["existing_candidates"]), "gaps": len(matrix["gap_requests"])}, ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        result = failure(error)
        if args.output.exists():
            print(json.dumps({"status": "FAILED", "output_untouched": str(args.output)}, ensure_ascii=False), flush=True)
            return 2
        try:
            atomic_json(args.output, result)
        except FileExistsError:
            print(json.dumps({"status": "FAILED", "output_untouched": str(args.output)}, ensure_ascii=False), flush=True)
            return 2
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
