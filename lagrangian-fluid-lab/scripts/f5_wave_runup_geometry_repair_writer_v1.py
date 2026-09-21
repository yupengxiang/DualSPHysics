#!/usr/bin/env python3
"""Materialize the root-reviewed F5 v3 geometry-repair input.

Only the Definition-relative input identity is written here.  The script
cannot invoke GenCase, the native decoder, a solver, CUDA, a queue, or any
scientific registry.  The following CPU/native preflight is a separate,
single-use command bound to the root-review and this contract.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1"
INPUT = ROOT / "input"
ROOT_REVIEW = ROOT / "root-review-receipt-v1.json"
PROPOSAL = ROOT / "geometry-repair-proposal-audit-v1.json"
SOURCE_DIR = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/17_WaveRunup"
SOURCE_DEFINITION = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/F5_wave_runup_q0p50_dp0p0075_Def.xml"
CONTRACT = INPUT / "geometry-repair-contract-v1.json"
MATERIALIZATION_AUDIT = ROOT / "materialization-audit-v1/invalid-materialization-audit-v1.json"
WRITER = LAB / "scripts/f5_wave_runup_geometry_repair_writer_v1.py"

CASE_ID = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v3"
DEFINITION_NAME = f"{CASE_ID}_Def.xml"
MOTION_NAME = "Mov_piston_q0p50_scaled_geomrepair_v3.dat"
SLOPE_NAME = "Slope_geomrepair_v3.stl"
BLOCKS_NAME = "Blocks_3D_scaled_geomrepair_v3.stl"
DEFINITION = INPUT / DEFINITION_NAME
MOTION = INPUT / MOTION_NAME
SLOPE = INPUT / SLOPE_NAME
BLOCKS = INPUT / BLOCKS_NAME
Q = 0.5
PISTON_SCALE = 1.0
DP = 0.0075
TIME_MAX = 16.0
OUTPUT_DT = 0.02


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _verify_root_review() -> dict[str, Any]:
    review = load(ROOT_REVIEW)
    if review.get("schema") != "core.f5.third_t1.geometry_repair_root_review_receipt.v1":
        raise ValueError("wrong F5 geometry repair root-review schema")
    decision = review.get("review_decision", {})
    if review.get("status") != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("geometry repair root review is not active")
    if decision.get("authorized_definition_materialization") is not True or decision.get("authorized_cpu_native_preflight") is not True:
        raise ValueError("root review does not authorize v3 materialization and preflight")
    if any(decision.get(key) for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("root review opens a forbidden path")
    for item in review.get("hash_bindings", {}).values():
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"stale root-review hash binding: {path}")
    return review


def _verify_proposal() -> dict[str, Any]:
    proposal = load(PROPOSAL)
    if proposal.get("schema") != "core.f5.third_t1.geometry_repair_proposal_audit.v1" or proposal.get("qualification_claim") != "none":
        raise ValueError("geometry repair proposal is not zero-credit")
    return proposal


def _motion(source: Path, target: Path, scale: float) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        fields = raw.split()
        if not fields or fields[0].startswith("#"):
            continue
        if len(fields) < 2:
            raise ValueError(f"motion row {line_number} has fewer than two fields")
        time_s, displacement = float(fields[0]), float(fields[1])
        if rows and time_s < rows[-1][0]:
            raise ValueError("motion times are not non-decreasing")
        rows.append((time_s, displacement * scale))
    if not rows or rows[0][0] != 0.0 or rows[-1][0] < 15.0:
        raise ValueError("official motion does not cover the registered source window")
    target.write_text("".join(f"{time_s:.10f} {displacement:.10f}\n" for time_s, displacement in rows), encoding="utf-8")
    return {"source": bind(source, "official piston source"), "output": bind(target, "fresh v3 piston motion"),
            "row_count": len(rows), "time_start_s": rows[0][0], "time_end_s": rows[-1][0], "scale": scale}


def _transformed_draw(file_name: str, *, autofill: bool) -> ET.Element:
    attrs = {"file": file_name}
    if autofill:
        attrs["autofill"] = "true"
    node = ET.Element("drawfilestl", attrs)
    ET.SubElement(node, "drawmove", {"x": "5.95", "y": "0.37", "z": "0.0"})
    ET.SubElement(node, "drawrotate", {"angx": "0", "angy": "0", "angz": "-90"})
    return node


def _insert_before(commands: list[ET.Element], target: ET.Element, nodes: list[ET.Element]) -> None:
    index = commands.index(target)
    for offset, node in enumerate(nodes):
        target_parent = target.getparent() if hasattr(target, "getparent") else None
        # ElementTree has no getparent; the caller inserts by rebuilding the
        # mainlist after this helper returns.
        if target_parent is not None:  # pragma: no cover - stdlib ET path
            target_parent.insert(index + offset, node)


def _definition(source: Path, target: Path) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None or definition.get("dp") != f"{DP:.9g}":
        raise ValueError("source v2 Definition has unexpected dp")
    motion_ref = root.find("./casedef/motion/objreal/mvpredef/file")
    if motion_ref is None:
        raise ValueError("source Definition has no piston motion reference")
    motion_ref.set("name", MOTION_NAME)
    params = {node.get("key"): node for node in root.findall("./execution/parameters/parameter")}
    if params.get("TimeMax") is None or params.get("TimeOut") is None:
        raise ValueError("source Definition lacks time parameters")
    params["TimeMax"].set("value", f"{TIME_MAX:.9g}")
    params["TimeOut"].set("value", f"{OUTPUT_DT:.9g}")
    gauges = root.find("./execution/special/gauges/default")
    if gauges is None:
        raise ValueError("source Definition lacks gauge defaults")
    for tag in ("computedt", "outputdt"):
        node = gauges.find(tag)
        if node is None:
            raise ValueError(f"source Definition lacks {tag}")
        node.set("value", f"{OUTPUT_DT:.9g}")
    for tag in ("computetime", "outputtime"):
        node = gauges.find(tag)
        if node is None:
            raise ValueError(f"source Definition lacks {tag}")
        node.set("start", "0")
        node.set("end", f"{TIME_MAX:.9g}")

    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("source Definition lacks geometry mainlist")
    old = list(mainlist)
    slope = next((node for node in old if node.tag == "drawfilestl" and node.get("file") == "Slope.stl"), None)
    blocks = next((node for node in old if node.tag == "drawfilestl" and node.get("file") == "Blocks_3D_scaled.stl"), None)
    if slope is None or blocks is None:
        raise ValueError("source Definition lacks both physical STL draws")
    slope.set("file", SLOPE_NAME)
    blocks.set("file", BLOCKS_NAME)
    if slope.get("autofill") is not None or blocks.get("autofill") is not None:
        raise ValueError("source physical STL draw unexpectedly has autofill")
    slope_index = old.index(slope)
    blocks_index = old.index(blocks)
    if blocks_index <= slope_index:
        raise ValueError("source STL order changed")
    rebuilt: list[ET.Element] = []
    for index, node in enumerate(old):
        if index == slope_index:
            if rebuilt and rebuilt[-1].tag == "setmkbound" and rebuilt[-1].get("mk") == "40":
                rebuilt.pop()
            rebuilt.extend([ET.Element("setmkvoid"), _transformed_draw(SLOPE_NAME, autofill=True)])
            rebuilt.append(ET.Element("setmkbound", {"mk": "40"}))
        if index == blocks_index:
            if rebuilt and rebuilt[-1].tag == "setmkbound" and rebuilt[-1].get("mk") == "50":
                rebuilt.pop()
            rebuilt.extend([ET.Element("setmkvoid"), _transformed_draw(BLOCKS_NAME, autofill=True)])
            rebuilt.append(ET.Element("setmkbound", {"mk": "50"}))
        rebuilt.append(node)
    mainlist[:] = rebuilt
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    # Reparse to ensure the written file has no accidental ElementTree-only state.
    out_root = ET.parse(target).getroot()
    out_commands = list(out_root.findall("./casedef/geometry/commands/mainlist/*"))
    slope_draws = [node for node in out_commands if node.tag == "drawfilestl" and node.get("file") == SLOPE_NAME]
    block_draws = [node for node in out_commands if node.tag == "drawfilestl" and node.get("file") == BLOCKS_NAME]
    if len(slope_draws) != 2 or len(block_draws) != 2:
        raise ValueError("v3 Definition does not contain one autofill and one physical draw per STL")
    for name, draws in ((SLOPE_NAME, slope_draws), (BLOCKS_NAME, block_draws)):
        if sum(node.get("autofill") == "true" for node in draws) != 1:
            raise ValueError(f"v3 {name} autofill count is not one")
        if any(node.get("autofill") is not None and node.get("autofill") != "true" for node in draws):
            raise ValueError(f"v3 {name} has unexpected autofill value")
    return {"source": bind(source, "prior v2 Definition template"), "output": bind(target, "fresh v3 geometry-repair Definition"),
            "dp_m": DP, "time_max_s": TIME_MAX, "output_interval_s": OUTPUT_DT,
            "motion_file": MOTION_NAME, "slope_file": SLOPE_NAME, "blocks_file": BLOCKS_NAME,
            "autofill_draws": 2, "physical_boundary_draws": 2, "void_precursors": 2}


def build(*, repair_invalid_materialization: bool = False) -> dict[str, Any]:
    review = _verify_root_review()
    proposal = _verify_proposal()
    if INPUT.exists() and any(INPUT.iterdir()):
        if not repair_invalid_materialization or not MATERIALIZATION_AUDIT.is_file():
            raise FileExistsError(f"v3 input directory already contains files: {INPUT}")
    INPUT.mkdir(parents=True, exist_ok=True)
    for path in (DEFINITION, MOTION, SLOPE, BLOCKS, CONTRACT):
        if path.exists() and not repair_invalid_materialization:
            raise FileExistsError(path)
    motion = _motion(SOURCE_DIR / "Mov_piston.dat", MOTION, PISTON_SCALE)
    definition = _definition(SOURCE_DEFINITION, INPUT / DEFINITION_NAME)
    shutil.copy2(SOURCE_DIR / "Slope.stl", SLOPE)
    shutil.copy2(SOURCE_DIR / "Blocks_3D_scaled.stl", BLOCKS)
    assets = [bind(SLOPE, "byte-identical renamed v3 slope source"), bind(BLOCKS, "byte-identical renamed v3 blocks source")]
    result = {
        "schema": "core.f5.third_t1.geometry_repair_materialization.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "v3_definition_written_preflight_pending_after_static_repair" if repair_invalid_materialization else "v3_definition_written_preflight_pending",
        "qualification_claim": "none",
        "candidate": {"family": "F5", "scope_id": "F5_prescribed_wave_runup_x_v1", "revision_id": "F5_piston_amplitude_runup_geomrepair_v3",
                      "q": Q, "piston_scale": PISTON_SCALE, "dp_m": DP, "case_id": CASE_ID},
        "repair_lineage": {"root_review": bind(ROOT_REVIEW, "geometry repair root review"),
                            "proposal": bind(PROPOSAL, "geometry repair proposal"),
                            "materialization_audit": bind(MATERIALIZATION_AUDIT, "preflight-free static materialization correction") if repair_invalid_materialization else None,
                            "prior_output_reused": False, "prior_generated_input_reused": False, "prior_trajectory_reused": False,
                            "hypothesis": "explicit setmkvoid plus autofill precursor before unchanged physical STL boundary redraw"},
        "fresh_identity": {"definition": definition, "motion": motion, "definition_adjacent_assets": assets,
                           "input_directory": rel(INPUT), "preflight_output_prefix": "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/preflight-v3/generated/F5_wave_runup_q0p50_dp0p0075_geomrepair_v3"},
        "fixed_contract": {"denominator_rows": 15, "time_max_s": TIME_MAX, "output_interval_s": OUTPUT_DT, "gauge_interval_s": OUTPUT_DT,
                           "event_window_required": True, "zero_credit_until_cpu_native_and_solver_reviews": True, "same_input_retry": False},
        "geometry_recipe": {"void_precursor_commands": ["setmkvoid", f"drawfilestl {SLOPE_NAME} autofill=true", "setmkbound mk=40", f"drawfilestl {SLOPE_NAME}",
                                                                "setmkvoid", f"drawfilestl {BLOCKS_NAME} autofill=true", "setmkbound mk=50", f"drawfilestl {BLOCKS_NAME}"],
                            "transforms_preserved": True, "source_assets_byte_identical": True, "thresholds_changed": False},
        "authorization": {"root_review": bind(ROOT_REVIEW, "exact root review authorization"), "definition_written": True, "motion_written": True,
                           "gencase_authorized_by_this_step": False, "native_decode_authorized_by_this_step": False, "solver_authorized": False,
                           "gpu_authorized": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_mutation": 0},
        "implementation": bind(WRITER, "v3 geometry repair writer"),
        "execution_controls": {"definition_written": True, "motion_written": True, "assets_copied": True, "gencase_invoked": False,
                               "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False, "queue_mutation": 0,
                               "ledger_mutation": 0, "registry_mutation": 0, "matrix_mutation": 0, "qualification_credit": 0},
    }
    CONTRACT.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def verify(path: Path = CONTRACT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f5.third_t1.geometry_repair_materialization.v1" or value.get("qualification_claim") != "none":
        raise ValueError("wrong v3 materialization contract")
    if value.get("execution_controls", {}).get("gencase_invoked") is not False or value.get("execution_controls", {}).get("solver_invoked") is not False:
        raise ValueError("v3 materialization claims execution")
    if value.get("execution_controls", {}).get("qualification_credit") != 0:
        raise ValueError("v3 materialization carries scientific credit")
    for item in (value.get("repair_lineage", {}).get("root_review"), value.get("repair_lineage", {}).get("proposal"), value.get("implementation")):
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"stale v3 contract binding: {path}")
    for item in value.get("fresh_identity", {}).get("definition_adjacent_assets", []):
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"stale v3 asset binding: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--repair-invalid-materialization", action="store_true")
    args = parser.parse_args()
    value = verify() if args.verify else build(repair_invalid_materialization=args.repair_invalid_materialization)
    if not args.verify:
        verify()
    print(json.dumps({"status": value["status"], "contract": rel(CONTRACT), "sha256": sha256(CONTRACT),
                      "definition": rel(DEFINITION), "solver_invoked": False, "gpu_started": False, "matrix_credit": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
