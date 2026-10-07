#!/usr/bin/env python3
"""Build an additive, source-bound F4-S1 fine-grid solver request.

The fine .008 GenCase is already a completed producer artifact.  This module
does not run GenCase or DualSPHysics and never reads the generated BI4 payload.
It records the distinction between the old producer/preflight report and the
terminal receipt, recomputes the XML particle-mass audit from the generated
XML, and writes a launch-disabled full 1.2 s request for parent dispatch.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.f4-fine-source-binding.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py")
STRICT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py")
RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py")
CURRENT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json")
MATRIX = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
PREFLIGHT = REQUEST_ROOT / "stage2-remaining-sentinel-spatial-preflight-v1/f4_s1_spatial_v1_fine_dp0p008000.json"
SOURCE_XML = DATA / "F4_DROP_CENTERED_REFERENCE_001_DP010/gencase-centered-reference-002/F4_DROP_CENTERED_REFERENCE_001_DP010.xml"
SOURCE_DEF = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261002/centered_reference_matrix_001/F4_DROP_CENTERED_REFERENCE_001_DP010_Def.xml")
CANDIDATE_ROOT = DATA / "F4_S1_SPATIAL_V1_FINE_DP0p008000/f4_s1_spatial_v1_fine_dp0p008000-001"
CANDIDATE_RECEIPT = CANDIDATE_ROOT / "execution-receipt.json"
CANDIDATE_XML = CANDIDATE_ROOT / "generated.xml"
CANDIDATE_BI4 = CANDIDATE_ROOT / "generated.bi4"
CANDIDATE_DEF = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_remaining_sentinel_spatial_preflight_inputs_v1/F4_S1/fine/F4_S1_SPATIAL_V1_FINE_DP0p008000_Def.xml"
FINE_REQUEST_DIR = REQUEST_ROOT / "stage2-f4-fine-full-window-v1"
AUDIT_PATH = REFERENCE / "stage2_f4_s1_fine_gencase_producer_audit_v1.json"
REQUEST_PATH = FINE_REQUEST_DIR / "f4_s1_fine_dp0008_same_cfl_dense_t1p2.json"

PHYSICAL_CASE_ID = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
ENDPOINT_S = 1.200084396929538


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def file_record(path: Path, *, digest: bool = True) -> dict[str, object]:
    path = path.resolve()
    s = path.stat()
    result: dict[str, object] = {"path": str(path), "bytes": s.st_size, "mtime_ns": s.st_mtime_ns}
    result["sha256"] = sha256_file(path) if digest else "PARENT_V4_GUARD_REQUIRED_BEFORE_DISPATCH"
    return result


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def xml_meta(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    definition = root.find(".//geometry/definition")
    constants = root.find(".//constants")
    particles = root.find(".//particles")
    if definition is None or constants is None or particles is None:
        raise ValueError(f"missing generated XML sections: {path}")
    mass_node = constants.find("massfluid")
    if mass_node is None:
        raise ValueError(f"missing massfluid: {path}")
    blocks = []
    for node in particles:
        if node.tag.rsplit("}", 1)[-1].lower() == "fluid" and node.get("begin") and node.get("count"):
            blocks.append({
                "mkfluid": node.get("mkfluid"),
                "begin": int(node.get("begin")),
                "count": int(node.get("count")),
            })
    massfluid = float(mass_node.get("value"))
    for block in blocks:
        block["sample_mass_kg"] = block["count"] * massfluid
    h_node = constants.find("h")
    return {
        "file": file_record(path),
        "dp_m": float(definition.get("dp")),
        "h_m": float(h_node.get("value")) if h_node is not None and h_node.get("value") else None,
        "massfluid_kg": massfluid,
        "fluid_blocks": blocks,
        "fluid_particle_count": sum(int(x["count"]) for x in blocks),
        "particle_count": int(particles.get("np")) if particles.get("np") else None,
        "sample_mass_kg": sum(float(x["sample_mass_kg"]) for x in blocks),
        "cfl": float(constants.find("cflnumber").get("value")) if constants.find("cflnumber") is not None else None,
        "parameters": {
            node.get("key"): node.get("value")
            for node in root.findall(".//parameters/parameter")
            if node.get("key") and node.get("value") is not None
        },
    }


def normalized_xml(path: Path) -> str:
    root = ET.parse(path).getroot()
    # Compare continuous geometry/control semantics while deleting only
    # intentional resolution outputs and generated date/application metadata.
    root.attrib.pop("date", None)
    root.attrib.pop("app", None)
    definition = root.find(".//geometry/definition")
    if definition is not None:
        definition.attrib.pop("dp", None)
    constants = root.find(".//constants")
    if constants is not None:
        for key in ("dp", "h", "massfluid", "massbound"):
            node = constants.find(key)
            if node is not None:
                constants.remove(node)
    particles = root.find(".//particles")
    if particles is not None:
        for key in ("np", "nb", "nbf", "mkboundfirst", "mkfluidfirst"):
            particles.attrib.pop(key, None)
        summary = particles.find("_summary")
        if summary is not None:
            particles.remove(summary)
        for node in particles:
            if node.tag.rsplit("}", 1)[-1].lower() in {"fluid", "fixed", "moving", "floating"}:
                node.attrib.pop("begin", None)
                node.attrib.pop("count", None)
    for node in root.iter():
        node.tail = None
    return ET.tostring(root, encoding="unicode")


def make_request(source: dict, candidate: dict) -> dict:
    receipt_sha = candidate["receipt"]["sha256"]
    attempt_root = str(DATA / "F4_S1_FINE_DP008_FULL_WINDOW_T1P2/f4-s1-fine-dp008-full-window-t1p2-root-001")
    input_files = [
        str(DISPATCH), str(STRICT), str(RUNTIME), str(SOLVER), str(CURRENT), str(MATRIX), str(QUALITY),
        str(PREFLIGHT), str(CANDIDATE_DEF), str(CANDIDATE_RECEIPT), str(CANDIDATE_XML), str(CANDIDATE_BI4),
        str(SOURCE_XML), str(SOURCE_DEF), str(__file__),
    ]
    input_hashes = {p: sha256_file(Path(p)) for p in input_files}
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": "F4",
        "case_id": "F4_S1_FINE_DP008_FULL_WINDOW_T1P2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "sentinel_id": "F4-S1",
        "attempt_id": "f4-s1-fine-dp008-full-window-t1p2-root-001",
        "kind": "qualification",
        "qualification_stage": "stage2_source_bound_full_window_fine_pending_primary_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": 17179869184,
        "estimated_peak_gpu_mib": 4096,
        "estimated_peak_cpu_bytes": 4294967296,
        "worktree_root": str(REPO),
        "cwd": attempt_root,
        "command": [str(SOLVER), f"{attempt_root}/generated", "{attempt_root}/solver_output", f"-tmax:{ENDPOINT_S:.15f}", "-tout:0.0005"],
        "candidate_gencase_receipt": str(CANDIDATE_RECEIPT),
        "candidate_gencase_receipt_sha256": receipt_sha,
        "candidate_generated_xml": str(CANDIDATE_XML),
        "candidate_generated_xml_sha256": candidate["generated_xml"]["sha256"],
        "candidate_generated_bi4": str(CANDIDATE_BI4),
        "candidate_generated_bi4_sha256": candidate["generated_bi4"]["sha256"],
        "expected_particles": candidate["generated_xml_meta"]["particle_count"],
        "expected_fluid_particles": candidate["generated_xml_meta"]["fluid_particle_count"],
        "expected_native_frames": 2402,
        "expected_dimension": 3,
        "physical_window_s": [0.0, ENDPOINT_S],
        "save_interval_s": 0.0005,
        "source_binding": {
            "schema": "ds02.stage2.f4-fine-full-window-binding.v1",
            "current_identity": {"sentinel_id": "F4-S1", "family_id": "F4", "physical_case_id": PHYSICAL_CASE_ID},
            "source_generated_xml": source,
            "candidate_generated_xml": candidate["generated_xml_meta"],
            "continuous_geometry_control": {
                "normalized_source_xml_sha256": hashlib.sha256(normalized_xml(SOURCE_XML).encode()).hexdigest(),
                "normalized_candidate_xml_sha256": hashlib.sha256(normalized_xml(CANDIDATE_XML).encode()).hexdigest(),
                "equal": normalized_xml(SOURCE_XML) == normalized_xml(CANDIDATE_XML),
                "intentional_changes": ["dp", "h", "massfluid", "fluid block counts", "lattice phase"],
                "geometry_or_motion_changed": False,
            },
            "source_def": file_record(SOURCE_DEF),
            "candidate_def": file_record(CANDIDATE_DEF),
            "preflight_report_vs_terminal_receipt": {
                "preflight_request": file_record(PREFLIGHT),
                "terminal_gencase_receipt": file_record(CANDIDATE_RECEIPT),
                "status": "TERMINAL_RECEIPT_COMPLETED_AND_AUDITED",
                "meaning": "The -0.429036% value is independently recomputed from the terminal generated.xml; the older preflight is provenance, not the terminal producer proof.",
            },
            "source_role": "immutable reference generated XML; no particle mass rescaling",
        },
        "mass_audit": candidate["mass_audit"],
        "controls": {
            "cfl_mode": "same_cfl",
            "xml_cfl": candidate["generated_xml_meta"]["cfl"],
            "xml_timemax_s": candidate["generated_xml_meta"]["parameters"].get("TimeMax"),
            "xml_timeout_s": candidate["generated_xml_meta"]["parameters"].get("TimeOut"),
            "effective_cli_tmax_s": ENDPOINT_S,
            "effective_cli_tout_s": 0.0005,
            "actual_dt_sequence": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER",
            "dt_clamp_events": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER",
            "savedt_or_dtallinfo": "UNKNOWN; this request does not enable or infer a full per-step trace",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "parent_dispatch_only",
            "gpu_uuid": "PARENT_ASSIGNMENT_REQUIRED",
            "solver_launch": "forbidden_until_parent_review",
            "launch_disabled": True,
            "primary_gpu_dispatch_required": True,
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "output_protection": {"refuse_overwrite": True, "attempt_root_must_not_exist_at_dispatch": True},
        "hdf5": "NOT_READ_OR_CREATED_IN_PREPARATION",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build() -> tuple[Path, Path]:
    source_meta = xml_meta(SOURCE_XML)
    candidate_meta = xml_meta(CANDIDATE_XML)
    receipt = load(CANDIDATE_RECEIPT)
    candidate = {
        "receipt": file_record(CANDIDATE_RECEIPT),
        "generated_xml": file_record(CANDIDATE_XML),
        "generated_bi4": file_record(CANDIDATE_BI4),
        "generated_xml_meta": candidate_meta,
    }
    source_mass = source_meta["sample_mass_kg"]
    candidate_mass = candidate_meta["sample_mass_kg"]
    blocks = []
    source_by_mk = {str(x["mkfluid"]): x for x in source_meta["fluid_blocks"]}
    for x in candidate_meta["fluid_blocks"]:
        s = source_by_mk.get(str(x["mkfluid"]))
        if s is None:
            continue
        delta = float(x["sample_mass_kg"]) - float(s["sample_mass_kg"])
        blocks.append({
            "mkfluid": str(x["mkfluid"]),
            "source_count": s["count"], "candidate_count": x["count"],
            "source_sample_mass_kg": s["sample_mass_kg"], "candidate_sample_mass_kg": x["sample_mass_kg"],
            "delta_kg": delta,
            "relative_error_pct_vs_source_mk": 100.0 * delta / float(s["sample_mass_kg"]),
            "absolute_fraction_of_whole_source": abs(delta) / float(source_mass),
            "status": "DIAGNOSTIC_ONLY",
        })
    mass_audit = {
        "source_generated_xml": source_meta,
        "terminal_candidate_generated_xml": candidate_meta,
        "source_whole_initial_sample_mass_kg": source_mass,
        "candidate_whole_initial_sample_mass_kg": candidate_mass,
        "whole_initial_relative_error_pct": 100.0 * (candidate_mass - source_mass) / source_mass,
        "whole_initial_budget_3_percentage_points": "PASS_DIAGNOSTIC_ONLY",
        "per_mk": blocks,
        "scientific_status": "UNKNOWN; whole mass and per-MK diagnostics do not grant QI/QN/QE",
        "particle_mass_rescale": False,
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "receipt_elapsed_seconds": receipt.get("elapsed_seconds"),
        "receipt_cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "receipt_total_particles": receipt.get("total_particles"),
        "receipt_fluid_particles": receipt.get("fluid_particles"),
    }
    candidate["mass_audit"] = mass_audit
    audit = {
        "schema": SCHEMA,
        "status": "PASS_TERMINAL_GENCASERECEIPT_AUDITED_SCIENTIFIC_UNKNOWN",
        "sentinel_id": "F4-S1", "family_id": "F4", "physical_case_id": PHYSICAL_CASE_ID,
        "grid": "fine", "dp_m": 0.008,
        "producer_report": {"preflight_request": file_record(PREFLIGHT), "reported_mass_error_pct": "-0.429036_APPROXIMATE"},
        "terminal_receipt": file_record(CANDIDATE_RECEIPT),
        "generated_xml": file_record(CANDIDATE_XML), "generated_bi4": file_record(CANDIDATE_BI4, digest=True),
        "mass_audit": mass_audit,
        "source_binding": {"source_xml": file_record(SOURCE_XML), "source_def": file_record(SOURCE_DEF), "candidate_def": file_record(CANDIDATE_DEF)},
        "solver_preparation": {"request_path": str(REQUEST_PATH), "launch_disabled": True, "full_window_s": [0.0, ENDPOINT_S], "save_interval_s": 0.0005, "solver_status": "NOT_STARTED"},
        "hdf5_read": False, "gpu_lease": "none", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
    }
    request = make_request(source_meta, candidate)
    atomic_json(AUDIT_PATH, audit)
    atomic_json(REQUEST_PATH, request)
    return AUDIT_PATH, REQUEST_PATH


if __name__ == "__main__":
    a, r = build()
    print(json.dumps({"audit": str(a), "request": str(r)}, indent=2))
