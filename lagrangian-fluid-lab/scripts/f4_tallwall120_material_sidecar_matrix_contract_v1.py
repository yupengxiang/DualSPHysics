#!/usr/bin/env python3
"""Static, fail-closed contract for the F4 Tallwall120 material sidecar matrix.

This module defines the coarse-to-fine interface for one material sidecar per
case in the fixed 32-case F4 Tallwall120 collection.  It is deliberately an
evidence contract, not a launcher: only bounded JSON and small-file metadata
are consumed.  Trajectory HDF5 content is never opened or hashed, and this
module never starts or controls a solver, worker, GPU, or queue.

The current repository state is expected to remain blocked.  The collection
manifest is a native CFD collection, not a material sidecar matrix; its case
rows currently use archives-v1 while the DEV_07 material proposal pins
archives-v2.  The report therefore preserves those mismatches and refuses
promotion, partial credit, or execution authorization.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "core.material.f4.tallwall120.sidecar_matrix_contract.v1"
MATERIAL_SIDECAR_SCHEMA = "core.material.f4.tallwall120.material_sidecar.v1"
COLLECTION_SCHEMA = "core.f4.tallwall120.production_collection.v1"
READER_SMOKE_SCHEMA = "local.f4.core_reader_smoke.stdout.v1"

OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
MAX_JSON_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = {".h5", ".hdf5"}

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_PREFIX = f"{SCOPE_ID}_DEV_"
EXPECTED_CASE_COUNT = 32
EXPECTED_SPLIT_COUNTS = {
    "train": 16,
    "validation": 4,
    "id_test": 6,
    "ood_test": 6,
}
EXPECTED_SPLITS_BY_INDEX = (
    "ood_test",
    "ood_test",
    "ood_test",
    "train",
    "train",
    "id_test",
    "train",
    "train",
    "validation",
    "id_test",
    "train",
    "train",
    "train",
    "validation",
    "id_test",
    "train",
    "train",
    "id_test",
    "validation",
    "train",
    "train",
    "train",
    "id_test",
    "validation",
    "train",
    "train",
    "id_test",
    "train",
    "train",
    "ood_test",
    "ood_test",
    "ood_test",
)
EXPECTED_CASE_IDS = tuple(
    f"{CASE_PREFIX}{index:02d}" for index in range(EXPECTED_CASE_COUNT)
)
EXPECTED_CASE_SPLITS = dict(zip(EXPECTED_CASE_IDS, EXPECTED_SPLITS_BY_INDEX))

EXPECTED_ARCHIVE_VARIANT = "archives-v2"
EXPECTED_EVENT_WINDOW_S = 8.68
EXPECTED_UNKNOWN_FRACTION_MAX = 0.01
EXPECTED_MASS_CLOSURE_ERROR_MAX = 1.0e-12
EXPECTED_RELIABLE_COVERAGE_MIN = 1.0
EXPECTED_RIGHT_CENSOR_STATUS = "not_right_censored"

COLLECTION_MANIFEST = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
READER_SMOKE_REPORT = Path(
    "reports/F4-TALLWALL120-CORE-READER-SMOKE-2026-09-28.json"
)
PROPOSAL_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json"
)
CONSISTENCY_AUDIT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"
)
TERMINAL_INTAKE_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json"
)
T2_ACCEPTANCE_BRIDGE = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260922-v3.json"
)

INPUT_REFS = {
    "collection_manifest": COLLECTION_MANIFEST,
    "reader_smoke": READER_SMOKE_REPORT,
    "dev07_proposal": PROPOSAL_REPORT,
    "receipt_consistency_audit": CONSISTENCY_AUDIT_REPORT,
    "terminal_evidence_intake": TERMINAL_INTAKE_REPORT,
    "t2_acceptance_bridge": T2_ACCEPTANCE_BRIDGE,
}

DEFAULT_OUTPUT_NAMESPACE = Path(
    "campaigns/core-v1/material/sidecars/"
    "f4-tallwall120-sidecar-matrix-v1-20260928"
)
DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-SIDECAR-MATRIX-CONTRACT-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-SIDECAR-MATRIX-CONTRACT-V1-2026-09-28.zh-CN.md"
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(root: Path, value: str | Path) -> dict[str, Any]:
    path = _resolve(root, value)
    if path.suffix.lower() in HDF5_SUFFIXES:
        raise ValueError(f"HDF5 content is outside the JSON boundary: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        raise ValueError(f"JSON input exceeds bound: {path} ({size} bytes)")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def _small_file_binding(root: Path, value: str | Path, role: str) -> dict[str, Any]:
    """Read/hash only bounded non-HDF5 files; stat HDF5 paths without reading."""

    path = _resolve(root, value)
    binding: dict[str, Any] = {
        "role": role,
        "path": _relative(root, path),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "bounded_small_file_read": False,
        "hdf5_metadata_only": False,
    }
    if path.suffix.lower() in HDF5_SUFFIXES:
        binding["bytes"] = path.stat().st_size if path.is_file() else None
        binding["hdf5_metadata_only"] = True
        binding["error"] = "hdf5_content_not_read_or_hashed"
        return binding
    if not path.is_file():
        binding["error"] = "missing_file"
        return binding
    binding["bytes"] = path.stat().st_size
    if binding["bytes"] > MAX_JSON_BYTES:
        binding["error"] = "file_exceeds_bounded_limit"
        return binding
    binding["sha256"] = _sha256_bytes(path.read_bytes())
    binding["bounded_small_file_read"] = True
    return binding


def _hdf5_metadata(root: Path, value: str | Path, declared_sha256: Any) -> dict[str, Any]:
    """Return filesystem metadata only; never open or hash the HDF5."""

    path = _resolve(root, value)
    exists = path.is_file()
    return {
        "path": _relative(root, path),
        "exists": exists,
        "bytes": path.stat().st_size if exists else None,
        "declared_sha256": declared_sha256,
        "content_read": False,
        "content_hash_recomputed": False,
        "metadata_only": True,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _number(value: Any) -> float | None:
    return float(value) if _finite_number(value) else None


def _check(
    name: str,
    passed: bool,
    reason: str,
    *,
    observed: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }


def _case_id(index: int) -> str:
    return EXPECTED_CASE_IDS[index]


def _archive_variant(path: Any) -> str | None:
    if not isinstance(path, str):
        return None
    for variant in ("archives-v1", "archives-v2"):
        if variant in path:
            return variant
    return None


def _replace_archive_variant(path: Any, variant: str) -> str | None:
    if not isinstance(path, str):
        return None
    if _archive_variant(path) is None:
        return None
    return path.replace("archives-v1", variant).replace("archives-v2", variant)


def _expected_source_path(collection_row: Mapping[str, Any]) -> str | None:
    trajectory = _mapping(collection_row.get("trajectory"))
    return _replace_archive_variant(trajectory.get("path"), EXPECTED_ARCHIVE_VARIANT)


def _manifest_case_rows(collection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [row for row in _list(collection.get("cases")) if isinstance(row, Mapping)]


def _find_case(rows: Sequence[Mapping[str, Any]], case_id: str) -> Mapping[str, Any] | None:
    for row in rows:
        if row.get("case_id") == case_id:
            return row
    return None


def _sidecar_entries(
    sidecars: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, list[Mapping[str, Any]]], list[str]]:
    """Normalize a sidecar list while retaining duplicate identities."""

    if sidecars is None:
        raw: Any = []
    elif isinstance(sidecars, Mapping):
        raw = sidecars.get("cases", sidecars)
        if isinstance(raw, Mapping):
            raw = [dict(value, case_id=key) for key, value in raw.items() if isinstance(value, Mapping)]
    else:
        raw = sidecars
    entries: dict[str, list[Mapping[str, Any]]] = {}
    malformed: list[str] = []
    for item in _list(raw):
        if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
            malformed.append("<missing-case-id>")
            continue
        entries.setdefault(str(item["case_id"]), []).append(item)
    return entries, malformed


def _claim_projection(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    claims = _mapping(sidecar.get("claims"))
    values = {
        "formal": sidecar.get("formal", claims.get("formal", False)),
        "formal_eligible": sidecar.get(
            "formal_eligible", claims.get("formal_eligible", False)
        ),
        "qualification": sidecar.get("qualification", claims.get("qualification", False)),
        "T1": sidecar.get("T1", claims.get("T1", False)),
        "T2": sidecar.get("T2", claims.get("T2", False)),
        "credit": sidecar.get("credit", claims.get("credit", 0)),
        "qualification_credit": sidecar.get(
            "qualification_credit", claims.get("qualification_credit", 0)
        ),
    }
    return values


def _marker_projection(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    markers = _mapping(sidecar.get("material_markers"))
    mass = _mapping(markers.get("mass_closure"))
    unknown = _mapping(markers.get("unknown_fraction"))
    coverage = _mapping(markers.get("reliable_coverage"))
    return {
        "mass_closure_error": mass.get("error"),
        "mass_closure_reported": _finite_number(mass.get("error")),
        "unknown_fraction_max": unknown.get("max"),
        "unknown_fraction_reported": _finite_number(unknown.get("max")),
        "reliable_coverage": coverage.get("fraction"),
        "reliable_coverage_reported": _finite_number(coverage.get("fraction")),
        "right_censor_status": markers.get("right_censor_status"),
    }


def _evaluate_one_sidecar(
    sidecar: Mapping[str, Any],
    *,
    expected_case_id: str,
    expected_split: str,
    expected_source_path: str | None,
    expected_source_sha256: Any,
    output_namespace: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blocking: list[str] = []
    source = _mapping(sidecar.get("source"))
    terminal = _mapping(sidecar.get("terminal"))
    markers = _marker_projection(sidecar)
    claims = _claim_projection(sidecar)
    output = _mapping(sidecar.get("output"))

    checks.append(
        _check(
            "sidecar_schema",
            sidecar.get("schema") == MATERIAL_SIDECAR_SCHEMA,
            "material sidecar schema must be the registered V1 schema",
            observed=sidecar.get("schema"),
            expected=MATERIAL_SIDECAR_SCHEMA,
        )
    )
    checks.append(
        _check(
            "sidecar_identity",
            sidecar.get("case_id") == expected_case_id,
            "sidecar case identity must match the fixed 32-case matrix",
            observed=sidecar.get("case_id"),
            expected=expected_case_id,
        )
    )
    checks.append(
        _check(
            "sidecar_scope",
            sidecar.get("family") == FAMILY and sidecar.get("scope_id") == SCOPE_ID,
            "sidecar family and scope must match F4 Tallwall120",
            observed={"family": sidecar.get("family"), "scope_id": sidecar.get("scope_id")},
            expected={"family": FAMILY, "scope_id": SCOPE_ID},
        )
    )
    checks.append(
        _check(
            "sidecar_split",
            sidecar.get("split") == expected_split,
            "sidecar split must match the fixed collection split",
            observed=sidecar.get("split"),
            expected=expected_split,
        )
    )
    checks.append(
        _check(
            "sidecar_source_path",
            source.get("hdf5") == expected_source_path,
            "sidecar source path must bind the expected archives-v2 source",
            observed=source.get("hdf5"),
            expected=expected_source_path,
        )
    )
    checks.append(
        _check(
            "sidecar_source_sha256",
            source.get("sha256") == expected_source_sha256,
            "sidecar source SHA-256 must bind the fixed case source",
            observed=source.get("sha256"),
            expected=expected_source_sha256,
        )
    )
    checks.append(
        _check(
            "fresh_output_namespace",
            output.get("namespace") == output_namespace
            and output.get("fresh") is True
            and output.get("overwrite_allowed") is False,
            "sidecar output must use a fresh non-overwriting namespace",
            observed=output,
            expected={
                "namespace": output_namespace,
                "fresh": True,
                "overwrite_allowed": False,
            },
        )
    )

    terminal_status = terminal.get("status")
    event_window_complete = (
        terminal.get("event_window_complete") is True
        and _finite_number(terminal.get("event_window_s"))
        and float(terminal["event_window_s"]) >= EXPECTED_EVENT_WINDOW_S
    )
    terminal_complete = terminal.get("execution_complete") is True and terminal_status == "complete"
    checks.append(
        _check(
            "terminal_full_event_window",
            bool(terminal_complete and event_window_complete),
            "material sidecar must contain a complete terminal full event window",
            observed={
                "status": terminal_status,
                "execution_complete": terminal.get("execution_complete"),
                "event_window_complete": terminal.get("event_window_complete"),
                "event_window_s": terminal.get("event_window_s"),
            },
            expected={
                "status": "complete",
                "execution_complete": True,
                "event_window_complete": True,
                "event_window_s_min": EXPECTED_EVENT_WINDOW_S,
            },
        )
    )
    checks.append(
        _check(
            "mass_closure_marker",
            markers["mass_closure_reported"]
            and float(markers["mass_closure_error"]) <= EXPECTED_MASS_CLOSURE_ERROR_MAX,
            "mass closure marker is required and must pass the fixed bound",
            observed=markers["mass_closure_error"],
            expected={"max_error": EXPECTED_MASS_CLOSURE_ERROR_MAX},
        )
    )
    checks.append(
        _check(
            "unknown_fraction_marker",
            markers["unknown_fraction_reported"]
            and 0.0 <= float(markers["unknown_fraction_max"]) <= EXPECTED_UNKNOWN_FRACTION_MAX,
            "unknown fraction marker is required and must pass the fixed bound",
            observed=markers["unknown_fraction_max"],
            expected={"max_fraction": EXPECTED_UNKNOWN_FRACTION_MAX},
        )
    )
    checks.append(
        _check(
            "reliable_coverage_marker",
            markers["reliable_coverage_reported"]
            and 0.0 <= float(markers["reliable_coverage"]) >= EXPECTED_RELIABLE_COVERAGE_MIN,
            "reliable coverage marker is required for the complete event window",
            observed=markers["reliable_coverage"],
            expected={"minimum_fraction": EXPECTED_RELIABLE_COVERAGE_MIN},
        )
    )
    checks.append(
        _check(
            "right_censor_marker",
            markers["right_censor_status"] == EXPECTED_RIGHT_CENSOR_STATUS,
            "right-censored or unresolved material paths cannot pass the contract",
            observed=markers["right_censor_status"],
            expected=EXPECTED_RIGHT_CENSOR_STATUS,
        )
    )

    nonzero_credit = any(
        (_finite_number(claims[key]) and float(claims[key]) != 0.0)
        if key in {"credit", "qualification_credit"}
        else claims[key] is True
        for key in claims
    )
    claims_clear = not nonzero_credit
    checks.append(
        _check(
            "formal_and_credit_claims_clear",
            claims_clear,
            "material sidecars may not self-assert formal, T1, T2, qualification, or credit",
            observed=claims,
            expected={
                "formal": False,
                "formal_eligible": False,
                "qualification": False,
                "T1": False,
                "T2": False,
                "credit": 0,
                "qualification_credit": 0,
            },
        )
    )

    for check in checks:
        if check["passed"]:
            continue
        name = str(check["check"])
        if name == "right_censor_marker":
            blocking.append("right_censored_or_unresolved")
        elif name == "formal_and_credit_claims_clear":
            blocking.append("formal_or_credit_claim_present")
        elif name == "terminal_full_event_window":
            blocking.append("partial_or_missing_terminal_event_window")
        else:
            blocking.append(name)

    status = "complete" if not blocking else "blocked"
    return {
        "case_id": expected_case_id,
        "split": expected_split,
        "status": status,
        "terminal_status": terminal_status,
        "terminal_complete": bool(terminal_complete),
        "event_window_complete": bool(event_window_complete),
        "material_markers": {
            "mass_closure_error": markers["mass_closure_error"],
            "mass_closure_pass": bool(
                markers["mass_closure_reported"]
                and float(markers["mass_closure_error"]) <= EXPECTED_MASS_CLOSURE_ERROR_MAX
            ),
            "unknown_fraction_max": markers["unknown_fraction_max"],
            "unknown_fraction_pass": bool(
                markers["unknown_fraction_reported"]
                and 0.0 <= float(markers["unknown_fraction_max"]) <= EXPECTED_UNKNOWN_FRACTION_MAX
            ),
            "reliable_coverage": markers["reliable_coverage"],
            "reliable_coverage_pass": bool(
                markers["reliable_coverage_reported"]
                and 0.0 <= float(markers["reliable_coverage"]) >= EXPECTED_RELIABLE_COVERAGE_MIN
            ),
            "right_censor_status": markers["right_censor_status"],
            "right_censor_pass": markers["right_censor_status"] == EXPECTED_RIGHT_CENSOR_STATUS,
        },
        "source": {
            "hdf5": source.get("hdf5"),
            "sha256": source.get("sha256"),
            "expected_hdf5": expected_source_path,
            "expected_sha256": expected_source_sha256,
        },
        "fresh_output_namespace": output_namespace,
        "formal_or_credit_claims": claims,
        "blocking_reasons": sorted(set(blocking)),
        "checks": checks,
        "credit": 0,
    }


def evaluate_matrix(
    collection: Mapping[str, Any],
    proposal: Mapping[str, Any],
    reader: Mapping[str, Any],
    consistency_audit: Mapping[str, Any],
    terminal_intake: Mapping[str, Any],
    acceptance_bridge: Mapping[str, Any],
    *,
    sidecars: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    output_namespace: str = DEFAULT_OUTPUT_NAMESPACE.as_posix(),
    collection_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Evaluate the matrix from JSON mappings without touching production HDF5."""

    rows = _manifest_case_rows(collection)
    row_by_id: dict[str, Mapping[str, Any]] = {}
    observed_ids: list[str] = []
    duplicate_manifest_ids: list[str] = []
    for row in rows:
        case_id = row.get("case_id")
        if isinstance(case_id, str):
            observed_ids.append(case_id)
            if case_id in row_by_id:
                duplicate_manifest_ids.append(case_id)
            else:
                row_by_id[case_id] = row

    missing_manifest_ids = sorted(set(EXPECTED_CASE_IDS) - set(observed_ids))
    extra_manifest_ids = sorted(set(observed_ids) - set(EXPECTED_CASE_IDS))
    manifest_duplicates = sorted(set(duplicate_manifest_ids))
    manifest_case_identity_pass = (
        len(rows) == EXPECTED_CASE_COUNT
        and not missing_manifest_ids
        and not extra_manifest_ids
        and not manifest_duplicates
        and len(observed_ids) == len(set(observed_ids))
    )

    split_drift: list[dict[str, Any]] = []
    scope_drift: list[str] = []
    family_drift: list[str] = []
    denominator_drift: list[str] = []
    collection_variant_counts: dict[str, int] = {}
    source_rows: list[dict[str, Any]] = []
    for expected_id in EXPECTED_CASE_IDS:
        row = row_by_id.get(expected_id)
        expected_split = EXPECTED_CASE_SPLITS[expected_id]
        if row is None:
            source_rows.append(
                {
                    "case_id": expected_id,
                    "expected_split": expected_split,
                    "collection_row_present": False,
                    "collection_source_path": None,
                    "collection_source_sha256": None,
                    "expected_source_path": None,
                    "expected_source_sha256": None,
                    "archive_variant": None,
                    "source_path_exact": False,
                    "source_sha256_exact": False,
                    "source_exact": False,
                }
            )
            continue
        observed_split = row.get("split")
        if observed_split != expected_split:
            split_drift.append(
                {
                    "case_id": expected_id,
                    "expected": expected_split,
                    "observed": observed_split,
                }
            )
        if row.get("family") != FAMILY:
            family_drift.append(expected_id)
        # The frozen collection case-row schema carries the scope at the
        # manifest root; tolerate an omitted per-row scope field, but reject
        # an explicitly supplied wrong scope.
        if "scope_id" in row and row.get("scope_id") != SCOPE_ID:
            scope_drift.append(expected_id)
        if row.get("denominator_included") is not True:
            denominator_drift.append(expected_id)
        trajectory = _mapping(row.get("trajectory"))
        collection_source_path = trajectory.get("path")
        collection_source_sha256 = trajectory.get("sha256")
        expected_source_path = _expected_source_path(row)
        expected_source_sha256 = collection_source_sha256
        if expected_id == EXPECTED_CASE_IDS[7]:
            proposal_target = _mapping(proposal.get("target"))
            expected_source_sha256 = proposal_target.get("source_sha256") or collection_source_sha256
        variant = _archive_variant(collection_source_path)
        if variant is not None:
            collection_variant_counts[variant] = collection_variant_counts.get(variant, 0) + 1
        source_rows.append(
            {
                "case_id": expected_id,
                "expected_split": expected_split,
                "collection_row_present": True,
                "collection_source_path": collection_source_path,
                "collection_source_sha256": collection_source_sha256,
                "expected_source_path": expected_source_path,
                "expected_source_sha256": expected_source_sha256,
                "archive_variant": variant,
                "source_path_exact": collection_source_path == expected_source_path,
                "source_sha256_exact": collection_source_sha256 == expected_source_sha256,
                "source_exact": collection_source_path == expected_source_path
                and collection_source_sha256 == expected_source_sha256,
            }
        )

    observed_split_counts: dict[str, int] = {}
    for row in rows:
        split = row.get("split")
        if isinstance(split, str):
            observed_split_counts[split] = observed_split_counts.get(split, 0) + 1

    collection_dev07 = _find_case(rows, EXPECTED_CASE_IDS[7])
    collection_dev07_trajectory = _mapping(_mapping(collection_dev07).get("trajectory"))
    proposal_target = _mapping(proposal.get("target"))
    proposal_scope = proposal_target.get("scope_id") == SCOPE_ID
    proposal_case = proposal_target.get("case_id") == EXPECTED_CASE_IDS[7]
    proposal_family = proposal_target.get("family") == FAMILY
    proposal_source_path = proposal_target.get("source_hdf5")
    proposal_source_sha256 = proposal_target.get("source_sha256")
    proposal_source_variant = _archive_variant(proposal_source_path)
    dev07_collection_source_path = collection_dev07_trajectory.get("path")
    dev07_collection_source_sha256 = collection_dev07_trajectory.get("sha256")

    reader_manifest_path = reader.get("manifest")
    reader_manifest_sha256 = reader.get("manifest_sha256")
    current_manifest_sha256 = collection_manifest_sha256 or "<not-bound-in-memory>"
    reader_path_exact = reader_manifest_path == COLLECTION_MANIFEST.as_posix()
    reader_sha_exact = reader_manifest_sha256 == current_manifest_sha256

    archives_binding = _mapping(consistency_audit.get("archives_path_binding"))
    consistency_archives_exact = archives_binding.get("exact_path_match") is True
    consistency_source_sha_exact = archives_binding.get("source_sha256_match") is True
    terminal_fresh_ref = _mapping(
        _mapping(terminal_intake.get("fresh_attempt_contract")).get("terminal_evidence_ref")
    )
    terminal_fresh_present = terminal_fresh_ref.get("exists") is True

    sidecar_by_id, malformed_sidecars = _sidecar_entries(sidecars)
    extra_sidecar_ids = sorted(set(sidecar_by_id) - set(EXPECTED_CASE_IDS))
    duplicate_sidecar_ids = sorted(
        case_id for case_id, entries in sidecar_by_id.items() if len(entries) > 1
    )

    case_reports: list[dict[str, Any]] = []
    for index, case_id in enumerate(EXPECTED_CASE_IDS):
        expected_split = EXPECTED_CASE_SPLITS[case_id]
        source_row = source_rows[index]
        entries = sidecar_by_id.get(case_id, [])
        if len(entries) != 1:
            reasons = []
            if not entries:
                reasons.append("missing_material_sidecar")
            else:
                reasons.append("duplicate_material_sidecar")
            if not source_row["source_exact"]:
                reasons.append("wrong_or_drifted_source")
            case_reports.append(
                {
                    "matrix_index": index,
                    "case_id": case_id,
                    "split": expected_split,
                    "status": "missing" if not entries else "blocked",
                    "terminal_status": "missing" if not entries else "duplicate",
                    "terminal_complete": False,
                    "event_window_complete": False,
                    "material_markers": {
                        "mass_closure_error": None,
                        "mass_closure_pass": False,
                        "unknown_fraction_max": None,
                        "unknown_fraction_pass": False,
                        "reliable_coverage": None,
                        "reliable_coverage_pass": False,
                        "right_censor_status": "unknown" if not entries else "duplicate",
                        "right_censor_pass": False,
                    },
                    "source": {
                        "hdf5": source_row["collection_source_path"],
                        "sha256": source_row["collection_source_sha256"],
                        "expected_hdf5": source_row["expected_source_path"],
                        "expected_sha256": source_row["expected_source_sha256"],
                    },
                    "fresh_output_namespace": f"{output_namespace}/{case_id}",
                    "formal_or_credit_claims": {},
                    "blocking_reasons": sorted(set(reasons)),
                    "checks": [],
                    "credit": 0,
                }
            )
            continue
        case_reports.append(
            _evaluate_one_sidecar(
                entries[0],
                expected_case_id=case_id,
                expected_split=expected_split,
                expected_source_path=source_row["expected_source_path"],
                expected_source_sha256=source_row["expected_source_sha256"],
                output_namespace=f"{output_namespace}/{case_id}",
            )
            | {"matrix_index": index}
        )

    sidecar_missing_ids = [
        case_id for case_id in EXPECTED_CASE_IDS if not sidecar_by_id.get(case_id)
    ]
    complete_sidecar_count = sum(row["status"] == "complete" for row in case_reports)
    full_event_window_count = sum(row["event_window_complete"] for row in case_reports)
    mass_closed_count = sum(row["material_markers"]["mass_closure_pass"] for row in case_reports)
    unknown_pass_count = sum(row["material_markers"]["unknown_fraction_pass"] for row in case_reports)
    reliable_coverage_pass_count = sum(
        row["material_markers"]["reliable_coverage_pass"] for row in case_reports
    )
    right_censor_pass_count = sum(row["material_markers"]["right_censor_pass"] for row in case_reports)

    checks = [
        _check(
            "fixed_32_case_denominator",
            manifest_case_identity_pass,
            "collection case IDs must be exactly the fixed 32-case matrix",
            observed={
                "row_count": len(rows),
                "missing_case_ids": missing_manifest_ids,
                "extra_case_ids": extra_manifest_ids,
                "duplicate_case_ids": manifest_duplicates,
            },
            expected={"case_count": EXPECTED_CASE_COUNT, "case_ids": list(EXPECTED_CASE_IDS)},
        ),
        _check(
            "fixed_split_matrix",
            not split_drift and observed_split_counts == EXPECTED_SPLIT_COUNTS,
            "case splits must match the fixed train/validation/id_test/ood_test matrix",
            observed={"counts": observed_split_counts, "drift": split_drift},
            expected=EXPECTED_SPLIT_COUNTS,
        ),
        _check(
            "f4_scope_binding",
            collection.get("schema") == COLLECTION_SCHEMA
            and collection.get("family") == FAMILY
            and collection.get("scope_id") == SCOPE_ID
            and not scope_drift
            and not family_drift,
            "collection schema, family, scope, and case rows must bind F4 Tallwall120",
            observed={
                "schema": collection.get("schema"),
                "family": collection.get("family"),
                "scope_id": collection.get("scope_id"),
                "scope_drift": scope_drift,
                "family_drift": family_drift,
            },
            expected={"schema": COLLECTION_SCHEMA, "family": FAMILY, "scope_id": SCOPE_ID},
        ),
        _check(
            "collection_denominator_flags",
            not denominator_drift,
            "every fixed case must remain in the declared collection denominator",
            observed=denominator_drift,
            expected=[],
        ),
        _check(
            "archives_v2_source_matrix",
            all(row["source_exact"] for row in source_rows),
            "material sidecars must bind archives-v2 paths and source SHA values",
            observed={
                "collection_archive_variants": collection_variant_counts,
                "source_drift_case_count": sum(not row["source_exact"] for row in source_rows),
            },
            expected={"archive_variant": EXPECTED_ARCHIVE_VARIANT, "case_count": EXPECTED_CASE_COUNT},
        ),
        _check(
            "dev07_proposal_source_binding",
            proposal_scope
            and proposal_case
            and proposal_family
            and proposal_source_variant == EXPECTED_ARCHIVE_VARIANT
            and dev07_collection_source_path == proposal_source_path
            and dev07_collection_source_sha256 == proposal_source_sha256,
            "DEV_07 proposal source, collection source, scope, and SHA must agree",
            observed={
                "proposal": {
                    "case_id": proposal_target.get("case_id"),
                    "family": proposal_target.get("family"),
                    "scope_id": proposal_target.get("scope_id"),
                    "source_hdf5": proposal_source_path,
                    "source_sha256": proposal_source_sha256,
                },
                "collection": {
                    "source_hdf5": dev07_collection_source_path,
                    "source_sha256": dev07_collection_source_sha256,
                },
            },
            expected={
                "case_id": EXPECTED_CASE_IDS[7],
                "family": FAMILY,
                "scope_id": SCOPE_ID,
                "archive_variant": EXPECTED_ARCHIVE_VARIANT,
            },
        ),
        _check(
            "reader_manifest_path_binding",
            reader_path_exact,
            "reader smoke must name the frozen collection manifest path",
            observed=reader_manifest_path,
            expected=COLLECTION_MANIFEST.as_posix(),
        ),
        _check(
            "reader_manifest_sha_binding",
            reader_sha_exact,
            "reader smoke manifest SHA must match the current manifest",
            observed=reader_manifest_sha256,
            expected=current_manifest_sha256,
        ),
        _check(
            "archives_path_consistency_audit",
            consistency_archives_exact and consistency_source_sha_exact,
            "receipt consistency must not report archives-v1/v2 or source drift",
            observed={
                "exact_path_match": archives_binding.get("exact_path_match"),
                "source_sha256_match": archives_binding.get("source_sha256_match"),
                "mismatch_class": archives_binding.get("mismatch_class"),
            },
            expected={"exact_path_match": True, "source_sha256_match": True},
        ),
        _check(
            "fresh_matrix_namespace",
            not Path(output_namespace).exists(),
            "the matrix namespace is proposal-only and must be fresh before execution",
            observed={"namespace": output_namespace, "exists": Path(output_namespace).exists()},
            expected={"exists": False},
        ),
        _check(
            "complete_material_sidecar_matrix",
            complete_sidecar_count == EXPECTED_CASE_COUNT,
            "all 32 cases require one complete material sidecar before any promotion",
            observed={
                "complete_sidecar_count": complete_sidecar_count,
                "missing_case_ids": sidecar_missing_ids,
                "duplicate_case_ids": duplicate_sidecar_ids,
                "extra_case_ids": extra_sidecar_ids,
                "malformed_sidecars": malformed_sidecars,
            },
            expected={"complete_sidecar_count": EXPECTED_CASE_COUNT},
        ),
        _check(
            "full_event_window_markers",
            full_event_window_count == EXPECTED_CASE_COUNT
            and mass_closed_count == EXPECTED_CASE_COUNT
            and unknown_pass_count == EXPECTED_CASE_COUNT
            and reliable_coverage_pass_count == EXPECTED_CASE_COUNT
            and right_censor_pass_count == EXPECTED_CASE_COUNT,
            "every sidecar must carry full event-window material markers",
            observed={
                "full_event_window_count": full_event_window_count,
                "mass_closed_count": mass_closed_count,
                "unknown_pass_count": unknown_pass_count,
                "reliable_coverage_pass_count": reliable_coverage_pass_count,
                "right_censor_pass_count": right_censor_pass_count,
            },
            expected={"case_count": EXPECTED_CASE_COUNT},
        ),
    ]

    blocking_reasons: list[str] = []
    for check in checks:
        if check["passed"]:
            continue
        name = str(check["check"])
        mapping = {
            "fixed_32_case_denominator": "missing_or_duplicate_cases",
            "fixed_split_matrix": "split_drift",
            "f4_scope_binding": "wrong_scope_or_family",
            "collection_denominator_flags": "collection_denominator_drift",
            "archives_v2_source_matrix": "archives_v1_v2_source_drift",
            "dev07_proposal_source_binding": "dev07_wrong_source",
            "reader_manifest_path_binding": "reader_manifest_path_drift",
            "reader_manifest_sha_binding": "reader_manifest_sha_drift",
            "archives_path_consistency_audit": "archives_v1_v2_receipt_drift",
            "fresh_matrix_namespace": "fresh_namespace_not_available",
            "complete_material_sidecar_matrix": "missing_or_incomplete_material_sidecars",
            "full_event_window_markers": "missing_required_material_markers",
        }
        blocking_reasons.append(mapping.get(name, name))
    for row in case_reports:
        blocking_reasons.extend(row.get("blocking_reasons", []))
    blocking_reasons = sorted(set(blocking_reasons))

    matrix_ready = not blocking_reasons
    status = "matrix_contract_ready_non_authorizing" if matrix_ready else "blocked_fail_closed"
    bridge_projection = {
        "status": acceptance_bridge.get("status"),
        "T2_macro": acceptance_bridge.get("T2_macro"),
        "T2_path": acceptance_bridge.get("T2_path"),
        "credit": acceptance_bridge.get("credit"),
        "material_matrix_ready": _mapping(acceptance_bridge.get("matrix_summary")).get(
            "material_matrix_ready"
        ),
        "formal_acceptance_receipt_count": _mapping(
            acceptance_bridge.get("matrix_summary")
        ).get("formal_acceptance_receipt_count"),
    }

    return {
        "schema": SCHEMA,
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": status,
        "decision": "diagnostic_proposal_contract_only",
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "collection_schema": collection.get("schema"),
            "case_count": EXPECTED_CASE_COUNT,
            "focus": "F4 Tallwall120 material sidecar matrix coarse-to-fine interface",
        },
        "fixed_matrix": {
            "case_count": EXPECTED_CASE_COUNT,
            "case_ids": list(EXPECTED_CASE_IDS),
            "case_splits": EXPECTED_CASE_SPLITS,
            "split_counts": EXPECTED_SPLIT_COUNTS,
            "archive_variant_required": EXPECTED_ARCHIVE_VARIANT,
            "sidecar_schema": MATERIAL_SIDECAR_SCHEMA,
        },
        "required_material_markers": {
            "full_event_window_s": EXPECTED_EVENT_WINDOW_S,
            "mass_closure_error_max": EXPECTED_MASS_CLOSURE_ERROR_MAX,
            "unknown_fraction_max": EXPECTED_UNKNOWN_FRACTION_MAX,
            "reliable_coverage_min": EXPECTED_RELIABLE_COVERAGE_MIN,
            "right_censor_status_required": EXPECTED_RIGHT_CENSOR_STATUS,
            "right_censored_or_unresolved_is_acceptance_failure": True,
            "partial_terminal_is_acceptance_failure": True,
            "no_event_imputation_or_partial_credit": True,
        },
        "source_binding": {
            "collection_manifest": {
                "path": COLLECTION_MANIFEST.as_posix(),
                "sha256": collection_manifest_sha256,
                "schema": collection.get("schema"),
            },
            "collection_archive_variants": collection_variant_counts,
            "source_matrix": source_rows,
            "dev07": {
                "proposal_source_hdf5": proposal_source_path,
                "proposal_source_sha256": proposal_source_sha256,
                "proposal_archive_variant": proposal_source_variant,
                "collection_source_hdf5": dev07_collection_source_path,
                "collection_source_sha256": dev07_collection_source_sha256,
                "archives_v1_v2_drift": dev07_collection_source_path != proposal_source_path,
                "source_sha256_match": dev07_collection_source_sha256 == proposal_source_sha256,
            },
            "reader": {
                "manifest_path": reader_manifest_path,
                "recorded_manifest_sha256": reader_manifest_sha256,
                "current_manifest_sha256": current_manifest_sha256,
                "path_exact": reader_path_exact,
                "sha256_exact": reader_sha_exact,
                "trusted_formal_eligible": _mapping(reader.get("reader_result")).get(
                    "formal_eligible"
                ),
            },
            "receipt_consistency": {
                "archives_path_exact": consistency_archives_exact,
                "source_sha256_exact": consistency_source_sha_exact,
                "mismatch_class": archives_binding.get("mismatch_class"),
            },
        },
        "fresh_output_namespace": {
            "namespace": output_namespace,
            "case_namespaces": [f"{output_namespace}/{case_id}" for case_id in EXPECTED_CASE_IDS],
            "exists": Path(output_namespace).exists(),
            "overwrite_allowed": False,
            "historical_trace_reuse": False,
            "execution_authorized": False,
            "solver_worker_gpu_queue_started": False,
        },
        "dev07_refs": {
            "source": {
                "proposal_target": proposal_source_path,
                "proposal_sha256": proposal_source_sha256,
                "collection_trajectory": dev07_collection_source_path,
                "collection_sha256": dev07_collection_source_sha256,
                "hdf5_content_read": False,
                "hdf5_hash_recomputed": False,
            },
            "reader": {
                "path": READER_SMOKE_REPORT.as_posix(),
                "manifest_path": reader_manifest_path,
                "manifest_sha256": reader_manifest_sha256,
            },
            "proposal": {
                "path": PROPOSAL_REPORT.as_posix(),
                "schema": proposal.get("schema"),
                "status": proposal.get("status"),
            },
            "terminal_intake": {
                "path": TERMINAL_INTAKE_REPORT.as_posix(),
                "status": terminal_intake.get("status"),
                "fresh_terminal_present": terminal_fresh_present,
            },
        },
        "material_sidecars": {
            "sidecar_count_supplied": sum(len(value) for value in sidecar_by_id.values()),
            "missing_case_ids": sidecar_missing_ids,
            "duplicate_case_ids": duplicate_sidecar_ids,
            "extra_case_ids": extra_sidecar_ids,
            "malformed_sidecars": malformed_sidecars,
            "cases": case_reports,
        },
        "matrix_summary": {
            "expected_case_count": EXPECTED_CASE_COUNT,
            "observed_collection_case_count": len(rows),
            "observed_sidecar_count": sum(len(value) for value in sidecar_by_id.values()),
            "complete_sidecar_count": complete_sidecar_count,
            "full_event_window_complete_count": full_event_window_count,
            "mass_closed_count": mass_closed_count,
            "unknown_fraction_pass_count": unknown_pass_count,
            "reliable_coverage_pass_count": reliable_coverage_pass_count,
            "right_censor_clear_count": right_censor_pass_count,
            "split_counts_expected": EXPECTED_SPLIT_COUNTS,
            "split_counts_observed": observed_split_counts,
            "denominator_complete": manifest_case_identity_pass and not denominator_drift,
            "matrix_ready": matrix_ready,
            "formal_acceptance_receipt_count": 0,
            "qualification_credit": 0,
        },
        "checks": checks,
        "blocking_reasons": blocking_reasons,
        "upstream_acceptance_bridge_projection": bridge_projection,
        "qualification": {
            "diagnostic_only": True,
            "proposal_only": True,
            "contract_only": True,
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1": False,
            "T2": False,
            "T2_macro": False,
            "T2_path": False,
            "credit": 0,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "execution_controls": {
            "static_only": True,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_started": False,
            "queue_mutation": 0,
            "production_hdf5_opened": False,
            "production_hdf5_content_read": False,
            "production_hdf5_hash_recomputed": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "small_file_metadata_only": True,
            "production_hdf5_metadata_only": True,
            "production_hdf5_opened": False,
            "production_hdf5_content_read": False,
            "production_hdf5_hash_recomputed": False,
            "solver_worker_gpu_queue_started": False,
        },
    }


def load_inputs(root: Path = LAB_ROOT) -> dict[str, dict[str, Any]]:
    """Load only the bounded JSON inputs used by the contract."""

    return {
        "collection": _read_json(root, COLLECTION_MANIFEST),
        "reader": _read_json(root, READER_SMOKE_REPORT),
        "proposal": _read_json(root, PROPOSAL_REPORT),
        "consistency_audit": _read_json(root, CONSISTENCY_AUDIT_REPORT),
        "terminal_intake": _read_json(root, TERMINAL_INTAKE_REPORT),
        "acceptance_bridge": _read_json(root, T2_ACCEPTANCE_BRIDGE),
    }


def build_report(root: Path = LAB_ROOT) -> dict[str, Any]:
    """Build the deterministic current-state report from bounded JSON inputs."""

    root = Path(root)
    inputs = load_inputs(root)
    manifest_binding = _small_file_binding(root, COLLECTION_MANIFEST, "F4 collection manifest")
    report = evaluate_matrix(
        inputs["collection"],
        inputs["proposal"],
        inputs["reader"],
        inputs["consistency_audit"],
        inputs["terminal_intake"],
        inputs["acceptance_bridge"],
        sidecars=None,
        output_namespace=DEFAULT_OUTPUT_NAMESPACE.as_posix(),
        collection_manifest_sha256=manifest_binding["sha256"],
    )
    proposal_target = _mapping(inputs["proposal"].get("target"))
    dev07_row = _find_case(_manifest_case_rows(inputs["collection"]), EXPECTED_CASE_IDS[7])
    dev07_trajectory = _mapping(_mapping(dev07_row).get("trajectory"))
    report["input_bindings"] = {
        name: _small_file_binding(root, path, name.replace("_", " "))
        for name, path in INPUT_REFS.items()
    }
    report["dev07_refs"]["source"]["proposal_hdf5_metadata"] = _hdf5_metadata(
        root, proposal_target.get("source_hdf5"), proposal_target.get("source_sha256")
    )
    report["dev07_refs"]["source"]["collection_hdf5_metadata"] = _hdf5_metadata(
        root, dev07_trajectory.get("path"), dev07_trajectory.get("sha256")
    )
    report["report_contract"] = {
        "builder": "scripts/f4_tallwall120_material_sidecar_matrix_contract_v1.py",
        "report_is_recomputed_from_bounded_json": True,
        "report_self_binding": False,
        "exact_build_report_binding_required": True,
    }
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Return invariant violations; this never promotes a report."""

    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    matrix = _mapping(report.get("fixed_matrix"))
    if matrix.get("case_count") != EXPECTED_CASE_COUNT:
        errors.append("fixed_matrix.case_count")
    if matrix.get("case_ids") != list(EXPECTED_CASE_IDS):
        errors.append("fixed_matrix.case_ids")
    if matrix.get("case_splits") != EXPECTED_CASE_SPLITS:
        errors.append("fixed_matrix.case_splits")
    if matrix.get("split_counts") != EXPECTED_SPLIT_COUNTS:
        errors.append("fixed_matrix.split_counts")
    qualification = _mapping(report.get("qualification"))
    for key in (
        "formal",
        "formal_eligible",
        "qualification",
        "T1",
        "T2",
        "T2_macro",
        "T2_path",
    ):
        if qualification.get(key) is not False:
            errors.append(f"qualification.{key}")
    for key in ("credit", "qualification_credit", "registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation", "completion_mutation"):
        if qualification.get(key) != 0:
            errors.append(f"qualification.{key}")
    if report.get("decision") != "diagnostic_proposal_contract_only":
        errors.append("decision")
    for row in _list(_mapping(report.get("material_sidecars")).get("cases")):
        if not isinstance(row, Mapping):
            errors.append("material_sidecars.cases.type")
            continue
        if row.get("credit") != 0:
            errors.append(f"case_credit:{row.get('case_id')}")
    boundary = _mapping(report.get("input_boundary"))
    for key in (
        "production_hdf5_opened",
        "production_hdf5_content_read",
        "production_hdf5_hash_recomputed",
        "solver_worker_gpu_queue_started",
    ):
        if boundary.get(key) is not False:
            errors.append(f"input_boundary.{key}")
    return errors


def verify_report(report_path: Path = DEFAULT_REPORT, root: Path = LAB_ROOT) -> dict[str, Any]:
    """Verify exact deterministic report binding and fail-closed invariants."""

    report_path = _resolve(Path(root), report_path)
    actual = _read_json(Path(root), report_path)
    errors = validate_report(actual)
    if errors:
        raise ValueError("report invariant violations: " + ", ".join(errors))
    expected = build_report(Path(root))
    if actual != expected:
        raise ValueError("report does not exactly equal build_report()")
    return actual


def write_report(output: Path = DEFAULT_REPORT, root: Path = LAB_ROOT) -> dict[str, Any]:
    output = _resolve(Path(root), output)
    report = build_report(Path(root))
    errors = validate_report(report)
    if errors:
        raise ValueError("refusing to write invalid report: " + ", ".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = write_report(args.output, args.root)
    print(
        json.dumps(
            {
                "output": _relative(args.root, _resolve(args.root, args.output)),
                "status": report["status"],
                "blocking_reasons": report["blocking_reasons"],
                "case_count": report["matrix_summary"]["expected_case_count"],
                "credit": report["qualification"]["credit"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
