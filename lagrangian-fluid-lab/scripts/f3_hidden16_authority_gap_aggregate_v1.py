#!/usr/bin/env python3
"""Aggregate the nine current F3 hidden16 authority-gap projections.

This is an additive, read-only verifier for the current model x seed matrix:
``graph_raw``, ``graph_residual`` and ``mlp`` crossed with seeds 17, 29 and
43.  It reads exactly the nine explicitly named gap JSON reports, with a
bounded descriptor-stable read.  It does not inspect a manifest, checkpoint,
trajectory, HDF5 file, scheduler database or production output.

The input reports are heterogeneous historical/current gap contracts.  The
aggregate therefore binds identity from both ``schema`` and ``report_id`` and
uses ``scope`` only when it is present.  It verifies complete unique coverage,
the shared zero-credit boundary, and the absence of launch/process markers.
The aggregate is itself diagnostic and fail-closed; it is not a training
matrix, admission receipt, scheduler authority, terminal receipt or Core gate.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = LAB_ROOT / "reports"

MODEL_ORDER = ("graph_raw", "graph_residual", "mlp")
SEED_ORDER = (17, 29, 43)
EXPECTED_KEYS = tuple((model, seed) for model in MODEL_ORDER for seed in SEED_ORDER)
EXPECTED_KEY_INDEX = {key: index for index, key in enumerate(EXPECTED_KEYS)}

EXPECTED_INPUTS: dict[tuple[str, int], Path] = {
    ("graph_raw", 17): REPORTS_ROOT
    / "F3-GRAPH-RAW-HIDDEN16-SEED17-AUTHORITY-PROJECTION-GAP-RERUN1-2026-09-29.json",
    ("graph_raw", 29): REPORTS_ROOT
    / "F3-GRAPH-RAW-HIDDEN16-SEED29-AUTHORITY-PROJECTION-GAP-RERUN1-2026-09-29.json",
    ("graph_raw", 43): REPORTS_ROOT
    / "F3-GRAPH-RAW-HIDDEN16-SEED43-AUTHORITY-BOUND-DIAGNOSTIC-ADMISSION-GAP-AUDIT-2026-09-29.json",
    ("graph_residual", 17): REPORTS_ROOT
    / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED17-AUTHORITY-PROJECTION-GAP-2026-09-29.json",
    ("graph_residual", 29): REPORTS_ROOT
    / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED29-AUTHORITY-PROJECTION-GAP-2026-09-29.json",
    ("graph_residual", 43): REPORTS_ROOT
    / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED43-AUTHORITY-PROJECTION-GAP-2026-09-29.json",
    ("mlp", 17): REPORTS_ROOT
    / "F3-MLP-HIDDEN16-SEED17-AUTHORITY-PROJECTION-GAP-2026-09-29.json",
    ("mlp", 29): REPORTS_ROOT
    / "F3-MLP-HIDDEN16-SEED29-AUTHORITY-PROJECTION-GAP-2026-09-29.json",
    ("mlp", 43): REPORTS_ROOT
    / "F3-MLP-HIDDEN16-SEED43-AUTHORITY-PROJECTION-GAP-2026-09-29.json",
}
EXPECTED_BASENAMES = {path.name: key for key, path in EXPECTED_INPUTS.items()}

SCHEMA = "core.f3.hidden16.authority_gap_aggregate.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-hidden16-authority-gap-aggregate-2026-09-29"
DEFAULT_REPORT = REPORTS_ROOT / "F3-HIDDEN16-AUTHORITY-GAP-AGGREGATE-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_REPORT_BYTES = 2 * 1024 * 1024
ALLOWED_INPUT_STATUSES = frozenset({"blocked_projection_gap", "blocked_fail_closed"})

ZERO_CREDIT_FIELDS: dict[str, Any] = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}

LAUNCH_BOOLEAN_KEYS = frozenset(
    {
        "launch_allowed",
        "popen_allowed",
        "runner_consumable",
        "worker_launch_authorized",
    }
)
LAUNCH_ZERO_KEYS = frozenset(
    {
        "popen_attempted",
        "popen_attempts",
        "processes_started",
        "processes_stopped",
        "processes_restarted",
        "worker_started",
        "worker_attempts",
        "solver_started",
        "solver_attempts",
        "gpu_execution_started",
        "gpu_execution_observed",
        "gpu_probes",
        "queue_submissions",
        "queue_submitted",
        "wait_attempted",
        "wait_attempts",
        "real_workload_started",
        "runtime_started",
    }
)


class AggregateError(ValueError):
    """Malformed input or a fail-closed aggregate contract violation."""


def _fail(message: str) -> None:
    raise AggregateError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _absolute_lexical(path: Path | str, name: str) -> Path:
    candidate = Path(os.fspath(path))
    if not candidate.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a lexical alias")
    if Path(os.path.normpath(str(candidate))) != candidate:
        _fail(f"{name} is not normalized")
    return candidate


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_uid),
        int(info.st_gid),
        int(info.st_nlink),
        int(info.st_size),
    )


def _read_bounded_json(path: Path | str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one report without following links and with stable file identity."""

    candidate = _absolute_lexical(path, name)
    try:
        before = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(before.st_mode):
        _fail(f"{name} must not be a symlink")
    if not stat.S_ISREG(before.st_mode):
        _fail(f"{name} must be a regular file")
    if before.st_nlink != 1:
        _fail(f"{name} must have exactly one hard link")
    if before.st_size < 1 or before.st_size > MAX_REPORT_BYTES:
        _fail(f"{name} exceeds bounded size {MAX_REPORT_BYTES}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")

    chunks: list[bytes] = []
    try:
        opened = os.fstat(fd)
        if _file_identity(opened) != _file_identity(before):
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= MAX_REPORT_BYTES:
            block = os.read(fd, MAX_REPORT_BYTES + 1 - total)
            if not block:
                break
            chunks.append(block)
            total += len(block)
        if total > MAX_REPORT_BYTES:
            _fail(f"{name} grew beyond bounded size {MAX_REPORT_BYTES}")
        closed = os.fstat(fd)
        if _file_identity(closed) != _file_identity(before):
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)

    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    raw = b"".join(chunks)
    if _file_identity(after) != _file_identity(before) or len(raw) != before.st_size:
        _fail(f"{name} changed after bounded read")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, AggregateError) as error:
        _fail(f"{name} is not strict bounded JSON: {error}")
    if not isinstance(payload, Mapping):
        _fail(f"{name} must contain a JSON object")
    descriptor = {
        "path": str(candidate),
        "basename": candidate.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "uid": int(before.st_uid),
        "gid": int(before.st_gid),
        "nlink": int(before.st_nlink),
    }
    return dict(payload), descriptor


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{name} must be a non-empty string")
    return value


def _identity_from_schema_and_id(report: Mapping[str, Any], name: str) -> tuple[str, int]:
    schema = _string(report.get("schema"), f"{name}.schema")
    report_id = _string(report.get("report_id"), f"{name}.report_id")
    schema_match = re.fullmatch(
        r"core\.f3\.(graph_raw|graph_residual|mlp)\.hidden16\.seed(17|29|43)\..+\.report",
        schema,
    )
    if schema_match is None:
        _fail(f"{name}.schema is not a hidden16 model×seed report schema")
    schema_key = (schema_match.group(1), int(schema_match.group(2)))
    report_id_match = re.fullmatch(
        r"f3-(graph-raw|graph-residual|mlp)-hidden16-seed(17|29|43)-.+",
        report_id,
    )
    if report_id_match is None:
        _fail(f"{name}.report_id is not a hidden16 model×seed report id")
    report_model = {
        "graph-raw": "graph_raw",
        "graph-residual": "graph_residual",
        "mlp": "mlp",
    }[report_id_match.group(1)]
    report_key = (report_model, int(report_id_match.group(2)))
    if schema_key != report_key:
        _fail(f"{name} schema/report_id identity mismatch")
    return schema_key


def _validate_optional_identity(report: Mapping[str, Any], expected: tuple[str, int], name: str) -> None:
    model, seed = expected
    for key, expected_value in (
        ("model_kind", model),
        ("model", model),
        ("seed", seed),
        ("hidden", 16),
    ):
        if key in report:
            _exact(report, key, expected_value, name)
    scope_value = report.get("scope")
    if scope_value is None:
        return
    scope = _mapping(scope_value, f"{name}.scope")
    for key, expected_value in (
        ("model_kind", model),
        ("model", model),
        ("seed", seed),
        ("hidden", 16),
        ("updates", 500),
    ):
        if key in scope:
            _exact(scope, key, expected_value, f"{name}.scope")


def _is_zero(value: Any) -> bool:
    return value is False or (type(value) is int and value == 0)


def _walk_key_values(value: Any) -> Sequence[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                found.append((key, child))
            found.extend(_walk_key_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_key_values(child))
    return found


def _validate_launch_denial(report: Mapping[str, Any], name: str) -> None:
    projection_value = report.get("projection_contract")
    if isinstance(projection_value, Mapping):
        projection = projection_value
        _exact(projection, "popen_allowed", False, f"{name}.projection_contract")
        _exact(projection, "runner_consumable", False, f"{name}.projection_contract")
        _exact(projection, "durable_receipt_written", False, f"{name}.projection_contract")
        _exact(projection, "historical_receipt_rewritten", False, f"{name}.projection_contract")
    else:
        # The raw seed43 audit predates the projection-contract envelope.  Its
        # readiness object is the explicit launch boundary and its static
        # implementation coverage confirms that no process-launch surface was
        # exercised.
        readiness = _mapping(report.get("readiness"), f"{name}.readiness")
        _exact(readiness, "launch_allowed", False, f"{name}.readiness")
        _exact(readiness, "popen_attempted", False, f"{name}.readiness")
        coverage = _mapping(
            report.get("implementation_coverage"),
            f"{name}.implementation_coverage",
        )
        _exact(
            coverage,
            "admission_module_has_no_process_launch_surface",
            True,
            f"{name}.implementation_coverage",
        )

    external_value = report.get("external_authority")
    if isinstance(external_value, Mapping):
        _exact(external_value, "verified", False, f"{name}.external_authority")
    else:
        observation = _mapping(
            report.get("production_observation"),
            f"{name}.production_observation",
        )
        _exact(
            observation,
            "production_authority_verified",
            False,
            f"{name}.production_observation",
        )

    markers = _walk_key_values(report)
    observed_popen_marker = False
    for key, value in markers:
        if key in LAUNCH_BOOLEAN_KEYS:
            if value is not False:
                _fail(f"{name}.{key} is not false")
            if key in {"launch_allowed", "popen_allowed", "runner_consumable"}:
                observed_popen_marker = True
        elif key in LAUNCH_ZERO_KEYS:
            if not _is_zero(value):
                _fail(f"{name}.{key} is not zero")
            if key in {"popen_attempted", "popen_attempts"}:
                observed_popen_marker = True
    if not observed_popen_marker:
        _fail(f"{name} has no explicit launch/Popen denial marker")


def _validate_zero_credit_boundary(report: Mapping[str, Any], name: str) -> int:
    """Validate common fields, or the narrower audit-readiness projection."""

    missing_common: list[str] = []
    for key, expected in ZERO_CREDIT_FIELDS.items():
        if key in report:
            _exact(report, key, expected, name)
        else:
            missing_common.append(key)

    if not missing_common:
        return int(report["credit"])

    # The raw/MLP seed43 audit reports intentionally scope their readiness
    # projection to diagnostic/formal/credit and do not repeat the wider
    # training qualification fields.  Their projection contract must still
    # explicitly deny formal promotion; missing fields are not treated as
    # positive claims.
    readiness = _mapping(report.get("readiness"), f"{name}.readiness")
    _exact(readiness, "diagnostic_only", True, f"{name}.readiness")
    _exact(readiness, "formal", False, f"{name}.readiness")
    _exact(readiness, "credit", 0, f"{name}.readiness")
    projection_value = report.get("projection_contract")
    if isinstance(projection_value, Mapping):
        projection = projection_value
        _exact(
            projection,
            "formal_promotion_allowed",
            False,
            f"{name}.projection_contract",
        )
    else:
        coverage = _mapping(
            report.get("implementation_coverage"),
            f"{name}.implementation_coverage",
        )
        _exact(
            coverage,
            "zero_credit_diagnostic_boundary",
            True,
            f"{name}.implementation_coverage",
        )
    if "credit" in report:
        return int(report["credit"])
    return int(readiness["credit"])


def _validate_input_report(
    report: Mapping[str, Any],
    expected: tuple[str, int],
    descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    name = str(descriptor["basename"])
    observed = _identity_from_schema_and_id(report, name)
    if observed != expected:
        _fail(f"{name} identity does not match its explicit matrix slot")
    _validate_optional_identity(report, expected, name)

    status = _string(report.get("status"), f"{name}.status")
    if status not in ALLOWED_INPUT_STATUSES:
        _fail(f"{name}.status is not fail-closed: {status!r}")
    source_credit = _validate_zero_credit_boundary(report, name)
    _validate_launch_denial(report, name)

    projection_value = report.get("projection_contract")
    projection = projection_value if isinstance(projection_value, Mapping) else {}
    external_value = report.get("external_authority")
    if isinstance(external_value, Mapping):
        authority_verified = bool(external_value["verified"])
    else:
        observation = _mapping(
            report["production_observation"],
            f"{name}.production_observation",
        )
        authority_verified = bool(observation["production_authority_verified"])
    return {
        "model_kind": expected[0],
        "seed": expected[1],
        "hidden": 16,
        "schema": str(report["schema"]),
        "report_id": str(report["report_id"]),
        "status": status,
        "source_report": dict(descriptor),
        "authority_verified": authority_verified,
        "zero_credit_verified": True,
        "launch_denied_verified": True,
        "runner_consumable": bool(projection.get("runner_consumable", False)),
        "credit": source_credit,
    }


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _aggregate_policy() -> dict[str, Any]:
    return {
        "read_only_input_reports": True,
        "explicit_input_count": len(EXPECTED_INPUTS),
        "max_report_bytes": MAX_REPORT_BYTES,
        "allowed_basenames": [EXPECTED_INPUTS[key].name for key in EXPECTED_KEYS],
        "bounded_json_parser": True,
        "rejects_symlink": True,
        "requires_single_hardlink": True,
        "production_manifest_opened": False,
        "production_checkpoint_opened": False,
        "production_trajectory_opened": False,
        "production_hdf5_opened": False,
        "scheduler_or_root_authority_read": False,
        "gpu_probe_performed": False,
        "queue_or_worker_started": False,
        "formal_matrix_or_gate_read": False,
        "formal_matrix_or_gate_written": False,
    }


def build_aggregate(
    paths: Sequence[Path | str] | None = None,
    *,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the fail-closed aggregate from exactly the nine named reports."""

    selected = tuple(DEFAULT_INPUTS if paths is None else paths)
    if len(selected) != len(EXPECTED_KEYS):
        _fail(f"exactly {len(EXPECTED_KEYS)} explicit gap reports are required")

    seen_basenames: set[str] = set()
    seen_paths: set[str] = set()
    records: list[dict[str, Any]] = []
    for index, path in enumerate(selected):
        candidate = _absolute_lexical(path, f"input[{index}]")
        canonical_path = str(candidate)
        if canonical_path in seen_paths:
            _fail(f"duplicate input path: {canonical_path}")
        seen_paths.add(canonical_path)
        expected = EXPECTED_BASENAMES.get(candidate.name)
        if expected is None:
            _fail(f"input[{index}] basename is not one of the nine explicit reports")
        if candidate.name in seen_basenames:
            _fail(f"duplicate explicit report basename: {candidate.name}")
        seen_basenames.add(candidate.name)
        report, descriptor = _read_bounded_json(candidate, f"input[{index}] {candidate.name}")
        records.append(_validate_input_report(report, expected, descriptor))

    observed_keys = {(record["model_kind"], record["seed"]) for record in records}
    if observed_keys != set(EXPECTED_KEYS):
        missing = [list(key) for key in EXPECTED_KEYS if key not in observed_keys]
        unexpected = [list(key) for key in observed_keys if key not in EXPECTED_KEY_INDEX]
        _fail(f"coverage is incomplete or unexpected: missing={missing}, unexpected={unexpected}")
    if len(observed_keys) != len(records):
        _fail("model×seed coverage is not unique")
    records.sort(key=lambda item: EXPECTED_KEY_INDEX[(item["model_kind"], item["seed"])])

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc or _now_utc(),
        "status": "blocked_fail_closed",
        "fail_closed": True,
        "scope": {
            "family": "F3",
            "model_kinds": list(MODEL_ORDER),
            "seeds": list(SEED_ORDER),
            "hidden": 16,
            "expected_projection_count": len(EXPECTED_KEYS),
            "mode": "authority_gap_aggregate",
        },
        "coverage": {
            "expected_count": len(EXPECTED_KEYS),
            "observed_count": len(records),
            "complete_unique": True,
            "missing": [],
            "unexpected": [],
            "duplicate_model_seed": [],
        },
        "projections": records,
        "aggregate_verification": {
            "complete_unique_model_seed_coverage": True,
            "all_input_statuses_fail_closed": True,
            "all_zero_credit": True,
            "all_launch_denied": True,
            "all_external_authority_unverified": True,
            "no_projection_is_runner_consumable": True,
        },
        "zero_credit": dict(ZERO_CREDIT_FIELDS),
        "launch_boundary": {
            "launch_allowed": False,
            "popen_attempted": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_execution_started": False,
            "queue_submitted": False,
            "formal_state_mutation": False,
            "core_gate_mutation": False,
        },
        "side_effects": {
            "aggregate_reads_only_gap_reports": True,
            "popen_attempts": 0,
            "solver_attempts": 0,
            "worker_attempts": 0,
            "gpu_probes": 0,
            "queue_submissions": 0,
            "production_large_files_opened": 0,
            "formal_matrix_writes": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "completion_writes": 0,
            "gate_writes": 0,
            "PLAN_writes": 0,
        },
        "input_policy": _aggregate_policy(),
    }
    errors = validate_report(report)
    if errors:
        raise AggregateError("aggregate self-validation failed: " + "; ".join(errors))
    return report


def _iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Return contract errors without reading any additional file."""

    errors: list[str] = []

    def exact(container: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
        if key not in container:
            errors.append(f"{name}.{key} missing")
            return
        observed = container[key]
        if type(expected) is bool and type(observed) is not bool:
            errors.append(f"{name}.{key} must be boolean")
        elif type(expected) is int and type(observed) is not int:
            errors.append(f"{name}.{key} must be integer")
        elif observed != expected:
            errors.append(f"{name}.{key} != {expected!r}")

    if report.get("schema") != REPORT_SCHEMA:
        errors.append("schema drift")
    if report.get("report_id") != REPORT_ID:
        errors.append("report_id drift")
    if report.get("status") != "blocked_fail_closed":
        errors.append("aggregate must remain blocked_fail_closed")
    exact(report, "fail_closed", True, "aggregate")
    if not _iso_timestamp(report.get("observed_at_utc")):
        errors.append("observed_at_utc must be an ISO-8601 UTC timestamp")

    scope = report.get("scope")
    if not isinstance(scope, Mapping):
        errors.append("scope must be an object")
    else:
        exact(scope, "family", "F3", "scope")
        exact(scope, "model_kinds", list(MODEL_ORDER), "scope")
        exact(scope, "seeds", list(SEED_ORDER), "scope")
        exact(scope, "hidden", 16, "scope")
        exact(scope, "expected_projection_count", 9, "scope")
        exact(scope, "mode", "authority_gap_aggregate", "scope")

    coverage = report.get("coverage")
    if not isinstance(coverage, Mapping):
        errors.append("coverage must be an object")
    else:
        for key, expected in (
            ("expected_count", 9),
            ("observed_count", 9),
            ("complete_unique", True),
            ("missing", []),
            ("unexpected", []),
            ("duplicate_model_seed", []),
        ):
            exact(coverage, key, expected, "coverage")

    projections = report.get("projections")
    observed_keys: list[tuple[Any, Any]] = []
    if not isinstance(projections, list):
        errors.append("projections must be a list")
    else:
        if len(projections) != 9:
            errors.append("projections must contain nine records")
        for index, item in enumerate(projections):
            name = f"projections[{index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{name} must be an object")
                continue
            model = item.get("model_kind")
            seed = item.get("seed")
            observed_keys.append((model, seed))
            if (model, seed) not in EXPECTED_KEY_INDEX:
                errors.append(f"{name} has unexpected model×seed")
            for key, expected in (
                ("hidden", 16),
                ("status", None),
                ("authority_verified", False),
                ("zero_credit_verified", True),
                ("launch_denied_verified", True),
                ("runner_consumable", False),
                ("credit", 0),
            ):
                if key not in item:
                    errors.append(f"{name}.{key} missing")
                elif key == "status":
                    if item[key] not in ALLOWED_INPUT_STATUSES:
                        errors.append(f"{name}.status is not fail-closed")
                else:
                    exact(item, key, expected, name)
            source = item.get("source_report")
            if not isinstance(source, Mapping):
                errors.append(f"{name}.source_report must be an object")
            else:
                basename = source.get("basename")
                if basename not in EXPECTED_BASENAMES:
                    errors.append(f"{name}.source_report basename is not explicit")
                elif EXPECTED_BASENAMES[basename] != (model, seed):
                    errors.append(f"{name}.source_report identity mismatch")
                source_path = source.get("path")
                if not isinstance(source_path, str) or not Path(source_path).is_absolute():
                    errors.append(f"{name}.source_report path must be absolute")
                if type(source.get("bytes")) is not int or source["bytes"] < 1:
                    errors.append(f"{name}.source_report bytes invalid")
                digest = source.get("sha256")
                if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    errors.append(f"{name}.source_report sha256 invalid")
                exact(source, "nlink", 1, f"{name}.source_report")
        if len(set(observed_keys)) != len(observed_keys):
            errors.append("projections contain duplicate model×seed records")
        if set(observed_keys) != set(EXPECTED_KEYS):
            errors.append("projections do not cover exactly the nine model×seed slots")

    verification = report.get("aggregate_verification")
    if not isinstance(verification, Mapping):
        errors.append("aggregate_verification must be an object")
    else:
        for key in (
            "complete_unique_model_seed_coverage",
            "all_input_statuses_fail_closed",
            "all_zero_credit",
            "all_launch_denied",
            "all_external_authority_unverified",
            "no_projection_is_runner_consumable",
        ):
            exact(verification, key, True, "aggregate_verification")

    zero_credit = report.get("zero_credit")
    if not isinstance(zero_credit, Mapping):
        errors.append("zero_credit must be an object")
    else:
        for key, expected in ZERO_CREDIT_FIELDS.items():
            exact(zero_credit, key, expected, "zero_credit")

    launch = report.get("launch_boundary")
    if not isinstance(launch, Mapping):
        errors.append("launch_boundary must be an object")
    else:
        for key in (
            "launch_allowed",
            "popen_attempted",
            "solver_started",
            "worker_started",
            "gpu_execution_started",
            "queue_submitted",
            "formal_state_mutation",
            "core_gate_mutation",
        ):
            exact(launch, key, False, "launch_boundary")

    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping):
        errors.append("side_effects must be an object")
    else:
        exact(side_effects, "aggregate_reads_only_gap_reports", True, "side_effects")
        for key in (
            "popen_attempts",
            "solver_attempts",
            "worker_attempts",
            "gpu_probes",
            "queue_submissions",
            "production_large_files_opened",
            "formal_matrix_writes",
            "registry_writes",
            "ledger_writes",
            "denominator_writes",
            "completion_writes",
            "gate_writes",
            "PLAN_writes",
        ):
            exact(side_effects, key, 0, "side_effects")

    policy = report.get("input_policy")
    if not isinstance(policy, Mapping):
        errors.append("input_policy must be an object")
    else:
        for key, expected in (
            ("read_only_input_reports", True),
            ("explicit_input_count", 9),
            ("max_report_bytes", MAX_REPORT_BYTES),
            ("bounded_json_parser", True),
            ("rejects_symlink", True),
            ("requires_single_hardlink", True),
            ("production_manifest_opened", False),
            ("production_checkpoint_opened", False),
            ("production_trajectory_opened", False),
            ("production_hdf5_opened", False),
            ("scheduler_or_root_authority_read", False),
            ("gpu_probe_performed", False),
            ("queue_or_worker_started", False),
            ("formal_matrix_or_gate_read", False),
            ("formal_matrix_or_gate_written", False),
        ):
            exact(policy, key, expected, "input_policy")
        exact(policy, "allowed_basenames", [EXPECTED_INPUTS[key].name for key in EXPECTED_KEYS], "input_policy")

    return errors


def _markdown(report: Mapping[str, Any]) -> str:
    rows = [
        "| model | seed | input status | authority verified | zero credit | launch denied |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for item in report["projections"]:
        rows.append(
            "| `{model}` | `{seed}` | `{status}` | `{authority}` | `{credit}` | `{launch}` |".format(
                model=item["model_kind"],
                seed=item["seed"],
                status=item["status"],
                authority=item["authority_verified"],
                credit=item["credit"],
                launch=item["launch_denied_verified"],
            )
        )
    return "\n".join(
        [
            "# F3 hidden16 authority-gap aggregate",
            "",
            "这是九个 F3 hidden16 model×seed authority-gap JSON 的只读聚合验证结果。它只验证覆盖、fail-closed、zero-credit 与 launch denial，不授予 formal/T1/T2、training、scheduler authority 或 Core gate。",
            "",
            f"- status：`{report['status']}`；fail-closed：`{report['fail_closed']}`",
            f"- coverage：`{report['coverage']['observed_count']}/{report['coverage']['expected_count']}`，complete unique=`{report['coverage']['complete_unique']}`",
            "- aggregate credit：`0`；launch_allowed=`False`；Popen=`False`",
            "- 输入读取：仅九个显式 gap JSON，有界 strict JSON、拒绝 symlink、要求单 hardlink；未读取 production manifest/checkpoint/trajectory/HDF5、scheduler/root authority 或 GPU。",
            "",
            *rows,
            "",
            "所有九条入口仍缺真实 external scheduler authority、trusted root/key 或完整 authority-bound terminal evidence；本聚合不把 caller claim 变成可信 authority。",
            "",
        ]
    )


def write_reports(
    report: Mapping[str, Any],
    *,
    report_path: Path | str = DEFAULT_REPORT,
    markdown_path: Path | str = DEFAULT_MARKDOWN,
) -> None:
    errors = validate_report(report)
    if errors:
        raise AggregateError("cannot write invalid aggregate: " + "; ".join(errors))
    json_path = _absolute_lexical(report_path, "aggregate report output")
    md_path = _absolute_lexical(markdown_path, "aggregate markdown output")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        dest="inputs",
        help="one of the nine explicit gap JSON paths; repeat exactly nine times",
    )
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--markdown", default=str(DEFAULT_MARKDOWN))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = DEFAULT_INPUTS if args.inputs is None else tuple(Path(item) for item in args.inputs)
    report = build_aggregate(paths)
    write_reports(report, report_path=Path(args.report), markdown_path=Path(args.markdown))
    print(canonical_json(report))
    return 0


DEFAULT_INPUTS = tuple(EXPECTED_INPUTS[key] for key in EXPECTED_KEYS)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AggregateError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
