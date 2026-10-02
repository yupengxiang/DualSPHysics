"""Register a static F6 floating-body cell-centre recipe.

The existing F6 body particles have resolution-dependent phases and point
counts.  This module computes an *ideal* Cartesian cell-centre construction
inside the frozen continuous body box and records the checks that a future
bounded GenCase/PartVTK run must perform.  It deliberately does not edit an
XML input, call GenCase, call the solver, or claim numerical qualification.

The proposal is useful only as a preflight.  GenCase rounds drawing limits to
the ``pointref`` lattice, so the candidate coordinates below are not treated
as generated evidence until the native output has been inspected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds02.f6.body-cellcenter-recipe.v1"
ROOT = Path("/home/jade/Projects/DualSPHysics")
INTEGRATION_ROOT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
)
ACTUAL_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_FULL12_FINE_PAIR_HEAVE_BODY_GEOMETRY_DIAGNOSTIC/"
    "root-heave-body-lattice-diagnostic-001/heave-body-lattice-diagnostic.json"
)
ACTUAL_EVIDENCE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/"
    "handoff_20261003/root_heave_geometry_diagnostic_001/actual-evidence.json"
)
CANONICAL_MOTHER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/"
    "handoff_20261002/commensurate_mother/physical_mother_geometry.json"
)
OUTPUT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/"
    "handoff_20261003/body_cellcenter_recipe_001/static-proposal.json"
)

FUNCTIONS_MATH = ROOT / "src/source/FunctionsMath.h"
JCASE_VRES = ROOT / "src/source/JCaseVRes.cpp"
CHANGES = ROOT / "CHANGES.txt"

BODY_COMMENT = "Native floatingtype=2 body; initial bottom at fluid upper face"
WALL_COMMENT = "Finite tank walls; physical endpoints frozen"
FLUID_COMMENT = "Frozen continuous fluid cell-centre population"

RESOLUTIONS: tuple[tuple[str, float], ...] = (
    ("coarse", 0.025),
    ("medium", 0.02),
    ("fine", 0.0125),
)


class RecipeError(ValueError):
    """Raised when the static recipe cannot be constructed safely."""


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest without loading a large file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise RecipeError(f"{label} is not a regular file: {path}")
    return path


def _number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RecipeError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise RecipeError(f"{label} is not finite: {value!r}")
    return result


def _vector(values: Iterable[Any], label: str) -> list[float]:
    result = [_number(value, f"{label}[{index}]") for index, value in enumerate(values)]
    if len(result) != 3:
        raise RecipeError(f"{label} must have three components")
    return result


def _close(a: Sequence[float], b: Sequence[float], tolerance: float = 1e-9) -> bool:
    return all(abs(float(x) - float(y)) <= tolerance for x, y in zip(a, b))


def integer_cell_counts(size_m: Sequence[float], dp_m: float, *, tolerance: float = 1e-9) -> tuple[int, int, int]:
    """Return integer cells per axis, rejecting non-commensurate geometry."""

    size = _vector(size_m, "size_m")
    dp = _number(dp_m, "dp_m")
    if dp <= 0:
        raise RecipeError("dp_m must be positive")
    counts: list[int] = []
    for axis, length in enumerate(size):
        ratio = length / dp
        count = int(round(ratio))
        if count <= 0 or abs(ratio - count) > tolerance * max(1.0, abs(ratio)):
            raise RecipeError(
                f"body size axis {axis} is not an integer multiple of dp: "
                f"size={length!r}, dp={dp!r}, ratio={ratio!r}"
            )
        counts.append(count)
    return tuple(counts)  # type: ignore[return-value]


def centered_box_recipe(
    low_m: Sequence[float], size_m: Sequence[float], dp_m: float
) -> dict[str, Any]:
    """Compute the ideal interior cell-centre lattice for one body box.

    ``candidate_drawbox`` is a proposed GenCase input only.  The final native
    points still depend on GenCase's draw and lattice rounding rules.
    """

    low = _vector(low_m, "low_m")
    size = _vector(size_m, "size_m")
    dp = _number(dp_m, "dp_m")
    counts = integer_cell_counts(size, dp)
    high = [low[index] + size[index] for index in range(3)]
    first = [low[index] + 0.5 * dp for index in range(3)]
    last = [high[index] - 0.5 * dp for index in range(3)]
    inner_size = [size[index] - dp for index in range(3)]
    centroid = [(first[index] + last[index]) / 2.0 for index in range(3)]
    count = math.prod(counts)
    proxy_volume = count * dp**3
    return {
        "dp_m": dp,
        "cell_counts_xyz": list(counts),
        "ideal_type2_count": count,
        "continuous_low_m": low,
        "continuous_high_m": high,
        "ideal_first_center_m": first,
        "ideal_last_center_m": last,
        "ideal_centroid_m": centroid,
        "candidate_drawbox": {
            "boxfill": "solid",
            "point_m": first,
            "size_m": inner_size,
            "semantic_status": "candidate_requires_native_gencase_verification",
        },
        "proxy_count_times_dp_cubed_m3": proxy_volume,
        "continuous_box_volume_m3": math.prod(size),
        "mass_policy": {
            "continuous_body_mass_kg_is_frozen": True,
            "massbody_is_not_recomputed": True,
            "masspart_is_reported_from_native_output": True,
            "count_times_dp_cubed_is_not_physical_volume": True,
            "mass_normalization": "forbidden",
        },
    }


def native_matches_target(
    native: Mapping[str, Any], target: Mapping[str, Any], *, tolerance: float = 1e-8
) -> bool:
    """Check the static target against one diagnostic native row."""

    count = int(native.get("type2_count", -1))
    if count != int(target["ideal_type2_count"]):
        return False
    for native_key, target_key in (
        ("point_min_m", "ideal_first_center_m"),
        ("point_max_m", "ideal_last_center_m"),
        ("point_centroid_m", "ideal_centroid_m"),
    ):
        try:
            values = _vector(native[native_key], native_key)
            expected = _vector(target[target_key], target_key)
        except (KeyError, RecipeError):
            return False
        if not _close(values, expected, tolerance):
            return False
    return True


def _xml_number(node: ET.Element, name: str, label: str) -> float:
    if name not in node.attrib:
        raise RecipeError(f"{label} lacks {name!r}")
    return _number(node.attrib[name], f"{label}.{name}")


def _xml_vector(node: ET.Element, label: str) -> list[float]:
    return [_xml_number(node, axis, label) for axis in "xyz"]


def _find_drawbox(root: ET.Element, comment: str) -> ET.Element:
    for node in root.findall(".//drawbox"):
        if node.get("cmt") == comment:
            return node
    raise RecipeError(f"XML is missing drawbox cmt={comment!r}")


def _drawbox_semantics(node: ET.Element, label: str) -> dict[str, Any]:
    point = node.find("point")
    size = node.find("size")
    if point is None or size is None:
        raise RecipeError(f"{label} drawbox lacks point or size")
    boxfill = node.findtext("boxfill")
    return {
        "boxfill": boxfill,
        "point_m": _xml_vector(point, f"{label}.point"),
        "size_m": _xml_vector(size, f"{label}.size"),
    }


def _element_attributes(node: ET.Element | None) -> dict[str, str] | None:
    return dict(node.attrib) if node is not None else None


def parse_definition(path: Path) -> dict[str, Any]:
    """Read immutable physical/numeric/control semantics from a Definition."""

    _require_file(path, "F6 Definition XML")
    root = ET.parse(path).getroot()
    definition = root.find(".//definition")
    if definition is None:
        raise RecipeError(f"missing geometry definition in {path}")
    pointref = definition.find("pointref")
    pointmin = definition.find("pointmin")
    pointmax = definition.find("pointmax")
    if pointref is None or pointmin is None or pointmax is None:
        raise RecipeError(f"incomplete lattice definition in {path}")
    body = _find_drawbox(root, BODY_COMMENT)
    wall = _find_drawbox(root, WALL_COMMENT)
    fluid = _find_drawbox(root, FLUID_COMMENT)
    floating = root.find(".//floatings/floating")
    if floating is None:
        raise RecipeError(f"missing floating block in {path}")
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    if massbody is None or center is None or inertia is None:
        raise RecipeError(f"incomplete floating mass/center/inertia in {path}")
    particles = root.find(".//particles")
    floating_particles = particles.find("floating") if particles is not None else None
    fluid_particles = particles.find("fluid") if particles is not None else None
    constants = root.find(".//constants")
    constant_values: dict[str, dict[str, str]] = {}
    if constants is not None:
        for child in list(constants):
            if child.tag is not None:
                constant_values[str(child.tag)] = dict(child.attrib)
    execution = root.find("./execution")
    parameters: dict[str, str] = {}
    if execution is not None:
        for parameter in execution.findall(".//parameter"):
            key = parameter.get("key")
            value = parameter.get("value")
            if key is not None and value is not None:
                parameters[key] = value
    motion = root.find(".//motion")
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "dp_m": _xml_number(definition, "dp", "definition") ,
        "pointref_m": _xml_vector(pointref, "definition.pointref"),
        "pointmin_m": _xml_vector(pointmin, "definition.pointmin"),
        "pointmax_m": _xml_vector(pointmax, "definition.pointmax"),
        "body": _drawbox_semantics(body, "body"),
        "wall": _drawbox_semantics(wall, "wall"),
        "fluid_numeric_drawbox": _drawbox_semantics(fluid, "fluid"),
        "floating": {
            "mkbound": floating.get("mkbound"),
            "massbody_kg": _xml_number(massbody, "value", "massbody"),
            "center_m": _xml_vector(center, "floating.center"),
            "inertia_kg_m2": _xml_vector(inertia, "floating.inertia"),
        },
        "particle_declaration": {
            "particles_attributes": _element_attributes(particles),
            "floating": _element_attributes(floating_particles),
            "fluid": _element_attributes(fluid_particles),
            "floating_masspart_kg": (
                _xml_number(floating_particles.find("masspart"), "value", "particles.floating.masspart")
                if floating_particles is not None and floating_particles.find("masspart") is not None
                else None
            ),
        },
        "constants": constant_values,
        "execution_parameters": parameters,
        "motion_xml": ET.tostring(motion, encoding="unicode") if motion is not None else None,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _report_native_rows(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = report.get("initial_body_lattice")
    if not isinstance(rows, list):
        raise RecipeError("diagnostic report lacks initial_body_lattice rows")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("role"), str):
            raise RecipeError("invalid initial_body_lattice row")
        result[str(row["role"])] = row
    missing = {role for role, _ in RESOLUTIONS} - set(result)
    if missing:
        raise RecipeError(f"diagnostic report lacks roles: {sorted(missing)}")
    return result


def _xml_paths_from_report(report: Mapping[str, Any]) -> dict[str, Path]:
    rows = _report_native_rows(report)
    result: dict[str, Path] = {}
    for role, _ in RESOLUTIONS:
        source = rows[role].get("source")
        if not isinstance(source, dict) or not isinstance(source.get("xml"), str):
            raise RecipeError(f"diagnostic report lacks XML source for {role}")
        result[role] = Path(str(source["xml"]))
    return result


def _physical_projection(parsed: Mapping[str, Any]) -> dict[str, Any]:
    """Fields that must remain continuous-physics invariant."""

    constants = parsed.get("constants") or {}
    physical_constant_names = ("data2d", "gravity", "cflnumber", "gamma", "rhop0")
    physical_constants = {
        name: constants[name] for name in physical_constant_names if name in constants
    }
    return {
        "body": parsed["body"],
        "wall": parsed["wall"],
        "floating": parsed["floating"],
        "physical_constants": physical_constants,
        "execution_parameters": parsed["execution_parameters"],
        "motion_xml": parsed["motion_xml"],
    }


def _compare_physical_inputs(parsed: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    roles = [role for role, _ in RESOLUTIONS]
    base = _physical_projection(parsed[roles[0]])
    comparisons: dict[str, Any] = {}
    for role in roles:
        projection = _physical_projection(parsed[role])
        comparisons[role] = {
            "matches_coarse_physical_projection": projection == base,
            "physical_projection_sha256": _hash_json(projection),
            "numeric_fields": {
                "dp_m": parsed[role]["dp_m"],
                "pointref_m": parsed[role]["pointref_m"],
                "pointmin_m": parsed[role]["pointmin_m"],
                "pointmax_m": parsed[role]["pointmax_m"],
                "fluid_numeric_drawbox": parsed[role]["fluid_numeric_drawbox"],
                "particle_declaration": parsed[role]["particle_declaration"],
                "numeric_constants": {
                    name: parsed[role].get("constants", {}).get(name)
                    for name in ("dp", "h", "b", "massbound", "massfluid")
                    if name in parsed[role].get("constants", {})
                },
            },
        }
    return {
        "all_physical_projections_identical": all(
            item["matches_coarse_physical_projection"] for item in comparisons.values()
        ),
        "roles": comparisons,
        "interpretation": (
            "The XMLs preserve the body/wall/floating/control projection only if the "
            "reported comparisons are true; dp, lattice phase, computational bounds "
            "and fluid construction box remain numeric fields."
        ),
    }


def _canonical_binding_review(
    parsed: Mapping[str, Mapping[str, Any]], mother: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare immutable XML body/wall values with the canonical mother."""

    body = mother.get("body")
    tank = mother.get("tank")
    if not isinstance(body, dict) or not isinstance(tank, dict):
        raise RecipeError("canonical mother lacks body or tank")
    body_point = _vector(body.get("point"), "canonical body.point")
    body_size = _vector(body.get("size"), "canonical body.size")
    body_mass = _number(body.get("mass_kg"), "canonical body.mass_kg")
    body_mkbound = int(body.get("mkbound"))
    tank_point = _vector(tank.get("low"), "canonical tank.low")
    tank_size = _vector(tank.get("size"), "canonical tank.size")
    center = [(body_point[index] + body_size[index] / 2.0) for index in range(3)]
    expected_inertia = mother.get("body_inertia_kg_m2")
    if not isinstance(expected_inertia, list):
        raise RecipeError("canonical mother lacks body_inertia_kg_m2")
    expected_diagonal = [
        _number(expected_inertia[index][index], f"canonical inertia[{index}][{index}]")
        for index in range(3)
    ]
    roles: dict[str, Any] = {}
    for role, parsed_row in parsed.items():
        xml_body = parsed_row["body"]
        xml_wall = parsed_row["wall"]
        xml_floating = parsed_row["floating"]
        body_ok = (
            _close(xml_body["point_m"], body_point)
            and _close(xml_body["size_m"], body_size)
            and int(xml_floating["mkbound"]) == body_mkbound
            and abs(float(xml_floating["massbody_kg"]) - body_mass) <= 1e-8
            and _close(xml_floating["center_m"], center)
            and _close(xml_floating["inertia_kg_m2"], expected_diagonal)
        )
        wall_ok = _close(xml_wall["point_m"], tank_point) and _close(
            xml_wall["size_m"], tank_size
        )
        roles[role] = {
            "body_and_rigid_constants_match_canonical": body_ok,
            "tank_wall_matches_canonical": wall_ok,
            "continuous_binding_verified": body_ok and wall_ok,
        }
    return {
        "roles": roles,
        "all_roles_match_canonical": all(
            row["continuous_binding_verified"] for row in roles.values()
        ),
        "canonical_fluid_region_is_separate_from_numeric_drawbox": True,
        "interpretation": (
            "The canonical liquid region is retained as a continuous contract. "
            "Per-resolution fluid drawbox coordinates are recorded as numeric construction fields."
        ),
    }


def _source_inventory(
    report_path: Path,
    evidence_path: Path | None,
    mother_path: Path,
    xml_paths: Mapping[str, Path],
) -> dict[str, Any]:
    files: dict[str, str] = {}
    for path in [report_path, mother_path, FUNCTIONS_MATH, JCASE_VRES, CHANGES, *xml_paths.values()]:
        if path.is_file():
            files[str(path.resolve())] = sha256_file(path)
    if evidence_path is not None and evidence_path.is_file():
        files[str(evidence_path.resolve())] = sha256_file(evidence_path)
    return {
        "sha256": files,
        "diagnostic_report": str(report_path.resolve()),
        "actual_evidence": str(evidence_path.resolve()) if evidence_path is not None else None,
        "canonical_mother": str(mother_path.resolve()),
        "no_raw_h5_or_vtk_rescan_performed": True,
    }


def _load_json(path: Path, label: str) -> dict[str, Any]:
    _require_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RecipeError(f"{label} root must be an object")
    return value


def build_proposal(
    *,
    actual_report_path: Path = ACTUAL_REPORT,
    actual_evidence_path: Path | None = ACTUAL_EVIDENCE,
    canonical_mother_path: Path = CANONICAL_MOTHER,
) -> dict[str, Any]:
    """Build a JSON-serializable static proposal from immutable evidence."""

    report = _load_json(actual_report_path, "F6 diagnostic report")
    mother = _load_json(canonical_mother_path, "F6 canonical physical mother")
    xml_paths = _xml_paths_from_report(report)
    parsed = {role: parse_definition(path) for role, path in xml_paths.items()}
    native_rows = _report_native_rows(report)

    body = mother.get("body")
    if not isinstance(body, dict):
        raise RecipeError("canonical mother lacks body")
    low = _vector(body.get("point"), "canonical body.point")
    size = _vector(body.get("size"), "canonical body.size")
    body_mass = _number(body.get("mass_kg"), "canonical body.mass_kg")
    mkbound = int(body.get("mkbound"))
    high = [low[index] + size[index] for index in range(3)]
    expected_center = [(low[index] + high[index]) / 2.0 for index in range(3)]

    candidates: list[dict[str, Any]] = []
    for role, dp in RESOLUTIONS:
        target = centered_box_recipe(low, size, dp)
        native = native_rows[role]
        target["role"] = role
        target["native_observation"] = {
            "type2_count": native.get("type2_count"),
            "point_min_m": native.get("point_min_m"),
            "point_max_m": native.get("point_max_m"),
            "point_centroid_m": native.get("point_centroid_m"),
            "declared_rigid_center_m": native.get("declared_rigid_center_m"),
            "centroid_minus_declared_center_m": native.get(
                "point_centroid_minus_declared_center_m"
            ),
            "source_xml": parsed[role]["path"],
            "source_xml_sha256": parsed[role]["sha256"],
            "source_pointref_m": parsed[role]["pointref_m"],
            "source_body_drawbox": parsed[role]["body"],
            "source_particle_declaration": parsed[role]["particle_declaration"],
            "source_constants": parsed[role]["constants"],
            "source_masspart_not_inferred": False,
        }
        target["native_matches_ideal_target"] = native_matches_target(native, target)
        target["future_native_gate"] = {
            "expected_type2_count": target["ideal_type2_count"],
            "expected_first_center_m": target["ideal_first_center_m"],
            "expected_last_center_m": target["ideal_last_center_m"],
            "expected_centroid_m": expected_center,
            "strict_inside_continuous_box": True,
            "allowance": "Only documented floating-point readback tolerance; no point outside the continuous box.",
        }
        candidates.append(target)

    physical_inputs = _compare_physical_inputs(parsed)
    canonical_binding = _canonical_binding_review(parsed, mother)
    report_heave = report.get("heave")
    source_hashes = _source_inventory(
        actual_report_path,
        actual_evidence_path,
        canonical_mother_path,
        xml_paths,
    )

    return {
        "schema": SCHEMA,
        "created_by": "ds_data02_f6_body_cellcenter_recipe_v1.py",
        "scope": "static discrete body phase proposal; no GenCase, solver, GPU, or conversion was run",
        "family_id": "F6",
        "status": "static_proposal_pending_native_revalidation",
        "q_i_status": "not_assessed_by_this_proposal",
        "q_n_status": "not_assessed",
        "production_approval": "none",
        "solver_or_gencase_started": False,
        "source_inventory": source_hashes,
        "actual_diagnostic": {
            "report_schema": report.get("schema"),
            "report_status": report.get("q_n_status"),
            "heave": report_heave,
            "observed_limitation": report.get("limitations"),
            "observed_resolution_rows": [
                {
                    "role": row.get("role"),
                    "dp_m": row.get("dp_m"),
                    "type2_count": row.get("type2_count"),
                    "centroid_offset_m": row.get("point_centroid_minus_declared_center_m"),
                    "count_times_dp_cubed_proxy_m3": row.get("count_times_dp_cubed_proxy_m3"),
                }
                for row in (native_rows[role] for role, _ in RESOLUTIONS)
            ],
        },
        "continuous_physical_mother": {
            "source_path": str(canonical_mother_path.resolve()),
            "body_low_m": low,
            "body_high_m": high,
            "body_size_m": size,
            "body_volume_m3": math.prod(size),
            "body_mass_kg": body_mass,
            "mkbound": mkbound,
            "declared_center_m": expected_center,
            "source_inertia_kg_m2": body.get("body_inertia_kg_m2"),
            "body_fields_are_frozen": True,
            "mass_normalization": "forbidden",
            "note": "N*dp^3 is a lattice-count proxy, not the physical displaced volume or a cause attribution.",
        },
        "physical_input_review": physical_inputs,
        "canonical_binding_review": canonical_binding,
        "candidates": candidates,
        "official_grid_evidence": {
            "calc_round_pos": {
                "path": str(FUNCTIONS_MATH.resolve()),
                "lines": "381-383",
                "formula": "posmin + dp * round((pos - posmin) / dp)",
            },
            "fit_domain": {
                "path": str(JCASE_VRES.resolve()),
                "lines": "727-745",
                "meaning": "pointmin/pointmax are rounded to the XML pointref lattice and expanded by dp when needed",
            },
            "pointref_loader": {
                "path": str(JCASE_VRES.resolve()),
                "lines": "967-985",
                "meaning": "XML pointref is consumed as the numerical lattice reference",
            },
            "interpretation": (
                "The candidate body first centers and inner span are ideal coordinates. "
                "They must be checked against the actual GenCase command and PartVTK output; "
                "the proposal cannot promote them to native evidence."
            ),
        },
        "numeric_candidate_policy": {
            "body_drawbox_point": "continuous_low + dp/2",
            "body_drawbox_size": "continuous_size - dp",
            "recommended_pointref": "dp/2 in x,y,z, subject to re-auditing all tank/fluid/support populations",
            "coarse_note": "coarse currently uses pointref=0; changing it is a numerical phase change and requires a full boundary/fluid re-audit",
            "medium_fine_note": "medium and fine already use pointref=dp/2, but their current body drawbox starts at the continuous low face; the body-only candidate still requires native verification",
            "physical_changes_allowed": [],
            "solver_boundary_model": "unchanged; do not switch DBC/mDBC as part of this proposal",
        },
        "future_native_acceptance_gates": [
            "Run only through the shared CPU runner after parent review; no direct GenCase/solver launch from this proposal.",
            "Verify generated XML/BI4 provenance and command prefix, then inspect official PartVTK/native output, not JSON metadata alone.",
            "Typed (Zone,Id) type-2 count must equal each candidate target and every position must be finite and strictly inside the frozen continuous body box within a declared readback tolerance.",
            "Native first/last center and centroid must match the candidate and the frozen physical center; report all residuals and duplicates.",
            "Keep massbody=128 kg, center, inertia, density/control, liquid, tank and rigid definitions bound to the frozen source; report native MassPart separately and never rescale mass.",
            "Re-audit fixed wall/fluid coverage and any other population affected by a global pointref change; a body centroid match alone cannot establish equivalence.",
            "Record actual GenCase/PartVTK counts and source hashes before any solver request; leave Q-I/Q-N/production pending until their independent evidence exists.",
        ],
        "next_action": "Root review of this static proposal; if accepted, schedule bounded CPU GenCase plus official initial PartVTK validation for each DP as a new immutable attempt.",
    }


def write_proposal(output_path: Path = OUTPUT, **kwargs: Any) -> dict[str, Any]:
    proposal = build_proposal(**kwargs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return proposal


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual-report", type=Path, default=ACTUAL_REPORT)
    parser.add_argument("--actual-evidence", type=Path, default=ACTUAL_EVIDENCE)
    parser.add_argument("--canonical-mother", type=Path, default=CANONICAL_MOTHER)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    proposal = write_proposal(
        args.output,
        actual_report_path=args.actual_report,
        actual_evidence_path=args.actual_evidence,
        canonical_mother_path=args.canonical_mother,
    )
    print(json.dumps({
        "output": str(args.output.resolve()),
        "schema": proposal["schema"],
        "status": proposal["status"],
        "solver_or_gencase_started": proposal["solver_or_gencase_started"],
        "roles": [row["role"] for row in proposal["actual_diagnostic"]["observed_resolution_rows"]],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
