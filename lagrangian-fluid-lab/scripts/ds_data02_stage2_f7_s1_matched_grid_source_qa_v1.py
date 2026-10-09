#!/usr/bin/env python3
"""Source-only QA for the three prepared F7-S1 spatial rungs.

The existing ``.025/.020/.016`` GenCase products are useful initial-state
diagnostics, but they are not three source-matched solver runs.  This worker
re-opens only the small Def/generated XML, receipt, CURRENT, and audit JSON
files already registered in its manifest.  It never opens BI4/VTK/OBI4/HDF5,
raw solver output, or a solver.

The report keeps three mass notions separate:

* the discrete sample mass from the registered generated XML,
* the source-resolution sample mass (the 0.020 reference), and
* the 320.1984 kg continuum-owner declaration from the bounded frame-zero
  evidence.

The first two support a reproducible initialization diagnostic.  The third is
not silently substituted as a particle denominator, and no mass result gives
continuous-owner, contact, flux, fate, or QI/QN/QE credit.
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


SCHEMA = "ds02.stage2.f7.s1.matched-grid-source-qa.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.matched-grid-source-qa.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
CURRENT_INDEX = 288
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".bi2", ".bi1", ".vtk"}
RUNG_LABELS = ("coarse", "original", "fine")
EXPECTED_DP = {"coarse": 0.025, "original": 0.020, "fine": 0.016}
EXPECTED_SAMPLE = {"coarse": 356.34375, "original": 325.6, "fine": 314.413056}


class MatchedGridQAError(ValueError):
    """Raised when the source-only matched-grid contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise MatchedGridQAError(f"source is not a regular file: {path}")
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
        raise MatchedGridQAError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MatchedGridQAError(f"{label} is not a JSON object: {path}")
    return value


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise MatchedGridQAError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MatchedGridQAError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise MatchedGridQAError(f"{label} is not finite")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise MatchedGridQAError(f"refusing to overwrite output: {path}")
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


def _load_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    entries = manifest.get("source_refs")
    if not isinstance(entries, list) or not entries:
        raise MatchedGridQAError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise MatchedGridQAError("malformed source reference")
        key = entry["key"]
        if key in paths:
            raise MatchedGridQAError(f"duplicate source key: {key}")
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise MatchedGridQAError(f"{key} path is missing")
        path = Path(path_value).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise MatchedGridQAError(f"{key} is a forbidden scientific payload: {path}")
        actual = stat_record(path)
        expected_sha = entry.get("sha256")
        if expected_sha not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(expected_sha), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if entry.get(field) is not None:
                expect(actual[field], int(entry[field]), f"{key} {field}")
        paths[key] = path
        stats[key] = actual
        if entry.get("kind", "json") == "json":
            docs[key] = read_json(path, key)
    return paths, stats, docs


def _element_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _flatten_xml(path: Path, *, generated: bool) -> list[tuple[str, tuple[tuple[str, str], ...], str]]:
    """Return a deterministic control signature, excluding resolution output."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise MatchedGridQAError(f"cannot parse XML {path}") from exc
    result: list[tuple[str, tuple[tuple[str, str], ...], str]] = []

    def walk(element: ET.Element, path_name: str, *, under_particles: bool = False) -> None:
        tag = _element_tag(element)
        if generated and (under_particles or tag == "particles" or "/particles/" in path_name):
            return
        if generated and path_name == "/case":
            attrs = tuple((key, value) for key, value in sorted(element.attrib.items()) if key not in {"app", "date"})
        else:
            attrs = tuple(sorted(element.attrib.items()))
        if tag == "definition" and "dp" in dict(attrs):
            attrs = tuple((key, value) for key, value in attrs if key != "dp")
        if generated and "/constants[" in path_name and tag in {"dp", "h", "b", "massbound", "massfluid"}:
            return
        text = (element.text or "").strip()
        result.append((path_name, attrs, text))
        sibling_indices: dict[str, int] = {}
        for child in list(element):
            child_tag = _element_tag(child)
            index = sibling_indices.get(child_tag, 0)
            sibling_indices[child_tag] = index + 1
            child_path = f"{path_name}/{child_tag}[{index}]"
            walk(child, child_path, under_particles=under_particles or (tag == "particles"))

    walk(root, f"/{_element_tag(root)}")
    return result


def _xml_path_signature(path: Path, *, generated: bool) -> str:
    rows = _flatten_xml(path, generated=generated)
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _xml_values(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise MatchedGridQAError(f"cannot parse generated XML {path}") from exc
    definition = root.find(".//geometry/definition")
    if definition is None or definition.get("dp") is None:
        raise MatchedGridQAError(f"generated XML has no geometry dp: {path}")
    constants = {
        element.tag.rsplit("}", 1)[-1]: element.get("value")
        for element in root.findall(".//execution/constants/*")
    }
    particles = root.find(".//execution/particles")
    fluid = root.find(".//execution/particles/fluid")
    if particles is None or fluid is None:
        raise MatchedGridQAError(f"generated XML has no particle/fluid summary: {path}")
    def number(value: str | None, label: str) -> float:
        if value is None:
            raise MatchedGridQAError(f"{label} missing in {path}")
        return finite(value, f"{path}:{label}")
    try:
        fluid_count = int(fluid.get("count", ""))
    except ValueError as exc:
        raise MatchedGridQAError(f"fluid count is not an integer: {path}") from exc
    return {
        "dp_m": number(definition.get("dp"), "definition.dp"),
        "massfluid_kg": number(constants.get("massfluid"), "constants.massfluid"),
        "fluid_count": fluid_count,
        "fluid_mk": fluid.get("mk"),
        "fluid_mkfluid": fluid.get("mkfluid"),
        "particle_count": int(particles.get("np", "0")),
        "generated_control_signature": _xml_path_signature(path, generated=True),
    }


def _def_values(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise MatchedGridQAError(f"cannot parse Def XML {path}") from exc
    definition = root.find(".//geometry/definition")
    if definition is None or definition.get("dp") is None:
        raise MatchedGridQAError(f"Def XML has no geometry dp: {path}")
    params: dict[str, str] = {}
    for element in root.findall(".//execution/parameters/parameter"):
        key = element.get("key")
        if key:
            params[key] = element.get("value", "")
    motion = root.find(".//motion//mvrotfile/file")
    fluid = root.find(".//setmkfluid")
    if motion is None or fluid is None:
        raise MatchedGridQAError(f"Def XML lacks motion/fluid declaration: {path}")
    return {
        "dp_m": finite(definition.get("dp"), "Def dp"),
        "motion_file": motion.get("name"),
        "fluid_mk": fluid.get("mk"),
        "parameters": params,
        "control_signature": _xml_path_signature(path, generated=False),
    }


def _find_candidate(audit: dict[str, Any], label: str) -> dict[str, Any]:
    family = audit.get("families", {}).get("F7-S1")
    if not isinstance(family, dict):
        raise MatchedGridQAError("initial MK audit has no F7-S1 family")
    candidates = family.get("candidate_initial_and_mk_audits")
    if not isinstance(candidates, list):
        raise MatchedGridQAError("F7-S1 candidate audit is not a list")
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("label") == label:
            return candidate
    raise MatchedGridQAError(f"initial MK audit lacks rung {label}")


def _validate_receipt(path: Path, label: str) -> dict[str, Any]:
    receipt = read_json(path, label)
    expect(receipt.get("schema"), "ds02.execution-receipt.v1", f"{label} schema")
    expect(receipt.get("status"), "completed", f"{label} status")
    expect(receipt.get("returncode"), 0, f"{label} returncode")
    return receipt


def build_report(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path, "matched-grid source manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    expect(manifest.get("family_id"), "F7", "manifest family")
    expect(manifest.get("sentinel_id"), "F7-S1", "manifest sentinel")
    expect(manifest.get("physical_case_id"), CASE_ID, "manifest physical case")
    paths, stats, docs = _load_refs(manifest)
    required_docs = {"source_status", "next_requests", "initial_mk_audit", "source_control_audit", "current336", "root141_proof", "root141_report", "root141_receipt"}
    missing = required_docs - set(docs)
    if missing:
        raise MatchedGridQAError(f"manifest source closure missing {sorted(missing)}")

    status_rows = [row for row in docs["source_status"].get("sentinels", []) if isinstance(row, dict) and row.get("sentinel_id") == "F7-S1"]
    if len(status_rows) != 1:
        raise MatchedGridQAError("source status does not contain exactly one F7-S1 row")
    status_row = status_rows[0]
    expect(status_row.get("family_id"), "F7", "source status family")
    expect(status_row.get("physical_case_id"), CASE_ID, "source status case")
    expect(status_row.get("terminal_state", {}).get("scientific_qualification"), {"QE": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN"}, "source status qualification")

    next_rows = [row for row in docs["next_requests"].get("requests", []) if isinstance(row, dict) and row.get("sentinel_id") == "F7-S1"]
    if len(next_rows) != 1:
        raise MatchedGridQAError("next-request index does not contain exactly one F7-S1 row")
    expect(next_rows[0].get("physical_case_id"), CASE_ID, "next request case")
    if next_rows[0].get("solver_launch") is not False:
        raise MatchedGridQAError("F7-S1 source prerequisite may not launch a solver")

    current = docs["current336"]
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise MatchedGridQAError("CURRENT336 must contain exactly 336 cases")
    case = cases[CURRENT_INDEX]
    if not isinstance(case, dict):
        raise MatchedGridQAError("CURRENT288 is not an object")
    expect(case.get("family_id"), "F7", "CURRENT288 family")
    expect(case.get("physical_case_id"), CASE_ID, "CURRENT288 case")
    expect(docs["root141_proof"].get("current_index"), CURRENT_INDEX, "ROOT141 current index")
    expect(docs["root141_proof"].get("status"), "VERIFIED_ACTUAL_F7_FRAME0_IDENTITY_POSITIONS_INITIAL_SUPPORT_MASS_DIAGNOSTIC_ONLY", "ROOT141 status")
    if docs["root141_proof"].get("H5_BI4_read_by_root") is not False or docs["root141_proof"].get("root_array_content_read") is not False:
        raise MatchedGridQAError("ROOT141 proof no longer has the bounded read policy")
    root_mass = docs["root141_proof"].get("mass_semantics")
    if not isinstance(root_mass, dict):
        raise MatchedGridQAError("ROOT141 mass semantics are missing")
    owner_mass = finite(root_mass.get("continuum_owner_mass_kg"), "ROOT141 owner mass")
    discrete_mass = finite(root_mass.get("official_csv_sample_mass_kg"), "ROOT141 discrete sample mass")
    expect(owner_mass, finite(manifest.get("continuum_owner_mass_kg"), "manifest owner mass"), "continuum owner mass")
    expect(discrete_mass, finite(manifest.get("official_discrete_sample_mass_kg"), "manifest discrete mass"), "discrete sample mass")
    if docs["root141_proof"].get("qualification", {}).get("continuous_owner") != "UNKNOWN":
        raise MatchedGridQAError("ROOT141 owner qualification was unexpectedly promoted")

    # Bind proof -> report -> receipt without treating the report as a new run.
    proof = docs["root141_proof"]
    expect(proof.get("report"), str(paths["root141_report"]), "ROOT141 report path")
    expect(proof.get("report_sha256"), stats["root141_report"]["sha256"], "ROOT141 report SHA")
    expect(proof.get("receipt"), str(paths["root141_receipt"]), "ROOT141 receipt path")
    expect(proof.get("receipt_sha256"), stats["root141_receipt"]["sha256"], "ROOT141 receipt SHA")
    _validate_receipt(paths["root141_receipt"], "ROOT141 receipt")
    root_report = docs["root141_report"]
    expect(root_report.get("schema"), "ds02.stage2.f7.s1.initial-spatial-qa.v2", "ROOT141 report schema")

    rungs = manifest.get("rungs")
    if not isinstance(rungs, list) or [r.get("label") for r in rungs if isinstance(r, dict)] != list(RUNG_LABELS):
        raise MatchedGridQAError("manifest must list coarse, original, fine in order")
    audit = docs["initial_mk_audit"]
    source_control = docs["source_control_audit"]
    source_control_rows = [row for row in source_control.get("sources", []) if isinstance(row, dict) and row.get("sentinel_id") == "F7-S1"]
    if len(source_control_rows) != 1:
        raise MatchedGridQAError("source-control audit does not contain exactly one F7-S1 row")
    source_control_row = source_control_rows[0]
    source_control_xml = source_control_row.get("source_xml", {})
    if source_control_xml.get("sha256") != stats["source_control_xml"]["sha256"]:
        raise MatchedGridQAError("source-control audit XML does not bind manifest source")

    rung_reports: list[dict[str, Any]] = []
    def_signature: str | None = None
    generated_signature: str | None = None
    def_signatures: dict[str, str] = {}
    generated_signatures: dict[str, str] = {}
    source_sample_mass = finite(manifest.get("source_sample_mass_kg"), "manifest source sample mass")
    rung_by_label = {r.get("label"): r for r in rungs if isinstance(r, dict)}
    for label in RUNG_LABELS:
        rung = rung_by_label[label]
        expected_dp = finite(rung.get("dp_m"), f"{label} dp")
        expect(expected_dp, EXPECTED_DP[label], f"{label} dp")
        def_key = rung.get("definition_ref")
        generated_key = rung.get("generated_xml_ref")
        receipt_key = rung.get("gencase_receipt_ref")
        for key, role in ((def_key, "definition_ref"), (generated_key, "generated_xml_ref"), (receipt_key, "gencase_receipt_ref")):
            if not isinstance(key, str) or key not in paths:
                raise MatchedGridQAError(f"{label} {role} is not bound")
        def_values = _def_values(paths[def_key])
        generated_values = _xml_values(paths[generated_key])
        expect(def_values["dp_m"], expected_dp, f"{label} Def dp")
        expect(generated_values["dp_m"], expected_dp, f"{label} generated dp")
        expect(def_values["motion_file"], "motion_obstacle_quintic.dat", f"{label} motion")
        expect(def_values["fluid_mk"], "1", f"{label} fluid command")
        expect(generated_values["fluid_mk"], "2", f"{label} generated fluid Mk")
        expect(generated_values["fluid_mkfluid"], "1", f"{label} generated fluid MKfluid")
        candidate = _find_candidate(audit, label)
        generated_meta = candidate.get("generated_xml", {}).get("file", {})
        receipt_meta = candidate.get("gencase_receipt", {})
        expect(generated_meta.get("path"), str(paths[generated_key]), f"{label} audit generated XML path")
        expect(generated_meta.get("sha256"), stats[generated_key]["sha256"], f"{label} audit generated XML SHA")
        expect(receipt_meta.get("path"), str(paths[receipt_key]), f"{label} audit receipt path")
        expect(receipt_meta.get("sha256"), stats[receipt_key]["sha256"], f"{label} audit receipt SHA")
        receipt = _validate_receipt(paths[receipt_key], f"{label} GenCase receipt")
        expect(receipt.get("case_id", receipt.get("request", {}).get("case_id")), rung.get("preflight_case_id"), f"{label} receipt case")
        expect(generated_values["fluid_count"], int(candidate["generated_xml"]["fluid_particle_count"]), f"{label} generated fluid count")
        expect(generated_values["particle_count"], int(candidate["gencase_terminal"]["total_particles"]), f"{label} total particle count")
        calculated_mass = generated_values["massfluid_kg"] * generated_values["fluid_count"]
        candidate_mass = finite(candidate["generated_xml"]["sample_mass_kg"], f"{label} candidate sample mass")
        if not math.isclose(calculated_mass, candidate_mass, rel_tol=0.0, abs_tol=1e-10):
            raise MatchedGridQAError(f"{label} generated mass does not match XML massfluid*count")
        expect(candidate.get("gencase_terminal", {}).get("status"), "completed", f"{label} GenCase status")
        expect(candidate.get("gencase_terminal", {}).get("returncode"), 0, f"{label} GenCase returncode")
        source_error = 100.0 * (candidate_mass - source_sample_mass) / source_sample_mass
        owner_error = 100.0 * (candidate_mass - owner_mass) / owner_mass
        if abs(source_error) <= 1.0:
            screen = "PASS_TARGET_1PCT_DIAGNOSTIC"
        elif abs(source_error) > 2.0:
            screen = "HARD_FAIL_GT2PCT_DIAGNOSTIC"
        else:
            screen = "MARGINAL_1_TO_2PCT_DIAGNOSTIC"
        def_signature = def_values["control_signature"]
        generated_signature = generated_values["generated_control_signature"]
        def_signatures[label] = def_signature
        generated_signatures[label] = generated_signature
        rung_reports.append({
            "label": label,
            "dp_m": expected_dp,
            "h_m": candidate["generated_xml"].get("h_m"),
            "definition": stats[def_key],
            "generated_xml": stats[generated_key],
            "gencase_receipt": stats[receipt_key],
            "source_control_signature": def_signature,
            "generated_control_signature": generated_signature,
            "gencase": {
                "fluid_particles": generated_values["fluid_count"],
                "total_particles": generated_values["particle_count"],
                "massfluid_kg": generated_values["massfluid_kg"],
                "sample_mass_kg": candidate_mass,
                "actual_output_tree_bytes": candidate["gencase_terminal"].get("actual_output_tree_bytes"),
            },
            "mass_diagnostic": {
                "source_sample_mass_kg": source_sample_mass,
                "continuum_owner_mass_kg": owner_mass,
                "candidate_minus_source_sample_pct": source_error,
                "candidate_minus_continuum_owner_pct": owner_error,
                "source_sample_gate": screen,
                "owner_comparison": "DIAGNOSTIC_ONLY_NO_OWNER_EQUIVALENCE",
            },
            "solver_receipt": "NONE_FOR_THIS_RUNG",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })

    if len(set(def_signatures.values())) != 1:
        raise MatchedGridQAError("F7-S1 Def control/geometry/motion signatures differ")
    if len(set(generated_signatures.values())) != 1:
        raise MatchedGridQAError("F7-S1 generated control/geometry/motion signatures differ")

    return {
        "schema": SCHEMA,
        "status": "SOURCE_CONTROL_CLOSED_MASS_DIAGNOSTIC_ONLY_NO_SOURCE_MATCHED_SOLVER",
        "family_id": "F7",
        "sentinel_id": "F7-S1",
        "physical_case_id": CASE_ID,
        "current_index": CURRENT_INDEX,
        "source_control": {
            "all_three_def_nonresolution_controls_equal": True,
            "all_three_generated_nonresolution_controls_equal": True,
            "motion_asset": "motion_obstacle_quintic.dat",
            "resolution_only_source_def_difference": True,
            "generated_control_signature": next(iter(generated_signatures.values())),
            "source_def_control_signature": next(iter(def_signatures.values())),
            "continuous_owner_equivalence": "UNKNOWN",
            "reason": "XML/drawbox declarations and frame-zero owner metadata do not prove continuous support or contact geometry.",
        },
        "mass_semantics": {
            "continuum_owner_mass_kg": owner_mass,
            "official_discrete_sample_mass_kg": discrete_mass,
            "source_sample_mass_kg": source_sample_mass,
            "native_frame0_mass_kg": root_mass.get("native_part_0000_observed_fluid_mass_kg"),
            "denominator_policy": "Keep continuum-owner, discrete sample, and native frame-zero values separate; source-sample gates are initialization diagnostics only.",
            "qualification_gate": "UNKNOWN",
        },
        "rungs": rung_reports,
        "scope": {
            "reads": "small JSON/XML/receipt only",
            "forbidden_reads": ["H5", "BI4", "OBI4", "VTK", "raw solver output", "new solver/GenCase"],
            "existing_products_immutable": True,
            "solver_match": "UNKNOWN_NO_SOURCE_MATCHED_FULL_WINDOW",
            "contact_wall_flux_fate_dynamics": "UNKNOWN",
            "native_type_mk": "not measured by this metadata-only QA",
            "next_step": "If a source-matched canary is considered, obtain parent-reviewed support/mass closure first; do not inherit F7-S2 runs.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, build_report(args.manifest))
    except MatchedGridQAError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
