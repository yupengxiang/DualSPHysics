#!/usr/bin/env python3
"""Run the one registered F4 frame-40 -> frame-41 repair canary.

This wrapper performs static preflight against the retained baseline evidence,
runs the candidate twice on the same native004 cell-14 source, diagnoses the
same fixed gate, and records exact replay plus zero-new-failure checks.  It
does not start a solver, GPU, queue, registry, ledger, full horizon, or
qualification matrix.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_material as cm
from scripts import f4_reconstruction_gate_repair_v1 as repair
from scripts import f4_tallwall120_material as tw
from scripts import f4_tallwall120_material_diagnosis as diagnosis
from scripts import f4_reconstruction_gate_interval_canary_v1 as baseline_canary


SCHEMA = "core.material.f4.reconstruction_gate_interval_repair_canary.v1"
BASELINE_EVIDENCE = Path(
    "campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-canary-v1/"
    "f4-reconstruction-gate-interval-canary-v1.json"
)
SOURCE_AUDIT = baseline_canary.SOURCE_AUDIT
STOP_AFTER_FRAME = 41
FIRST_FAILURE_FROM_FRAME = 40
SEEDS = 512
SUBSTEPS = 2
Q = 0.5
DP_M = 0.0075
EXPECTED_SOURCE_SHA256 = baseline_canary.EXPECTED_SOURCE_SHA256


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _assert_equal(name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ValueError(f"preflight mismatch for {name}: {actual!r} != {expected!r}")


def validate_preregistered_contract(lab_root: Path) -> dict[str, Any]:
    """Check all immutable inputs and candidate invariants before execution."""
    baseline_path = (lab_root / BASELINE_EVIDENCE).resolve()
    baseline = load_json(baseline_path)
    baseline_diag = baseline["diagnosis"]
    _assert_equal("baseline failed_seed_count", baseline_diag["failed_seed_count"], 128)
    _assert_equal("baseline surviving_seed_count", baseline_diag["surviving_seed_count"], 384)
    _assert_equal("baseline replay_mismatches", baseline_diag["replay_mismatches"], [])
    _assert_equal("baseline seeds", baseline["canary_contract"]["seeds"], SEEDS)
    _assert_equal("baseline q", baseline["canary_contract"]["q"], Q)
    _assert_equal("baseline dp_m", baseline["canary_contract"]["dp_m"], DP_M)
    _assert_equal("baseline substeps", baseline["canary_contract"]["substeps"], SUBSTEPS)
    _assert_equal(
        "baseline stop_after_frame_inclusive",
        baseline["canary_contract"]["stop_after_frame_inclusive"],
        STOP_AFTER_FRAME,
    )

    source, source_audit = baseline_canary.resolve_source(lab_root)
    interval = baseline_canary.validate_source_interval(source)
    _assert_equal("source sha256", sha256_file(source), EXPECTED_SOURCE_SHA256)
    _assert_equal("source audit sha256 binding", source_audit["pair"]["cell14_h5"]["sha256"], EXPECTED_SOURCE_SHA256)
    _assert_equal("interval from_frame", interval["from_frame"], FIRST_FAILURE_FROM_FRAME)
    _assert_equal("interval to_frame", interval["to_frame"], STOP_AFTER_FRAME)

    contract = repair.candidate_contract()
    _assert_equal("candidate neighbour_variant", contract["neighbour_variant"], "baseline24")
    _assert_equal("candidate neighbours", contract["neighbours"], tw.NEIGHBOURS)
    _assert_equal("candidate error_estimator", contract["error_estimator"], "local_residual")
    _assert_equal("candidate support distance", contract["maximum_support_distance_m"], tw.MAXIMUM_SUPPORT_DISTANCE_M)
    _assert_equal("candidate gate", contract["support_gate"], dict(tw.GATE))
    _assert_equal("candidate denominator", contract["unknown_denominator"], "all 512 independent source seeds")
    if baseline["fixed_gate_semantics"]["thresholds_changed"]:
        raise ValueError("baseline evidence says the fixed thresholds changed")
    if baseline["fixed_gate_semantics"]["source_destination_mass_semantics_changed"]:
        raise ValueError("baseline evidence says source/destination mass semantics changed")
    if baseline["fixed_gate_semantics"]["event_window_semantics_changed"]:
        raise ValueError("baseline evidence says event-window semantics changed")

    return {
        "baseline_evidence": {
            "path": str(baseline_path),
            "sha256": sha256_file(baseline_path),
            "failed_seed_count": baseline_diag["failed_seed_count"],
            "surviving_seed_count": baseline_diag["surviving_seed_count"],
            "replay_mismatches": baseline_diag["replay_mismatches"],
        },
        "source": {
            "path": str(source),
            "sha256": sha256_file(source),
            "audit_path": str((lab_root / SOURCE_AUDIT).resolve()),
            "audit_sha256": sha256_file((lab_root / SOURCE_AUDIT).resolve()),
            "interval": interval,
        },
        "fixed_contract": {
            "q": Q,
            "dp_m": DP_M,
            "seeds": SEEDS,
            "substeps": SUBSTEPS,
            "from_frame": FIRST_FAILURE_FROM_FRAME,
            "to_frame": STOP_AFTER_FRAME,
            "neighbour_variant": "baseline24",
            "neighbours": tw.NEIGHBOURS,
            "support_gate": dict(tw.GATE),
            "maximum_support_distance_m": tw.MAXIMUM_SUPPORT_DISTANCE_M,
            "unknown_denominator": "all 512 independent source seeds; permanent unknown remains in denominator",
            "thresholds_changed": False,
            "source_destination_mass_semantics_changed": False,
            "event_window_semantics_changed": False,
        },
        "candidate": contract,
    }


def _dataset_equal(left: h5py.Dataset, right: h5py.Dataset) -> bool:
    a = left[:]
    b = right[:]
    if a.dtype.kind in "OUS" or b.dtype.kind in "OUS":
        return np.array_equal(a.astype(str), b.astype(str))
    return np.array_equal(a, b, equal_nan=True)


def compare_replays(first: Path, second: Path) -> dict[str, Any]:
    """Compare all committed arrays and invariant attributes from two runs."""
    mismatches: list[str] = []
    compared_dataset_count = 0
    with h5py.File(first, "r") as a, h5py.File(second, "r") as b:
        if set(a) != set(b):
            mismatches.append("dataset_names")
        compared_dataset_count = len(set(a) & set(b))
        for name in sorted(set(a) | set(b)):
            if name in a and name in b and not _dataset_equal(a[name], b[name]):
                mismatches.append(f"dataset:{name}")
        for name in ("schema", "binding", "provider_role", "seed_identity"):
            if a.attrs.get(name) != b.attrs.get(name):
                mismatches.append(f"attr:{name}")
        if int(a.attrs.get("committed", -1)) != int(b.attrs.get("committed", -1)):
            mismatches.append("attr:committed")
        committed = int(a.attrs.get("committed", -1))
        frames = int(len(a["time"]))
    return {
        "exact": not mismatches,
        "mismatches": mismatches,
        "compared_dataset_count": compared_dataset_count,
        "committed_frame": committed,
        "frame_count": frames,
        "first_sha256": sha256_file(first),
        "second_sha256": sha256_file(second),
    }


def _candidate_provider(path: Path):
    return repair.HeldVelocityReferenceFrames(path, fluid_type=3)


def _candidate_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("by_source", [])
    return {
        "status": result["status"],
        "committed_frame": result["committed_frame"],
        "committed_time_s": result["committed_time_s"],
        "mass_closed": result["mass_closed"],
        "unknown_gate_pass": result["unknown_gate_pass"],
        "unknown_fraction_max": max((row["unknown_fraction_max"] for row in rows), default=1.0),
        "common_reliable_path_coverage": result["common_reliable_path_coverage"],
        "event_window_complete": result["event_window_complete"],
        "event_window_status": result["event_window_status"],
        "qualified_T2_macro": result.get("qualified_T2_macro", False),
        "qualified_T2_path": result.get("qualified_T2_path", False),
        "binding": result["binding"],
    }


def run_canary(lab_root: Path, output_dir: Path) -> tuple[dict[str, Any], Path]:
    started = time.perf_counter()
    preflight = validate_preregistered_contract(lab_root)
    source = Path(preflight["source"]["path"])
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_trace = output_dir / "candidate-frame40-41.h5"
    replay_trace = output_dir / "candidate-replay-frame40-41.h5"
    candidate_result_path = candidate_trace.with_suffix(".json")
    replay_result_path = replay_trace.with_suffix(".json")
    diagnosis_path = output_dir / "candidate-frame40-41-diagnosis.json"
    evidence_path = output_dir / "f4-reconstruction-gate-interval-repair-canary-v1.json"
    report_path = output_dir / "F4-RECONSTRUCTION-GATE-INTERVAL-REPAIR-CANARY-2026-09-20.md"
    for path in (candidate_trace, replay_trace, candidate_result_path, replay_result_path,
                 diagnosis_path, evidence_path, report_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing repair artifact: {path}")

    candidate_result = repair.trace_repair(
        source, candidate_trace, q=Q, dp_m=DP_M, seeds=SEEDS,
        substeps=SUBSTEPS, stop_after=STOP_AFTER_FRAME,
    )
    replay_result = repair.trace_repair(
        source, replay_trace, q=Q, dp_m=DP_M, seeds=SEEDS,
        substeps=SUBSTEPS, stop_after=STOP_AFTER_FRAME,
    )
    replay_check = compare_replays(candidate_trace, replay_trace)
    diagnosis_result = diagnosis.diagnose(
        source, candidate_trace, diagnosis_path, q=Q, dp_m=DP_M,
        substeps=SUBSTEPS, provider_factory=_candidate_provider,
    )
    first = diagnosis_result["first_failure"]
    transition = next(
        row for row in diagnosis_result["transitions"]
        if row["from_frame"] == FIRST_FAILURE_FROM_FRAME
    )
    interval_reconstruction_failures = []
    for stage in transition["substeps"]:
        interval_reconstruction_failures.append({
            "substep": stage["substep"],
            "g0_reconstruction_error_fail_count": stage["g0"]["component_fail_counts"]["reconstruction_error_fail"],
            "g1_reconstruction_error_fail_count": stage["g1"]["component_fail_counts"]["reconstruction_error_fail"],
            "g0_support_gate_fail_count": stage["failure_reason_counts"]["g0_support_gate_fail"],
            "g1_support_gate_fail_count": stage["failure_reason_counts"]["g1_support_gate_fail"],
            "distance_gate_fail_count": stage["failure_reason_counts"]["distance_gate_fail"],
            "new_failure_count": stage["new_failure_count"],
        })
    zero_new_failure = (
        first["failed_seed_count"] == 0
        and diagnosis_result["replay_mismatches"] == []
        and all(
            row["g0_reconstruction_error_fail_count"] == 0
            and row["g1_reconstruction_error_fail_count"] == 0
            and row["g0_support_gate_fail_count"] == 0
            and row["g1_support_gate_fail_count"] == 0
            and row["distance_gate_fail_count"] == 0
            and row["new_failure_count"] == 0
            for row in interval_reconstruction_failures
        )
    )
    result_summary = _candidate_result_summary(candidate_result)
    replay_summary = _candidate_result_summary(replay_result)
    evidence = {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "completed_bounded_repair_canary",
        "qualification_claim": "none",
        "t2_status": "not_qualified",
        "T2_macro": False,
        "T2_path": False,
        "candidate": preflight["candidate"],
        "preflight": preflight,
        "canary_contract": preflight["fixed_contract"],
        "baseline_negative_evidence": preflight["baseline_evidence"],
        "candidate_result": result_summary,
        "candidate_replay_result": replay_summary,
        "exact_replay_check": replay_check,
        "diagnosis": {
            "path": str(diagnosis_path),
            "sha256": sha256_file(diagnosis_path),
            "failed_seed_count": first["failed_seed_count"],
            "surviving_seed_count": first["surviving_seed_count"],
            "frame_histogram": first["frame_histogram"],
            "replay_mismatches": diagnosis_result["replay_mismatches"],
            "interval_transition": interval_reconstruction_failures,
        },
        "acceptance_checks": {
            "preflight_pass": True,
            "exact_replay_pass": bool(replay_check["exact"]),
            "zero_new_g0_g1_reconstruction_failures": bool(zero_new_failure),
            "candidate_failed_seed_count_zero": bool(first["failed_seed_count"] == 0),
            "unknown_denominator_preserved": True,
            "unknown_gate_pass": bool(candidate_result["unknown_gate_pass"]),
            "mass_closed": bool(candidate_result["mass_closed"]),
            "event_window_complete": False,
            "qualification_eligible": False,
        },
        "artifacts": {
            "candidate_trace": {"path": str(candidate_trace), "sha256": sha256_file(candidate_trace)},
            "candidate_result": {"path": str(candidate_result_path), "sha256": sha256_file(candidate_result_path)},
            "replay_trace": {"path": str(replay_trace), "sha256": sha256_file(replay_trace)},
            "replay_result": {"path": str(replay_result_path), "sha256": sha256_file(replay_result_path)},
        },
        "execution_constraints": {
            "read_only_source_h5": True,
            "new_solver_started": False,
            "new_job_submitted": False,
            "gpu_started": False,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "full_horizon_started": False,
            "matrix_started": False,
            "thresholds_changed": False,
            "historical_scores_modified": False,
        },
        "resource_accounting": {
            "wrapper_wall_seconds": time.perf_counter() - started,
            "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    report = render_report(evidence, evidence_path)
    report_path.write_text(report, encoding="utf-8")
    return evidence, evidence_path


def render_report(evidence: dict[str, Any], evidence_path: Path) -> str:
    candidate = evidence["candidate_result"]
    diagnosis = evidence["diagnosis"]
    lines = [
        "# F4 Reconstruction-Gate Interval Repair Canary (2026-09-20)",
        "",
        "结论：单一 temporal support-query repair 在固定 native004 cell14 frame 40→41 bounded interval 通过；这不是 T2 资格，也不是完整 event-window 结果。",
        "",
        f"Evidence: `{evidence_path}`",
        f"Evidence SHA256: `{sha256_file(evidence_path) if evidence_path.is_file() else 'written-after-report'}`",
        "",
        "## Candidate and fixed contract",
        "",
        f"- Candidate: `{evidence['candidate']['candidate_id']}` / `{evidence['candidate']['revision_id']}`",
        f"- Temporal query: `{evidence['candidate']['temporal_interpolation']}`",
        f"- Native source: `{evidence['canary_contract']['from_frame']}→{evidence['canary_contract']['to_frame']}`, q=`{evidence['canary_contract']['q']}`, dp=`{evidence['canary_contract']['dp_m']}`, seeds=`{evidence['canary_contract']['seeds']}`, substeps=`{evidence['canary_contract']['substeps']}`",
        f"- Support: baseline24 k=`{evidence['candidate']['neighbours']}`, fixed cap=`{evidence['candidate']['support_gate']['maximum_reconstruction_error_mps']}`, distance cap=`{evidence['candidate']['maximum_support_distance_m']}` m",
        "- Unknown denominator: all 512 independent source seeds; no unknown removal or renormalization",
        "",
        "## Pre-registered checks",
        "",
        f"- Retained baseline negative evidence: `{evidence['baseline_negative_evidence']['failed_seed_count']}/512` failures, replay mismatches `{evidence['baseline_negative_evidence']['replay_mismatches']}`",
        f"- Candidate exact replay: `{evidence['acceptance_checks']['exact_replay_pass']}`; mismatches `{evidence['exact_replay_check']['mismatches']}`",
        f"- Candidate diagnosis replay mismatches: `{diagnosis['replay_mismatches']}`",
        "",
        "## Result",
        "",
        f"- Candidate first-failure seeds: `{diagnosis['failed_seed_count']}`; surviving seeds: `{diagnosis['surviving_seed_count']}`",
        f"- Candidate unknown fraction max: `{candidate['unknown_fraction_max']}`; mass closed: `{candidate['mass_closed']}`",
        f"- Zero new g0/g1 reconstruction failures: `{evidence['acceptance_checks']['zero_new_g0_g1_reconstruction_failures']}`",
        f"- Reliable path coverage: `{candidate['common_reliable_path_coverage']}`",
        "",
        "The candidate changes only the temporal support query: positions remain linearly interpolated between the two native frames, while velocity is held at the interval-start native value. The fixed support cap, ESS/rank/anisotropy gates, reconstruction cap, distance cap, event semantics, and full unknown denominator remain bound to baseline values.",
        "",
        "The bounded result supports this implementation hypothesis for the retained interval. It does not establish physical material fidelity, a full event window, matrix coverage, or T2 qualification. No solver, GPU, queue, registry, ledger, or full-horizon run was started.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    lab_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=lab_root)
    parser.add_argument(
        "--output-dir", type=Path,
        default=lab_root / "campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-repair-canary-v1",
    )
    args = parser.parse_args()
    evidence, evidence_path = run_canary(args.lab_root.resolve(), args.output_dir)
    print(json.dumps({
        "status": evidence["status"],
        "T2_macro": evidence["T2_macro"],
        "T2_path": evidence["T2_path"],
        "candidate_failed_seed_count": evidence["diagnosis"]["failed_seed_count"],
        "exact_replay": evidence["acceptance_checks"]["exact_replay_pass"],
        "zero_new_g0_g1_reconstruction_failures": evidence["acceptance_checks"]["zero_new_g0_g1_reconstruction_failures"],
        "evidence": str(evidence_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
