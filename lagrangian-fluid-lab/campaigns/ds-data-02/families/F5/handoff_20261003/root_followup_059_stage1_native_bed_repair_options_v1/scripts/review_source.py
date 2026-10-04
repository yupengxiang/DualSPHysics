#!/usr/bin/env python3
"""Read-only review of the bound F5 bed source and two repair recipes.

The command hashes and parses only the bound XML/STL/JSON metadata.  It does
not import h5py, open native arrays, edit a source file, invoke GenCase, or
launch a solver.  A future Root dispatch may use the report as a preflight
record before creating a candidate-specific GenCase request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.f5.stage1.native-filled-bed-repair-options-review.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _float(value: str) -> float:
    return float(value)


def _stl_signals(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    vertices = [
        tuple(_float(value) for value in match.groups())
        for match in re.finditer(
            r"\bvertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
            text,
        )
    ]
    return {
        "encoding": "ascii" if text.lstrip().startswith("solid") else "unknown",
        "facet_count": len(re.findall(r"\bfacet\s+normal\b", text)),
        "vertex_count": len(vertices),
        "bounds_m": {
            "x": [min(v[0] for v in vertices), max(v[0] for v in vertices)],
            "y": [min(v[1] for v in vertices), max(v[1] for v in vertices)],
            "z": [min(v[2] for v in vertices), max(v[2] for v in vertices)],
        }
        if vertices
        else None,
    }


def _xml_signals(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    triangles = list(root.iter("drawtriangles"))
    points = [point for node in triangles for point in node.iter("point")]
    faces = [face for node in triangles for face in node.iter("triangle")]
    ranges: list[dict[str, Any]] = []
    for particles in root.iter("particles"):
        for node in list(particles):
            if node.tag not in {"fixed", "moving", "fluid"} or "begin" not in node.attrib:
                continue
            ranges.append(
                {
                    "tag": node.tag,
                    "begin": int(node.attrib["begin"]),
                    "count": int(node.attrib["count"]),
                    "mk": int(node.attrib["mk"]) if "mk" in node.attrib else None,
                    "mkbound": int(node.attrib["mkbound"])
                    if "mkbound" in node.attrib
                    else None,
                    "mkfluid": int(node.attrib["mkfluid"])
                    if "mkfluid" in node.attrib
                    else None,
                }
            )
    return {
        "setmkbound": [dict(node.attrib) for node in root.iter("setmkbound")],
        "setmkfluid": [dict(node.attrib) for node in root.iter("setmkfluid")],
        "setdrawmode": [dict(node.attrib) for node in root.iter("setdrawmode")],
        "drawtriangles_count": len(triangles),
        "drawtriangles_point_count": len(points),
        "drawtriangles_triangle_count": len(faces),
        "drawfilestl": [dict(node.attrib) for node in root.iter("drawfilestl")],
        "shapeout": [dict(node.attrib) for node in root.iter("shapeout")],
        "drawboxes": [
            {
                "cmt": node.attrib.get("cmt"),
                "boxfill": (node.findtext("boxfill") or "").strip(),
                "point": dict(node.find("point").attrib)
                if node.find("point") is not None
                else None,
                "size": dict(node.find("size").attrib)
                if node.find("size") is not None
                else None,
            }
            for node in root.iter("drawbox")
        ],
        "particle_ranges": ranges,
    }


def review(binding_path: Path, options_path: Path, output_dir: Path) -> dict[str, Any]:
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    options = json.loads(options_path.read_text(encoding="utf-8"))
    source_files = binding["source_inputs"]
    checked: dict[str, Any] = {}
    for role in ("selected_definition_def050", "generated_xml_gen050", "generated_def_gen050", "bed_stl_gen050"):
        entry = source_files[role]
        path = Path(entry["path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise ValueError(f"SHA mismatch for {role}: {actual} != {entry['sha256']}")
        checked[role] = {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}

    selected = _xml_signals(Path(source_files["selected_definition_def050"]["path"]))
    generated = _xml_signals(Path(source_files["generated_xml_gen050"]["path"]))
    generated_ranges = generated["particle_ranges"]
    bed_ranges = [item for item in generated_ranges if item["tag"] == "fixed" and item["mk"] == 40]
    total = sum(item["count"] for item in generated_ranges)
    continuity = sorted(generated_ranges, key=lambda item: item["begin"])
    cursor = 0
    contiguous = True
    for item in continuity:
        contiguous = contiguous and item["begin"] == cursor
        cursor = item["begin"] + item["count"]

    output = {
        "schema": SCHEMA,
        "status": "completed_static_source_review",
        "source_arrays_opened": False,
        "source_files_modified": False,
        "gencase_invoked": False,
        "solver_invoked": False,
        "checked_source_files": checked,
        "selected_definition_signals": selected,
        "generated_xml_signals": generated,
        "stl_signals": _stl_signals(Path(source_files["bed_stl_gen050"]["path"])),
        "generated_identity_range_review": {
            "range_count": len(generated_ranges),
            "total_particles_from_ranges": total,
            "contiguous_from_zero": contiguous and cursor == 214515,
            "mk40_ranges": bed_ranges,
        },
        "candidate_count": len(options["candidates"]),
        "candidate_ids": [candidate["id"] for candidate in options["candidates"]],
        "shared_gate": options["shared_gate"],
        "interpretation_boundary": {
            "static_geometry_recipe_only": True,
            "native_fixed_bed_result": False,
            "missing_bed_result": False,
            "solver_root_cause": False,
            "hollow_stl_claim": False,
            "repair_authorized": False,
            "production_approval": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "native_filled_bed_repair_options_review.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--options", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = review(args.binding, args.options, args.output_dir)
    print(
        "static source review passed: "
        f"{result['candidate_count']} candidates, "
        f"{len(result['generated_identity_range_review']['mk40_ranges'])} mk40 range(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
