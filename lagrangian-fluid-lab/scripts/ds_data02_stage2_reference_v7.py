#!/usr/bin/env python3
"""Strict v7 reference comparison and explicit portable-source migration.

The v5/v6 evaluators remain immutable historical/development consumers.  This
module adds the checks needed before a reference result can be compared:
frozen config and source hashes, query-time identity, nested-array shapes,
fixed thresholds, separate time/output budgets, and source-region event keys.
It also supplies a small-file migration verifier.  A changed mtime is accepted
only after an explicit path-map migration record and a successful full hash;
same-size wrong content and an unbound path are rejected.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np

from ds_data02_stage2_observer_v6 import (  # noqa: E402
    OBSERVER_CONFIG_SCHEMA,
    ObserverBindingError,
    canonical_json,
    validate_observer_config,
)


STRICT_EVALUATION_SCHEMA = "ds02.stage2.manual-observation-evaluation.v7"
MIGRATION_SCHEMA = "ds02.stage2.portable-source-migration.v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ObserverBindingError(f"{name} must be finite")
    return float(value)


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ObserverBindingError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _array(value: Any, name: str) -> np.ndarray:
    if isinstance(value, (str, bytes, bool)):
        raise ObserverBindingError(f"{name} must be a numeric array")
    try:
        result = np.asarray(value, dtype="float64")
    except (TypeError, ValueError) as error:
        raise ObserverBindingError(f"{name} must be a numeric array") from error
    if result.ndim == 0 or not np.isfinite(result).all():
        raise ObserverBindingError(f"{name} must be finite and non-scalar")
    return result


def _shape(value: Any, name: str) -> tuple[int, ...]:
    return tuple(_array(value, name).shape)


def _exact_float_list(value: Any, name: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ObserverBindingError(f"{name} must be a numeric list")
    result = [_finite(item, f"{name}[{index}]") for index, item in enumerate(value)]
    if any(right < left for left, right in zip(result, result[1:])):
        raise ObserverBindingError(f"{name} must be nondecreasing")
    return result


def load_frozen_observer_config(path: Path | str, expected_sha256: str) -> dict[str, Any]:
    path = Path(path).resolve()
    expected = _digest(expected_sha256, "frozen_config_sha256")
    if not path.is_file() or sha256(path) != expected:
        raise ObserverBindingError("frozen observer config path or hash differs")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ObserverBindingError("frozen observer config is not valid JSON") from error
    validated = validate_observer_config(config)
    evaluator = validated.get("manual_evaluator")
    if not isinstance(evaluator, Mapping) or evaluator.get("schema") != "ds02.stage2.manual-observation-evaluator.v1":
        raise ObserverBindingError("frozen observer config has no strict manual evaluator profile")
    tolerances = evaluator.get("macro_total_tolerances")
    if not isinstance(tolerances, Mapping):
        raise ObserverBindingError("frozen evaluator macro_total_tolerances are required")
    for kind in ("position", "velocity", "kinetic_energy", "mass_fraction", "net_flux_fraction"):
        value = _finite(tolerances.get(kind), f"macro_total_tolerances.{kind}")
        if value <= 0:
            raise ObserverBindingError(f"macro_total_tolerances.{kind} must be positive")
    event_fraction = _finite(evaluator.get("event_time_total_fraction"), "event_time_total_fraction")
    budget = _finite(evaluator.get("budget_fraction"), "budget_fraction")
    if event_fraction <= 0 or not 0 < budget <= 0.25:
        raise ObserverBindingError("frozen evaluator event/budget thresholds are invalid")
    if evaluator.get("identity_binding") != "source_region_id":
        raise ObserverBindingError("frozen evaluator must use source_region_id event identity")
    return dict(validated, _frozen_config_sha256=expected, _frozen_config_path=str(path))


def _config_binding(bundle: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = bundle.get("config_binding")
    if not isinstance(value, Mapping):
        raise ObserverBindingError(f"{name}.config_binding is required")
    if not isinstance(value.get("path"), str):
        raise ObserverBindingError(f"{name}.config_binding.path is required")
    _digest(value.get("sha256"), f"{name}.config_binding.sha256")
    return value


def _source_bindings(bundle: Mapping[str, Any], name: str) -> dict[str, str]:
    value = bundle.get("bindings")
    if not isinstance(value, Mapping) or not value:
        raise ObserverBindingError(f"{name}.bindings is required")
    result = {str(key): _digest(raw, f"{name}.bindings.{key}") for key, raw in value.items()}
    return result


def _budget_record(bundle: Mapping[str, Any], name: str, frozen: Mapping[str, Any]) -> dict[str, Any]:
    value = bundle.get("budgets")
    if not isinstance(value, Mapping):
        raise ObserverBindingError(f"{name}.budgets is required")
    max_fraction = _finite(frozen.get("budget_fraction"), "budget_fraction")
    checks = []
    for key in ("time_fraction_used", "output_fraction_used"):
        fraction = _finite(value.get(key), f"{name}.budgets.{key}")
        checks.append({"name": f"budget.{key}", "value": fraction,
                       "limit": max_fraction, "status": "PASS" if 0 <= fraction <= max_fraction else "FAIL"})
    return {"checks": checks, "status": "PASS" if all(row["status"] == "PASS" for row in checks) else "FAIL"}


def _event_key(record: Mapping[str, Any], name: str) -> tuple[str, str]:
    event_id = record.get("event_id")
    source_region = record.get("source_region_id")
    if not isinstance(event_id, str) or not event_id or not isinstance(source_region, str) or not source_region:
        raise ObserverBindingError(f"{name} requires event_id and source_region_id")
    return event_id, source_region


def _event_map(bundle: Mapping[str, Any], name: str) -> dict[tuple[str, str], Mapping[str, Any]]:
    events = bundle.get("events")
    if not isinstance(events, list):
        raise ObserverBindingError(f"{name}.events is required")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    statuses = {"observed", "right_censored", "failed_before_observation", "initially_inside",
                "ambiguous_multiple_crossing"}
    for index, record in enumerate(events):
        if not isinstance(record, Mapping):
            raise ObserverBindingError(f"{name}.events[{index}] is not an object")
        key = _event_key(record, f"{name}.events[{index}]")
        if key in result or record.get("status") not in statuses:
            raise ObserverBindingError(f"{name}.events[{index}] has a duplicate or unsupported status")
        brackets = record.get("saved_brackets", [])
        if not isinstance(brackets, list):
            raise ObserverBindingError(f"{name}.events[{index}].saved_brackets is not a list")
        for pair in brackets:
            if not isinstance(pair, list) or len(pair) != 2 or not _finite(pair[0], "bracket") < _finite(pair[1], "bracket"):
                raise ObserverBindingError(f"{name}.events[{index}] has an invalid saved bracket")
        result[key] = record
    return result


def evaluate_manual_predictions_v7(reference: Mapping[str, Any], prediction: Mapping[str, Any],
                                   frozen_config_path: Path | str) -> dict[str, Any]:
    """Compare hand-authored predictions against a digest-bound frozen config."""
    for name, bundle in (("reference", reference), ("prediction", prediction)):
        if not isinstance(bundle, Mapping):
            raise ObserverBindingError(f"{name} must be an object")
        expected_schema = "ds02.stage2.manual-observation-reference.v1" if name == "reference" else "ds02.stage2.manual-observation-predictions.v1"
        if bundle.get("schema") != expected_schema:
            raise ObserverBindingError(f"{name} has unsupported schema")
    reference_config = _config_binding(reference, "reference")
    prediction_config = _config_binding(prediction, "prediction")
    if reference_config.get("path") != prediction_config.get("path") or reference_config.get("sha256") != prediction_config.get("sha256"):
        raise ObserverBindingError("reference and prediction config bindings differ")
    config = load_frozen_observer_config(frozen_config_path, str(reference_config["sha256"]))
    source_reference = _source_bindings(reference, "reference")
    source_prediction = _source_bindings(prediction, "prediction")
    binding_checks = []
    if set(source_reference) != set(source_prediction):
        raise ObserverBindingError("reference and prediction source binding keys differ")
    for key in sorted(source_reference):
        passed = source_reference[key] == source_prediction[key]
        binding_checks.append({"name": f"binding.{key}", "status": "PASS" if passed else "FAIL"})
    queries = _exact_float_list(reference.get("query_times_s"), "reference.query_times_s")
    prediction_queries = _exact_float_list(prediction.get("query_times_s"), "prediction.query_times_s")
    frozen_queries = _exact_float_list(config.get("query_times_s"), "frozen.query_times_s")
    if queries != frozen_queries or prediction_queries != frozen_queries:
        raise ObserverBindingError("reference/prediction query times differ from frozen config")
    evaluator = config["manual_evaluator"]
    budget_reference = _budget_record(reference, "reference", evaluator)
    budget_prediction = _budget_record(prediction, "prediction", evaluator)
    failures = [row["name"] for row in binding_checks if row["status"] != "PASS"]
    if budget_reference["status"] != "PASS":
        failures.append("budget.reference")
    if budget_prediction["status"] != "PASS":
        failures.append("budget.prediction")

    ref_macros, pred_macros = reference.get("macros"), prediction.get("macros")
    if not isinstance(ref_macros, Mapping) or not isinstance(pred_macros, Mapping) or set(ref_macros) != set(pred_macros):
        raise ObserverBindingError("reference and prediction macro keys differ")
    macro_checks = []
    tolerance_map = evaluator["macro_total_tolerances"]
    for macro_name in sorted(ref_macros):
        spec = ref_macros[macro_name]
        if not isinstance(spec, Mapping) or spec.get("kind") not in tolerance_map:
            raise ObserverBindingError(f"macro {macro_name} is missing a frozen kind")
        kind = spec["kind"]
        frozen_total = _finite(tolerance_map[kind], f"frozen macro tolerance {kind}")
        if "total_tolerance" in spec and _finite(spec["total_tolerance"], f"macro {macro_name}.total_tolerance") != frozen_total:
            raise ObserverBindingError(f"macro {macro_name} attempts to override frozen tolerance")
        expected = _array(spec.get("values"), f"reference.macros.{macro_name}.values")
        actual = _array(pred_macros[macro_name], f"prediction.macros.{macro_name}")
        if expected.shape != actual.shape:
            failures.append(f"macro.{macro_name}.shape")
            macro_checks.append({"name": f"macro.{macro_name}", "status": "FAIL", "reason": "shape"})
            continue
        scale = _finite(spec.get("reference_scale"), f"macro {macro_name}.reference_scale")
        if scale <= 0:
            raise ObserverBindingError(f"macro {macro_name} needs fixed nonzero reference scale")
        errors = np.abs(actual - expected)
        normalized_rmse = float(np.sqrt(np.mean(errors * errors)) / scale)
        normalized_max = float(np.max(errors) / scale)
        budget_limit = frozen_total * _finite(evaluator["budget_fraction"], "budget_fraction")
        passed = normalized_rmse <= budget_limit and normalized_max <= frozen_total
        macro_checks.append({"name": f"macro.{macro_name}", "kind": kind,
                             "status": "PASS" if passed else "FAIL",
                             "shape": list(expected.shape), "rmse_normalized": normalized_rmse,
                             "max_normalized": normalized_max, "frozen_total_tolerance": frozen_total,
                             "budget_limit": budget_limit})
        if not passed:
            failures.append(f"macro.{macro_name}")

    ref_events, pred_events = _event_map(reference, "reference"), _event_map(prediction, "prediction")
    if set(ref_events) != set(pred_events):
        failures.append("event.source_region_identity")
    event_checks = []
    event_fraction = _finite(evaluator["event_time_total_fraction"], "event_time_total_fraction")
    budget_fraction = _finite(evaluator["budget_fraction"], "budget_fraction")
    for key in sorted(set(ref_events) | set(pred_events)):
        expected, actual = ref_events.get(key), pred_events.get(key)
        if expected is None or actual is None:
            event_checks.append({"name": f"event.{key}", "status": "FAIL", "reason": "identity"})
            continue
        status_equal = expected["status"] == actual["status"]
        check = {"name": f"event.{key}", "status": "PASS" if status_equal else "FAIL",
                 "expected_status": expected["status"], "actual_status": actual["status"],
                 "saved_brackets_retained": actual.get("saved_brackets", [])}
        if not status_equal:
            failures.append(check["name"] + ".status")
        if expected["status"] == "observed" and status_equal:
            feature = _finite(expected.get("feature_time_s"), f"event {key}.feature_time_s")
            expected_time = _finite(expected.get("event_time_s"), f"event {key}.reference_time")
            actual_time = _finite(actual.get("event_time_s"), f"event {key}.prediction_time")
            if "event_time_tolerance_fraction" in expected and _finite(expected["event_time_tolerance_fraction"], f"event {key}.tolerance") != event_fraction:
                raise ObserverBindingError(f"event {key} attempts to override frozen event tolerance")
            relative = abs(actual_time - expected_time) / feature
            allowed = event_fraction * budget_fraction
            check.update(relative_time_error=relative, frozen_total_tolerance=event_fraction,
                         budget_limit=allowed)
            if relative > allowed:
                check["status"] = "FAIL"
                failures.append(check["name"] + ".time")
        elif expected["status"] != "observed" and actual.get("event_time_s") is not None:
            check["status"] = "FAIL"
            failures.append(check["name"] + ".numeric_censor")
        event_checks.append(check)
    return {
        "schema": STRICT_EVALUATION_SCHEMA,
        "status": "PASS_DEVELOPMENT_OBSERVABLES_V7" if not failures else "FAIL_DEVELOPMENT_OBSERVABLES_V7",
        "failures": sorted(set(failures)),
        "config_binding": {"path": str(config["_frozen_config_path"]), "sha256": config["_frozen_config_sha256"]},
        "binding_checks": binding_checks,
        "query_times_s": queries,
        "macro_checks": macro_checks,
        "event_checks": event_checks,
        "budget_checks": {"reference": budget_reference, "prediction": budget_prediction},
        "identity_scope": "source_region_id; typed (Zone,Idp) is diagnostic only within one bound grid/lineage",
        "model_invoked": False, "hidden_test": False,
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
    }


def verify_portable_source(path: Path | str, expected: Mapping[str, Any], *,
                           verify_source_hash: bool = False,
                           migration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Verify a bound small file, allowing only explicit hash-confirmed mtime migration."""
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ObserverBindingError(f"portable source is unavailable: {target}")
    stat = target.stat()
    expected_bytes = expected.get("bytes")
    expected_mtime = expected.get("mtime_ns")
    if expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise ObserverBindingError("portable source byte count differs")
    mtime_matches = expected_mtime is None or int(expected_mtime) == stat.st_mtime_ns
    expected_hash = expected.get("sha256") or expected.get("producer_declared_sha256")
    if verify_source_hash and (not isinstance(expected_hash, str) or not _HEX64.fullmatch(expected_hash)):
        raise ObserverBindingError("full-hash validation requires an expected SHA-256")
    actual_hash = sha256(target) if verify_source_hash else None
    if verify_source_hash and actual_hash != expected_hash:
        raise ObserverBindingError("portable source content hash differs")
    migration_used = False
    if not mtime_matches:
        if not verify_source_hash or not isinstance(migration, Mapping):
            raise ObserverBindingError("mtime differs; explicit hash-confirmed migration is required")
        if migration.get("schema") != MIGRATION_SCHEMA or migration.get("allow_mtime_change") is not True:
            raise ObserverBindingError("migration sidecar does not authorize mtime change")
        if Path(str(migration.get("relocated_path", ""))).expanduser().resolve() != target:
            raise ObserverBindingError("migration relocated_path does not bind this target")
        if _digest(migration.get("source_sha256"), "migration.source_sha256") != actual_hash:
            raise ObserverBindingError("migration source hash differs from target")
        if int(migration.get("relocated_bytes")) != stat.st_size or int(migration.get("relocated_mtime_ns")) != stat.st_mtime_ns:
            raise ObserverBindingError("migration relocated stat differs from target")
        path_map = migration.get("path_map")
        if not isinstance(path_map, Mapping) or str(path_map.get(str(migration.get("source_path")))) != str(target):
            raise ObserverBindingError("migration path_map is not explicit for this source")
        migration_used = True
    return {"path": str(target), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": actual_hash, "mtime_verified": mtime_matches,
            "migration_used": migration_used, "read_only": True}

