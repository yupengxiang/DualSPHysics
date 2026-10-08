#!/usr/bin/env python3
"""Audit materialized family labels for mass, censoring, and split safety.

This is a post-materialization consumer.  It reads a producer label report and
the new ``native-labels.h5`` artifact, never the original trajectory H5, BI4,
Run.out, or solver output.  The audit makes the useful scientific scope
explicit: native initial-MK mass weighting, saved-frame chord residence, and
observed saved-chord event brackets.  It keeps continuous first arrival,
hidden recrossings, physical fate, dynamics, QN, and QE unknown.

The manifest assigns complete physical cases to a development or recovery-safe
split.  It rejects identity-level or family-level leakage across those splits.
Recovery-safe means append-only, source-bound replay into a new output path; it
does not turn a recovery artifact into qualification evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.family-label-quality.v1"
MANIFEST_SCHEMA = "ds02.stage2.family-label-quality-manifest.v1"
REPORT_SCHEMA = "ds02.stage2.family-label-report.v1"
LABEL_SCHEMA = "ds-data-02.native-labels.v1"
SPLITS = {"development", "recovery_safe", "holdout"}


class QualityError(RuntimeError):
    """Raised when a materialized label product is not source-safe."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise QualityError(f"{label} must be a non-empty path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise QualityError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(str(value), label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualityError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise QualityError(f"{label} must be a JSON object")
    return path, payload


def _float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise QualityError(f"{label} is not numeric") from error
    if number != number or number in (float("inf"), float("-inf")):
        raise QualityError(f"{label} is not finite")
    return number


def _check_close(actual: float, expected: float, tolerance: float, label: str) -> float:
    residual = abs(float(actual) - float(expected))
    if residual > tolerance:
        raise QualityError(f"{label} residual {residual} exceeds {tolerance}")
    return residual


def _report_bindings(report: dict[str, Any], labels_h5: Path, *, verify_h5: bool = True) -> dict[str, Any]:
    if report.get("schema") != REPORT_SCHEMA:
        raise QualityError("unsupported family label report schema")
    if report.get("status") != "LABELS_MATERIALIZED_SOURCE_BOUND":
        raise QualityError("family label report is not a completed source-bound product")
    if report.get("model_invoked") is not False:
        raise QualityError("label product must not invoke a model")
    if report.get("physical_fate") != "UNKNOWN" or report.get("dynamic_impact") != "UNKNOWN":
        raise QualityError("label report cannot grant physical fate or dynamic impact")
    if report.get("q_n_status") != "not_assessed" or report.get("q_e_status") != "not_assessed":
        raise QualityError("label report qualification status is not conservative")
    label_engine = report.get("label_engine")
    if not isinstance(label_engine, dict):
        raise QualityError("label report lacks label_engine semantics")
    if label_engine.get("saved_frame_chords") is not True:
        raise QualityError("label report does not identify saved-frame chord labels")
    if label_engine.get("hidden_continuous_events") != "UNKNOWN":
        raise QualityError("continuous event visibility is not explicitly unknown")
    if label_engine.get("moving_frame") != "UNSUPPORTED_WITHOUT_BOUND_TRANSFORMS":
        raise QualityError("moving-frame support is not fail-closed")
    mass_gate = report.get("mass_gate")
    if not isinstance(mass_gate, dict) or mass_gate.get("screen_only") is not True:
        raise QualityError("mass gate is not explicitly screen-only")
    if mass_gate.get("qualification_credit") != "none":
        raise QualityError("mass gate unexpectedly grants qualification credit")
    source_join = report.get("source_join")
    if not isinstance(source_join, dict):
        raise QualityError("label report lacks source_join")
    trajectory_sha = source_join.get("trajectory_sha256")
    if not isinstance(trajectory_sha, str) or len(trajectory_sha) != 64:
        raise QualityError("source_join lacks the producer trajectory digest")
    materialization = report.get("materialization")
    if not isinstance(materialization, dict):
        raise QualityError("label report lacks materialization binding")
    declared_path = require_file(materialization.get("path"), "label materialization path")
    if declared_path != labels_h5:
        raise QualityError(f"report labels path differs: {declared_path} != {labels_h5}")
    declared_sha = materialization.get("sha256")
    if not isinstance(declared_sha, str) or len(declared_sha) != 64:
        raise QualityError("label materialization lacks a SHA256")
    actual_sha = sha256_file(labels_h5) if verify_h5 else declared_sha
    if actual_sha != declared_sha:
        raise QualityError("label H5 differs from the producer report")
    source_summary = report.get("observed_label_summary")
    if not isinstance(source_summary, dict):
        raise QualityError("label report lacks observed_label_summary")
    return {
        "family_id": source_join.get("family_id") or report.get("family_id"),
        "physical_case_id": source_join.get("physical_case_id") or report.get("physical_case_id"),
        "trajectory_sha256": trajectory_sha,
        "materialization_sha256": actual_sha,
        "source_join": source_join,
        "materialization": materialization,
        "source_summary": source_summary,
    }


def _load_h5():
    try:
        import h5py
        import numpy as np
    except ImportError as error:  # pragma: no cover - runner environment issue
        raise QualityError("h5py and numpy are required for label quality audit") from error
    return h5py, np


def _source_final_table(h: Any, np: Any, source_labels: Any, mass: Any, final_category: Any,
                        source_count: int, region_count: int, tolerance: float) -> tuple[dict[str, Any], float]:
    table = np.asarray(h["source_final_mass_kg"][:], dtype=float)
    expected_shape = (source_count + 1, region_count + 3)
    if table.shape != expected_shape:
        raise QualityError(f"source_final_mass_kg shape {table.shape} != {expected_shape}")
    if not np.isfinite(table).all() or (table < -tolerance).any():
        raise QualityError("source_final_mass_kg is non-finite or negative")
    max_residual = 0.0
    source_rows: list[dict[str, Any]] = []
    for source in range(1, source_count + 1):
        selected = source_labels == source
        initial = float(mass[selected].sum())
        row = table[source]
        max_residual = max(max_residual, _check_close(float(row.sum()), initial, tolerance,
                                                       f"source {source} final table mass"))
        categories: dict[str, float] = {
            "invalid_state": float(row[0]),
            "numerical_loss": float(row[1]),
            "unknown": float(row[2]),
        }
        for region in range(1, region_count + 1):
            categories[f"destination_{region}"] = float(row[region + 2])
        expected_categories = {
            "invalid_state": float(mass[selected & (final_category == -2)].sum()),
            "numerical_loss": float(mass[selected & (final_category == -1)].sum()),
            "unknown": float(mass[selected & (final_category == 0)].sum()),
        }
        for region in range(1, region_count + 1):
            expected_categories[f"destination_{region}"] = float(
                mass[selected & (final_category == region)].sum()
            )
        for key, expected in expected_categories.items():
            max_residual = max(max_residual, _check_close(categories[key], expected, tolerance,
                                                           f"source {source} {key}"))
        source_rows.append({
            "source_label": source,
            "initial_mass_kg": initial,
            "final_mass_by_category_kg": categories,
        })
    if np.any(np.abs(table[0]) > tolerance):
        raise QualityError("source_final_mass_kg row zero contains initial-fluid mass")
    return {"source_rows": source_rows, "table_sum_kg": float(table.sum())}, max_residual


def _audit_entry(report_path: Path, labels_h5: Path, split: str, *, entry_key: str) -> dict[str, Any]:
    report_path, report = read_json(report_path, "family label report")
    bindings = _report_bindings(report, labels_h5)
    h5py, np = _load_h5()
    tolerance = 1e-8
    with h5py.File(labels_h5, "r") as h:
        if h.attrs.get("schema") != LABEL_SCHEMA:
            raise QualityError("label H5 schema differs")
        if h.attrs.get("complete") is not True and bool(h.attrs.get("complete")) is not True:
            raise QualityError("label H5 is not complete")
        if str(h.attrs.get("source_hdf5_sha256", "")) != bindings["trajectory_sha256"]:
            raise QualityError("label H5 source trajectory digest differs from report")
        source_hdf5 = Path(str(h.attrs.get("source_hdf5", ""))).expanduser().resolve()
        report_trajectory = Path(str(bindings["source_join"].get("trajectory", ""))).expanduser().resolve()
        if source_hdf5 != report_trajectory:
            raise QualityError("label H5 source trajectory path differs from report")
        try:
            config = json.loads(str(h.attrs.get("config_json", "{}")))
        except json.JSONDecodeError as error:
            raise QualityError("label H5 config_json is invalid") from error
        if not isinstance(config, dict) or config.get("frame_kind") != "fixed_solver_frame":
            raise QualityError("quality audit requires a fixed solver frame")
        report_config = bindings["source_join"].get("config_json")
        if isinstance(report_config, dict) and config != report_config:
            raise QualityError("label H5 config differs from source-bound report")
        required = (
            "time", "particle_id", "particle_zone", "source_label", "initial_fluid_mass_kg",
            "destination_time_series", "final_category", "failure_reason", "first_passage_interval",
            "first_passage_chord_time", "first_passage_censor", "residence_time_s",
            "unresolved_interval_time_s", "forward_backward_mass_kg", "cumulative_net_flux_kg",
            "unknown_mass_kg", "numerical_loss_mass_kg", "invalid_state_mass_kg", "source_final_mass_kg",
        )
        missing = [name for name in required if name not in h]
        if missing:
            raise QualityError("label H5 is missing datasets: " + ", ".join(missing))
        time = np.asarray(h["time"][:], dtype=float)
        particle_id = np.asarray(h["particle_id"][:])
        particle_zone = np.asarray(h["particle_zone"][:])
        source_label = np.asarray(h["source_label"][:], dtype=int)
        mass = np.asarray(h["initial_fluid_mass_kg"][:], dtype=float)
        destination = h["destination_time_series"]
        final_category = np.asarray(h["final_category"][:], dtype=int)
        failure_reason = np.asarray(h["failure_reason"][:], dtype=int)
        if time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all() or not (np.diff(time) > 0).all():
            raise QualityError("label time must be finite and strictly increasing")
        nt, n = destination.shape
        if nt != len(time) or source_label.shape != (n,) or mass.shape != (n,):
            raise QualityError("label dataset axes disagree")
        keys = np.column_stack((particle_zone, particle_id))
        if len(np.unique(keys, axis=0)) != n:
            raise QualityError("label typed identity axis is not unique")
        if not np.isfinite(mass).all() or (mass < -tolerance).any():
            raise QualityError("initial fluid mass axis is non-finite or negative")
        fluid = source_label > 0
        if not fluid.any() or (mass[~fluid] > tolerance).any() or (mass[fluid] <= 0).any():
            raise QualityError("source labels and initial mass do not define a positive fluid cohort")
        source_count = len(config.get("source_regions", []))
        region_count = len(config.get("destination_regions", []))
        event_count = len(config.get("events", []))
        if source_count < 1 or region_count < 1:
            raise QualityError("label config lacks finite source/destination regions")
        if (source_label < 0).any() or (source_label > source_count).any():
            raise QualityError("source labels exceed config source cohorts")
        initial_mass = float(mass.sum())
        attr_mass = _float(h.attrs.get("initial_fluid_mass_kg"), "initial_fluid_mass_kg")
        mass_tolerance = max(tolerance, abs(initial_mass) * 1e-9)
        max_residual = _check_close(attr_mass, initial_mass, mass_tolerance, "initial mass attribute")
        final_category = np.asarray(final_category, dtype=int)
        if not np.array_equal(final_category, np.asarray(destination[-1], dtype=int)):
            raise QualityError("final_category differs from the final destination frame")
        if not np.array_equal(failure_reason,
                              np.where(~fluid, 4, np.where(final_category == -1, 1,
                              np.where(final_category == -2, 2,
                              np.where(final_category == 0, 3, 0))))):
            raise QualityError("failure_reason does not follow final native category")
        unknown = np.asarray(h["unknown_mass_kg"][:], dtype=float)
        numerical_loss = np.asarray(h["numerical_loss_mass_kg"][:], dtype=float)
        invalid = np.asarray(h["invalid_state_mass_kg"][:], dtype=float)
        if any(series.shape != (nt,) for series in (unknown, numerical_loss, invalid)):
            raise QualityError("mass ledger series has an invalid shape")
        if any((not np.isfinite(series).all() or (series < -mass_tolerance).any())
               for series in (unknown, numerical_loss, invalid)):
            raise QualityError("mass ledger series is non-finite or negative")
        frame_residual = 0.0
        for ti in range(nt):
            dest = np.asarray(destination[ti], dtype=int)
            if (dest < -3).any() or (dest > region_count).any():
                raise QualityError("destination category is outside the registered code range")
            if (dest[~fluid] != -3).any() or (dest[fluid] == -3).any():
                raise QualityError("noninitial and fluid identities are mixed in destination labels")
            frame_residual = max(frame_residual,
                                 abs(float(mass[dest == 0].sum()) - float(unknown[ti])),
                                 abs(float(mass[dest == -1].sum()) - float(numerical_loss[ti])),
                                 abs(float(mass[dest == -2].sum()) - float(invalid[ti])))
        if frame_residual > mass_tolerance:
            raise QualityError(f"per-frame mass ledger residual {frame_residual} exceeds {mass_tolerance}")
        table_summary, table_residual = _source_final_table(
            h, np, source_label, mass, final_category, source_count, region_count, mass_tolerance
        )
        max_residual = max(max_residual, frame_residual, table_residual)
        intervals = np.asarray(h["first_passage_interval"][:], dtype=float)
        estimates = np.asarray(h["first_passage_chord_time"][:], dtype=float)
        censor = np.asarray(h["first_passage_censor"][:], dtype=int)
        expected_axis = (n, event_count)
        if intervals.shape != (n, event_count, 2) or estimates.shape != expected_axis or censor.shape != expected_axis:
            raise QualityError("first-passage dataset axes disagree with the event config")
        if not np.isin(censor, [0, 1]).all():
            raise QualityError("first-passage censor codes are not binary")
        observed = censor == 0
        if np.any(observed & ~fluid[:, None]):
            raise QualityError("non-fluid identities have observed first passage")
        if observed.any():
            if not np.isfinite(intervals[observed]).all() or not np.isfinite(estimates[observed]).all():
                raise QualityError("observed first passage contains non-finite values")
            low = intervals[..., 0][observed]
            high = intervals[..., 1][observed]
            estimate = estimates[observed]
            if not (high > low).all() or not ((estimate >= low - 1e-12) & (estimate <= high + 1e-12)).all():
                raise QualityError("first-passage estimate is outside its saved-frame bracket")
            if not np.isin(low, time).all() or not np.isin(high, time).all():
                raise QualityError("first-passage bracket endpoint is not a saved frame")
        if not bool(np.isnan(intervals[~observed]).all()) or not bool(np.isnan(estimates[~observed]).all()):
            raise QualityError("censored first passage must retain NaN interval/estimate")
        residence = np.asarray(h["residence_time_s"][:], dtype=float)
        unresolved = np.asarray(h["unresolved_interval_time_s"][:], dtype=float)
        duration = float(time[-1] - time[0])
        if residence.shape != (n, region_count) or unresolved.shape != (n,):
            raise QualityError("residence dataset axes disagree")
        if (not np.isfinite(residence).all() or not np.isfinite(unresolved).all() or
                (residence < -1e-12).any() or (unresolved < -1e-12).any() or
                (residence.sum(axis=1) + unresolved > duration + 1e-8).any()):
            raise QualityError("residence/censor interval accounting is invalid")
        directional = np.asarray(h["forward_backward_mass_kg"][:], dtype=float)
        net = np.asarray(h["cumulative_net_flux_kg"][:], dtype=float)
        if directional.shape != (nt, event_count, 2) or net.shape != (nt, event_count):
            raise QualityError("flux dataset axes disagree with the event config")
        if (not np.isfinite(directional).all() or (directional < -mass_tolerance).any() or
                (np.diff(directional, axis=0) < -mass_tolerance).any() or
                not np.allclose(net, directional[..., 0] - directional[..., 1],
                                rtol=1e-9, atol=mass_tolerance)):
            raise QualityError("directional/net flux ledger is invalid")
        source_rows = table_summary["source_rows"]
        gate = report.get("mass_gate", {})
        threshold = _float(gate.get("whole_initial_fraction_gate", 0.003), "mass gate")
        if threshold <= 0:
            raise QualityError("mass gate must be positive")
        final_unknown = float(unknown[-1])
        max_unknown = float(np.max(unknown))
        observed_event_mass = []
        for event_index in range(event_count):
            event_observed = observed[:, event_index] & fluid
            event_observed_mass = float(mass[event_observed].sum())
            observed_event_mass.append({
                "event_id": config["events"][event_index]["id"],
                "observed_count": int(event_observed.sum()),
                "observed_mass_kg": event_observed_mass,
                "censored_count": int((fluid & ~observed[:, event_index]).sum()),
                "censored_mass_kg": float(mass[fluid & ~observed[:, event_index]].sum()),
            })
    checks = {
        "report_h5_binding": True,
        "fixed_frame_only": True,
        "typed_identity_unique": True,
        "initial_mass_closed": True,
        "per_frame_mass_ledger_closed": frame_residual <= mass_tolerance,
        "source_final_mass_closed": table_residual <= mass_tolerance,
        "saved_brackets_valid": True,
        "residence_and_censor_time_closed": True,
        "directional_net_flux_closed": True,
    }
    if not all(checks.values()):
        raise QualityError("family label quality checks failed")
    return {
        "schema": SCHEMA,
        "status": "LABEL_QUALITY_PASS_SOURCE_BOUND_MASS_CENSOR_AUDIT",
        "entry_key": entry_key,
        "family_id": bindings["family_id"],
        "physical_case_id": bindings["physical_case_id"],
        "split": split,
        "source": {
            "report_path": str(report_path),
            "report_sha256": sha256_file(report_path),
            "labels_h5": str(labels_h5),
            "labels_h5_sha256": bindings["materialization_sha256"],
            "trajectory_sha256": bindings["trajectory_sha256"],
            "raw_solver_output": bindings["source_join"].get("raw_solver_output"),
            "initial_fluid_mass_kg": initial_mass,
        },
        "mass_weighted_scope": {
            "whole_initial_denominator_kg": initial_mass,
            "source_cohorts": source_rows,
            "unknown_final_mass_kg": final_unknown,
            "unknown_final_fraction": final_unknown / initial_mass,
            "unknown_max_mass_kg": max_unknown,
            "unknown_max_fraction": max_unknown / initial_mass,
            "screen_gate_fraction": threshold,
            "screen_max_fraction_passes": max_unknown / initial_mass <= threshold,
            "qualification_credit": "none",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "censoring_scope": {
            "event_summary": observed_event_mass,
            "first_passage": "first observed saved-frame chord bracket only",
            "hidden_continuous_events": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
            "numerical_loss_identity_censoring": "UNKNOWN_PHYSICAL_DESTINATION",
            "residence": "piecewise-linear saved-chord occupancy",
        },
        "split_scope": {
            "unit": "complete physical case and trajectory; no identity-level split",
            "family_leakage_checked": True,
            "recovery_safe": split == "recovery_safe",
            "recovery_policy": "append-only new output, source immutable, no qualification credit",
        },
        "quality_checks": checks,
        "read_policy": {
            "original_trajectory_h5_opened": False,
            "part_bi4_opened": False,
            "solver_started": False,
            "model_invoked": False,
        },
    }


def _validate_manifest_payload(manifest: dict[str, Any], *, check_paths: bool = True,
                               verify_artifacts: bool = True) -> list[dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise QualityError("unsupported family label quality manifest schema")
    policy = manifest.get("split_policy")
    if not isinstance(policy, dict) or policy.get("unit") != "complete_physical_case":
        raise QualityError("manifest split policy is not physical-case based")
    if policy.get("identity_level_split") is not False or policy.get("family_leakage_forbidden") is not True:
        raise QualityError("manifest split policy permits leakage")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise QualityError("manifest entries are required")
    seen_case: set[str] = set()
    seen_family_split: dict[str, str] = {}
    seen_trajectory: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise QualityError(f"manifest entry {index} is not an object")
        split = entry.get("split")
        if split not in SPLITS:
            raise QualityError(f"manifest entry {index} has unsupported split")
        report_path = require_file(entry.get("report"), f"entry {index} report")
        report_path, report = read_json(report_path, f"entry {index} report")
        bindings = _report_bindings(
            report,
            require_file(entry.get("labels_h5"), f"entry {index} labels H5"),
            verify_h5=verify_artifacts,
        ) if check_paths else {
            "family_id": report.get("family_id"),
            "physical_case_id": report.get("physical_case_id"),
            "trajectory_sha256": report.get("source_join", {}).get("trajectory_sha256"),
        }
        family = entry.get("family_id") or bindings.get("family_id")
        physical = entry.get("physical_case_id") or bindings.get("physical_case_id")
        trajectory = bindings.get("trajectory_sha256")
        if not isinstance(family, str) or not isinstance(physical, str) or not isinstance(trajectory, str):
            raise QualityError(f"manifest entry {index} lacks exact family/case/trajectory identity")
        if family != report.get("family_id") or physical != report.get("physical_case_id"):
            raise QualityError(f"manifest entry {index} identity differs from report")
        if physical in seen_case or trajectory in seen_trajectory:
            raise QualityError("manifest repeats a physical case or trajectory identity")
        prior_split = seen_family_split.get(family)
        if prior_split is not None and prior_split != split:
            raise QualityError(f"family {family} is split across {prior_split} and {split}")
        seen_case.add(physical)
        seen_trajectory.add(trajectory)
        seen_family_split[family] = split
        if split == "recovery_safe":
            recovery = entry.get("recovery_policy")
            if recovery != {
                "append_only_output": True,
                "no_source_mutation": True,
                "overwrite_forbidden": True,
                "qualification_credit": "none",
            }:
                raise QualityError("recovery_safe entry lacks the exact append-only policy")
        normalized.append({
            "entry_key": entry.get("entry_key", physical),
            "family_id": family,
            "physical_case_id": physical,
            "split": split,
            "report": str(report_path),
            "labels_h5": str(require_file(entry.get("labels_h5"), f"entry {index} labels H5")),
            "report_sha256": sha256_file(report_path),
            "labels_h5_sha256": report.get("materialization", {}).get("sha256"),
            "trajectory_sha256": trajectory,
            "recovery_policy": entry.get("recovery_policy"),
        })
    if not any(row["split"] == "development" for row in normalized):
        raise QualityError("manifest has no development case")
    if not any(row["split"] == "recovery_safe" for row in normalized):
        raise QualityError("manifest has no recovery_safe case")
    return normalized


def make_manifest(entries: Iterable[dict[str, Any]], output: Path | str) -> dict[str, Any]:
    payload = {
        "schema": MANIFEST_SCHEMA,
        "split_policy": {
            "unit": "complete_physical_case",
            "identity_level_split": False,
            "family_leakage_forbidden": True,
            "trajectory_digest_leakage_forbidden": True,
            "development_purpose": "label/rule calibration only; no QN/QE or physical-fate credit",
            "recovery_safe_purpose": "append-only source-bound replay; no qualification credit",
        },
        "entries": list(entries),
        "claim_boundary": {
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "continuous_first_arrival": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
        },
    }
    _validate_manifest_payload(payload, check_paths=True, verify_artifacts=False)
    path = Path(output).expanduser().resolve()
    if path.exists():
        raise QualityError(f"refusing to overwrite manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def make_request(manifest_path: Path | str, output: Path | str, worktree_root: Path | str) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "family label quality manifest")
    entries = _validate_manifest_payload(manifest, check_paths=True, verify_artifacts=False)
    root = Path(worktree_root).expanduser().resolve()
    worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_v1.py"
    dispatch = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
    strict = root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
    runtime = root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
    for path in (worker, dispatch, strict, runtime):
        require_file(str(path), "quality request source")
    current_paths = set()
    inputs = [manifest_path, worker, dispatch, strict, runtime]
    for entry in entries:
        report = Path(entry["report"])
        labels = Path(entry["labels_h5"])
        inputs.extend((report, labels))
        try:
            report_payload = read_json(report, "family label report")[1]
            current = report_payload["source_join"]["source_bindings"]["current_manifest"]["path"]
            current_paths.add(str(require_file(current, "CURRENT manifest")))
        except KeyError as error:
            raise QualityError(f"report lacks CURRENT source binding: {report}") from error
    inputs.extend(Path(path) for path in sorted(current_paths))
    unique_inputs: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        resolved = path.resolve()
        if str(resolved) not in seen:
            unique_inputs.append(resolved)
            seen.add(str(resolved))
    input_hashes: dict[str, str] = {}
    for path in unique_inputs:
        if path in (Path(entry["labels_h5"]).resolve() for entry in entries):
            # The producer report is the immutable declared output digest.  A
            # guard/worker rechecks this H5 before reading it; prepare does not
            # perform a second large-file hash pass.
            expected = next(entry["labels_h5_sha256"] for entry in entries if Path(entry["labels_h5"]).resolve() == path)
            if not isinstance(expected, str) or len(expected) != 64:
                raise QualityError(f"entry label H5 lacks producer digest: {path}")
            input_hashes[str(path)] = expected
        else:
            input_hashes[str(path)] = sha256_file(path)
    label_bytes = sum(Path(entry["labels_h5"]).stat().st_size for entry in entries)
    request = {
        "schema": "ds02.runner-request.v1",
        "attempt_id": "family-label-quality-v1",
        "case_id": "DS02_STAGE2_FAMILY_LABEL_QUALITY_ALL_MATERIALIZED_CANARIES_V1",
        "family_id": "F1_F2_F3_F4_F5_F6_F7",
        "kind": "cpu",
        "cpu_task_kind": "post_materialization_audit",
        "cpu_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(root),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker), "run", "--manifest", str(manifest_path),
            "--output", "{attempt_root}/family-label-quality-v1.json",
        ],
        "input_files": [str(path) for path in unique_inputs],
        "input_sha256": input_hashes,
        "launch_allowed": True,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {
            "materialized_label_h5_bytes_read": label_bytes,
            "original_trajectory_h5_bytes_read": 0,
            "part_bi4_bytes_read": 0,
            "solver_started": False,
            "cfd_or_model_run": False,
            "h5_prepare_hash_deferred_to_guard": True,
        },
        "qualification": {
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
            "mass_gate_is_screen_only": True,
        },
        "split_policy": manifest["split_policy"],
        "request_note": "Audit completed family label products for source-MK weighted mass closure, saved-frame censor brackets, and physical-case split safety. The worker never opens original H5/BI4 or starts a solver; no physical-fate/dynamics credit is granted.",
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise QualityError(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def run(manifest_path: Path | str, output: Path | str) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "family label quality manifest")
    # _audit_entry performs the single full label-H5 digest/read pass.  The
    # manifest preflight remains path/report-only so a seven-case request does
    # not hash every large label artifact twice.
    entries = _validate_manifest_payload(manifest, check_paths=True, verify_artifacts=False)
    results = []
    for entry in entries:
        results.append(_audit_entry(Path(entry["report"]), Path(entry["labels_h5"]),
                                    entry["split"], entry_key=entry["entry_key"]))
    result = {
        "schema": SCHEMA,
        "status": "FAMILY_LABEL_QUALITY_PASS_MASS_CENSOR_SPLIT_SOURCE_BOUND",
        "manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "entry_count": len(results),
            "families": sorted({row["family_id"] for row in results}),
            "splits": {split: sum(row["split"] == split for row in results) for split in sorted(SPLITS)},
        },
        "cases": results,
        "claim_boundary": manifest["claim_boundary"],
        "read_policy": {
            "original_trajectory_h5_opened": False,
            "part_bi4_opened": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise QualityError(f"refusing to overwrite quality report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=str(output.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make_manifest_parser = sub.add_parser("make-manifest")
    make_manifest_parser.add_argument("--entries-json", type=Path, required=True)
    make_manifest_parser.add_argument("--output", type=Path, required=True)
    make_request_parser = sub.add_parser("make-request")
    make_request_parser.add_argument("--manifest", type=Path, required=True)
    make_request_parser.add_argument("--output", type=Path, required=True)
    make_request_parser.add_argument("--worktree-root", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "make-manifest":
        entries_path, entries = read_json(args.entries_json, "entries JSON")
        raw_entries = entries.get("entries") if isinstance(entries.get("entries"), list) else entries
        if not isinstance(raw_entries, list):
            raise QualityError("entries JSON must contain a list or an entries list")
        result = make_manifest(raw_entries, args.output)
        print(json.dumps({"status": "MANIFEST_CREATED", "path": str(Path(args.output).resolve()),
                          "entries": len(result["entries"])}, sort_keys=True))
        return 0
    if args.command == "make-request":
        result = make_request(args.manifest, args.output, args.worktree_root)
        print(json.dumps({"status": result["status"], "path": str(Path(args.output).resolve()),
                          "inputs": len(result["input_files"])}, sort_keys=True))
        return 0
    result = run(args.manifest, args.output)
    print(json.dumps({"status": result["status"], "path": str(Path(args.output).resolve()),
                      "cases": len(result["cases"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
