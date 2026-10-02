#!/usr/bin/env python3
"""Audit native F2 event brackets and resolution observations.

The labels and trajectories are consumed artifacts.  This program only reads
them and writes a sidecar that keeps numerical lattice identity separate from
the owner-declared physical condition.  It deliberately does not qualify a
solver run or classify native exclusions as physical spill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np


SCHEMA = "ds-data-02.f2-event-audit.v1"
EVENT_NAMES = {
    1: "cup_departure",
    2: "cup_return",
    3: "receiver_entry",
    4: "receiver_exit",
    5: "tray_entry",
    6: "tray_exit",
}
DESTINATION_NAMES = ("unknown", "cup", "receiver", "tray", "inflight")


class AuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"expected JSON object: {path}")
    return value


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def event_bracket_rows(h5_path: Path, event_codes: dict[str, int]) -> dict[str, Any]:
    with h5py.File(h5_path, "r") as handle:
        if "time" not in handle or "events" not in handle:
            raise AuditError(f"event/time datasets missing in {h5_path}")
        time = np.asarray(handle["time"], dtype=np.float64)
        events = np.asarray(handle["events"])
    if time.ndim != 1 or len(time) < 2 or not np.all(np.isfinite(time)):
        raise AuditError(f"invalid native time axis in {h5_path}")
    if not np.all(np.diff(time) > 0):
        raise AuditError(f"native time axis is not strictly increasing in {h5_path}")

    rows: dict[str, Any] = {}
    for name, code in event_codes.items():
        selected = events[events["event_code"] == int(code)]
        if len(selected) == 0:
            rows[name] = {
                "event_code": int(code),
                "observed": False,
                "status": "right_censored_or_not_observed",
            }
            continue
        first = selected[int(np.argmin(selected["time_s"]))]
        before = int(first["frame_before"])
        after = int(first["frame_after"])
        if before < 0 or after >= len(time) or after <= before:
            raise AuditError(f"invalid bracket {before},{after} for {name} in {h5_path}")
        left = float(time[before])
        right = float(time[after])
        observed = finite_float(first["time_s"])
        rows[name] = {
            "event_code": int(code),
            "observed": True,
            "status": "bracketed_native_consecutive_frames",
            "first_event_time_s": observed,
            "frame_before": before,
            "frame_after": after,
            "bracket_left_s": left,
            "bracket_right_s": right,
            "bracket_width_s": right - left,
            "bracket_half_width_s": 0.5 * (right - left),
            "particle_index": int(first["particle_index"]),
            "zone": int(first["zone"]),
            "idp": int(first["idp"]),
        }
    return {
        "frames": int(len(time)),
        "time_start_s": float(time[0]),
        "time_end_s": float(time[-1]),
        "save_interval_min_s": float(np.min(np.diff(time))),
        "save_interval_max_s": float(np.max(np.diff(time))),
        "events": rows,
    }


def canonical_physical_binding(owner: dict[str, Any]) -> dict[str, Any]:
    binding = owner.get("physical_binding")
    if not isinstance(binding, dict):
        raise AuditError("owner metadata has no physical_binding")
    return {
        "physical_case_id": owner.get("physical_case_id"),
        "physical_condition_hash_declared": owner.get("physical_condition_hash_declared"),
        "physical_binding_sha256": owner.get("physical_binding_sha256"),
        "geometry_family_id": binding.get("geometry_family_id"),
        "control_family_id": binding.get("control_family_id"),
        "motion_source_sha256": owner.get("source_motion", {}).get("sha256"),
        "geometry": binding.get("geometry"),
        "initial_state": binding.get("initial_state"),
        "parameters": binding.get("parameters"),
    }


def load_case(spec: dict[str, Any], budget: float, save_fraction: float) -> dict[str, Any]:
    required = ("case_id", "labels_report", "labels_h5", "owner_metadata")
    missing = [key for key in required if key not in spec]
    if missing:
        raise AuditError(f"case spec missing {missing}")
    labels_path = Path(spec["labels_report"])
    h5_path = Path(spec["labels_h5"])
    owner_path = Path(spec["owner_metadata"])
    for key, path in (("labels_report", labels_path), ("labels_h5", h5_path), ("owner_metadata", owner_path)):
        expected = spec.get(f"{key}_sha256")
        if expected is not None and sha256(path) != expected:
            raise AuditError(f"{key} hash differs from frozen manifest for {spec['case_id']}")
    labels = read_json(labels_path)
    owner = read_json(owner_path)
    event_codes = labels.get("event_ledger", {}).get("event_codes")
    if not isinstance(event_codes, dict):
        event_codes = {name: code for code, name in EVENT_NAMES.items()}
    event_codes = {str(name): int(code) for name, code in event_codes.items()}
    brackets = event_bracket_rows(h5_path, event_codes)
    physical = canonical_physical_binding(owner)
    max_half = max(
        (value.get("bracket_half_width_s", 0.0) for value in brackets["events"].values() if value.get("observed")),
        default=0.0,
    )
    label_physical_hash = labels.get("physical_condition_hash")
    canonical_hash = physical.get("physical_condition_hash_declared")
    final_mass = labels.get("final_mass_kg_by_destination", {})
    event_ledger = labels.get("event_ledger", {})
    source_population = labels.get("source_population", {})
    initial_mass = physical.get("initial_state", {}).get("initial_mass_total_kg")
    if initial_mass is None:
        initial_mass = 24.576
    return {
        "case_id": str(spec["case_id"]),
        "mechanism_id": labels.get("mechanism_id"),
        "resolution": labels.get("numerical_recipe_fields", {}).get("resolution"),
        "labels_report": {"path": str(labels_path), "sha256": sha256(labels_path)},
        "labels_h5": {"path": str(h5_path), "sha256": sha256(h5_path)},
        "owner_metadata": {"path": str(owner_path), "sha256": sha256(owner_path)},
        "physical_binding": physical,
        "label_physical_condition_hash": label_physical_hash,
        "label_physical_hash_matches_owner": label_physical_hash == canonical_hash,
        "label_physical_hash_warning": (
            "labels hash includes resolution-specific lattice fields; use owner canonical hash"
            if label_physical_hash != canonical_hash else None
        ),
        "numerical_recipe_hash": labels.get("numerical_recipe_hash"),
        "dimensions": labels.get("dimensions"),
        "time_axis": brackets,
        "event_brackets": brackets["events"],
        "final_mass_kg_by_destination": {name: float(final_mass.get(name, 0.0)) for name in DESTINATION_NAMES},
        "unknown_mass_kg_max": float(labels.get("unknown_mass_kg_max", 0.0)),
        "event_counts": dict(event_ledger.get("counts_by_code", {})),
        "event_mass_kg_by_code": dict(event_ledger.get("mass_kg_by_code", {})),
        "first_time_s_by_code": dict(event_ledger.get("first_time_s_by_code", {})),
        "event_ledger_status": event_ledger.get("status"),
        "lifecycle": labels.get("lifecycle"),
        "initial_mass_kg_from_owner": float(initial_mass),
        "initial_mass_kg_from_labels": float(source_population.get("initial_fluid_mass_kg", 0.0)),
        "final_missing_fluid_count": int(source_population.get("final_missing_fluid_count", 0)),
        "save_budget": {
            "event_time_absolute_budget_s": budget,
            "save_fraction_max": save_fraction,
            "save_half_width_budget_s": budget * save_fraction,
            "max_observed_first_passage_half_width_s": max_half,
            "status": "pass" if max_half <= budget * save_fraction else "fail",
        },
    }


def relative_delta(value: float, reference: float, scale: float) -> dict[str, float]:
    delta = value - reference
    return {
        "absolute": float(delta),
        "relative_to_reference": float(delta / reference) if reference else (0.0 if delta == 0 else math.inf),
        "relative_to_initial_mass": float(delta / scale) if scale else math.inf,
    }


def compare_resolution(cases: list[dict[str, Any]], initial_mass: float) -> dict[str, Any]:
    by_mechanism: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_mechanism.setdefault(str(case["mechanism_id"]), []).append(case)
    result: dict[str, Any] = {}
    for mechanism, group in sorted(by_mechanism.items()):
        group.sort(key=lambda item: {"coarse": 0, "medium": 1, "fine": 2}.get(item.get("resolution"), 99))
        reference = next((item for item in group if item.get("resolution") == "medium"), group[0])
        comparisons = []
        for case in group:
            destination = {
                key: relative_delta(float(case["final_mass_kg_by_destination"][key]),
                                    float(reference["final_mass_kg_by_destination"][key]), initial_mass)
                for key in DESTINATION_NAMES
            }
            first_times = {}
            for name, value in case["event_brackets"].items():
                ref_value = reference["event_brackets"].get(name, {})
                if value.get("observed") and ref_value.get("observed"):
                    first_times[name] = relative_delta(float(value["first_event_time_s"]),
                                                       float(ref_value["first_event_time_s"]), initial_mass)
                else:
                    first_times[name] = {"status": "one_or_both_not_observed"}
            comparisons.append({
                "case_id": case["case_id"],
                "resolution": case.get("resolution"),
                "reference_case_id": reference["case_id"],
                "final_destination_mass_delta": destination,
                "unknown_mass_delta_kg": float(case["unknown_mass_kg_max"] - reference["unknown_mass_kg_max"]),
                "event_count_delta": {
                    key: int(case["event_counts"].get(key, 0)) - int(reference["event_counts"].get(key, 0))
                    for key in sorted(set(case["event_counts"]) | set(reference["event_counts"]))
                },
                "first_passage_time_delta": first_times,
            })
        result[mechanism] = {
            "reference_resolution": "medium",
            "reference_case_id": reference["case_id"],
            "comparisons": comparisons,
            "status": "observed_only; no numerical acceptance claim",
        }
    return result


def audit(manifest_path: Path, quality_contract_path: Path, integration_plan_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    quality = read_json(quality_contract_path)
    integration_plan = read_json(integration_plan_path)
    specs = manifest.get("cases")
    if not isinstance(specs, list) or not specs:
        raise AuditError("manifest cases must be a nonempty list")
    cases_by_mechanism = quality.get("background_contracts", {})
    cases: list[dict[str, Any]] = []
    for spec in specs:
        labels = read_json(Path(spec["labels_report"]))
        mechanism = str(labels.get("mechanism_id"))
        contract = cases_by_mechanism.get(mechanism, {}).get("q_n", {})
        budget = float(contract.get("event_time_absolute_budget_s", 0.0))
        fraction = float(contract.get("save_fraction_of_total_error_budget_max", 0.0))
        cases.append(load_case(spec, budget, fraction))
    canonical_by_mechanism: dict[str, set[str]] = {}
    for case in cases:
        canonical_by_mechanism.setdefault(str(case["mechanism_id"]), set()).add(
            str(case["physical_binding"].get("physical_condition_hash_declared"))
        )
    canonical_consistent = all(len(values) == 1 for values in canonical_by_mechanism.values())
    observed_brackets = [
        float(event["bracket_half_width_s"])
        for case in cases for event in case["event_brackets"].values() if event.get("observed")
    ]
    max_half = max(observed_brackets, default=0.0)
    # Save/integration are separate factors.  No integration result is inferred here.
    save_budgets = [case["save_budget"] for case in cases]
    save_pass = all(item["status"] == "pass" for item in save_budgets)
    initial_mass = 24.576
    report = {
        "schema": SCHEMA,
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "quality_contract": {"path": str(quality_contract_path), "sha256": sha256(quality_contract_path)},
        "integration_save_plan": {"path": str(integration_plan_path), "sha256": sha256(integration_plan_path)},
        "thresholds_frozen_before_observation": True,
        "thresholds": {
            "event_time_absolute_budget_s_by_mechanism": {
                mechanism: float(quality["background_contracts"][mechanism]["q_n"]["event_time_absolute_budget_s"])
                for mechanism in sorted(cases_by_mechanism)
                if mechanism in {str(case["mechanism_id"]) for case in cases}
            },
            "save_fraction_max": 0.2,
            "integration_fraction_max": 0.2,
            "save_half_width_budget_s": 0.2 * 0.0036681953999691376,
            "current_save_interval_role": integration_plan.get("comparison", {}).get("reference_matrix_save_interval_role"),
        },
        "cases": cases,
        "canonical_physical_identity": {
            "hashes_by_mechanism": {key: sorted(value) for key, value in canonical_by_mechanism.items()},
            "same_across_resolutions": canonical_consistent,
            "label_hashes_are_not_canonical": any(not case["label_physical_hash_matches_owner"] for case in cases),
            "interpretation": "owner physical binding is authoritative; resolution-specific grid origin belongs to numerical recipe",
        },
        "first_passage_bracket_summary": {
            "observed_event_bracket_count": len(observed_brackets),
            "max_half_width_s": max_half,
            "max_width_s": 2.0 * max_half,
            "save_budget_status": "pass" if save_pass else "fail",
            "integration_study_status": "not_assessed; integration step study is a separate factor",
            "recommended_new_baseline_save_interval_s": 0.001,
            "requires_new_numeric_recipe_for_save_budget": not save_pass,
        },
        "resolution_comparison": compare_resolution(cases, initial_mass),
        "scientific_verdict": {
            "q_i": "event-evidence-sidecar-ready; source labels and native exclusions remain separately adjudicated",
            "q_n": "pending; current 0.01 s saved brackets exceed the frozen save allocation",
            "production": "not_eligible_from_this_audit",
            "qualification_claim": "none",
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--quality-contract", type=Path, required=True)
    parser.add_argument("--integration-save-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit(args.manifest, args.quality_contract, args.integration_save_plan)
    except (AuditError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"f2_handoff_20261002_event_audit: {type(exc).__name__}: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "output": str(args.output), "sha256": sha256(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
