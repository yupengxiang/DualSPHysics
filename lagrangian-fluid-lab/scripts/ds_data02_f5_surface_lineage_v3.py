"""Verify actual F5 surface repair preserves fluid, piston and physical XML across resolutions.

Generalized v3:
- Removes hardcoded fine N=2352000 and piston=169817.
- Supports any resolution (coarse DP=0.05, medium DP=0.025, fine DP=0.010).
- Dynamically validates fluid particle count against mother receipt and expected fluid particles.
- Dynamically extracts piston cohort from XML execution block and validates exact trailing coordinate payload.
- Verifies physical XML projection invariance after removing the 4 surface-first support nodes.
- Verifies all 60 triangle mesh vertices against reference STL bed mesh.
- Verifies prescribed piston motion dat bytes and STL bed mesh bytes equality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
import xml.etree.ElementTree as ET


SCHEMA_LINEAGE_V3 = "ds02.f5.actual-surface-discretization-lineage.v3"


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def projection(node: ET.Element) -> list[Any]:
    return [
        node.tag,
        sorted(node.attrib.items()),
        (node.text or "").strip(),
        [projection(child) for child in node],
    ]


def _vtk_points_payload(path: Path) -> tuple[int, bytes]:
    data = Path(path).read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\s*\n", data)
    if match is None:
        raise ValueError(f"unsupported VTK point block: {path}")
    count = int(match.group(1))
    start = match.end()
    end = start + count * 3 * 4
    if len(data) < end:
        raise ValueError(f"truncated VTK point payload: {path}")
    return count, data[start:end]


def audit_lineage(manifest_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    old_prefix = Path(manifest["old_prefix"])
    new_prefix = Path(manifest["new_prefix"])

    # 1. Receipt validation
    old_receipt_path = Path(manifest["old_receipt"])
    new_receipt_path = Path(manifest["new_receipt"])
    if not old_receipt_path.is_file():
        raise FileNotFoundError(f"old receipt missing: {old_receipt_path}")
    if not new_receipt_path.is_file():
        raise FileNotFoundError(f"new receipt missing: {new_receipt_path}")

    old_r = json.loads(old_receipt_path.read_text(encoding="utf-8"))
    new_r = json.loads(new_receipt_path.read_text(encoding="utf-8"))

    if old_r.get("status") != "completed" or old_r.get("returncode") != 0:
        raise ValueError(f"old GenCase did not complete successfully: {old_receipt_path}")
    if new_r.get("status") != "completed" or new_r.get("returncode") != 0:
        raise ValueError(f"new GenCase did not complete successfully: {new_receipt_path}")

    old_fluid_count = old_r.get("fluid_particles")
    new_fluid_count = new_r.get("fluid_particles")
    if not isinstance(old_fluid_count, int) or old_fluid_count <= 0:
        raise ValueError(f"invalid old fluid particles count: {old_fluid_count}")
    if old_fluid_count != new_fluid_count:
        raise ValueError(f"fluid particle count mismatch: old={old_fluid_count}, new={new_fluid_count}")

    expected_fluid = manifest.get("expected_fluid_particles")
    if expected_fluid is not None and new_fluid_count != int(expected_fluid):
        raise ValueError(f"actual fluid count {new_fluid_count} does not match expected {expected_fluid}")

    # 2. XML Definition and 4 Surface-First Support Nodes Check
    old_xml_path = Path(manifest["old_definition"])
    new_xml_path = Path(manifest["new_definition"])
    old_tree = ET.parse(old_xml_path).getroot()
    new_tree = ET.parse(new_xml_path).getroot()

    main = new_tree.find(".//geometry/commands/mainlist")
    if main is None:
        raise ValueError(f"new XML missing geometry commands mainlist: {new_xml_path}")

    surface_cmd = next((n for n in main if n.tag == "drawtriangles"), None)
    if surface_cmd is None:
        raise ValueError("new XML missing drawtriangles command")

    support_nodes = [n for n in main if n.get("cmt", "").startswith("root_numeric_bed_surface_support")]
    if len(support_nodes) != 4 or [n.tag for n in support_nodes] != ["setmkbound", "setdrawmode", "drawtriangles", "setdrawmode"]:
        raise ValueError(f"unexpected surface-first repair command sequence: {[n.tag for n in support_nodes]}")

    triangles_elem = surface_cmd.find("triangles")
    points_elem = surface_cmd.find("points")
    if triangles_elem is None or points_elem is None:
        raise ValueError("drawtriangles missing points or triangles elements")
    if len(triangles_elem) != 60:
        raise ValueError(f"expected 60 surface triangles, found {len(triangles_elem)}")

    # 3. Verify Triangle Vertices match reference bed STL
    bed_stl_path = Path(manifest["new_bed"])
    vertices: list[tuple[float, float, float]] = []
    for line in bed_stl_path.read_text(encoding="utf-8").splitlines():
        fields = line.strip().split()
        if fields and fields[0] == "vertex":
            vertices.append(tuple(float(x) for x in fields[1:]))

    actual_pts = [tuple(float(n.get(k)) for k in "xyz") for n in points_elem]
    actual_triangles = [tuple(int(n.get(k)) for k in "xyz") for n in triangles_elem]
    expected_triangles = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(60)]
    mesh_same = (actual_pts == vertices) and (actual_triangles == expected_triangles)

    # 4. Invariance of Physical XML projection (after removing the 4 support nodes)
    for n in support_nodes:
        main.remove(n)
    physical_same = projection(old_tree) == projection(new_tree)

    # 5. Fluid VTK Payload Check
    old_fluid_vtk = old_prefix.with_name(old_prefix.name + "_Fluid.vtk")
    new_fluid_vtk = new_prefix.with_name(new_prefix.name + "_Fluid.vtk")
    old_fluid_c, old_fluid_bytes = _vtk_points_payload(old_fluid_vtk)
    new_fluid_c, new_fluid_bytes = _vtk_points_payload(new_fluid_vtk)
    fluid_same = (old_fluid_bytes == new_fluid_bytes) and (old_fluid_c == new_fluid_count)

    # 6. Prescribed Piston Moving Particle Payload Check
    moving_payloads: list[bytes] = []
    piston_counts: list[int] = []
    for prefix in [old_prefix, new_prefix]:
        xml_p = prefix.with_suffix(".xml")
        root = ET.parse(xml_p).getroot()
        particles = root.find(".//execution/particles")
        if particles is None:
            raise ValueError(f"missing execution/particles in {xml_p}")
        moving_node = particles.find("moving")
        if moving_node is None:
            raise ValueError(f"missing moving particles node in {xml_p}")
        m_count = int(moving_node.get("count"))
        nb = int(particles.get("nb"))
        bound_vtk = prefix.with_name(prefix.name + "_Bound.vtk")
        bound_count, payload = _vtk_points_payload(bound_vtk)
        if bound_count != nb:
            raise ValueError(f"Bound VTK count {bound_count} differs from particles nb {nb}")
        piston_counts.append(m_count)
        moving_payloads.append(payload[-m_count * 3 * 4:])

    piston_same = (piston_counts[0] == piston_counts[1]) and (moving_payloads[0] == moving_payloads[1])

    # 7. Prescribed Motion and Bed STL file equality
    motion_same = sha256_file(manifest["old_motion"]) == sha256_file(manifest["new_motion"])
    bed_same = sha256_file(manifest["old_bed"]) == sha256_file(manifest["new_bed"])

    checks = {
        "original_physical_definition_projection_equal": physical_same,
        "all_original_mesh_triangle_vertices_equal": mesh_same,
        "actual_complete_fluid_coordinate_payload_equal": fluid_same,
        "actual_prescribed_piston_coordinate_payload_equal": piston_same,
        "motion_bytes_equal": motion_same,
        "bed_mesh_bytes_equal": bed_same,
    }

    result = {
        "schema": SCHEMA_LINEAGE_V3,
        "case_id": manifest.get("case_id", new_prefix.name),
        "checks": checks,
        "passed": all(checks.values()),
        "fluid_particles": new_fluid_count,
        "moving_particles": piston_counts[0],
        "native_fluid_mass_kg": float(manifest.get("expected_fluid_mass_kg", 2352.0)),
        "q_n_granted": False,
        "production_granted": False,
        "claim_boundary": (
            "Initialization byte lineage only; fixed boundary particle discretization changes deliberately "
            "to support numerical bed surface; no claim to numerical convergence."
        ),
        "source_sha256": {
            k: sha256_file(v) for k, v in manifest.items() if k not in ["old_prefix", "new_prefix", "case_id", "expected_fluid_particles", "expected_fluid_mass_kg", "dp_m"]
        },
    }

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    res = audit_lineage(args.manifest, args.output)
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
