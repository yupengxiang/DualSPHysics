#!/usr/bin/env python3
"""V4 additive typed-only evaluator with a complete dual-CURRENT shadow.

The consumed V3 evaluator rewrites the operator shadow's ``current_binding``
and ``source_files`` entries to the historical result view.  Its frozen
``observer_profile`` still carries the actual CURRENT hash, so the V14
profile validator correctly rejects the shadow before scoring.  This wrapper
keeps V3's source/result checks and changes only the in-memory shadow: every
CURRENT-bearing profile field is rebound together and the profile self hash is
recomputed.  Frozen requests and producer result bytes are never rewritten.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any, Mapping


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V3_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v3_current_bound.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedEvaluatorV4CurrentError(f"cannot load V3 evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load(V3_SCRIPT, "ds02_bound_typed_only_evaluator_v3_for_v4_current_bound")


class TypedEvaluatorV4CurrentError(V3.TypedEvaluatorV2CurrentError):
    pass


V2 = V3.V2
V1 = V2.V1
REQUEST_SCHEMA = V3.REQUEST_SCHEMA
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-report.v4-current-reconciled"
UNKNOWN = V3.UNKNOWN


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V3.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    return V3.sha256_file(path)


def _rebind_current_profile(profile: Mapping[str, Any], *, actual: str,
                            historical: str) -> dict[str, Any]:
    """Return a profile shadow whose CURRENT fields match the shadow request.

    Values are checked before replacement.  A profile claiming a third
    catalog is rejected rather than silently relabeled.  The profile's
    canonical hash is then recomputed because V14 validates it independently.
    """
    if not isinstance(profile, Mapping):
        raise TypedEvaluatorV4CurrentError("frozen observer_profile is missing")
    shadow = copy.deepcopy(dict(profile))
    current_value = shadow.get("current_binding_sha256")
    if current_value not in {actual, historical}:
        raise TypedEvaluatorV4CurrentError("observer profile CURRENT binding is neither actual nor historical")
    source_hashes = shadow.get("source_file_sha256")
    if not isinstance(source_hashes, dict):
        raise TypedEvaluatorV4CurrentError("observer profile source_file_sha256 is missing")
    current_source = source_hashes.get("current_catalog")
    if current_source not in {actual, historical}:
        raise TypedEvaluatorV4CurrentError("observer profile current_catalog source hash is neither actual nor historical")
    shadow["current_binding_sha256"] = historical
    rebound_sources = dict(source_hashes)
    rebound_sources["current_catalog"] = historical
    shadow["source_file_sha256"] = rebound_sources
    # V14's _canonical_sha256 excludes only this field.  Keep the exact V14
    # implementation in the closure when available; the V2 canonical helper
    # has the same sorted, compact, NaN-rejecting encoding for this profile.
    replay = getattr(V2.V10, "V14", None)
    canonical = getattr(replay, "_canonical_sha256", None)
    if not callable(canonical):
        canonical = getattr(V2.V8, "_canonical_sha256", None)
    if not callable(canonical):
        canonical = canonical_sha
    shadow["sha256"] = canonical(shadow)
    return shadow


def _dual_source_score(result: Mapping[str, Any], frozen: Mapping[str, Any],
                       binding_info: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score against a historical result view with all CURRENT fields aligned."""
    source = result.get("source_binding")
    if not isinstance(source, Mapping):
        raise TypedEvaluatorV4CurrentError("result source_binding is missing")
    actual = str(binding_info.get("current_catalog_sha256", ""))
    historical = str(binding_info.get("historical_result_current_catalog_sha256", ""))
    if len(actual) != 64 or len(historical) != 64 or actual == historical:
        raise TypedEvaluatorV4CurrentError("dual CURRENT binding is not a distinct actual/historical pair")
    if source.get("current_catalog_sha256") != historical:
        raise TypedEvaluatorV4CurrentError("result CURRENT hash differs from the explicitly bound historical relocated view")
    files = source.get("source_files")
    if not isinstance(files, Mapping) or files.get("current_catalog") != historical:
        raise TypedEvaluatorV4CurrentError("result current source-file hash differs from the explicitly bound historical view")

    shadow = copy.deepcopy(frozen)
    current = shadow.get("current_binding")
    if not isinstance(current, dict):
        raise TypedEvaluatorV4CurrentError("frozen current_binding is missing")
    current["sha256"] = historical
    source_files = shadow.get("source_files")
    if not isinstance(source_files, list):
        raise TypedEvaluatorV4CurrentError("frozen source_files are missing")
    current_entries = [item for item in source_files
                       if isinstance(item, dict) and item.get("role") == "current_catalog"]
    if len(current_entries) != 1:
        raise TypedEvaluatorV4CurrentError("frozen current_catalog source entry is not unique")
    current_entries[0]["sha256"] = historical
    shadow["observer_profile"] = _rebind_current_profile(
        shadow.get("observer_profile"), actual=actual, historical=historical)

    score = V2.V1._score_typed_result(result, shadow)
    reconciliation = {
        "status": "PASS_DUAL_CURRENT_RESULT_HISTORICAL_VIEW",
        "actual_current_catalog_sha256": actual,
        "historical_result_current_catalog_sha256": historical,
        "result_current_catalog_sha256": historical,
        "shadow_current_binding_sha256": shadow["current_binding"]["sha256"],
        "shadow_source_file_current_catalog_sha256": shadow["source_files"][0]["sha256"]
        if shadow["source_files"] and shadow["source_files"][0].get("role") == "current_catalog"
        else next(item["sha256"] for item in shadow["source_files"] if item.get("role") == "current_catalog"),
        "shadow_observer_profile_current_binding_sha256": shadow["observer_profile"]["current_binding_sha256"],
        "shadow_observer_profile_source_file_current_catalog_sha256": shadow["observer_profile"]["source_file_sha256"]["current_catalog"],
        "shadow_observer_profile_sha256": shadow["observer_profile"]["sha256"],
        "shadow_request_used_only_in_memory": True,
        "real_current_validated_separately_by_parent": True,
        "exact_current_source_claim": "NOT_GRANTED_TO_HISTORICAL_RESULT_VIEW",
    }
    score["current_source_reconciliation"] = reconciliation
    return score, reconciliation


# Delegate all other V3 request validation and CLI behavior through the
# immutable implementation, but replace the runtime scorer and report schema.
V3._dual_source_score = _dual_source_score
V3.REPORT_SCHEMA = REPORT_SCHEMA


def _load_request(path: Path | str):
    return V3._load_request(path)


def run_trial(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return V3.run_trial(*args, **kwargs)


def main(argv: list[str] | None = None) -> int:
    return V3.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
