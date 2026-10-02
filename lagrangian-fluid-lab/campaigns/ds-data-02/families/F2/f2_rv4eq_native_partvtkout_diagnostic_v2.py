#!/usr/bin/env python3
"""Decode native RV4EQ DP005 exclusions with the official PartVTKOut tool.

This is an additive, read-only audit for the two completed four-second RV4EQ
DP005 baseline solver views.  It deliberately does not require an H5
conversion: the native PartOut ledger, RunPARTs timeline, generated XML, and
the official ``PartVTKOut_linux64`` export are sufficient to record each
excluded ``Idp`` with its first missing frame, time, Motive, position, velocity,
density, typed identity, and domain/finite-geometry evidence.

Every exclusion remains ``native_solver_excluded_numerical_unknown``.  A
position-only exclusion is never interpreted as physical spill, receiver
arrival, cup departure, or wall penetration.  Moving-body pose closure and
full-frame lifecycle labels are deferred to the separate H5/full-frame
postprocess handoff.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


FAMILY_ROOT = Path(__file__).resolve().parent
LEGACY_HELPERS = FAMILY_ROOT / "f2_handoff_20261002_dp005_native_diagnostic_v1.py"
DIAGNOSTIC_HELPER = FAMILY_ROOT / "f2_native_resolution_diagnostic.py"
SCHEMA = "ds-data-02.f2.rv4eq-native-partvtkout-diagnostic.v2"


class DiagnosticError(RuntimeError):
    """Raised when a completed native source is not auditable."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Any, label: str) -> Path:
    candidate = Path(str(path)).expanduser().resolve()
    if not candidate.is_file():
        raise DiagnosticError(f"{label} is missing: {candidate}")
    return candidate


def load_json(path: Any, label: str) -> dict[str, Any]:
    candidate = require_file(path, label)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DiagnosticError(f"{label} must be a JSON object: {candidate}")
    return value


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def binding(path: Path, *, role: str | None = None) -> dict[str, Any]:
    path = require_file(path, role or "source input")
    result = {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
    if role is not None:
        result["role"] = role
    return result


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise DiagnosticError(f"cannot import helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def typed_ranges(xml_path: Path) -> list[dict[str, Any]]:
    """Read exact type/Mk ranges from generated XML, not a dataset label."""
    root = ET.parse(xml_path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise DiagnosticError(f"generated XML has no particles section: {xml_path}")
    ranges: list[dict[str, Any]] = []
    for tag, type_id in (("fixed", 0), ("moving", 1), ("fluid", 3)):
        for node in particles.findall(f"./{tag}"):
            try:
                begin = int(node.attrib["begin"])
                count = int(node.attrib["count"])
                mk_key = "mkbound" if tag in {"fixed", "moving"} else "mkfluid"
                mk = int(node.attrib[mk_key])
            except (KeyError, TypeError, ValueError) as error:
                raise DiagnosticError(f"invalid typed range in {xml_path}: {ET.tostring(node, encoding='unicode')}") from error
            if count <= 0:
                raise DiagnosticError(f"empty typed range in {xml_path}: {ET.tostring(node, encoding='unicode')}")
            ranges.append({
                "low": begin,
                "high": begin + count - 1,
                "type": type_id,
                "mk": mk,
                "source": tag,
            })
    if not ranges:
        raise DiagnosticError(f"generated XML has no typed ranges: {xml_path}")
    ranges.sort(key=lambda item: (int(item["low"]), int(item["high"]), int(item["type"]), int(item["mk"])))
    previous_high = -1
    for item in ranges:
        if int(item["low"]) <= previous_high:
            raise DiagnosticError(f"overlapping typed ranges in {xml_path}: {ranges}")
        previous_high = int(item["high"])
    return ranges


def typed_identity(idp: int, ranges: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    matches = [item for item in ranges if int(item["low"]) <= idp <= int(item["high"])]
    if len(matches) != 1:
        return {
            "status": "unknown",
            "idp": int(idp),
            "matching_ranges": [dict(item) for item in matches],
        }
    item = matches[0]
    return {
        "status": "resolved",
        "idp": int(idp),
        "type": int(item["type"]),
        "mk": int(item["mk"]),
        "source": str(item["source"]),
        "range": dict(item),
    }


def classify_domain(position: list[float], signature: Mapping[str, Any], dp_m: float) -> dict[str, Any]:
    evidence = signature.get("simulation_domain")
    if not isinstance(evidence, Mapping):
        return {"status": "domain_undeclared", "declared": None}
    low = [float(value) for value in evidence["low_m"]]
    high = [float(value) for value in evidence["high_m"]]
    distances = {
        f"{axis}{side}": (position[index] - low[index] if side == "-" else high[index] - position[index])
        for index, axis in enumerate(("x", "y", "z"))
        for side in ("-", "+")
    }
    tolerance = max(2.0 * float(dp_m), 1e-6)
    outside_faces = sorted(name for name, distance in distances.items() if distance < 0.0)
    near_faces = sorted(name for name, distance in distances.items() if 0.0 <= distance <= tolerance)
    return {
        "status": "outside_domain" if outside_faces else "inside_domain",
        "declared_low_m": low,
        "declared_high_m": high,
        "inside_without_tolerance": not outside_faces,
        "outside_faces": outside_faces,
        "near_faces_within_2dp": near_faces,
        "signed_face_distances_m": distances,
        "tolerance_m": tolerance,
        "interpretation": "domain position evidence only; no physical fate inferred",
    }


def finite_geometry(position: list[float], signature: Mapping[str, Any], dp_m: float) -> dict[str, Any]:
    boxes = {int(item["mk"]): item for item in signature.get("boundary_boxes", [])}
    result: dict[str, Any] = {}
    tolerance = max(2.0 * float(dp_m), 1e-6)
    for mk, name in ((0, "moving_cup_initial_aabb"), (1, "receiver_aabb"), (2, "tray_aabb")):
        box = boxes.get(mk)
        if not isinstance(box, Mapping):
            result[name] = {"declared": False}
            continue
        low = [float(value) for value in box["point_m"]]
        high = [low[index] + float(box["size_m"][index]) for index in range(3)]
        inside = all(low[index] - tolerance <= position[index] <= high[index] + tolerance for index in range(3))
        outside_distance = 0.0
        for index, value in enumerate(position):
            if value < low[index]:
                outside_distance += (low[index] - value) ** 2
            elif value > high[index]:
                outside_distance += (value - high[index]) ** 2
        result[name] = {
            "declared": True,
            "inside_initial_aabb_with_2dp": inside,
            "distance_to_initial_aabb_m": outside_distance ** 0.5,
            "declared_low_m": low,
            "declared_high_m": high,
            "note": "moving cup uses initial AABB only; interpolated pose is deferred to full-frame postprocess",
        }
    return result


def audit_case(case: Mapping[str, Any], *, helper: Any, legacy: Any, partvtkout: Path, output_root: Path) -> dict[str, Any]:
    case_id = str(case["case_id"])
    xml_path = require_file(case["generated_xml"], f"{case_id} generated XML")
    motion_path = require_file(case["motion"], f"{case_id} motion control")
    runparts_path = require_file(case["runparts"], f"{case_id} RunPARTs.csv")
    solver_receipt_path = require_file(case["solver_receipt"], f"{case_id} solver receipt")
    gencase_receipt_path = require_file(case["gencase_receipt"], f"{case_id} GenCase receipt")
    data_dir = require_file(Path(str(case["data_dir"])) / "PartOut_000.obi4", f"{case_id} PartOut_000.obi4").parent
    partinfo = require_file(data_dir / "PartInfo.ibi4", f"{case_id} PartInfo.ibi4")
    solver_receipt = load_json(solver_receipt_path, f"{case_id} solver receipt")
    if solver_receipt.get("status") != "completed" or solver_receipt.get("returncode") != 0:
        raise DiagnosticError(f"{case_id} solver receipt is not completed/code0")
    ranges = typed_ranges(xml_path)
    signature = legacy.geometry_signature(xml_path)
    motion = legacy.motion_values(motion_path)
    steps = legacy.runparts(runparts_path)
    if len(steps) != int(case.get("expected_frames", 401)):
        raise DiagnosticError(f"{case_id} RunPARTs has {len(steps)} rows, expected {case.get('expected_frames', 401)}")
    artifact_dir = output_root / "artifacts" / "partvtkout" / case_id
    exclusion = helper.decode_exclusions(binary=partvtkout, data_dir=data_dir, output_dir=artifact_dir, prefix="excluded_particles")
    records_dir = output_root / "artifacts" / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    enriched_path = records_dir / f"{case_id}.jsonl"
    motive_totals: Counter[str] = Counter()
    type_totals: Counter[str] = Counter()
    mk_totals: Counter[str] = Counter()
    domain_face_totals: Counter[str] = Counter()
    unresolved_parts: list[int] = []
    records: list[dict[str, Any]] = []
    with enriched_path.open("w", encoding="utf-8") as handle:
        for raw in exclusion["rows"]:
            part = int(raw["part_out"])
            time_s = steps[part]["time_s"] if 0 <= part < len(steps) else None
            if time_s is None:
                unresolved_parts.append(part)
            identity = typed_identity(int(raw["idp"]), ranges)
            domain = classify_domain(list(raw["position_m"]), signature, float(case["dp_m"]))
            geometry = finite_geometry(list(raw["position_m"]), signature, float(case["dp_m"]))
            for face in domain.get("outside_faces", []) + domain.get("near_faces_within_2dp", []):
                domain_face_totals[str(face)] += 1
            motive_totals[str(raw["motive"])] += 1
            type_totals[str(identity.get("type", "unknown"))] += 1
            mk_totals[str(identity.get("mk", "unknown"))] += 1
            record = {
                "idp": int(raw["idp"]),
                "typed_identity": identity,
                "part_out": part,
                "first_missing_frame": part,
                "first_missing_time_s": time_s,
                "motive": int(raw["motive"]),
                "motive_class": "native_solver_excluded_numerical_unknown",
                "position_m": list(raw["position_m"]),
                "velocity_m_s": list(raw["velocity_m_s"]),
                "density_kg_m3": float(raw["density_kg_m3"]),
                "domain_position_evidence": domain,
                "finite_geometry_position_evidence": geometry,
                "physical_fate": "unknown",
            }
            handle.write(json.dumps(jsonable(record), ensure_ascii=False, sort_keys=True) + "\n")
            records.append(record)
    np_out = int(sum(row["NpOut"] for row in steps))
    np_out_pos = int(sum(row["NpOutPos"] for row in steps))
    np_out_rho = int(sum(row["NpOutRho"] for row in steps))
    np_out_mov = int(sum(row["NpOutMov"] for row in steps))
    source_paths = [
        FAMILY_ROOT / Path(__file__).name,
        LEGACY_HELPERS,
        DIAGNOSTIC_HELPER,
        xml_path,
        motion_path,
        runparts_path,
        solver_receipt_path,
        gencase_receipt_path,
        data_dir / "PartOut_000.obi4",
        partinfo,
        enriched_path,
    ]
    source_bindings = {str(path.resolve()): binding(path) for path in source_paths}
    source_bindings.update({item["path"]: item for item in exclusion.get("outputs", [])})
    return {
        "case_id": case_id,
        "background": str(case.get("background", "")),
        "physical_case_id": str(case.get("physical_case_id", "")),
        "mechanism_id": str(case.get("mechanism_id", "")),
        "dp_m": float(case["dp_m"]),
        "physical_condition_hash": case.get("physical_condition_hash"),
        "source_bindings": source_bindings,
        "typed_identity_ranges": ranges,
        "generated_xml_signature": signature,
        "motion_signature": {key: value for key, value in motion.items() if key != "values"},
        "native_timeline": {
            "path": str(runparts_path),
            "sha256": sha256(runparts_path),
            "rows": len(steps),
            "first_time_s": steps[0]["time_s"],
            "last_time_s": steps[-1]["time_s"],
            "expected_save_interval_s": float(case.get("expected_save_interval_s", 0.01)),
            "full_window_completed": len(steps) == int(case.get("expected_frames", 401)) and abs(float(steps[-1]["time_s"]) - 4.0) < 1e-3,
            "NpOut_sum": np_out,
            "NpOutPos_sum": np_out_pos,
            "NpOutRho_sum": np_out_rho,
            "NpOutMov_sum": np_out_mov,
        },
        "partvtkout_exclusions": {
            "binary": exclusion["binary"],
            "command": exclusion["command"],
            "returncode": exclusion["returncode"],
            "row_count": len(records),
            "row_count_equals_runparts_NpOutPos_sum": len(records) == np_out_pos,
            "motive_totals": dict(sorted(motive_totals.items())),
            "typed_type_totals": dict(sorted(type_totals.items())),
            "typed_mk_totals": dict(sorted(mk_totals.items())),
            "domain_face_evidence_totals": dict(sorted(domain_face_totals.items())),
            "unresolved_first_missing_parts": sorted(set(unresolved_parts)),
            "raw_outputs": exclusion.get("outputs", []),
            "enriched_records": {"path": str(enriched_path), "sha256": sha256(enriched_path), "rows": len(records)},
            "records": records,
            "all_rows_are_native_numerical_unknown": True,
        },
        "moving_boundary_pose": {
            "status": "deferred_fullframe_postprocess",
            "motion_control": {"path": str(motion_path), "sha256": sha256(motion_path)},
            "native_partvtkout_has_no_interpolated_rigid_pose": True,
            "no_cup_departure_or_physical_spill_claim": True,
        },
        "interpretation": {
            "motive_is_not_physical_spill": True,
            "position_near_domain_face_is_not_physical_spill": True,
            "position_outside_domain_is_not_physical_wall_penetration_without_pose_and_face_closure": True,
            "receiver_tray_membership_is_geometry_side_evidence_only": True,
            "initial_mass_or_excluded_mass_not_normalized": True,
            "qualification_claim": "none",
            "production_claim": "none",
            "scientific_status": "native_exclusions_decoded_pending_fullframe_pose_and_fate_review",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--partvtkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = require_file(args.manifest, "RV4 native PartVTKOut manifest")
    manifest = load_json(manifest_path, "RV4 native PartVTKOut manifest")
    if manifest.get("schema") != f"{SCHEMA}-input":
        raise DiagnosticError(f"unexpected manifest schema: {manifest.get('schema')!r}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or {str(case.get("background")) for case in cases} != {"CENTER", "OFFSET"}:
        raise DiagnosticError("manifest must contain exactly CENTER and OFFSET cases")
    partvtkout = require_file(args.partvtkout, "official PartVTKOut_linux64")
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    helper = import_module(DIAGNOSTIC_HELPER, "f2_native_resolution_diagnostic_v2")
    legacy = import_module(LEGACY_HELPERS, "f2_native_diagnostic_legacy_v1")
    report = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": binding(manifest_path),
        "official_tool": binding(partvtkout, role="native exclusion decoder"),
        "cases": [audit_case(case, helper=helper, legacy=legacy, partvtkout=partvtkout, output_root=output.parent / "artifacts") for case in cases],
        "status": "diagnostic_complete_pending_scientific_review",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    output.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "path": str(output), "sha256": sha256(output), "case_count": len(report["cases"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
