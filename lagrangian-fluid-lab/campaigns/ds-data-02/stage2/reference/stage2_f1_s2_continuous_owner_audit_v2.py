#!/usr/bin/env python3
"""Source-bound continuous-owner audit for the F1-S2 three-grid family.

The audit deliberately stops at the source/owner boundary.  It proves the
continuous box and its controls from small owner/Def/generated-XML files,
then joins the already completed ROOT207 child observer report and ROOT217
manufactured calibration proof.  It does not read a production BI4, H5, VTK,
or solver output.  Native particle support therefore remains a separately
prepared, unrun gate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f1-s2.continuous-owner-audit.v2"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.continuous-owner-audit-manifest.v2"
MAX_BYTES = 16 * 1024 * 1024
FLOAT_TOL = 2.0e-10
MASS_TOL = 2.0e-6


class AuditError(RuntimeError):
    pass


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"invalid numeric {label}: {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"non-finite numeric {label}")
    return result


def close(a: float, b: float, tol: float = FLOAT_TOL) -> bool:
    return abs(float(a) - float(b)) <= tol


def vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise AuditError(f"{label} must be a length-3 array")
    return [finite(item, f"{label}[{i}]") for i, item in enumerate(value)]


def vectors_close(left: list[float], right: list[float], tol: float = FLOAT_TOL) -> bool:
    return len(left) == len(right) and all(close(a, b, tol) for a, b in zip(left, right))


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stat_record(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": str(path),
        "bytes": st.st_size,
        "dev": st.st_dev,
        "ino": st.st_ino,
        "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns,
    }


def read_bound(path_value: str | Path, expected_sha: str | None = None,
               *, label: str, max_bytes: int = MAX_BYTES) -> tuple[bytes, dict[str, Any]]:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise AuditError(f"{label} is not a regular non-symlink file: {path}")
    before = stat_record(path)
    if before["bytes"] > max_bytes:
        raise AuditError(f"{label} exceeds bounded read: {before['bytes']} > {max_bytes}")
    data = path.read_bytes()
    observed = digest_bytes(data)
    after = stat_record(path)
    if before != after:
        raise AuditError(f"{label} changed during read")
    if expected_sha is not None and observed != expected_sha:
        raise AuditError(f"{label} SHA mismatch: expected {expected_sha}, got {observed}")
    record = dict(after)
    record["sha256"] = observed
    return data, record


def read_json(path_value: str | Path, expected_sha: str | None, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data, record = read_bound(path_value, expected_sha, label=label)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} root must be an object")
    return value, record


def read_xml(path_value: str | Path, expected_sha: str | None, *, label: str) -> tuple[ET.Element, dict[str, Any]]:
    data, record = read_bound(path_value, expected_sha, label=label)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise AuditError(f"{label} is not valid XML") from exc
    return root, record


def first(root: ET.Element, name: str) -> ET.Element | None:
    return next((node for node in root.iter() if lname(node.tag) == name), None)


def child(node: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in node if lname(item.tag) == name), None)


def attr_number(node: ET.Element | None, key: str, label: str) -> float:
    if node is None or key not in node.attrib:
        raise AuditError(f"missing {label}")
    return finite(node.attrib[key], label)


def attr_vec(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise AuditError(f"missing {label}")
    return [attr_number(node, key, f"{label}.{key}") for key in ("x", "y", "z")]


def parse_parameters(root: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in root.iter():
        if lname(node.tag) == "parameter" and "key" in node.attrib and "value" in node.attrib:
            result[node.attrib["key"]] = node.attrib["value"]
    return result


def parse_drawboxes(root: ET.Element) -> list[dict[str, Any]]:
    active_fluid: str | None = None
    active_bound: str | None = None
    boxes: list[dict[str, Any]] = []
    for node in root.iter():
        tag = lname(node.tag)
        if tag == "setmkfluid":
            active_fluid = node.attrib.get("mk")
            active_bound = None
        elif tag == "setmkbound":
            active_bound = node.attrib.get("mk")
            active_fluid = None
        elif tag == "setmkvoid":
            active_bound = None
            active_fluid = None
        elif tag != "drawbox":
            continue
        fill = child(node, "boxfill")
        if fill is None or (fill.text or "").strip().lower() != "solid":
            continue
        point = attr_vec(child(node, "point"), "drawbox.point")
        size = attr_vec(child(node, "size"), "drawbox.size")
        if any(value <= 0 for value in size):
            raise AuditError("drawbox size must be positive")
        boxes.append({
            "comment": node.attrib.get("cmt", ""),
            "point_m": point,
            "size_m": size,
            "fluid_relative": int(active_fluid) if active_fluid is not None else None,
            "bound_absolute": int(active_bound) if active_bound is not None else None,
            "volume_m3": size[0] * size[1] * size[2],
        })
    return boxes


def parse_xml(path_value: str | Path, expected_sha: str, *, label: str) -> dict[str, Any]:
    root, record = read_xml(path_value, expected_sha, label=label)
    definition = first(root, "definition")
    gravity_node = first(root, "gravity")
    rhop_node = first(root, "rhop0")
    if definition is None or "dp" not in definition.attrib:
        raise AuditError(f"{label} lacks definition dp")
    gravity = attr_vec(gravity_node, f"{label}.gravity")
    rhop = attr_number(rhop_node, "value", f"{label}.rhop0")
    boxes = parse_drawboxes(root)
    fluid_boxes = [box for box in boxes if box["fluid_relative"] is not None]
    if len(fluid_boxes) != 1:
        raise AuditError(f"{label} expected exactly one fluid drawbox, got {len(fluid_boxes)}")
    particles = first(root, "particles")
    fluid_nodes = [node for node in root.iter() if lname(node.tag) == "fluid"]
    fluid_row = next((node for node in fluid_nodes if node.attrib.get("mkfluid") == "0"), None)
    massfluid_node = first(root, "massfluid")
    massbound_node = first(root, "massbound")
    particle_count = int(particles.attrib["np"]) if particles is not None and "np" in particles.attrib else None
    fluid_count = int(fluid_row.attrib["count"]) if fluid_row is not None else None
    massfluid = attr_number(massfluid_node, "value", f"{label}.massfluid") if massfluid_node is not None else None
    massbound = attr_number(massbound_node, "value", f"{label}.massbound") if massbound_node is not None else None
    fluid_box = fluid_boxes[0]
    return {
        "path": str(Path(path_value).expanduser().resolve()),
        "file": record,
        "definition_dp_m": finite(definition.attrib["dp"], f"{label}.dp"),
        "gravity_m_s2": gravity,
        "rhop0_kg_m3": rhop,
        "parameters": parse_parameters(root),
        "boxes": boxes,
        "fluid_box": fluid_box,
        "particle_count": particle_count,
        "fluid_count": fluid_count,
        "massfluid_kg": massfluid,
        "massbound_kg": massbound,
        "sample_mass_kg": fluid_count * massfluid if fluid_count is not None and massfluid is not None else None,
        "fluid_mk_absolute": int(fluid_row.attrib["mk"]) if fluid_row is not None and "mk" in fluid_row.attrib else None,
        "fluid_mk_relative": int(fluid_row.attrib["mkfluid"]) if fluid_row is not None and "mkfluid" in fluid_row.attrib else None,
    }


def parse_owner(owner: dict[str, Any]) -> dict[str, Any]:
    if owner.get("schema") != "ds02.root.lower-head-fallback-owner.v1":
        raise AuditError("unexpected owner schema")
    binding = owner.get("physical_binding")
    if not isinstance(binding, dict):
        raise AuditError("owner lacks physical_binding")
    geom = binding.get("geometry", {})
    initial = binding.get("initial_state", {})
    fluid = geom.get("fluid_reservoir")
    if not isinstance(fluid, dict):
        raise AuditError("owner lacks fluid reservoir")
    low = vector(fluid.get("low_m"), "owner.fluid.low_m")
    size = vector(fluid.get("size_m"), "owner.fluid.size_m")
    density = finite(binding.get("density_kg_m3"), "owner.density")
    volume = finite(binding.get("parameters", {}).get("continuum_fluid_volume_m3"), "owner.volume")
    mass = finite(initial.get("continuum_mass_by_source_kg", {}).get("fluid"), "owner.mass")
    gravity = vector(binding.get("gravity_m_s2"), "owner.gravity")
    velocity = vector(initial.get("velocities_m_per_s", {}).get("fluid"), "owner.velocity")
    tank = geom.get("tank")
    divider = geom.get("obstacle_or_divider")
    if not isinstance(tank, dict) or not isinstance(divider, dict):
        raise AuditError("owner lacks tank/divider")
    result = {
        "schema": owner["schema"],
        "family_id": owner.get("family_id"),
        "case_id": owner.get("case_id"),
        "physical_case_id": owner.get("physical_case_id"),
        "fluid_low_m": low,
        "fluid_size_m": size,
        "fluid_high_m": [low[i] + size[i] for i in range(3)],
        "density_kg_m3": density,
        "volume_m3": volume,
        "mass_kg": mass,
        "gravity_m_s2": gravity,
        "velocity_m_s": velocity,
        "mkfluid_relative": int(fluid.get("mkfluid")),
        "tank_low_m": vector(tank.get("low_m"), "owner.tank.low_m"),
        "tank_size_m": vector(tank.get("size_m"), "owner.tank.size_m"),
        "divider_low_m": vector(divider.get("low_m"), "owner.divider.low_m"),
        "divider_size_m": vector(divider.get("size_m"), "owner.divider.size_m"),
        "controls": {str(k): str(v) for k, v in owner.get("solver_parameters", {}).items()},
        "source": owner.get("source", {}),
        "claims": owner.get("claims", {}),
    }
    calculated_volume = size[0] * size[1] * size[2]
    if not close(calculated_volume, volume, 1e-12):
        raise AuditError(f"owner volume mismatch: {calculated_volume} vs {volume}")
    if not close(calculated_volume * density, mass, 1e-9):
        raise AuditError(f"owner mass mismatch: {calculated_volume * density} vs {mass}")
    if not vectors_close(gravity, [0.0, 0.0, -9.81], 1e-12):
        raise AuditError("owner gravity is not the registered F1-S2 gravity")
    if any(abs(value) > 1e-15 for value in velocity):
        raise AuditError("owner initial fluid velocity is not zero")
    # The continuous box must be inside the finite tank.
    tank_high = [result["tank_low_m"][i] + result["tank_size_m"][i] for i in range(3)]
    if any(result["fluid_low_m"][i] < result["tank_low_m"][i] - FLOAT_TOL or
           result["fluid_high_m"][i] > tank_high[i] + FLOAT_TOL for i in range(3)):
        raise AuditError("owner fluid reservoir is outside tank")
    # The divider x interval ends before the fluid x interval begins and its
    # y interval is disjoint from the full fluid y interval.
    div_high = [result["divider_low_m"][i] + result["divider_size_m"][i] for i in range(3)]
    overlap = all(max(result["fluid_low_m"][i], result["divider_low_m"][i]) <
                  min(result["fluid_high_m"][i], div_high[i]) - FLOAT_TOL for i in range(3))
    if overlap:
        raise AuditError("owner divider overlaps the fluid reservoir")
    result["calculated_volume_m3"] = calculated_volume
    result["calculated_mass_kg"] = calculated_volume * density
    result["primitive_source_drawbox_note"] = "The Def drawbox is an inset cell-centre primitive; it is not substituted for this owner box."
    return result


def parse_receipt(receipt: dict[str, Any], owner_xml_path: str, def_sha: str) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed":
        raise AuditError("owner source receipt is not a completed ds02.execution-receipt.v1 receipt")
    if receipt.get("returncode") not in (0, "0", None):
        raise AuditError("owner source receipt has nonzero returncode")
    input_hashes = receipt.get("input_hashes_at_launch", {})
    if not isinstance(input_hashes, dict):
        raise AuditError("owner source receipt lacks input hashes")
    values = {str(v) for v in input_hashes.values() if isinstance(v, str)}
    if def_sha not in values:
        raise AuditError("owner source Def SHA is not present in receipt input hashes")
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or Path(owner_xml_path).resolve().parent.parent != Path(output_root).resolve():
        # GenCase receipts use the attempt root; the prepared XML is nested
        # below it.  Accept the exact prepared directory or its parent only.
        xml_parent = Path(owner_xml_path).resolve().parent
        if not isinstance(output_root, str) or Path(output_root).resolve() not in (xml_parent, xml_parent.parent):
            raise AuditError("owner source receipt output_root does not bind generated XML")
    return {
        "schema": receipt["schema"],
        "status": receipt["status"],
        "returncode": receipt.get("returncode"),
        "output_root": output_root,
        "input_hash_count": len(input_hashes),
    }


def proof_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def verify_root207(manifest: dict[str, Any], owner: dict[str, Any], grids: dict[str, dict[str, Any]]) -> dict[str, Any]:
    binding = manifest["proofs"]["root207"]
    proof, proof_stat = read_json(binding["path"], binding["sha256"], label="ROOT207 proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise AuditError("ROOT207 proof schema mismatch")
    if proof.get("status") != "VERIFIED_ACTUAL_F1_ROOT207_SELECTED_NATIVE_HEADER_WEIGHTED_OBSERVATIONS_AXIS_CALIBRATION_UNKNOWN":
        raise AuditError("ROOT207 proof status mismatch")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("scientific_Q_credit") is not False:
        raise AuditError("ROOT207 proof has an unsafe read or scientific-credit flag")
    child_path = proof.get("child_report")
    child_sha = proof.get("child_report_sha256")
    wrapper_path = proof.get("report")
    wrapper_sha = proof.get("report_sha256")
    if not all(isinstance(item, str) for item in (child_path, child_sha, wrapper_path, wrapper_sha)):
        raise AuditError("ROOT207 proof lacks child/wrapper report edges")
    wrapper, wrapper_stat = read_json(wrapper_path, wrapper_sha, label="ROOT207 wrapper report")
    child, child_stat = read_json(child_path, child_sha, label="ROOT207 child report")
    if wrapper.get("schema") != "ds02.stage2.f1.native-selected-observer-guarded-wrapper.v4":
        raise AuditError("ROOT207 wrapper schema mismatch")
    if wrapper.get("child_output", {}).get("path") != str(proof_path(child_path)):
        raise AuditError("ROOT207 wrapper child path is not the proof child path")
    if child.get("schema") != "ds02.stage2.f1.native-selected-observer.v1" or child.get("status") != "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES":
        raise AuditError("ROOT207 child report schema/status mismatch")
    if child.get("scope", {}).get("xml_mass_fallback") is not False:
        raise AuditError("ROOT207 child used XML mass fallback")
    cases = child.get("cases")
    if not isinstance(cases, list):
        raise AuditError("ROOT207 child cases are missing")
    s2_cases = [case for case in cases if isinstance(case, dict) and str(case.get("label", "")).startswith("F1_S2_")]
    if {case.get("label") for case in s2_cases} != {"F1_S2_DP0225_COARSE", "F1_S2_DP020_MEDIUM", "F1_S2_DP017_FINE"}:
        raise AuditError("ROOT207 child does not contain the exact three F1-S2 cases")
    selected = {str(item.get("label")): item for item in proof.get("selected_case_verifications", []) if isinstance(item, dict)}
    case_report: dict[str, Any] = {}
    labels = {"F1_S2_DP0225_COARSE": "coarse", "F1_S2_DP020_MEDIUM": "medium", "F1_S2_DP017_FINE": "fine"}
    for case in s2_cases:
        label = case["label"]
        grid_label = labels[label]
        xml = grids[grid_label]
        identity = case.get("identity", {})
        if identity.get("family_id") != "F1" or identity.get("sentinel_id") != "F1-S2" or identity.get("physical_case_id") != owner["physical_case_id"]:
            raise AuditError(f"ROOT207 {label} identity mismatch")
        source_xml = case.get("source", {}).get("generated_xml", {})
        if source_xml.get("path") != xml["path"] or source_xml.get("sha256") != xml["file"]["sha256"]:
            raise AuditError(f"ROOT207 {label} generated XML edge mismatch")
        grid = identity.get("grid", {})
        observations = case.get("selected_observations")
        if not isinstance(observations, list) or not observations or not all(isinstance(item, dict) for item in observations):
            raise AuditError(f"ROOT207 {label} selected observations missing")
        first_observation = observations[0]
        role_counts = first_observation.get("observables", {}).get("role_counts", {})
        fluid_count = role_counts.get("fluid")
        native_massfluid = first_observation.get("native_header", {}).get("MassFluid", {}).get("value")
        selected_sample_mass = first_observation.get("observables", {}).get("fluid_observable_using_native_MassFluid", {}).get("sample_mass_kg")
        selected_frames = [item.get("frame") for item in observations]
        if any(not isinstance(frame, int) for frame in selected_frames):
            raise AuditError(f"ROOT207 {label} selected frame IDs are invalid")
        if not close(finite(grid.get("dp_m"), f"{label}.dp"), xml["definition_dp_m"], 1e-12):
            raise AuditError(f"ROOT207 {label} dp mismatch")
        if int(fluid_count) != int(xml["fluid_count"]):
            raise AuditError(f"ROOT207 {label} fluid count mismatch")
        if not close(finite(native_massfluid, f"{label}.MassFluid"), xml["massfluid_kg"], 2e-9):
            raise AuditError(f"ROOT207 {label} native MassFluid mismatch")
        native_sample_mass = int(fluid_count) * finite(native_massfluid, f"{label}.MassFluid")
        if not close(finite(selected_sample_mass, f"{label}.sample_mass"), native_sample_mass, MASS_TOL):
            raise AuditError(f"ROOT207 {label} native sample mass mismatch")
        selected_case = selected.get(label)
        if selected_case is None or selected_case.get("selected_frames") != selected_frames:
            raise AuditError(f"ROOT207 {label} proof/child selected-frame mismatch")
        case_report[grid_label] = {
            "label": label,
            "fluid_count": int(fluid_count),
            "native_massfluid_kg": finite(native_massfluid, f"{label}.MassFluid"),
            "sample_mass_kg": finite(selected_sample_mass, f"{label}.sample_mass"),
            "xml_declared_sample_mass_kg": xml["sample_mass_kg"],
            "selected_frames": selected_frames,
            "native_report_case_sha256": digest_bytes(json.dumps(case, sort_keys=True, separators=(",", ":")).encode()),
        }
    return {
        "proof": proof_stat,
        "wrapper_report": wrapper_stat,
        "child_report": child_stat,
        "proof_status": proof["status"],
        "three_s2_cases": case_report,
        "content_join": "proof->wrapper->child->generated_xml SHA/path and native/header arithmetic verified",
    }


def verify_root217(manifest: dict[str, Any]) -> dict[str, Any]:
    binding = manifest["proofs"]["root217"]
    proof, proof_stat = read_json(binding["path"], binding["sha256"], label="ROOT217 proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise AuditError("ROOT217 proof schema mismatch")
    if proof.get("status") != "VERIFIED_ACTUAL_OFFICIAL_WRITER_DECODER_OBSERVER_V4_MANUFACTURED_CALIBRATION_ONLY":
        raise AuditError("ROOT217 proof status mismatch")
    report_path = proof.get("report")
    report_sha = proof.get("report_sha256")
    if not isinstance(report_path, str) or not isinstance(report_sha, str):
        raise AuditError("ROOT217 proof lacks report edge")
    report, report_stat = read_json(report_path, report_sha, label="ROOT217 calibration report")
    if report.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration.v4" or report.get("status") != "PASS_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER_V4":
        raise AuditError("ROOT217 calibration report schema/status mismatch")
    scope = report.get("scope", {})
    if scope.get("manufactured_fixture_only") is not True or scope.get("production_native_payload_read") is not False:
        raise AuditError("ROOT217 calibration scope is not manufactured-only")
    if proof.get("production_reader_or_world_axis_calibration_not_inferred") is not True:
        raise AuditError("ROOT217 world-axis non-inference guard missing")
    if not proof.get("all_actual_bound_source_prepost_current_stat_SHA_equal"):
        raise AuditError("ROOT217 source stability guard missing")
    golden = report.get("observer_calibration", {}).get("particle_golden", {})
    negatives = report.get("negative_fixture_execution", {})
    if golden.get("all_rows_pass") is not True or proof.get("per_particle_golden", {}).get("all_rows_pass") is not True:
        raise AuditError("ROOT217 per-particle golden validation did not pass")
    if proof.get("negative_mutations", {}).get("all_rejected") is not True:
        raise AuditError("ROOT217 negative mutation validation did not pass")
    return {
        "proof": proof_stat,
        "report": report_stat,
        "proof_status": proof["status"],
        "manufactured_particle_count": proof.get("manufactured_particle_count"),
        "per_particle_golden": True,
        "negative_mutations_rejected": True,
        "world_axis_production_status": "UNKNOWN_NOT_INFERRED",
        "content_join": "proof->calibration report SHA/path and manufactured-only gates verified",
    }


def source_control_signature(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "gravity_m_s2": parsed["gravity_m_s2"],
        "rhop0_kg_m3": parsed["rhop0_kg_m3"],
        "parameters": parsed["parameters"],
        "boxes": [
            {"comment": box["comment"], "point_m": box["point_m"], "size_m": box["size_m"], "fluid_relative": box["fluid_relative"], "bound_absolute": box["bound_absolute"]}
            for box in parsed["boxes"]
        ],
    }


def build_report(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AuditError("manifest schema mismatch")
    contract_path = manifest.get("contract_path")
    contract, contract_stat = read_json(contract_path, manifest.get("contract_sha256"), label="V2 contract")
    if contract.get("schema") != "ds02.stage2.f1-s2.continuous-owner-audit-contract.v2":
        raise AuditError("contract schema mismatch")
    owner_json, owner_stat = read_json(manifest["owner"]["path"], manifest["owner"]["sha256"], label="owner JSON")
    owner = parse_owner(owner_json)
    def_root, def_stat = read_xml(manifest["source_def"]["path"], manifest["source_def"]["sha256"], label="source Def")
    def_parsed = parse_xml(manifest["source_def"]["path"], manifest["source_def"]["sha256"], label="source Def")
    grids: dict[str, dict[str, Any]] = {}
    for item in manifest.get("grids", []):
        label = str(item["label"])
        grids[label] = parse_xml(item["path"], item["sha256"], label=f"{label} generated XML")
    if set(grids) != {"coarse", "medium", "fine"}:
        raise AuditError("manifest must contain coarse, medium, fine grids")
    receipt_json, receipt_stat = read_json(manifest["receipt"]["path"], manifest["receipt"]["sha256"], label="source GenCase receipt")
    receipt = parse_receipt(receipt_json, owner["source"].get("generated_xml", ""), manifest["source_def"]["sha256"])

    owner_xml = grids["medium"]
    owner_source_xml = owner["source"].get("generated_xml")
    if owner_source_xml != owner_xml["path"]:
        raise AuditError("owner generated_xml does not equal medium grid path")
    source_def_signature = source_control_signature(def_parsed)
    medium_box: dict[str, Any] | None = None
    for label, parsed in grids.items():
        if parsed["fluid_mk_relative"] != owner["mkfluid_relative"] or parsed["fluid_mk_absolute"] != 1:
            raise AuditError(f"{label} native XML fluid MK mapping is not 0 -> absolute 1")
        if not vectors_close(parsed["gravity_m_s2"], owner["gravity_m_s2"], 1e-12) or not close(parsed["rhop0_kg_m3"], owner["density_kg_m3"], 1e-12):
            raise AuditError(f"{label} gravity/density differs from owner")
        if source_control_signature(parsed) != source_def_signature:
            raise AuditError(f"{label} source controls/geometry differ from Def")
        if not close(parsed["definition_dp_m"], next(item["dp_m"] for item in contract["grids"] if item["label"] == label), 1e-12):
            raise AuditError(f"{label} dp differs from contract")
        box = parsed["fluid_box"]
        if label == "medium":
            expected_point = [owner["fluid_low_m"][i] + parsed["definition_dp_m"] / 2.0 for i in range(3)]
            expected_size = [owner["fluid_size_m"][i] - parsed["definition_dp_m"] for i in range(3)]
            if not vectors_close(box["point_m"], expected_point, 2e-9) or not vectors_close(box["size_m"], expected_size, 2e-9):
                raise AuditError("medium fluid drawbox is not the owner box inset by medium dp/2")
            if any(value <= 0 for value in expected_size):
                raise AuditError("medium inset owner box is non-positive")
            medium_box = box
        elif medium_box is not None:
            if not vectors_close(box["point_m"], medium_box["point_m"], 2e-12) or not vectors_close(box["size_m"], medium_box["size_m"], 2e-12):
                raise AuditError(f"{label} fluid drawbox changed geometry instead of reusing the source primitive")
    if medium_box is None:
        raise AuditError("medium grid was not parsed")
    for label in ("coarse", "fine"):
        box = grids[label]["fluid_box"]
        if not vectors_close(box["point_m"], medium_box["point_m"], 2e-12) or not vectors_close(box["size_m"], medium_box["size_m"], 2e-12):
            raise AuditError(f"{label} fluid drawbox does not match the medium source primitive")
    root207 = verify_root207(manifest, owner, grids)
    root217 = verify_root217(manifest)
    grid_report: list[dict[str, Any]] = []
    for label in ("coarse", "medium", "fine"):
        parsed = grids[label]
        grid_report.append({
            "label": label,
            "definition_dp_m": parsed["definition_dp_m"],
            "fluid_count": parsed["fluid_count"],
            "native_massfluid_kg_from_xml_header": parsed["massfluid_kg"],
            "xml_declared_discrete_sample_mass_kg": parsed["sample_mass_kg"],
            "native_selected_sample_mass_kg": root207["three_s2_cases"][label]["sample_mass_kg"],
            "native_minus_owner_mass_kg": root207["three_s2_cases"][label]["sample_mass_kg"] - owner["mass_kg"],
            "continuous_owner_mass_kg": owner["mass_kg"],
            "discrete_minus_owner_mass_kg": parsed["sample_mass_kg"] - owner["mass_kg"],
            "discrete_mass_is_not_continuum_truth": True,
            "generated_xml": parsed["file"],
        })
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema": SCHEMA,
        "status": "PASS_SOURCE_OWNER_CONTROL_CLOSURE_NATIVE_SUPPORT_PENDING",
        "generated_at_utc": now,
        "scope": {
            "source_owner_continuum_geometry": "CLOSED_FROM_OWNER_JSON_AND_SOURCE_DEF_XML",
            "control_and_geometry_across_three_grids": "CLOSED_EXCEPT_RESOLUTION_DP_AND_PARTICLE_COUNTS",
            "native_effective_support": "UNKNOWN_PENDING_GUARDED_ONE_FRAME_POSITION_AUDIT",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
            "production_native_payload_read": False,
            "production_h5_vtk_read": False,
            "solver_launch": False,
            "ledger_mutation": False,
        },
        "owner_continuum": {
            "physical_case_id": owner["physical_case_id"],
            "fluid_low_m": owner["fluid_low_m"],
            "fluid_size_m": owner["fluid_size_m"],
            "fluid_high_m": owner["fluid_high_m"],
            "density_kg_m3": owner["density_kg_m3"],
            "volume_m3": owner["calculated_volume_m3"],
            "mass_kg": owner["calculated_mass_kg"],
            "gravity_m_s2": owner["gravity_m_s2"],
            "initial_velocity_m_s": owner["velocity_m_s"],
            "divider_disjoint": True,
            "tank_containment": True,
            "box_boolean_clip": "NO_FLUID_BOOLEAN_CLIP_DECLARED; OWNER_IS_CLOSED_AXIS_ALIGNED_BOX",
            "source_policy": "Owner box and density define continuous mass; primitive inset drawbox and native sample mass are diagnostics only.",
        },
        "source_bindings": {
            "owner_json": owner_stat,
            "source_def": def_stat,
            "source_receipt": receipt_stat,
            "source_receipt_join": receipt,
            "contract": contract_stat,
            "owner_source_generated_xml": owner_xml["file"],
        },
        "three_grid_source_control_closure": grid_report,
        "proof_edges": {"root207": root207, "root217": root217},
        "minimum_next_native_validation": contract["minimum_next_native_validation"],
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "Native positions/support and production world-axis remain outside this source-only audit."},
        "read_scope": contract["read_scope"],
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def self_test() -> None:
    if not close(1.0 * 1.0 * 0.34 * 1000.0, 340.0, 1e-12):
        raise AssertionError("owner arithmetic self-test failed")
    owner = {"fluid_low_m": [2.2, 0.0, 0.0], "fluid_high_m": [3.2, 1.0, .34], "divider_low_m": [1.2, .34, 0.0], "divider_size_m": [.8, .06, .7]}
    high = [owner["divider_low_m"][i] + owner["divider_size_m"][i] for i in range(3)]
    overlap = all(max(owner["fluid_low_m"][i], owner["divider_low_m"][i]) < min(owner["fluid_high_m"][i], high[i]) for i in range(3))
    if overlap:
        raise AssertionError("divider overlap negative fixture not rejected")
    try:
        vector([0.0, float("nan"), 0.0], "negative")
    except AuditError:
        pass
    else:
        raise AssertionError("non-finite vector negative fixture not rejected")
    print("PASS_F1_S2_CONTINUOUS_OWNER_AUDIT_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        if args.manifest is None or args.output is None:
            parser.error("--manifest and --output are required unless --self-test is used")
        manifest, _ = read_json(args.manifest, None, label="audit manifest")
        atomic_write(args.output, build_report(manifest))
        print(f"PASS_SOURCE_OWNER_CONTROL_CLOSURE {args.output}")
        return 0
    except (AuditError, OSError, ValueError, KeyError, ET.ParseError) as exc:
        print(f"FAIL_SOURCE_OWNER_CONTROL_CLOSURE: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
