#!/usr/bin/env python3
"""Independent metadata verifier for the guarded raw-HDF5 field audit V3.

This verifier intentionally reads the compact manifest/report and file
metadata only.  It does not import h5py and never hashes or opens a
trajectory HDF5 file; the worker's pre/post content hashes are treated as
guarded evidence and are checked against the deferred source contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

SCRIPT = Path(__file__).resolve()
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-audit-manifest.v2"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-audit.v3"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
REQUIRED_FIELDS = ("position", "velocity", "density", "mass", "pressure", "valid", "type")
FINITE_FIELDS = ("position", "velocity", "density", "mass", "pressure")
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class VerificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise VerificationError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise VerificationError(f"{label} is not hexadecimal")
    return value


def read_json(path_value: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(path_value, (str, os.PathLike)) or not path_value:
        raise VerificationError(f"{label} lacks a path")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise VerificationError(f"{label} is missing: {path}")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise VerificationError(f"{label} exceeds the bounded JSON size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return path, value


def path_ref(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise VerificationError(f"{label} lacks a path")
    return Path(value).expanduser().resolve()


def stat_key(value: dict[str, Any], label: str) -> tuple[Any, ...]:
    try:
        return tuple(value[key] for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"))
    except KeyError as exc:
        raise VerificationError(f"{label} is missing stat field {exc.args[0]}") from exc


def current_stat(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise VerificationError(f"{label} is missing: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def one_case(rows: Any, case_id: str, label: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise VerificationError(f"{label} is not a list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise VerificationError(f"{label} has non-unique case {case_id}")
    return matches[0]



def compare_stat(expected: dict[str, Any], actual: dict[str, Any], label: str) -> None:
    for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if expected.get(key) != actual.get(key):
            raise VerificationError(f"{label} differs at {key}")


def load_static_refs(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    refs = manifest.get("static_source_refs")
    if not isinstance(refs, list) or not refs:
        raise VerificationError("manifest static_source_refs is missing")
    static: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            raise VerificationError("static source ref is not an object")
        path = path_ref(ref.get("path"), "static source ref")
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise VerificationError("verifier refuses HDF5 as a static input")
        expected = digest(ref.get("sha256"), f"static source SHA {path}")
        if sha256_file(path) != expected:
            raise VerificationError(f"static source changed: {path}")
        key = str(path)
        if key in static and static[key]["sha256"] != expected:
            raise VerificationError(f"conflicting static source refs: {path}")
        static[key] = {**ref, "path": key, "sha256": expected}
    current = manifest.get("current_catalog")
    if not isinstance(current, dict):
        raise VerificationError("manifest current_catalog is missing")
    current_path = path_ref(current.get("path"), "manifest CURRENT")
    current_sha = digest(current.get("sha256"), "manifest CURRENT SHA")
    if current_sha != CURRENT_SHA256 or sha256_file(current_path) != current_sha:
        raise VerificationError("manifest CURRENT path/SHA is not the frozen CURRENT catalog")
    current_ref = current_stat(current_path, "manifest CURRENT")
    return static, {"path": str(current_path), "sha256": current_sha, "stat": current_ref, "case_count": current.get("cases")}


def verify_case(case: dict[str, Any], result: dict[str, Any], static: dict[str, dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    case_id = case.get("physical_case_id")
    if not isinstance(case_id, str) or not case_id:
        raise VerificationError("manifest case has no physical_case_id")
    if result.get("physical_case_id") != case_id:
        raise VerificationError(f"{case_id}: result identity mismatch")
    if result.get("status") != "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT":
        raise VerificationError(f"{case_id}: unexpected result status")
    if result.get("worker_version") != "v3_vectorized_postread_guard":
        raise VerificationError(f"{case_id}: report is not from the V3 worker")
    source = result.get("source_binding")
    if not isinstance(source, dict):
        raise VerificationError(f"{case_id}: source_binding missing")
    report_manifest = source.get("manifest")
    if not isinstance(report_manifest, dict) or report_manifest.get("path") != current.get("path") or report_manifest.get("sha256") != current.get("sha256") or report_manifest.get("manifest_path") != current.get("manifest_path"):
        raise VerificationError(f"{case_id}: manifest binding is incomplete")
    trajectory = source.get("trajectory_h5")
    manifest_h5 = case.get("trajectory_h5")
    if not isinstance(trajectory, dict) or not isinstance(manifest_h5, dict):
        raise VerificationError(f"{case_id}: HDF5 source contract missing")
    h5_path = path_ref(manifest_h5.get("path"), f"{case_id} manifest HDF5")
    if path_ref(trajectory.get("path"), f"{case_id} report HDF5") != h5_path:
        raise VerificationError(f"{case_id}: HDF5 path differs from manifest")
    known = digest(manifest_h5.get("known_sha256"), f"{case_id} manifest HDF5 SHA")
    for key in ("known_sha256", "pre_sha256", "post_sha256"):
        if digest(trajectory.get(key), f"{case_id} report HDF5 {key}") != known:
            raise VerificationError(f"{case_id}: HDF5 {key} differs from manifest")
    expected_stat = {"path": str(h5_path), **{key: manifest_h5.get(key) for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}}
    pre_stat = trajectory.get("pre_stat")
    post_stat = trajectory.get("post_stat")
    if not isinstance(pre_stat, dict) or not isinstance(post_stat, dict):
        raise VerificationError(f"{case_id}: HDF5 pre/post stat missing")
    compare_stat(expected_stat, pre_stat, f"{case_id} HDF5 pre-stat versus manifest")
    compare_stat(pre_stat, post_stat, f"{case_id} HDF5 pre/post stat")
    compare_stat(pre_stat, current_stat(h5_path, f"{case_id} HDF5"), f"{case_id} HDF5 current stat")
    if trajectory.get("deferred_manifest_stat_match") is not True or source.get("hash_passes_minimum") != 3:
        raise VerificationError(f"{case_id}: deferred HDF5 guard evidence is incomplete")
    if trajectory.get("post_capture_after_all_dataset_and_attribute_reads") is not True:
        raise VerificationError(f"{case_id}: final HDF5 guard does not bracket all reads")

    producer_refs = source.get("producer_refs")
    if not isinstance(producer_refs, list) or len(producer_refs) != 4:
        raise VerificationError(f"{case_id}: producer refs are incomplete")
    expected_fields = ("producer_terminal_proof", "case_manifest", "producer_receipt", "typed_summary")
    seen = set()
    for item in producer_refs:
        if not isinstance(item, dict) or item.get("role") not in expected_fields or item["role"] in seen:
            raise VerificationError(f"{case_id}: producer ref identity is invalid")
        seen.add(item["role"])
        manifest_ref = case.get(item["role"])
        if not isinstance(manifest_ref, dict):
            raise VerificationError(f"{case_id}: manifest producer ref missing")
        path = path_ref(item.get("path"), f"{case_id} {item['role']}")
        expected_path = path_ref(manifest_ref.get("path"), f"{case_id} manifest {item['role']}")
        if path != expected_path or digest(item.get("sha256"), f"{case_id} {item['role']} SHA") != digest(manifest_ref.get("sha256"), f"{case_id} manifest {item['role']} SHA"):
            raise VerificationError(f"{case_id}: report producer ref differs from manifest")
        static_ref = static.get(str(path))
        if static_ref is None or static_ref["sha256"] != item["sha256"] or sha256_file(path) != item["sha256"]:
            raise VerificationError(f"{case_id}: producer ref is not current static evidence")

    dimensions = result.get("dimensions")
    if not isinstance(dimensions, dict):
        raise VerificationError(f"{case_id}: dimensions missing")
    for key in ("frames_expected", "frames_scanned", "particles_expected", "particles_scanned"):
        if not isinstance(dimensions.get(key), int) or dimensions[key] <= 0:
            raise VerificationError(f"{case_id}: invalid dimensions.{key}")
    if dimensions["frames_expected"] != dimensions["frames_scanned"] or dimensions["particles_expected"] != dimensions["particles_scanned"]:
        raise VerificationError(f"{case_id}: scan dimensions are incomplete")
    if dimensions["frames_expected"] != int(case.get("expected_frames", -1)) or dimensions["particles_expected"] != int(case.get("expected_particles", -1)):
        raise VerificationError(f"{case_id}: dimensions differ from manifest")

    identity = result.get("identity")
    if not isinstance(identity, dict) or identity.get("key") != "(Zone,Idp)" or identity.get("status") not in {"VALID", "NOT_EXPOSED", "DUPLICATE_ZONE_IDP", "PRESENT_INVALID_TYPE"}:
        raise VerificationError(f"{case_id}: identity status is invalid")
    if not all(isinstance(identity.get(key), bool) for key in ("unique", "integer_zone", "integer_idp")):
        raise VerificationError(f"{case_id}: identity booleans are missing")
    if identity["status"] == "VALID" and identity != {"key": "(Zone,Idp)", "status": "VALID", "unique": True, "integer_zone": True, "integer_idp": True, "initial_axis_exposed": {"particle_id": "PRESENT", "particle_zone": "PRESENT"}}:
        raise VerificationError(f"{case_id}: valid identity has inconsistent fields")

    initial_type = result.get("initial_type")
    if not isinstance(initial_type, dict) or initial_type.get("status") not in {"PRESENT_VALID_CODES", "PRESENT_UNKNOWN_CODES", "PRESENT_INVALID_TYPE", "PRESENT_SHAPE_MISMATCH", "NOT_EXPOSED"}:
        raise VerificationError(f"{case_id}: initial type status is invalid")
    role_counts = initial_type.get("role_counts")
    if not isinstance(role_counts, dict) or set(role_counts) != {"fixed", "moving", "floating", "fluid", "unknown_initial_type"} or sum(role_counts.values()) != dimensions["particles_expected"]:
        raise VerificationError(f"{case_id}: initial role counts do not reconcile")
    invalid_codes = initial_type.get("invalid_code_count")
    if initial_type["status"] == "PRESENT_VALID_CODES" and invalid_codes != 0:
        raise VerificationError(f"{case_id}: valid initial type has invalid codes")
    if initial_type["status"] in {"NOT_EXPOSED", "PRESENT_INVALID_TYPE", "PRESENT_SHAPE_MISMATCH"} and invalid_codes is not None:
        raise VerificationError(f"{case_id}: unavailable initial type has a fabricated invalid-code count")

    initial_mass = result.get("initial_mass")
    if not isinstance(initial_mass, dict) or initial_mass.get("status") not in {"PRESENT_FINITE_POSITIVE", "PRESENT_INVALID_VALUES", "PRESENT_INVALID_TYPE", "PRESENT_SHAPE_MISMATCH", "NOT_EXPOSED"}:
        raise VerificationError(f"{case_id}: initial mass status is invalid")
    if initial_mass["status"] == "PRESENT_FINITE_POSITIVE":
        if initial_mass.get("finite_positive") is not True or initial_mass.get("invalid_value_count") != 0 or not isinstance(initial_mass.get("total_kg"), (int, float)):
            raise VerificationError(f"{case_id}: finite initial mass ledger is inconsistent")
    elif initial_mass.get("finite_positive") is not False or initial_mass.get("total_kg") is not None:
        raise VerificationError(f"{case_id}: unavailable/invalid initial mass was overstated")
    if initial_mass.get("native_massfluid_binding") != "UNKNOWN_NOT_ATTEMPTED":
        raise VerificationError(f"{case_id}: native MassFluid binding was overstated")

    scan = result.get("field_scan")
    if not isinstance(scan, dict) or scan.get("frames_full_scan") is not True or scan.get("inactive_nonfinite_separate") is not True:
        raise VerificationError(f"{case_id}: full-frame scan evidence is incomplete")
    field_status = scan.get("field_status")
    observations = scan.get("observations")
    if not isinstance(field_status, dict) or set(field_status) != set(FINITE_FIELDS) | {"valid", "type"} or not isinstance(observations, dict):
        raise VerificationError(f"{case_id}: field status ledger is incomplete")
    for field in FINITE_FIELDS:
        status = field_status[field]
        value = observations.get(field)
        if status == "PRESENT":
            if not isinstance(value, dict) or value.get("observations") != dimensions["frames_expected"] * dimensions["particles_expected"]:
                raise VerificationError(f"{case_id}: {field} was not fully streamed")
        elif status not in {"NOT_EXPOSED", "PRESENT_SHAPE_MISMATCH", "PRESENT_INVALID_TYPE"}:
            raise VerificationError(f"{case_id}: invalid {field} status")
    if field_status["valid"] not in {"PRESENT", "NOT_EXPOSED", "PRESENT_SHAPE_MISMATCH", "PRESENT_INVALID_TYPE"} or field_status["type"] not in {"PRESENT", "NOT_EXPOSED", "PRESENT_SHAPE_MISMATCH", "PRESENT_INVALID_TYPE"}:
        raise VerificationError(f"{case_id}: invalid mask/type status")
    roles = scan.get("roles")
    if not isinstance(roles, dict) or set(roles) != {"fixed", "moving", "floating", "fluid", "unknown_initial_type"}:
        raise VerificationError(f"{case_id}: role ledger is incomplete")
    for role, ledger in roles.items():
        if not isinstance(ledger, dict) or not isinstance(ledger.get("initial_particle_count"), int) or ledger["initial_particle_count"] < 0:
            raise VerificationError(f"{case_id}: role {role} initial count is invalid")
        for bucket in ("active_nonfinite", "inactive_nonfinite"):
            values = ledger.get(bucket)
            if not isinstance(values, dict) or set(values) != set(FINITE_FIELDS) or any(not isinstance(value, int) or value < 0 for value in values.values()):
                raise VerificationError(f"{case_id}: role {role} {bucket} is invalid")
    if sum(ledger["initial_particle_count"] for ledger in roles.values()) != dimensions["particles_expected"]:
        raise VerificationError(f"{case_id}: role initial counts do not reconcile")
    role_reconciliation = scan.get("role_reconciliation")
    if not isinstance(role_reconciliation, dict):
        raise VerificationError(f"{case_id}: role reconciliation is missing")
    if role_reconciliation.get("initial_expected_particles") != dimensions["particles_expected"] or role_reconciliation.get("initial_role_count_total") != dimensions["particles_expected"] or role_reconciliation.get("initial_role_counts_reconciled") is not True:
        raise VerificationError(f"{case_id}: initial role reconciliation is inconsistent")
    mask_exposed = field_status["valid"] == "PRESENT"
    total_active = scan.get("active_nonfinite_total")
    total_inactive = scan.get("inactive_nonfinite_total")
    if mask_exposed:
        if not isinstance(total_active, int) or not isinstance(total_inactive, int):
            raise VerificationError(f"{case_id}: exposed mask lacks active/inactive totals")
        if total_active != sum(sum(ledger["active_nonfinite"].values()) for ledger in roles.values()) or total_inactive != sum(sum(ledger["inactive_nonfinite"].values()) for ledger in roles.values()):
            raise VerificationError(f"{case_id}: active/inactive nonfinite totals do not reconcile")
    elif total_active is not None or total_inactive is not None:
        raise VerificationError(f"{case_id}: missing mask has fabricated active/inactive totals")
    if mask_exposed:
        if role_reconciliation.get("frame_expected_observations") != dimensions["frames_expected"] * dimensions["particles_expected"] or role_reconciliation.get("frame_active_count_total") != sum(ledger["observed_active_count"] for ledger in roles.values()) or role_reconciliation.get("frame_inactive_count_total") != sum(ledger["observed_inactive_count"] for ledger in roles.values()) or role_reconciliation.get("frame_role_counts_reconciled") is not True:
            raise VerificationError(f"{case_id}: frame role reconciliation is inconsistent")
    elif any(role_reconciliation.get(key) is not None for key in ("frame_active_count_total", "frame_inactive_count_total", "frame_invalid_mask_count", "frame_role_counts_reconciled")):
        raise VerificationError(f"{case_id}: unavailable mask has fabricated frame reconciliation")
    status = scan.get("active_finite_status")
    if status == "ALL_ACTIVE_REQUIRED_FIELDS_FINITE" and (set(field_status.values()) != {"PRESENT"} or initial_type.get("status") != "PRESENT_VALID_CODES" or not mask_exposed or scan.get("frame_type_unknown_total") != 0 or scan.get("active_type_unknown_total") != 0 or total_active != 0 or scan.get("invalid_mask_total") != 0):
        raise VerificationError(f"{case_id}: ALL_ACTIVE status hides an unknown field/type/mask")
    if status not in {"ALL_ACTIVE_REQUIRED_FIELDS_FINITE", "INITIAL_TYPE_UNKNOWN", "REQUIRED_FIELD_NOT_EXPOSED", "ACTIVE_MASK_NOT_EXPOSED", "ACTIVE_TYPE_OR_ROLE_UNKNOWN", "ACTIVE_NONFINITE_OBSERVATIONS", "MASK_UNKNOWN_OBSERVATIONS"}:
        raise VerificationError(f"{case_id}: active finite status is invalid")
    if scan.get("vectorized_chunk_reductions") is not True:
        raise VerificationError(f"{case_id}: V3 vectorized reduction marker is missing")
    ranges = result.get("physical_ranges")
    if not isinstance(ranges, dict) or ranges.get("status") != "DIAGNOSTIC_ONLY_NO_GATE":
        raise VerificationError(f"{case_id}: physical ranges are not diagnostic-only")
    units = result.get("units")
    material = result.get("material_and_mk")
    if not isinstance(units, dict) or units.get("authority") != "UNKNOWN_UNVERIFIED" or not isinstance(material, dict) or material.get("semantic_authority") != "UNKNOWN" or material.get("material_labels_used_for_science") is not False:
        raise VerificationError(f"{case_id}: source authority was overstated")
    if result.get("scientific_qualification") != UNKNOWN_QUALIFICATION:
        raise VerificationError(f"{case_id}: scientific qualification is not UNKNOWN")
    boundary = result.get("claim_boundary")
    if not isinstance(boundary, dict) or any(boundary.get(key) != "UNKNOWN" for key in ("continuous_event_time", "native_exit_cause", "physical_fate", "legal_flux", "dynamical_impact")):
        raise VerificationError(f"{case_id}: physical boundary was overstated")
    return {"physical_case_id": case_id, "family_id": case.get("family_id"), "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT", "active_finite_status": status, "initial_mass_status": initial_mass["status"], "missing_fields": [field for field, state in field_status.items() if state != "PRESENT"], "unit_comparison": units.get("comparison"), "physical_ranges_diagnostic": True}


def verify(manifest_path_value: Path, report_path_value: Path, output_path_value: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path_value, "manifest")
    report_path, report = read_json(report_path_value, "report")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT":
        raise VerificationError("manifest schema/status is not guarded-ready V2-compatible")
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT":
        raise VerificationError("report schema/status is not a complete V3 no-credit scan")
    static, current = load_static_refs(manifest)
    report_manifest = report.get("manifest")
    if not isinstance(report_manifest, dict) or path_ref(report_manifest.get("path"), "report manifest") != manifest_path:
        raise VerificationError("report does not identify the supplied manifest")
    if digest(report_manifest.get("sha256"), "report manifest SHA") != sha256_file(manifest_path):
        raise VerificationError("report manifest SHA does not match supplied manifest")
    report_binding = report_manifest.get("current_binding")
    if not isinstance(report_binding, dict) or report_binding.get("path") != current["path"] or report_binding.get("sha256") != current["sha256"] or report_binding.get("manifest_path") != str(manifest_path) or report_binding.get("static_ref_count") != len(static):
        raise VerificationError("report current/static binding differs from manifest")
    cases = manifest.get("cases")
    results = report.get("case_results")
    counts = report.get("counts")
    if not isinstance(cases, list) or not isinstance(results, list) or not isinstance(counts, dict):
        raise VerificationError("manifest/report case collections are missing")
    case_ids = [case.get("physical_case_id") for case in cases if isinstance(case, dict)]
    result_ids = [result.get("physical_case_id") for result in results if isinstance(result, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids) or case_ids != result_ids:
        raise VerificationError("manifest/report case identity sequence differs")
    if counts != {"requested": len(cases), "completed": len(cases), "failed": 0} or report.get("failed_cases") != []:
        raise VerificationError("report counts do not reconcile")
    read_policy = report.get("read_policy")
    if not isinstance(read_policy, dict) or read_policy.get("trajectory_h5_opened_after_reservation") is not True or read_policy.get("raw_bi4_opened") is not False or read_policy.get("solver_started") is not False or read_policy.get("legacy_model_fields_used") is not False:
        raise VerificationError("report read policy is unsafe or incomplete")
    if report.get("scientific_qualification") != UNKNOWN_QUALIFICATION:
        raise VerificationError("top-level scientific qualification is not UNKNOWN")
    verified = [verify_case(case, result, static, {**current, "manifest_path": str(manifest_path)}) for case, result in zip(cases, results)]
    output = {
        "schema": "ds02.stage2.verify-scientific-field-h5-audit.v3",
        "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT",
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "report": {"path": str(report_path), "sha256": sha256_file(report_path)},
        "case_count": len(verified), "cases": verified,
        "source_content_read_by_verifier": False, "production_eligible": False, "scientific_credit": 0,
        "scientific_qualification": UNKNOWN_QUALIFICATION,
        "claim_boundary": {"active_field_integrity": "bounded raw-HDF5 scan only", "physical_ranges": "diagnostic only; no gate", "units": "producer declaration versus protocol; authority UNKNOWN", "material_and_mk": "presence only; authority UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    output_path = output_path_value.expanduser().resolve()
    if output_path.exists():
        raise VerificationError(f"refusing to overwrite verifier output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise VerificationError("verifier output exceeds bounded size")
    output_path.write_text(encoded, encoding="utf-8")
    return {"status": output["status"], "output": str(output_path), "case_count": len(verified), "production_eligible": False, "scientific_credit": 0}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--report", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = verify(args.manifest, args.report, args.output)
    except (VerificationError, OSError) as exc:
        print(f"verify-scientific-field-h5-audit-v3: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
