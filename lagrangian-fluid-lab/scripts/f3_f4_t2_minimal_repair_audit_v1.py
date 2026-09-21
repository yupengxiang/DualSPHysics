"""Audit the smallest legitimate closure needed for the retained F3/F4 T2 evidence.

This module consumes the already versioned CPU source/window audit and its
remediation preflight.  It performs no solver work and does not open an HDF5
file.  The purpose is to separate integer denominator deficits (which can be
used to plan a repair) from claims that a checkpoint or a short event window
can already satisfy a scientific gate.

The report is intentionally negative evidence.  A valid checkpoint can make a
future run restartable, but it cannot turn a permanent unknown into a reliable
seed or manufacture the missing CFD frames needed by an event window.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "core.material.t2.minimal_repair_audit.v1"
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
EVENT_WINDOW_S = 4.34
AUDIT_NAME = "f3-f4-t2-cpu-source-window-audit-v1-20260920.json"
PREFLIGHT_NAME = "f3-f4-t2-cpu-only-remediation-preflight-20260920.json"
REPAIR_DIAGNOSIS_NAME = "f4-material-repair-failure-diagnosis-20260919.json"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _relative(path: Path, lab_root: Path) -> str:
    return str(path.resolve().relative_to(lab_root.resolve()))


def _source_row(value: dict[str, Any]) -> dict[str, Any]:
    """Return only stable scalar fields from an audited source row."""
    denominator = int(value["seed_denominator"])
    unknown_count = int(value["terminal_unknown_count"])
    unknown_fraction = float(value["terminal_unknown_fraction"])
    if denominator <= 0 or unknown_count < 0 or unknown_count > denominator:
        raise ValueError("invalid source denominator or unknown count")
    expected_fraction = unknown_count / denominator
    if abs(expected_fraction - unknown_fraction) > 1.0e-12:
        raise ValueError("source unknown fraction is not bound to its count")
    allowed = maximum_allowed_count(denominator, UNKNOWN_LIMIT)
    reasons = {
        str(key): int(count)
        for key, count in (value.get("first_failure_reason_counts") or {}).items()
    }
    return {
        "source_id": str(value["source_id"]),
        "seed_denominator": denominator,
        "terminal_unknown_count": unknown_count,
        "terminal_unknown_fraction": unknown_fraction,
        "maximum_allowed_unknown_count": allowed,
        "minimum_unknown_recovery_count": max(0, unknown_count - allowed),
        "unknown_gate_pass": bool(value["unknown_gate_pass"]),
        "first_failure_frame": value.get("first_failure_frame"),
        "first_failure_time_s": value.get("first_failure_time_s"),
        "first_failure_reason_counts": dict(sorted(reasons.items())),
        "dominant_first_failure_reason": (
            max(sorted(reasons), key=lambda key: reasons[key]) if reasons else None
        ),
        "denominator_policy": value.get("denominator_policy"),
    }


def maximum_allowed_count(denominator: int, limit: float) -> int:
    """Return the largest integer count satisfying ``count/denominator <= limit``."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if not 0.0 <= float(limit) <= 1.0:
        raise ValueError("fraction limit must lie in [0, 1]")
    return int(math.floor(float(limit) * int(denominator) + 1.0e-12))


def _cdf_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    denominator = None
    for source in row["trace_audit"].get("source_rows", []):
        if str(source["source_id"]) == "0":
            # CDF values in this retained comparison use the same per-source
            # seed denominator as the trace.  Use each source row below when
            # converting the bound to integer units.
            denominator = int(source["seed_denominator"])
            break
    output = []
    for source_id, comparison in sorted(row.get("cdf_comparison", {}).items(), key=lambda item: str(item[0])):
        matching = [
            item for item in row["trace_audit"].get("source_rows", [])
            if str(item["source_id"]) == str(source_id)
        ]
        if not matching:
            raise ValueError(f"CDF source has no denominator: {source_id}")
        denominator = int(matching[0]["seed_denominator"])
        allowed_units = maximum_allowed_count(denominator, CDF_LIMIT)
        bounds = {str(key): float(value) for key, value in comparison["bounds"].items()}
        peak_event, peak_bound = max(sorted(bounds.items()), key=lambda item: item[1])
        units = int(round(peak_bound * denominator))
        if abs(units / denominator - peak_bound) > 1.0e-12:
            raise ValueError("CDF bound is not represented on the source denominator")
        output.append({
            "source_id": str(source_id),
            "seed_denominator": denominator,
            "cdf_bound_by_event": dict(sorted(bounds.items())),
            "maximum_cdf_bound": peak_bound,
            "maximum_cdf_bound_event": peak_event,
            "maximum_cdf_bound_units": units,
            "maximum_allowed_cdf_bound_units": allowed_units,
            "minimum_cdf_bound_reduction_units": max(0, units - allowed_units),
            "cdf_gate_pass": bool(comparison["pass"]),
            "interpretation": (
                "integer bound units are a planning deficit only; reducing a CDF "
                "bound is not equivalent to recovering that many seeds"
            ),
        })
    return output


def _f3_section(audit: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in sorted(audit["f3"]["rows"], key=lambda item: int(item["row"])):
        trace = row["trace_audit"]
        source_rows = [_source_row(item) for item in trace.get("source_rows", [])]
        rows.append({
            "row": int(row["row"]),
            "case_id": row.get("case_id"),
            "source_rows": source_rows,
            "minimum_unknown_recovery_count": sum(
                item["minimum_unknown_recovery_count"] for item in source_rows
            ),
            "cdf": _cdf_rows(row),
            "checkpoint_pass": bool(trace.get("checkpoint", {}).get("pass")),
            "trace_integrity_pass": bool(trace.get("integrity_pass")),
            "permanent_unknown_recovery_forbidden": True,
            "recovery_interpretation": (
                "A valid terminal checkpoint can preserve/restart the trace, but "
                "the retained permanent_unknown state cannot be relabeled as reliable."
            ),
        })
    return {
        "rows": rows,
        "row_count": len(rows),
        "minimum_unknown_recovery_count_across_retained_rows": sum(
            row["minimum_unknown_recovery_count"] for row in rows
        ),
        # The retained comparison is one fixed left/right pair reused for
        # rows 29 and 31.  Do not add the same CDF deficit twice; report the
        # worst bound once per source and retain the row-level values above.
        "minimum_cdf_bound_reduction_units_by_source": {
            str(source): max(
                item["minimum_cdf_bound_reduction_units"]
                for row in rows for item in row["cdf"]
                if item["source_id"] == str(source)
            )
            for source in sorted({
                item["source_id"] for row in rows for item in row["cdf"]
            })
        },
        "cdf_pair_reused_across_rows": True,
        "scope_complete": False,
        "qualification_eligible": False,
    }


def _f4_case(case: dict[str, Any]) -> dict[str, Any]:
    trace = case.get("trace_audit", {})
    source_rows = [_source_row(item) for item in trace.get("source_rows", [])]
    if not source_rows:
        denominator = int(case.get("seed_denominator") or 0)
        unknown_fraction = float(case["unknown_fraction_max"])
        unknown_count = int(round(denominator * unknown_fraction))
        source_rows = [{
            "source_id": "declared",
            "seed_denominator": denominator,
            "terminal_unknown_count": unknown_count,
            "terminal_unknown_fraction": unknown_fraction,
            "maximum_allowed_unknown_count": maximum_allowed_count(denominator, UNKNOWN_LIMIT),
            "minimum_unknown_recovery_count": max(
                0, unknown_count - maximum_allowed_count(denominator, UNKNOWN_LIMIT)
            ),
            "unknown_gate_pass": unknown_count / denominator <= UNKNOWN_LIMIT,
            "first_failure_frame": None,
            "first_failure_time_s": None,
            "first_failure_reason_counts": {},
            "dominant_first_failure_reason": None,
            "denominator_policy": "all geometric seeds carrying this source label",
        }]
    required_horizon = EVENT_WINDOW_S
    event = trace.get("event_window", {})
    observed_time = event.get("committed_time_s")
    if observed_time is None:
        observed_time = 0.0
    observed_time = float(observed_time)
    missing = max(0.0, required_horizon - observed_time)
    checkpoint_pass = bool(trace.get("checkpoint", {}).get("pass"))
    return {
        "case_id": case["case_id"],
        "canary_id": case["canary_id"],
        "source_rows": source_rows,
        "minimum_unknown_recovery_count": sum(
            item["minimum_unknown_recovery_count"] for item in source_rows
        ),
        "unknown_gate_pass": bool(trace.get("unknown_gate", {}).get("pass")),
        "event_window": {
            "required_s": required_horizon,
            "observed_s": observed_time,
            "minimum_missing_horizon_s": missing,
            "complete": bool(case.get("event_window_complete")),
            "status": event.get("status"),
        },
        "checkpoint_pass": checkpoint_pass,
        "checkpoint_recovery_status": (
            "valid_checkpoint_but_source_horizon_incomplete"
            if checkpoint_pass and missing > 0.0
            else "no_valid_checkpoint"
            if not checkpoint_pass
            else "horizon_complete"
        ),
        "trace_integrity_pass": bool(trace.get("integrity_pass")),
        "repair_does_not_change_denominator": True,
        "qualification_eligible": False,
        "failure_classification": list(case.get("failure_classification", [])),
    }


def _repair_probe(diagnosis: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize the existing saved-frame F4 repair probe, if available."""
    if not diagnosis:
        return {"available": False, "qualification_effect": "none"}
    records = diagnosis.get("first_failure_and_gate_probe", {}).get("records", [])
    variants = sorted({str(item.get("variant")) for item in records if item.get("variant")})
    summary: dict[str, Any] = {"available": bool(records), "qualification_effect": "none"}
    for variant in variants:
        rows = [item for item in records if str(item.get("variant")) == variant]
        first = next((item for item in rows if int(item.get("stored_unknown_count", 0)) > 0), None)
        late = max(rows, key=lambda item: int(item.get("frame", -1))) if rows else None
        if first is None:
            continue

        def compact(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "frame": int(item["frame"]),
                "time_s": float(item["time_s"]),
                "stored_unknown_count": int(item["stored_unknown_count"]),
                "sample_gate_fail_count": int(item["sample_gate_fail_count"]),
                "reconstruction_fail_count": int(item["reconstruction_fail_count"]),
                "support_distance_fail_count": int(item["support_distance_fail_count"]),
                "effective_sample_size_fail_count": int(item["effective_sample_size_fail_count"]),
                "geometry_rank_fail_count": int(item["geometry_rank_fail_count"]),
                "anisotropy_fail_count": int(item["anisotropy_fail_count"]),
            }

        summary[variant] = {
            "first_unknown_probe": compact(first),
            "last_probe": compact(late),
            "first_failure_interpretation": (
                "reconstruction-error gate is the first observed cause; support, ESS, "
                "rank and anisotropy do not contribute at that frame"
                if int(first["reconstruction_fail_count"]) == int(first["sample_gate_fail_count"])
                and int(first["support_distance_fail_count"]) == 0
                and int(first["effective_sample_size_fail_count"]) == 0
                and int(first["geometry_rank_fail_count"]) == 0
                and int(first["anisotropy_fail_count"]) == 0
                else "first failure has multiple gate components; retain the component counts"
            ),
        }
    return summary


def _f4_section(audit: dict[str, Any], diagnosis: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = [_f4_case(case) for case in audit["f4"]["cases"]]
    return {
        "cases": cases,
        "case_count": len(cases),
        "minimum_unknown_recovery_count_across_retained_cases": sum(
            case["minimum_unknown_recovery_count"] for case in cases
        ),
        "all_checkpoints_valid": bool(cases) and all(case["checkpoint_pass"] for case in cases),
        "all_event_windows_complete": bool(cases) and all(
            case["event_window"]["complete"] for case in cases
        ),
        "minimum_missing_horizon_s_by_case": {
            case["case_id"]: case["event_window"]["minimum_missing_horizon_s"]
            for case in cases
        },
        "repair_candidate_probe": _repair_probe(diagnosis),
        "scope_complete": False,
        "qualification_eligible": False,
    }


def _coverage(preflight: dict[str, Any]) -> dict[str, Any]:
    observed = preflight["observed_negative_state"]
    f3 = observed["f3"]["scope_coverage"]
    f4 = observed["f4"]["scope_coverage"]
    return {
        "f3": {
            "registered_rows": int(f3["registered_rows"]),
            "formal_row_complete": bool(f3["formal_row_complete"]),
            "blocked_source_rows": [int(item) for item in f3["blocked_source_rows"]],
            "source_available_not_submitted_rows": [
                int(item) for item in f3["source_available_not_submitted_rows"]
            ],
        },
        "f4": {
            "registered_overlay_rows": int(f4["registered_overlay_rows"]),
            "source_cfd_cells": int(f4["source_cfd_cells"]),
            "cadence_exact_pairs_complete": bool(f4["cadence_exact_pairs_complete"]),
            "seed_density_4096_overlays_complete": bool(
                f4["seed_density_4096_overlays_complete"]
            ),
            "formal_matrix_acceptance": bool(f4["formal_matrix_acceptance"]),
        },
        "qualification_credit": "none",
    }


def build_report(lab_root: str | Path, output_path: str | Path | None = None) -> dict[str, Any]:
    lab_root = Path(lab_root).resolve()
    evidence = lab_root / "campaigns/core-v1/material/evidence"
    audit_path = evidence / AUDIT_NAME
    preflight_path = evidence / PREFLIGHT_NAME
    diagnosis_path = evidence / REPAIR_DIAGNOSIS_NAME
    audit = _read(audit_path)
    preflight = _read(preflight_path)
    if audit.get("schema") != "core.material.t2.cpu_source_window_audit.v1":
        raise ValueError("source/window audit schema changed")
    if preflight.get("schema") != "core.material.t2.cpu_only_remediation_preflight.v1":
        raise ValueError("remediation preflight schema changed")
    gates = audit.get("registered_gates", {})
    if float(gates.get("unknown_fraction_per_source_max")) != UNKNOWN_LIMIT:
        raise ValueError("unknown gate drifted")
    if float(gates.get("f3_cdf_sup_abs_difference_max")) != CDF_LIMIT:
        raise ValueError("CDF gate drifted")
    if float(preflight["registered_gates"]["f4_full_registered_event_window_s"]) != EVENT_WINDOW_S:
        raise ValueError("F4 event window drifted")
    diagnosis_exists = diagnosis_path.is_file()
    diagnosis = _read(diagnosis_path) if diagnosis_exists else None
    f3 = _f3_section(audit)
    f4 = _f4_section(audit, diagnosis)
    coverage = _coverage(preflight)
    inputs = [
        {
            "path": _relative(audit_path, lab_root),
            "sha256": sha256_file(audit_path),
            "role": "retained CPU source/window gate audit",
        },
        {
            "path": _relative(preflight_path, lab_root),
            "sha256": sha256_file(preflight_path),
            "role": "fixed-gate remediation and coverage preflight",
        },
    ]
    if diagnosis_exists:
        inputs.append({
            "path": _relative(diagnosis_path, lab_root),
            "sha256": sha256_file(diagnosis_path),
            "role": "F4 real-canary first-failure repair diagnosis",
        })
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "record_id": "f3-f4-t2-minimal-repair-audit-20260920",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "blocked_for_qualification",
        "mode": "read_only_json_evidence_audit",
        "qualification_claim": "none",
        "qualification_credit": "none",
        "t2_status": "not_established",
        "t2_qualified": False,
        "T2_macro": False,
        "T2_path": False,
        "execution_constraints": {
            "read_only": True,
            "json_only": True,
            "terminal_h5_opened": False,
            "new_job_submitted": False,
            "gpu_started": False,
            "solver_started": False,
            "central_ledger_mutation": 0,
            "registry_mutation": 0,
            "thresholds_changed": False,
            "historical_scores_changed": False,
        },
        "registered_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "f3_cdf_sup_abs_difference_max": CDF_LIMIT,
            "f4_full_registered_event_window_s": EVENT_WINDOW_S,
            "right_censored_is_not_acceptance": True,
            "unknown_denominator": "all geometric seeds remain in each source denominator",
        },
        "minimum_repair_deficits": {
            "f3": f3,
            "f4": f4,
        },
        "checkpoint_and_cache_audit": {
            "f3_terminal_checkpoints_valid": all(row["checkpoint_pass"] for row in f3["rows"]),
            "f4_retained_checkpoints_valid": f4["all_checkpoints_valid"],
            "safe_recovery_claim": "restartability only",
            "forbidden_recovery_claims": [
                "do not relabel permanent_unknown seeds as reliable",
                "do not treat a short F4 checkpoint as a complete 4.34 s event window",
                "do not infer CDF agreement from checkpoint integrity",
            ],
        },
        "coverage_audit": coverage,
        "independent_qualification_path_available": False,
        "qualification_blockers": [
            "F3 retained source rows exceed the fixed per-source 1% unknown gate and the CDF bound exceeds 0.02.",
            "F4 retained canaries exceed the fixed per-source 1% unknown gate; valid checkpoints only preserve restart state.",
            "Every retained F4 event window is right-censored before 4.34 s, so the missing horizon cannot be recovered from current short traces.",
            "The registered 33-row F3/F4 scopes remain incomplete and no independent accepted second material family exists.",
        ],
        "minimum_repair_interpretation": {
            "unknown_counts": "integer deficits are the smallest number of terminal unknown seeds that a future fixed-gate run would need to convert into valid reliable paths; they are not permission to edit a trace",
            "cdf_units": "CDF bound deficits are denominator units and are not seed-recovery guarantees",
            "event_horizon": "minimum missing seconds are a lower bound on saved source time; event completion and unknown gates still require a new accepted run",
        },
        "input_evidence": inputs,
        "implementation_binding": {
            "script": {
                "path": _relative(Path(__file__), lab_root),
                "sha256": sha256_file(__file__),
            },
            "hash_algorithm": "sha256",
        },
    }
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(args.lab_root, args.output)
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "f3_unknown_recovery": report["minimum_repair_deficits"]["f3"]["minimum_unknown_recovery_count_across_retained_rows"],
        "f4_unknown_recovery": report["minimum_repair_deficits"]["f4"]["minimum_unknown_recovery_count_across_retained_cases"],
        "independent_qualification_path_available": report["independent_qualification_path_available"],
        "output": str(args.output.resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
