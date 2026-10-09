#!/usr/bin/env python3
"""Build a source-preserving F7-S1 coarse selector candidate.

This is a bounded *preflight* for a possible follow-up GenCase attempt.  It
does not run GenCase, read BI4/VTK/HDF5 data, or inspect a solver trajectory.
The candidate is derived from the already completed ROOT146/148/149 JSON
evidence and the immutable coarse Def XML.  Its predicted count is a lattice
calculation, not an assertion about how GenCase will interpret the XML.

The coarse source currently reports 22,806 fluid particles (356.34375 kg) for
an owner mass of 320.1984 kg.  ROOT149 shows 810 unique coarse positions just
above the owner y-high face by 2 ULP.  The forward candidate keeps the fixed
paddle, tank, motion, constants, and dp=.025 m, while replacing only the four
fluid selector boxes with a deterministic 42 x 28 x 18 center lattice.  Paddle
interior centers are omitted, giving a preregistered 20,484 cells and
320.0625 kg at the XML MassFluid.  The output explicitly remains a candidate;
the actual generated XML/receipt must be checked by a later guarded task.
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
from typing import Any, Iterable


SCHEMA = "ds02.stage2.f7.s1.coarse-selector-candidate.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.coarse-selector-candidate.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
RUNTIME_ALIAS = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
CURRENT_INDEX = 288
DP_M = 0.025
OWNER_MASS_KG = 320.1984
RHO_KG_M3 = 1000.0
PADDLE_LOW = (-0.07, -0.24, 0.05)
PADDLE_HIGH = (-0.01, 0.24, 0.53)
OWNER_LOW = (-0.55, -0.35, 0.05)
OWNER_HIGH = (0.55, 0.35, 0.482)
TARGET_CELL_COUNT = round(OWNER_MASS_KG / (RHO_KG_M3 * DP_M**3))
EXPECTED_CANDIDATE_COUNT = 20484
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".vtk", ".obi4", ".bi4", ".bi2", ".bi1"}


class CandidateError(ValueError):
    """Raised when a source-bound candidate contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def static_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise CandidateError(f"source is not a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateError(f"{label} must be a JSON object: {path}")
    return value


def _expect(actual: Any, wanted: Any, label: str) -> None:
    if actual != wanted:
        raise CandidateError(f"{label}: expected {wanted!r}, got {actual!r}")


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise CandidateError(f"{label} is not finite")
    return result


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _vec(element: ET.Element, label: str) -> tuple[float, float, float]:
    return tuple(_finite(element.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z"))


def _atomic_write(path: Path, payload: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise CandidateError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    _atomic_write(path, payload)


def _load_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise CandidateError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("key"), str):
            raise CandidateError("malformed source reference")
        key = ref["key"]
        if key in paths:
            raise CandidateError(f"duplicate source reference: {key}")
        path = Path(str(ref.get("path", ""))).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise CandidateError(f"{key} is a forbidden native payload: {path}")
        actual = static_record(path)
        expected = ref.get("sha256")
        if expected not in (None, "PARENT_GUARD_COMPUTED"):
            _expect(actual["sha256"], str(expected), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if ref.get(field) is not None:
                _expect(actual[field], int(ref[field]), f"{key} {field}")
        paths[key] = path
        stats[key] = actual
        if ref.get("kind", "json") == "json":
            docs[key] = read_json(path, key)
    return paths, stats, docs


def _parse_def(path: Path) -> ET.ElementTree:
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise CandidateError(f"coarse Def XML cannot be parsed: {path}") from exc
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise CandidateError("coarse Def lacks geometry/definition")
    _expect(definition.get("dp"), "0.025", "coarse Def dp")
    return tree


def _validate_fixed_source_geometry(tree: ET.ElementTree) -> None:
    """Pin the candidate's non-fluid geometry/control to the known F7 source."""
    root = tree.getroot()
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise CandidateError("coarse Def lacks geometry commands/mainlist")
    active_mk: str | None = None
    boxes: dict[str, list[tuple[tuple[float, float, float], tuple[float, float, float]]]] = {}
    for element in mainlist:
        tag = _tag(element)
        if tag in {"setmkbound", "setmkfluid"}:
            active_mk = element.get("mk")
        elif tag == "drawbox" and active_mk in {"0", "2"}:
            point = element.find("point")
            size = element.find("size")
            if point is None or size is None:
                raise CandidateError("fixed source drawbox lacks point/size")
            low = _vec(point, "fixed source drawbox point")
            extent = _vec(size, "fixed source drawbox size")
            boxes.setdefault(active_mk, []).append((low, tuple(low[i] + extent[i] for i in range(3))))
    _expect(len(boxes.get("0", [])), 1, "fixed tank drawbox count")
    _expect(len(boxes.get("2", [])), 1, "fixed paddle drawbox count")
    _expect(boxes["0"][0][0], (-0.6, -0.4, 0.0), "fixed tank low")
    _expect(boxes["0"][0][1], (0.6, 0.4, 0.6), "fixed tank high")
    _expect(boxes["2"][0][0], PADDLE_LOW, "fixed paddle low")
    paddle_high = boxes["2"][0][1]
    if any(not math.isclose(paddle_high[i], (PADDLE_HIGH[0], PADDLE_HIGH[1], 0.53)[i], rel_tol=0.0, abs_tol=2e-15) for i in range(3)):
        raise CandidateError(f"fixed paddle high: expected {(PADDLE_HIGH[0], PADDLE_HIGH[1], 0.53)!r}, got {paddle_high!r}")
    constants = root.find(".//casedef/constantsdef")
    if constants is None:
        raise CandidateError("coarse Def lacks constantsdef")
    gravity = constants.find("gravity")
    rhop0 = constants.find("rhop0")
    if gravity is None or rhop0 is None:
        raise CandidateError("coarse Def lacks gravity/rhop0")
    _expect(_vec(gravity, "gravity"), (0.0, 0.0, -9.81), "fixed gravity")
    _expect(_finite(rhop0.get("value"), "rhop0"), RHO_KG_M3, "fixed density")


def _drawbox(low: tuple[float, float, float], high: tuple[float, float, float], comment: str) -> ET.Element:
    box = ET.Element("drawbox", {"cmt": comment})
    ET.SubElement(box, "boxfill").text = "solid"
    ET.SubElement(box, "point", {axis: format(low[i], ".17g") for i, axis in enumerate(("x", "y", "z"))})
    ET.SubElement(
        box,
        "size",
        {axis: format(high[i] - low[i], ".17g") for i, axis in enumerate(("x", "y", "z"))},
    )
    return box


def _cell_box(lo: tuple[float, float, float], hi: tuple[float, float, float], dp: float, comment: str) -> ET.Element:
    """Encode a closed cell-center interval as a half-dp expanded drawbox."""
    low = tuple(value - dp / 2.0 for value in lo)
    high = tuple(value + dp / 2.0 for value in hi)
    return _drawbox(low, high, comment)


def _replace_fluid_boxes(tree: ET.ElementTree, boxes: Iterable[ET.Element]) -> None:
    mainlist = tree.getroot().find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise CandidateError("coarse Def lacks geometry commands/mainlist")
    setmkfluid = next((element for element in mainlist if _tag(element) == "setmkfluid" and element.get("mk") == "1"), None)
    if setmkfluid is None:
        raise CandidateError("coarse Def lacks setmkfluid mk=1")
    # GenCase's XML grammar keeps ``setmkfluid`` as a state command; its
    # following drawboxes are siblings in ``mainlist`` rather than children.
    start = list(mainlist).index(setmkfluid) + 1
    old: list[ET.Element] = []
    for element in list(mainlist)[start:]:
        tag = _tag(element)
        if tag == "drawbox":
            old.append(element)
            continue
        if tag in {"shapeout", "setmkbound", "setmkfluid"}:
            break
    if len(old) != 4:
        raise CandidateError(f"expected four source fluid drawboxes, got {len(old)}")
    main_children = list(mainlist)
    positions = [main_children.index(element) for element in old]
    for element in old:
        mainlist.remove(element)
    insert_at = min(positions)
    for offset, box in enumerate(boxes):
        mainlist.insert(insert_at + offset, box)
    remaining = [element for element in list(mainlist)[insert_at : insert_at + 4] if _tag(element) == "drawbox"]
    if len(remaining) != 4:
        raise CandidateError("candidate must contain exactly four fluid drawboxes")


def _selector_bounds(tree: ET.ElementTree) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    root = tree.getroot()
    setmkfluid = next((element for element in root.iter() if _tag(element) == "setmkfluid" and element.get("mk") == "1"), None)
    if setmkfluid is None:
        raise CandidateError("candidate tree lacks setmkfluid mk=1")
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise CandidateError("candidate tree lacks geometry commands/mainlist")
    start = list(mainlist).index(setmkfluid) + 1
    lows: list[tuple[float, float, float]] = []
    highs: list[tuple[float, float, float]] = []
    for box in list(mainlist)[start:]:
        if _tag(box) in {"shapeout", "setmkbound", "setmkfluid"}:
            break
        if _tag(box) != "drawbox":
            continue
        point = box.find("point")
        size = box.find("size")
        if point is None or size is None:
            raise CandidateError("candidate fluid drawbox lacks point/size")
        low = _vec(point, "candidate drawbox point")
        extent = _vec(size, "candidate drawbox size")
        lows.append(low)
        highs.append(tuple(low[i] + extent[i] for i in range(3)))
    if len(lows) != 4:
        raise CandidateError("candidate fluid drawbox count is not four")
    return tuple(min(row[i] for row in lows) for i in range(3)), tuple(max(row[i] for row in highs) for i in range(3))


def _candidate_lattice() -> dict[str, Any]:
    # Deterministic centered tie-break: choose the smallest lower index among
    # ties after minimizing center displacement.  The source ROOT149 lattice
    # uses owner low + i*dp and has 45x29x18 positions at dp=.025.
    counts = (42, 28, 18)
    base_counts = (45, 29, 18)
    offsets = tuple((base_counts[i] - counts[i]) // 2 for i in range(3))
    axes = tuple(tuple(OWNER_LOW[i] + DP_M * (offsets[i] + j) for j in range(counts[i])) for i in range(3))
    points = [(x, y, z) for x in axes[0] for y in axes[1] for z in axes[2]]
    kept = [point for point in points if not all(PADDLE_LOW[i] <= point[i] <= PADDLE_HIGH[i] for i in range(3))]
    count = len(kept)
    mass = count * RHO_KG_M3 * DP_M**3
    return {
        "axis_counts": list(counts),
        "source_axis_counts": list(base_counts),
        "axis_offsets_from_source": list(offsets),
        "axis_center_coordinates_m": {axis: [axes[i][0], axes[i][-1]] for i, axis in enumerate("xyz")},
        "owner_center_m": [0.0, 0.0, 0.266],
        "paddle_low_m": list(PADDLE_LOW),
        "paddle_high_m": list(PADDLE_HIGH),
        "candidate_full_lattice_count_before_paddle": len(points),
        "paddle_excluded_center_count": len(points) - count,
        "predicted_fluid_count": count,
        "target_fluid_count_from_owner_mass": TARGET_CELL_COUNT,
        "predicted_massfluid_kg": mass,
        "owner_mass_error_kg": mass - OWNER_MASS_KG,
        "owner_mass_error_fraction": (mass - OWNER_MASS_KG) / OWNER_MASS_KG,
        "selection_rule": "fixed dp=.025 source lattice, 42x28x18 centered tie-break; exclude centers inside fixed paddle; no search against actual generated output",
        "source_lattice_contract": "ROOT149 observed coarse lattice 45x29x18 with owner-low origin; candidate uses this as a deterministic diagnostic base only",
        "predicted_count_is_not_gencase_result": True,
    }


def _candidate_boxes(lattice: dict[str, Any]) -> list[ET.Element]:
    axes = lattice["axis_center_coordinates_m"]
    x0, x1 = axes["x"]
    y0, y1 = axes["y"]
    z0, z1 = axes["z"]
    # The four boxes partition the non-paddle lattice centers.  The intervals
    # are explicit and disjoint; root's later GenCase run must verify actual
    # cell interpretation and generated count.
    return [
        _cell_box((x0, y0, z0), (-0.075, y1, z1), DP_M, "candidate left selector; predicted lattice only"),
        _cell_box((0.0, y0, z0), (x1, y1, z1), DP_M, "candidate right selector; predicted lattice only"),
        _cell_box((-0.05, y0, z0), (-0.025, -0.25, z1), DP_M, "candidate lower paddle bypass; predicted lattice only"),
        _cell_box((-0.05, 0.25, z0), (-0.025, y1, z1), DP_M, "candidate upper paddle bypass; predicted lattice only"),
    ]


def _xml_bytes(tree: ET.ElementTree) -> bytes:
    ET.indent(tree, space="  ")
    return ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=False) + b"\n"


def _validate_source(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = read_json(manifest_path, "candidate manifest")
    _expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    _expect(manifest.get("family_id"), "F7", "manifest family")
    _expect(manifest.get("sentinel_id"), "F7-S1", "manifest sentinel")
    _expect(manifest.get("physical_case_id"), CASE_ID, "manifest physical case")
    _expect(manifest.get("current_index"), CURRENT_INDEX, "manifest CURRENT index")
    _expect(manifest.get("dp_m"), DP_M, "manifest dp")
    _expect(manifest.get("continuum_owner_mass_kg"), OWNER_MASS_KG, "manifest owner mass")
    _expect(manifest.get("owner_rescale"), False, "owner rescale policy")
    _expect(manifest.get("tolerance_widen"), False, "tolerance policy")
    paths, stats, docs = _load_refs(manifest)
    required = {"current336", "coarse_def", "root143_report", "root143_proof", "root146_report", "root146_proof", "root148_report", "root148_proof", "root149_report", "root149_proof"}
    missing = required - set(paths)
    if missing:
        raise CandidateError(f"manifest source closure missing {sorted(missing)}")
    current = docs["current336"].get("cases")
    if not isinstance(current, list) or len(current) != 336:
        raise CandidateError("CURRENT336 must contain exactly 336 cases")
    row = current[CURRENT_INDEX]
    _expect(row.get("family_id"), "F7", "CURRENT288 family")
    _expect(row.get("physical_case_id"), CASE_ID, "CURRENT288 physical case")
    _expect(row.get("runtime_case_alias"), RUNTIME_ALIAS, "CURRENT288 runtime alias")
    root143 = docs["root143_report"]
    _expect(root143.get("status"), "SOURCE_CONTROL_CLOSED_MASS_DIAGNOSTIC_ONLY_NO_SOURCE_MATCHED_SOLVER", "ROOT143 status")
    # ROOT143 predates the later nested ``current_binding`` shape and stores
    # its exact CURRENT row at the top level.  Keep this strict: accepting a
    # missing index would allow an otherwise matching F7 report from another
    # case to feed the candidate.
    if "current_index" in root143:
        _expect(root143.get("current_index"), CURRENT_INDEX, "ROOT143 current index")
    else:
        _expect(root143.get("current_binding", {}).get("index"), CURRENT_INDEX, "ROOT143 current index")
    _expect(root143.get("mass_semantics", {}).get("continuum_owner_mass_kg"), OWNER_MASS_KG, "ROOT143 owner mass")
    coarse143 = next((r for r in root143.get("rungs", []) if r.get("label") == "coarse"), None)
    if coarse143 is None:
        raise CandidateError("ROOT143 lacks coarse rung")
    _expect(coarse143.get("gencase", {}).get("fluid_particles"), 22806, "ROOT143 coarse fluid count")
    _expect(coarse143.get("gencase", {}).get("sample_mass_kg"), 356.34375, "ROOT143 coarse sample mass")
    root146 = docs["root146_report"]
    _expect(root146.get("status"), "COMPLETED_F7_S1_THREE_GRID_FRAME0_BI4_IDENTITY_SUPPORT_QA", "ROOT146 status")
    coarse146 = next((r for r in root146.get("rungs", []) if r.get("label") == "coarse"), None)
    if coarse146 is None:
        raise CandidateError("ROOT146 lacks coarse rung")
    _expect(coarse146.get("frame", {}).get("fluid_particles"), 22806, "ROOT146 coarse fluid count")
    _expect(coarse146.get("frame", {}).get("support_diagnostics", {}).get("fluid_outside_owner_envelope_count"), 810, "ROOT146 coarse outside count")
    root148 = docs["root148_report"]
    _expect(root148.get("status"), "SOURCE_XML_SELECTOR_AND_FACE_DISTANCE_DIAGNOSTIC_ONLY", "ROOT148 status")
    root149 = docs["root149_report"]
    _expect(root149.get("status"), "COMPLETED_F7_S1_THREE_GRID_COORDINATE_FACE_LATTICE_AUDIT", "ROOT149 status")
    coarse149 = next((r for r in root149.get("rungs", []) if r.get("label") == "coarse"), None)
    if coarse149 is None:
        raise CandidateError("ROOT149 lacks coarse rung")
    _expect(coarse149.get("fluid_count"), 22806, "ROOT149 coarse fluid count")
    _expect(coarse149.get("outside_owner_envelope_count"), 810, "ROOT149 coarse outside count")
    _expect(coarse149.get("face_counts_unique_outside_ids", {}).get("y_high"), 810, "ROOT149 coarse y-high count")
    _expect(coarse149.get("spacing_phase_by_axis")[0].get("coordinate_unique_count"), 45, "ROOT149 coarse x count")
    _expect(coarse149.get("spacing_phase_by_axis")[1].get("coordinate_unique_count"), 29, "ROOT149 coarse y count")
    _expect(coarse149.get("spacing_phase_by_axis")[2].get("coordinate_unique_count"), 18, "ROOT149 coarse z count")
    owner = docs["owner_metadata"].get("physical_binding", {})
    _expect(owner.get("family_id"), "F7", "owner metadata family")
    _expect(owner.get("physical_case_id"), CASE_ID, "owner metadata case")
    _expect(owner.get("initial_state", {}).get("initial_mass_total_kg"), OWNER_MASS_KG, "owner metadata mass")
    _expect(owner.get("geometry", {}).get("fluid_envelope", {}).get("low_m"), list(OWNER_LOW), "owner metadata envelope low")
    _expect(owner.get("geometry", {}).get("paddle", {}).get("low_m"), list(PADDLE_LOW), "owner metadata paddle low")
    _expect(owner.get("geometry", {}).get("paddle", {}).get("size_m"), [0.06, 0.48, 0.48], "owner metadata paddle size")
    tree = _parse_def(paths["coarse_def"])
    _validate_fixed_source_geometry(tree)
    return manifest, paths, stats, docs


def build_report(manifest_path: Path | str, output: Path | str | None = None) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest, paths, stats, docs = _validate_source(manifest_path)
    tree = _parse_def(paths["coarse_def"])
    lattice = _candidate_lattice()
    if lattice["predicted_fluid_count"] != EXPECTED_CANDIDATE_COUNT:
        raise CandidateError("deterministic candidate count changed")
    boxes = _candidate_boxes(lattice)
    _replace_fluid_boxes(tree, boxes)
    selector_low, selector_high = _selector_bounds(tree)
    candidate_bytes = _xml_bytes(tree)
    candidate_path: Path | None = None
    if output is not None:
        output = Path(output).expanduser().resolve()
        candidate_path = output.parent / "f7-s1-coarse-selector-candidate-v1_Def.xml"
        _atomic_write(candidate_path, candidate_bytes)
        result_output = output
    else:
        result_output = None
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_F7_S1_COARSE_SELECTOR_CANDIDATE_SOURCE_ONLY",
        "family_id": "F7",
        "sentinel_id": "F7-S1",
        "physical_case_id": CASE_ID,
        "current_binding": {"index": CURRENT_INDEX, "runtime_case_alias": RUNTIME_ALIAS},
        "source_binding": {
            "manifest": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "coarse_def": str(paths["coarse_def"]),
            "coarse_def_sha256": stats["coarse_def"]["sha256"],
            "root143_report_sha256": stats["root143_report"]["sha256"],
            "root146_report_sha256": stats["root146_report"]["sha256"],
            "root148_report_sha256": stats["root148_report"]["sha256"],
            "root149_report_sha256": stats["root149_report"]["sha256"],
            "root149_proof_sha256": stats["root149_proof"]["sha256"],
        },
        "existing_coarse_evidence": {
            "root143_fluid_count": 22806,
            "root143_sample_mass_kg": 356.34375,
            "root143_owner_mass_kg": OWNER_MASS_KG,
            "root143_sample_owner_error_fraction": (356.34375 - OWNER_MASS_KG) / OWNER_MASS_KG,
            "root146_outside_owner_envelope_unique_count": 810,
            "root149_outside_owner_envelope_unique_count": 810,
            "root149_outside_face_counts": {"y_high": 810, "other_faces": 0},
            "root149_max_positive_y_high_violation_m": 1.1102230246251565e-16,
            "root149_grid_unique_counts": {"x": 45, "y": 29, "z": 18},
            "interpretation": "numeric/source diagnostic; not legal spill, wall contact, physical fate, or dynamics",
        },
        "candidate": {
            "definition_xml_path": str(candidate_path) if candidate_path is not None else "OUTPUT_PARENT/f7-s1-coarse-selector-candidate-v1_Def.xml",
            "definition_xml_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "dp_m": DP_M,
            "owner_envelope_m": {"low": list(OWNER_LOW), "high": list(OWNER_HIGH)},
            "paddle_box_m": {"low": list(PADDLE_LOW), "high": list(PADDLE_HIGH)},
            "fluid_selector_union_m": {"low": list(selector_low), "high": list(selector_high)},
            "fluid_box_count": 4,
            "lattice": lattice,
            "xml_change_scope": "four direct mk=1 drawboxes only; boundary/tank, paddle, gravity, motion, numerical controls and output parameters copied from immutable coarse Def",
            "actual_gencase_status": "NOT_RUN_BY_THIS_WORKER",
            "actual_generated_count": "UNKNOWN_PENDING_GUARDED_GENCASE",
            "comparison_required": ["generated XML SHA", "execution receipt", "fluid count", "MassFluid", "actual bounds", "Idp uniqueness", "paddle exclusion", "source/control SHA"],
        },
        "scientific_scope": {
            "candidate_purpose": "bounded source-preserving selector sensitivity preflight",
            "not_a_physical_boundary_repair": True,
            "not_a_mass_rescale": True,
            "not_a_tolerance_widen": True,
            "continuous_owner": "UNKNOWN",
            "contact": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "qualification_status": "NOT_GRANTED; candidate must be independently generated and compared",
        },
        "read_policy": {
            "json_xml_only": True,
            "bi4_read": False,
            "obi4_read": False,
            "vtk_read": False,
            "hdf5_read": False,
            "solver_started": False,
            "gencase_started": False,
            "gpu_started": False,
            "old_products_immutable": True,
            "source_candidate_written_only_under_attempt_root": True,
        },
        "source_cost": {
            "input_file_count": len(stats),
            "input_bytes": sum(item["bytes"] for item in stats.values()),
            "native_bytes_read": 0,
            "hdf5_bytes_read": 0,
            "vtk_bytes_read": 0,
            "estimated_output_bytes": len(candidate_bytes) + 65536,
        },
        "claim_boundary": {
            "existing_810": "exact ROOT149 unique numeric boundary evidence preserved",
            "candidate_predicted_count": "lattice preregistration only",
            "candidate_mass": "rho*dp^3 diagnostic only until actual GenCase output",
            "selector_semantics": "candidate cell-center construction; official GenCase sampling remains UNKNOWN",
            "physical_boundary_or_spill": "UNKNOWN",
            "task_mass_gate": "frozen whole-owner mass screen remains unchanged; no Q credit",
        },
        "old_products_unchanged": True,
    }
    if result_output is not None:
        _atomic_json(result_output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        build_report(args.manifest, args.output)
    except CandidateError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
