#!/usr/bin/env python3
"""Independent metadata verifier for the guarded raw-HDF5 field audit.

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
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-audit-manifest.v1"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-audit.v1"
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


def count_nested_nonfinite(roles: dict[str, Any], bucket: str) -> int:
    total = 0
    for role, value in roles.items():
        if not isinstance(value, dict):
            raise VerificationError(f"role {role} is not an object")
        counts = value.get(bucket)
        if not isinstance(counts, dict) or set(counts) != set(FINITE_FIELDS):
            raise VerificationError(f"role {role} has incomplete {bucket}")
        for field in FINITE_FIELDS:
            if not isinstance(counts[field], int) or isinstance(counts[field], bool) or counts[field] < 0:
                raise VerificationError(f"role {role} has invalid {bucket}.{field}")
            total += counts[field]
    return total


def verify_case(case: dict[str, Any], result: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    case_id = case.get("physical_case_id")
    if not isinstance(case_id, str) or not case_id:
        raise VerificationError("manifest case has no physical_case_id")
    if result.get("physical_case_id") != case_id:
        raise VerificationError(f"case result identity mismatch for {case_id}")
    if result.get("status") != "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT":
        raise VerificationError(f"{case_id}: unexpected completed status")
    source = result.get("source")
    manifest_h5 = case.get("trajectory_h5")
    if not isinstance(source, dict) or not isinstance(manifest_h5, dict):
        raise VerificationError(f"{case_id}: missing source contract")
    source_h5 = source.get("trajectory_h5")
    if not isinstance(source_h5, dict):
        raise VerificationError(f"{case_id}: missing source trajectory")
    h5_path = path_ref(manifest_h5.get("path"), f"{case_id} manifest HDF5")
    if path_ref(source_h5.get("path"), f"{case_id} report HDF5") != h5_path:
        raise VerificationError(f"{case_id}: HDF5 path differs from manifest")
    h5_sha = digest(manifest_h5.get("known_sha256"), f"{case_id} manifest HDF5 SHA")
    for key in ("known_sha256", "pre_sha256", "post_sha256"):
        if digest(source_h5.get(key), f"{case_id} report HDF5 {key}") != h5_sha:
            raise VerificationError(f"{case_id}: report HDF5 {key} differs from manifest")
    pre_stat = source_h5.get("pre_stat")
    post_stat = source_h5.get("post_stat")
    if not isinstance(pre_stat, dict) or not isinstance(post_stat, dict):
        raise VerificationError(f"{case_id}: HDF5 pre/post stat missing")
    if stat_key(pre_stat, f"{case_id} pre-stat") != stat_key(post_stat, f"{case_id} post-stat"):
        raise VerificationError(f"{case_id}: HDF5 changed between worker pre/post snapshots")
    if stat_key(pre_stat, f"{case_id} pre-stat")[0] != str(h5_path):
        raise VerificationError(f"{case_id}: HDF5 stat path mismatch")
    # This is a stat-only check.  Content SHA is deliberately not recomputed here.
    if stat_key(current_stat(h5_path, f"{case_id} HDF5"), f"{case_id} current HDF5") != stat_key(pre_stat, f"{case_id} pre-stat"):
        raise VerificationError(f"{case_id}: current HDF5 stat differs from worker snapshots")

    dimensions = result.get("dimensions")
    if not isinstance(dimensions, dict):
        raise VerificationError(f"{case_id}: dimensions missing")
    for name in ("frames_expected", "frames_scanned", "particles_expected", "particles_scanned"):
        if not isinstance(dimensions.get(name), int) or dimensions[name] <= 0:
            raise VerificationError(f"{case_id}: invalid dimensions.{name}")
    if dimensions["frames_expected"] != dimensions["frames_scanned"] or dimensions["particles_expected"] != dimensions["particles_scanned"]:
        raise VerificationError(f"{case_id}: scan did not cover expected dimensions")
    if dimensions["frames_expected"] != int(case.get("expected_frames", -1)) or dimensions["particles_expected"] != int(case.get("expected_particles", -1)):
        raise VerificationError(f"{case_id}: dimensions differ from deferred contract")

    identity = result.get("identity")
    if identity != {"key": "(Zone,Idp)", "unique": True, "integer_zone": True, "integer_idp": True}:
        raise VerificationError(f"{case_id}: identity contract is incomplete")
    scan = result.get("field_scan")
    if not isinstance(scan, dict) or scan.get("required_datasets_present") is not True or scan.get("frames_full_scan") is not True or scan.get("inactive_nonfinite_separate") is not True:
        raise VerificationError(f"{case_id}: full active/inactive field scan is not proven")
    if set(scan.get("roles", {})) != {"fixed", "moving", "floating", "fluid"}:
        raise VerificationError(f"{case_id}: role ledger is incomplete")
    for name in ("active_nonfinite_total", "inactive_nonfinite_total", "invalid_mask_total", "active_type_unknown_total"):
        value = scan.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise VerificationError(f"{case_id}: invalid field_scan.{name}")
    if scan["active_nonfinite_total"] != count_nested_nonfinite(scan["roles"], "active_nonfinite"):
        raise VerificationError(f"{case_id}: active non-finite total does not reconcile")
    if scan["inactive_nonfinite_total"] != count_nested_nonfinite(scan["roles"], "inactive_nonfinite"):
        raise VerificationError(f"{case_id}: inactive non-finite total does not reconcile")
    expected_status = "ALL_ACTIVE_REQUIRED_FIELDS_FINITE" if scan["active_nonfinite_total"] == 0 and scan["active_type_unknown_total"] == 0 and scan["invalid_mask_total"] == 0 else "ACTIVE_FIELD_OR_MASK_UNKNOWN_OBSERVATIONS_PRESENT"
    if scan.get("active_finite_status") != expected_status:
        raise VerificationError(f"{case_id}: active finite status is inconsistent")

    units = result.get("units")
    if not isinstance(units, dict) or units.get("authority") != "UNKNOWN_UNVERIFIED":
        raise VerificationError(f"{case_id}: units authority was overstated")
    material = result.get("material_and_mk")
    if not isinstance(material, dict) or material.get("semantic_authority") != "UNKNOWN" or material.get("material_labels_used_for_science") is not False:
        raise VerificationError(f"{case_id}: material/MK authority was overstated")
    if result.get("scientific_qualification") != UNKNOWN_QUALIFICATION:
        raise VerificationError(f"{case_id}: scientific qualification is not UNKNOWN")
    boundary = result.get("claim_boundary")
    if not isinstance(boundary, dict) or any(boundary.get(key) != "UNKNOWN" for key in ("continuous_event_time", "native_exit_cause", "physical_fate", "legal_flux", "dynamical_impact")):
        raise VerificationError(f"{case_id}: claim boundary was overstated")
    if source.get("hash_passes_minimum") != 3:
        raise VerificationError(f"{case_id}: minimum three-pass source hash evidence is missing")
    return {"physical_case_id": case_id, "family_id": case.get("family_id"), "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT", "active_nonfinite_total": scan["active_nonfinite_total"], "inactive_nonfinite_total": scan["inactive_nonfinite_total"], "unit_comparison": units.get("comparison"), "material_dataset_presence": material.get("dataset_presence")}


def verify(manifest_path_value: Path, report_path_value: Path, output_path_value: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path_value, "manifest")
    report_path, report = read_json(report_path_value, "report")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT":
        raise VerificationError("manifest schema/status is not guarded-ready")
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT":
        raise VerificationError("report schema/status is not a complete no-credit scan")
    report_manifest = report.get("manifest")
    if not isinstance(report_manifest, dict) or path_ref(report_manifest.get("path"), "report manifest") != manifest_path:
        raise VerificationError("report does not identify the supplied manifest")
    if digest(report_manifest.get("sha256"), "report manifest SHA") != sha256_file(manifest_path):
        raise VerificationError("report manifest SHA does not match supplied manifest")
    if manifest.get("current_catalog", {}).get("sha256") != CURRENT_SHA256:
        raise VerificationError("manifest is not bound to the frozen CURRENT catalog")
    cases = manifest.get("cases")
    results = report.get("case_results")
    counts = report.get("counts")
    if not isinstance(cases, list) or not isinstance(results, list) or not isinstance(counts, dict):
        raise VerificationError("manifest/report case collections are missing")
    case_ids = [case.get("physical_case_id") for case in cases if isinstance(case, dict)]
    result_ids = [result.get("physical_case_id") for result in results if isinstance(result, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids) or case_ids != result_ids:
        raise VerificationError("manifest/report case identity sequence differs")
    if counts != {"requested": len(cases), "completed": len(cases), "failed": 0}:
        raise VerificationError("report counts do not reconcile")
    if report.get("failed_cases") != []:
        raise VerificationError("complete report contains failed cases")
    read_policy = report.get("read_policy")
    if not isinstance(read_policy, dict) or read_policy.get("trajectory_h5_opened_after_reservation") is not True or read_policy.get("raw_bi4_opened") is not False or read_policy.get("solver_started") is not False or read_policy.get("legacy_model_fields_used") is not False:
        raise VerificationError("report read policy is unsafe or incomplete")
    if report.get("scientific_qualification") != UNKNOWN_QUALIFICATION:
        raise VerificationError("top-level scientific qualification is not UNKNOWN")
    verified = [verify_case(case, result, manifest_path) for case, result in zip(cases, results)]
    output = {
        "schema": "ds02.stage2.verify-scientific-field-h5-audit.v1",
        "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT",
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "report": {"path": str(report_path), "sha256": sha256_file(report_path)},
        "case_count": len(verified),
        "cases": verified,
        "source_content_read_by_verifier": False,
        "scientific_credit": 0,
        "production_eligible": False,
        "scientific_qualification": UNKNOWN_QUALIFICATION,
        "claim_boundary": {"active_field_integrity": "bounded raw-HDF5 scan only", "units": "producer declaration versus protocol; authority UNKNOWN", "material_and_mk": "presence only; authority UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
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
        print(f"verify-scientific-field-h5-audit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
