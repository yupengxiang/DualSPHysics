#!/usr/bin/env python3
"""Audit source drawbox/pointref evidence against the closed owner geometry.

This is a small XML-only audit.  It records what the source actually declares
and what remains unknown about GenCase cell-centre/support semantics.  It does
not treat a particle count or a midpoint envelope as a continuous truth and
does not modify any source or generated artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.source-support-audit.v2"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
CLOSURE = REFERENCE / "stage2_f2_f3_f6_owner_scale_closure_v2.json"
OUTPUT = REFERENCE / "stage2_f2_f3_f6_source_support_audit_v2.json"
OFFICIAL_TEMPLATE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/doc/xml_format/GenCase_CaseTemplate.xml"
)
OFFICIAL_HELP = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/doc/help/GenCase_Help.out"
)
SOURCES = {
    "F2-S1": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
        "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/"
        "root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804/prepared/"
        "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.xml"
    ),
    "F3-S2": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
        "F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/"
        "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/"
        "F3_STAGE1_DP006_P1200_AY0750.xml"
    ),
    "F6-S2": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025/root-stage1-f6-2p0-genuine-gencase-073/"
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025.xml"
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def number(node: ET.Element, key: str) -> float:
    raw = node.attrib.get(key)
    if raw is None:
        raise ValueError(f"{tag(node)} missing @{key}")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{tag(node)} @{key} is non-finite")
    return value


def vec(node: ET.Element, keys: tuple[str, str, str]) -> list[float]:
    return [number(node, key) for key in keys]


def parse_source(path: Path) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    pointrefs = [vec(node, ("x", "y", "z")) for node in root.iter() if tag(node) == "pointref"]
    shape_modes = [dict(node.attrib) for node in root.iter() if tag(node) == "setshapemode"]
    active: tuple[str, str] | None = None
    fluid: list[dict[str, Any]] = []
    for node in root.iter():
        name = tag(node)
        if name in {"setmkfluid", "setmkbound"}:
            active = ("fluid" if name == "setmkfluid" else "bound", str(node.attrib.get("mk", "")))
        elif name == "drawbox" and active and active[0] == "fluid":
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError(f"{path}: fluid drawbox missing point/size")
            p = vec(point, ("x", "y", "z"))
            s = vec(size, ("x", "y", "z"))
            fluid.append({"mkfluid": active[1], "point_m": p, "size_m": s, "end_m": [p[i] + s[i] for i in range(3)], "comment": node.attrib.get("cmt")})
    if not fluid:
        raise ValueError(f"{path}: no fluid drawbox")
    lo = [min(item["point_m"][i] for item in fluid) for i in range(3)]
    hi = [max(item["end_m"][i] for item in fluid) for i in range(3)]
    extent = [hi[i] - lo[i] for i in range(3)]
    volume = extent[0] * extent[1] * extent[2]
    return {
        "fluid_drawboxes": fluid,
        "fluid_union_bounds_m": {"min": lo, "max": hi},
        "fluid_union_extent_m": extent,
        "fluid_union_volume_m3": volume,
        "pointref": pointrefs,
        "setshapemode": {"present": bool(shape_modes), "nodes": shape_modes},
    }


def documentation_evidence(path: Path, tokens: tuple[str, ...]) -> dict[str, Any]:
    evidence = record(path, "official GenCase documentation")
    matches: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if any(token.lower() in line.lower() for token in tokens):
            matches.append({"line": line_number, "text": line.rstrip()})
    return {"file": evidence, "token_matches": matches}


def vec_diff(a: list[float], b: list[float]) -> list[float]:
    return [a[i] - b[i] for i in range(3)]


def close(a: list[float], b: list[float], tol: float = 1e-12) -> bool:
    return len(a) == len(b) and all(math.isfinite(x) and math.isfinite(y) and abs(x - y) <= tol for x, y in zip(a, b))


def build() -> dict[str, Any]:
    closure_record = record(CLOSURE, "owner scale closure")
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("schema") != "ds02.stage2.owner-scale-closure.v2":
        raise ValueError("source support audit requires owner-scale closure v2")
    entries: dict[str, Any] = {}
    input_sources: dict[str, Any] = {}
    for sentinel, path in SOURCES.items():
        source_record = record(path, f"{sentinel} source XML")
        source = parse_source(path)
        owner = closure["sentinels"][sentinel]["continuous_owner"]
        owner_low = owner["low_m"]
        owner_extent = owner["extent_m"]
        source_low = source["fluid_union_bounds_m"]["min"]
        source_extent = source["fluid_union_extent_m"]
        if sentinel == "F2-S1":
            interpretation = {
                "status": "SOURCE_OWNER_BOX_EQUAL_SAMPLE_SUPPORT_STILL_DIFFERENT",
                "owner_to_source_low_equal": close(owner_low, source_low),
                "owner_to_source_extent_equal": close(owner_extent, source_extent),
                "owner_to_source_volume_equal": math.isclose(owner["volume_m3"], source["fluid_union_volume_m3"], rel_tol=0, abs_tol=1e-12),
                "sample_mass_difference_is_not_explained_by_pointref": True,
                "support_or_lattice_explanation": "UNKNOWN_NO_POINTREF_AND_NO_OFFICIAL_SHAPE_SEMANTICS_BOUND_IN_THIS_AUDIT",
                "qualification": "UNKNOWN",
            }
        elif sentinel == "F3-S2":
            interpretation = {
                "status": "SOURCE_CELL_CENTRE_BOX_INSIDE_OWNER_BOX_EXPLICIT",
                "owner_to_source_low_delta_m": vec_diff(source_low, owner_low),
                "owner_to_source_extent_delta_m": vec_diff(owner_extent, source_extent),
                "pointref_values_m": source["pointref"],
                "pointref_matches_positive_owner_to_source_low_delta": bool(source["pointref"]) and close(source["pointref"][0], vec_diff(source_low, owner_low)),
                "owner_mass_kg": owner["mass_kg"],
                "source_drawbox_density_mass_kg": source["fluid_union_volume_m3"] * owner["density_kg_m3"],
                "support_or_lattice_explanation": "POINTREF_AND_DRAWBOX_OFFSET_OBSERVED; OFFICIAL_CELL_CENTRE_EQUIVALENCE_NOT_CLAIMED",
                "qualification": "UNKNOWN",
            }
        else:
            interpretation = {
                "status": "SOURCE_DRAWBOX_DECLARED_CELL_CENTRE_POPULATION",
                "source_comments": [item.get("comment") for item in source["fluid_drawboxes"]],
                "pointref_values_m": source["pointref"],
                "owner_to_source_low_delta_m": vec_diff(source_low, owner_low),
                "owner_to_source_extent_delta_m": vec_diff(owner_extent, source_extent),
                "support_or_lattice_explanation": "SOURCE_COMMENT_ONLY; CONTINUOUS_MASS_EQUIVALENCE_UNKNOWN",
                "qualification": "UNKNOWN",
            }
        input_sources[sentinel] = source_record
        entries[sentinel] = {
            "source": source,
            "owner_continuous_geometry": {
                "low_m": owner_low,
                "extent_m": owner_extent,
                "volume_m3": owner["volume_m3"],
                "mass_kg": owner["mass_kg"],
            },
            "discrete_sample": closure["sentinels"][sentinel]["discrete_initial_sample"],
            "shape_and_pointref_evidence": {
                "setshapemode": source["setshapemode"],
                "pointref": source["pointref"],
                "semantics_status": "DIRECT_XML_EVIDENCE_ONLY_OFFICIAL_INTERPRETATION_NOT_BOUND",
            },
            "interpretation": interpretation,
            "candidate_grid_rule": "retain owner geometry and source-defined support contract; no mass rescale and no midpoint-envelope substitution",
        }
    return {
        "schema": SCHEMA,
        "status": "SOURCE_SUPPORT_AUDIT_COMPLETE_PHYSICAL_EQUIVALENCE_UNKNOWN",
        "read_policy": {
            "source_xml_read": True,
            "owner_closure_read": True,
            "bi4_read": False,
            "native_part_read": False,
            "h5_read": False,
            "solver_started": False,
            "official_shape_semantics_claimed": False,
        },
        "inputs": {"owner_scale_closure": closure_record, "source_xml": input_sources},
        "official_documentation": {
            "template": documentation_evidence(OFFICIAL_TEMPLATE, ("pointref", "setshapemode")),
            "help": documentation_evidence(OFFICIAL_HELP, ("GenCase config_in", "-dp:", "-save:")),
            "interpretation_scope": "The template documents node/token syntax only. The v5.4 help has no behavioral rule that equates drawbox volume, pointref, or cell-centre support with continuous owner mass; no such equivalence is claimed here.",
            "official_behavioral_semantics_status": "UNKNOWN_NOT_SPECIFIED_BY_BOUND_DOCUMENTS",
        },
        "sentinels": entries,
        "mass_policy": {
            "continuous_owner_mass_is_authority_for_owner_scope": True,
            "discrete_sample_mass_is_diagnostic": True,
            "particle_count_is_not_geometry_equivalence": True,
            "rescale_forbidden": True,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse overwrite of immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def self_test() -> None:
    assert close([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    assert not close([0.0, 0.0, 0.0], [0.0, 0.0, math.nan])
    assert vec_diff([0.0, 0.0, 0.0], [-0.003, -0.003, -0.003]) == [0.003, 0.003, 0.003]
    print("stage2 F2/F3/F6 source-support audit v1 self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    atomic_json(args.output, build())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
