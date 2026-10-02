#!/usr/bin/env python3
"""Prepare a read-only F2 floor-safe native audit and deferred full-state handoff.

The two floor-safe DP005 solver views already completed in the external data
root.  This producer binds those exact XML/BI4/motion bytes, terminal solver
receipts, and RunPARTs ledgers.  ``--prepare`` writes an official
PartVTKOut-only diagnostic manifest/request.  The diagnostic command itself
does not run a solver or converter; it only decodes the completed native
``PartOut_000.obi4`` exclusion ledger.  ``--finalize`` consumes the resulting
diagnostic report and writes root-owned full-state conversion requests,
owner metadata, and labels requests that remain disabled until an actual
terminal H5/report/receipt exists.

The floor-safe native exclusions are always a numerical unknown.  This module
does not reuse the older adaptive-baseline exclusion IDs or Motive totals,
does not infer physical spill, and never grants Q-I, Q-N, or production.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET


FAMILY_ROOT = Path(__file__).resolve().parents[2]
HANDOFF_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION_ROOT / "lagrangian-fluid-lab"
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics") / "lagrangian-fluid-lab"
PYTHON = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PARTVTKOUT = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
DIRECT_CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_direct_convert.py"
BI4_DECODER = OFFICIAL_LAB / "campaigns/l1-resume/artifacts/bi4_dump"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
NATIVE_DIAGNOSTIC = FAMILY_ROOT / "f2_rv4eq_native_partvtkout_diagnostic_v2.py"
LEGACY_NATIVE_HELPER = FAMILY_ROOT / "f2_handoff_20261002_dp005_native_diagnostic_v1.py"
NATIVE_HELPER = FAMILY_ROOT / "f2_native_resolution_diagnostic.py"
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
CASE_REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
GOAL = FAMILY_ROOT.parents[1] / "GOAL_ZH.md"
FLOOR_REQUEST_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/temporal_studies_floor_safe_v1"
FLOOR_INPUT_ROOT = F2_DATA / "F2_RV4EQ_DP005_FLOORSAFE_INPUTS_20261002"
PREP_MANIFEST = HANDOFF_ROOT / "rv4_floorsafe_native_partvtkout_manifest_v1.json"
PREP_REQUEST = HANDOFF_ROOT / "rv4_floorsafe_native_partvtkout_request_v1.json"
FINAL_MANIFEST = HANDOFF_ROOT / "rv4_floorsafe_postprocess_handoff_manifest_v1.json"
NATIVE_REPORT_DEFAULT = F2_DATA / (
    "F2_RV4EQ_FLOORSAFE_NATIVE_PARTVTKOUT_20261003_V1/"
    "rv4-floorsafe-native-preflight-001/rv4-floorsafe-native-partvtkout-diagnostic.json"
)

CONTINUOUS_MASS_KG = 24.576
EVENT_TIME_BUDGET_S = 0.0036681953999691376
SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
MACRO_RELATIVE_BUDGET = 0.05
EXPECTED_FRAMES = 401
EXPECTED_SAVE_INTERVAL_S = 0.01
TIME_MAX_S = 4.0
BYTES_PER_PARTICLE_FRAME = 64
STORAGE_MARGIN = 1.40


def require(path: Path, label: str) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with require(path, "hash input").open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    path = require(path, role)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def deferred(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": None,
        "bytes": None,
        "role": role,
        "status": "awaiting_terminal_converter_receipt",
        "required_status": "completed",
        "must_bind_actual_hash_before_dispatch": True,
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def parameters(xml_path: Path) -> dict[str, str]:
    root = ET.parse(require(xml_path, "generated XML")).getroot()
    return {
        str(node.attrib["key"]): str(node.attrib.get("value", ""))
        for node in root.findall(".//execution/parameters/parameter")
        if node.attrib.get("key") is not None
    }


def xml_projection(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(require(xml_path, "XML projection")).getroot()
    numerical_keys = {"DtFixed", "DtIni", "DtMin"}

    def normalized(node: ET.Element) -> Any:
        attrs = dict(node.attrib)
        if node.tag == "parameter" and attrs.get("key") in numerical_keys:
            attrs["value"] = "<numerical-view>"
        return (
            str(node.tag),
            tuple(sorted((str(key), str(value)) for key, value in attrs.items())),
            (node.text or "").strip(),
            tuple(normalized(child) for child in node),
        )

    return {
        "physical_projection_sha256": canonical_hash(normalized(root)),
        "full_xml_sha256": sha256(xml_path),
        "parameters": parameters(xml_path),
    }


def typed_ranges(xml_path: Path) -> list[dict[str, Any]]:
    particles = ET.parse(require(xml_path, "typed XML")).getroot().find(".//particles")
    if particles is None:
        raise ValueError(f"no particles section in {xml_path}")
    ranges: list[dict[str, Any]] = []
    for tag, type_id in (("fixed", 0), ("moving", 1), ("fluid", 3)):
        for node in particles.findall(f"./{tag}"):
            begin = int(node.attrib.get("begin", "0"))
            count = int(node.attrib["count"])
            if count <= 0:
                raise ValueError(f"empty {tag} range in {xml_path}")
            key = "mkbound" if tag in {"fixed", "moving"} else "mkfluid"
            mk = int(node.attrib[key])
            ranges.append({"source": tag, "type": type_id, "mk": mk, "begin": begin, "count": count, "end": begin + count - 1})
    ranges.sort(key=lambda item: (item["begin"], item["end"]))
    previous_end = -1
    for item in ranges:
        if item["begin"] <= previous_end:
            raise ValueError(f"overlapping typed ranges in {xml_path}")
        previous_end = item["end"]
    return ranges


def numeric_runparts(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with require(path, "RunPARTs").open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                int(str(row.get("Part", "")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    return rows


def fnumber(row: dict[str, str], key: str) -> float:
    value = row.get(key)
    if value is None or value == "":
        raise ValueError(f"RunPARTs field missing: {key}")
    return float(str(value).replace(",", ""))


def runparts_summary(path: Path, *, expected_total: int, expected_fluid: int, expected_boundary: int, target_dt: float) -> dict[str, Any]:
    rows = numeric_runparts(path)
    if len(rows) != EXPECTED_FRAMES:
        raise ValueError(f"expected {EXPECTED_FRAMES} numeric RunPARTs rows, got {len(rows)}")
    parts = [int(str(row["Part"]).replace(",", "")) for row in rows]
    if parts != list(range(EXPECTED_FRAMES)):
        raise ValueError(f"RunPARTs Part sequence is not 0..{EXPECTED_FRAMES - 1}")
    times = [fnumber(row, "TimeStep [s]") for row in rows]
    fields = {key: [int(round(fnumber(row, key))) for row in rows] for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    populations = {key: [int(round(fnumber(row, key))) for row in rows] for key in ("NpSim", "NpfSim", "NpbSim")}
    dt_min = [fnumber(row, "DtMin [s]") for row in rows[1:]]
    dt_max = [fnumber(row, "DtMax [s]") for row in rows[1:]]
    return {
        "path": str(Path(path).resolve()),
        "sha256": sha256(path),
        "numeric_rows": len(rows),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "strict_time_increase": all(a < b for a, b in zip(times, times[1:])),
        "full_window_completed": times[-1] >= TIME_MAX_S,
        "expected_save_interval_s": EXPECTED_SAVE_INTERVAL_S,
        "population_ranges": {key: {"min": min(values), "max": max(values)} for key, values in populations.items()},
        "initial_population": {key: values[0] for key, values in populations.items()},
        "expected_population_match": (
            populations["NpSim"][0] == expected_total
            and populations["NpfSim"][0] == expected_fluid
            and populations["NpbSim"][0] == expected_boundary
        ),
        "typed_population": {
            "total_particles": expected_total,
            "fluid_particles": expected_fluid,
            "boundary_and_moving_particles": expected_boundary,
        },
        "excluded_interval_sums": {key: sum(values) for key, values in fields.items()},
        "excluded_interval_max": {key: max(values) for key, values in fields.items()},
        "native_exclusion_unknown": True,
        "dt_min_post_initial_min_s": min(dt_min),
        "dt_min_post_initial_max_s": max(dt_min),
        "dt_max_post_initial_min_s": min(dt_max),
        "dt_max_post_initial_max_s": max(dt_max),
        "requested_dt_s": target_dt,
        "realized_fixed_step_exact": all(abs(value - target_dt) <= 1e-18 for value in dt_min + dt_max),
    }


def case_paths(background: str) -> dict[str, Any]:
    bg = background.lower()
    case_id = f"F2_RV4EQ_DP005_{background}_V1_REDUCED_DT_SAVE010_FLOORSAFE001"
    physical_case_id = f"F2H10V2_{background}_V1"
    mechanism = "center_catch" if background == "CENTER" else "offset_spill"
    physical_hash = {
        "CENTER": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
        "OFFSET": "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef",
    }[background]
    target_dt = {"CENTER": 3.8622877247068534e-06, "OFFSET": 3.886820497826205e-06}[background]
    input_dir = FLOOR_INPUT_ROOT / bg / case_id
    prefix = input_dir / case_id
    solver_root = F2_DATA / case_id / f"qualification-f2_rv4eq_dp005_{bg}_v1_reduced_dt_save010_floorsafe001-native-fullstate-v1"
    output = solver_root / "solver_output"
    gencase_root = F2_DATA / f"F2_RV4EQ_DP005_{background}_V1" / f"gencase-f2_rv4eq_dp005_{bg}_v1-20261002-001"
    request = FLOOR_REQUEST_ROOT / "requests" / f"{case_id}_request.json"
    baseline_id = f"F2_RV4EQ_DP005_{background}_V1_BASELINE_SAVE001"
    baseline_prefix = F2_DATA / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002" / baseline_id / baseline_id
    return {
        "background": background,
        "case_id": case_id,
        "physical_case_id": physical_case_id,
        "mechanism_id": mechanism,
        "physical_condition_hash": physical_hash,
        "target_dt_s": target_dt,
        "input_dir": input_dir,
        "prefix": prefix,
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "motion": input_dir / f"F2_RV4EQ_DP005_{background}_V1_BASELINE_SAVE001_motion.dat",
        "baseline_xml": baseline_prefix.with_suffix(".xml"),
        "baseline_bi4": baseline_prefix.with_suffix(".bi4"),
        "baseline_motion": baseline_prefix.parent / f"{baseline_id}_motion.dat",
        "solver_root": solver_root,
        "solver_receipt": solver_root / "execution-receipt.json",
        "run_out": output / "Run.out",
        "run_csv": output / "Run.csv",
        "runparts": output / "RunPARTs.csv",
        "data_dir": output / "data",
        "partinfo": output / "data/PartInfo.ibi4",
        "part_motion_ref": output / "data/PartMotionRef.ibi4",
        "partout": output / "data/PartOut_000.obi4",
        "part_first": output / "data/Part_0000.bi4",
        "part_middle": output / "data/Part_0200.bi4",
        "part_last": output / "data/Part_0400.bi4",
        "gencase_receipt": gencase_root / "execution-receipt.json",
        "floor_request": request,
        "baseline_case_id": baseline_id,
    }


def verify_case(c: dict[str, Any]) -> dict[str, Any]:
    request = load_json(c["floor_request"], f"{c['background']} floor-safe solver request")
    if request.get("case_id") != c["case_id"]:
        raise ValueError(f"{c['background']} request case_id mismatch")
    for key in ("xml", "bi4", "motion", "baseline_xml", "baseline_bi4", "baseline_motion", "solver_receipt", "run_out", "run_csv", "runparts", "partinfo", "part_motion_ref", "partout", "part_first", "part_middle", "part_last", "gencase_receipt"):
        require(c[key], f"{c['background']} {key}")
    receipt = load_json(c["solver_receipt"], f"{c['background']} floor-safe solver receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{c['background']} floor-safe solver is not completed/code0")
    xml_info = xml_projection(c["xml"])
    baseline_info = xml_projection(c["baseline_xml"])
    if xml_info["physical_projection_sha256"] != baseline_info["physical_projection_sha256"]:
        raise ValueError(f"{c['background']} floor-safe XML physical projection differs from baseline")
    params = xml_info["parameters"]
    for key in ("DtFixed", "DtIni", "DtMin"):
        if abs(float(params[key]) - c["target_dt_s"]) > 1e-18:
            raise ValueError(f"{c['background']} floor-safe {key} is not the realized target")
    if params.get("TimeMax") != "4" or params.get("TimeOut") != "0.01" or params.get("CoefDtMin") != "0.05":
        raise ValueError(f"{c['background']} floor-safe non-numerical solver parameter changed")
    if sha256(c["bi4"]) != sha256(c["baseline_bi4"]):
        raise ValueError(f"{c['background']} floor-safe BI4 differs from physical baseline")
    if sha256(c["motion"]) != sha256(c["baseline_motion"]):
        raise ValueError(f"{c['background']} floor-safe motion differs from physical baseline")
    ranges = typed_ranges(c["xml"])
    typed_counts = {source: sum(item["count"] for item in ranges if item["source"] == source) for source in ("fixed", "moving", "fluid")}
    particles = ET.parse(c["xml"]).getroot().find(".//particles")
    assert particles is not None
    xml_total = int(particles.attrib["np"])
    xml_boundary = int(particles.attrib["nb"])
    xml_fluid = xml_total - xml_boundary
    summary = runparts_summary(c["runparts"], expected_total=xml_total, expected_fluid=xml_fluid, expected_boundary=xml_boundary, target_dt=c["target_dt_s"])
    if summary["initial_population"] != {"NpSim": xml_total, "NpfSim": xml_fluid, "NpbSim": xml_boundary}:
        raise ValueError(f"{c['background']} RunPARTs initial population differs from XML")
    return {
        "source_request": binding(c["floor_request"], "floor-safe solver request"),
        "solver_receipt": binding(c["solver_receipt"], "terminal floor-safe solver receipt"),
        "generated_xml": binding(c["xml"], "floor-safe generated XML"),
        "generated_bi4": binding(c["bi4"], "floor-safe native BI4"),
        "motion": binding(c["motion"], "copied motion control"),
        "gencase_receipt": binding(c["gencase_receipt"], "completed source GenCase receipt"),
        "run_out": binding(c["run_out"], "floor-safe Run.out"),
        "run_csv": binding(c["run_csv"], "floor-safe Run.csv"),
        "runparts_source": binding(c["runparts"], "floor-safe RunPARTs ledger"),
        "partinfo": binding(c["partinfo"], "floor-safe PartInfo BI4"),
        "part_motion_ref": binding(c["part_motion_ref"], "floor-safe moving reference BI4"),
        "partout": binding(c["partout"], "floor-safe PartOut BI4"),
        "native_part_files": {
            "count": EXPECTED_FRAMES,
            "first": binding(c["part_first"], "first floor-safe native Part BI4"),
            "middle": binding(c["part_middle"], "middle floor-safe native Part BI4"),
            "last": binding(c["part_last"], "last floor-safe native Part BI4"),
        },
        "baseline_physical_sources": {
            "xml": binding(c["baseline_xml"], "immutable baseline XML for physical projection"),
            "bi4": binding(c["baseline_bi4"], "immutable baseline BI4 for physical equivalence"),
            "motion": binding(c["baseline_motion"], "immutable baseline motion for physical equivalence"),
        },
        "physical_equivalence": {
            "physical_condition_hash": c["physical_condition_hash"],
            "physical_xml_projection_sha256": xml_projection(c["xml"])["physical_projection_sha256"],
            "baseline_xml_projection_sha256": xml_projection(c["baseline_xml"])["physical_projection_sha256"],
            "allowed_xml_changes": ["DtFixed", "DtIni", "DtMin"],
            "bi4_bytes_equal": sha256(c["bi4"]) == sha256(c["baseline_bi4"]),
            "motion_bytes_equal": sha256(c["motion"]) == sha256(c["baseline_motion"]),
            "no_baseline_exclusion_reuse": True,
        },
        "typed_xml_ranges": ranges,
        "typed_xml_counts": typed_counts,
        "runparts": summary,
        "solver_parameters": xml_info["parameters"],
        "solver_receipt_summary": {key: receipt.get(key) for key in ("status", "returncode", "elapsed_seconds", "gpu_seconds", "finished_at_utc")},
    }


def make_preflight_manifest(cases: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_rows = []
    for background, c in cases.items():
        case_rows.append({
            "background": background,
            "case_id": c["case_id"],
            "physical_case_id": c["physical_case_id"],
            "mechanism_id": c["mechanism_id"],
            "dp_m": 0.005,
            "physical_condition_hash": c["physical_condition_hash"],
            "expected_frames": EXPECTED_FRAMES,
            "expected_save_interval_s": EXPECTED_SAVE_INTERVAL_S,
            "generated_xml": str(c["xml"].resolve()),
            "motion": str(c["motion"].resolve()),
            "gencase_receipt": str(c["gencase_receipt"].resolve()),
            "solver_receipt": str(c["solver_receipt"].resolve()),
            "solver_output": str(c["run_out"].parent.resolve()),
            "runparts": str(c["runparts"].resolve()),
            "data_dir": str(c["data_dir"].resolve()),
            "native_endpoint_bindings": evidence[background],
            "exclusion_semantics": "all PartVTKOut rows remain native_solver_excluded_numerical_unknown; no physical fate inference",
        })
    return {
        # Reuse the official v2 diagnostic reader's input schema while
        # keeping a fresh diagnostic_id/scope for the floor-safe native view.
        "schema": "ds-data-02.f2.rv4eq-native-partvtkout-diagnostic.v2-input",
        "diagnostic_id": "F2_RV4EQ_FLOORSAFE_NATIVE_PARTVTKOUT_20261003_V1",
        "family_id": "F2",
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_FLOORSAFE_REDUCED_DT_SAVE010_20261003",
        "source_policy": "read_only_completed_floor_safe_solver_native_outputs; no baseline exclusion reuse; no H5, solver, conversion, GPU, Q-I, Q-N, or production claim",
        "expected_frames": EXPECTED_FRAMES,
        "expected_save_interval_s": EXPECTED_SAVE_INTERVAL_S,
        "cases": case_rows,
        "qualification_claim": "none",
        "production_claim": "none",
    }


def make_preflight_request(manifest: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    inputs = [NATIVE_DIAGNOSTIC, LEGACY_NATIVE_HELPER, NATIVE_HELPER, PARTVTKOUT, PREP_MANIFEST, RUNTIME, STRICT_DISPATCH, GOAL, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX]
    for row in evidence.values():
        for key in ("generated_xml", "motion", "gencase_receipt", "solver_receipt", "run_out", "runparts_source", "runparts", "partinfo", "partout", "native_part_files"):
            value = row.get(key)
            if isinstance(value, dict) and "path" in value:
                inputs.append(Path(value["path"]))
            elif isinstance(value, dict):
                for item in value.values():
                    if isinstance(item, dict) and "path" in item:
                        inputs.append(Path(item["path"]))
    unique = list(dict.fromkeys(Path(item).resolve() for item in inputs))
    hashes = {str(path): sha256(path) for path in unique}
    return {
        "schema": "ds-data-02.runner.request.v1",
        "kind": "audit",
        "family_id": "F2",
        "case_id": manifest["diagnostic_id"],
        "attempt_id": "rv4-floorsafe-native-preflight-001",
        "command": [str(PYTHON), str(NATIVE_DIAGNOSTIC), "--manifest", str(PREP_MANIFEST.resolve()), "--partvtkout", str(PARTVTKOUT.resolve()), "--output", "{attempt_root}/rv4-floorsafe-native-partvtkout-diagnostic.json"],
        "cwd": str(FAMILY_ROOT),
        "cpu_task_kind": "official_partvtkout_native_audit",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 536870912,
        "input_files": [str(path) for path in unique],
        "input_sha256": hashes,
        "expected_outputs": {
            "report": "{attempt_root}/rv4-floorsafe-native-partvtkout-diagnostic.json",
            "records": "{attempt_root}/artifacts/records/*.jsonl",
            "partvtkout": "{attempt_root}/artifacts/partvtkout/*",
            "receipt": "{attempt_root}/execution-receipt.json",
        },
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "solver_launch_forbidden": True,
        "conversion_launch_forbidden": True,
        "runnable": True,
        "launch_allowed": False,
        "root_only": True,
        "qualification_claim": "none; native exclusion audit only",
        "production_claim": "none",
        "request_note": "This request decodes only the two completed floor-safe native PartOut ledgers with official PartVTKOut. It must not substitute adaptive-baseline IDs/Motive values and grants no Q-I/Q-N.",
    }


def conversion_request(c: dict[str, Any], evidence: dict[str, Any], owner_path: Path, preflight_report: Path, output_attempt: Path) -> dict[str, Any]:
    summary = evidence["runparts"]
    actual_particles = int(summary["population_ranges"]["NpSim"]["max"])
    raw_bytes = actual_particles * EXPECTED_FRAMES * BYTES_PER_PARTICLE_FRAME
    estimated_storage = int((raw_bytes * STORAGE_MARGIN) + 0.5)
    # Direct conversion cost is data-size dominated.  Keep this request
    # conservative and root-dispatched; no local conversion is attempted.
    input_paths = [
        Path(__file__), DIRECT_CONVERTER, BI4_DECODER, OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64",
        RUNTIME, STRICT_DISPATCH, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX,
        owner_path, preflight_report, c["xml"], c["bi4"], c["motion"], c["gencase_receipt"], c["solver_receipt"],
        c["run_out"], c["run_csv"], c["runparts"], c["partinfo"], c["part_motion_ref"], c["partout"], c["part_first"], c["part_middle"], c["part_last"],
    ]
    unique = list(dict.fromkeys(Path(path).resolve() for path in input_paths))
    input_hashes = {str(path): sha256(path) for path in unique}
    command = [
        str(PYTHON), str(DIRECT_CONVERTER),
        "--data-root", str(c["data_dir"].resolve()),
        "--generated-xml", str(c["xml"].resolve()),
        "--output", str(output_attempt / "trajectory.h5"),
        "--report", str(output_attempt / "conversion-report.json"),
        "--solver-log", str(c["run_out"].resolve()),
        "--solver-receipt", str(c["solver_receipt"].resolve()),
        "--gencase-receipt", str(c["gencase_receipt"].resolve()),
        "--owner-metadata", str(owner_path.resolve()),
        "--decoder", str(BI4_DECODER.resolve()),
        "--partvtk", str((OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64").resolve()),
        "--validation-dir", str(output_attempt / "partvtk-validation"),
        "--keep-validation-csv",
    ]
    return {
        "schema": "ds-data-02.runner.request.v1",
        "kind": "conversion",
        "family_id": "F2",
        "case_id": c["case_id"],
        "attempt_id": f"conversion-{c['case_id'].lower()}-fullstate-floorsafe-v1",
        "command": command,
        "cwd": str(INTEGRATION_LAB),
        "worktree_root": str(Path(__file__).resolve().parents[4]),
        "cpu_task_kind": "native_bi4_streaming_fullstate_conversion",
        "cpu_threads": 4,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": estimated_storage,
        "resource_estimate": {
            "actual_max_particles_from_RunPARTs": actual_particles,
            "expected_frames": EXPECTED_FRAMES,
            "bytes_per_particle_frame": BYTES_PER_PARTICLE_FRAME,
            "raw_trajectory_bytes_lower_bound": raw_bytes,
            "storage_margin_fraction": STORAGE_MARGIN - 1.0,
            "estimated_storage_bytes": estimated_storage,
            "estimated_storage_gib": estimated_storage / 1024**3,
            "wall_bound_reason": "root review required; bound from actual floor-safe Np and 401 native frames, not baseline exclusion count",
        },
        "input_files": [str(path) for path in unique],
        "input_sha256": input_hashes,
        "generated_xml": binding(c["xml"], "floor-safe generated XML"),
        "gencase_prefix": str(c["prefix"].resolve()),
        "gencase_receipt": binding(c["gencase_receipt"], "source GenCase receipt"),
        "source_bindings": {
            "physical_condition_hash": c["physical_condition_hash"],
            "physical_xml_projection_sha256": evidence["physical_equivalence"]["physical_xml_projection_sha256"],
            "baseline_physical_xml_projection_sha256": evidence["physical_equivalence"]["baseline_xml_projection_sha256"],
            "bi4_bytes_equal_to_physical_baseline": evidence["physical_equivalence"]["bi4_bytes_equal"],
            "motion_bytes_equal_to_physical_baseline": evidence["physical_equivalence"]["motion_bytes_equal"],
            "solver_receipt": binding(c["solver_receipt"], "terminal floor-safe solver receipt"),
            "runparts": binding(c["runparts"], "floor-safe RunPARTs ledger"),
            "native_partvtkout_preflight": binding(preflight_report, "floor-safe PartVTKOut preflight"),
            "owner_metadata": binding(owner_path, "floor-safe fullstate owner metadata"),
            "no_baseline_exclusion_reuse": True,
        },
        "actual_source": {
            "data_root": str(c["data_dir"].resolve()),
            "event_window_s": [0.0, TIME_MAX_S],
            "expected_native_frame_count": EXPECTED_FRAMES,
            "expected_total_particles_initial": int(evidence["runparts"]["initial_population"]["NpSim"]),
            "full_window_native_part_files": evidence["native_part_files"],
            "native_exclusion_accounting": "floor-safe RunPARTs full-window sum only; each fate remains numerical_unknown",
            "physical_fate": "unknown_until_fullstate_pose_and_finite_boundary_closure",
        },
        "quality_thresholds": {
            "continuous_initial_mass_kg": CONTINUOUS_MASS_KG,
            "native_mass_relative_budget_fraction": 1e-12,
            "event_time_absolute_budget_s": EVENT_TIME_BUDGET_S,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "macro_relative_error_threshold": MACRO_RELATIVE_BUDGET,
            "unknown_mass_remains_in_initial_denominator": True,
            "thresholds_apply_before_results": True,
        },
        "expected_outputs": {
            "trajectory": str(output_attempt / "trajectory.h5"),
            "conversion_report": str(output_attempt / "conversion-report.json"),
            "receipt": str(output_attempt / "execution-receipt.json"),
        },
        "conversion_launch": {"allowed": False, "reason": "root owns shared conversion slots and must dispatch after input review"},
        "runnable": True,
        "launch_allowed": False,
        "root_only": True,
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "qualification_claim": "none; conversion evidence only after root terminal dispatch",
        "production_claim": "none",
        "deferred_labels": True,
        "request_note": "Fresh floor-safe native inputs. Same physical mother/control/BI4/motion as RV4; only explicit DtFixed/DtIni/DtMin numerical recipe differs. Root must bind actual terminal H5/report/receipt before labels; this request does not grant Q-I/Q-N.",
    }


def owner_metadata(c: dict[str, Any], evidence: dict[str, Any], native_report: Path, conversion_path: Path, conversion_attempt: Path) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f2.rv4eq-floorsafe-fullstate-owner.v1-deferred",
        "status": "deferred_until_terminal_converter",
        "q_n_status": "not_assessed",
        "family_id": "F2",
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_FLOORSAFE_REDUCED_DT_SAVE010_20261003",
        "background": c["background"],
        "case_id": c["case_id"],
        "physical_case_id": c["physical_case_id"],
        "mechanism_id": c["mechanism_id"],
        "physical_condition_hash": c["physical_condition_hash"],
        "physical_binding_sha256": c["physical_condition_hash"],
        "numerical_recipe": {
            "recipe_id": "F2_RV4EQ_DP005_FLOORSAFE_TEMPORAL_V1",
            "variant": "reduced_dt_save010_floorsafe001",
            "dp_m": 0.005,
            "time_window_s": [0.0, TIME_MAX_S],
            "save_interval_s": EXPECTED_SAVE_INTERVAL_S,
            "DtFixed_s": c["target_dt_s"],
            "DtIni_s": c["target_dt_s"],
            "DtMin_s": c["target_dt_s"],
            "CoefDtMin": 0.05,
            "physical_condition_hash": c["physical_condition_hash"],
        },
        "physical_binding": {
            "source": "RV4EQ DP005 physical mother; floor-safe numerical view",
            "continuous_initial_mass_kg": CONTINUOUS_MASS_KG,
            "mass_policy": "native converter/header mass remains authoritative; no normalization or rescaling",
            "same_physical_xml_projection_sha256": evidence["physical_equivalence"]["physical_xml_projection_sha256"] == evidence["physical_equivalence"]["baseline_xml_projection_sha256"],
            "same_bi4_bytes": evidence["physical_equivalence"]["bi4_bytes_equal"],
            "same_motion_bytes": evidence["physical_equivalence"]["motion_bytes_equal"],
            "allowed_xml_changes": ["DtFixed", "DtIni", "DtMin"],
        },
        "source": {
            "generated_xml": evidence["generated_xml"],
            "generated_bi4": evidence["generated_bi4"],
            "motion_control": evidence["motion"],
            "gencase_receipt": evidence["gencase_receipt"],
            "solver_receipt": evidence["solver_receipt"],
            "run_out": evidence["run_out"],
            "run_csv": evidence["run_csv"],
            "runparts": evidence["runparts_source"],
            "partinfo": evidence["partinfo"],
            "part_motion_ref": evidence["part_motion_ref"],
            "partout": evidence["partout"],
            "native_part_files": evidence["native_part_files"],
            "native_partvtkout_preflight": binding(native_report, "floor-safe PartVTKOut preflight"),
        },
        "native_exclusion_evidence": {
            "runparts_full_window": evidence["runparts"],
            "partvtkout_report": binding(native_report, "floor-safe PartVTKOut preflight"),
            "all_fate_unknown": True,
            "do_not_reuse_baseline_exclusion_ids_or_motives": True,
            "physical_spill_inference": False,
        },
        "typed_lifecycle_contract": {
            "identity_key": ["Zone", "Idp"],
            "required_datasets": ["time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass"],
            "required_units": {"time": "s", "position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa"},
            "moving_pose_required": True,
            "native_unknown_not_physical_spill": True,
        },
        "fullstate_terminal_binding": {
            "status": "deferred_until_root_conversion_terminal",
            "conversion_request": deferred(conversion_path, "deferred root conversion request"),
            "trajectory_h5": deferred(conversion_attempt / "trajectory.h5", "terminal full-state trajectory H5"),
            "conversion_report": deferred(conversion_attempt / "conversion-report.json", "terminal converter report"),
            "conversion_receipt": deferred(conversion_attempt / "execution-receipt.json", "terminal converter receipt"),
            "must_bind_before_labels": True,
        },
        "event_contract": {
            "finite_cup_receiver_tray": True,
            "moving_pose_source": "actual saved Type=1 nodes plus frozen motion control",
            "numerical_unknown_destination_separate": True,
            "event_time_budget_s": EVENT_TIME_BUDGET_S,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "macro_relative_budget": MACRO_RELATIVE_BUDGET,
        },
        "qualification_claim": "none",
        "production_claim": "none",
    }


def labels_request(c: dict[str, Any], owner_path: Path, conversion_path: Path, conversion_attempt: Path, static_inputs: list[Path]) -> dict[str, Any]:
    future_h5 = conversion_attempt / "trajectory.h5"
    future_report = conversion_attempt / "conversion-report.json"
    future_receipt = conversion_attempt / "execution-receipt.json"
    return {
        "schema": "ds-data-02.f2.rv4eq-floorsafe-labels-request.v1-deferred",
        "family_id": "F2",
        "background": c["background"],
        "case_id": c["case_id"],
        "attempt_id": f"labels-{c['case_id'].lower()}-floorsafe-v1-deferred",
        "status": "disabled_until_terminal_fullstate_h5",
        "runnable": False,
        "launch_allowed": False,
        "root_only": True,
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "disabled_reason": "No real floor-safe H5/conversion report/receipt exists yet; labels cannot be dispatched or self-declared.",
        "owner_metadata": binding(owner_path, "floor-safe owner metadata"),
        "static_input_files": [str(path.resolve()) for path in static_inputs],
        "static_input_sha256": {str(path.resolve()): sha256(path) for path in static_inputs},
        "deferred_input_bindings": {
            "trajectory_h5": deferred(future_h5, "terminal floor-safe trajectory H5"),
            "conversion_report": deferred(future_report, "terminal floor-safe conversion report"),
            "conversion_receipt": deferred(future_receipt, "terminal floor-safe conversion receipt"),
        },
        "required_before_dispatch": [
            "terminal conversion receipt status=completed and returncode=0",
            "actual H5 shape/type/valid/units/lifecycle report passes structural Q-I checks",
            "actual moving-body pose dataset is bound to saved Type=1 nodes and frozen motion control",
            "native PartVTKOut exclusions remain numerical_unknown and are not relabeled as spill",
            "no qualified=true or within_budget=true self declaration is accepted",
        ],
        "qualification_claim": "none",
        "production_claim": "none",
    }


def prepare() -> dict[str, Any]:
    cases = {background: case_paths(background) for background in ("CENTER", "OFFSET")}
    evidence = {background: verify_case(cases[background]) for background in cases}
    manifest = make_preflight_manifest(cases, evidence)
    dump(PREP_MANIFEST, manifest)
    request = make_preflight_request(manifest, evidence)
    # The request must hash the final manifest bytes, so write it before the
    # request digest map and then regenerate the request exactly once.
    dump(PREP_MANIFEST, manifest)
    request = make_preflight_request(manifest, evidence)
    dump(PREP_REQUEST, request)
    return {"manifest": manifest, "request": request, "evidence": evidence}


def finalize(native_report: Path) -> dict[str, Any]:
    native_report = require(native_report, "completed floor-safe PartVTKOut report")
    cases = {background: case_paths(background) for background in ("CENTER", "OFFSET")}
    evidence = {background: verify_case(cases[background]) for background in cases}
    report = load_json(native_report, "floor-safe native PartVTKOut report")
    if report.get("status") != "diagnostic_complete_pending_scientific_review":
        raise ValueError(f"unexpected native diagnostic status: {report.get('status')!r}")
    by_background = {str(item.get("background")): item for item in report.get("cases", [])}
    if set(by_background) != set(cases):
        raise ValueError("native report must contain exactly CENTER and OFFSET floor-safe cases")
    for background, c in cases.items():
        item = by_background[background]
        if item.get("case_id") != c["case_id"]:
            raise ValueError(f"{background} native report is bound to the wrong case")
        timeline = item.get("native_timeline", {})
        if timeline.get("rows") != EXPECTED_FRAMES or not timeline.get("full_window_completed"):
            raise ValueError(f"{background} native diagnostic timeline is incomplete")
        expected_sum = evidence[background]["runparts"]["excluded_interval_sums"]["NpOut"]
        actual_sum = int(timeline.get("NpOut_sum", -1))
        if actual_sum != expected_sum:
            raise ValueError(f"{background} native report RunPARTs sum mismatch")
        if not item.get("partvtkout_exclusions", {}).get("all_rows_are_native_numerical_unknown"):
            raise ValueError(f"{background} native exclusions lost unknown-fate semantics")
    owners: dict[str, Path] = {}
    conversions: dict[str, Path] = {}
    labels: dict[str, Path] = {}
    static_inputs = [NATIVE_DIAGNOSTIC, LEGACY_NATIVE_HELPER, NATIVE_HELPER, DIRECT_CONVERTER, RUNTIME, STRICT_DISPATCH, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX, GOAL]
    for background, c in cases.items():
        owner_path = HANDOFF_ROOT / "owner_metadata" / f"{c['case_id']}.owner.v1-deferred.json"
        conversion_path = HANDOFF_ROOT / "conversion_requests" / f"{c['case_id']}_conversion_request_v1.json"
        conversion_attempt = F2_DATA / c["case_id"] / f"conversion-{c['case_id'].lower()}-fullstate-floorsafe-v1"
        owner_value = owner_metadata(c, evidence[background], native_report, conversion_path, conversion_attempt)
        dump(owner_path, owner_value)
        conversion_value = conversion_request(c, evidence[background], owner_path, native_report, conversion_attempt)
        dump(conversion_path, conversion_value)
        label_path = HANDOFF_ROOT / "labels_requests" / f"{c['case_id']}_labels_request_v1_deferred.json"
        labels_value = labels_request(c, owner_path, conversion_path, conversion_attempt, [*static_inputs, owner_path, conversion_path, native_report])
        dump(label_path, labels_value)
        owners[background] = owner_path
        conversions[background] = conversion_path
        labels[background] = label_path
    final = {
        "schema": "ds-data-02.f2.rv4eq-floorsafe-postprocess-handoff.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F2",
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_FLOORSAFE_REDUCED_DT_SAVE010_20261003",
        "native_partvtkout_report": binding(native_report, "completed floor-safe PartVTKOut report"),
        "preflight_manifest": binding(PREP_MANIFEST, "floor-safe native preflight manifest"),
        "preflight_request": binding(PREP_REQUEST, "floor-safe native preflight request"),
        "cases": [
            {
                "background": background,
                "case_id": cases[background]["case_id"],
                "owner_metadata": binding(owners[background], "floor-safe fullstate owner metadata"),
                "conversion_request": binding(conversions[background], "deferred root conversion request"),
                "labels_request": binding(labels[background], "disabled deferred labels request"),
                "native_runparts": evidence[background]["runparts"],
                "native_exclusion_row_count": by_background[background]["partvtkout_exclusions"]["row_count"],
                "native_exclusion_fate": "unknown",
                "status": "conversion_deferred_labels_disabled_qn_pending",
            }
            for background in ("CENTER", "OFFSET")
        ],
        "source_policy": "floor-safe physical source/control/BI4/motion bytes are independent of baseline exclusion accounting; all consumed sources immutable",
        "launch_policy": {"solver": False, "native_partvtkout": False, "conversion": False, "labels": False, "root_owns_dispatch": True},
        "quality_thresholds": {
            "continuous_initial_mass_kg": CONTINUOUS_MASS_KG,
            "native_mass_relative_budget_fraction": 1e-12,
            "event_time_absolute_budget_s": EVENT_TIME_BUDGET_S,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "macro_relative_error_threshold": MACRO_RELATIVE_BUDGET,
            "unknown_mass_remains_in_initial_denominator": True,
        },
        "qualification_claim": "none",
        "production_claim": "none",
        "q_n_status": "not_assessed",
    }
    dump(FINAL_MANIFEST, final)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--native-report", type=Path, default=NATIVE_REPORT_DEFAULT)
    args = parser.parse_args()
    if args.prepare == args.finalize:
        parser.error("choose exactly one of --prepare or --finalize")
    result = prepare() if args.prepare else finalize(args.native_report)
    print(json.dumps({"status": "prepared" if args.prepare else "finalized", "path": str(PREP_MANIFEST if args.prepare else FINAL_MANIFEST), "case_count": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
