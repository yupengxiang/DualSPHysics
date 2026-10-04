#!/usr/bin/env python3
"""Materialize the F6 fresh072 source-only owner and QA handoff.

This builder reads bounded XML/JSON metadata and hashes opaque GenCase output
files.  It never decodes BI4/H5/CSV arrays and never launches a worker.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

F6WT = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
D070 = F6WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_070_stage1_omega_internal_actual_native_qa_full241_v1"
D073 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_two_omega_endpoints_actual_gencase_073"
AUDIT = D070 / "gencase/actual-gencase-metadata-audit.json"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
FLOATINGINFO = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
PYTHON = F6WT / "lagrangian-fluid-lab/.venv/bin/python"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
FINAL_PACKAGE = F6WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_072_stage1_omega_internal_canonical_owner_qa_v1"
HISTORICAL = [
    {
        "id": "root_angular_native_qa_review_019",
        "interpretation": "historical initial QA failure retained and not rejudged",
        "path": str(DATA / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-initial-qa-019/f6_angular_release_initial_qa_report.json"),
        "sha256": "6e2f9e5d7c1a2a8e3082ca44ab7299a71bb8eb20645b0fd76bbe8c8f38358476",
    },
    {
        "id": "root_angular_native_semantic_review_020",
        "interpretation": "historical semantic audit retained and not rejudged",
        "path": str(DATA / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-semantic-audit-v3-020/f6_angular_release_semantic_audit_report.json"),
        "sha256": "c4ddf7f87d4f01f0b7242457edaaa6247922e6b34fd42c403a3531e5a926f17c",
    },
]
CASES = [
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025", 0.50),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025", 0.75),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025", 1.25),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025", 1.50),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025", 1.75),
]
EXPECTED_COUNTS = {"dimension": 3, "fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}
CENTER = [2.4, 1.2, 1.08]
TANK = [4.8, 2.4, 2.4]
CANONICAL_SCHEMA = "ds02.root.f6.prospective-endpoint-canonical-owner.v1"
PHYSICAL_SCHEMA = "ds-data-02.physical-binding.v1"
QA_SCHEMA = "ds02.f6.stage1-omega-initial-native-qa-binding.v3"
OWNER_HASH = "SHA-256(json.dumps(physical_binding, sort_keys=True, separators=(',', ':')))"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} is missing: {path}")


def vec(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise RuntimeError(f"missing XML node: {label}")
    result = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise RuntimeError(f"missing XML {label}.{axis}")
        value = float(raw)
        if not math.isfinite(value):
            raise RuntimeError(f"nonfinite XML {label}.{axis}")
        result.append(value)
    return result


def close(left: list[float], right: list[float], tol: float = 1e-12) -> bool:
    return len(left) == len(right) and all(abs(a - b) <= tol for a, b in zip(left, right))


def geometry_fingerprint(root: ET.Element) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    keep = {
        "definition", "pointref", "pointmin", "pointmax", "setdrawmode",
        "setmkfluid", "setmkbound", "drawbox", "boxfill", "point", "size",
        "shapeout", "commands", "mainlist",
    }
    return [
        (node.tag, tuple(sorted(node.attrib.items())))
        for node in root.findall(".//geometry//*")
        if node.tag in keep
    ]


def find_first(root: ET.Element, path: str, label: str) -> ET.Element:
    node = root.find(path)
    if node is None:
        raise RuntimeError(f"missing XML {label}")
    return node


def parse_xml_contract(source: Path, generated: Path, expected_omega: list[float]) -> dict[str, Any]:
    source_root = ET.parse(source).getroot()
    generated_root = ET.parse(generated).getroot()
    if geometry_fingerprint(source_root) != geometry_fingerprint(generated_root):
        raise RuntimeError(f"source/generated geometry fingerprint differs: {generated}")
    definition = find_first(generated_root, ".//geometry/definition", "geometry/definition")
    particles = find_first(generated_root, ".//particles", "particles")
    np = int(particles.get("np", "-1"))
    nb = int(particles.get("nb", "-1"))
    nbf = int(particles.get("nbf", "-1"))
    counts = {
        "dimension": 3,
        "fixed": nbf,
        "moving": 0,
        "floating": nb - nbf,
        "fluid": np - nb,
        "total": np,
    }
    generated_omega = vec(find_first(generated_root, ".//angularvelini", "angularvelini"), "angularvelini")
    source_omega = vec(find_first(source_root, ".//angularvelini", "source angularvelini"), "source angularvelini")
    center = vec(find_first(generated_root, ".//center", "center"), "center")
    tdof = vec(find_first(generated_root, ".//translationDOF", "translationDOF"), "translationDOF")
    rdof = vec(find_first(generated_root, ".//rotationDOF", "rotationDOF"), "rotationDOF")
    massbody = float(find_first(generated_root, ".//massbody", "massbody").get("value", "nan"))
    masspart = float(find_first(generated_root, ".//masspart", "masspart").get("value", "nan"))
    rho = float(find_first(generated_root, ".//rhop0", "rhop0").get("value", "nan"))
    data2d = find_first(generated_root, ".//data2d", "data2d").get("value", "").lower() == "true"
    sizes = [vec(node, "geometry/size") for node in generated_root.findall(".//geometry//size")]
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"XML count contract mismatch: {generated} -> {counts}")
    if not close(generated_omega, expected_omega) or not close(source_omega, expected_omega):
        raise RuntimeError(f"XML omega mismatch: {generated}")
    if not close(center, CENTER) or not close(tdof, [1.0, 1.0, 1.0]) or not close(rdof, [1.0, 1.0, 1.0]):
        raise RuntimeError(f"XML center/DOF mismatch: {generated}")
    if abs(float(definition.get("dp", "nan")) - 0.025) > 1e-12:
        raise RuntimeError(f"XML dp mismatch: {generated}")
    if abs(massbody - 128.0) > 1e-12 or abs(masspart - 0.015625) > 1e-12 or abs(rho - 1000.0) > 1e-12 or data2d:
        raise RuntimeError(f"XML mass/density/3D mismatch: {generated}")
    if not any(close(size, TANK) for size in sizes):
        raise RuntimeError(f"XML tank geometry missing: {generated}")
    return {
        "all_checks_passed": True,
        "source_generated_geometry_fingerprint_equal": True,
        "generated_casedef_omega_matches_source": close(generated_omega, source_omega),
        "generated_particle_omega_matches_source": close(generated_omega, expected_omega),
        "source_omega_matches_expected": close(source_omega, expected_omega),
        "generated_counts": counts,
        "generated_casedef_omega_rad_s": generated_omega,
        "generated_particle_omega_rad_s": generated_omega,
        "source_omega_rad_s": source_omega,
        "expected_omega_rad_s": expected_omega,
        "center_m": center,
        "dp_m": float(definition.get("dp")),
        "massbody_kg": massbody,
        "masspart_kg": masspart,
        "massfluid_kg": masspart,
        "rho0_kg_m3": rho,
        "translation_dof": [int(x) for x in tdof],
        "rotation_dof": [int(x) for x in rdof],
        "data2d": data2d,
        "true_3d": not data2d,
        "tank_size_m": TANK,
        "geometry_size_candidates_m": sizes,
        "checks": {
            "generated_casedef_omega_matches_source": close(generated_omega, source_omega),
            "generated_center_matches_physical": close(center, CENTER),
            "generated_counts_match_xml_contract": counts == EXPECTED_COUNTS,
            "generated_density_1000kg_m3": abs(rho - 1000.0) <= 1e-12,
            "generated_dp_0p025": abs(float(definition.get("dp")) - 0.025) <= 1e-12,
            "generated_free_6dof": tdof == [1.0, 1.0, 1.0] and rdof == [1.0, 1.0, 1.0],
            "generated_massbody_128kg": abs(massbody - 128.0) <= 1e-12,
            "generated_masspart_0p015625kg": abs(masspart - 0.015625) <= 1e-12,
            "generated_true_3d_data2d_false": data2d is False,
            "geometry_tank_size_4p8_2p4_2p4": any(close(size, TANK) for size in sizes),
            "source_generated_geometry_fingerprint_equal": True,
        },
    }


def endpoint_case(meta: dict[str, Any], out: Path, seed: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    case_id = str(meta["case_id"])
    scale = float(meta["source_scale"])
    omega = [float(x) for x in meta["omega_rad_s"]]
    meta070 = load(D070 / "metadata" / f"{case_id}.json")
    source = D070 / "source" / f"{case_id}_Def.xml"
    generated = Path(meta["generated_xml"])
    bi4 = Path(meta["generated_bi4"])
    receipt = Path(meta["execution_receipt"])
    actual_request = Path(meta["actual_gencase_request"])
    for path, label in [(source, "fresh070 source XML"), (generated, "actual GenCase XML"), (bi4, "actual GenCase BI4"), (receipt, "actual GenCase receipt"), (actual_request, "actual GenCase request")]:
        require_file(path, label)
    source_hash = sha256(source)
    generated_hash = sha256(generated)
    bi4_hash = sha256(bi4)
    receipt_hash = sha256(receipt)
    request_hash = sha256(actual_request)
    if source_hash != meta["source_definition_sha256"] or generated_hash != meta["generated_xml_sha256"] or bi4_hash != meta["generated_bi4_sha256"] or receipt_hash != meta["execution_receipt_sha256"] or request_hash != meta["actual_gencase_request_sha256"]:
        raise RuntimeError(f"actual hash audit mismatch for {case_id}")
    receipt_obj = load(receipt)
    if receipt_obj.get("status") != "completed" or int(receipt_obj.get("returncode", -1)) != 0:
        raise RuntimeError(f"GenCase receipt is not completed/0: {case_id}")
    if int(receipt_obj.get("total_particles", -1)) != 417505 or int(receipt_obj.get("fluid_particles", -1)) != 327680 or int(receipt_obj.get("solver_dimension_from_gencase", -1)) != 3:
        raise RuntimeError(f"GenCase receipt count contract mismatch: {case_id}")
    xml_metadata = parse_xml_contract(source, generated, omega)
    expected_native = copy.deepcopy(meta070["expected_native"])
    if expected_native["counts"] != EXPECTED_COUNTS or expected_native["center_m"] != CENTER or expected_native["floating_mk"] != 60 or expected_native["floating_type"] != 2 or expected_native["physical_mass_kg"] != 128.0 or expected_native["native_support_mass_kg"] != 256.0:
        raise RuntimeError(f"bounded typed metadata contract mismatch: {case_id}")
    owner_binding = copy.deepcopy(seed["physical_binding"])
    owner_binding["physical_case_id"] = case_id
    owner_binding["parameters"]["initial_angular_velocity_rad_s"] = omega
    condition_hash = hashlib.sha256(json.dumps(owner_binding, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    owner = {
        "schema": CANONICAL_SCHEMA,
        "family_id": "F6",
        "case_id": case_id,
        "physical_case_id": case_id,
        "physical_condition_sha256": condition_hash,
        "physical_binding": owner_binding,
        "source_definition": str(source),
        "source_definition_sha256": source_hash,
        "source_plan_condition_sha256": None,
        "condition_hash_semantics": OWNER_HASH + "; source-plan condition hash is intentionally null for the fresh072 internal endpoints and is never fabricated.",
        "precision_status": "not_accepted",
        "q_n": "not_granted",
        "native_support_vs_physical_mass": "256 kg lattice support and 128 kg physical rigid body remain distinct, no rescale",
        "independent_case_increment": 0,
        "source_diff_policy": "Only the genuine initial angular velocity changes across this internal scale; geometry, controls, mass semantics, free six-DOF declaration, and solver recipe remain inherited from the canonical physical binding.",
        "native_initial_qa": "pending_root_actual_partvtk_qa",
        "full_event_window_s": [0, 12],
        "expected_frames": 241,
    }
    owner_path = out / "owners" / f"{case_id}.canonical-owner.json"
    write_json(owner_path, owner)
    owner_hash = sha256(owner_path)
    metadata = {
        "schema": "ds02.f6.omega-internal-fresh072-actual-gencase-binding.v1",
        "family_id": "F6",
        "case_id": case_id,
        "scale": scale,
        "angular_velocity_rad_s": omega,
        "actual_gencase_request": str(actual_request),
        "actual_gencase_request_sha256": request_hash,
        "attempt_id": meta["attempt_id"],
        "gencase_attempt_root": meta["attempt_root"],
        "gencase_prefix": meta["gencase_prefix"],
        "gencase_receipt": str(receipt),
        "gencase_receipt_sha256": receipt_hash,
        "gencase_status": receipt_obj["status"],
        "gencase_returncode": int(receipt_obj["returncode"]),
        "generated_xml": str(generated),
        "generated_xml_sha256": generated_hash,
        "generated_bi4": str(bi4),
        "generated_bi4_sha256": bi4_hash,
        "source_definition": str(source),
        "source_definition_sha256": source_hash,
        "canonical_owner": {"path": str(owner_path), "sha256": owner_hash, "physical_condition_sha256": condition_hash},
        "source_plan_condition_sha256": None,
        "runtime_counts": {"dimension": 3, "fluid": 327680, "total": 417505},
        "xml_counts": EXPECTED_COUNTS,
        "expected_native": expected_native,
        "xml_metadata": xml_metadata,
        "quality": {"independent_case_count_increment": 0, "precision_status": "not_accepted", "production_approval": "none", "q_n_status": "not_assessed", "visual_status": "not_passed"},
        "claim_boundary": "Metadata and opaque hashes bind actual GenCase XML/BI4/receipt only; this is not native UID/type/mass/finite/overlap QA, FloatingInfo corroboration, Q-N, precision, visual, or production approval.",
        "read_policy": "XML/receipt JSON and opaque BI4 hash only; no BI4/H5/CSV/particle arrays were decoded.",
    }
    write_json(out / "metadata" / f"{case_id}.actual-gencase-binding.json", metadata)
    endpoint = {
        "canonical_owner": str(owner_path),
        "canonical_owner_sha256": owner_hash,
        "case_id": case_id,
        "endpoint_id": case_id,
        "execution_receipt": str(receipt),
        "execution_receipt_sha256": receipt_hash,
        "expected_counts": EXPECTED_COUNTS,
        "expected_masspart_kg": 0.015625,
        "expected_native_support_mass_kg": 256.0,
        "expected_physical_mass_kg": 128.0,
        "gencase_attempt_root": meta["attempt_root"],
        "generated_bi4": str(bi4),
        "generated_bi4_sha256": bi4_hash,
        "generated_xml": str(generated),
        "generated_xml_sha256": generated_hash,
        "omega_rad_s": omega,
        "physical_condition_sha256": condition_hash,
        "role": "internal_omega_scale",
        "scale": scale,
        "source_definition": str(source),
        "source_definition_sha256": source_hash,
        "source_plan_condition_sha256": None,
        "status": "actual_gencase_completed_0_pending_root_native_qa",
        "topphysical_case_id": case_id,
    }
    future = {
        "case_id": case_id,
        "scale": scale,
        "omega_rad_s": omega,
        "canonical_owner": str(owner_path),
        "canonical_owner_sha256": owner_hash,
        "physical_condition_sha256": condition_hash,
        "gencase": {"receipt": str(receipt), "receipt_sha256": receipt_hash, "xml": str(generated), "xml_sha256": generated_hash, "bi4": str(bi4), "bi4_sha256": bi4_hash, "status": "completed", "returncode": 0},
    }
    return endpoint, metadata, future


def derive_future_requests(out: Path, metas: dict[str, dict[str, Any]], endpoints: dict[str, dict[str, Any]], qa_request_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    old_qual_dir = D070 / "qualification/requests"
    old_state = load(D070 / "floatinginfo/requests/f6_first8_five_omega_state0_request.json")
    new_state_binding = load(D070 / "floatinginfo/state0-binding.json")
    for key in ["cases"]:
        new_state_binding[key] = []
    new_state_binding["schema"] = "ds02.f6.stage1-omega-internal-floatinginfo-state0-binding.v2"
    new_state_binding["scope_id"] = "root_followup_072_stage1_omega_internal_canonical_owner_qa_v1"
    new_state_binding["runner_worker"] = str(D070 / "workers/run_f6_state0_omega_internal_v1.py")
    new_state_binding["runner_worker_sha256"] = sha256(D070 / "workers/run_f6_state0_omega_internal_v1.py")
    new_state_binding["status"] = "source_only_disabled"
    new_state_binding["launch_allowed"] = False
    new_state_binding["root_only"] = True
    new_state_binding["historical_actual_corroboration"] = load(D070 / "floatinginfo/state0-binding.json").get("historical_actual_corroboration")
    derived_cases = []
    derived_receipts = []
    for case_id, _scale in CASES:
        meta = metas[case_id]
        ep = endpoints[case_id]
        old_path = old_qual_dir / f"{case_id}-full241-native-request.json"
        old = load(old_path)
        suffix = case_id.rsplit("_S", 1)[1].split("_DP", 1)[0]
        attempt_root = DATA / "families/F6" / case_id / f"root-stage1-f6-omega-{suffix.lower().replace('p','p')}-full241-native-072"
        # Keep the historical scale spelling used by fresh070 while moving the attempt suffix.
        scale_text = {"050": "0p5", "075": "0p75", "125": "1p25", "150": "1p5", "175": "1p75"}[suffix]
        attempt_root = DATA / "families/F6" / case_id / f"root-stage1-f6-omega-{scale_text}-full241-native-072"
        d = copy.deepcopy(old)
        d["attempt_id"] = f"root-stage1-f6-omega-{scale_text}-full241-native-072"
        d["attempt_root"] = str(attempt_root)
        d["request_id"] = f"f6-{scale_text}-full241-native-072"
        d["canonical_owner"] = ep["canonical_owner"]
        d["canonical_owner_sha256"] = ep["canonical_owner_sha256"]
        d["physical_condition_sha256"] = ep["physical_condition_sha256"]
        d["source_definition"] = ep["source_definition"]
        d["source_definition_sha256"] = ep["source_definition_sha256"]
        d["source_plan_condition_sha256"] = None
        d["gencase_prefix"] = meta["gencase_prefix"]
        d["gencase_xml"] = meta["generated_xml"]
        d["gencase_xml_sha256"] = meta["generated_xml_sha256"]
        d["gencase_bi4"] = meta["generated_bi4"]
        d["gencase_bi4_sha256"] = meta["generated_bi4_sha256"]
        d["gencase_receipt"] = meta["gencase_receipt"]
        d["gencase_receipt_sha256"] = meta["gencase_receipt_sha256"]
        d["actual_initial_qa"] = {"attempt_id": "root-stage1-f6-first8-five-omega-actual-native-initial-qa-072", "request_source": str(qa_request_path), "receipt_sha256": None, "index_sha256": None, "pass": None, "status": "pending_root"}
        d["floatinginfo_state0"] = {"audit_sha256": None, "observed_omega_rad_s": None, "status": "pending_root"}
        d["launch"] = False
        d["launch_allowed"] = False
        d["status"] = "source_only_disabled"
        path = out / "future/full241-requests" / f"{case_id}-full241-native-request.json"
        write_json(path, d)
        derived_cases.append({"case_id": case_id, "request": str(path), "request_sha256": sha256(path), "attempt_id": d["attempt_id"], "attempt_root": str(attempt_root), "solver_receipt": str(attempt_root / "execution-receipt.json"), "solver_receipt_sha256": None, "trajectory_h5": str(attempt_root / "solver_output/trajectory.h5"), "trajectory_h5_sha256": None, "conversion_report": str(attempt_root / "solver_output/conversion-report.json"), "conversion_report_sha256": None, "status": "disabled_waiting_actual_qa"})
        state_attempt_root = DATA / "families/F6" / "F6_TWO_ENDPOINT_STATE0_OMEGA_CORROBORATION" / f"root-stage1-f6-omega-{scale_text}-floatinginfo-state0-072"
        new_state_binding["cases"].append({"canonical_owner": ep["canonical_owner"], "canonical_owner_sha256": ep["canonical_owner_sha256"], "case_id": case_id, "declared_omega_rad_s": ep["omega_rad_s"], "endpoint_xml": meta["generated_xml"], "endpoint_xml_sha256": meta["generated_xml_sha256"], "floating_info_csv": None, "native_data": str(DATA / "families/F6" / case_id / f"root-stage1-f6-omega-{scale_text}-full241-native-072/solver_output/data"), "observed_omega_rad_s": None, "pass": None, "scale": float(meta["scale"]), "solver_receipt": str(DATA / "families/F6" / case_id / f"root-stage1-f6-omega-{scale_text}-full241-native-072/execution-receipt.json"), "solver_receipt_sha256": None, "status": "pending_root_full241_and_state0"})
        derived_receipts.append({"case_id": case_id, "full241": derived_cases[-1], "state0": {"attempt_root": str(state_attempt_root), "solver_receipt": str(new_state_binding["cases"][-1]["solver_receipt"]), "solver_receipt_sha256": None, "audit": str(state_attempt_root / "audit" / f"{case_id}.json"), "audit_sha256": None, "summary_sha256": None, "status": "disabled_waiting_full241"}})
    state_binding_path = out / "future/state0-binding.json"
    write_json(state_binding_path, new_state_binding)
    state_request = copy.deepcopy(old_state)
    state_request["attempt_id"] = "root-stage1-f6-first8-five-omega-floatinginfo-state0-072"
    state_request["command"] = [str(PYTHON), str(D070 / "workers/run_f6_state0_omega_internal_v1.py"), "--binding", str(state_binding_path), "--output-dir", "{attempt_root}/audit"]
    state_request["attempt_root"] = str(DATA / "families/F6/F6_TWO_ENDPOINT_STATE0_OMEGA_CORROBORATION/root-stage1-f6-first8-five-omega-floatinginfo-state0-072")
    state_request["cases"] = new_state_binding["cases"]
    state_request["runner_worker"] = str(D070 / "workers/run_f6_state0_omega_internal_v1.py")
    state_request["runner_worker_sha256"] = sha256(D070 / "workers/run_f6_state0_omega_internal_v1.py")
    state_request["launch"] = False
    state_request["launch_allowed"] = False
    state_request["status"] = "source_only_disabled"
    state_request_path = out / "future/state0-request.json"
    write_json(state_request_path, state_request)
    future = {
        "schema": "ds02.f6.fresh072-derived-receipt-binding.v1",
        "family_id": "F6",
        "scope_id": "root_followup_072_stage1_omega_internal_canonical_owner_qa_v1",
        "status": "source_only_disabled",
        "launch_allowed": False,
        "root_only": True,
        "claim_boundary": "All native QA, full241 solver, and FloatingInfo state0 outputs remain future Root receipts; every future output hash is null until Root completes the actual run.",
        "initial_native_qa": {"request": str(qa_request_path), "request_sha256": sha256(qa_request_path), "attempt_root": str(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_OMEGA_INTERNAL/root-stage1-f6-first8-five-omega-actual-native-initial-qa-072"), "receipt": None, "receipt_sha256": None, "index": None, "index_sha256": None, "status": "disabled_waiting_root_actual_qa"},
        "full241_requests": derived_cases,
        "state0_request": {"request": str(state_request_path), "request_sha256": sha256(state_request_path), "binding": str(state_binding_path), "binding_sha256": sha256(state_binding_path), "attempt_root": state_request["attempt_root"], "receipt": None, "receipt_sha256": None, "summary_sha256": None, "status": "disabled_waiting_root_full241"},
        "cases": derived_receipts,
        "no_future_hash_fabrication": True,
        "omega_policy": "Each future state0 audit must compare FloatingInfo observed omega with its own generated XML and canonical owner; V0=0 cannot prove zero angular velocity and mother endpoint omega is never substituted.",
    }
    write_json(out / "future/derived-receipt-binding.json", future)
    return future, state_request


def build(out: Path) -> None:
    if out.exists():
        raise RuntimeError(f"output already exists: {out}")
    out.mkdir(parents=True)
    audit = load(AUDIT)
    actual_by_case = {entry["case_id"]: entry for entry in audit["cases"]}
    if set(actual_by_case) != {case for case, _ in CASES}:
        raise RuntimeError("actual GenCase audit does not contain exactly fresh072 five cases")
    seed_path = D073 / "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025/canonical-owner.json"
    require_file(seed_path, "Root073 canonical seed")
    seed = load(seed_path)
    seed_hash = sha256(seed_path)
    if seed.get("schema") != CANONICAL_SCHEMA or seed.get("physical_binding", {}).get("schema") != PHYSICAL_SCHEMA:
        raise RuntimeError("Root073 canonical seed schema mismatch")
    endpoints: dict[str, dict[str, Any]] = {}
    metas: dict[str, dict[str, Any]] = {}
    future_case_metadata: list[dict[str, Any]] = []
    # fresh070's strict wrapper is reused verbatim except for the selector
    # needed by the actual GenCase XML, whose tank size is nested under boxfill.
    worker = out / "workers/run_f6_initial_native_qa_fresh072_v1.py"
    worker.parent.mkdir(parents=True, exist_ok=True)
    source_worker = D070 / "workers/run_f6_initial_native_qa_internal_v1.py"
    worker.write_text(source_worker.read_text(encoding="utf-8").replace('generated.findall(".//geometry/size")', 'generated.findall(".//geometry//size")'), encoding="utf-8")
    for case_id, _scale in CASES:
        ep, metadata, future_case = endpoint_case(actual_by_case[case_id], out, seed)
        endpoints[case_id] = ep
        metas[case_id] = metadata
        future_case_metadata.append(future_case)
    qa_endpoints = [endpoints[case_id] for case_id, _ in CASES]
    base_worker = D070.parent / "root_followup_066_stage1_omega_initial_native_qa_contract_fix_v1/workers/run_f6_initial_native_qa_v1.py"
    qa_binding = {
        "schema": QA_SCHEMA,
        "scope_id": "root_followup_072_stage1_omega_internal_canonical_owner_qa_v1",
        "family_id": "F6",
        "status": "source_only_disabled",
        "launch_allowed": False,
        "root_only": True,
        "root_review_required": True,
        "independent_case_count_increment": 0,
        "historical_evidence": HISTORICAL,
        "official_partvtk": {"path": str(PARTVTK), "sha256": sha256(PARTVTK)},
        "worker_source": {"execution_role": "fresh070 wrapper around unchanged strict QA066 typed/geometry worker; Root supplies this five-case binding at enablement", "path": str(worker), "sha256": sha256(worker)},
        "endpoints": qa_endpoints,
        "qa_contract": {
            "angular_boundary": "GenCase particle V0=0 cannot establish zero angular velocity; full native FloatingInfo state0 is required per endpoint.",
            "checks": ["official PartVTK UID/type/mk/count/finite/positive weights+density/true3D/zero initial fluid V/unique coordinates/no gross overlap", "XML source/generated omega/geometry/free6DOF/mass semantics", "physical mass 128 kg, native support 256 kg, masspart 0.015625 kg kept distinct"],
            "precision_status": "not_accepted",
            "q_n_status": "not_assessed",
            "production_approval": "none",
        },
        "read_policy": {"source_package": "bounded XML/JSON metadata and opaque hashes only", "native_bi4": "PartVTK input at Root execution only", "csv_arrays": False, "h5": False, "root_worker": "official PartVTK writes private CSV under Root attempt; source package does not read arrays"},
    }
    qa_binding_path = out / "qa/qa-binding.json"
    write_json(qa_binding_path, qa_binding)
    qa_attempt_root = DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_OMEGA_INTERNAL/root-stage1-f6-first8-five-omega-actual-native-initial-qa-072"
    report_paths = [str(qa_attempt_root / "initial-native-qa" / case_id / "initial-native-qa.json") for case_id, _ in CASES]
    qa_request = {
        "schema": "ds02.runner-request.v2",
        "request_id": "f6-first8-five-omega-initial-native-qa-072",
        "attempt_id": "root-stage1-f6-first8-five-omega-actual-native-initial-qa-072",
        "family_id": "F6",
        "kind": "cpu",
        "status": "source_only_disabled",
        "launch": False,
        "launch_allowed": False,
        "root_only": True,
        "root_review_required": True,
        "solver_launch_forbidden": True,
        "cwd": str(F6WT / "lagrangian-fluid-lab"),
        "attempt_root": str(qa_attempt_root),
        "command": [str(PYTHON), str(worker), "--binding", str(qa_binding_path), "--output-root", "{attempt_root}/initial-native-qa", "--partvtk-exe", str(PARTVTK), "--expected-partvtk-sha256", sha256(PARTVTK), "--threads", "2"],
        "enable_condition": "Root enables only after all five direct-root genuine GenCase069 receipts are completed/0 and each fresh072 canonical owner is materialized and hash-bound; this request runs only the official initial-native QA worker and never runs GenCase or a solver.",
        "expected_outputs": {"index": str(qa_attempt_root / "initial-native-qa/initial-native-qa-index.json"), "index_sha256": None, "reports": report_paths, "report_sha256": {case_id: None for case_id, _ in CASES}},
        "gencase_gate": [{"case_id": ep["case_id"], "receipt": ep["execution_receipt"], "receipt_sha256": ep["execution_receipt_sha256"], "xml": ep["generated_xml"], "xml_sha256": ep["generated_xml_sha256"], "bi4": ep["generated_bi4"], "bi4_sha256": ep["generated_bi4_sha256"], "status": "completed", "returncode": 0} for ep in qa_endpoints],
        "historical_evidence": HISTORICAL,
        "input_files": [str(PYTHON), str(PARTVTK), str(qa_binding_path), str(worker), str(base_worker)] + [str(D070 / "source" / f"{case_id}_Def.xml") for case_id, _ in CASES] + [ep["generated_xml"] for ep in qa_endpoints] + [ep["execution_receipt"] for ep in qa_endpoints],
        "runtime_inputs": {"strict_dispatch": {"path": str(STRICT), "sha256": sha256(STRICT)}, "runtime_v2": {"path": str(RUNTIME), "sha256": sha256(RUNTIME)}, "goal": {"path": str(GOAL), "sha256": sha256(GOAL)}},
        "mass_policy": {"physical_mass_kg": 128.0, "native_support_mass_kg": 256.0, "masspart_kg": 0.015625, "equality_required": False, "normalization": "none"},
        "claim_boundary": "Source-only disabled request; no native pass, angular propagation, Q-N, precision, visual, or production claim.",
    }
    qa_request_path = out / "qa/initial-native-qa-request.json"
    write_json(qa_request_path, qa_request)
    seed_provenance = {
        "schema": "ds02.f6.fresh072-root073-canonical-seed-binding.v1",
        "family_id": "F6",
        "seed_owner": str(seed_path),
        "seed_owner_sha256": seed_hash,
        "condition_hash_algorithm": OWNER_HASH,
        "seed_physical_condition_sha256": seed["physical_condition_sha256"],
        "derived_cases": future_case_metadata,
        "source_plan_policy": "fresh072 internal endpoints intentionally keep source_plan_condition_sha256 null; Root073 source-plan hashes are historical aliases and are not substituted for canonical physical binding.",
        "read_policy": "Root073 owner JSON and bounded metadata only; no arrays decoded.",
    }
    write_json(out / "provenance/root073-canonical-seed-binding.json", seed_provenance)
    derive_future_requests(out, metas, endpoints, qa_request_path)
    # Rewrite package-internal absolute paths from the staging directory to the
    # final F6 WT location before hashing the handoff. External data paths stay
    # absolute and are never rewritten.
    def logical_path(path: Path) -> str:
        raw = str(path)
        prefix = str(out)
        if raw == prefix or raw.startswith(prefix + "/"):
            return str(FINAL_PACKAGE) + raw[len(prefix):]
        return raw

    def rewrite(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(str(out), str(FINAL_PACKAGE))
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        return value

    for json_path in sorted(out.rglob("*.json")):
        value = load(json_path)
        write_json(json_path, rewrite(value))

    # Copy this exact source builder into the package for reproducibility.
    builder_copy = out / "builders/build_f6_fresh072.py"
    builder_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), builder_copy)
    readme = f"""F6 fresh072: five internal omega canonical owners and disabled native QA handoff

Generated at {datetime.now(timezone.utc).isoformat(timespec='seconds')}.

This package binds the five genuine Root120/GenCase069 direct-root outputs:
S050=[0.04,0.06,0.03], S075=[0.06,0.09,0.045], S125=[0.10,0.15,0.075],
S150=[0.12,0.18,0.09], and S175=[0.14,0.21,0.105] rad/s. Each actual receipt is
completed with returncode 0 and the XML contract is 417505 total, 327680 fluid,
73441 fixed, 16384 floating, 3D, Mk60/type2 floating support, dp 0.025 m,
center [2.4,1.2,1.08], free six DOF, and body mass 128 kg.

The canonical physical condition hash is computed only from the Root073
physical-binding.v1 JSON with case identity and the endpoint XML angular
velocity. The source-plan condition hash is deliberately null for these
internal endpoints. Physical body mass 128 kg, native support mass 256 kg,
and masspart 0.015625 kg remain separate; no normalization is applied.

The executable handoff is qa/initial-native-qa-request.json. It is disabled,
Root-only, CPU initial-native QA, and invokes the fresh070 wrapper from the
F6 WT. Root should enable it only after reviewing qa/qa-binding.json. The
worker then performs official PartVTK typed/geometry checks into the private
DATA attempt output. It is not a result claim.

future/ contains derived disabled full241 and FloatingInfo state0 request
metadata. It does not edit fresh070 and every future solver, QA, conversion,
and state0 output hash is null. Particle V0=0 is explicitly not treated as
proof of zero angular velocity; each endpoint requires its own state0 audit.

Read policy: this source package reads bounded XML/JSON metadata and hashes
opaque GenCase files only. It does not decode BI4/H5/CSV/particle arrays and
does not launch GenCase, PartVTK, a solver, or FloatingInfo.
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    test_text = r'''#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL_PACKAGE = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_072_stage1_omega_internal_canonical_owner_qa_v1")
def resolve(path: Path) -> Path:
    raw = str(path)
    prefix = str(FINAL_PACKAGE)
    if raw == prefix or raw.startswith(prefix + "/"):
        return ROOT / raw[len(prefix):].lstrip("/")
    return path

F6WT_PREFIX = "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
CASES = [
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025",
]
EXPECTED = {"dimension": 3, "fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path: Path):
    return json.loads(path.read_text())

def close(a, b):
    return len(a) == len(b) and all(abs(float(x) - float(y)) <= 1e-12 for x, y in zip(a, b))

def vec(node):
    return [float(node.get(axis)) for axis in "xyz"]

def test_fresh072_contract():
    binding = load(ROOT / "qa/qa-binding.json")
    assert binding["schema"] == "ds02.f6.stage1-omega-initial-native-qa-binding.v3"
    assert binding["status"] == "source_only_disabled"
    assert binding["launch_allowed"] is False and binding["root_only"] is True
    assert len(binding["historical_evidence"]) == 2
    assert len(binding["endpoints"]) == 5
    for endpoint in binding["endpoints"]:
        case = endpoint["case_id"]
        assert case in CASES
        owner_path = resolve(Path(endpoint["canonical_owner"]))
        assert owner_path.is_file() and str(owner_path).startswith(str(ROOT))
        assert digest(owner_path) == endpoint["canonical_owner_sha256"]
        owner = load(owner_path)
        assert owner["schema"] == "ds02.root.f6.prospective-endpoint-canonical-owner.v1"
        assert owner["case_id"] == case and owner["physical_case_id"] == case
        physical = owner["physical_binding"]
        condition = hashlib.sha256(json.dumps(physical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert condition == owner["physical_condition_sha256"] == endpoint["physical_condition_sha256"]
        assert owner["source_plan_condition_sha256"] is None and endpoint["source_plan_condition_sha256"] is None
        assert endpoint["expected_counts"] == EXPECTED
        source = Path(endpoint["source_definition"])
        assert str(source).startswith(F6WT_PREFIX) and source.is_file()
        assert digest(source) == endpoint["source_definition_sha256"]
        xml = Path(endpoint["generated_xml"])
        root = ET.parse(xml).getroot()
        particles = root.find(".//particles")
        assert particles is not None
        np = int(particles.get("np")); nb = int(particles.get("nb")); nbf = int(particles.get("nbf"))
        assert {"dimension": 3, "fixed": nbf, "moving": 0, "floating": nb - nbf, "fluid": np - nb, "total": np} == EXPECTED
        assert close(vec(root.find(".//angularvelini")), endpoint["omega_rad_s"])
        assert close(vec(root.find(".//center")), [2.4, 1.2, 1.08])
        assert float(root.find(".//massbody").get("value")) == 128.0
        assert float(root.find(".//masspart").get("value")) == 0.015625
        assert root.find(".//data2d").get("value").lower() == "false"
        sizes = [vec(node) for node in root.findall(".//geometry//size")]
        assert any(close(size, [4.8, 2.4, 2.4]) for size in sizes)
    request = load(ROOT / "qa/initial-native-qa-request.json")
    assert request["launch"] is False and request["launch_allowed"] is False
    assert str(FINAL_PACKAGE / "workers/run_f6_initial_native_qa_fresh072_v1.py") == request["command"][1]
    assert str(request["command"][1]).startswith(F6WT_PREFIX)
    worker_text = resolve(Path(request["command"][1])).read_text()
    assert ".//geometry//size" in worker_text
    assert request["expected_outputs"]["index_sha256"] is None
    assert all(value is None for value in request["expected_outputs"]["report_sha256"].values())
    future = load(ROOT / "future/derived-receipt-binding.json")
    assert future["launch_allowed"] is False and future["no_future_hash_fabrication"] is True
    assert future["initial_native_qa"]["receipt_sha256"] is None
    assert future["initial_native_qa"]["index_sha256"] is None
    assert future["state0_request"]["receipt_sha256"] is None and future["state0_request"]["summary_sha256"] is None
    for item in future["full241_requests"]:
        assert item["solver_receipt_sha256"] is None
        assert item["trajectory_h5_sha256"] is None and item["conversion_report_sha256"] is None

if __name__ == "__main__":
    test_fresh072_contract()
    print("fresh072 contract: PASS")
'''
    (out / "tests/test_fresh072_contract.py").parent.mkdir(parents=True, exist_ok=True)
    (out / "tests/test_fresh072_contract.py").write_text(test_text, encoding="utf-8")
    # Manifest excludes itself to avoid a self-referential hash.
    package_files = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "input-hash-binding.json":
            package_files.append({"path": logical_path(path), "sha256": sha256(path)})
    external = []
    for path in [PYTHON, worker, base_worker, D070 / "workers/run_f6_state0_omega_internal_v1.py", PARTVTK, FLOATINGINFO, SOLVER, STRICT, RUNTIME, GOAL, seed_path, AUDIT, D070 / "floatinginfo/state0-binding.json", D070 / "floatinginfo/requests/f6_first8_five_omega_state0_request.json"]:
        require_file(path, "external input")
        external.append({"path": logical_path(path), "sha256": sha256(path)})
    for case_id, _ in CASES:
        metadata = metas[case_id]
        for key in ["actual_gencase_request", "gencase_receipt", "generated_xml", "generated_bi4", "source_definition"]:
            path = Path(metadata[key])
            external.append({"path": logical_path(path), "sha256": metadata[key + "_sha256"] if key + "_sha256" in metadata else sha256(path)})
    write_json(out / "input-hash-binding.json", {"schema": "ds02.f6.fresh072-input-hash-binding.v1", "status": "source_only_disabled", "read_policy": "bounded JSON/XML and opaque hashes only; no arrays", "package_file_count": len(package_files), "package_files": package_files, "external_inputs": external})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
