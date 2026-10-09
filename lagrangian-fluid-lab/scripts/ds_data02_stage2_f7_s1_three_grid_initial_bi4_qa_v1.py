#!/usr/bin/env python3
"""Guarded frame-zero QA for the three existing F7-S1 GenCase BI4 files.

The XML, receipts, and source proof are validated before any native payload is
opened.  After the shared parent reserves the attempt, the worker opens only
the three already-produced ``generated.bi4`` files, one frame each, using the
pinned F7 safe scanner.  The scanner and every memmap payload read are inside a
single pre/post stat and full-file SHA boundary per file.  No solver output,
PartOut, HDF5, VTK, or new GenCase run is touched.

The result is an initial identity/support diagnostic.  It keeps each grid's
XML/native MassFluid and particle mass separate from the 320.1984 kg
continuum-owner value.  Missing native Type/Mk arrays use an explicit header
Idp partition fallback and do not receive independent material credit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f7.s1.three-grid-initial-bi4-qa.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.three-grid-initial-bi4-qa.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
RUNTIME_ALIAS = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
CURRENT_INDEX = 288
RUNG_LABELS = ("coarse", "original", "fine")
EXPECTED_DP = {"coarse": 0.025, "original": 0.02, "fine": 0.016}
FORBIDDEN_STATIC_SUFFIXES = {".h5", ".hdf5", ".hdf", ".vtk", ".obi4", ".bi2", ".bi1", ".bi4"}


class ThreeGridQAError(ValueError):
    """Raised when the static or deferred three-grid contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def static_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ThreeGridQAError(f"static source is not a regular file: {path}")
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
        raise ThreeGridQAError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ThreeGridQAError(f"{label} is not a JSON object: {path}")
    return value


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise ThreeGridQAError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ThreeGridQAError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ThreeGridQAError(f"{label} is not finite")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise ThreeGridQAError(f"refusing to overwrite output: {path}")
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


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _control_signature(path: Path) -> str:
    """Compare generated controls while excluding resolution output."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ThreeGridQAError(f"cannot parse generated XML: {path}") from exc
    rows: list[tuple[str, tuple[tuple[str, str], ...], str]] = []

    def walk(element: ET.Element, name: str, *, under_particles: bool = False) -> None:
        tag = _tag(element)
        if under_particles or tag == "particles" or "/particles/" in name:
            return
        attrs = tuple((key, value) for key, value in sorted(element.attrib.items()) if not (name == "/case" and key in {"app", "date"}))
        if tag == "definition":
            attrs = tuple((key, value) for key, value in attrs if key != "dp")
        if "/constants[" in name and tag in {"dp", "h", "b", "massbound", "massfluid"}:
            return
        rows.append((name, attrs, (element.text or "").strip()))
        indexes: dict[str, int] = {}
        for child in list(element):
            child_tag = _tag(child)
            index = indexes.get(child_tag, 0)
            indexes[child_tag] = index + 1
            walk(child, f"{name}/{child_tag}[{index}]", under_particles=(tag == "particles"))

    walk(root, f"/{_tag(root)}")
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _generated_summary(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ThreeGridQAError(f"generated XML cannot be parsed: {path}") from exc
    definition = root.find(".//geometry/definition")
    particles = root.find(".//execution/particles")
    fluid = root.find(".//execution/particles/fluid")
    if definition is None or particles is None or fluid is None:
        raise ThreeGridQAError(f"generated XML lacks particle blocks: {path}")
    constants = {_tag(element): element.get("value") for element in root.findall(".//execution/constants/*")}
    try:
        total = int(particles.get("np", ""))
        fluid_count = int(fluid.get("count", ""))
    except ValueError as exc:
        raise ThreeGridQAError(f"generated XML particle counts are not integers: {path}") from exc
    massfluid = finite(constants.get("massfluid"), f"{path} MassFluid")
    return {
        "dp_m": finite(definition.get("dp"), f"{path} dp"),
        "h_m": finite(constants.get("h"), f"{path} h"),
        "massfluid_kg": massfluid,
        "total_particles": total,
        "fluid_particles": fluid_count,
        "fluid_mk": fluid.get("mk"),
        "fluid_mkfluid": fluid.get("mkfluid"),
        "control_signature": _control_signature(path),
    }


def _load_static_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    entries = manifest.get("source_refs")
    if not isinstance(entries, list) or not entries:
        raise ThreeGridQAError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise ThreeGridQAError("malformed source reference")
        key = entry["key"]
        if key in paths:
            raise ThreeGridQAError(f"duplicate source key: {key}")
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ThreeGridQAError(f"{key} path is missing")
        path = Path(path_value).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_STATIC_SUFFIXES:
            raise ThreeGridQAError(f"{key} is a deferred scientific payload: {path}")
        actual = static_record(path)
        expected = entry.get("sha256")
        if expected not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(expected), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if entry.get(field) is not None:
                expect(actual[field], int(entry[field]), f"{key} {field}")
        paths[key] = path
        stats[key] = actual
        if entry.get("kind", "json") == "json":
            docs[key] = read_json(path, key)
    return paths, stats, docs


def _validate_static_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = read_json(manifest_path, "three-grid BI4 manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    expect(manifest.get("family_id"), "F7", "manifest family")
    expect(manifest.get("sentinel_id"), "F7-S1", "manifest sentinel")
    expect(manifest.get("physical_case_id"), CASE_ID, "manifest physical case")
    paths, stats, docs = _load_static_refs(manifest)
    required = {
        "source_status", "current336", "owner_metadata", "root143_proof", "root143_report", "root143_receipt",
        "v2_worker", "safe_decoder", "native_decoder_helper",
    }
    missing = required - set(paths)
    if missing:
        raise ThreeGridQAError(f"manifest source closure missing {sorted(missing)}")
    current = docs["current336"].get("cases")
    if not isinstance(current, list) or len(current) != 336:
        raise ThreeGridQAError("CURRENT336 must contain exactly 336 cases")
    row = current[CURRENT_INDEX]
    expect(row.get("family_id"), "F7", "CURRENT288 family")
    expect(row.get("physical_case_id"), CASE_ID, "CURRENT288 physical case")
    expect(row.get("runtime_case_alias"), RUNTIME_ALIAS, "CURRENT288 runtime alias")
    status_rows = [r for r in docs["source_status"].get("sentinels", []) if isinstance(r, dict) and r.get("sentinel_id") == "F7-S1"]
    if len(status_rows) != 1:
        raise ThreeGridQAError("source status does not contain exactly one F7-S1 row")
    expect(status_rows[0].get("physical_case_id"), CASE_ID, "source status case")
    owner = docs["owner_metadata"].get("physical_binding", {})
    expect(owner.get("family_id"), "F7", "owner family")
    expect(owner.get("physical_case_id"), CASE_ID, "owner case")
    expect(owner.get("initial_state", {}).get("initial_mass_total_kg"), 320.1984, "continuum owner mass")

    proof = docs["root143_proof"]
    expect(proof.get("status"), "VERIFIED_ACTUAL_F7_THREE_GRID_XML_DECLARATIONS_SOURCE_MASS_DIAGNOSTIC_ONLY", "ROOT143 status")
    expect(proof.get("H5_BI4_read_by_root"), False, "ROOT143 H5/BI4 read")
    expect(proof.get("root_array_content_read"), False, "ROOT143 array read")
    expect(proof.get("report"), str(paths["root143_report"]), "ROOT143 report path")
    expect(proof.get("report_sha256"), stats["root143_report"]["sha256"], "ROOT143 report SHA")
    expect(proof.get("receipt"), str(paths["root143_receipt"]), "ROOT143 receipt path")
    expect(proof.get("receipt_sha256"), stats["root143_receipt"]["sha256"], "ROOT143 receipt SHA")
    proof_report = docs["root143_report"]
    expect(proof_report.get("schema"), "ds02.stage2.f7.s1.matched-grid-source-qa.v1", "ROOT143 report schema")
    expect(proof_report.get("current_index"), CURRENT_INDEX, "ROOT143 report current index")
    expect(proof_report.get("source_control", {}).get("all_three_generated_nonresolution_controls_equal"), True, "ROOT143 generated controls")
    expect(proof_report.get("source_control", {}).get("all_three_def_nonresolution_controls_equal"), True, "ROOT143 source controls")
    if not paths["v2_worker"].is_file() or not paths["safe_decoder"].is_file() or not paths["native_decoder_helper"].is_file():
        raise ThreeGridQAError("pinned scanner/loader source is unavailable")
    rungs = manifest.get("rungs")
    if not isinstance(rungs, list) or [r.get("label") for r in rungs if isinstance(r, dict)] != list(RUNG_LABELS):
        raise ThreeGridQAError("manifest rungs must be coarse/original/fine")
    deferred = manifest.get("deferred_inputs")
    if not isinstance(deferred, dict) or set(deferred) != set(RUNG_LABELS):
        raise ThreeGridQAError("manifest must bind exactly three deferred BI4 inputs")
    for label in RUNG_LABELS:
        entry = deferred[label]
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ThreeGridQAError(f"deferred {label} is malformed")
        if not entry["path"].lower().endswith(".bi4"):
            raise ThreeGridQAError(f"deferred {label} is not BI4")
        if int(entry.get("bytes", 0)) <= 0:
            raise ThreeGridQAError(f"deferred {label} lacks positive byte estimate")
        expect(entry.get("sha256"), "PARENT_GUARD_COMPUTED", f"deferred {label} SHA policy")
        rung = next(r for r in rungs if r["label"] == label)
        for key in ("generated_xml_ref", "gencase_receipt_ref"):
            if rung.get(key) not in paths:
                raise ThreeGridQAError(f"{label} missing {key}")
        summary = _generated_summary(paths[rung["generated_xml_ref"]])
        expect(summary["dp_m"], EXPECTED_DP[label], f"{label} generated dp")
        expect(summary["fluid_mk"], "2", f"{label} generated fluid Mk")
        expect(summary["fluid_mkfluid"], "1", f"{label} generated fluid MKfluid")
        receipt = docs.get(rung["gencase_receipt_ref"])
        if receipt is None:
            raise ThreeGridQAError(f"{label} GenCase receipt is not JSON")
        expect(receipt.get("schema"), "ds02.execution-receipt.v1", f"{label} receipt schema")
        expect(receipt.get("status"), "completed", f"{label} receipt status")
        expect(receipt.get("returncode"), 0, f"{label} receipt returncode")
        expect(receipt.get("request", {}).get("case_id"), rung.get("preflight_case_id"), f"{label} receipt case")
    return manifest, paths, stats, docs


def _load_v2_worker(path: Path):
    spec = importlib.util.spec_from_file_location("f7_s1_initial_spatial_qa_v2_for_three_grid", path)
    if spec is None or spec.loader is None:
        raise ThreeGridQAError(f"cannot load pinned F7 v2 worker: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _strip_arrays(frame: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in frame.items() if not key.startswith("_")}


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, paths, stats, docs = _validate_static_manifest(manifest_path.expanduser().resolve())
    v2 = _load_v2_worker(paths["v2_worker"])
    scanner = v2._load_scanner({"safe_decoder": paths["safe_decoder"], "native_decoder_helper": paths["native_decoder_helper"]})
    frames: dict[str, dict[str, Any]] = {}
    rung_reports: list[dict[str, Any]] = []
    controls: dict[str, str] = {}
    deferred = manifest["deferred_inputs"]
    for rung in manifest["rungs"]:
        label = rung["label"]
        generated = _generated_summary(paths[rung["generated_xml_ref"]])
        native_path = Path(deferred[label]["path"]).expanduser().resolve()
        if not native_path.is_file():
            raise ThreeGridQAError(f"deferred {label} is unavailable after reservation: {native_path}")
        stat = native_path.stat()
        expect(stat.st_size, int(deferred[label]["bytes"]), f"deferred {label} bytes")
        expected = {"expected_fluid": generated["fluid_particles"]}
        try:
            frame = v2._frame_summary(native_path, scanner, expected, f"prepared_{label}_generated_bi4")
        except Exception as exc:
            if isinstance(exc, ThreeGridQAError):
                raise
            raise ThreeGridQAError(f"{label} bounded BI4 scan failed: {exc}") from exc
        header = frame.get("header", {})
        expect(int(header.get("CaseNp")), generated["total_particles"], f"{label} BI4 CaseNp")
        expect(int(header.get("CaseNfluid")), generated["fluid_particles"], f"{label} BI4 CaseNfluid")
        expect(frame.get("total_particles"), generated["total_particles"], f"{label} BI4 total particles")
        expect(frame.get("fluid_particles"), generated["fluid_particles"], f"{label} BI4 fluid particles")
        if not math.isclose(float(header.get("MassFluid")), generated["massfluid_kg"], rel_tol=0.0, abs_tol=1e-12):
            raise ThreeGridQAError(f"{label} BI4 MassFluid differs from generated XML")
        if not frame.get("finite_positions"):
            raise ThreeGridQAError(f"{label} BI4 positions are not finite")
        if not frame.get("id_unique"):
            raise ThreeGridQAError(f"{label} BI4 Idp values are not unique")
        expect(frame.get("post_after_all_payload_reads"), True, f"{label} post hash placement")
        expect(frame.get("array_reader_content_sha256"), "NOT_COMPUTED", f"{label} array reader digest")
        controls[label] = generated["control_signature"]
        frame_public = _strip_arrays(frame)
        source_mass = generated["massfluid_kg"] * generated["fluid_particles"]
        observed_mass = finite(frame.get("fluid_mass_kg"), f"{label} observed mass")
        frame_public["generated_xml"] = generated
        frame_public["header_matches_generated_xml"] = True
        frame_public["native_header_massfluid_kg"] = float(header["MassFluid"])
        frame_public["generated_xml_massfluid_kg"] = generated["massfluid_kg"]
        frame_public["source_xml_fluid_mass_kg"] = source_mass
        frame_public["observed_fluid_mass_kg"] = observed_mass
        frame_public["continuum_owner_mass_kg"] = 320.1984
        frame_public["observed_minus_owner_pct"] = (observed_mass / 320.1984 - 1.0) * 100.0
        frame_public["native_type_mk_scope"] = (
            "native Type/Mk arrays observed in this bounded payload"
            if frame.get("native_type_array") is not None and frame.get("native_mk_array") is not None
            else "header Idp partition fallback; no independent native Type/Mk arrays"
        )
        frame_public["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "continuous_owner": "UNKNOWN", "contact": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"}
        frames[label] = frame_public
        rung_reports.append({
            "label": label,
            "dp_m": generated["dp_m"],
            "generated_xml_path": str(paths[rung["generated_xml_ref"]]),
            "prepared_bi4_path": str(native_path),
            "frame": frame_public,
            "read_scope": "one existing GenCase generated.bi4 after parent reservation; no solver frame",
        })
    expect(len(set(controls.values())), 1, "generated non-resolution control signatures")
    result = {
        "schema": SCHEMA,
        "status": "COMPLETED_F7_S1_THREE_GRID_FRAME0_BI4_IDENTITY_SUPPORT_QA",
        "family_id": "F7",
        "sentinel_id": "F7-S1",
        "physical_case_id": CASE_ID,
        "current_binding": {"index": CURRENT_INDEX, "runtime_case_alias": RUNTIME_ALIAS},
        "source_binding": {
            "root143_proof": str(paths["root143_proof"]),
            "root143_proof_sha256": stats["root143_proof"]["sha256"],
            "all_three_generated_control_signatures_equal": True,
            "common_generated_control_signature": next(iter(controls.values())),
            "continuum_owner_mass_kg": 320.1984,
            "official_discrete_sample_mass_kg": 325.60001628000003,
            "owner_and_discrete_denominators_separate": True,
        },
        "rungs": rung_reports,
        "read_policy": {
            "prepared_bi4_files_opened": 3,
            "later_native_frames_opened": 0,
            "solver_started": False,
            "gencase_started": False,
            "hdf5_opened": False,
            "partout_opened": False,
            "vtk_opened": False,
            "gpu_started": False,
            "post_hash_after_all_payload_reads": True,
            "array_reader_content_sha256": "NOT_COMPUTED",
            "old_products_immutable": True,
        },
        "scope_caveats": {
            "sampling_phase": "No solver frames are read; saved-time sampling and phase are UNKNOWN.",
            "clipping_filtering": "Observed finite frame-zero coordinates do not identify clipping/filtering mechanism.",
            "bounds": "Envelope/paddle inclusion is an observed support diagnostic, not contact, wall, legal flux, spill, or physical-fate evidence.",
            "mass": "Each XML/native header and observed particle mass remains separate from the 320.1984 kg continuum owner; no rescale or tolerance widening.",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
        },
        "old_products_unchanged": True,
    }
    atomic_json(output, result)
    print(json.dumps({"status": result["status"], "rungs": list(frames), "solver_started": False}, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.manifest, args.output)
    except (ThreeGridQAError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
