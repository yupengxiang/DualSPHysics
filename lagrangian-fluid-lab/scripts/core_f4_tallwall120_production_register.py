#!/usr/bin/env python3
"""Register a formally verified F4 production scope in the Core registry.

The production collector is deliberately read-only.  This small, explicit
registration boundary turns its formal collection into the typed Core
qualification/case evidence consumed by ``core_campaign.py``.  It refuses
partial collections, qualification products, hash mismatches and ambiguous
registry migrations before writing anything.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
COLLECTION_SCHEMA = "core.f4.tallwall120.production_collection.v1"
QUALIFICATION_SCHEMA = "core.qualification.v1"
CASE_SCHEMA = "core.case_audit.v1"
REGISTRY_SCHEMA = "core.registry.v1"
EXPECTED_SPLITS = {"train": 16, "validation": 4, "id_test": 6, "ood_test": 6}


class RegistrationError(ValueError):
    """Raised when formal evidence cannot be admitted to the Core registry."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistrationError(f"cannot read JSON evidence: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistrationError(f"evidence must be a JSON object: {path}")
    return value


def _relative_path(lab_root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (lab_root / candidate).resolve()
    try:
        relative = resolved.relative_to(lab_root.resolve())
    except ValueError as exc:
        raise RegistrationError(f"evidence escapes lab root: {value}") from exc
    if ".." in relative.parts:
        raise RegistrationError(f"parent traversal in evidence path: {value}")
    return relative


def _file_ref(lab_root: Path, value: str | Path, *, role: str,
              expected_sha: str | None = None,
              expected_bytes: int | None = None) -> dict[str, Any]:
    relative = _relative_path(lab_root, value)
    path = lab_root / relative
    if not path.is_file():
        raise RegistrationError(f"{role} is missing: {relative}")
    size = path.stat().st_size
    sha = _sha256(path)
    if expected_bytes is not None and size != expected_bytes:
        raise RegistrationError(f"{role} byte count mismatch: {relative}")
    if expected_sha is not None and sha != expected_sha:
        raise RegistrationError(f"{role} SHA-256 mismatch: {relative}")
    return {"path": relative.as_posix(), "bytes": size, "sha256": sha, "role": role}


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _write_idempotent(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        existing = _load(path)
        if existing != value:
            raise RegistrationError(f"refusing to overwrite different evidence: {path}")
        return
    _atomic_json(path, value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


def _validate_range_qualification(lab_root: Path, path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    qualification = _load(path)
    _require(qualification.get("schema") == QUALIFICATION_SCHEMA,
             "range qualification schema is unsupported")
    _require(qualification.get("scope_id") == SCOPE_ID,
             "range qualification scope does not bind F4 tallwall120")
    _require(qualification.get("family") == FAMILY, "range qualification family mismatch")
    _require(qualification.get("T1_numerical") is True,
             "range qualification does not pass T1 numerical")
    _require(qualification.get("matrix_complete") is True,
             "range qualification matrix is incomplete")
    _require(qualification.get("independent_checks_passed") is True,
             "range qualification independent checks are incomplete")
    _require(qualification.get("extent") == "parameter_range",
             "range qualification is not a parameter-range qualification")
    return qualification, _file_ref(lab_root, path, role="F4 range qualification")


def _validate_collection(lab_root: Path, path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    collection = _load(path)
    _require(collection.get("schema") == COLLECTION_SCHEMA, "formal collection schema is unsupported")
    _require(collection.get("scope_id") == SCOPE_ID, "formal collection scope mismatch")
    _require(collection.get("family") == FAMILY, "formal collection family mismatch")
    _require(collection.get("formal_release_requested") is True,
             "formal collection was not created with a formal request")
    _require(collection.get("formal_eligible") is True,
             "formal collection is not formally eligible")
    _require(collection.get("qualification_evidence_verified") is True,
             "qualification evidence was not authoritatively verified")
    _require(collection.get("gpu_started") is False, "registration evidence claims a GPU side effect")
    _require(collection.get("ledger_written") is False, "read-only collector wrote a ledger")
    _require(collection.get("central_registry_written") is False,
             "read-only collector wrote the central registry")
    for key, expected in (("registered_case_count", 32), ("prepared_case_count", 32),
                          ("execution_complete_count", 32),
                          ("execution_receipt_bound_case_count", 32),
                          ("authoritative_audit_verified_case_count", 32),
                          ("scientifically_passed_case_count", 32),
                          ("failed_case_count", 0), ("pending_case_count", 0),
                          ("invalid_case_count", 0)):
        _require(collection.get(key) == expected, f"formal collection {key} is not {expected}")
    _require(collection.get("hold_reasons") == [], "formal collection has hold reasons")

    rows = collection.get("cases")
    manifest_rows = collection.get("reader_manifest", {}).get("cases")
    _require(isinstance(rows, list) and len(rows) == 32, "formal collection must contain 32 case rows")
    _require(isinstance(manifest_rows, list) and len(manifest_rows) == 32,
             "formal reader manifest must contain 32 cases")
    manifest_by_id = {row.get("case_id"): row for row in manifest_rows if isinstance(row, dict)}
    _require(len(manifest_by_id) == 32, "formal reader manifest case IDs are not unique")
    indexes = [row.get("index") for row in rows]
    _require(sorted(indexes) == list(range(32)), "formal collection indices are not exactly 0..31")
    observed_splits = Counter(row.get("split") for row in rows)
    _require(dict(observed_splits) == EXPECTED_SPLITS,
             f"formal collection split counts differ: {dict(observed_splits)}")

    collection_ref = _file_ref(lab_root, path, role="formal F4 production collection")
    normalized_rows: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item["index"]):
        _require(row.get("family") == FAMILY, f"case {row.get('index')} family mismatch")
        case_id = row.get("case_id")
        _require(isinstance(case_id, str) and case_id in manifest_by_id,
                 f"case {row.get('index')} is absent from the reader manifest")
        _require(row.get("status") == "completed", f"case {case_id} is not completed")
        _require(row.get("scientific_status") == "passed", f"case {case_id} is not scientifically passed")
        _require(row.get("authoritative_audit_verified") is True,
                 f"case {case_id} lacks authoritative audit verification")
        _require(row.get("execution_complete") is True and row.get("execution_receipt_bound") is True,
                 f"case {case_id} lacks complete execution binding")
        _require(row.get("qualification_only") is False and row.get("reader_eligible") is True,
                 f"case {case_id} is not a production reader case")
        _require(row.get("failure_category") is None and row.get("reasons") == [],
                 f"case {case_id} has a failure or reason")
        manifest = manifest_by_id[case_id]
        _require(manifest.get("production_status") == "completed" and
                 manifest.get("scientific_status") == "passed" and
                 manifest.get("qualification_only") is not True and
                 manifest.get("qualification_case") is not True,
                 f"reader manifest case {case_id} is not a completed production case")
        trajectory = _file_ref(lab_root, manifest.get("hdf5"), role=f"case {case_id} trajectory",
                               expected_sha=manifest.get("sha256"), expected_bytes=manifest.get("bytes"))
        # Verify the authoritative refs before the case evidence is created.  The
        # collection already carries the expected hashes; re-reading them here
        # prevents a registry entry from binding a changed archive.
        for field in ("audit", "execution", "result", "observations", "prepared"):
            ref = row.get(field)
            _require(isinstance(ref, dict) and ref.get("path"),
                     f"case {case_id} lacks {field} binding")
            _file_ref(lab_root, ref["path"], role=f"case {case_id} {field}",
                      expected_sha=ref.get("sha256"), expected_bytes=ref.get("bytes"))
        normalized_rows.append({"row": row, "manifest": manifest, "trajectory": trajectory})
    return collection, collection_ref, normalized_rows


def register_f4(*, lab_root: Path, registry_path: Path, formal_collection: Path,
                range_qualification: Path, qualification_output: Path,
                case_dir: Path, registration_output: Path) -> dict[str, Any]:
    lab_root = lab_root.resolve()
    registry_path = registry_path if registry_path.is_absolute() else lab_root / registry_path
    formal_collection = formal_collection if formal_collection.is_absolute() else lab_root / formal_collection
    range_qualification = range_qualification if range_qualification.is_absolute() else lab_root / range_qualification
    qualification_output = qualification_output if qualification_output.is_absolute() else lab_root / qualification_output
    case_dir = case_dir if case_dir.is_absolute() else lab_root / case_dir
    registration_output = registration_output if registration_output.is_absolute() else lab_root / registration_output

    _, range_ref = _validate_range_qualification(lab_root, range_qualification)
    collection, collection_ref, rows = _validate_collection(lab_root, formal_collection)

    qualification = {
        "schema": QUALIFICATION_SCHEMA,
        "scope_id": SCOPE_ID,
        "family": FAMILY,
        "T1_numerical": True,
        "T2_macro": False,
        "T2_path": False,
        "external_physical_validation": False,
        "extent": "parameter_range",
        "matrix_complete": True,
        "independent_checks_passed": True,
        "qualification_origin": "formal F4 range qualification plus hash-bound 32-case production collection",
        "range_qualification": range_ref,
        "production_collection": collection_ref,
        "formal_eligible": True,
        "formal_release_requested": True,
        "registered_production_cases_completed": 32,
        "fixed_split_counts": EXPECTED_SPLITS,
        "qualification_evidence_verified": True,
    }
    _write_idempotent(qualification_output, qualification)
    qualification_ref = _file_ref(lab_root, qualification_output, role="registered F4 qualification")

    case_records: list[dict[str, Any]] = []
    for item in rows:
        row, manifest, trajectory = item["row"], item["manifest"], item["trajectory"]
        case_id = row["case_id"]
        case_path = case_dir / f"{case_id}.json"
        case_evidence = {
            "schema": CASE_SCHEMA,
            "case_id": case_id,
            "physical_case_id": row.get("physical_case_id", case_id),
            "lineage_group_id": row.get("lineage_group_id", case_id),
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "split": row["split"],
            "hard_integrity_pass": True,
            "T1_numerical": True,
            "scientific_status": "passed",
            "qualification_only": False,
            "source_collection": collection_ref,
            "authoritative_audit": row["audit"],
            "execution_receipt": row["execution"],
            "result": row["result"],
            "observations": row["observations"],
            "prepared": row["prepared"],
            "trajectory": trajectory,
            "reader_manifest_case": {
                "case_id": manifest["case_id"],
                "hdf5": trajectory,
                "known_inputs_sha256": manifest.get("known_inputs_sha256"),
                "production_status": manifest.get("production_status"),
            },
        }
        _write_idempotent(case_path, case_evidence)
        case_ref = _file_ref(lab_root, case_path, role=f"registered F4 case {case_id}")
        case_records.append({
            "case_id": case_id,
            "physical_case_id": case_evidence["physical_case_id"],
            "lineage_group_id": case_evidence["lineage_group_id"],
            "split": row["split"],
            "hard_integrity_pass": True,
            "T1_numerical": True,
            "audit": case_ref,
        })

    new_scope = {
        "scope_id": SCOPE_ID,
        "family": FAMILY,
        "qualification": qualification_ref,
        "cases": case_records,
    }
    registry = _load(registry_path) if registry_path.exists() else {
        "schema": REGISTRY_SCHEMA, "scope_studies": [], "scopes": [],
        "training_runs": [], "evaluations": [],
    }
    _require(registry.get("schema") == REGISTRY_SCHEMA, "registry schema is unsupported")
    scopes = registry.setdefault("scopes", [])
    existing = next((scope for scope in scopes if scope.get("scope_id") == SCOPE_ID), None)
    if existing is None:
        scopes.append(new_scope)
    elif existing != new_scope:
        raise RegistrationError("existing F4 registry scope differs; refusing implicit migration")
    _atomic_json(registry_path, registry)

    previous_registration = _load(registration_output) if registration_output.exists() else {}
    registration = {
        "schema": "core.f4.tallwall120.production_registration.v1",
        "registered_at_utc": previous_registration.get(
            "registered_at_utc", datetime.now(timezone.utc).isoformat()),
        "scope_id": SCOPE_ID,
        "family": FAMILY,
        "formal_collection": collection_ref,
        "qualification": qualification_ref,
        "case_count": len(case_records),
        "split_counts": dict(Counter(item["split"] for item in case_records)),
        "registry": _file_ref(lab_root, registry_path, role="Core registry"),
        "central_registry_written": True,
        "ledger_written": False,
        "gpu_started": False,
        "formal_collection_sha256": collection_ref["sha256"],
        "formal_collection_scope": collection.get("scope_id"),
    }
    _write_idempotent(registration_output, registration)
    return registration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--registry", type=Path, default=Path("campaigns/core-v1/registry.json"))
    parser.add_argument("--formal-collection", type=Path, required=True)
    parser.add_argument("--range-qualification", type=Path, required=True)
    parser.add_argument("--qualification-output", type=Path,
                        default=Path("campaigns/core-v1/evidence/f4-tallwall120-formal-qualification-20260920.json"))
    parser.add_argument("--case-dir", type=Path,
                        default=Path("campaigns/core-v1/evidence/f4-tallwall120-cases"))
    parser.add_argument("--registration-output", type=Path,
                        default=Path("campaigns/core-v1/evidence/f4-tallwall120-formal-registration-20260920.json"))
    args = parser.parse_args(argv)
    try:
        result = register_f4(lab_root=args.lab_root, registry_path=args.registry,
                             formal_collection=args.formal_collection,
                             range_qualification=args.range_qualification,
                             qualification_output=args.qualification_output,
                             case_dir=args.case_dir,
                             registration_output=args.registration_output)
    except RegistrationError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
