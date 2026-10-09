#!/usr/bin/env python3
"""Report F7 fixed-owner lattice phase and source-control mismatch.

This is a JSON/XML-only diagnostic.  It does not construct a GenCase input,
read a native payload, search for a particle count, or start GenCase/solver.
The source control XML and the candidate ``.025`` Def are kept as separate
declarations.  The report therefore records why the current coarse result
cannot be used as a source-preserving owner match, even though a deterministic
owner-envelope lattice can be calculated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f7.s1.fixed-owner-phase-diagnostic.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.fixed-owner-phase-diagnostic.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
CURRENT_INDEX = 288
OWNER_LOW = (-0.55, -0.35, 0.05)
OWNER_HIGH = (0.55, 0.35, 0.482)
PADDLE_LOW = (-0.07, -0.24, 0.05)
PADDLE_HIGH = (-0.01, 0.24, 0.53)
OWNER_MASS_KG = 320.1984
DP_M = 0.025
SOURCE_DP_M = 0.02
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".vtk", ".obi4", ".bi4", ".bi2", ".bi1"}


class DiagnosticError(ValueError):
    """Raised when a source-bound phase diagnostic is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def static_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DiagnosticError(f"source is not a regular file: {path}")
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
        raise DiagnosticError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DiagnosticError(f"{label} must be an object: {path}")
    return value


def expect(actual: Any, wanted: Any, label: str) -> None:
    if actual != wanted:
        raise DiagnosticError(f"{label}: expected {wanted!r}, got {actual!r}")


def number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DiagnosticError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise DiagnosticError(f"{label} is not finite")
    return result


def vector(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise DiagnosticError(f"{label} is not a three-vector")
    return tuple(number(item, f"{label}[{i}]") for i, item in enumerate(value))


def close_vec(actual: tuple[float, ...], wanted: tuple[float, ...], label: str, tol: float = 2e-15) -> None:
    if len(actual) != len(wanted) or any(abs(a - b) > tol for a, b in zip(actual, wanted)):
        raise DiagnosticError(f"{label}: expected {wanted!r}, got {actual!r}")


def load_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise DiagnosticError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("key"), str):
            raise DiagnosticError("malformed source reference")
        key = ref["key"]
        if key in paths:
            raise DiagnosticError(f"duplicate source reference: {key}")
        path = Path(str(ref.get("path", ""))).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise DiagnosticError(f"{key} points to forbidden native payload: {path}")
        if path.suffix.lower() not in {".json", ".xml"}:
            raise DiagnosticError(f"{key} is not JSON/XML: {path}")
        actual = static_record(path)
        if ref.get("sha256") not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(ref["sha256"]), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if ref.get(field) is not None:
                expect(actual[field], int(ref[field]), f"{key} {field}")
        paths[key] = path
        records[key] = actual
        if ref.get("kind", "json") == "json":
            docs[key] = read_json(path, key)
    return paths, records, docs


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def xml_number(element: ET.Element, attribute: str, label: str) -> float:
    return number(element.get(attribute), f"{label}.{attribute}")


def parse_declared_dp(path: Path, label: str) -> float:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise DiagnosticError(f"{label} cannot be parsed: {path}") from exc
    definition = next((node for node in root.iter() if local_tag(node) == "definition"), None)
    if definition is None:
        raise DiagnosticError(f"{label} lacks geometry definition")
    return xml_number(definition, "dp", label)


def current_binding(current: dict[str, Any]) -> dict[str, Any]:
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise DiagnosticError("CURRENT336 does not expose exactly 336 cases")
    row = cases[CURRENT_INDEX]
    if not isinstance(row, dict):
        raise DiagnosticError("CURRENT F7 row is malformed")
    expect(row.get("family_id"), "F7", "CURRENT family")
    expect(row.get("physical_case_id"), CASE_ID, "CURRENT physical case")
    expect(row.get("runtime_case_alias"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE", "CURRENT runtime alias")
    return {
        "case_key": row.get("case_key"),
        "index": CURRENT_INDEX,
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "runtime_case_alias": row["runtime_case_alias"],
    }


def _find_coarse(proof: dict[str, Any]) -> dict[str, Any]:
    rows = proof.get("rung_summaries")
    if not isinstance(rows, list):
        raise DiagnosticError("ROOT149 proof lacks rung_summaries")
    for row in rows:
        if isinstance(row, dict) and row.get("label") == "coarse":
            return row
    raise DiagnosticError("ROOT149 proof lacks coarse summary")


def _axis_phase(low: float, high: float, step: float) -> dict[str, Any]:
    lo, hi, dp = Decimal(str(low)), Decimal(str(high)), Decimal(str(step))
    exact = (hi - lo) / dp
    whole = int(exact.to_integral_value(rounding=ROUND_FLOOR))
    remainder = hi - lo - Decimal(whole) * dp
    return {
        "low_m": float(lo),
        "high_m": float(hi),
        "span_m": float(hi - lo),
        "span_over_dp": float(exact),
        "whole_contained_cells": whole,
        "covered_length_m": float(Decimal(whole) * dp),
        "unrepresented_high_tail_m": float(remainder),
        "low_phase_mod_dp": float((lo / dp) % 1),
        "high_phase_mod_dp": float((hi / dp) % 1),
    }


def _cell_center_inside_paddle(center: tuple[float, float, float]) -> bool:
    return all(PADDLE_LOW[i] <= center[i] < PADDLE_HIGH[i] for i in range(3))


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path.resolve(), "F7 phase manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    paths, records, docs = load_refs(manifest)
    required = ("current336", "owner_metadata", "source_control_xml", "coarse_def", "root149_proof", "root154_proof", "root146_proof")
    for key in required:
        if key not in paths:
            raise DiagnosticError(f"required source reference is missing: {key}")
    current = current_binding(docs["current336"])
    owner = docs["owner_metadata"].get("physical_binding")
    if not isinstance(owner, dict):
        raise DiagnosticError("owner metadata lacks physical_binding")
    expect(owner.get("physical_case_id"), CASE_ID, "owner physical case")
    geometry = owner.get("geometry")
    if not isinstance(geometry, dict):
        raise DiagnosticError("owner metadata lacks geometry")
    envelope = geometry.get("fluid_envelope")
    if not isinstance(envelope, dict):
        raise DiagnosticError("owner metadata lacks fluid_envelope")
    owner_low = vector(envelope.get("low_m"), "owner low")
    owner_size = vector(envelope.get("size_m"), "owner size")
    owner_high = tuple(owner_low[i] + owner_size[i] for i in range(3))
    close_vec(owner_low, OWNER_LOW, "owner low")
    close_vec(owner_high, OWNER_HIGH, "owner high")
    paddle = geometry.get("paddle")
    if not isinstance(paddle, dict):
        raise DiagnosticError("owner metadata lacks paddle geometry")
    paddle_low = vector(paddle.get("low_m"), "owner paddle low")
    paddle_size = vector(paddle.get("size_m"), "owner paddle size")
    paddle_high = tuple(paddle_low[i] + paddle_size[i] for i in range(3))
    close_vec(paddle_low, PADDLE_LOW, "owner paddle low")
    close_vec(paddle_high, PADDLE_HIGH, "owner paddle high")
    initial = owner.get("initial_state")
    if not isinstance(initial, dict):
        raise DiagnosticError("owner metadata lacks initial_state")
    expect(initial.get("initial_mass_total_kg"), OWNER_MASS_KG, "owner mass")
    source_dp = parse_declared_dp(paths["source_control_xml"], "source control XML")
    coarse_dp = parse_declared_dp(paths["coarse_def"], "candidate coarse Def")
    expect(source_dp, SOURCE_DP_M, "source XML dp")
    expect(coarse_dp, DP_M, "candidate coarse Def dp")
    coarse = _find_coarse(docs["root149_proof"])
    expect(coarse.get("exact_outside_count_reproduced"), True, "ROOT149 exact outside count")
    root154 = docs["root154_proof"]
    root146 = docs["root146_proof"]
    coarse_rung146 = next((r for r in root146.get("rungs", []) if isinstance(r, dict) and r.get("label") == "coarse"), None)
    if not isinstance(coarse_rung146, dict):
        raise DiagnosticError("ROOT146 proof lacks coarse rung")
    phase = {axis: _axis_phase(owner_low[i], owner_high[i], DP_M) for i, axis in enumerate(("x", "y", "z"))}
    dimensions = tuple(int(phase[a]["whole_contained_cells"]) for a in ("x", "y", "z"))
    center_excluded = 0
    for ix in range(dimensions[0]):
        x = owner_low[0] + (ix + 0.5) * DP_M
        for iy in range(dimensions[1]):
            y = owner_low[1] + (iy + 0.5) * DP_M
            for iz in range(dimensions[2]):
                z = owner_low[2] + (iz + 0.5) * DP_M
                if _cell_center_inside_paddle((x, y, z)):
                    center_excluded += 1
    cell_count = math.prod(dimensions)
    selected_count = cell_count - center_excluded
    represented_mass = selected_count * DP_M**3 * 1000.0
    return {
        "schema": SCHEMA,
        "status": "F7_FIXED_OWNER_PHASE_AND_SOURCE_DP_MISMATCH_NO_GENCASE",
        "current_binding": current,
        "source_inputs": records,
        "source_contract": {
            "owner_envelope_m": {"low": list(owner_low), "high": list(owner_high)},
            "owner_mass_kg": OWNER_MASS_KG,
            "density_kg_m3": 1000.0,
            "source_control_dp_m": source_dp,
            "candidate_coarse_def_dp_m": coarse_dp,
            "lattice_dp_m": DP_M,
            "source_control_and_candidate_dp_match": False,
            "source_control_and_lattice_dp_match": False,
            "candidate_and_lattice_dp_match": True,
        },
        "phase_and_quadrature": {
            "axes": phase,
            "full_contained_cell_count": cell_count,
            "paddle_center_excluded_cell_count": center_excluded,
            "selected_cell_count": selected_count,
            "paddle_center_rule": "half-open center membership; source GenCase boundary semantics remain UNKNOWN",
            "owner_paddle_m": {"low": list(paddle_low), "high": list(paddle_high)},
            "represented_mass_kg": represented_mass,
            "represented_minus_owner_mass_kg": represented_mass - OWNER_MASS_KG,
            "represented_minus_owner_fraction": represented_mass / OWNER_MASS_KG - 1.0,
            "mass_fit_search": False,
            "target_count_search": False,
            "quadrature_rule": "full cells contained by declared owner envelope; no mass-fit or source selector replacement",
            "z_tail_is_unrepresented_support_not_spill": True,
        },
        "observed_prior_evidence": {
            "ROOT149_coarse_actual": {
                "fluid_count": coarse.get("fluid_count"),
                "fluid_bounds_m": coarse.get("fluid_bounds_m"),
                "outside_owner_envelope_count": coarse.get("outside_owner_envelope_count"),
                "outside_face_counts_unique_ids": coarse.get("face_counts_unique_outside_ids"),
                "max_positive_violation_distance_m": coarse.get("max_positive_violation_distance_m"),
                "selector_union_m": coarse.get("selector_vs_owner_paddle", {}).get("selector_union_low_m"),
                "selector_semantics": coarse.get("sampling_diagnostic", {}).get("inclusive_or_cell_center_mechanism"),
            },
            "ROOT146_coarse_actual": {
                "fluid_count": coarse_rung146.get("fluid_particles"),
                "fluid_mass_kg": coarse_rung146.get("fluid_mass_kg"),
                "observed_minus_owner_pct": coarse_rung146.get("observed_minus_owner_pct"),
                "fluid_support_scope": coarse_rung146.get("support_diagnostics", {}).get("fluid_support_scope"),
            },
            "ROOT154_candidate": {
                "predicted_cells": root154.get("root_independent_lattice_count"),
                "predicted_mass_kg": root154.get("predicted_mass_kg"),
                "support_is_cropped_or_shifted": True,
                "not_a_source_preserving_match": True,
            },
        },
        "interpretation": {
            "initial_mass_matching_status": "UNSUPPORTED_FOR_CURRENT_DP025_SOURCE_CONTROL_DP020",
            "why_current_coarse_is_not_a_match": [
                "The bound source control declares dp=.02 while the candidate coarse Def and fixed-owner lattice use dp=.025.",
                "The owner z span is 17.28 lattice cells, leaving a .007 m high tail under full-cell containment.",
                "ROOT149 shows the actual coarse selector/lattice phase and boundary semantics are not established by this source-only calculation.",
                "ROOT154 obtains mass agreement by a cropped/shifted selector and is therefore a separate sensitivity candidate.",
            ],
            "minimum_alternative_recipe_evidence": [
                "An explicit continuous-owner geometry/clip/transform contract bound to the same control.",
                "A declared cell quadrature and lattice-phase/boundary-inclusion rule, with no count-to-mass search.",
                "A source-preserving generated-input audit before any scientific comparison.",
            ],
            "physical_fate_or_dynamics": "UNKNOWN",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
        "read_policy": {"json_xml_only": True, "h5_opened": False, "bi4_opened": False, "obi4_opened": False, "vtk_opened": False, "solver_started": False, "gencase_started": False, "old_products_modified": False},
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise DiagnosticError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, derive(args.manifest))
    except DiagnosticError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
