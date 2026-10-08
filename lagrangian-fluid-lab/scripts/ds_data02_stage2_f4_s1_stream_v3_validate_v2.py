#!/usr/bin/env python3
"""Independently validate and compare completed F4-S1 V3 saved-frame output.

The validator consumes only the V3 report, its manifest, the emitted CSV/JSON
sidecars, and their hashes.  It never opens trajectory HDF5, BI4, PartOut, or
solver files.  The comparison has three explicitly separate observations:

* ``spatial_proxy`` compares terminal active/source/aperture mass and counts;
  V3 does not emit coordinates, so this is not a claim about a full spatial
  field or COM.
* ``integral`` compares trapezoidal saved-frame integrals of mass, momentum,
  energy, and aperture occupancy.
* ``save_sampling`` compares row/time-grid statistics and saved-crossing
  diagnostics.  A crossing count is never promoted to a continuous event
  time or physical flux.

The frozen values below are the Stage2 preregistered diagnostic limits.  They
are reported as observations and screening classifications only; this
validator never grants scientific qualification, Q-N/Q-E/Q-I, or physical
fate/flux credit.  In particular, this forward validator does not import the
older proxy-integral percentage or endpoint-second limits.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f4-s1-stream-v3-validator.v2"
V3_REPORT_SCHEMA = "ds02.stage2.f4-s1-stream.v3"
MANIFEST_SCHEMA = "ds02.stage2.f4-s1-stream-manifest.v3"
EXPECTED_VARIANTS = ("coarse-native", "medium-native", "fine-native", "fine-half_dt", "fine-half_save")
REFERENCE_VARIANT = "fine-native"

# These are the frozen Stage2 task thresholds.  V3 only supplies saved-frame
# proxies, so the validator records these thresholds without converting them
# into a qualification gate.  The whole-initial-mass screen is separate from
# the source/MK/region/flux diagnostic screen.
FROZEN_TOLERANCES = {
    "whole_initial_unknown_mass_fraction_max": 0.003,
    "mk_region_flux_whole_initial_mass_fraction_max": 0.03,
    "mass_preferred_relative_max": 0.01,
    "mass_marginal_relative_max": 0.02,
    "mass_hard_relative_max": 0.02,
    "position_relative_domain_length_max": 0.02,
    "velocity_kinetic_energy_relative_nonzero_max": 0.05,
    "event_time_relative_window_max": 0.01,
    "integration_output_allocation_each_fraction": 0.25,
    "near_zero_scale_floor": 1.0e-12,
}


class ValidationError(RuntimeError):
    """Raised when a completed V3 output is not source-bound or well formed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"expected JSON object: {path}")
    return value


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _float(row: Mapping[str, Any], field: str, *, path: Path, row_index: int) -> float:
    value = row.get(field)
    if not _finite(value):
        raise ValidationError(f"non-finite {field} at {path}:{row_index}")
    return float(value)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValidationError(f"missing V3 CSV sidecar: {path}")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValidationError(f"V3 CSV has no saved rows: {path}")
    return rows


def _trapz(rows: Sequence[Mapping[str, str]], field: str, path: Path) -> float:
    if len(rows) < 1:
        return 0.0
    times = [_float(row, "time_s", path=path, row_index=index) for index, row in enumerate(rows)]
    values = [_float(row, field, path=path, row_index=index) for index, row in enumerate(rows)]
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValidationError(f"time_s is not strictly increasing: {path}")
    return float(sum(0.5 * (left + right) * (t_right - t_left) for left, right, t_left, t_right in zip(values, values[1:], times, times[1:])))


def _relative_difference(value: float, reference: float) -> dict[str, Any]:
    absolute = abs(float(value) - float(reference))
    scale = max(abs(float(reference)), FROZEN_TOLERANCES["near_zero_scale_floor"])
    return {
        "value": float(value),
        "reference": float(reference),
        "absolute_difference": absolute,
        "relative_difference": absolute / scale,
        "near_zero_reference": abs(float(reference)) < FROZEN_TOLERANCES["near_zero_scale_floor"],
    }


def _artifact_summary(artifact: Mapping[str, Any], *, csv_path: Path, labels: Mapping[str, Any]) -> dict[str, Any]:
    rows = _read_csv(csv_path)
    times = [_float(row, "time_s", path=csv_path, row_index=index) for index, row in enumerate(rows)]
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValidationError(f"V3 saved times are not strictly increasing: {csv_path}")
    expected_frames = int(artifact.get("frames", -1))
    if expected_frames != len(rows):
        raise ValidationError(f"V3 frame count differs from CSV: {artifact.get('artifact_id')}")
    source_data = artifact.get("source_event_data")
    if not isinstance(source_data, Mapping) or labels != source_data:
        raise ValidationError(f"V3 labels JSON differs from report source_event_data: {artifact.get('artifact_id')}")
    whole_mass = float(artifact.get("whole_initial_fluid_mass_kg", 0.0))
    if not _finite(whole_mass) or whole_mass <= 0:
        raise ValidationError(f"invalid whole initial fluid mass: {artifact.get('artifact_id')}")
    source_labels = sorted(str(label) for label in source_data)
    terminal = rows[-1]
    spatial_fields = ["active_fluid_mass_kg", "unknown_fluid_mass_kg", "cumulative_unique_unknown_fluid_mass_kg"]
    integral_fields = ["active_fluid_mass_kg", "unknown_fluid_mass_kg", "active_momentum_x_kg_m_s", "active_momentum_y_kg_m_s", "active_momentum_z_kg_m_s", "active_kinetic_energy_j"]
    for label in source_labels:
        spatial_fields.extend([f"{label}_active_mass_kg", f"{label}_finite_aperture_mass_kg", f"{label}_finite_aperture_particles"])
        integral_fields.extend([f"{label}_active_mass_kg", f"{label}_finite_aperture_mass_kg", f"{label}_finite_aperture_particles"])
    spatial = {field: _float(terminal, field, path=csv_path, row_index=len(rows) - 1) for field in spatial_fields}
    integrals = {field: _trapz(rows, field, csv_path) for field in integral_fields}
    dt = [right - left for left, right in zip(times, times[1:])]
    accepted_crossings = {
        label: int(data.get("accepted_saved_crossings", -1))
        for label, data in source_data.items()
        if isinstance(data, Mapping)
    }
    later_crossings = {
        label: int(data.get("later_saved_crossings", -1))
        for label, data in source_data.items()
        if isinstance(data, Mapping)
    }
    first_bracket_widths: list[float] = []
    for label, data in source_data.items():
        if not isinstance(data, Mapping):
            raise ValidationError(f"source event data is not an object: {label}")
        accepted = int(data.get("accepted_saved_crossings", -1))
        first = int(data.get("first_saved_crossings", -1))
        later = int(data.get("later_saved_crossings", -1))
        positive = int(data.get("positive_saved_crossings", -1))
        negative = int(data.get("negative_saved_crossings", -1))
        candidate = int(data.get("candidate_plane_crossings", -1))
        outside = int(data.get("outside_aperture_crossings", -1))
        if min(accepted, first, later, positive, negative, candidate, outside) < 0 or first + later != accepted or positive + negative != accepted or candidate != accepted + outside:
            raise ValidationError(f"inconsistent per-source crossing ledger: {label}")
        per_id = data.get("per_typed_identity")
        if not isinstance(per_id, Mapping):
            raise ValidationError(f"missing per-identity crossing ledger: {label}")
        if sum(int(value.get("total_saved_crossings", -1)) for value in per_id.values()) != accepted:
            raise ValidationError(f"per-identity total differs from source total: {label}")
        for identity, value in per_id.items():
            if not isinstance(value, Mapping) or int(value.get("first_saved_crossings", -1)) + int(value.get("later_saved_crossings", -1)) != int(value.get("total_saved_crossings", -1)):
                raise ValidationError(f"per-identity first/later ledger invalid: {label}/{identity}")
            bracket = value.get("first_bracket_s")
            if bracket is not None and (not isinstance(bracket, list) or len(bracket) != 2 or not all(_finite(item) for item in bracket) or bracket[1] < bracket[0]):
                raise ValidationError(f"invalid saved bracket: {label}/{identity}")
            if bracket is not None:
                first_bracket_widths.append(float(bracket[1]) - float(bracket[0]))
    unknown_terminal_fraction = spatial["unknown_fluid_mass_kg"] / whole_mass
    unknown_cumulative_fraction = spatial["cumulative_unique_unknown_fluid_mass_kg"] / whole_mass
    region_flux = {
        str(label): {
            "accepted_saved_initial_mass_kg": float(data.get("accepted_saved_initial_mass_kg", 0.0)),
            "whole_initial_mass_fraction": float(data.get("accepted_saved_initial_mass_kg", 0.0)) / whole_mass,
            "physical_flux": "unknown",
        }
        for label, data in source_data.items()
        if isinstance(data, Mapping)
    }
    window_T = times[-1] - times[0]
    return {
        "artifact_id": artifact["artifact_id"],
        "resolution": artifact["resolution"],
        "time_variant": artifact["time_variant"],
        "frames": len(rows),
        "particles": int(artifact.get("particles", -1)),
        "whole_initial_fluid_mass_kg": whole_mass,
        "saved_time_window_s": [times[0], times[-1]],
        "window_T_s": window_T,
        "sampling": {
            "row_count": len(rows),
            "dt_min_s": min(dt) if dt else 0.0,
            "dt_max_s": max(dt) if dt else 0.0,
            "dt_median_s": statistics.median(dt) if dt else 0.0,
            "accepted_saved_crossings": accepted_crossings,
            "later_saved_crossings": later_crossings,
            "first_saved_bracket_widths_s": first_bracket_widths,
            "max_first_saved_bracket_width_s": max(first_bracket_widths) if first_bracket_widths else 0.0,
            "continuous_event_time": "unknown",
        },
        "spatial_proxy_terminal": spatial,
        "integrals_saved_trapezoid": integrals,
        "unknown_mass_screen": {
            "terminal_fraction": unknown_terminal_fraction,
            "cumulative_unique_fraction": unknown_cumulative_fraction,
            "terminal_status": (
                "within_unknown_mass_screen"
                if unknown_terminal_fraction <= FROZEN_TOLERANCES["whole_initial_unknown_mass_fraction_max"]
                else "exceeds_unknown_mass_screen"
            ),
            "cumulative_status": (
                "within_unknown_mass_screen"
                if unknown_cumulative_fraction <= FROZEN_TOLERANCES["whole_initial_unknown_mass_fraction_max"]
                else "exceeds_unknown_mass_screen"
            ),
            "physical_fate": "unknown",
        },
        "region_flux_saved_crossings": region_flux,
        "source_event_data": source_data,
    }


def _compare_group(
    summaries: Mapping[str, Mapping[str, Any]],
    reference_variant: str,
    group_key: str,
    *,
    group_label: str,
) -> dict[str, Any]:
    def metric_status(field: str, comparison: Mapping[str, Any]) -> str:
        if comparison["near_zero_reference"]:
            return "near_zero_reference"
        relative = float(comparison["relative_difference"])
        if field.endswith("_mass_kg") or "mass_" in field:
            if relative <= FROZEN_TOLERANCES["mass_preferred_relative_max"]:
                return "within_mass_preferred_diagnostic_band"
            if relative <= FROZEN_TOLERANCES["mass_marginal_relative_max"]:
                return "within_mass_marginal_diagnostic_band"
            return "exceeds_mass_hard_diagnostic_band"
        if "momentum" in field or "kinetic_energy" in field:
            if relative <= FROZEN_TOLERANCES["velocity_kinetic_energy_relative_nonzero_max"]:
                return "within_velocity_kinetic_energy_diagnostic_band"
            return "exceeds_velocity_kinetic_energy_diagnostic_band"
        if field.endswith("_particles"):
            return "exact_saved_count" if comparison["absolute_difference"] == 0 else "saved_count_difference_diagnostic"
        return "reported_without_frozen_task_threshold"

    reference = summaries[reference_variant][group_key]
    result: dict[str, Any] = {}
    for variant, summary in summaries.items():
        if variant == reference_variant:
            continue
        values = summary[group_key]
        metrics: dict[str, Any] = {}
        for field in sorted(reference):
            comparison = _relative_difference(float(values[field]), float(reference[field]))
            comparison["diagnostic_status"] = metric_status(field, comparison)
            metrics[field] = comparison
        result[variant] = {
            "reference_variant": reference_variant,
            "group": group_label,
            "metrics": metrics,
            "qualification_credit": "not_granted",
        }
    return result


def _region_flux_comparison(summaries: Mapping[str, Mapping[str, Any]], reference_variant: str) -> dict[str, Any]:
    """Compare saved aperture observations while retaining the .03 screen.

    The V3 operator observes saved records and typed source labels only.  A
    finite-aperture count/mass is therefore a region observation; it is not a
    proof of continuous transport, net flux, or physical fate.
    """

    reference = summaries[reference_variant]["region_flux_saved_crossings"]
    result: dict[str, Any] = {}
    for variant, summary in summaries.items():
        if variant == reference_variant:
            continue
        current = summary["region_flux_saved_crossings"]
        labels = sorted(set(reference) | set(current))
        sources: dict[str, Any] = {}
        for label in labels:
            ref = reference.get(label, {"whole_initial_mass_fraction": 0.0})
            cur = current.get(label, {"whole_initial_mass_fraction": 0.0})
            current_fraction = float(cur.get("whole_initial_mass_fraction", 0.0))
            comparison = _relative_difference(
                current_fraction,
                float(ref.get("whole_initial_mass_fraction", 0.0)),
            )
            comparison["whole_initial_mass_fraction"] = current_fraction
            comparison["whole_initial_mass_fraction_status"] = (
                "within_mk_region_flux_whole_initial_mass_screen"
                if current_fraction <= FROZEN_TOLERANCES["mk_region_flux_whole_initial_mass_fraction_max"]
                else "exceeds_mk_region_flux_whole_initial_mass_screen"
            )
            comparison["physical_flux"] = "unknown"
            comparison["physical_fate"] = "unknown"
            sources[label] = comparison
        aggregate_fraction = sum(
            float(item.get("whole_initial_mass_fraction", 0.0))
            for item in current.values()
            if isinstance(item, Mapping)
        )
        result[variant] = {
            "reference_variant": reference_variant,
            "sources": sources,
            "aggregate_whole_initial_mass_fraction": aggregate_fraction,
            "aggregate_status": (
                "within_mk_region_flux_whole_initial_mass_screen"
                if aggregate_fraction <= FROZEN_TOLERANCES["mk_region_flux_whole_initial_mass_fraction_max"]
                else "exceeds_mk_region_flux_whole_initial_mass_screen"
            ),
            "physical_flux": "unknown",
            "physical_fate": "unknown",
            "qualification_credit": "not_granted",
        }
    return result


def _sampling_comparison(summaries: Mapping[str, Mapping[str, Any]], reference_variant: str) -> dict[str, Any]:
    reference = summaries[reference_variant]["sampling"]
    result: dict[str, Any] = {}
    for variant, summary in summaries.items():
        if variant == reference_variant:
            continue
        current = summary["sampling"]
        endpoint_delta = abs(float(current["dt_max_s"]) - float(reference["dt_max_s"]))
        time_end_delta = abs(float(summary["saved_time_window_s"][1]) - float(summaries[reference_variant]["saved_time_window_s"][1]))
        count_delta = {label: int(current["accepted_saved_crossings"].get(label, 0)) - int(reference["accepted_saved_crossings"].get(label, 0)) for label in sorted(set(current["accepted_saved_crossings"]) | set(reference["accepted_saved_crossings"]))}
        later_delta = {label: int(current["later_saved_crossings"].get(label, 0)) - int(reference["later_saved_crossings"].get(label, 0)) for label in sorted(set(current["later_saved_crossings"]) | set(reference["later_saved_crossings"]))}
        window_T = max(float(summary["window_T_s"]), FROZEN_TOLERANCES["near_zero_scale_floor"])
        event_budget = FROZEN_TOLERANCES["event_time_relative_window_max"] * window_T
        max_bracket = float(current["max_first_saved_bracket_width_s"])
        result[variant] = {
            "reference_variant": reference_variant,
            "time_end_absolute_difference_s": time_end_delta,
            "dt_max_absolute_difference_s": endpoint_delta,
            "endpoint_status": "reported_without_frozen_endpoint_gate",
            "event_time_relative_window_budget_s": event_budget,
            "max_first_saved_bracket_width_s": max_bracket,
            "event_bracket_status": (
                "within_event_time_diagnostic_budget"
                if max_bracket <= event_budget
                else "exceeds_event_time_diagnostic_budget"
            ),
            "accepted_saved_crossing_count_difference": count_delta,
            "later_saved_crossing_count_difference": later_delta,
            "integration_output_allocation_each_fraction": FROZEN_TOLERANCES["integration_output_allocation_each_fraction"],
            "allocation_status": "diagnostic bookkeeping target only; V3 does not decompose integration/output allocation",
            "crossing_count_interpretation": "saved-record diagnostic difference only; no continuous event or physical-flux claim",
            "continuous_event_time": "unknown",
            "qualification_credit": "not_granted",
        }
    return result


def validate(*, report_path: Path, manifest_path: Path, output_path: Path) -> dict[str, Any]:
    report = _load_object(report_path)
    manifest = _load_object(manifest_path)
    if report.get("schema") != V3_REPORT_SCHEMA:
        raise ValidationError("input report is not F4 V3")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValidationError("input manifest is not F4 V3")
    if report.get("manifest", {}).get("path") != str(manifest_path) or report.get("manifest", {}).get("sha256") != sha256_file(manifest_path):
        raise ValidationError("V3 report does not bind the supplied manifest")
    if report.get("source_evidence") != manifest.get("source_evidence"):
        raise ValidationError("V3 report does not preserve the manifest source-evidence binding")
    artifacts = report.get("artifacts")
    manifest_artifacts = {item["artifact_id"]: item for item in manifest.get("artifacts", []) if isinstance(item, Mapping)}
    expected_artifact_ids = {item["artifact_id"] for item in manifest.get("artifacts", []) if isinstance(item, Mapping)}
    if not isinstance(artifacts, list) or set(manifest_artifacts) != {item.get("artifact_id") for item in artifacts} or set(manifest_artifacts) != expected_artifact_ids:
        raise ValidationError("V3 report does not cover exactly the five expected variants")
    summaries: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise ValidationError("V3 artifact report is not an object")
        artifact_id = str(artifact["artifact_id"])
        item = manifest_artifacts[artifact_id]
        variant = f"{item['resolution']}-{item['time_variant']}"
        if artifact.get("case_id") != item.get("case_id") or artifact.get("resolution") != item.get("resolution") or artifact.get("time_variant") != item.get("time_variant"):
            raise ValidationError(f"V3 artifact identity mismatch: {artifact_id}")
        if artifact.get("physical_binding_sha256") != item.get("physical_binding_sha256"):
            raise ValidationError(f"V3 physical binding mismatch: {artifact_id}")
        if artifact.get("trajectory_hdf5", {}).get("declared_sha256") != item["trajectory_hdf5"]["sha256"] or artifact.get("trajectory_hdf5", {}).get("worker_rehashed") is not False:
            raise ValidationError(f"H5 declaration/re-hash policy mismatch: {artifact_id}")
        for key in ("metadata", "conversion_report", "conversion_receipt", "source_regions"):
            declared = item.get(key)
            observed = artifact.get(key)
            if not isinstance(declared, Mapping) or not isinstance(observed, Mapping) or observed.get("path") != declared.get("path") or observed.get("sha256") != declared.get("sha256"):
                raise ValidationError(f"V3 artifact source binding mismatch for {key}: {artifact_id}")
        declared_binding = item.get("source_binding")
        observed_binding = artifact.get("source_binding")
        if not isinstance(declared_binding, Mapping) or not isinstance(observed_binding, Mapping):
            raise ValidationError(f"V3 artifact source_binding missing: {artifact_id}")
        for key, value in declared_binding.items():
            if not isinstance(value, Mapping) or "path" not in value:
                continue
            observed = observed_binding.get(key)
            if not isinstance(observed, Mapping) or observed.get("path") != value.get("path") or observed.get("sha256") != value.get("sha256"):
                raise ValidationError(f"V3 artifact source_binding mismatch for {key}: {artifact_id}")
        curve = artifact.get("curve")
        labels = artifact.get("labels")
        if not isinstance(curve, Mapping) or not isinstance(labels, Mapping):
            raise ValidationError(f"V3 output paths missing: {artifact_id}")
        curve_path = Path(str(curve.get("path")))
        labels_path = Path(str(labels.get("path")))
        if not curve_path.is_file() or not labels_path.is_file():
            raise ValidationError(f"V3 output sidecar missing: {artifact_id}")
        if curve.get("sha256") != sha256_file(curve_path) or labels.get("sha256") != sha256_file(labels_path):
            raise ValidationError(f"V3 output sidecar SHA mismatch: {artifact_id}")
        label_object = _load_object(labels_path)
        summary = _artifact_summary(artifact, csv_path=curve_path, labels=label_object)
        summary["variant"] = variant
        summaries[variant] = summary
    if set(summaries) != set(EXPECTED_VARIANTS):
        raise ValidationError(f"unexpected V3 variant labels: {sorted(summaries)}")
    result = {
        "schema": SCHEMA,
        "status": "completed_source_bound_v3_diagnostic_validation",
        "report": {"path": str(report_path), "sha256": sha256_file(report_path)},
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "artifacts": summaries,
        "frozen_tolerances": FROZEN_TOLERANCES,
        "tolerance_basis": {
            "status": "frozen_Stage2_thresholds_reported_as_diagnostics_only",
            "whole_initial_unknown_mass_screen": "0.003 of frozen whole-initial fluid mass; this is a missing-identity screen, not physical-fate closure",
            "mk_region_flux_screen": "0.03 of frozen whole-initial fluid mass for source/MK/region observations; V3 cannot establish continuous flux",
            "mass_bands": "preferred <=1%; marginal >1% and <=2%; hard >2%; bands classify observations and do not qualify a task",
            "position_band": "0.02 domain length; not evaluated because V3 emits no coordinates or COM",
            "velocity_kinetic_energy_band": "5% against a nonzero reference for saved momentum/kinetic-energy proxies only",
            "event_time_band": "1% of the saved time window for saved first-bracket width only; continuous event timing remains unknown",
            "integration_output_allocation": "one quarter each as frozen bookkeeping target; V3 has no decomposition that can verify this allocation",
            "endpoint_seconds": "no independent endpoint-second gate is applied",
            "qualification_credit": "not granted",
        },
        "comparison_reference": REFERENCE_VARIANT,
        "spatial_proxy": _compare_group(summaries, REFERENCE_VARIANT, "spatial_proxy_terminal", group_label="saved-frame spatial mass/aperture proxy"),
        "integral": _compare_group(summaries, REFERENCE_VARIANT, "integrals_saved_trapezoid", group_label="saved-frame trapezoidal mass/momentum/energy proxy"),
        "region_flux": _region_flux_comparison(summaries, REFERENCE_VARIANT),
        "save_sampling": _sampling_comparison(summaries, REFERENCE_VARIANT),
        "claim_boundary": {
            "spatial_coordinates_or_COM": "not available in V3 CSV; spatial_proxy is mass/aperture occupancy only",
            "position_relative_domain_length": "not evaluated; no coordinate or domain-length field is present",
            "velocity_kinetic_energy": "saved momentum/kinetic-energy diagnostics only; nonzero-reference 5% band does not bound force or dynamics",
            "continuous_event_time": "unknown",
            "physical_flux": "unknown",
            "physical_fate": "unknown",
            "unknown_mass_screen": "screen only; physical destination and dynamics remain unknown",
            "mk_region_flux_screen": "source/MK/region saved observations only; no net-flux or fate credit",
            "integration_output_allocation": "frozen one-quarter bookkeeping target is not measured by this output",
            "calibration_credit": "not_granted",
            "q_n": "not_assessed",
            "q_e": "not_assessed",
            "all_frozen_thresholds_are_qualification_gates": False,
            "qualification_credit": "not_granted",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output"] = {"path": str(output_path), "sha256": sha256_file(output_path)}
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = validate(report_path=args.report, manifest_path=args.manifest, output_path=args.output)
    print(json.dumps({"status": result["status"], "output": result["output"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
