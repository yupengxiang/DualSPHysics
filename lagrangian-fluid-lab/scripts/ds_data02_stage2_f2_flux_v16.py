#!/usr/bin/env python3
"""Forward correction for the v15 F2 net-flux accounting.

The v15 full replay is immutable.  Its event summary reports the known
endpoint subtotal separately but labels ``net_flux_interval_kg`` as only the
unknown contribution.  This module creates a v16 forward view in which the
known subtotal and the unknown endpoint contribution are explicit, and the
total net interval is their sum.  Hidden within-bracket recrossings remain
unbounded for gross flux.

The forward sidecar binds to the completed v15 JSON report by content SHA. It
does not read trajectory HDF5 and does not change the v15 report.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


REQUEST_SCHEMA = "ds02.stage2.f2-s1-flux-forward-request.v16"
RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v16"
SIDECAR_SCHEMA = "ds02.stage2.f2-s1-flux-forward-sidecar.v16"
V15_RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v15"


class FluxV16BindingError(ValueError):
    """Raised when a v15 report or flux accounting contract is malformed."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FluxV16BindingError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise FluxV16BindingError(f"{name} must be finite")
    return result


def _drop_key(value: Any, key_to_drop: str) -> Any:
    if isinstance(value, Mapping):
        return {key: _drop_key(item, key_to_drop)
                for key, item in value.items() if key != key_to_drop}
    if isinstance(value, list):
        return [_drop_key(item, key_to_drop) for item in value]
    return value


def _motion_binding_v16(result: Mapping[str, Any]) -> dict[str, Any]:
    semantics = result.get("motion_completion_semantics")
    if not isinstance(semantics, Mapping):
        raise FluxV16BindingError("v15 motion completion semantics are missing")
    rotation_duration = _finite(semantics.get("rotation_duration_s"), "rotation_duration_s")
    rotation_stop = _finite(semantics.get("rotation_stop_s"), "rotation_stop_s")
    finish = _finite(semantics.get("finish_s"), "finish_s")
    if (not math.isclose(rotation_duration, 0.9, rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(rotation_stop, 1.4, rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(finish, 4.0, rel_tol=0.0, abs_tol=1e-12) or
            semantics.get("table_coverage_s") != [0.0, 4.0] or
            not math.isclose(_finite(semantics.get("finish_angle_deg"), "finish_angle_deg"),
                             -105.0, rel_tol=0.0, abs_tol=1e-12)):
        raise FluxV16BindingError("v15 motion semantics do not match the frozen F2 source contract")
    return {
        "source_role": "motion_dat",
        "angles_units": "degrees",
        "start_angle_deg": _finite(semantics.get("start_angle_deg"), "start_angle_deg"),
        "finish_angle_deg": _finite(semantics.get("finish_angle_deg"), "finish_angle_deg"),
        "rotation_duration_s": rotation_duration,
        "static_hold_start_s": _finite(semantics.get("static_hold_start_s"), "static_hold_start_s"),
        "rotation_stop_s": rotation_stop,
        "table_coverage_s": [0.0, finish],
        "completion_policy": "hold_last_pose_zero_angular_velocity_after_finish",
        "finish_inclusive": True,
        "case_token_semantics": "ROT090 denotes rotation_duration_s=0.9; it is not a numeric angle",
        "status": "SOURCE_BOUND_DEVELOPMENT_UNKNOWN",
    }


def correct_event_summary(event_summary: Mapping[str, Any], *, unknown_endpoint_mass_kg: float) -> dict[str, Any]:
    """Correct endpoint net-flux interval naming without bounding hidden gross flux.

    ``known_endpoint_subtotal`` is the signed sum from particles whose final
    membership is observed.  ``unknown_endpoint_mass`` is a nonnegative
    contribution interval from missing/unknown endpoint identities.  The
    total interval is therefore ``[known, known + unknown]``.  This is not a
    gross-flux interval: hidden recrossings between saved frames can make
    gross flux arbitrarily larger than the saved crossing subtotal.
    """
    if not isinstance(event_summary, Mapping):
        raise FluxV16BindingError("event_summary must be an object")
    known = _finite(event_summary.get("net_flux_known_endpoint_subtotal_kg"),
                    "net_flux_known_endpoint_subtotal_kg")
    unknown = _finite(unknown_endpoint_mass_kg, "unknown_endpoint_mass_kg")
    if unknown < 0:
        raise FluxV16BindingError("unknown endpoint mass must be nonnegative")
    corrected = dict(event_summary)
    for legacy in ("net_flux_interval_kg", "net_flux_mass_kg", "net_flux_unknown_interval_kg"):
        corrected.pop(legacy, None)
    corrected["net_flux_known_endpoint_subtotal_kg"] = known
    corrected["net_flux_unknown_endpoint_contribution_interval_kg"] = [0.0, unknown]
    corrected["net_flux_total_interval_kg"] = [known, known + unknown]
    corrected["net_flux_total_interval_status"] = (
        "KNOWN_ENDPOINT_SUBTOTAL_PLUS_UNKNOWN_ENDPOINT_MASS; signed endpoint net interval"
    )
    corrected["net_flux_status"] = (
        "KNOWN_ENDPOINT_SUBTOTAL_PLUS_UNKNOWN_ENDPOINT_CONTRIBUTION; "
        "gross hidden recrossings remain UNKNOWN"
    )
    corrected["gross_flux_mass_kg"] = None
    corrected["gross_flux_status"] = "UNKNOWN_HIDDEN_WITHIN_SAVED_BRACKET_RECROSSINGS"
    corrected["flux_accounting_scope"] = {
        "known_endpoint_subtotal": "signed observed endpoint membership subtotal",
        "unknown_endpoint_contribution": "[0, missing/unknown endpoint mass]",
        "total_net_interval": "known subtotal plus unknown endpoint contribution",
        "gross_flux": "unbounded/UNKNOWN without a no-hidden-recross proof",
    }
    return corrected


def forward_result(result: Mapping[str, Any], *, unknown_endpoint_mass_kg: float) -> dict[str, Any]:
    """Return an in-memory v16 view while preserving source identity and UNKNOWN quality."""
    if not isinstance(result, Mapping) or result.get("schema") != V15_RESULT_SCHEMA:
        raise FluxV16BindingError("a v15 replay result is required")
    event_summary = result.get("event_summary")
    if not isinstance(event_summary, Mapping):
        raise FluxV16BindingError("v15 event_summary is missing")
    view = _drop_key(copy.deepcopy(dict(result)), "case_name_angle_conflict")
    view["schema"] = RESULT_SCHEMA
    view["event_summary"] = correct_event_summary(
        event_summary, unknown_endpoint_mass_kg=unknown_endpoint_mass_kg)
    view["moving_source_motion_binding"] = _motion_binding_v16(view)
    view["replay_implementation"] = "v16_flux_forward_sidecar_over_immutable_v15_result"
    view["forward_correction"] = {
        "source_result_schema": V15_RESULT_SCHEMA,
        "legacy_fields_removed": [
            "event_summary.net_flux_interval_kg",
            "event_summary.net_flux_mass_kg",
            "event_summary.net_flux_unknown_interval_kg",
            "moving_source_motion_binding.case_name_angle_conflict",
        ],
        "gross_hidden_recrossings_remain_unknown": True,
    }
    view["quality"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                        "qualification": "UNKNOWN"}
    return view


def build_sidecar(report_path: Path | str, output_path: Path | str | None = None) -> dict[str, Any]:
    """Read one completed v15 JSON report and write a small corrected sidecar."""
    report_path = Path(report_path).expanduser().resolve()
    if not report_path.is_file():
        raise FluxV16BindingError(f"v15 report is missing: {report_path}")
    report = json.loads(report_path.read_text())
    if report.get("schema") != V15_RESULT_SCHEMA:
        raise FluxV16BindingError("report is not the expected v15 replay result")
    denominator = report.get("initial_mass_denominator")
    if not isinstance(denominator, Mapping):
        raise FluxV16BindingError("initial_mass_denominator is required")
    initial_missing = _finite(denominator.get("initial_missing_mass_kg"), "initial_missing_mass_kg")
    later_missing = _finite(denominator.get("later_missing_mass_kg"), "later_missing_mass_kg")
    if initial_missing != 0.0 or later_missing < 0.0:
        raise FluxV16BindingError("F2 v16 requires no initially absent mass and nonnegative later missing mass")
    if denominator.get("later_missing_unique_count") != 3:
        raise FluxV16BindingError("F2 v16 source contract requires the three later-missing IDs")
    source_binding = report.get("source_binding")
    if not isinstance(source_binding, Mapping):
        raise FluxV16BindingError("source_binding is required")
    event_summary = report.get("event_summary")
    corrected = correct_event_summary(event_summary, unknown_endpoint_mass_kg=later_missing)
    motion = _motion_binding_v16(report)
    sidecar: dict[str, Any] = {
        "schema": SIDECAR_SCHEMA,
        "request_schema": REQUEST_SCHEMA,
        "status": "SOURCE_BOUND_DEVELOPMENT_UNKNOWN",
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_report": {
            "path": str(report_path),
            "schema": report.get("schema"),
            "sha256": sha256(report_path),
            "runner_status": report.get("runner_status"),
            "trajectory_read": report.get("trajectory_read"),
        },
        "source_binding": dict(source_binding),
        "initial_mass_binding": {
            "denominator_kg": _finite(denominator.get("denominator_kg"), "denominator_kg"),
            "initial_missing_mass_kg": initial_missing,
            "later_missing_mass_kg": later_missing,
            "later_missing_unique_count": 3,
            "unknown_endpoint_contribution_source": "v15.initial_mass_denominator.later_missing_mass_kg",
            "denominator_unchanged": True,
        },
        "motion_binding": motion,
        "event_summary_correction": {
            "known_endpoint_subtotal_kg": corrected["net_flux_known_endpoint_subtotal_kg"],
            "unknown_endpoint_contribution_interval_kg": corrected["net_flux_unknown_endpoint_contribution_interval_kg"],
            "total_net_interval_kg": corrected["net_flux_total_interval_kg"],
            "gross_flux_mass_kg": None,
            "gross_flux_status": corrected["gross_flux_status"],
            "status": corrected["net_flux_total_interval_status"],
            "observed_gross_flux_mass_kg": corrected.get("observed_gross_flux_mass_kg"),
            "legacy_fields_removed": [
                "net_flux_interval_kg", "net_flux_mass_kg", "net_flux_unknown_interval_kg",
            ],
        },
        "preserved_observations": {
            "label_counts": corrected.get("label_counts"),
            "receiver_final_destination_mass_kg": corrected.get("receiver_final_destination_mass_kg"),
            "residence_known_mass_time_kg_s": corrected.get("residence_known_mass_time_kg_s"),
            "unknown_flux_intervals_count": len(corrected.get("unknown_flux_intervals", [])),
        },
        "semantic_correction": {
            "deprecated_case_name_angle_conflict_removed": True,
            "duration_semantics": "rotation_duration_s=0.9; rotation_stop_s=1.4; XML/motion table coverage=0..4 s",
            "completion_semantics": "after finish=4, explicit last-pose hold with zero angular velocity",
            "no_hdf5_read": True,
            "source_report_only": True,
        },
    }
    sidecar["sha256"] = _canonical_sha256(sidecar)
    if output_path is not None:
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return sidecar


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        sidecar = build_sidecar(args.report, args.output)
    except (OSError, json.JSONDecodeError, FluxV16BindingError) as error:
        parser.error(str(error))
    print(json.dumps({"output": str(args.output), "sha256": sidecar["sha256"],
                      "total_net_interval_kg": sidecar["event_summary_correction"]["total_net_interval_kg"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
