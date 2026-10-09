#!/usr/bin/env python3
"""Build a JSON-only enriched audit from completed scientific scans using the producer's actual identity fields.

The input manifest enumerates the CURRENT336 catalog, v29 audit rows, the
detail-card report, and every detail/scan/receipt JSON path explicitly.  The
worker joins those objects by exact case key, current index, and declared
SHA-256.  It summarizes fields that the producer actually exposed (units,
identity convention, saved-time macros, and typed active-count/mass ledgers)
without opening trajectory HDF5, BI4/OBI4, VTK, or raw solver payloads.

An empty finite-field failure list is reported as an observed empty list.  It
does not become a finite-validity claim.  Per-ID lifecycle is not inferred
from saved-frame counts or missing-ID records.  The product keeps v29's 118
native-omission scope and 290 lifecycle-exposure rows as separate quantities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
V29_SCHEMA = "ds02.stage2.final-qualification-catalog.v29"
DETAIL_REPORT_SCHEMA = "ds02.stage2.scientific-scan-detail.v2"
DETAIL_CARD_SCHEMA = "ds02.stage2.scientific-scan-detail-card.v2"
SCAN_SCHEMA = "ds02.stage2.scientific-scan.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
MANIFEST_SCHEMA = "ds02.stage2.scientific-scan-enriched-audit.manifest.v3"
REQUEST_SCHEMA = "ds02.stage2.scientific-scan-enriched-audit-request.v3"
OUTPUT_SCHEMA = "ds02.stage2.scientific-scan-enriched-audit.v3"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".vtk", ".vtu", ".raw"}
LEDGER_ROLES = ("fixed", "floating", "fluid", "moving")


class AuditError(RuntimeError):
    """Raised when an explicit JSON source join is not closed."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise AuditError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _path(value: Any, label: str, *, allow_payload_declared: bool = False) -> Path:
    if not isinstance(value, (str, Path)):
        raise AuditError(f"{label} must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise AuditError(f"{label} must be absolute")
    if not allow_payload_declared and path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise AuditError(f"{label} points at forbidden scientific payload: {path}")
    if not path.is_file():
        raise AuditError(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be an object: {path}")
    return value


def _ref(path: Path, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {"role": role, "path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "sha256": sha256_file(path), "source_scope": "JSON_ONLY"}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _case_key(row: dict[str, Any]) -> str | None:
    value = row.get("case_key")
    if isinstance(value, str) and "/" in value:
        return value
    family, physical = row.get("family_id"), row.get("physical_case_id")
    if isinstance(family, str) and isinstance(physical, str):
        return f"{family}/{physical}"
    return None


def _producer_case_key(value: dict[str, Any], label: str) -> str:
    """Return the identity emitted by the real scan producer.

    ``scientific-scan.json`` does not emit the catalog's synthetic ``case_key``;
    it emits the two source identity fields ``family_id`` and
    ``physical_case_id``.  Detail cards do carry ``case_key`` but their
    embedded scientific projection deliberately omits it.  V2 treated the
    projection as if it were the producer object and therefore rejected the
    first real F1 scan.  V3 accepts only the producer pair and derives the
    same canonical key, without accepting a caller-supplied alias.
    """
    family = value.get("family_id")
    physical = value.get("physical_case_id")
    if not isinstance(family, str) or not isinstance(physical, str):
        raise AuditError(f"{label} lacks producer family_id/physical_case_id")
    return f"{family}/{physical}"


def _load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]], dict[str, Any]]:
    manifest = _json(path, "enriched-audit manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AuditError(f"unexpected manifest schema: {manifest.get('schema')!r}")
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise AuditError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    for item in refs:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise AuditError("malformed manifest source reference")
        key = item["key"]
        if key in paths:
            raise AuditError(f"duplicate source key: {key}")
        p = _path(item.get("path"), f"source {key}")
        expected = _sha(item.get("sha256"), f"source {key}")
        actual = _ref(p, str(item.get("role", key)))
        if actual["sha256"] != expected:
            raise AuditError(f"source {key} digest changed")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if field in item and item[field] is not None and actual[field] != item[field]:
                raise AuditError(f"source {key} {field} changed")
        paths[key], records[key] = p, actual
    current = records.get("current336")
    if current is None or current["sha256"] != CURRENT_SHA256:
        raise AuditError("manifest does not bind exact CURRENT336")
    policy = manifest.get("current_receipt_binding_policy")
    if not isinstance(policy, dict):
        raise AuditError("manifest has no current receipt binding policy")
    if policy.get("exact_path") != str(paths["current336"]):
        raise AuditError("current receipt policy exact path differs from current336 source")
    if policy.get("exact_sha256") != CURRENT_SHA256:
        raise AuditError("current receipt policy does not require exact CURRENT336 SHA")
    aliases = policy.get("known_nonexact_aliases")
    if not isinstance(aliases, list):
        raise AuditError("current receipt policy aliases are not a list")
    for alias in aliases:
        if not isinstance(alias, dict) or not isinstance(alias.get("path"), str) or not isinstance(alias.get("sha256"), str):
            raise AuditError("malformed current receipt alias")
        alias_key = alias.get("source_key")
        if not isinstance(alias_key, str) or alias_key not in paths:
            raise AuditError("current receipt alias has no explicit source reference")
        if str(paths[alias_key]) != alias["path"] or records[alias_key]["sha256"] != alias["sha256"]:
            raise AuditError("current receipt alias source binding differs from manifest")
        if alias["sha256"] == CURRENT_SHA256:
            raise AuditError("known nonexact alias unexpectedly equals exact CURRENT336 SHA")
    return manifest, paths, records, policy


def _load_current(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    current = _json(path, "CURRENT336")
    if current.get("schema") != CURRENT_SCHEMA or not isinstance(current.get("cases"), list) or len(current["cases"]) != 336:
        raise AuditError("CURRENT336 must contain exactly 336 cases")
    rows: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(current["cases"]):
        if not isinstance(row, dict) or row.get("current_index", index) != index:
            raise AuditError(f"CURRENT336 index is not exact at {index}")
        key = _case_key(row)
        if key is None or key in rows:
            raise AuditError(f"CURRENT336 case identity is invalid at {index}")
        rows[key] = row
    if len(rows) != 336:
        raise AuditError("CURRENT336 case identity count is not 336")
    return current["cases"], rows


def _summary_ledger(role: str, value: Any, frames: int, case_key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditError(f"{case_key} ledger {role} is not an object")
    counts, masses = value.get("active_count"), value.get("active_mass_kg")
    if not isinstance(counts, list) or not isinstance(masses, list) or len(counts) != frames or len(masses) != frames:
        raise AuditError(f"{case_key} ledger {role} lengths do not equal frames")
    if not all(_finite(v) and float(v) >= 0 for v in counts + masses):
        raise AuditError(f"{case_key} ledger {role} has non-finite or negative values")
    return {
        "frames": frames,
        "active_count_first": counts[0] if counts else None,
        "active_count_last": counts[-1] if counts else None,
        "active_count_min": min(counts) if counts else None,
        "active_count_max": max(counts) if counts else None,
        "active_mass_kg_first": masses[0] if masses else None,
        "active_mass_kg_last": masses[-1] if masses else None,
        "active_mass_kg_min": min(masses) if masses else None,
        "active_mass_kg_max": max(masses) if masses else None,
        "saved_frame_series_observed": True,
        "per_id_lifecycle_exposed": False,
    }


def _receipt_current_binding(
    receipt: dict[str, Any], expected_path: str, expected_sha256: str
) -> dict[str, Any]:
    """Classify the receipt's CURRENT336 input without accepting aliases.

    Older scan receipts can point at a catalog-002 CURRENT336 path whose JSON
    happens to have the same case shape but a different digest.  That is a
    source-closure mismatch, not a reason to silently substitute the primary
    CURRENT file.  We keep the row for audit completeness and expose the
    mismatch so callers cannot grant exact-current scientific credit.
    """
    hashes = receipt.get("input_hashes_after_run")
    if not isinstance(hashes, dict):
        return {
            "status": "CURRENT_RECEIPT_BINDING_NOT_OBSERVED",
            "expected_path": expected_path,
            "expected_sha256": expected_sha256,
            "observed": [],
            "exact": False,
        }
    observed = []
    exact = False
    for raw_path, raw_sha in hashes.items():
        if not isinstance(raw_path, str) or Path(raw_path).name != "CURRENT336.json":
            continue
        item = {"path": raw_path, "sha256": raw_sha}
        observed.append(item)
        if raw_path == expected_path and raw_sha == expected_sha256:
            exact = True
    if exact:
        status = "CURRENT_RECEIPT_BINDING_EXACT"
    elif observed:
        status = "CURRENT_RECEIPT_BINDING_MISMATCH"
    else:
        status = "CURRENT_RECEIPT_BINDING_NOT_OBSERVED"
    return {
        "status": status,
        "expected_path": expected_path,
        "expected_sha256": expected_sha256,
        "observed": observed,
        "exact": exact,
    }


def _case_audit(
    key: str,
    current: dict[str, Any],
    v29: dict[str, Any],
    card_path: Path,
    card_ref: dict[str, Any],
    scan_path: Path,
    scan_ref: dict[str, Any],
    receipt_path: Path,
    receipt_ref: dict[str, Any],
    expected_current_path: str,
    expected_current_sha256: str,
) -> dict[str, Any]:
    card = _json(card_path, f"detail card {key}")
    if card.get("schema") != DETAIL_CARD_SCHEMA or card.get("case_key") != key or card.get("current_index") != current.get("current_index"):
        raise AuditError(f"detail card identity mismatch: {key}")
    card_scan = card.get("scan_provenance") or {}
    card_receipt = card.get("receipt_provenance") or {}
    if card_scan.get("path") != str(scan_path) or card_scan.get("observed_sha256") != scan_ref["sha256"]:
        raise AuditError(f"detail card scan binding mismatch: {key}")
    if card_receipt.get("path") != str(receipt_path) or card_receipt.get("observed_sha256") != receipt_ref["sha256"]:
        raise AuditError(f"detail card receipt binding mismatch: {key}")
    scientific = card.get("scientific_scan")
    if not isinstance(scientific, dict) or scientific.get("schema") != SCAN_SCHEMA:
        raise AuditError(f"detail card does not carry scientific scan v1: {key}")
    scan = _json(scan_path, f"scientific scan {key}")
    if scan.get("schema") != SCAN_SCHEMA or scan.get("scan_status") != "SCANNED":
        raise AuditError(f"scientific scan schema/status mismatch: {key}")
    if _producer_case_key(scan, f"scientific scan {key}") != key:
        raise AuditError(f"scientific scan producer identity mismatch: {key}")
    # The detail card's scientific_scan is a projection, not a copy of the
    # producer's identity-bearing top-level object.  Compare only fields the
    # projection is documented to preserve, while using the producer pair
    # above as the authoritative case identity.
    if scientific.get("frames") != scan.get("frames"):
        raise AuditError(f"detail/scan frame field mismatch: {key}")
    if scientific.get("scan_status") not in (None, scan.get("scan_status")):
        raise AuditError(f"detail/scan status field mismatch: {key}")
    if scientific.get("full_saved_timeline_scanned") not in (None, scan.get("full_saved_timeline_scanned")):
        raise AuditError(f"detail/scan timeline field mismatch: {key}")
    receipt = _json(receipt_path, f"execution receipt {key}")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError(f"scan receipt is not completed: {key}")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise AuditError(f"scan receipt has no embedded request: {key}")
    command = request.get("command")
    if not isinstance(command, list) or "--case-id" not in command or command[command.index("--case-id") + 1] != current.get("physical_case_id"):
        raise AuditError(f"scan receipt command case binding mismatch: {key}")
    current_binding = _receipt_current_binding(receipt, expected_current_path, expected_current_sha256)
    frames = scientific.get("frames")
    if not isinstance(frames, int) or frames <= 0:
        raise AuditError(f"invalid frame count: {key}")
    metadata = scientific.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("units"), dict) or not isinstance(metadata.get("identity_key"), str):
        raise AuditError(f"units/identity metadata not exposed: {key}")
    units = metadata["units"]
    expected_units = {"density": "kg/m^3", "mass": "kg", "position": "m", "pressure": "Pa", "time": "s", "velocity": "m/s"}
    if units != expected_units:
        raise AuditError(f"unexpected units metadata for {key}")
    macros = scientific.get("macros")
    if not isinstance(macros, list) or len(macros) != frames:
        raise AuditError(f"macro frame count is not exact: {key}")
    macro_times = []
    for macro in macros:
        if not isinstance(macro, dict) or set(macro) != {"active_fluid_com_m", "active_fluid_kinetic_energy_J", "active_fluid_mass_kg", "active_fluid_mean_velocity_m_s", "time_s"}:
            raise AuditError(f"macro field schema mismatch: {key}")
        if not _finite(macro["time_s"]) or not _finite(macro["active_fluid_mass_kg"]) or not _finite(macro["active_fluid_kinetic_energy_J"]):
            raise AuditError(f"macro scalar is non-finite: {key}")
        macro_times.append(float(macro["time_s"]))
    failures = scientific.get("failures")
    missing_ids = scientific.get("missing_id_records")
    if not isinstance(failures, list) or not isinstance(missing_ids, list):
        raise AuditError(f"failure/missing-id fields are not lists: {key}")
    ledgers = scientific.get("type_ledgers")
    if not isinstance(ledgers, dict) or set(ledgers) != set(LEDGER_ROLES):
        raise AuditError(f"typed ledgers are not fixed/floating/fluid/moving: {key}")
    ledger_summary = {role: _summary_ledger(role, ledgers[role], frames, key) for role in LEDGER_ROLES}
    v29_audit = v29.get("scientific_audit") or {}
    v29_scan = v29_audit.get("scan_provenance") or {}
    v29_receipt = v29_audit.get("receipt_provenance") or {}
    if v29_scan.get("path") != str(scan_path) or v29_scan.get("declared_sha256") != scan_ref["sha256"]:
        raise AuditError(f"v29 scan provenance mismatch: {key}")
    if v29_receipt.get("path") != str(receipt_path) or v29_receipt.get("declared_sha256") != receipt_ref["sha256"]:
        raise AuditError(f"v29 receipt provenance mismatch: {key}")
    lifecycle = "NOT_EXPOSED_AS_PER_ID_LIFECYCLE"
    return {
        "case_key": key,
        "current_index": current.get("current_index"),
        "family_id": current.get("family_id"),
        "physical_case_id": current.get("physical_case_id"),
        "source_roles": {"v29_source_role": (v29.get("current") or {}).get("source_role"), "detail_claim": (card.get("claim_boundary") or {}).get("units_identity_time_lifecycle")},
        "scan_binding": {"detail_card": {"path": str(card_path), "sha256": card_ref["sha256"]}, "scientific_scan": {"path": str(scan_path), "sha256": scan_ref["sha256"]}, "execution_receipt": {"path": str(receipt_path), "sha256": receipt_ref["sha256"]}, "v29_scan_provenance": "EXACT_PATH_AND_SHA_JOIN", "v29_receipt_provenance": "EXACT_PATH_AND_SHA_JOIN", "current_receipt": current_binding},
        "receipt": {"attempt_id": request.get("attempt_id"), "status": receipt.get("status"), "finished_at_utc": receipt.get("finished_at_utc"), "output_root": receipt.get("output_root"), "cpu_core_seconds": receipt.get("cpu_core_seconds"), "current_binding": current_binding, "trajectory_h5_opened_by_collector": (card.get("claim_boundary") or {}).get("trajectory_h5_opened_by_collector") is True},
        "observed_fields": {"scan_schema": SCAN_SCHEMA, "frames": frames, "particles": scientific.get("particles"), "full_saved_timeline_scanned": scientific.get("full_saved_timeline_scanned"), "failures_count": len(failures), "missing_id_record_count": len(missing_ids), "metadata_units": units, "identity_key": metadata.get("identity_key"), "coordinate_frame": metadata.get("coordinate_frame"), "macro_time_count": len(macros), "macro_time_first_s": macro_times[0], "macro_time_last_s": macro_times[-1], "macro_time_strictly_increasing": all(a < b for a, b in zip(macro_times, macro_times[1:])), "typed_ledgers": ledger_summary, "per_id_lifecycle": lifecycle, "finite_field_failure_list": {"status": "OBSERVED_EMPTY" if not failures else "OBSERVED_NONEMPTY", "count": len(failures), "qualification_credit": "NONE"}},
        "source_closure": {"status": "EXACT_CURRENT_AND_SCAN_RECEIPT_JOIN" if current_binding["exact"] else current_binding["status"], "scientific_credit": "NONE" if not current_binding["exact"] else "SOURCE_FIELDS_ONLY"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }


def build_catalog(manifest_path: Path | str) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest, paths, records, current_policy = _load_manifest(manifest_path)
    current_rows, current_by_key = _load_current(paths["current336"])
    v29 = _json(paths["v29_product"], "v29 catalog")
    if v29.get("schema") != V29_SCHEMA or not isinstance(v29.get("cases"), list) or len(v29["cases"]) != 336:
        raise AuditError("v29 catalog must contain exactly 336 cases")
    v29_by_key = {_case_key(row): row for row in v29["cases"] if isinstance(row, dict)}
    if len(v29_by_key) != 336 or set(v29_by_key) != set(current_by_key):
        raise AuditError("v29 case identity set differs from exact CURRENT336")
    detail_report = _json(paths["detail_report"], "scientific-scan detail report")
    if detail_report.get("schema") != DETAIL_REPORT_SCHEMA or len(detail_report.get("detail_cards", [])) != 336:
        raise AuditError("detail report must contain exactly 336 cards")
    if (detail_report.get("current") or {}).get("sha256") != CURRENT_SHA256:
        raise AuditError("detail report CURRENT binding differs from exact CURRENT336")
    cases = manifest.get("case_sources")
    if not isinstance(cases, list) or len(cases) != 336:
        raise AuditError("manifest case_sources must contain exactly 336 rows")
    by_manifest = {row.get("case_key"): row for row in cases if isinstance(row, dict)}
    if len(by_manifest) != 336 or set(by_manifest) != set(current_by_key):
        raise AuditError("manifest case_sources identity set differs from CURRENT336")
    cards = {row.get("case_key"): row for row in detail_report["detail_cards"] if isinstance(row, dict)}
    if len(cards) != 336 or set(cards) != set(current_by_key):
        raise AuditError("detail report case identity set differs from CURRENT336")
    output_rows = []
    for index, current in enumerate(current_rows):
        key = _case_key(current)
        current["_current_path"] = str(paths["current336"])
        source = by_manifest[key]
        card_ref = source.get("detail_card") or {}
        scan_ref = source.get("scientific_scan") or {}
        receipt_ref = source.get("execution_receipt") or {}
        card_path = _path(card_ref.get("path"), f"detail card {key}")
        scan_path = _path(scan_ref.get("path"), f"scientific scan {key}")
        receipt_path = _path(receipt_ref.get("path"), f"execution receipt {key}")
        for label, item, path in (("detail", card_ref, card_path), ("scan", scan_ref, scan_path), ("receipt", receipt_ref, receipt_path)):
            expected = _sha(item.get("sha256"), f"{key} {label} SHA")
            actual = sha256_file(path)
            if actual != expected:
                raise AuditError(f"{key} {label} digest changed")
        if card_path != _path(cards[key].get("path"), f"detail report card {key}") or cards[key].get("sha256") != card_ref.get("sha256"):
            raise AuditError(f"detail report card binding mismatch: {key}")
        output_rows.append(
            _case_audit(
                key,
                current,
                v29_by_key[key],
                card_path,
                _ref(card_path, "detail_card"),
                scan_path,
                _ref(scan_path, "scientific_scan"),
                receipt_path,
                _ref(receipt_path, "execution_receipt"),
                str(current_policy["exact_path"]),
                str(current_policy["exact_sha256"]),
            )
        )
    native_count = sum(bool((row.get("native_omission") is not None)) for row in v29["cases"])
    lifecycle_missing = sum(((row.get("qualification_dimensions") or {}).get("finite_fields") or {}).get("active_finite_lifecycle_fields") == "NOT_EXPOSED_IN_THIS_AUDIT_ROW" for row in v29["cases"])
    current_exact = sum(row.get("source_closure", {}).get("status") == "EXACT_CURRENT_AND_SCAN_RECEIPT_JOIN" for row in output_rows)
    current_mismatch = sum(row.get("source_closure", {}).get("status") == "CURRENT_RECEIPT_BINDING_MISMATCH" for row in output_rows)
    current_unobserved = sum(row.get("source_closure", {}).get("status") == "CURRENT_RECEIPT_BINDING_NOT_OBSERVED" for row in output_rows)
    return {
        "schema": OUTPUT_SCHEMA,
        "status": "COMPLETED_JSON_ONLY_ENRICHED_SCIENTIFIC_SCAN_AUDIT_V3",
        "current_binding": {"path": str(paths["current336"]), "sha256": CURRENT_SHA256, "case_count": 336, "family_counts": {f"F{i}": 48 for i in range(1, 8)}, "receipt_policy": current_policy},
        "source_binding": {"v29_catalog": {"path": str(paths["v29_product"]), "sha256": records["v29_product"]["sha256"]}, "detail_report": {"path": str(paths["detail_report"]), "sha256": records["detail_report"]["sha256"]}, "exact_case_set_join": True, "all_scan_and_receipt_paths_explicit": True},
        "read_policy": {"scientific_scan_json_opened": True, "execution_receipt_json_opened": True, "detail_card_json_opened": True, "trajectory_h5_opened": False, "bi4_opened": False, "obi4_opened": False, "vtk_opened": False, "raw_solver_output_opened": False, "solver_started": False, "model_invoked": False},
        "coverage": {"case_count": 336, "scanned_status_count": len(output_rows), "native_omission_cases_from_v29": native_count, "lifecycle_missing_exposure_rows_from_v29": lifecycle_missing, "non_native_rows": "NOT_REPORTED", "detail_cards_with_exact_scan_receipt_join": len(output_rows), "exact_current_receipt_joins": current_exact, "current_receipt_binding_mismatches": current_mismatch, "current_receipt_binding_not_observed": current_unobserved, "detail_cards_with_exact_scan_receipt_join": len(output_rows), "scan_failure_lists_observed_empty": sum(row["observed_fields"]["failures_count"] == 0 for row in output_rows), "per_id_lifecycle_exposed_rows": 0},
        "semantic_boundary": {"finite_failures_empty": "Observed empty producer failure lists do not prove finite validity.", "typed_ledgers": "Saved-frame active count/mass series are exposed metadata; they do not establish per-ID lifecycle, continuous events, legal flux, or dynamics.", "lifecycle": "Per-ID lifecycle is NOT_EXPOSED_AS_PER_ID_LIFECYCLE; 290 v29 missing-exposure rows are not non-native rows.", "native_omission": "118 is the v29 native-omission scope and is kept separate from lifecycle exposure.", "current_binding": "Only rows whose receipt explicitly hashed the exact primary CURRENT336 path and SHA receive exact-current source-closure status; known aliases with different SHA are retained as mismatches and receive no scientific credit.", "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"}},
        "cases": output_rows,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--manifest", required=True)
    build.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_catalog(Path(args.manifest))
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        raise SystemExit("--output must be absolute")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except AuditError as exc:
        raise SystemExit(f"scientific-scan enriched-audit error: {exc}")
