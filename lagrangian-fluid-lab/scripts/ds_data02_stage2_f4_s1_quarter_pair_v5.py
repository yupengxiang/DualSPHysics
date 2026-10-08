#!/usr/bin/env python3
"""Validate the two admissible F4-S1 saved-output comparison pairs.

This forward-only consumer reads the completed V4 saved-segment report and
small F4-S2 provenance/terminal sidecars.  It deliberately compares only

* ``fine-native`` versus ``fine-half_save`` (same spatial recipe, changed
  saved-output cadence), and
* ``fine-native`` versus ``fine-half_dt`` (same spatial recipe, changed
  integration step control).

The coarse and medium variants are reported as excluded because their spatial
resolution changes; they are not treated as time samples.  Pair differences
are saved-frame diagnostics under the registered quarter-budget allocation.
They do not grant Q-I/Q-N/Q-E, continuous-event, flux, or physical-fate credit.
No HDF5, BI4, PartOut, or solver trajectory is opened.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f4-s1-quarter-pair-validator.v5"
V4_SCHEMA = "ds02.stage2.f4-s1-stream.v4-saved-segments"
EXPECTED_VARIANTS = ("coarse-native", "medium-native", "fine-native", "fine-half_dt", "fine-half_save")
PAIR_VARIANTS = {
    "save_sampling": ("fine-native", "fine-half_save"),
    "integration_step": ("fine-native", "fine-half_dt"),
}
PAIR_METRICS = (
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
    "saved_interval_occupancy_seconds",
    "saved_right_hold_residence_mass_time_kg_s",
    "saved_trapezoid_residence_mass_time_kg_s",
    "first_bracket_width_max_s",
    "first_bracket_width_median_s",
)
SOURCE_LABELS = ("pool", "falling_drop")
WHOLE_INITIAL_UNKNOWN_MAX = 0.003
WHOLE_INITIAL_REGION_DIFF_MAX = 0.03
QUARTER_BUDGET = 0.25


class QuarterPairError(RuntimeError):
    """Raised when a completed source-bound pair input is malformed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise QuarterPairError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise QuarterPairError(f"expected JSON object: {path}")
    return value


def require_file(path: Path, expected_sha256: str | None = None, *, label: str = "input") -> str:
    if not path.is_file():
        raise QuarterPairError(f"missing {label}: {path}")
    actual = sha256_file(path)
    if expected_sha256 is not None and actual != expected_sha256:
        raise QuarterPairError(f"{label} SHA mismatch: expected {expected_sha256}, got {actual}: {path}")
    return actual


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, label: str) -> float:
    if not _finite(value):
        raise QuarterPairError(f"{label} is not finite: {value!r}")
    return float(value)


def _same_tuple(left: Mapping[str, Any], right: Mapping[str, Any], fields: Sequence[str]) -> bool:
    return all(left.get(field) == right.get(field) for field in fields)


def _validate_v4_request(request_path: Path, worker_path: Path) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != "ds02.request.v1":
        raise QuarterPairError("V4 request has an unexpected schema")
    if request.get("family_id") != "F4" or request.get("case_id") != "STAGE2_F4_S1_SAVED_SEGMENT_LABELS_V4":
        raise QuarterPairError("V4 request is not the exact F4-S1 producer request")
    if request.get("source_consumption_policy", {}).get("trajectory_hdf5_opened") is not False:
        raise QuarterPairError("V4 request does not bind the no-H5 source policy")
    input_hashes = request.get("input_hashes")
    if not isinstance(input_hashes, Mapping):
        raise QuarterPairError("V4 request has no input hash map")
    expected_worker = input_hashes.get(str(worker_path))
    actual_worker = require_file(worker_path, label="V4 worker")
    if expected_worker != actual_worker:
        raise QuarterPairError("V4 request does not bind the supplied worker")
    return request


def _validate_v4_proof(
    proof_path: Path,
    report_path: Path,
    request_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    proof = load_json(proof_path)
    if not str(proof.get("status", "")).startswith("PASS_ACTUAL_F4_SAVED_SEGMENT"):
        raise QuarterPairError("V4 producer proof is not an actual PASS")
    if proof.get("report") != str(report_path) or proof.get("report_sha256") != sha256_file(report_path):
        raise QuarterPairError("V4 producer proof report path does not match the supplied report")
    if proof.get("request") != str(request_path) or proof.get("request_sha256") != sha256_file(request_path):
        raise QuarterPairError("V4 producer proof does not bind the supplied request")
    if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != sha256_file(receipt_path):
        raise QuarterPairError("V4 producer proof does not bind the supplied receipt")
    receipt = load_json(receipt_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise QuarterPairError("V4 producer receipt is not completed")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("H5_BI4_read_by_worker") is not False:
        raise QuarterPairError("V4 proof does not preserve its no-H5/BI4 scope")
    qualification = proof.get("scientific_qualification")
    if qualification != {"QE": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN"}:
        raise QuarterPairError("V4 proof carries an unexpected qualification claim")
    return proof


def _validate_v4_report(report_path: Path) -> dict[str, Any]:
    report = load_json(report_path)
    if report.get("schema") != V4_SCHEMA or report.get("status") != "completed_source_bound_saved_segment_diagnostic":
        raise QuarterPairError("supplied report is not the completed V4 saved-segment product")
    closure = report.get("source_control_geometry_closure")
    if not isinstance(closure, Mapping):
        raise QuarterPairError("V4 report has no source/control/geometry closure")
    if closure.get("all_variants_source_hashes_verified") is not True:
        raise QuarterPairError("V4 report source hashes are not verified")
    if closure.get("same_control_geometry_lineage_tuple_across_variants") is not True:
        raise QuarterPairError("V4 variants do not share a closed control/geometry lineage")
    if closure.get("trajectory_h5_opened") is not False or closure.get("bi4_partout_opened") is not False:
        raise QuarterPairError("V4 report is outside the saved-sidecar scope")
    variants = report.get("variants")
    if not isinstance(variants, Mapping) or set(variants) != set(EXPECTED_VARIANTS):
        raise QuarterPairError("V4 report does not contain exactly the five registered variants")
    for variant in EXPECTED_VARIANTS:
        item = variants[variant]
        if not isinstance(item, Mapping) or not isinstance(item.get("sources"), Mapping) or not isinstance(item.get("occupancy"), Mapping):
            raise QuarterPairError(f"V4 variant is missing source/occupancy data: {variant}")
        if set(item["sources"]) != set(SOURCE_LABELS) or set(item["occupancy"]) != set(SOURCE_LABELS):
            raise QuarterPairError(f"V4 variant has unexpected source labels: {variant}")
        closure_item = closure.get("variant_closure", {}).get(variant)
        if not isinstance(closure_item, Mapping):
            raise QuarterPairError(f"V4 variant has no closure item: {variant}")
        if closure_item.get("source_binding_files_sha_verified") is not True:
            raise QuarterPairError(f"V4 source binding is not verified: {variant}")
    return report


def _pair_scope(report: Mapping[str, Any], pair_name: str) -> dict[str, Any]:
    if pair_name not in PAIR_VARIANTS:
        raise QuarterPairError(f"unknown comparison pair: {pair_name}")
    reference_name, current_name = PAIR_VARIANTS[pair_name]
    variants = report["variants"]
    closure = report["source_control_geometry_closure"]["variant_closure"]
    reference = closure[reference_name]
    current = closure[current_name]
    fields = ("control_family_id", "geometry_family_id", "lineage_group_id", "mass_policy", "source_to_native_mk")
    if not _same_tuple(reference, current, fields):
        raise QuarterPairError(f"{pair_name} pair does not preserve control/geometry/source mapping")
    if pair_name == "save_sampling":
        if variants[reference_name]["saved_time_window_s"] != variants[current_name]["saved_time_window_s"]:
            raise QuarterPairError("fine-native and fine-half_save do not share the saved time window")
        scope = "same spatial/control/geometry; output-save cadence comparison"
    else:
        scope = "same spatial/control/geometry; integration-step comparison"
    if reference_name != "fine-native" or variants[current_name]["source_control_geometry_closure"]["lineage_group_id"] != reference["lineage_group_id"]:
        raise QuarterPairError(f"{pair_name} is not anchored to fine-native")
    return {
        "pair": pair_name,
        "reference_variant": reference_name,
        "current_variant": current_name,
        "scope": scope,
        "resolution_comparison": "held_fine",
        "control_geometry_source_tuple_equal": True,
        "excluded_spatial_variants": {
            "coarse-native": "excluded: spatial resolution changes",
            "medium-native": "excluded: spatial resolution changes",
        },
    }


def _metric_value(report: Mapping[str, Any], variant: str, source: str, metric: str) -> float:
    item = report["variants"][variant]
    if metric.startswith("saved_"):
        value = item["occupancy"][source][metric]
    else:
        value = item["sources"][source][metric]
    if value is None and metric.startswith("first_bracket_width_"):
        # No first crossing is a right-censored/no-event observation.  Zero is
        # used only as a comparison sentinel; the output marks this metric as
        # not observed rather than treating it as a measured zero-width event.
        return 0.0
    return _number(value, f"{variant}/{source}/{metric}")


def _compare_pair(report: Mapping[str, Any], pair_name: str) -> dict[str, Any]:
    scope = _pair_scope(report, pair_name)
    reference = scope["reference_variant"]
    current = scope["current_variant"]
    result: dict[str, Any] = {**scope, "sources": {}}
    for source in SOURCE_LABELS:
        whole_mass = _number(report["variants"][reference]["whole_initial_mass_kg"], f"{reference}/whole_initial_mass_kg")
        metrics: dict[str, Any] = {}
        for metric in PAIR_METRICS:
            ref = _metric_value(report, reference, source, metric)
            cur = _metric_value(report, current, source, metric)
            absolute = abs(cur - ref)
            item: dict[str, Any] = {
                "reference": ref,
                "value": cur,
                "difference": cur - ref,
                "absolute_difference": absolute,
                "reference_zero": abs(ref) <= 1.0e-12,
            }
            if metric.startswith("first_bracket_width_") and ref == 0.0 and cur == 0.0:
                item["observation_status"] = "no_first_saved_crossing_in_both_variants"
            if metric.endswith("_kg") or metric.endswith("_mass_kg") or metric.endswith("_net_transport_mass_kg") or metric.endswith("_residence_mass_time_kg_s"):
                item["absolute_difference_fraction_of_reference_whole_initial_mass"] = absolute / whole_mass
            if abs(ref) > 1.0e-12:
                item["relative_difference_to_reference"] = absolute / abs(ref)
            else:
                item["relative_difference_to_reference"] = None
            metrics[metric] = item
        result["sources"][source] = {
            "whole_initial_mass_kg": whole_mass,
            "metrics": metrics,
            "current_amount_is_observation_not_error_gate": True,
            "repeated_crossings_are_not_net_flux": True,
            "continuous_event_time": "unknown",
            "hidden_recrossings": "unknown",
            "physical_flux": "unknown",
            "physical_fate": "unknown",
        }
    result["qualification_credit"] = "not_granted"
    result["interpretation"] = (
        "pair difference is a saved-sidecar diagnostic under the registered quarter-budget allocation; "
        "it is not a continuous-event error bound or a physical flux/fate result"
    )
    return result


def _parse_semicolon_number(value: str) -> float:
    return float(value.replace(",", ""))


def _s2_terminal_summary(receipt_path: Path, runparts_path: Path) -> dict[str, Any]:
    receipt = load_json(receipt_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise QuarterPairError("F4-S2 terminal solver receipt is not completed")
    require_file(receipt_path, label="F4-S2 solver receipt")
    require_file(runparts_path, label="F4-S2 RunPARTs")
    with runparts_path.open(newline="", encoding="utf-8") as stream:
        rows = [
            row
            for row in csv.DictReader(stream, delimiter=";")
            if str(row.get("Part", "")).strip().isdigit()
        ]
    if not rows:
        raise QuarterPairError("F4-S2 RunPARTs has no rows")
    required = {"TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "NpSim", "NpfSim"}
    if not required.issubset(rows[0]):
        raise QuarterPairError("F4-S2 RunPARTs lacks terminal native fields")
    def max_int(field: str) -> int:
        return max(int(_parse_semicolon_number(row[field])) for row in rows)
    last = rows[-1]
    return {
        "case_scope": "F4-S2 separate physical case; terminal evidence is not transferred to F4-S1",
        "receipt_status": receipt["status"],
        "returncode": receipt["returncode"],
        "saved_rows": len(rows),
        "final_saved_time_s": _parse_semicolon_number(last["TimeStep [s]"]),
        "max_native_excluded_particles": max_int("NpOut"),
        "max_native_position_exclusions": max_int("NpOutPos"),
        "max_native_density_exclusions": max_int("NpOutRho"),
        "max_native_movement_exclusions": max_int("NpOutMov"),
        "initial_simulated_particles": int(_parse_semicolon_number(rows[0]["NpSim"])),
        "final_simulated_particles": int(_parse_semicolon_number(last["NpSim"])),
        "initial_fluid_or_floating_particles": int(_parse_semicolon_number(rows[0]["NpfSim"])),
        "final_fluid_or_floating_particles": int(_parse_semicolon_number(last["NpfSim"])),
        "native_exclusion_interpretation": "RunPARTs numeric ledger only; no fate or harmlessness inference",
    }


def _s2_initial_summary(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "ds02.stage2.sentinel.initial-frame-equivalence.v2.3" or value.get("status") != "PASS":
        raise QuarterPairError("F4-S2 initial-frame sidecar is not the expected PASS")
    scope = value.get("scope", {})
    if scope.get("frame_index") != 0 or scope.get("full_time_scan") is not False or scope.get("partvtk_started") is not False:
        raise QuarterPairError("F4-S2 initial-frame scope is wider or different than declared")
    if value.get("scientific_acceptance", {}).get("QN") != "NOT_ASSESSED":
        raise QuarterPairError("F4-S2 initial-frame sidecar unexpectedly grants QN")
    return {
        "status": "PASS_FRAME_ZERO_ONLY",
        "physical_case_id": scope.get("physical_case_id"),
        "frame_index": scope.get("frame_index"),
        "full_time_scan": scope.get("full_time_scan"),
        "raw_read": scope.get("raw_read"),
        "typed_read": scope.get("typed_read"),
        "scientific_acceptance": value.get("scientific_acceptance"),
        "unknown_full_time_continuum": True,
        "unknown_qn": True,
    }


def analyze(
    *,
    v4_report_path: Path,
    v4_request_path: Path,
    v4_proof_path: Path,
    v4_receipt_path: Path,
    s2_initial_path: Path,
    s2_receipt_path: Path,
    s2_runparts_path: Path,
    s2_runout_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    v4_report = _validate_v4_report(v4_report_path)
    v4_request = load_json(v4_request_path)
    command = v4_request.get("command")
    if not isinstance(command, list) or len(command) < 2 or not isinstance(command[1], str):
        raise QuarterPairError("V4 request command does not identify its worker")
    worker_path = Path(command[1])
    _validate_v4_request(v4_request_path, worker_path)
    v4_proof = _validate_v4_proof(v4_proof_path, v4_report_path, v4_request_path, v4_receipt_path)
    s2_initial = _s2_initial_summary(s2_initial_path)
    s2_terminal = _s2_terminal_summary(s2_receipt_path, s2_runparts_path)
    require_file(s2_runout_path, label="F4-S2 Run.out")
    result = {
        "schema": SCHEMA,
        "status": "completed_source_bound_quarter_pair_diagnostic",
        "producer": {
            "v4_report": {"path": str(v4_report_path), "sha256": sha256_file(v4_report_path)},
            "v4_request": {"path": str(v4_request_path), "sha256": sha256_file(v4_request_path)},
            "v4_proof": {"path": str(v4_proof_path), "sha256": sha256_file(v4_proof_path)},
            "v4_receipt": {"path": str(v4_receipt_path), "sha256": sha256_file(v4_receipt_path)},
            "v4_worker_h5_bi4_opened": False,
        },
        "comparison_scope": {
            "allowed_pairs": PAIR_VARIANTS,
            "excluded_variants": {
                "coarse-native": "spatial resolution changes; not a pure time sample",
                "medium-native": "spatial resolution changes; not a pure time sample",
            },
            "same_spatial_fine_pairs_only": True,
            "source_control_geometry_gate": v4_report["source_control_geometry_closure"],
        },
        "quarter_budget": {
            "time_sampling_component_fraction": QUARTER_BUDGET,
            "output_reconstruction_component_fraction": QUARTER_BUDGET,
            "source": "QUALITY_LABEL_SPLIT_ZH.md registered quarter allocation",
            "status": "budget_metadata_only_no_qualification_gate",
            "unresolved_components": ["spatial_discretization", "continuous_event_semantics", "physical_fate_flux"],
        },
        "pairs": {name: _compare_pair(v4_report, name) for name in PAIR_VARIANTS},
        "frozen_screens": {
            "whole_initial_unknown_mass_fraction_max": WHOLE_INITIAL_UNKNOWN_MAX,
            "mk_region_flux_whole_initial_mass_difference_max": WHOLE_INITIAL_REGION_DIFF_MAX,
            "meaning": "screens are reported separately; saved crossing amount is never passed through the error gate",
        },
        "f4_s2_reference_evidence": {
            "initial_frame": {"path": str(s2_initial_path), "sha256": sha256_file(s2_initial_path), "summary": s2_initial},
            "terminal_receipt": {"path": str(s2_receipt_path), "sha256": sha256_file(s2_receipt_path)},
            "terminal_runparts": {"path": str(s2_runparts_path), "sha256": sha256_file(s2_runparts_path)},
            "terminal_runout": {"path": str(s2_runout_path), "sha256": sha256_file(s2_runout_path)},
            "terminal_summary": s2_terminal,
            "transfer_to_f4_s1": "forbidden; S2 is a separate physical case",
        },
        "qi_gate_status": {
            "saved_schema_identity_mass_and_source_binding": "PASS_FOR_SAVED_DIAGNOSTIC",
            "same_control_geometry_for_two_pairs": "PASS",
            "native_exit_and_mass_ledger_for_f4_s1_v4": "UNKNOWN; V4 does not consume PartOut/RunPARTs as an S1 native join",
            "continuous_event_time_and_hidden_recrossings": "UNKNOWN; V4 retains adjacent saved brackets only",
            "full_time_continuum_gate": "UNKNOWN",
            "f4_s2_frame_zero_equivalence": "PASS_FRAME_ZERO_ONLY",
        },
        "qn_gate_status": {
            "pair_difference_as_scoped_observation": "REPORTED",
            "time_and_output_quarter_budget": "NOT_ASSESSED_AS_QN",
            "continuous_transport_flux": "UNKNOWN",
            "physical_destination_fate": "UNKNOWN",
            "qualification_credit": "not_granted",
        },
        "claim_boundary": {
            "saved_pair_difference": "diagnostic only",
            "current_crossing_amount": "observation only; no .03 error gate",
            "repeated_crossing_mass": "not net physical flux",
            "continuous_event_time": "unknown",
            "hidden_recrossings": "unknown",
            "physical_flux": "unknown",
            "physical_fate": "unknown",
            "Q_I": "saved diagnostic schema/source closure only; dynamics/continuum prerequisites incomplete",
            "Q_N": "unknown/not assessed",
            "Q_E": "unknown/not assessed",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output"] = {"path": str(output_path), "sha256": sha256_file(output_path)}
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v4-report", type=Path, required=True)
    parser.add_argument("--v4-request", type=Path, required=True)
    parser.add_argument("--v4-proof", type=Path, required=True)
    parser.add_argument("--v4-receipt", type=Path, required=True)
    parser.add_argument("--s2-initial", type=Path, required=True)
    parser.add_argument("--s2-receipt", type=Path, required=True)
    parser.add_argument("--s2-runparts", type=Path, required=True)
    parser.add_argument("--s2-runout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = analyze(
        v4_report_path=args.v4_report,
        v4_request_path=args.v4_request,
        v4_proof_path=args.v4_proof,
        v4_receipt_path=args.v4_receipt,
        s2_initial_path=args.s2_initial,
        s2_receipt_path=args.s2_receipt,
        s2_runparts_path=args.s2_runparts,
        s2_runout_path=args.s2_runout,
        output_path=args.output,
    )
    print(json.dumps({"status": result["status"], "output": result["output"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
