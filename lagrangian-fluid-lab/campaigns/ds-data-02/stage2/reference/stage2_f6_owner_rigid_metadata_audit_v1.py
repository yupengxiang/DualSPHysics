#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Audit F6 physical rigid-body metadata without opening particle payloads.

The source XML is the authority for ``massbody``, physical COM, inertia,
gravity, and execution controls.  The source/graph metadata supplies the
known discrete sample counts and candidate XML paths, but a fluid sample
mass is never substituted for the physical body mass and no continuous-owner
qualification is inferred.  This worker reads small XML/JSON only: it does
not open VTK, BI4, H5, Part, or solver output arrays.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f6-owner-rigid-metadata-audit.v1"
PASS_STATUS = "PASS_F6_SOURCE_XML_OWNER_RIGID_METADATA_AUDIT_V1"
UNKNOWN_STATUS = "UNKNOWN_F6_OWNER_CONTINUOUS_OR_DYNAMIC_EQUIVALENCE_V1"
CASE_IDS = ("F6-S1", "F6-S2")


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label}: {raw}")
    resolved = raw.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"{label} is not regular: {resolved}")
    return resolved


def _stat(path: Path) -> tuple[int, int, int, int, int, int]:
    st = path.stat()
    return (int(st.st_size), int(st.st_mtime_ns), int(st.st_ctime_ns), int(st.st_dev), int(st.st_ino), int(st.st_mode))


def _stat_dict(v: tuple[int, int, int, int, int, int]) -> dict[str, int]:
    return {"bytes": v[0], "mtime_ns": v[1], "ctime_ns": v[2], "st_dev": v[3], "st_ino": v[4], "mode": v[5]}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, label: str, max_bytes: int = 8 * 1024 * 1024) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before[0] > max_bytes:
        raise ValueError(f"{label} is larger than bounded metadata limit")
    data = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed during read")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value, {"path": str(path), "bytes": len(data), "sha256": _sha_bytes(data), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True, "content_scope": "bounded_source_metadata"}


def _read_xml(path: Path, label: str) -> tuple[ET.Element, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before[0] > 2 * 1024 * 1024:
        raise ValueError(f"{label} exceeds bounded XML limit")
    data = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed during read")
    return ET.fromstring(data), {"path": str(path), "bytes": len(data), "sha256": _sha_bytes(data), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True, "content_scope": "small_XML_source_or_generated_metadata"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"missing {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {label}")
    return result


def _vector(node: ET.Element, label: str) -> list[float]:
    return [_finite(node.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def _declaration(root: ET.Element, label: str) -> dict[str, Any]:
    # The generated execution floating block has begin; the preceding
    # floating block is a source declaration.  Use the execution block for
    # count/MK and its repeated physical fields for an exact XML audit.
    execution = [node for node in root.iter() if _local(node.tag) == "floating" and node.get("begin") is not None]
    if len(execution) != 1:
        raise ValueError(f"{label} expected exactly one execution floating block")
    block = execution[0]
    body = next((node for node in root.iter() if _local(node.tag) == "floating" and node.get("begin") is None), None)
    def child(name: str) -> ET.Element | None:
        return next((node for node in block if _local(node.tag) == name), None)
    massbody = child("massbody")
    center = child("center")
    inertia = child("inertia")
    masspart = next((node for node in root.iter() if _local(node.tag) == "masspart"), None)
    if massbody is None or center is None or inertia is None or masspart is None:
        raise ValueError(f"{label} lacks physical massbody/center/inertia or masspart")
    # The non-execution ``floating`` declaration is the source physical
    # declaration and retains the precise frozen values.  Generated XML
    # repeats these fields in the execution block, sometimes rounded for the
    # solver.  Report both and compare candidates against the source-level
    # values rather than silently treating a rounded copy as the authority.
    source_massbody = next((node for node in body or [] if _local(node.tag) == "massbody"), None)
    source_center = next((node for node in body or [] if _local(node.tag) == "center"), None)
    source_inertia = next((node for node in body or [] if _local(node.tag) == "inertia"), None)
    physical_massbody = source_massbody if source_massbody is not None else massbody
    physical_center = source_center if source_center is not None else center
    physical_inertia = source_inertia if source_inertia is not None else inertia
    params: dict[str, float] = {}
    for node in root.iter():
        if _local(node.tag) == "parameter" and node.get("key"):
            params[str(node.get("key"))] = _finite(node.get("value"), f"{label}.parameter.{node.get('key')}")
    gravity = next((node for node in root.iter() if _local(node.tag) == "gravity" and node.get("z") is not None), None)
    return {
        "floating_mk_absolute": int(block.get("mk", "-1")),
        "floating_begin": int(block.get("begin", "-1")),
        "floating_count": int(block.get("count", "-1")),
        "physical_body_massbody_kg": _finite(physical_massbody.get("value"), f"{label}.physical_massbody"),
        "physical_center_m": _vector(physical_center, f"{label}.physical_center"),
        "physical_inertia_kg_m2": _vector(physical_inertia, f"{label}.physical_inertia"),
        "execution_massbody_kg": _finite(massbody.get("value"), f"{label}.execution_massbody"),
        "execution_center_m": _vector(center, f"{label}.execution_center"),
        "execution_inertia_kg_m2": _vector(inertia, f"{label}.execution_inertia"),
        "floating_sample_masspart_kg": _finite(masspart.get("value"), f"{label}.masspart"),
        "gravity_m_per_s2": _vector(gravity, f"{label}.gravity") if gravity is not None else None,
        "parameters": params,
        "source_body_declaration_present": body is not None,
        "physical_body_mass_is_not_floating_sample_mass": True,
    }


def _comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    mass_equal = math.isclose(left["physical_body_massbody_kg"], right["physical_body_massbody_kg"], rel_tol=0.0, abs_tol=1.0e-12)
    center_equal = all(math.isclose(a, b, rel_tol=0.0, abs_tol=1.0e-12) for a, b in zip(left["physical_center_m"], right["physical_center_m"]))
    inertia_equal = all(math.isclose(a, b, rel_tol=0.0, abs_tol=1.0e-10) for a, b in zip(left["physical_inertia_kg_m2"], right["physical_inertia_kg_m2"]))
    return {"physical_massbody_equal": mass_equal, "physical_center_equal": center_equal, "physical_inertia_equal": inertia_equal, "status": "PASS_DECLARED_PHYSICAL_RIGID_FIELDS_EQUAL" if mass_equal and center_equal and inertia_equal else "FAIL_DECLARED_PHYSICAL_RIGID_FIELDS_DIFFER"}


def _grid_candidates(graph_row: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in graph_row.get("spatial_ladder", []):
        if item.get("grid") == "original":
            continue
        generated = item.get("generated_xml", {}).get("path") if isinstance(item.get("generated_xml"), dict) else None
        result.append({"grid": item.get("grid"), "case_id": item.get("case_id"), "requested_dp_m": item.get("requested_dp_m"), "generated_xml": generated, "sample_mass_kg_from_graph": item.get("candidate_sample_mass_kg"), "mass_gate_from_graph": item.get("whole_initial_mass_gate"), "continuous_geometry_status_from_graph": item.get("continuous_geometry_control_status"), "scientific_qualification_from_graph": item.get("scientific_qualification", "UNKNOWN")})
    return result


def run(source_audit_path: Path, graph_path: Path, output: Path) -> dict[str, Any]:
    source_audit, source_record = _read_json(source_audit_path, "F6 source/control audit")
    graph, graph_record = _read_json(graph_path, "F6 study graph")
    rows = {row.get("sentinel_id"): row for row in source_audit.get("sources", []) if isinstance(row, dict)}
    graph_rows = {row.get("sentinel_id"): row for row in graph.get("sentinels", []) if isinstance(row, dict)}
    cases: list[dict[str, Any]] = []
    any_unknown = False
    for sid in CASE_IDS:
        row, graph_row = rows.get(sid), graph_rows.get(sid)
        if not isinstance(row, dict) or not isinstance(graph_row, dict):
            raise ValueError(f"missing F6 {sid} source/graph row")
        source_xml = Path(str(row.get("source_xml", {}).get("path")))
        source_root, source_xml_record = _read_xml(source_xml, f"{sid} source XML")
        source_decl = _declaration(source_root, f"{sid} source XML")
        candidates = []
        for candidate in _grid_candidates(graph_row):
            path_value = candidate.get("generated_xml")
            if not path_value:
                candidate["status"] = "UNKNOWN_NO_GENERATED_XML_PATH"
                any_unknown = True
            else:
                path = Path(str(path_value))
                if not path.is_file() or path.is_symlink():
                    candidate["status"] = "UNKNOWN_GENERATED_XML_MISSING"
                    any_unknown = True
                else:
                    generated_root, generated_record = _read_xml(path, f"{sid} {candidate.get('grid')} generated XML")
                    declaration = _declaration(generated_root, f"{sid} {candidate.get('grid')} generated XML")
                    candidate["generated_xml_record"] = generated_record
                    candidate["declaration"] = declaration
                    candidate["declaration_comparison_to_source"] = _comparison(source_decl, declaration)
                    candidate["status"] = "PARSED_XML_DECLARATION_ONLY"
            candidates.append(candidate)
        cases.append({
            "sentinel_id": sid,
            "family_id": row.get("family_id"),
            "physical_case_id": row.get("physical_case_id"),
            "runtime_case_alias": graph_row.get("runtime_case_alias"),
            "source_xml": source_xml_record,
            "source_physical_declaration": source_decl,
            "source_metadata": {
                "source_fluid_particle_count": graph_row.get("source_fluid_particles"),
                "source_fluid_sample_mass_kg": graph_row.get("source_sample_mass_kg"),
                "source_floating_sample_particle_count": source_decl["floating_count"],
                "source_floating_sample_mass_kg": source_decl["floating_count"] * source_decl["floating_sample_masspart_kg"],
                "source_dp_m": graph_row.get("source_dp_m"),
                "control_payload_sha256": row.get("canonical_control_payload_sha256"),
                "control_equivalence": row.get("control_equivalence", "UNKNOWN"),
                "continuous_owner_status": "UNKNOWN_SOURCE_XML_AND_DISCRETE_GRAPH_DO_NOT_PROVE_CONTINUOUS_OWNER",
                "sample_mass_is_not_physical_body_mass": True,
            },
            "candidate_grids": candidates,
        })
    result = {
        "schema": SCHEMA,
        "status": UNKNOWN_STATUS if any_unknown else PASS_STATUS,
        "family_id": "F6",
        "sentinel_ids": list(CASE_IDS),
        "source_inputs": {"source_audit": source_record, "study_graph": graph_record},
        "cases": cases,
        "read_scope": {"source_and_generated_xml": True, "source_and_graph_metadata": True, "vtk_points": False, "bi4_part_h5": False, "solver_launch": False, "continuous_owner_inferred": False},
        "interpretation": {"physical_massbody_center_inertia_are_authoritative_xml_inputs": True, "discrete_fluid_and_floating_sample_mass_are_diagnostics": True, "rigid_body_dynamic_or_continuous_geometry_qualification": "UNKNOWN"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "XML declarations and bounded source metadata are joined; no particle payload or continuous-owner proof is inferred"},
    }
    _atomic_json(output, result)
    return result


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-root244-fixture-") as directory:
        root = Path(directory)
        xml = root / "fixture.xml"
        xml.write_text("<case><execution><floating mk='60' begin='1' count='2'><massbody value='128'/><center x='1' y='2' z='3'/><inertia x='4' y='5' z='6'/><masspart value='0.5'/></floating><constants><gravity x='0' y='0' z='-9.81'/></constants></execution><parameter key='TimeMax' value='1'/></case>", encoding="utf-8")
        root_xml = root / "source.xml"
        root_xml.write_text(xml.read_text(encoding="utf-8"), encoding="utf-8")
        source = root / "source.json"
        graph = root / "graph.json"
        source.write_text(json.dumps({"sources": [{"sentinel_id": sid, "family_id": "F6", "physical_case_id": sid, "source_xml": {"path": str(root_xml)}, "canonical_control_payload_sha256": "a" * 64, "control_equivalence": "UNKNOWN"} for sid in CASE_IDS]}) + "\n", encoding="utf-8")
        graph.write_text(json.dumps({"sentinels": [{"sentinel_id": sid, "runtime_case_alias": sid, "source_particles": 4, "source_fluid_particles": 2, "source_sample_mass_kg": 1.0, "source_dp_m": 0.1, "spatial_ladder": []} for sid in CASE_IDS]}) + "\n", encoding="utf-8")
        result = run(source, graph, root / "out.json")
        if result["cases"][0]["source_physical_declaration"]["physical_body_massbody_kg"] != 128.0:
            raise AssertionError("physical mass declaration fixture failed")
        bad = root / "bad.xml"
        bad.write_text(xml.read_text(encoding="utf-8").replace("value='128'", "value='nan'"), encoding="utf-8")
        try:
            _read_xml(bad, "bad XML")
            _declaration(ET.parse(bad).getroot(), "bad XML")
        except ValueError:
            pass
        else:
            raise AssertionError("non-finite XML was accepted")
    return {"status": "PASS", "schema": SCHEMA, "physical_body_separate_from_sample": True, "nonfinite_rejected": True, "payload_reads": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-audit", type=Path)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    if args.source_audit is None or args.graph is None or args.output is None:
        parser.error("--source-audit, --graph, and --output are required")
    result = run(args.source_audit, args.graph, args.output)
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "cases": len(result["cases"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
