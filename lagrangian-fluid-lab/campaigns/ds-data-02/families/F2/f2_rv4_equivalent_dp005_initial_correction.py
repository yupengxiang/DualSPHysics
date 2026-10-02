#!/usr/bin/env python3
"""Additive correction sidecar for the RV4-equivalent DP005 initial audit.

The first audit already decoded both actual GenCase BI4 files with PartVTK.
This sidecar reads those immutable CSV/report bytes and makes two distinctions
explicit: initial fluid occupancy relative to the finite cup/receiver/tray,
and RV4-original-to-DP005 physical projection equality.  It does not rerun
PartVTK, GenCase, or a solver, and never edits the first audit report.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping


FAMILY_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002"
OLD_AUDIT = FAMILY_ROOT / "f2_rv4_equivalent_dp005.py"
RUNTIME_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
VENV_PYTHON = FAMILY_ROOT.parents[3] / ".venv/bin/python"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RV4_ROOT = INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs"
RV4_CASES = {
    "CENTER": {
        "case": "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
        "hash": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
    },
    "OFFSET": {
        "case": "F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
        "hash": "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef",
    },
}
DP = 0.005
FLUID_COUNT = 196608
CONTINUOUS_MASS = 24.576


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_old():
    spec = importlib.util.spec_from_file_location("f2_rv4eq_dp005_audit_source", OLD_AUDIT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen audit source: {OLD_AUDIT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def csv_rows(path: Path):
    import csv

    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        header = None
        for line in handle:
            if line.startswith("Pos.x [m]"):
                header = [item.strip() for item in line.split(",") if item.strip()]
                break
        if header is None:
            raise ValueError(f"PartVTK header missing: {path}")
        for row in csv.DictReader(handle, fieldnames=header):
            if row.get("Type"):
                yield row


def f(row: Mapping[str, str], key: str) -> float:
    return float(row[key])


def i(row: Mapping[str, str], key: str) -> int:
    return int(float(row[key]))


def rv4_paths(background: str) -> tuple[Path, Path]:
    case = RV4_CASES[background]["case"]
    directory = RV4_ROOT / case
    return directory / f"{case}.xml", directory / f"F2H10V2_{background}_V1_MEDIUM_motion.dat"


def case_correction(record: Mapping[str, Any], audit_root: Path, output_root: Path, old: Any) -> dict[str, Any]:
    case_id = str(record["case_id"])
    report = audit_root / case_id / "rv4-equivalent-dp005-initial-audit.json"
    report_data = json.loads(report.read_text(encoding="utf-8"))
    csv_path = Path(report_data["native_initial_population"]["csv"]["path"])
    generated_xml = Path(report_data["gencase"]["xml"]["path"])
    generated_motion = Path(report_data["gencase"]["motion"]["path"])
    receipt = Path(report_data["gencase"]["receipt"]["path"])
    metadata = json.loads(Path(record["metadata"]["path"]).read_text(encoding="utf-8"))
    new_xml = Path(record["definition"]["path"])
    new_motion = Path(record["motion"]["path"])
    background = str(record["background"])
    rv4_xml, rv4_motion = rv4_paths(background)

    boxes = old.declared_bound_boxes(new_xml)
    cup = next(item for item in boxes if item["mk"] == 0)
    receiver = next(item for item in boxes if item["mk"] == 1)
    tray = next(item for item in boxes if item["mk"] == 2)
    cup_low = cup["low_m"]
    cup_high = [low + size for low, size in zip(cup["low_m"], cup["size_m"])]
    receiver_high = [low + size for low, size in zip(receiver["low_m"], receiver["size_m"])]
    tray_high = [low + size for low, size in zip(tray["low_m"], tray["size_m"])]
    fluid_count = 0
    inside_cup = 0
    near_cup_face = 0
    receiver_overlap = 0
    tray_overlap = 0
    min_face_margin = [float("inf"), float("inf"), float("inf")]
    source_counts: dict[str, int] = {}
    typed_ids: set[tuple[int, int]] = set()
    for row in csv_rows(csv_path):
        typed_ids.add((i(row, "Zone"), i(row, "Idp")))
        if i(row, "Type") != 3:
            continue
        point = [f(row, f"Pos.{axis} [m]") for axis in "xyz"]
        fluid_count += 1
        source_counts[str(i(row, "Mk"))] = source_counts.get(str(i(row, "Mk")), 0) + 1
        margins = [point[index] - cup_low[index] for index in range(3)] + [cup_high[index] - point[index] for index in range(3)]
        for index in range(3):
            min_face_margin[index] = min(min_face_margin[index], margins[index], margins[index + 3])
        if all(cup_low[index] < point[index] < cup_high[index] for index in range(3)):
            inside_cup += 1
        if min(margins) <= DP / 2:
            near_cup_face += 1
        if all(receiver["low_m"][index] <= point[index] <= receiver_high[index] for index in range(3)):
            receiver_overlap += 1
        if all(tray["low_m"][index] <= point[index] <= tray_high[index] for index in range(3)):
            tray_overlap += 1

    rv4_projection = old.source_projection(rv4_xml, rv4_motion)
    new_projection = old.source_projection(new_xml, new_motion)
    output_projection = old.source_projection(generated_xml, generated_motion)
    rv4_to_new = old.equal_physical_contract(rv4_projection, new_projection)
    rv4_to_output = old.equal_physical_contract(rv4_projection, output_projection)
    checks = {
        "rv4_to_new_physical_projection_equal": rv4_to_new["physical_solids_controls_window_equal"],
        "rv4_to_generated_output_projection_equal": rv4_to_output["physical_solids_controls_window_equal"],
        "motion_bytes_equal_to_rv4": sha256(rv4_motion) == sha256(new_motion) == sha256(generated_motion),
        "actual_3d_and_fluid_count": report_data["checks"]["actual_3d"] and fluid_count == FLUID_COUNT,
        "all_fluid_strictly_inside_initial_cup": inside_cup == FLUID_COUNT,
        "no_fluid_within_dp_half_of_cup_face": near_cup_face == 0,
        "no_initial_receiver_overlap": receiver_overlap == 0,
        "no_initial_tray_overlap": tray_overlap == 0,
        "three_source_counts": source_counts == {"1": 65536, "2": 65536, "3": 65536},
        "typed_ids_unique": len(typed_ids) == len(report_data["native_initial_population"]["row_count"] and typed_ids),
    }
    # The last check is written explicitly so an empty/partial CSV cannot pass.
    checks["typed_ids_unique"] = len(typed_ids) == report_data["native_initial_population"]["row_count"]
    result = {
        "schema": "ds-data-02.f2.rv4-equivalent-dp005.initial-correction.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope_id": SCOPE_ID,
        "case_id": case_id,
        "background": background,
        "qualification_claim": "none; additive initial occupancy/equivalence evidence only",
        "production_claim": "none",
        "source_binding": {
            "first_audit_report": {"path": str(report), "sha256": sha256(report)},
            "partvtk_csv": {"path": str(csv_path), "sha256": sha256(csv_path)},
            "gencase_receipt": {"path": str(receipt), "sha256": sha256(receipt)},
            "rv4_xml": {"path": str(rv4_xml), "sha256": sha256(rv4_xml)},
            "rv4_motion": {"path": str(rv4_motion), "sha256": sha256(rv4_motion)},
            "dp005_definition": {"path": str(new_xml), "sha256": sha256(new_xml)},
            "dp005_motion": {"path": str(new_motion), "sha256": sha256(new_motion)},
            "physical_condition_hash": RV4_CASES[background]["hash"],
        },
        "physical_projection": {"rv4_to_dp005_source": rv4_to_new, "rv4_to_generated_output": rv4_to_output},
        "initial_occupancy": {
            "fluid_count": fluid_count,
            "inside_cup_strict_count": inside_cup,
            "cup_face_min_margin_m_by_axis": min_face_margin,
            "near_cup_face_count_within_dp_half": near_cup_face,
            "receiver_overlap_count": receiver_overlap,
            "tray_overlap_count": tray_overlap,
            "source_counts_by_native_mk": source_counts,
            "initial_moving_state_count": report_data["native_initial_population"]["moving_type1_mk17_count"],
            "pose_semantics": "initial t=0 moving cup native nodes are present; prescribed pose/control is bound by RV4 motion axis/window/file hash; no solver pose is inferred from this initial frame",
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "old_comm4_negative_remains_separate": True,
    }
    output = output_root / case_id / "rv4-equivalent-dp005-initial-correction.json"
    write_json(output, result)
    return {"case_id": case_id, "report": str(output), "report_sha256": sha256(output), "all_checks_pass": result["all_checks_pass"], "checks": checks, "occupancy": result["initial_occupancy"]}


def run(manifest_path: Path, audit_root: Path, output_root: Path) -> dict[str, Any]:
    old = load_old()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = [case_correction(record, audit_root, output_root, old) for record in manifest["cases"]]
    result = {"schema": "ds-data-02.f2.rv4-equivalent-dp005.initial-correction-manifest.v1", "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)}, "scope_id": SCOPE_ID, "cases": cases, "all_checks_pass": all(case["all_checks_pass"] for case in cases), "qualification_claim": "none", "production_claim": "none"}
    output = output_root / "rv4-equivalent-dp005-initial-correction-manifest.json"
    write_json(output, result)
    result["report"] = {"path": str(output), "sha256": sha256(output)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def make_request(manifest_path: Path, audit_root: Path, request_path: Path, attempt_id: str) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_files = [Path(__file__).resolve(), OLD_AUDIT.resolve(), RUNTIME_V2.resolve(), manifest_path.resolve()]
    for record in manifest["cases"]:
        first = audit_root / record["case_id"] / "rv4-equivalent-dp005-initial-audit.json"
        first_data = json.loads(first.read_text(encoding="utf-8"))
        input_files.extend([Path(record["definition"]["path"]), Path(record["motion"]["path"]), Path(record["metadata"]["path"]), first, Path(first_data["native_initial_population"]["csv"] ["path"]), Path(first_data["gencase"]["xml"]["path"]), Path(first_data["gencase"]["motion"]["path"]), Path(first_data["gencase"]["receipt"]["path"]), *rv4_paths(record["background"])] )
    unique: list[Path] = []
    seen: set[str] = set()
    for path in input_files:
        path = path.resolve()
        if str(path) not in seen:
            seen.add(str(path))
            if not path.is_file():
                raise FileNotFoundError(path)
            unique.append(path)
    request = {
        "schema": "ds-data-02.runner.request.v1", "family_id": FAMILY_ID, "case_id": "F2_RV4EQ_DP005_INITIAL_CORRECTION", "attempt_id": attempt_id,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 4, "max_wall_seconds": 600, "estimated_storage_bytes": 2 * 1024**3,
        "command": [str(VENV_PYTHON.resolve()), str(Path(__file__).resolve()), "audit", "--manifest", str(manifest_path.resolve()), "--audit-root", str(audit_root.resolve()), "--report-root", "{attempt_root}/correction"],
        "cwd": str(FAMILY_ROOT.resolve()), "raw_output_root": str((DATA_ROOT / "families/F2/F2_RV4EQ_DP005_INITIAL_CORRECTION").resolve()), "worktree_root": str(FAMILY_ROOT.parents[4].resolve()), "solver_launch_forbidden": True, "scope_id": SCOPE_ID,
        "input_files": [str(path) for path in unique], "input_sha256": {str(path): sha256(path) for path in unique}, "request_note": "Read-only additive sidecar over completed PartVTK initial CSVs; no GenCase/solver/GPU/Q-I/Q-N/production claim.",
    }
    write_json(request_path, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_request = sub.add_parser("make-request")
    p_request.add_argument("--manifest", type=Path, required=True)
    p_request.add_argument("--audit-root", type=Path, required=True)
    p_request.add_argument("--request", type=Path, required=True)
    p_request.add_argument("--attempt-id", default="audit-f2-rv4eq-dp005-initial-correction-20261002-001")
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--manifest", type=Path, required=True)
    p_audit.add_argument("--audit-root", type=Path, required=True)
    p_audit.add_argument("--report-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "make-request":
        request = make_request(args.manifest.resolve(), args.audit_root.resolve(), args.request.resolve(), args.attempt_id)
        print(json.dumps({"status": "written", "request": str(args.request.resolve()), "input_count": len(request["input_files"])}, ensure_ascii=False, indent=2))
        return 0
    result = run(args.manifest.resolve(), args.audit_root.resolve(), args.report_root.resolve())
    return 0 if result["all_checks_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
