#!/usr/bin/env python3
"""Execute the single Terra-High-authorized F9 CPU/native semantic preflight.

This script has exactly two runtime entry points: one GenCase invocation and
one native BI4 decode.  It never starts DualSPHysics, CUDA, a queue, training,
or any Core registration.  The output is an unqualified, zero-credit receipt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
REPO = LAB.parent
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.core_cfd import native_frame  # noqa: E402

ROOT = LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001"
REVIEW = ROOT / "root-review/root-admission-receipt-v2.json"
DEFINITION = ROOT / "input/F9_GRAVITY_FILM_NUSSELT_R001_Def.xml"
CONTRACT = ROOT / "definition-contract-v2.json"
PARSER_CONTRACT = ROOT / "metric-parser-contract-v1.json"
OUTPUT = ROOT / "preflight-r002"
PREFIX = OUTPUT / "generated/F9_GRAVITY_FILM_NUSSELT_R001"
RECEIPT = OUTPUT / "preflight-receipt-v1.json"
GENCASE = REPO / "bin/linux/GenCase_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
SCHEMA = "core.cfd.f9.cpu_native_semantic_preflight.v1"
TARGET_WIDTH = 0.24
WIDTH_TOLERANCE = 1.0e-8
PERIODIC_Z = 0.025225016464
PERIODIC_TOLERANCE = 1.0e-10
THETA = np.deg2rad(6.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def root_review() -> dict[str, Any]:
    value = load(REVIEW)
    if value.get("root_preflight_admission_granted") is not True:
        raise AssertionError("root review did not grant the one-shot preflight")
    if value.get("formal_scientific_admission") is not False or value.get("qualification_credit") != 0:
        raise AssertionError("root review credit/admission is not closed")
    scope = value.get("authorized_scope", {})
    if scope.get("cpu_gencase_invocations") != 1 or scope.get("native_bi4_decoder_invocations") != 1:
        raise AssertionError("authorized invocation count is not exactly one")
    if scope.get("isolated_output_root") != "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/preflight-r002":
        raise AssertionError("wrong isolated output root")
    if value.get("prohibited_scope", {}).get("solver") is not True:
        raise AssertionError("solver prohibition is missing")
    for item in value.get("hash_bindings", {}).values():
        if not isinstance(item, dict):
            continue
        path = REPO / item["path"]
        if not path.is_file() or sha256(path) != item.get("sha256"):
            raise AssertionError(f"stale root-review binding: {item.get('path')}")
    return value


def fresh_guard() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError("F9 preflight namespace is not fresh; retry is forbidden")
    if PREFIX.with_suffix(".xml").exists() or PREFIX.with_suffix(".bi4").exists():
        raise FileExistsError("F9 generated prefix already exists")


def xml_vector(node: ET.Element, name: str) -> list[float] | None:
    value = node.find(f"./*[@name='{name}']")
    if value is None or value.get("x") is None:
        return None
    return [float(value.get(axis)) for axis in ("x", "y", "z")]


def xml_scalar(node: ET.Element, name: str) -> float | None:
    value = node.find(f"./*[@name='{name}']")
    if value is None or value.get("v") is None:
        return None
    return float(value.get("v"))


def native_semantics(native_xml: Path) -> dict[str, Any]:
    root = ET.parse(native_xml).getroot()
    parent = root.find("./item")
    if parent is None:
        raise ValueError("native snapshot has no JPartDataBi4 item")
    names = {element.get("name") for element in parent if element.get("name")}
    return {
        "map_pos_min": xml_vector(parent, "MapPosMin"),
        "map_pos_max": xml_vector(parent, "MapPosMax"),
        "peri_x_inc": xml_vector(parent, "PeriXinc"),
        "peri_y_inc": xml_vector(parent, "PeriYinc"),
        "peri_z_inc": xml_vector(parent, "PeriZinc"),
        "peri_mode": int(xml_scalar(parent, "PeriMode") or 0),
        "case_pos_min": xml_vector(parent, "CasePosMin"),
        "case_pos_max": xml_vector(parent, "CasePosMax"),
        "case_np": int(xml_scalar(parent, "CaseNp") or -1),
        "case_nfixed": int(xml_scalar(parent, "CaseNfixed") or -1),
        "case_nmoving": int(xml_scalar(parent, "CaseNmoving") or -1),
        "case_nfloat": int(xml_scalar(parent, "CaseNfloat") or -1),
        "case_nfluid": int(xml_scalar(parent, "CaseNfluid") or -1),
        "dp": xml_scalar(parent, "Dp"),
        "h": xml_scalar(parent, "H"),
        "fields": sorted(names),
    }


def generated_counts(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles section")
    total = int(particles.get("np", "-1"))
    boundary = int(particles.get("nb", "-1"))
    fixed = particles.findall("fixed")
    fluid = particles.findall("fluid")
    floating = particles.findall("floating")
    blocks = [*fixed, *fluid, *floating]
    spans = []
    for block in blocks:
        begin = int(block.get("begin", "-1"))
        count = int(block.get("count", "-1"))
        if begin < 0 or count <= 0:
            raise ValueError("generated XML block span is invalid")
        spans.append({"kind": block.tag, "begin": begin, "count": count})
    ids = np.concatenate([np.arange(item["begin"], item["begin"] + item["count"]) for item in spans])
    contiguous = len(ids) == total and np.array_equal(ids, np.arange(total))
    return {
        "total_particles": total,
        "boundary_particles": boundary,
        "fixed_blocks": len(fixed),
        "fluid_blocks": len(fluid),
        "floating_blocks": len(floating),
        "blocks": spans,
        "xml_ids_contiguous": bool(contiguous),
        "hard_shape_pass": bool(len(fixed) == 1 and len(fluid) == 1 and not floating and contiguous and boundary == int(fixed[0].get("count", "-1")) and boundary > 0),
    }


def definition_semantics() -> dict[str, Any]:
    root = ET.parse(DEFINITION).getroot()
    params = {node.get("key"): float(node.get("value")) for node in root.findall(".//parameter")}
    gravity_node = root.find(".//gravity")
    return {
        "x_periodic_z_m": params.get("XPeriodicIncZ"),
        "y_periodic_z_m": params.get("YPeriodicIncZ"),
        "xy_periodic_present": "XYPeriodic" in params,
        "gravity": [float(gravity_node.get(axis)) for axis in ("x", "y", "z")],
        "bottom_normal": [float(x) for x in ("0.104528463", "0", "0.994521895")],
    }


def audit_native(ids: np.ndarray, positions: np.ndarray, velocity: np.ndarray, density: np.ndarray,
                 counts: dict[str, Any], semantics: dict[str, Any], definition: dict[str, Any], decoded: Path) -> dict[str, Any]:
    total = counts["total_particles"]
    fixed_count = counts["blocks"][0]["count"]
    fluid_begin = counts["blocks"][1]["begin"]
    fluid_count = counts["blocks"][1]["count"]
    shape = {
        "id_count_matches_xml": len(ids) == total,
        "ids_unique": len(np.unique(ids)) == len(ids),
        "ids_contiguous": len(ids) == total and np.array_equal(ids, np.arange(total, dtype=np.uint32)),
        "arrays_finite": bool(np.isfinite(positions).all() and np.isfinite(velocity).all() and np.isfinite(density).all()),
        "density_positive": bool(np.all(density > 0)),
    }
    fluid_pos = positions[fluid_begin:fluid_begin + fluid_count]
    fixed_pos = positions[:fixed_count]
    local_normal = positions[:, 0] * np.sin(THETA) + positions[:, 2] * np.cos(THETA)
    fluid_normal = local_normal[fluid_begin:fluid_begin + fluid_count]
    overlap = len({tuple(row) for row in fixed_pos}.intersection({tuple(row) for row in fluid_pos}))
    normal_files = sorted(path.name for path in decoded.iterdir() if "nor" in path.name.lower())
    normal_bytes = {name: (decoded / name).stat().st_size for name in normal_files}
    geometry = {
        "fluid_normal_extent_m": [float(fluid_normal.min()), float(fluid_normal.max())],
        "fluid_normal_thickness_m": float(fluid_normal.max() - fluid_normal.min()),
        "target_thickness_m": 0.03,
        "thickness_tolerance_m": 2.0 * float(semantics.get("dp") or 0.0),
        "thickness_pass": bool(abs((fluid_normal.max() - fluid_normal.min()) - 0.03) <= 2.0 * float(semantics.get("dp") or 0.0)),
        "fixed_fluid_exact_position_overlap_count": overlap,
        "overlap_pass": overlap == 0,
        "native_normal_files": normal_files,
        "native_normal_file_bytes": normal_bytes,
        "normal_metadata_present": bool(normal_files),
    }
    case_min = np.asarray(semantics["case_pos_min"], dtype=float)
    case_max = np.asarray(semantics["case_pos_max"], dtype=float)
    dp = float(semantics["dp"])
    derived_min = case_min.copy()
    derived_max = case_max.copy()
    # JSph uses Dp/2 on periodic axes and H*BORDER_MAP otherwise.
    border = np.full(3, float(semantics["h"]) * 0.05)
    border[:2] = dp / 2.0
    derived_min -= border
    derived_max += border
    width = float(derived_max[0] - derived_min[0])
    map_gate = {
        "bi4_header_map_pos_min": semantics["map_pos_min"],
        "bi4_header_map_pos_max": semantics["map_pos_max"],
        "bi4_header_map_loaded": semantics["map_pos_min"] != [0.0, 0.0, 0.0] or semantics["map_pos_max"] != [0.0, 0.0, 0.0],
        "runtime_source_projection_map_pos_min": derived_min.tolist(),
        "runtime_source_projection_map_pos_max": derived_max.tolist(),
        "runtime_source_projection_width_x_m": width,
        "target_width_x_m": TARGET_WIDTH,
        "tolerance_m": WIDTH_TOLERANCE,
        "pass": abs(width - TARGET_WIDTH) <= WIDTH_TOLERANCE,
        "method": "JPartsLoad4.CalculeLimits + JSph BORDER_MAP/periodic-axis rule; no solver invoked",
    }
    periodic = {
        "definition_x_periodic_z_m": definition["x_periodic_z_m"],
        "definition_y_periodic_z_m": definition["y_periodic_z_m"],
        "bi4_header_peri_x_inc": semantics["peri_x_inc"],
        "bi4_header_peri_y_inc": semantics["peri_y_inc"],
        "expected_runtime_peri_x_inc": [-width, 0.0, definition["x_periodic_z_m"]],
        "expected_runtime_peri_y_inc": [0.0, -float(derived_max[1] - derived_min[1]), definition["y_periodic_z_m"]],
        "source_configuration_pass": bool(
            not definition["xy_periodic_present"]
            and abs(definition["x_periodic_z_m"] - PERIODIC_Z) <= PERIODIC_TOLERANCE
            and abs(definition["y_periodic_z_m"]) <= PERIODIC_TOLERANCE
        ),
        "note": "GenCase BI4 header does not serialize Definition execution parameters; expected runtime vector is recorded as a source-bound projection, not a native solver receipt.",
    }
    hard = {
        "shape": bool(counts["hard_shape_pass"]),
        "native_arrays": bool(all(shape.values())),
        "map_width": bool(map_gate["pass"]),
        "periodic_configuration": bool(periodic["source_configuration_pass"]),
        "geometry": bool(geometry["thickness_pass"] and geometry["overlap_pass"] and geometry["normal_metadata_present"]),
    }
    return {"shape": shape, "geometry": geometry, "map_gate": map_gate, "periodic": periodic,
            "hard_gates": hard, "all_hard_gates_pass": bool(all(hard.values()))}


def run() -> dict[str, Any]:
    review = root_review()
    if sha256(DEFINITION) != review["hash_bindings"]["definition_xml"]["sha256"]:
        raise AssertionError("Definition changed after root review")
    fresh_guard()
    OUTPUT.mkdir(parents=True)
    (PREFIX.parent).mkdir(parents=True)
    log = OUTPUT / "gencase.stdout.log"
    command = [str(GENCASE), str(DEFINITION.with_suffix("")), str(PREFIX), "-save:all"]
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(command, cwd=OUTPUT, stdout=log.open("w"), stderr=subprocess.STDOUT, check=False)
    controls = {"gencase_invoked": True, "native_decode_invoked": False, "native_preflight_invoked": False,
                "solver_launch": False, "gpu_launch": False, "queue_mutation": 0, "registry_mutation": 0,
                "ledger_mutation": 0, "denominator_mutation": 0, "metric_parser_invoked": False}
    base: dict[str, Any] = {
        "schema": SCHEMA, "created_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "cpu_native_semantic_preflight_failed_gencase", "formal_scientific_admission": False,
        "qualification_claim": "none", "qualification_credit": 0, "root_review": ref(REVIEW, "Terra High root admission receipt"),
        "definition": ref(DEFINITION, "byte-identical F9 r001 Definition"), "contract": ref(CONTRACT, "F9 static definition contract v2"),
        "metric_parser_contract": ref(PARSER_CONTRACT, "unused frozen parser contract"), "gencase_command": command,
        "gencase_returncode": int(process.returncode), "execution_controls": controls,
    }
    if process.returncode != 0:
        base["gencase_log"] = ref(log, "GenCase stdout/stderr")
        RECEIPT.write_text(json.dumps(base, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        return base
    generated_xml = PREFIX.with_suffix(".xml")
    generated_bi4 = PREFIX.with_suffix(".bi4")
    counts = generated_counts(generated_xml)
    decoded_prefix = OUTPUT / "native/decoded"
    decoded_prefix.parent.mkdir(parents=True, exist_ok=True)
    controls["native_decode_invoked"] = True
    controls["native_preflight_invoked"] = True
    try:
        ids, positions, velocity, density, metadata, info, decoded_folder = native_frame(generated_bi4, decoded_prefix, DECODER)
    except subprocess.CalledProcessError as error:
        base.update({
            "status": "cpu_native_semantic_preflight_failed_native_decode",
            "generated_xml": ref(generated_xml, "GenCase generated XML"),
            "generated_bi4": ref(generated_bi4, "GenCase generated BI4"),
            "gencase_log": ref(log, "GenCase stdout/stderr"),
            "generated_counts": counts,
            "native_decoder": ref(DECODER, "native BI4 decoder"),
            "native_decode_returncode": int(error.returncode),
            "native_decode_error": "decoder could not create its requested XML output because its parent directory was absent; the one authorized invocation is not retried",
            "execution_controls": controls,
        })
        RECEIPT.write_text(json.dumps(base, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        return base
    native_xml = decoded_prefix.with_suffix(".xml")
    semantics = native_semantics(native_xml)
    definition = definition_semantics()
    audit = audit_native(ids, positions, velocity, density, counts, semantics, definition, decoded_folder)
    base.update({
        "status": "cpu_native_semantic_preflight_pass" if audit["all_hard_gates_pass"] else "cpu_native_semantic_preflight_failed_hard_audit",
        "generated_xml": ref(generated_xml, "GenCase generated XML"), "generated_bi4": ref(generated_bi4, "GenCase generated BI4"),
        "gencase_log": ref(log, "GenCase stdout/stderr"), "native_xml": ref(native_xml, "native decoded semantic XML"),
        "generated_counts": counts, "native_metadata": metadata, "native_info": info, "native_semantic": semantics,
        "audit": audit, "execution_controls": controls,
        "allowed_scope_statement": "No solver, GPU, queue, registry, ledger, denominator, metric parser, T1/T2 registration, or production batch was invoked.",
    })
    RECEIPT.write_text(json.dumps(base, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return base


def verify() -> dict[str, Any]:
    value = load(RECEIPT)
    if value.get("schema") != SCHEMA or value.get("qualification_claim") != "none" or value.get("qualification_credit") != 0:
        raise AssertionError("receipt schema or credit is open")
    controls = value.get("execution_controls", {})
    for key in ("solver_launch", "gpu_launch", "metric_parser_invoked"):
        if controls.get(key) is not False:
            raise AssertionError(f"forbidden control opened: {key}")
    for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"):
        if controls.get(key) != 0:
            raise AssertionError(f"forbidden mutation opened: {key}")
    for key in ("definition", "contract", "metric_parser_contract", "root_review", "gencase_log", "generated_xml", "generated_bi4", "native_xml"):
        item = value.get(key)
        if item and sha256(Path(item["path"])) != item["sha256"]:
            raise AssertionError(f"receipt binding changed: {key}")
    if value.get("status") == "cpu_native_semantic_preflight_pass" and not value.get("audit", {}).get("all_hard_gates_pass"):
        raise AssertionError("pass status lacks hard-gate proof")
    return {"status": "ok", "preflight_status": value.get("status"), "qualification_credit": value.get("qualification_credit", 0)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "verify"))
    args = parser.parse_args()
    value = run() if args.command == "run" else verify()
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0 if args.command == "verify" or value.get("status") == "cpu_native_semantic_preflight_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
