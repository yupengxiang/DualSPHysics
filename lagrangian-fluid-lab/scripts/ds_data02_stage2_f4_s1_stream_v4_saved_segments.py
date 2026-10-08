#!/usr/bin/env python3
"""Derive source/MK saved-segment labels from a completed F4-S1 V3 stream.

This forward-only consumer reads the V3 report, manifest, saved CSV rows,
saved event labels, and source/control/geometry sidecars.  It never opens the
declared trajectory HDF5 or any BI4/PartOut file.  It reports event-weighted
and unique-identity crossing masses separately, including first/later and
positive/negative directions, plus saved-frame aperture occupancy and
residence.  A V3 event bracket is an adjacent saved-record interval; it is
not a continuous first-arrival time and it cannot reveal hidden re-crossings.

The output is a source-bound diagnostic product.  Physical net flux, fate,
continuous transport, and native-exclusion impact remain UNKNOWN until a
separately guarded trajectory observer supplies the missing evidence.
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


SCHEMA = "ds02.stage2.f4-s1-stream.v4-saved-segments"
REPORT_SCHEMA = "ds02.stage2.f4-s1-stream.v3"
MANIFEST_SCHEMA = "ds02.stage2.f4-s1-stream-manifest.v3"
EXPECTED_ARTIFACT_PREFIX = "f4_drop_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000-"
EXPECTED_VARIANTS = ("coarse-native", "medium-native", "fine-native", "fine-half_dt", "fine-half_save")
EXPECTED_VARIANT = {
    "coarse-native": ("coarse", "native"),
    "medium-native": ("medium", "native"),
    "fine-native": ("fine", "native"),
    "fine-half_dt": ("fine", "half_dt"),
    "fine-half_save": ("fine", "half_save"),
}
SAVED_TIME_REFERENCE = "fine-half_save"
INTEGRATION_REFERENCE = "fine-native"
SOURCE_BINDING_KEYS = (
    "definition_xml",
    "gencase_receipt",
    "generated_xml",
    "owner_metadata_source",
    "solver_log",
    "solver_receipt",
)


class SavedSegmentError(RuntimeError):
    """Raised when a V3 source-bound diagnostic input is malformed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SavedSegmentError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise SavedSegmentError(f"expected JSON object: {path}")
    return value


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def float_field(row: Mapping[str, Any], field: str, path: Path, index: int) -> float:
    value = row.get(field)
    if not finite(value):
        raise SavedSegmentError(f"non-finite {field} at {path}:{index}")
    return float(value)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SavedSegmentError(f"missing V3 CSV: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SavedSegmentError(f"V3 CSV has no saved rows: {path}")
    times = [float_field(row, "time_s", path, index) for index, row in enumerate(rows)]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise SavedSegmentError(f"V3 saved times are not strictly increasing: {path}")
    return rows


def verify_path_entry(value: Any, label: str, *, require_exists: bool = True) -> tuple[Path, str]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
        raise SavedSegmentError(f"{label} must contain path and sha256")
    path = Path(str(value["path"]))
    expected = str(value["sha256"])
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected.lower()):
        raise SavedSegmentError(f"{label}.sha256 is not a SHA-256 digest")
    if require_exists:
        if not path.is_file():
            raise SavedSegmentError(f"{label} is missing: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise SavedSegmentError(f"{label} SHA mismatch: expected {expected}, got {actual}: {path}")
    return path, expected


def _same_path_hash(left: Any, right: Any, label: str) -> None:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise SavedSegmentError(f"{label} binding is not an object")
    if left.get("path") != right.get("path") or left.get("sha256") != right.get("sha256"):
        raise SavedSegmentError(f"{label} path/hash differs between report and manifest")


def _parse_typed_key(value: str) -> tuple[int, int]:
    try:
        zone, idp = value.split(":", 1)
        return int(zone), int(idp)
    except (TypeError, ValueError) as exc:
        raise SavedSegmentError(f"invalid typed identity key: {value!r}") from exc


def _validate_crossing_counts(label: str, data: Mapping[str, Any]) -> None:
    fields = (
        "candidate_plane_crossings",
        "outside_aperture_crossings",
        "accepted_saved_crossings",
        "first_saved_crossings",
        "later_saved_crossings",
        "positive_saved_crossings",
        "negative_saved_crossings",
    )
    counts = {field: int(data.get(field, -1)) for field in fields}
    if min(counts.values()) < 0:
        raise SavedSegmentError(f"negative or missing crossing count: {label}")
    if counts["first_saved_crossings"] + counts["later_saved_crossings"] != counts["accepted_saved_crossings"]:
        raise SavedSegmentError(f"first/later count mismatch: {label}")
    if counts["positive_saved_crossings"] + counts["negative_saved_crossings"] != counts["accepted_saved_crossings"]:
        raise SavedSegmentError(f"positive/negative count mismatch: {label}")
    if counts["candidate_plane_crossings"] != counts["accepted_saved_crossings"] + counts["outside_aperture_crossings"]:
        raise SavedSegmentError(f"candidate/aperture count mismatch: {label}")


def _validate_first_bracket(value: Any, label: str) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2 or not all(finite(item) for item in value) or float(value[1]) < float(value[0]):
        raise SavedSegmentError(f"invalid saved-time bracket: {label}")
    return [float(value[0]), float(value[1])]


def _validate_source_event_data(source_data: Mapping[str, Any], *, whole_mass: float) -> None:
    for label, raw in source_data.items():
        if not isinstance(raw, Mapping):
            raise SavedSegmentError(f"source event data is not an object: {label}")
        _validate_crossing_counts(str(label), raw)
        accepted_mass = raw.get("accepted_saved_initial_mass_kg")
        if not finite(accepted_mass) or float(accepted_mass) < 0 or float(accepted_mass) / whole_mass > 1.0e6:
            raise SavedSegmentError(f"invalid accepted source mass: {label}")
        per_id = raw.get("per_typed_identity")
        if not isinstance(per_id, Mapping):
            raise SavedSegmentError(f"missing per-identity crossing ledger: {label}")
        total = 0
        for identity, value in per_id.items():
            if not isinstance(value, Mapping):
                raise SavedSegmentError(f"typed identity ledger is not an object: {label}/{identity}")
            _parse_typed_key(str(identity))
            total_count = int(value.get("total_saved_crossings", -1))
            first_count = int(value.get("first_saved_crossings", -1))
            later_count = int(value.get("later_saved_crossings", -1))
            positive_count = int(value.get("positive_saved_crossings", -1))
            negative_count = int(value.get("negative_saved_crossings", -1))
            if min(total_count, first_count, later_count, positive_count, negative_count) < 0:
                raise SavedSegmentError(f"invalid identity crossing count: {label}/{identity}")
            if first_count + later_count != total_count or positive_count + negative_count != total_count:
                raise SavedSegmentError(f"identity crossing count mismatch: {label}/{identity}")
            if total_count and not finite(value.get("saved_initial_mass_kg")):
                raise SavedSegmentError(f"identity mass is not finite: {label}/{identity}")
            if total_count and float(value["saved_initial_mass_kg"]) < 0:
                raise SavedSegmentError(f"identity mass is negative: {label}/{identity}")
            _validate_first_bracket(value.get("first_bracket_s"), f"{label}/{identity}")
            later_brackets = value.get("later_brackets_s", [])
            if not isinstance(later_brackets, list) or len(later_brackets) != later_count:
                raise SavedSegmentError(f"later bracket count mismatch: {label}/{identity}")
            for bracket_index, bracket in enumerate(later_brackets):
                _validate_first_bracket(bracket, f"{label}/{identity}/later[{bracket_index}]")
            total += total_count
        if total != int(raw["accepted_saved_crossings"]):
            raise SavedSegmentError(f"per-identity total differs from source total: {label}")


def validate_inputs(report_path: Path, manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    report = load_object(report_path)
    manifest = load_object(manifest_path)
    if report.get("schema") != REPORT_SCHEMA or manifest.get("schema") != MANIFEST_SCHEMA:
        raise SavedSegmentError("inputs are not F4-S1 V3 report/manifest")
    if report.get("manifest", {}).get("path") != str(manifest_path) or report.get("manifest", {}).get("sha256") != sha256_file(manifest_path):
        raise SavedSegmentError("V3 report does not bind the supplied manifest")
    if report.get("source_evidence") != manifest.get("source_evidence"):
        raise SavedSegmentError("V3 report does not preserve source_evidence")
    verify_path_entry(manifest.get("source_evidence"), "manifest.source_evidence")
    operator_contract = manifest.get("operator_contract")
    if not isinstance(operator_contract, Mapping) or operator_contract.get("schema") != "ds02.stage2.f4-typed-operator.v3":
        raise SavedSegmentError("manifest operator contract is not the source V3 contract")
    if operator_contract.get("mass_denominator") != "whole_initial_fluid_mass_kg":
        raise SavedSegmentError("saved-segment masses must use the whole initial fluid mass denominator")
    manifest_artifacts = {str(item["artifact_id"]): item for item in manifest.get("artifacts", []) if isinstance(item, Mapping)}
    report_artifacts = {str(item["artifact_id"]): item for item in report.get("artifacts", []) if isinstance(item, Mapping)}
    if set(manifest_artifacts) != set(report_artifacts) or set(report_artifacts) != {
        f"f4_drop_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000-{variant}" for variant in EXPECTED_VARIANTS
    }:
        raise SavedSegmentError("V3 report/manifest does not cover exactly the five expected variants")
    validated: dict[str, dict[str, Any]] = {}
    for artifact_id in sorted(manifest_artifacts):
        item = manifest_artifacts[artifact_id]
        artifact = report_artifacts[artifact_id]
        if not artifact_id.startswith(EXPECTED_ARTIFACT_PREFIX):
            raise SavedSegmentError(f"unexpected F4 artifact id: {artifact_id}")
        variant = artifact_id[len(EXPECTED_ARTIFACT_PREFIX):]
        resolution, time_variant = EXPECTED_VARIANT[variant]
        if artifact.get("case_id") != item.get("case_id") or artifact.get("resolution") != resolution or artifact.get("time_variant") != time_variant:
            raise SavedSegmentError(f"artifact identity mismatch: {artifact_id}")
        if artifact.get("physical_binding_sha256") != item.get("physical_binding_sha256"):
            raise SavedSegmentError(f"physical binding mismatch: {artifact_id}")
        trajectory = artifact.get("trajectory_hdf5")
        declared_trajectory = item.get("trajectory_hdf5")
        if not isinstance(trajectory, Mapping) or trajectory.get("declared_sha256") != declared_trajectory.get("sha256") or trajectory.get("worker_rehashed") is not False:
            raise SavedSegmentError(f"trajectory declaration/re-hash policy mismatch: {artifact_id}")
        for key in ("metadata", "conversion_report", "conversion_receipt", "source_regions"):
            _same_path_hash(artifact.get(key), item.get(key), f"{artifact_id}.{key}")
            verify_path_entry(item[key], f"{artifact_id}.{key}")
        report_binding = artifact.get("source_binding")
        manifest_binding = item.get("source_binding")
        if not isinstance(report_binding, Mapping) or not isinstance(manifest_binding, Mapping):
            raise SavedSegmentError(f"missing source binding: {artifact_id}")
        for key in SOURCE_BINDING_KEYS:
            _same_path_hash(report_binding.get(key), manifest_binding.get(key), f"{artifact_id}.source_binding.{key}")
            verify_path_entry(manifest_binding[key], f"{artifact_id}.source_binding.{key}")
        curve = artifact.get("curve")
        labels = artifact.get("labels")
        curve_path, _ = verify_path_entry(curve, f"{artifact_id}.curve")
        labels_path, _ = verify_path_entry(labels, f"{artifact_id}.labels")
        label_object = load_object(labels_path)
        source_data = artifact.get("source_event_data")
        if not isinstance(source_data, Mapping) or label_object != source_data:
            raise SavedSegmentError(f"labels differ from report source_event_data: {artifact_id}")
        whole_mass = float(artifact.get("whole_initial_fluid_mass_kg", 0.0))
        if not finite(whole_mass) or whole_mass <= 0:
            raise SavedSegmentError(f"invalid whole initial mass: {artifact_id}")
        _validate_source_event_data(source_data, whole_mass=whole_mass)
        source_initial = artifact.get("source_initial_mass_kg")
        if not isinstance(source_initial, Mapping) or any(not finite(value) or float(value) < 0 for value in source_initial.values()):
            raise SavedSegmentError(f"invalid source initial mass map: {artifact_id}")
        regions_path, _ = verify_path_entry(item["source_regions"], f"{artifact_id}.source_regions")
        regions = load_object(regions_path)
        if regions.get("schema") != "ds02.f4.source-regions.v1" or regions.get("physical_binding_sha256") != item.get("physical_binding_sha256"):
            raise SavedSegmentError(f"source-regions identity mismatch: {artifact_id}")
        if not isinstance(regions.get("source_to_native_mk"), Mapping):
            raise SavedSegmentError(f"source-regions MK mapping missing: {artifact_id}")
        rows = read_csv(curve_path)
        if int(artifact.get("frames", -1)) != len(rows):
            raise SavedSegmentError(f"CSV frame count mismatch: {artifact_id}")
        validated[variant] = {
            "artifact": artifact,
            "manifest": item,
            "curve_path": curve_path,
            "labels": label_object,
            "rows": rows,
            "regions": regions,
            "whole_initial_mass_kg": whole_mass,
            "source_initial_mass_kg": {str(key): float(value) for key, value in source_initial.items()},
            "source_binding": {key: {"path": str(manifest_binding[key]["path"]), "sha256": str(manifest_binding[key]["sha256"])} for key in SOURCE_BINDING_KEYS},
        }
    return report, manifest, validated


def _identity_mass_record(identity: str, value: Mapping[str, Any]) -> dict[str, Any]:
    total = int(value["total_saved_crossings"])
    saved_mass = float(value.get("saved_initial_mass_kg", 0.0))
    per_event_mass = saved_mass / total if total else 0.0
    first_count = int(value["first_saved_crossings"])
    later_count = int(value["later_saved_crossings"])
    positive_count = int(value["positive_saved_crossings"])
    negative_count = int(value["negative_saved_crossings"])
    first_direction = value.get("first_direction")
    first_positive_count = first_count if first_direction == "positive_x" else 0
    first_negative_count = first_count if first_direction == "negative_x" else 0
    direction_known = first_count == 0 or first_direction in {"positive_x", "negative_x"}
    positive_mass = positive_count * per_event_mass
    negative_mass = negative_count * per_event_mass
    first_positive_mass = first_positive_count * per_event_mass if direction_known else None
    first_negative_mass = first_negative_count * per_event_mass if direction_known else None
    later_positive_mass = positive_mass - first_positive_mass if first_positive_mass is not None else None
    later_negative_mass = negative_mass - first_negative_mass if first_negative_mass is not None else None
    zone, idp = _parse_typed_key(identity)
    return {
        "typed_identity": identity,
        "zone": zone,
        "idp": idp,
        "initial_mass_kg_reconstructed": per_event_mass,
        "mass_weight_basis": "saved_initial_mass_kg divided by this identity's saved event count; V3 has no separate event mass vector",
        "total_saved_crossings": total,
        "first_saved_crossings": first_count,
        "later_saved_crossings": later_count,
        "positive_saved_crossings": positive_count,
        "negative_saved_crossings": negative_count,
        "event_weighted_mass_kg": saved_mass,
        "event_weighted_positive_mass_kg": positive_mass,
        "event_weighted_negative_mass_kg": negative_mass,
        "event_weighted_net_transport_mass_kg": positive_mass - negative_mass,
        "unique_first_mass_kg": first_count * per_event_mass,
        "unique_first_positive_mass_kg": first_positive_mass,
        "unique_first_negative_mass_kg": first_negative_mass,
        "unique_first_net_transport_mass_kg": (first_positive_mass - first_negative_mass) if direction_known else None,
        "later_recross_mass_kg": later_count * per_event_mass,
        "later_positive_mass_kg": later_positive_mass,
        "later_negative_mass_kg": later_negative_mass,
        "later_net_transport_mass_kg": (later_positive_mass - later_negative_mass) if direction_known else None,
        "first_direction": first_direction,
        "first_direction_semantics": "saved segment direction; unknown if absent",
        "first_bracket_s": _validate_first_bracket(value.get("first_bracket_s"), f"{identity}.first"),
        "later_brackets_s": value.get("later_brackets_s", []),
        "continuous_event_time": "unknown",
        "hidden_recrossings": "unknown",
    }


def _source_summary(label: str, data: Mapping[str, Any], *, source_initial_mass: float, whole_mass: float) -> dict[str, Any]:
    identities = [_identity_mass_record(str(identity), value) for identity, value in sorted(data["per_typed_identity"].items())]
    def total(key: str) -> float:
        return float(sum(float(item[key]) for item in identities if item[key] is not None))
    accepted_mass = float(data["accepted_saved_initial_mass_kg"])
    first_mass = total("unique_first_mass_kg")
    later_mass = total("later_recross_mass_kg")
    positive_mass = total("event_weighted_positive_mass_kg")
    negative_mass = total("event_weighted_negative_mass_kg")
    first_positive = total("unique_first_positive_mass_kg")
    first_negative = total("unique_first_negative_mass_kg")
    later_positive = total("later_positive_mass_kg")
    later_negative = total("later_negative_mass_kg")
    first_brackets = [item["first_bracket_s"] for item in identities if item["first_bracket_s"] is not None]
    first_widths = [bracket[1] - bracket[0] for bracket in first_brackets]
    return {
        "source_label": label,
        "native_mk": None,
        "source_initial_mass_kg": source_initial_mass,
        "source_initial_mass_fraction_whole_initial": source_initial_mass / whole_mass,
        "candidate_plane_crossings": int(data["candidate_plane_crossings"]),
        "outside_aperture_crossings": int(data["outside_aperture_crossings"]),
        "accepted_saved_crossings": int(data["accepted_saved_crossings"]),
        "first_saved_crossings": int(data["first_saved_crossings"]),
        "later_saved_crossings": int(data["later_saved_crossings"]),
        "positive_saved_crossings": int(data["positive_saved_crossings"]),
        "negative_saved_crossings": int(data["negative_saved_crossings"]),
        "event_weighted_mass_kg": accepted_mass,
        "event_weighted_positive_mass_kg": positive_mass,
        "event_weighted_negative_mass_kg": negative_mass,
        "event_weighted_net_transport_mass_kg": positive_mass - negative_mass,
        "event_weighted_mass_fraction_whole_initial": accepted_mass / whole_mass,
        "event_weighted_net_fraction_whole_initial": (positive_mass - negative_mass) / whole_mass,
        "unique_first_identity_count": len(identities),
        "unique_first_mass_kg": first_mass,
        "unique_first_positive_mass_kg": first_positive,
        "unique_first_negative_mass_kg": first_negative,
        "unique_first_net_transport_mass_kg": first_positive - first_negative,
        "unique_first_mass_fraction_whole_initial": first_mass / whole_mass,
        "later_recross_mass_kg": later_mass,
        "later_positive_mass_kg": later_positive,
        "later_negative_mass_kg": later_negative,
        "later_net_transport_mass_kg": later_positive - later_negative,
        "later_recross_mass_fraction_whole_initial": later_mass / whole_mass,
        "repeated_event_mass_fraction": later_mass / accepted_mass if accepted_mass else 0.0,
        "mass_reconstruction_difference_kg": accepted_mass - sum(float(item["event_weighted_mass_kg"]) for item in identities),
        "first_bracket_count": len(first_brackets),
        "first_bracket_width_min_s": min(first_widths) if first_widths else None,
        "first_bracket_width_max_s": max(first_widths) if first_widths else None,
        "first_bracket_width_median_s": statistics.median(first_widths) if first_widths else None,
        "continuous_event_time": "unknown",
        "physical_flux": "unknown",
        "physical_fate": "unknown",
        "typed_identities": identities,
    }


def _occupancy_summary(label: str, rows: Sequence[Mapping[str, str]], path: Path) -> dict[str, Any]:
    mass_field = f"{label}_finite_aperture_mass_kg"
    particles_field = f"{label}_finite_aperture_particles"
    times = [float_field(row, "time_s", path, index) for index, row in enumerate(rows)]
    mass_values = [float_field(row, mass_field, path, index) for index, row in enumerate(rows)]
    particle_values = [float_field(row, particles_field, path, index) for index, row in enumerate(rows)]
    dt = [right - left for left, right in zip(times, times[1:])]
    occupied_rows = sum(value > 0 for value in particle_values)
    occupancy_seconds = sum(delta for delta, particles in zip(dt, particle_values[1:]) if particles > 0)
    right_hold_mass_time = sum(delta * mass for delta, mass in zip(dt, mass_values[1:]))
    trapezoid_mass_time = sum(delta * 0.5 * (left + right) for delta, left, right in zip(dt, mass_values, mass_values[1:]))
    window = times[-1] - times[0]
    return {
        "source_label": label,
        "saved_frame_count": len(rows),
        "saved_frames_with_aperture_particles": occupied_rows,
        "saved_frame_occupancy_fraction": occupied_rows / len(rows),
        "saved_interval_occupancy_seconds": occupancy_seconds,
        "saved_interval_occupancy_fraction": occupancy_seconds / window if window else 0.0,
        "saved_right_hold_residence_mass_time_kg_s": right_hold_mass_time,
        "saved_trapezoid_residence_mass_time_kg_s": trapezoid_mass_time,
        "saved_residence_mass_time_difference_kg_s": right_hold_mass_time - trapezoid_mass_time,
        "saved_time_window_s": [times[0], times[-1]],
        "continuous_occupancy": "unknown_between_saved_frames",
        "continuous_residence": "unknown_between_saved_frames",
    }


def _relative(value: float, reference: float) -> dict[str, float]:
    absolute = abs(value - reference)
    scale = max(abs(reference), 1.0e-12)
    return {"value": value, "reference": reference, "absolute_difference": absolute, "relative_difference": absolute / scale}


def _compare_saved_time(variants: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    reference = variants[SAVED_TIME_REFERENCE]
    result: dict[str, Any] = {}
    metrics = (
        "accepted_saved_crossings",
        "first_saved_crossings",
        "later_saved_crossings",
        "positive_saved_crossings",
        "negative_saved_crossings",
        "event_weighted_mass_kg",
        "event_weighted_positive_mass_kg",
        "event_weighted_negative_mass_kg",
        "event_weighted_net_transport_mass_kg",
        "unique_first_mass_kg",
        "unique_first_net_transport_mass_kg",
        "later_recross_mass_kg",
        "later_net_transport_mass_kg",
    )
    for variant, current in variants.items():
        if variant == SAVED_TIME_REFERENCE:
            continue
        sources: dict[str, Any] = {}
        for label, current_source in current["sources"].items():
            reference_source = reference["sources"][label]
            source_metrics: dict[str, Any] = {}
            for metric in metrics:
                source_metrics[metric] = _relative(float(current_source[metric]), float(reference_source[metric]))
            source_metrics["occupancy_seconds"] = _relative(
                float(current["occupancy"][label]["saved_interval_occupancy_seconds"]),
                float(reference["occupancy"][label]["saved_interval_occupancy_seconds"]),
            )
            source_metrics["right_hold_residence_mass_time_kg_s"] = _relative(
                float(current["occupancy"][label]["saved_right_hold_residence_mass_time_kg_s"]),
                float(reference["occupancy"][label]["saved_right_hold_residence_mass_time_kg_s"]),
            )
            source_metrics["first_bracket_width_max_s"] = _relative(
                float(current["sources"][label]["first_bracket_width_max_s"] or 0.0),
                float(reference["sources"][label]["first_bracket_width_max_s"] or 0.0),
            )
            sources[label] = source_metrics
        result[variant] = {
            "reference_variant": SAVED_TIME_REFERENCE,
            "sources": sources,
            "interpretation": "saved-time comparison only; adjacent saved segments do not identify hidden crossings or continuous event times",
            "physical_flux": "unknown",
            "qualification_credit": "not_granted",
        }
    return result


def _compare_integration(variants: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    reference = variants[INTEGRATION_REFERENCE]
    result: dict[str, Any] = {}
    for variant, current in variants.items():
        if variant == INTEGRATION_REFERENCE:
            continue
        sources: dict[str, Any] = {}
        for label in current["sources"]:
            cur = current["occupancy"][label]
            ref = reference["occupancy"][label]
            sources[label] = {
                "right_hold_residence_mass_time_kg_s": _relative(float(cur["saved_right_hold_residence_mass_time_kg_s"]), float(ref["saved_right_hold_residence_mass_time_kg_s"])),
                "trapezoid_residence_mass_time_kg_s": _relative(float(cur["saved_trapezoid_residence_mass_time_kg_s"]), float(ref["saved_trapezoid_residence_mass_time_kg_s"])),
                "occupancy_seconds": _relative(float(cur["saved_interval_occupancy_seconds"]), float(ref["saved_interval_occupancy_seconds"])),
            }
        result[variant] = {
            "reference_variant": INTEGRATION_REFERENCE,
            "sources": sources,
            "interpretation": "saved integration/output comparison only; no physical transport or allocation claim",
            "integration_output_allocation_each_fraction": 0.25,
            "qualification_credit": "not_granted",
        }
    return result


def analyze(*, report_path: Path, manifest_path: Path, output_path: Path) -> dict[str, Any]:
    report, manifest, inputs = validate_inputs(report_path, manifest_path)
    variants: dict[str, dict[str, Any]] = {}
    closure: dict[str, Any] = {}
    for variant in EXPECTED_VARIANTS:
        item = inputs[variant]
        artifact = item["artifact"]
        source_data = item["labels"]
        source_to_mk = {str(label): int(native_mk) for label, native_mk in item["regions"]["source_to_native_mk"].items()}
        sources: dict[str, Any] = {}
        occupancy: dict[str, Any] = {}
        for label, data in source_data.items():
            source = _source_summary(
                str(label),
                data,
                source_initial_mass=float(item["source_initial_mass_kg"].get(str(label), 0.0)),
                whole_mass=item["whole_initial_mass_kg"],
            )
            source["native_mk"] = source_to_mk.get(str(label))
            sources[str(label)] = source
            occupancy[str(label)] = _occupancy_summary(str(label), item["rows"], item["curve_path"])
        closure[variant] = {
            "physical_binding_sha256": artifact["physical_binding_sha256"],
            "control_family_id": item["manifest"]["source_identity"]["control_family_id"],
            "geometry_family_id": item["manifest"]["source_identity"]["geometry_family_id"],
            "lineage_group_id": item["manifest"]["source_identity"]["lineage_group_id"],
            "mass_policy": item["manifest"]["source_identity"]["mass_policy"],
            "source_to_native_mk": source_to_mk,
            "source_binding_files_sha_verified": True,
            "trajectory_h5_opened": False,
            "continuous_transport_owner": "not established by this saved-CSV consumer",
        }
        variants[variant] = {
            "whole_initial_mass_kg": item["whole_initial_mass_kg"],
            "saved_time_window_s": artifact["saved_time_window_s"],
            "sources": sources,
            "occupancy": occupancy,
            "source_control_geometry_closure": closure[variant],
        }
    closure_values = {tuple(value[key] for key in ("control_family_id", "geometry_family_id", "lineage_group_id", "mass_policy")) for value in closure.values()}
    result = {
        "schema": SCHEMA,
        "status": "completed_source_bound_saved_segment_diagnostic",
        "report": {"path": str(report_path), "sha256": sha256_file(report_path)},
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "source_control_geometry_closure": {
            "all_variants_source_hashes_verified": True,
            "same_control_geometry_lineage_tuple_across_variants": len(closure_values) == 1,
            "variant_closure": closure,
            "trajectory_h5_opened": False,
            "bi4_partout_opened": False,
        },
        "variants": variants,
        "saved_time_comparison": _compare_saved_time(variants),
        "integration_comparison": _compare_integration(variants),
        "mass_weight_semantics": {
            "event_weighted": "each accepted saved crossing contributes the identity's reconstructed initial particle mass, so later crossings are intentionally counted again",
            "unique_identity": "first saved crossing per (Zone,Idp) contributes once",
            "net_transport": "positive saved-segment mass minus negative saved-segment mass; not continuous net flux",
            "whole_initial_denominator": "all reported mass fractions use the variant's frozen whole initial fluid mass",
        },
        "upstream_v3_limitations": {
            "region_amount_gate": "V3/V2 region crossing amounts are retained as observations here; their current amount is not treated as a .03 error gate",
            "repeated_mass": "accepted_saved_initial_mass_kg accumulates repeated identity crossings and is not a net-flux error estimate",
            "unknown_mass_screen": "the .003 whole-initial unknown-identity screen is separate from source crossing amounts",
        },
        "claim_boundary": {
            "first_saved_bracket": "adjacent saved-record interval only",
            "continuous_first_arrival": "unknown",
            "hidden_recrossings": "unknown",
            "continuous_residence": "unknown between saved frames",
            "physical_flux": "unknown",
            "physical_fate": "unknown",
            "native_exclusion_impact": "unknown",
            "qualification_credit": "not_granted",
            "q_n": "not_assessed",
            "q_e": "not_assessed",
        },
        "next_scientific_evidence": {
            "task": "source-bound continuous transport/fate observer for F4-S1",
            "reuse": "this product supplies per-source/MK/identity saved brackets and sampling diagnostics",
            "required": [
                "guarded adjacent trajectory positions/velocities with exact (Zone,Idp) initial masses",
                "continuous segment or native event semantics for crossings and hidden re-crossings",
                "same owner/control/geometry lineage and explicit native-exclusion identity joins",
                "physical destination/fate evidence separate from numerical invalidity",
            ],
            "acceptance": "saved-segment labels may be accepted as diagnostics; no Q-N/Q-E/flux/fate credit until the required evidence is source-bound",
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
    result = analyze(report_path=args.report, manifest_path=args.manifest, output_path=args.output)
    print(json.dumps({"status": result["status"], "output": result["output"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
