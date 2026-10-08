#!/usr/bin/env python3
"""Materialize the existing 336 scientific-scan JSON records as detail cards.

This is a JSON-only consumer of already completed scan products.  It joins the
immutable CURRENT336 identity, the v29 catalog/proof, each scientific-scan
JSON, and its execution receipt.  It never opens a trajectory HDF5, BI4
particle file, raw solver directory, or starts a solver.  The detailed card
keeps the scan's actual units, identity, saved times, type ledgers, missing-ID
records, macros, lifecycle flags, and failure list; an empty failure list is
reported as an empty observed list and is never upgraded to a finite/error
claim.
This V2 forward consumer keeps the immutable V1 request untouched.  Its
``current_index`` is the authoritative list position in CURRENT336 when the
CURRENT case object has no embedded index.  The producer manifest's index is
checked against that position and both values are retained in each card.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.scientific-scan-detail.v2"
MANIFEST_SCHEMA = "ds02.stage2.scientific-scan-detail-manifest.v2"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
CATALOG_SCHEMA = "ds02.stage2.final-qualification-catalog.v29"
AUDIT_PROOF_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
SCAN_SCHEMA = "ds02.stage2.scientific-scan.v1"


class DetailContractError(RuntimeError):
    """Raised when a detail input is missing, mismatched, or not completed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise DetailContractError(f"missing JSON input: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DetailContractError(f"invalid JSON input: {path}: {exc}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise DetailContractError(f"expected JSON object: {path}")
    return value


def _declared_file(value: Any, name: str) -> tuple[Path, str]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
        raise DetailContractError(f"{name} must contain path and sha256")
    digest = str(value["sha256"])
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise DetailContractError(f"{name} has an invalid SHA-256 digest")
    return Path(str(value["path"])), digest


def _verify_json(path: Path, expected: str, *, require_file: bool) -> dict[str, Any] | None:
    if not require_file:
        return None
    if not path.is_file():
        raise DetailContractError(f"declared JSON input is not a file: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise DetailContractError(f"JSON input SHA mismatch: {path}: expected {expected}, got {actual}")
    return _load_object(path)


def _case_key(case: Mapping[str, Any]) -> str:
    return f"{case.get('family_id')}/{case.get('physical_case_id')}"


def _manifest_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise DetailContractError(f"unexpected detail manifest schema: {manifest.get('schema')!r}")
    if manifest.get("case_count") != 336:
        raise DetailContractError("detail manifest must cover exactly 336 cases")
    if manifest.get("trajectory_read_policy") != "json_only_no_h5_bi4_raw_solver":
        raise DetailContractError("detail manifest trajectory policy is not JSON-only")
    entries = manifest.get("cases")
    if not isinstance(entries, list) or len(entries) != 336:
        raise DetailContractError("detail manifest cases must contain exactly 336 entries")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise DetailContractError(f"manifest case {index} is not an object")
        key = entry.get("case_key")
        if not isinstance(key, str) or key in seen or "/" not in key:
            raise DetailContractError(f"manifest case key is invalid or duplicated: {key!r}")
        seen.add(key)
        for name in ("scan", "receipt", "trajectory"):
            _declared_file(entry.get(name), f"case {key} {name}")
        if entry.get("family_id") != key.split("/", 1)[0] or entry.get("physical_case_id") != key.split("/", 1)[1]:
            raise DetailContractError(f"manifest case identity mismatch: {key}")
        if "current_index" in entry:
            if not isinstance(entry["current_index"], int) or entry["current_index"] < 0:
                raise DetailContractError(f"manifest current_index is invalid: {key}")
            if entry["current_index"] != index:
                raise DetailContractError(f"manifest current_index is not its authoritative list position: {key}")
        result.append(entry)
    if len(seen) != 336:
        raise DetailContractError("detail manifest does not have 336 unique case keys")
    return result


def _authoritative_current_order(current: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Build exact identity and list-position maps from CURRENT336 order."""

    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise DetailContractError("CURRENT336 source is not the expected 336-case list")
    by_key: dict[str, dict[str, Any]] = {}
    positions: dict[str, int] = {}
    for list_index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise DetailContractError(f"CURRENT case {list_index} is not an object")
        key = _case_key(case)
        if key in by_key:
            raise DetailContractError(f"CURRENT contains duplicate case identity: {key}")
        by_key[key] = dict(case)
        positions[key] = list_index
    return by_key, positions


def validate_manifest_dict(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate JSON-only structure without opening any declared source file."""

    return _manifest_entries(manifest)


def _validate_scan_and_receipt(
    *,
    entry: Mapping[str, Any],
    current: Mapping[str, Any],
    scan: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    key = str(entry["case_key"])
    family_id = str(entry["family_id"])
    physical_case_id = str(entry["physical_case_id"])
    if scan.get("schema") != SCAN_SCHEMA:
        raise DetailContractError(f"{key}: unexpected scan schema")
    if scan.get("family_id") != family_id or scan.get("physical_case_id") != physical_case_id:
        raise DetailContractError(f"{key}: scan identity mismatch")
    trajectory_path, trajectory_sha = _declared_file(entry["trajectory"], f"{key} trajectory")
    if scan.get("trajectory") != str(trajectory_path):
        raise DetailContractError(f"{key}: scan trajectory path is not the bound CURRENT trajectory")
    scan_frames = scan.get("frames")
    scan_particles = scan.get("particles")
    if scan_frames != current.get("frames") or scan_particles != current.get("particles"):
        raise DetailContractError(f"{key}: scan frame/particle count differs from CURRENT")
    times = scan.get("time_s")
    if not isinstance(times, list) or len(times) != int(scan_frames):
        raise DetailContractError(f"{key}: saved time array is missing or has the wrong length")
    window = current.get("actual_time_window_s")
    if not isinstance(window, list) or len(window) != 2 or not times or float(times[0]) != float(window[0]) or float(times[-1]) != float(window[1]):
        raise DetailContractError(f"{key}: scan saved time endpoints do not match CURRENT window")
    if scan.get("full_saved_timeline_scanned") is not True:
        raise DetailContractError(f"{key}: scan does not declare a full saved timeline")
    if scan.get("scan_status") != "SCANNED":
        raise DetailContractError(f"{key}: scan status is not SCANNED")
    if scan.get("metadata", {}).get("identity_key") != "(Zone,Idp)":
        raise DetailContractError(f"{key}: scan identity key is not (Zone,Idp)")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise DetailContractError(f"{key}: producer scan receipt is not completed successfully")
    if receipt.get("output_root") != str(Path(str(entry["scan"]["path"])).parent):
        raise DetailContractError(f"{key}: receipt output root does not bind the scan path")
    command = receipt.get("command")
    if not isinstance(command, list) or physical_case_id not in command:
        raise DetailContractError(f"{key}: receipt command does not bind the exact physical case")
    for phase in ("input_hashes_at_launch", "input_hashes_after_run"):
        input_hashes = receipt.get(phase)
        if not isinstance(input_hashes, Mapping) or input_hashes.get(str(trajectory_path)) != trajectory_sha:
            raise DetailContractError(f"{key}: receipt {phase} does not bind the trajectory SHA")


def _detail_card(*, entry: Mapping[str, Any], current: Mapping[str, Any], current_list_index: int, scan: Mapping[str, Any], receipt: Mapping[str, Any], scan_sha: str, receipt_sha: str) -> dict[str, Any]:
    """Copy the observed JSON fields without interpreting them as physics."""

    return {
        "schema": "ds02.stage2.scientific-scan-detail-card.v2",
        "case_key": entry["case_key"],
        "family_id": entry["family_id"],
        "physical_case_id": entry["physical_case_id"],
        "current_identity": {
            "current_index": current.get("current_index"),
            "current_list_index": current_list_index,
            "producer_current_index_present": "current_index" in current,
            "runtime_case_alias": current.get("runtime_case_alias"),
            "frames": current.get("frames"),
            "particles": current.get("particles"),
            "actual_time_window_s": current.get("actual_time_window_s"),
            "known_numeric_physical_parameters": current.get("known_numeric_physical_parameters", {}),
            "trajectory_path": entry["trajectory"]["path"],
            "trajectory_declared_sha256": entry["trajectory"]["sha256"],
        },
        "scan_provenance": {"path": entry["scan"]["path"], "declared_sha256": entry["scan"]["sha256"], "observed_sha256": scan_sha},
        "receipt_provenance": {"path": entry["receipt"]["path"], "declared_sha256": entry["receipt"]["sha256"], "observed_sha256": receipt_sha},
        "scientific_scan": {
            "schema": scan.get("schema"),
            "source_bytes": scan.get("source_bytes"),
            "source_mtime_ns": scan.get("source_mtime_ns"),
            "full_saved_timeline_scanned": scan.get("full_saved_timeline_scanned"),
            "frames": scan.get("frames"),
            "particles": scan.get("particles"),
            "time_s": scan.get("time_s"),
            "metadata": scan.get("metadata"),
            "type_ledgers": scan.get("type_ledgers"),
            "missing_id_records": scan.get("missing_id_records"),
            "macros": scan.get("macros"),
            "failures": scan.get("failures"),
            "scan_status": scan.get("scan_status"),
            "raw_native_alignment": scan.get("raw_native_alignment"),
            "QI_dynamics": scan.get("QI_dynamics"),
            "QN": scan.get("QN"),
            "QE": scan.get("QE"),
            "input_hash_verification": scan.get("input_hash_verification"),
            "wall_seconds": scan.get("wall_seconds"),
            "peak_rss_kib": scan.get("peak_rss_kib"),
        },
        "execution_receipt": {
            "schema": receipt.get("schema"),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "request": receipt.get("request"),
            "command": receipt.get("command"),
            "output_root": receipt.get("output_root"),
            "started_at_utc": receipt.get("started_at_utc"),
            "finished_at_utc": receipt.get("finished_at_utc"),
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "cpu_core_seconds": receipt.get("cpu_core_seconds"),
            "gpu_seconds": receipt.get("gpu_seconds"),
            "bytes": receipt.get("bytes"),
            "input_hashes_at_launch": receipt.get("input_hashes_at_launch"),
            "input_hashes_after_run": receipt.get("input_hashes_after_run"),
        },
        "claim_boundary": {
            "units_identity_time_lifecycle": "observed JSON fields",
            "finite_field_failure_list": "observed only; empty does not prove finite validity",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN_QE_QI": "NOT_ASSESSED",
            "trajectory_h5_opened_by_collector": False,
            "bi4_raw_solver_opened_by_collector": False,
        },
    }


def run(*, manifest_path: Path, current_path: Path, catalog_path: Path, audit_proof_path: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        runner_owned = {"stdout.log", "execution-receipt.json"}
        leftovers = [path for path in output_dir.iterdir() if path.name not in runner_owned]
        if leftovers:
            raise DetailContractError(f"refusing to overwrite output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_object(manifest_path)
    entries = _manifest_entries(manifest)
    current = _load_object(current_path)
    catalog = _load_object(catalog_path)
    audit_proof = _load_object(audit_proof_path)
    if current.get("schema") != CURRENT_SCHEMA or len(current.get("cases", [])) != 336:
        raise DetailContractError("CURRENT336 source is not the expected 336-case schema")
    if catalog.get("schema") != CATALOG_SCHEMA or len(catalog.get("cases", [])) != 336:
        raise DetailContractError("v29 catalog source is not the expected 336-case schema")
    if audit_proof.get("schema") != AUDIT_PROOF_SCHEMA or audit_proof.get("distinct_completed_cases") != 336:
        raise DetailContractError("scientific audit proof does not cover 336 completed cases")
    current_by_key, current_positions = _authoritative_current_order(current)
    catalog_by_key = {case["case_key"]: case for case in catalog["cases"]}
    if set(current_by_key) != set(catalog_by_key) or len(current_by_key) != 336:
        raise DetailContractError("CURRENT and v29 catalog case identities differ")
    started = time.monotonic()
    detail_dir = output_dir / "details"
    detail_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for entry in entries:
        key = str(entry["case_key"])
        current_case = current_by_key.get(key)
        catalog_case = catalog_by_key.get(key)
        if current_case is None or catalog_case is None:
            raise DetailContractError(f"manifest case is absent from CURRENT or v29 catalog: {key}")
        current_list_index = current_positions[key]
        declared_manifest_index = entry.get("current_index")
        if declared_manifest_index is not None and int(declared_manifest_index) != current_list_index:
            raise DetailContractError(f"{key}: manifest current_index does not match CURRENT list position")
        scan_path, scan_expected = _declared_file(entry["scan"], f"{key} scan")
        receipt_path, receipt_expected = _declared_file(entry["receipt"], f"{key} receipt")
        scan = _verify_json(scan_path, scan_expected, require_file=True)
        receipt = _verify_json(receipt_path, receipt_expected, require_file=True)
        assert scan is not None and receipt is not None
        catalog_scan = catalog_case["scientific_audit"]["scan_provenance"]
        catalog_receipt = catalog_case["scientific_audit"]["receipt_provenance"]
        if catalog_scan.get("path") != str(scan_path) or catalog_scan.get("declared_sha256") != scan_expected:
            raise DetailContractError(f"{key}: manifest scan does not match v29 catalog")
        if catalog_receipt.get("path") != str(receipt_path) or catalog_receipt.get("declared_sha256") != receipt_expected:
            raise DetailContractError(f"{key}: manifest receipt does not match v29 catalog")
        _validate_scan_and_receipt(entry=entry, current=current_case, scan=scan, receipt=receipt)
        card_current = dict(current_case)
        card_current["current_index"] = current_list_index
        card = _detail_card(entry=entry, current=card_current, current_list_index=current_list_index, scan=scan, receipt=receipt, scan_sha=scan_expected, receipt_sha=receipt_expected)
        card_path = detail_dir / f"{current_list_index:03d}-{current_case['family_id']}-{current_case['physical_case_id']}.json"
        if card_path.exists():
            raise DetailContractError(f"refusing to overwrite detail card: {card_path}")
        card_path.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        status = str(scan.get("scan_status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        index.append({"case_key": key, "current_index": current_list_index, "current_list_index": current_list_index, "path": str(card_path), "sha256": sha256_file(card_path), "scan_status": status, "field_failure_count": len(scan.get("failures") or []), "missing_record_count": len(scan.get("missing_id_records") or [])})
    index.sort(key=lambda item: int(item["current_index"]))
    report = {
        "schema": SCHEMA,
        "attempt_status": "completed_actual_json_only_detail_collection",
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "current": {"path": str(current_path), "sha256": sha256_file(current_path)},
        "catalog": {"path": str(catalog_path), "sha256": sha256_file(catalog_path)},
        "audit_proof": {"path": str(audit_proof_path), "sha256": sha256_file(audit_proof_path)},
        "case_count": len(index),
        "status_counts": status_counts,
        "detail_cards": index,
        "source_read_policy": {"current_json_opened": True, "catalog_json_opened": True, "audit_proof_json_opened": True, "scientific_scan_json_opened": True, "execution_receipt_json_opened": True, "trajectory_h5_opened": False, "bi4_opened": False, "raw_solver_output_opened": False, "solver_started": False},
        "claim_boundary": {"units_identity_time_lifecycle": "JSON fields copied with source hashes", "empty_failure_list": "observed empty list only; no finite/error credit", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN_QE_QI": "NOT_ASSESSED"},
        "resource": {"wall_seconds": time.monotonic() - started, "source_json_case_count": len(index)},
    }
    report_path = output_dir / "scientific-scan-detail-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["report"] = {"path": str(report_path), "sha256": sha256_file(report_path)}
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", choices=("run",), default="run")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--audit-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    report = run(manifest_path=args.manifest, current_path=args.current, catalog_path=args.catalog, audit_proof_path=args.audit_proof, output_dir=args.output)
    print(json.dumps({"report": report["report"], "cases": report["case_count"], "status": report["attempt_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
