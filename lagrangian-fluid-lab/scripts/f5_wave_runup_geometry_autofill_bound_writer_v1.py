#!/usr/bin/env python3
"""Materialize the v4 official-autofill-bound F5 input identity."""

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
INPUT = ROOT / "v4-input"
ROOT_REVIEW = ROOT / "autofill-bound-root-review-v1.json"
PROPOSAL = ROOT / "geometry-repair-proposal-audit-v1.json"
V3_PREFLIGHT = ROOT / "preflight-v3/preflight.json"
SOURCE_DIR = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/17_WaveRunup"
SOURCE_DEFINITION = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/F5_wave_runup_q0p50_dp0p0075_Def.xml"
WRITER = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_writer_v1.py"
CONTRACT = INPUT / "geometry-autofill-bound-contract-v1.json"
CASE_ID = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v4"
DEFINITION_NAME = f"{CASE_ID}_Def.xml"
MOTION_NAME = "Mov_piston_q0p50_scaled_geomrepair_v4.dat"
SLOPE_NAME = "Slope_geomrepair_v4.stl"
BLOCKS_NAME = "Blocks_3D_scaled_geomrepair_v4.stl"
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
    if review.get("schema") != "core.f5.third_t1.geometry_autofill_bound_root_review_receipt.v1":
        raise ValueError("wrong v4 root-review schema")
    decision = review.get("review_decision", {})
    if review.get("status") != "authorized_one_fresh_v4_cpu_native_preflight_only" or decision.get("authorized_definition_materialization") is not True:
        raise ValueError("v4 materialization is not authorized")
    if any(decision.get(key) for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("v4 root review opens a forbidden path")
    for item in review.get("hash_bindings", {}).values():
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"stale v4 root-review binding: {path}")
    return review


def _motion(source: Path, target: Path) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        fields = raw.split()
        if not fields or fields[0].startswith("#"):
            continue
        time_s, displacement = float(fields[0]), float(fields[1])
        if rows and time_s < rows[-1][0]:
            raise ValueError("motion times are not monotonic")
        rows.append((time_s, displacement * PISTON_SCALE))
    if not rows or rows[-1][0] < 15.0:
        raise ValueError("motion does not cover the fixed source window")
    target.write_text("".join(f"{t:.10f} {x:.10f}\n" for t, x in rows), encoding="utf-8")
    return {"source": bind(source, "official piston source"), "output": bind(target, "fresh v4 piston motion"), "row_count": len(rows),
            "time_start_s": rows[0][0], "time_end_s": rows[-1][0], "scale": PISTON_SCALE}


def _definition(source: Path, target: Path) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None or definition.get("dp") != f"{DP:.9g}":
        raise ValueError("source Definition dp mismatch")
    motion = root.find("./casedef/motion/objreal/mvpredef/file")
    if motion is None:
        raise ValueError("source Definition has no motion file")
    motion.set("name", MOTION_NAME)
    params = {node.get("key"): node for node in root.findall("./execution/parameters/parameter")}
    params["TimeMax"].set("value", f"{TIME_MAX:.9g}")
    params["TimeOut"].set("value", f"{OUTPUT_DT:.9g}")
    gauges = root.find("./execution/special/gauges/default")
    for tag in ("computedt", "outputdt"):
        gauges.find(tag).set("value", f"{OUTPUT_DT:.9g}")
    for tag in ("computetime", "outputtime"):
        gauges.find(tag).set("start", "0")
        gauges.find(tag).set("end", f"{TIME_MAX:.9g}")
    main = root.find("./casedef/geometry/commands/mainlist")
    commands = list(main)
    slope = next(node for node in commands if node.tag == "drawfilestl" and node.get("file") == "Slope.stl")
    blocks = next(node for node in commands if node.tag == "drawfilestl" and node.get("file") == "Blocks_3D_scaled.stl")
    slope.set("file", SLOPE_NAME)
    slope.set("autofill", "true")
    blocks.set("file", BLOCKS_NAME)
    blocks.set("autofill", "true")
    if any(node.get("autofill") != "true" for node in (slope, blocks)):
        raise ValueError("v4 STL draws are not official autofill draws")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    out = ET.parse(target).getroot()
    draws = [node for node in out.findall("./casedef/geometry/commands/mainlist/drawfilestl") if node.get("file") in {SLOPE_NAME, BLOCKS_NAME}]
    if len(draws) != 2 or any(node.get("autofill") != "true" for node in draws):
        raise ValueError("v4 Definition does not contain exactly two autofill STL draws")
    return {"source": bind(source, "prior v2 Definition template"), "output": bind(target, "fresh v4 Definition"),
            "dp_m": DP, "time_max_s": TIME_MAX, "output_interval_s": OUTPUT_DT, "motion_file": MOTION_NAME,
            "slope_file": SLOPE_NAME, "blocks_file": BLOCKS_NAME, "autofill_draws": 2, "separate_boundary_redraws": 0}


def build() -> dict[str, Any]:
    _verify_root_review()
    prior = load(V3_PREFLIGHT)
    if prior.get("matrix_credit") != 0 or prior.get("qualified") is not False:
        raise ValueError("v3 failure evidence carries scientific credit")
    if INPUT.exists() and any(INPUT.iterdir()):
        raise FileExistsError(f"v4 input directory already contains files: {INPUT}")
    INPUT.mkdir(parents=True, exist_ok=True)
    motion = _motion(SOURCE_DIR / "Mov_piston.dat", MOTION)
    definition = _definition(SOURCE_DEFINITION, DEFINITION)
    shutil.copy2(SOURCE_DIR / "Slope.stl", SLOPE)
    shutil.copy2(SOURCE_DIR / "Blocks_3D_scaled.stl", BLOCKS)
    assets = [bind(SLOPE, "byte-identical renamed v4 slope source"), bind(BLOCKS, "byte-identical renamed v4 blocks source")]
    result = {
        "schema": "core.f5.third_t1.geometry_autofill_bound_materialization.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "v4_definition_written_preflight_pending",
        "qualification_claim": "none",
        "candidate": {"family": "F5", "scope_id": "F5_prescribed_wave_runup_x_v1", "revision_id": "F5_piston_amplitude_runup_geomrepair_v4",
                      "q": Q, "piston_scale": PISTON_SCALE, "dp_m": DP, "case_id": CASE_ID},
        "repair_lineage": {"root_review": bind(ROOT_REVIEW, "v4 autofill-bound root review"), "proposal": bind(PROPOSAL, "F5 geometry proposal"),
                            "v3_failure": bind(V3_PREFLIGHT, "v3 geometry-gate failure"), "prior_v3_input_reused": False,
                            "hypothesis": "official setmkbound plus drawfilestl autofill=true materializes the closed STL as boundary and excludes interior fluid cells"},
        "fresh_identity": {"definition": definition, "motion": motion, "definition_adjacent_assets": assets, "input_directory": rel(INPUT),
                           "preflight_output_prefix": "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/preflight-v4/generated/F5_wave_runup_q0p50_dp0p0075_geomrepair_v4"},
        "fixed_contract": {"denominator_rows": 15, "time_max_s": TIME_MAX, "output_interval_s": OUTPUT_DT, "gauge_interval_s": OUTPUT_DT,
                           "event_window_required": True, "zero_credit_until_cpu_native_and_solver_reviews": True, "same_input_retry": False},
        "geometry_recipe": {"slope": "setmkbound mk=40 then one autofill=true draw with unchanged transform", "blocks": "setmkbound mk=50 then one autofill=true draw with unchanged transform",
                            "fluid": "unchanged setmkfluid mk=0 and fillbox mode=void", "thresholds_changed": False},
        "authorization": {"root_review": bind(ROOT_REVIEW, "exact v4 root review"), "definition_written": True, "motion_written": True,
                           "gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False,
                           "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_mutation": 0},
        "implementation": bind(WRITER, "v4 autofill-bound writer"),
        "execution_controls": {"definition_written": True, "motion_written": True, "assets_copied": True, "gencase_invoked": False,
                               "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False, "queue_mutation": 0,
                               "ledger_mutation": 0, "registry_mutation": 0, "matrix_mutation": 0, "qualification_credit": 0},
    }
    CONTRACT.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def verify(path: Path = CONTRACT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f5.third_t1.geometry_autofill_bound_materialization.v1" or value.get("qualification_claim") != "none":
        raise ValueError("wrong v4 materialization contract")
    if value.get("execution_controls", {}).get("gencase_invoked") is not False or value.get("execution_controls", {}).get("qualification_credit") != 0:
        raise ValueError("v4 materialization claims execution or credit")
    for item in (value.get("repair_lineage", {}).get("root_review"), value.get("repair_lineage", {}).get("proposal"), value.get("repair_lineage", {}).get("v3_failure"), value.get("implementation")):
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"stale v4 contract binding: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    value = verify() if args.verify else build()
    if not args.verify:
        verify()
    print(json.dumps({"status": value["status"], "contract": rel(CONTRACT), "sha256": sha256(CONTRACT), "solver_invoked": False, "matrix_credit": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
