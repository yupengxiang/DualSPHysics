#!/usr/bin/env python3
"""Prepare a source-preserving F3-S2 commensurate dp=0.003 GenCase attempt.

The reviewed S2 XML/control and continuous owner remain bound.  Only the
resolution and half-cell selectors are changed so the 0.9 x 0.18 x 0.09 m
owner contains 300 x 60 x 30 fluid points.  This worker may invoke official
GenCase only under the root guarded request; it never starts a solver or reads
BI4/HDF5/native trajectories.  The old dp=0.0048 products are immutable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.f3.s2.commensurate-dp003-gencase.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
SOURCE_XML_SHA256 = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
SOURCE_CONTROL_SHA256 = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
PRIOR_SUPPORT_SHA256 = "3a882f545b4393f1d56863c54a6057871c31ba44e5db64a9a01cea7f343c64c0"
GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
SOURCE_DP_M = 0.006
TARGET_DP_M = 0.003
RHO_KG_M3 = 1000.0
OWNER_LOW_M = [-0.45, -0.09, 0.0]
OWNER_SIZE_M = [0.9, 0.18, 0.09]
TANK_SIZE_M = [0.9, 0.18, 0.51]
EXPECTED_FLUID_AXIS_COUNTS = [300, 60, 30]
EXPECTED_FLUID_COUNT = 540000
EXPECTED_SAMPLE_MASS_KG = 14.58
EXPECTED_MASSFLUID_KG = RHO_KG_M3 * TARGET_DP_M ** 3
SOURCE_FIXED_COUNT = 111708
ESTIMATED_FIXED_COUNT = int(round(SOURCE_FIXED_COUNT * (SOURCE_DP_M / TARGET_DP_M) ** 2))
ESTIMATED_TOTAL_COUNT = ESTIMATED_FIXED_COUNT + EXPECTED_FLUID_COUNT
ESTIMATED_OUTPUT_BI4_BYTES = 49561401
ESTIMATED_OUTPUT_TREE_BYTES = 256 * 1024 * 1024
EPS = 1e-12


class CandidateError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise CandidateError(f"missing input: {path}")
    stat = path.stat()
    return {
        "path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino,
        "sha256": sha256(path),
    }


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise CandidateError(f"{label} must be a regular file: {path}")
    return path


def write_new(path: Path, value: Any) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def copy_fresh(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite candidate control: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if sha256(target) != sha256(source):
        raise CandidateError("candidate control clone digest changed")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def first(root: ET.Element, name: str, label: str) -> ET.Element:
    for node in root.iter():
        if local(node.tag) == name:
            return node
    raise CandidateError(f"{label} has no <{name}>")


def child(parent: ET.Element, name: str, label: str) -> ET.Element:
    for node in list(parent):
        if local(node.tag) == name:
            return node
    raise CandidateError(f"{label} has no child <{name}>")


def number(node: ET.Element, axis: str, label: str) -> float:
    value = node.get(axis)
    if value is None:
        raise CandidateError(f"{label}.{axis} missing")
    try:
        result = float(value)
    except ValueError as exc:
        raise CandidateError(f"{label}.{axis} not numeric") from exc
    if not math.isfinite(result):
        raise CandidateError(f"{label}.{axis} not finite")
    return result


def vector(node: ET.Element, label: str) -> list[float]:
    return [number(node, axis, label) for axis in "xyz"]


def set_vector(node: ET.Element, values: list[float]) -> None:
    for axis, value in zip("xyz", values):
        node.set(axis, format(value, ".17g"))


def same(actual: list[float], expected: list[float], label: str) -> None:
    if len(actual) != len(expected) or any(abs(a - b) > EPS for a, b in zip(actual, expected)):
        raise CandidateError(f"{label} differs: {actual!r} != {expected!r}")


def targets() -> dict[str, list[float]]:
    half = TARGET_DP_M / 2.0
    return {
        "pointref_m": [half, half, half],
        "fluid_low_m": [OWNER_LOW_M[i] + half for i in range(3)],
        "fluid_size_m": [OWNER_SIZE_M[i] - TARGET_DP_M for i in range(3)],
        "bound_low_m": [OWNER_LOW_M[0] - half, OWNER_LOW_M[1] - half, -half],
        "bound_size_m": [OWNER_SIZE_M[0] + TARGET_DP_M, OWNER_SIZE_M[1] + TARGET_DP_M, TANK_SIZE_M[2] + half],
    }


def geometry(root: ET.Element) -> tuple[ET.Element, ET.Element, ET.Element, ET.Element]:
    geom = first(root, "geometry", "source XML")
    definition = child(geom, "definition", "geometry")
    commands = child(geom, "commands", "geometry")
    normal_list = next((node for node in list(commands)
                        if local(node.tag) == "list" and node.get("name") == "GeometryForNormals"), None)
    main = child(commands, "mainlist", "geometry")
    if normal_list is None:
        raise CandidateError("GeometryForNormals is missing")
    normal_box = child(normal_list, "drawbox", "GeometryForNormals")
    boxes = [node for node in list(main) if local(node.tag) == "drawbox"]
    if len(boxes) != 2:
        raise CandidateError(f"mainlist drawbox count {len(boxes)} != 2")
    return definition, normal_box, boxes[0], boxes[1]


def projection(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition, normal_box, fluid_box, bound_box = geometry(root)
    pointref = child(definition, "pointref", "definition")
    fluid_point, fluid_size = child(fluid_box, "point", "fluid"), child(fluid_box, "size", "fluid")
    bound_point, bound_size = child(bound_box, "point", "bound"), child(bound_box, "size", "bound")
    particles = next((node for node in root.iter() if local(node.tag) == "particles"), None)
    counts: dict[str, int] = {}
    if particles is not None:
        for node in list(particles):
            if local(node.tag) in {"fixed", "fluid", "floating", "moving"} and node.get("count") is not None:
                counts[local(node.tag)] = counts.get(local(node.tag), 0) + int(node.get("count"))
    constants = next((node for node in root.iter() if local(node.tag) == "constants"), None)
    mass = next((node for node in list(constants) if local(node.tag) == "massfluid"), None) if constants is not None else None
    return {
        "label": label, "dp_m": number(definition, "dp", f"{label}.definition"),
        "pointref_m": vector(pointref, f"{label}.pointref"),
        "normal_low_m": vector(child(normal_box, "point", f"{label}.normal"), f"{label}.normal.point"),
        "normal_size_m": vector(child(normal_box, "size", f"{label}.normal"), f"{label}.normal.size"),
        "fluid_low_m": vector(fluid_point, f"{label}.fluid.point"),
        "fluid_size_m": vector(fluid_size, f"{label}.fluid.size"),
        "bound_low_m": vector(bound_point, f"{label}.bound.point"),
        "bound_size_m": vector(bound_size, f"{label}.bound.size"),
        "counts": counts,
        "massfluid_kg": None if mass is None else number(mass, "value", f"{label}.massfluid"),
        "control_name": next((node.get("value") for node in root.iter() if local(node.tag) == "acctimesfile"), None),
    }


def build_candidate_xml(source: Path, destination: Path) -> dict[str, Any]:
    if sha256(source) != SOURCE_XML_SHA256:
        raise CandidateError("source XML digest differs")
    tree = ET.parse(source)
    definition, normal_box, fluid_box, bound_box = geometry(tree.getroot())
    source_projection = projection(source, "source")
    same(source_projection["normal_low_m"], OWNER_LOW_M, "source normal low")
    same(source_projection["normal_size_m"], TANK_SIZE_M, "source tank geometry")
    if abs(source_projection["dp_m"] - SOURCE_DP_M) > EPS:
        raise CandidateError("source dp is not 0.006")
    if source_projection["control_name"] != "CaseSloshingAccData.csv":
        raise CandidateError("source control basename differs")
    expected = targets()
    definition.set("dp", format(TARGET_DP_M, ".17g"))
    set_vector(child(definition, "pointref", "definition"), expected["pointref_m"])
    set_vector(child(fluid_box, "point", "fluid"), expected["fluid_low_m"])
    set_vector(child(fluid_box, "size", "fluid"), expected["fluid_size_m"])
    set_vector(child(bound_box, "point", "bound"), expected["bound_low_m"])
    set_vector(child(bound_box, "size", "bound"), expected["bound_size_m"])
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite candidate XML: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    candidate = projection(destination, "candidate")
    if abs(candidate["dp_m"] - TARGET_DP_M) > EPS:
        raise CandidateError("candidate dp mutation failed")
    for field in ("pointref_m", "fluid_low_m", "fluid_size_m", "bound_low_m", "bound_size_m"):
        same(candidate[field], expected[field], f"candidate {field}")
    same(candidate["normal_low_m"], OWNER_LOW_M, "candidate normal low")
    same(candidate["normal_size_m"], TANK_SIZE_M, "candidate tank geometry")
    if candidate["control_name"] != source_projection["control_name"]:
        raise CandidateError("candidate control basename changed")
    return {
        "source_projection": source_projection, "candidate_projection": candidate,
        "targets": expected, "source_xml_sha256": SOURCE_XML_SHA256,
        "candidate_xml_sha256": sha256(destination),
    }


def source_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise CandidateError("prepared source physical case differs")
    if report.get("xml_sha256") != SOURCE_XML_SHA256 or report.get("forcing_sha256") != SOURCE_CONTROL_SHA256:
        raise CandidateError("prepared source XML/control SHA differs")
    binding = report.get("physical_binding") or {}
    initial = (binding.get("geometry") or {}).get("initial_fluid") or {}
    if initial.get("low_m") != OWNER_LOW_M or initial.get("size_m") != OWNER_SIZE_M:
        raise CandidateError("prepared continuous owner differs")
    if binding.get("initial_state", {}).get("initial_mass_total_kg") != EXPECTED_SAMPLE_MASS_KG:
        raise CandidateError("prepared owner mass differs")
    return report


def support_report(path: Path) -> dict[str, Any]:
    if sha256(path) != PRIOR_SUPPORT_SHA256:
        raise CandidateError("ROOT081 report changed")
    report = json.loads(path.read_text(encoding="utf-8"))
    if set(report.get("cases", {})) != {"original_dp006", "coarse_dp0075", "fine_dp0048"}:
        raise CandidateError("ROOT081 grid case set changed")
    return report


def manifest_value(path: Path, inputs: dict[str, Path], gencase: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "ds02.stage2.f3.s2.commensurate-dp003-gencase.manifest.v1":
        raise CandidateError("candidate manifest schema differs")
    if value.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise CandidateError("candidate manifest physical case differs")
    candidate = value.get("candidate") or {}
    if candidate.get("dp_m") != TARGET_DP_M or candidate.get("fluid_axis_counts") != EXPECTED_FLUID_AXIS_COUNTS:
        raise CandidateError("candidate manifest resolution differs")
    if candidate.get("fluid_particles") != EXPECTED_FLUID_COUNT:
        raise CandidateError("candidate manifest fluid count differs")
    declared = value.get("inputs") or {}
    for key, actual in {**inputs, "gencase": gencase}.items():
        entry = declared.get(key) or {}
        if Path(entry.get("path", "")).expanduser().resolve() != actual.resolve():
            raise CandidateError(f"candidate manifest {key} path differs")
        if entry.get("sha256") != sha256(actual):
            raise CandidateError(f"candidate manifest {key} SHA differs")
    return value


def generated_projection(path: Path) -> dict[str, Any]:
    value = projection(path, "generated")
    expected = targets()
    if abs(value["dp_m"] - TARGET_DP_M) > EPS:
        raise CandidateError("generated dp differs")
    for field in ("pointref_m", "fluid_low_m", "fluid_size_m", "bound_low_m", "bound_size_m"):
        same(value[field], expected[field], f"generated {field}")
    same(value["normal_low_m"], OWNER_LOW_M, "generated normal low")
    same(value["normal_size_m"], TANK_SIZE_M, "generated tank geometry")
    if value["counts"].get("fluid") != EXPECTED_FLUID_COUNT:
        raise CandidateError(f"generated fluid count {value['counts'].get('fluid')} != {EXPECTED_FLUID_COUNT}")
    if value["massfluid_kg"] is None or abs(value["massfluid_kg"] - EXPECTED_MASSFLUID_KG) > EPS:
        raise CandidateError("generated MassFluid does not equal rho*dp^3")
    if abs(value["counts"]["fluid"] * value["massfluid_kg"] - EXPECTED_SAMPLE_MASS_KG) > EPS:
        raise CandidateError("generated sample mass differs from continuous owner")
    if value["counts"].get("fixed", 0) <= 0:
        raise CandidateError("generated fixed count is empty")
    if value["control_name"] != "CaseSloshingAccData.csv":
        raise CandidateError("generated control basename differs")
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    source = require_file(args.source_xml, "source XML")
    control = require_file(args.source_control, "source control")
    prepared = require_file(args.prepared_report, "prepared source report")
    support = require_file(args.prior_support_report, "ROOT081 support report")
    gencase = require_file(args.gencase, "official GenCase binary")
    manifest = require_file(args.manifest, "candidate manifest")
    if sha256(gencase) != GENCASE_SHA256 or sha256(control) != SOURCE_CONTROL_SHA256:
        raise CandidateError("official GenCase or control SHA differs")
    source_record = record(source)
    control_record = record(control)
    prepared_record = record(prepared)
    support_record = record(support)
    gencase_record = record(gencase)
    manifest_record = record(manifest)
    manifest_value(
        manifest,
        {"source_xml": source, "source_control": control, "prepared_report": prepared, "prior_support_report": support},
        gencase,
    )
    source_report_value = source_report(prepared)
    support_value = support_report(support)
    output = Path(args.output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("attempt output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    candidate_dir, generated_dir = output / "candidate_source", output / "generated"
    candidate_dir.mkdir()
    generated_dir.mkdir()
    candidate_xml = candidate_dir / "F3_S2_P1200_AY0750_DP003_MATCHED.xml"
    candidate_control = candidate_dir / control.name
    provenance = build_candidate_xml(source, candidate_xml)
    copy_fresh(control, candidate_control)
    command_prefix = generated_dir / "F3_S2_P1200_AY0750_DP003_MATCHED"
    command = [str(gencase), str(candidate_xml.with_suffix("")), str(command_prefix), "-save:all"]
    completed = subprocess.run(command, cwd=candidate_dir, capture_output=True, text=True, check=False)
    (output / "gencase.stdout").write_text(completed.stdout, encoding="utf-8")
    (output / "gencase.stderr").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"official GenCase failed with return code {completed.returncode}")
    generated_xml, generated_bi4 = command_prefix.with_suffix(".xml"), command_prefix.with_suffix(".bi4")
    if not generated_xml.is_file() or not generated_bi4.is_file():
        raise CandidateError("official GenCase did not emit XML and BI4")
    generated = generated_projection(generated_xml)
    post = {"manifest": record(manifest), "source_xml": record(source), "source_control": record(control),
            "prepared_report": record(prepared), "prior_support_report": record(support),
            "gencase": record(gencase)}
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_F3_S2_COMMENSURATE_DP003_GENCASE",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source_binding": {
            "manifest": manifest_record, "source_xml": source_record, "source_control": control_record,
            "prepared_report": prepared_record, "prior_support_report": support_record,
            "continuous_owner": {"low_m": OWNER_LOW_M, "size_m": OWNER_SIZE_M,
                                 "volume_m3": math.prod(OWNER_SIZE_M),
                                 "density_kg_m3": RHO_KG_M3, "mass_kg": EXPECTED_SAMPLE_MASS_KG},
            "preserved_fields": ["owner/tank geometry", "boundary geometry", "control bytes/basename",
                                 "gravity/material/control parameters"],
            "mutated_fields": ["dp", "pointref half-cell phase", "fluid inner selector",
                               "bound half-dp envelope"],
            "historical_dp0048_immutable": True,
        },
        "candidate_provenance": provenance,
        "official_gencase": {"binary": gencase_record, "command": command,
                             "returncode": completed.returncode,
                             "generated_xml": record(generated_xml),
                             "generated_bi4": record(generated_bi4),
                             "generated_projection": generated},
        "preflight_estimate": {
            "fluid_axis_counts": EXPECTED_FLUID_AXIS_COUNTS,
            "fluid_particles": EXPECTED_FLUID_COUNT,
            "expected_massfluid_kg": EXPECTED_MASSFLUID_KG,
            "expected_sample_mass_kg": EXPECTED_SAMPLE_MASS_KG,
            "fixed_particles_estimate": ESTIMATED_FIXED_COUNT,
            "total_particles_estimate": ESTIMATED_TOTAL_COUNT,
            "output_bi4_bytes_estimate": ESTIMATED_OUTPUT_BI4_BYTES,
            "reserved_output_tree_bytes": ESTIMATED_OUTPUT_TREE_BYTES,
            "estimate_basis": "source fixed count scaled by (0.006/0.003)^2; BI4 fit from reviewed .0048/.006/.0075 outputs; actual GenCase output is authoritative",
        },
        "scientific_status": {"source_control_closed": True, "continuous_owner_preserved": True,
                             "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                             "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "mass_rescale": False},
        "input_stability": {"post": post, "all_source_inputs_recorded_after_worker": True},
        "scope": {"official_gencase_started": True, "solver_started": False, "gpu_started": False,
                  "trajectory_h5_read": False, "source_bi4_read": False,
                  "old_products_modified": False, "historical_dp0048_reclassified": False},
        "prior_support_summary": {"source_grid": support_value["cases"]["original_dp006"]["generated"],
                                  "historical_dp0048_hardfail_preserved": True},
    }
    write_new(output / "f3_s2_commensurate_dp003_gencase_v1.json", report)
    return report


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-xml", required=True)
    parser.add_argument("--source-control", required=True)
    parser.add_argument("--prepared-report", required=True)
    parser.add_argument("--prior-support-report", required=True)
    parser.add_argument("--gencase", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main() -> int:
    try:
        value = run(parser().parse_args())
    except Exception as exc:
        print(f"F3 commensurate dp003 GenCase failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"schema": value["schema"], "status": value["status"],
                      "fluid_particles": value["preflight_estimate"]["fluid_particles"],
                      "fixed_particles_estimate": value["preflight_estimate"]["fixed_particles_estimate"],
                      "total_particles_estimate": value["preflight_estimate"]["total_particles_estimate"],
                      "QI": value["scientific_status"]["QI"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
