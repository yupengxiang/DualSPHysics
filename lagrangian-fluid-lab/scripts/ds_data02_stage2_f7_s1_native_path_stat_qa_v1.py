#!/usr/bin/env python3
"""Bounded F7-S1 initial-output path/stat audit.

This is a forward-only companion to the source/control QA.  The three
already-produced GenCase ``generated.bi4`` files are registered as
``stat_only`` inputs.  The worker checks that each file still belongs to its
registered GenCase output root and that its metadata is unchanged, but it
never opens, hashes, or decodes a BI4/VTK/native payload.  XML particle
summaries and receipts are small metadata and are read normally.

The result identifies what is already observable (resolution-dependent counts,
metadata bounds, and output-tree identity) and leaves lattice phase, clipping
mechanism, solver sampling, contact, and physical fate UNKNOWN.  A GenCase
payload is not a solver frame, so these stats cannot be used as a coarse-grid
repair or as a numerical qualification result.
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


SCHEMA = "ds02.stage2.f7.s1.native-path-stat-qa.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.native-path-stat-qa.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
CURRENT_INDEX = 288
FORBIDDEN_STATIC_SUFFIXES = {".h5", ".hdf5", ".hdf", ".obi4", ".bi2", ".bi1", ".vtk"}
STAT_ONLY_SUFFIXES = {".bi4", ".out", ".vtk"}
RUNG_LABELS = ("coarse", "original", "fine")
EXPECTED_DP = {"coarse": 0.025, "original": 0.02, "fine": 0.016}


class NativePathStatQAError(ValueError):
    """Raised when the stat-only source contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_only(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise NativePathStatQAError(f"stat-only source is not a regular file: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "st_dev": value.st_dev,
        "st_ino": value.st_ino,
        "sha256": "NOT_READ_BY_POLICY",
    }


def static_stat(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise NativePathStatQAError(f"source is not a regular file: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "st_dev": value.st_dev,
        "st_ino": value.st_ino,
        "sha256": sha256_file(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativePathStatQAError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise NativePathStatQAError(f"{label} is not a JSON object: {path}")
    return value


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise NativePathStatQAError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise NativePathStatQAError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise NativePathStatQAError(f"{label} is not finite")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise NativePathStatQAError(f"refusing to overwrite output: {path}")
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
        raise NativePathStatQAError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise NativePathStatQAError("malformed source reference")
        key = entry["key"]
        if key in paths:
            raise NativePathStatQAError(f"duplicate source key: {key}")
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise NativePathStatQAError(f"{key} path is missing")
        path = Path(path_value).expanduser().resolve()
        read_policy = entry.get("read_policy", "content")
        if read_policy == "stat_only":
            if path.suffix.lower() not in STAT_ONLY_SUFFIXES:
                raise NativePathStatQAError(f"{key} stat-only suffix is unsupported: {path}")
            actual = stat_only(path)
            expect(entry.get("sha256"), "NOT_READ_BY_POLICY", f"{key} SHA policy")
        else:
            if path.suffix.lower() in FORBIDDEN_STATIC_SUFFIXES:
                raise NativePathStatQAError(f"{key} is a forbidden content input: {path}")
            actual = static_stat(path)
            expected = entry.get("sha256")
            if expected not in (None, "PARENT_GUARD_COMPUTED"):
                expect(actual["sha256"], str(expected), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if entry.get(field) is not None:
                expect(actual[field], int(entry[field]), f"{key} {field}")
        paths[key] = path
        stats[key] = actual
        if read_policy != "stat_only" and entry.get("kind", "json") == "json":
            docs[key] = read_json(path, key)
    return paths, stats, docs


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _control_signature(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise NativePathStatQAError(f"cannot parse generated XML: {path}") from exc
    rows: list[tuple[str, tuple[tuple[str, str], ...], str]] = []

    def walk(element: ET.Element, name: str, *, in_particles: bool = False) -> None:
        tag = _tag(element)
        if in_particles or tag == "particles" or "/particles/" in name:
            return
        attrs = tuple((k, v) for k, v in sorted(element.attrib.items()) if not (name == "/case" and k in {"app", "date"}))
        # ``dp`` is the one intended resolution change.  The generated XML
        # keeps it on the geometry definition, so remove it before comparing
        # the otherwise common control/geometry/motion contract.
        if tag == "definition":
            attrs = tuple((k, v) for k, v in attrs if k != "dp")
        if "/constants[" in name and tag in {"dp", "h", "b", "massbound", "massfluid"}:
            return
        rows.append((name, attrs, (element.text or "").strip()))
        indexes: dict[str, int] = {}
        for child in list(element):
            child_tag = _tag(child)
            index = indexes.get(child_tag, 0)
            indexes[child_tag] = index + 1
            walk(child, f"{name}/{child_tag}[{index}]", in_particles=(tag == "particles"))

    walk(root, f"/{_tag(root)}")
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _generated_summary(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise NativePathStatQAError(f"cannot parse generated XML: {path}") from exc
    definition = root.find(".//geometry/definition")
    particles = root.find(".//execution/particles")
    fluid = root.find(".//execution/particles/fluid")
    posmin = root.find(".//execution/particles/_summary/positions/posmin")
    posmax = root.find(".//execution/particles/_summary/positions/posmax")
    if definition is None or particles is None or fluid is None or posmin is None or posmax is None:
        raise NativePathStatQAError(f"generated XML lacks required particle summary: {path}")
    constants = {e.tag.rsplit("}", 1)[-1]: e.get("value") for e in root.findall(".//execution/constants/*")}
    try:
        total = int(particles.get("np", ""))
        fluid_count = int(fluid.get("count", ""))
    except ValueError as exc:
        raise NativePathStatQAError(f"generated XML particle count is not integer: {path}") from exc
    def vector(element: ET.Element) -> list[float]:
        return [finite(element.get(axis), f"{path}:{axis}") for axis in ("x", "y", "z")]
    return {
        "dp_m": finite(definition.get("dp"), "generated dp"),
        "h_m": finite(constants.get("h"), "generated h"),
        "massfluid_kg": finite(constants.get("massfluid"), "generated massfluid"),
        "total_particles": total,
        "fluid_particles": fluid_count,
        "fluid_mk": fluid.get("mk"),
        "fluid_mkfluid": fluid.get("mkfluid"),
        "position_summary_min_m": vector(posmin),
        "position_summary_max_m": vector(posmax),
        "control_signature": _control_signature(path),
    }


def _candidate(audit: dict[str, Any], label: str) -> dict[str, Any]:
    family = audit.get("families", {}).get("F7-S1")
    if not isinstance(family, dict):
        raise NativePathStatQAError("initial audit has no F7-S1 family")
    for row in family.get("candidate_initial_and_mk_audits", []):
        if isinstance(row, dict) and row.get("label") == label:
            return row
    raise NativePathStatQAError(f"initial audit lacks {label}")


def _receipt(path: Path, label: str) -> dict[str, Any]:
    receipt = read_json(path, label)
    expect(receipt.get("schema"), "ds02.execution-receipt.v1", f"{label} schema")
    expect(receipt.get("status"), "completed", f"{label} status")
    expect(receipt.get("returncode"), 0, f"{label} returncode")
    return receipt


def build_report(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path, "F7 stat-only manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    expect(manifest.get("family_id"), "F7", "manifest family")
    expect(manifest.get("sentinel_id"), "F7-S1", "manifest sentinel")
    expect(manifest.get("physical_case_id"), CASE_ID, "manifest physical case")
    paths, stats, docs = _load_refs(manifest)
    needed = {"source_status", "initial_mk_audit", "current336", "root141_proof", "root141_report", "root141_receipt", "source_control_audit"}
    missing = needed - set(docs)
    if missing:
        raise NativePathStatQAError(f"manifest source closure missing {sorted(missing)}")
    status_rows = [r for r in docs["source_status"].get("sentinels", []) if isinstance(r, dict) and r.get("sentinel_id") == "F7-S1"]
    if len(status_rows) != 1:
        raise NativePathStatQAError("source status does not contain exactly one F7-S1 row")
    expect(status_rows[0].get("physical_case_id"), CASE_ID, "source status case")
    cases = docs["current336"].get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise NativePathStatQAError("CURRENT336 must contain 336 cases")
    expect(cases[CURRENT_INDEX].get("physical_case_id"), CASE_ID, "CURRENT288 case")
    proof = docs["root141_proof"]
    expect(proof.get("current_index"), CURRENT_INDEX, "ROOT141 current index")
    expect(proof.get("H5_BI4_read_by_root"), False, "ROOT141 bounded read")
    expect(proof.get("root_array_content_read"), False, "ROOT141 array policy")
    _receipt(paths["root141_receipt"], "ROOT141 receipt")
    expect(proof.get("report"), str(paths["root141_report"]), "ROOT141 report path")
    expect(proof.get("report_sha256"), stats["root141_report"]["sha256"], "ROOT141 report SHA")
    expect(proof.get("receipt"), str(paths["root141_receipt"]), "ROOT141 receipt path")
    expect(proof.get("receipt_sha256"), stats["root141_receipt"]["sha256"], "ROOT141 receipt SHA")
    owner_mass = finite(proof.get("mass_semantics", {}).get("continuum_owner_mass_kg"), "owner mass")
    expect(owner_mass, finite(manifest.get("continuum_owner_mass_kg"), "manifest owner mass"), "owner mass")
    audit = docs["initial_mk_audit"]
    rows = manifest.get("rungs")
    if not isinstance(rows, list) or [r.get("label") for r in rows if isinstance(r, dict)] != list(RUNG_LABELS):
        raise NativePathStatQAError("manifest rungs must be coarse/original/fine")
    controls: dict[str, str] = {}
    rung_reports: list[dict[str, Any]] = []
    for rung in rows:
        label = rung["label"]
        expect(finite(rung.get("dp_m"), f"{label} dp"), EXPECTED_DP[label], f"{label} dp")
        generated_key = rung.get("generated_xml_ref")
        receipt_key = rung.get("gencase_receipt_ref")
        native_key = rung.get("native_stat_ref")
        for key in (generated_key, receipt_key, native_key):
            if not isinstance(key, str) or key not in paths:
                raise NativePathStatQAError(f"{label} source key is missing")
        summary = _generated_summary(paths[generated_key])
        expect(summary["dp_m"], EXPECTED_DP[label], f"{label} generated dp")
        expect(summary["fluid_mk"], "2", f"{label} fluid Mk")
        expect(summary["fluid_mkfluid"], "1", f"{label} fluid MKfluid")
        candidate = _candidate(audit, label)
        expect(candidate["generated_xml"]["file"]["path"], str(paths[generated_key]), f"{label} XML path")
        expect(candidate["generated_xml"]["file"]["sha256"], stats[generated_key]["sha256"], f"{label} XML SHA")
        expect(candidate["gencase_receipt"]["path"], str(paths[receipt_key]), f"{label} receipt path")
        expect(candidate["gencase_receipt"]["sha256"], stats[receipt_key]["sha256"], f"{label} receipt SHA")
        receipt = _receipt(paths[receipt_key], f"{label} GenCase receipt")
        expected_case_id = rung.get("preflight_case_id")
        expect(receipt.get("request", {}).get("case_id"), expected_case_id, f"{label} receipt case")
        output_root = Path(candidate["gencase_terminal"]["output_root"]).expanduser().resolve()
        native_path = paths[native_key]
        try:
            native_path.relative_to(output_root)
        except ValueError as exc:
            raise NativePathStatQAError(f"{label} stat-only payload escapes registered output root") from exc
        expect(native_path.name, "generated.bi4", f"{label} prepared BI4 name")
        if stats[native_key]["sha256"] != "NOT_READ_BY_POLICY":
            raise NativePathStatQAError(f"{label} native payload was not marked stat-only")
        controls[label] = summary["control_signature"]
        source_mass = finite(candidate["whole_initial_mass"]["source_kg"], f"{label} source mass")
        candidate_mass = finite(candidate["whole_initial_mass"]["candidate_kg"], f"{label} candidate mass")
        rung_reports.append({
            "label": label,
            "dp_m": summary["dp_m"],
            "h_m": summary["h_m"],
            "registered_output_root": str(output_root),
            "prepared_native_path": stats[native_key],
            "native_payload_sha256": "NOT_READ_BY_POLICY",
            "native_payload_content_read": False,
            "generated_xml": stats[generated_key],
            "gencase_receipt": stats[receipt_key],
            "gencase_status": "COMPLETED_METADATA_ONLY",
            "total_particles": summary["total_particles"],
            "fluid_particles": summary["fluid_particles"],
            "massfluid_kg": summary["massfluid_kg"],
            "sample_mass_kg": candidate_mass,
            "source_sample_mass_kg": source_mass,
            "sample_mass_error_pct": 100.0 * (candidate_mass - source_mass) / source_mass,
            "position_summary_min_m": summary["position_summary_min_m"],
            "position_summary_max_m": summary["position_summary_max_m"],
            "sampling_phase_clipping": {
                "solver_frames": "NONE_NO_SOLVER_RECEIPT",
                "saved_time_sampling": "UNKNOWN",
                "lattice_phase": "UNKNOWN_NATIVE_PAYLOAD_NOT_READ",
                "clipping_or_filtering_mechanism": "UNKNOWN_NATIVE_PAYLOAD_NOT_READ",
                "metadata_bounds_are_not_contact_or_spill_evidence": True,
            },
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })
    if len(set(controls.values())) != 1:
        raise NativePathStatQAError("F7-S1 generated control signatures differ")
    return {
        "schema": SCHEMA,
        "status": "SOURCE_CONTROL_AND_NATIVE_PATH_STATS_CLOSED_NO_NATIVE_CONTENT_READ",
        "family_id": "F7",
        "sentinel_id": "F7-S1",
        "physical_case_id": CASE_ID,
        "current_index": CURRENT_INDEX,
        "source_control": {
            "common_generated_control_signature": next(iter(controls.values())),
            "all_three_nonresolution_controls_equal": True,
            "continuous_owner_equivalence": "UNKNOWN",
            "owner_mass_kg": owner_mass,
            "owner_mass_is_not_discrete_denominator": True,
        },
        "native_read_policy": {
            "stat_only_paths": True,
            "content_sha256": "NOT_READ_BY_POLICY",
            "bi4_opened": False,
            "vtk_opened": False,
            "partout_opened": False,
            "hdf5_opened": False,
            "solver_started": False,
            "old_products_immutable": True,
        },
        "rungs": rung_reports,
        "scope_caveats": {
            "sampling": "No solver output exists for these three F7-S1 rungs; saved-time accuracy is UNKNOWN.",
            "phase_and_clipping": "Changing counts/bounds with dp is observed metadata; phase, clipping, and filtering mechanisms require native content and remain UNKNOWN.",
            "physical_boundary": "Generated bounds and moving/fixed declarations do not prove wall/contact or legal flux.",
            "repair": "No coarse repair is proposed by this audit; preserve mass gates and owner denominator, then require a separately source-bound candidate if root authorizes one.",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, build_report(args.manifest))
    except NativePathStatQAError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
