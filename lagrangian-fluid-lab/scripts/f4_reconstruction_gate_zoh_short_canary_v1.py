#!/usr/bin/env python3
"""Run a bounded continuation of the reviewed F4 ZOH repair hypothesis.

The existing frame-40 -> frame-41 ZOH result is positive only for the first
loss interval.  This diagnostic extends that *same* native cell, seed grid,
fixed gate, and causal query rule through frame 50 (about 0.20 s).  It is a
CPU-only material replay: no solver, GPU, queue, registry, ledger, or full
event-window work is started.  The full 512-seed denominator remains bound to
the output and a right-censored event window never earns T2 credit.

The runner writes a new evidence directory and refuses to overwrite it.  It
also performs an exact replay and a read-only support diagnosis so a future
root review can bind the candidate implementation, source, and outputs by
hash before any solver-backed canary is considered.
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

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f4_reconstruction_gate_interval_canary_v1 as baseline
from scripts import f4_reconstruction_gate_interval_repair_canary_v1 as repair_canary
from scripts import f4_reconstruction_gate_repair_v1 as repair
from scripts import f4_tallwall120_material_diagnosis as diagnosis


SCHEMA = "core.material.f4.reconstruction_gate_zoh_short_canary.v1"
STOP_AFTER_FRAME = 50
FIRST_LOSS_FROM_FRAME = 40
SEEDS = 512
SUBSTEPS = 2
Q = 0.5
DP_M = 0.0075
EVENT_WINDOW_S = 4.34
UNKNOWN_LIMIT = 0.01
EXPECTED_SOURCE_SHA256 = baseline.EXPECTED_SOURCE_SHA256
SOURCE_AUDIT = baseline.SOURCE_AUDIT


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


def validate_contract(lab_root: Path) -> dict[str, Any]:
    """Bind the unchanged source, candidate, and fixed acceptance semantics."""
    source, source_audit = baseline.resolve_source(lab_root)
    interval = baseline.validate_source_interval(source)
    _assert_equal("source sha256", sha256_file(source), EXPECTED_SOURCE_SHA256)
    _assert_equal(
        "source audit sha256",
        source_audit["pair"]["cell14_h5"]["sha256"],
        EXPECTED_SOURCE_SHA256,
    )
    with h5py.File(source, "r") as handle:
        times = handle["time"][:]
        if len(times) <= STOP_AFTER_FRAME:
            raise ValueError("native source does not contain the requested short continuation")
        if not all(times[i] < times[i + 1] for i in range(STOP_AFTER_FRAME)):
            raise ValueError("native source time axis is not strictly increasing")
        extension = {
            "from_frame": FIRST_LOSS_FROM_FRAME,
            "to_frame": STOP_AFTER_FRAME,
            "from_time_s": float(times[FIRST_LOSS_FROM_FRAME]),
            "to_time_s": float(times[STOP_AFTER_FRAME]),
            "interval_s": float(times[STOP_AFTER_FRAME] - times[FIRST_LOSS_FROM_FRAME]),
        }
        frame_count = int(len(times))
        particle_count = int(handle["position"].shape[1])

    candidate = repair.candidate_contract()
    _assert_equal("candidate neighbour variant", candidate["neighbour_variant"], "baseline24")
    _assert_equal("candidate neighbours", candidate["neighbours"], 24)
    _assert_equal("candidate error estimator", candidate["error_estimator"], "local_residual")
    _assert_equal("candidate unknown denominator", candidate["unknown_denominator"], "all 512 independent source seeds")
    _assert_equal("candidate support distance", candidate["maximum_support_distance_m"], 0.03)
    if candidate["support_gate"] != repair_canary.tw.GATE:
        raise ValueError("candidate support gate drifted")

    source_audit_path = (lab_root / SOURCE_AUDIT).resolve()
    return {
        "source": {
            "path": str(source),
            "sha256": sha256_file(source),
            "audit_path": str(source_audit_path),
            "audit_sha256": sha256_file(source_audit_path),
            "role": source_audit["pair"]["cell14_role"],
            "frame_count": frame_count,
            "particle_count": particle_count,
            "short_extension": extension,
        },
        "candidate": candidate,
        "fixed_contract": {
            "q": Q,
            "dp_m": DP_M,
            "seeds": SEEDS,
            "substeps": SUBSTEPS,
            "stop_after_frame_inclusive": STOP_AFTER_FRAME,
            "unknown_denominator": "all 512 independent geometric source seeds; permanent unknown remains in denominator",
            "unknown_fraction_limit": UNKNOWN_LIMIT,
            "event_window_required_s": EVENT_WINDOW_S,
            "event_window_policy": "full 4.34 s required; right-censored or unresolved is not acceptance",
            "thresholds_changed": False,
            "source_destination_mass_semantics_changed": False,
            "event_window_semantics_changed": False,
            "interpolation": "linear_native_position_interval_start_velocity_zoh",
        },
    }


def _dataset_equal(left: h5py.Dataset, right: h5py.Dataset) -> bool:
    import numpy as np

    a = left[:]
    b = right[:]
    if a.dtype.kind in "OUS" or b.dtype.kind in "OUS":
        return bool(np.array_equal(a.astype(str), b.astype(str)))
    return bool(np.array_equal(a, b, equal_nan=True))


def compare_replays(first: Path, second: Path) -> dict[str, Any]:
    """Compare all committed arrays and immutable binding attributes."""
    mismatches: list[str] = []
    with h5py.File(first, "r") as a, h5py.File(second, "r") as b:
        if set(a) != set(b):
            mismatches.append("dataset_names")
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
        "committed_frame": committed,
        "frame_count": frames,
        "first_sha256": sha256_file(first),
        "second_sha256": sha256_file(second),
    }


def _provider(path: Path):
    return repair.HeldVelocityReferenceFrames(path, fluid_type=3)


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("by_source", [])
    return {
        "status": result["status"],
        "committed_frame": result["committed_frame"],
        "committed_time_s": result["committed_time_s"],
        "mass_closed": result["mass_closed"],
        "unknown_gate_pass": result["unknown_gate_pass"],
        "unknown_fraction_max": max((float(row["unknown_fraction_max"]) for row in rows), default=1.0),
        "seed_denominator": SEEDS,
        "common_reliable_path_coverage": result["common_reliable_path_coverage"],
        "event_window_required_s": EVENT_WINDOW_S,
        "event_window_observed_s": result["committed_time_s"],
        "event_window_missing_s": max(0.0, EVENT_WINDOW_S - float(result["committed_time_s"])),
        "event_window_complete": result["event_window_complete"],
        "event_window_status": result["event_window_status"],
        "qualified_T2_macro": result.get("qualified_T2_macro", False),
        "qualified_T2_path": result.get("qualified_T2_path", False),
        "binding": result["binding"],
        "by_source": rows,
    }


def _interval_summary(diag: dict[str, Any]) -> dict[str, Any]:
    transition = next(
        row for row in diag["transitions"] if int(row["from_frame"]) == FIRST_LOSS_FROM_FRAME
    )
    stages = []
    for stage in transition["substeps"]:
        stages.append({
            "substep": int(stage["substep"]),
            "g0_reconstruction_error_fail_count": int(stage["g0"]["component_fail_counts"]["reconstruction_error_fail"]),
            "g1_reconstruction_error_fail_count": int(stage["g1"]["component_fail_counts"]["reconstruction_error_fail"]),
            "g0_support_gate_fail_count": int(stage["failure_reason_counts"]["g0_support_gate_fail"]),
            "g1_support_gate_fail_count": int(stage["failure_reason_counts"]["g1_support_gate_fail"]),
            "distance_gate_fail_count": int(stage["failure_reason_counts"]["distance_gate_fail"]),
            "wall_blocked_count": int(stage["failure_reason_counts"]["wall_blocked"]),
            "new_failure_count": int(stage["new_failure_count"]),
        })
    return {
        "from_frame": FIRST_LOSS_FROM_FRAME,
        "to_frame": FIRST_LOSS_FROM_FRAME + 1,
        "input_reliable_count": transition["input_reliable_count"],
        "output_reliable_count": transition["output_reliable_count"],
        "trace_replay_reliable_match": transition["trace_replay_reliable_match"],
        "substeps": stages,
    }


def build_report(evidence: dict[str, Any], evidence_path: Path) -> str:
    candidate = evidence["candidate"]
    result = evidence["candidate_result"]
    first = evidence["diagnosis"]["first_failure"]
    checks = evidence["acceptance_checks"]
    return "\n".join([
        "# F4 ZOH short continuation canary (2026-09-20)",
        "",
        "结论：同一 native004 cell-14、同一 512-seed 全分母和固定 gate 下，causal interval-start velocity ZOH 从 frame 40→41 延伸到 frame 50；该 CPU-only replay 用于验证修复持续性，仍不构成 T2 或完整事件窗资格。",
        "",
        f"Evidence: `{evidence_path}`",
        f"Evidence SHA256: `{sha256_file(evidence_path) if evidence_path.exists() else 'written-after-report'}`",
        "",
        "## Fixed contract",
        "",
        f"- Candidate: `{candidate['candidate_id']}` / `{candidate['revision_id']}`",
        f"- Source: native cell-14, SHA-256 `{evidence['preflight']['source']['sha256']}`",
        f"- Window: frame `{FIRST_LOSS_FROM_FRAME}→{STOP_AFTER_FRAME}` (`{evidence['preflight']['source']['short_extension']['from_time_s']:.15f}`→`{evidence['preflight']['source']['short_extension']['to_time_s']:.15f}` s)",
        f"- Seeds/steps: `{SEEDS}` independent geometric seeds, `{SUBSTEPS}` RK2 substeps",
        f"- Fixed reconstruction cap: `{candidate['support_gate']['maximum_reconstruction_error_mps']}` m/s; support distance cap `{candidate['maximum_support_distance_m']}` m",
        "- Unknown denominator: all 512 source seeds; permanent unknown is retained; no survivor renormalization",
        f"- Registered event window: `{EVENT_WINDOW_S}` s; observed `{result['event_window_observed_s']}` s; right-censor status remains `{result['event_window_status']}`",
        "",
        "## Result",
        "",
        f"- Candidate first-failure count: `{first['failed_seed_count']}`; surviving seeds: `{first['surviving_seed_count']}`",
        f"- First-failure histogram: `{first['frame_histogram']}`",
        f"- Unknown fraction max: `{result['unknown_fraction_max']}`; unknown gate pass: `{result['unknown_gate_pass']}`",
        f"- Common reliable path coverage: `{result['common_reliable_path_coverage']}`; mass closed: `{result['mass_closed']}`",
        f"- Exact replay: `{checks['exact_replay_pass']}`; diagnosis replay mismatches: `{evidence['diagnosis']['replay_mismatches']}`",
        f"- Frame-40→41 ZOH transition has zero new reconstruction/support/distance failures: `{checks['zero_new_failure_at_first_loss_interval']}`",
        "",
        "The extension preserves the source, support model, thresholds, event definitions, source/destination mass semantics, and full unknown denominator. A short CPU replay cannot supply the missing 4.34 s event window or F3 CDF agreement. Any solver-backed canary requires a separate root review that binds the hashes below; no solver/GPU/queue job was submitted here.",
        "",
    ])


def run(lab_root: Path, output_dir: Path) -> tuple[dict[str, Any], Path]:
    started = time.perf_counter()
    lab_root = Path(lab_root).resolve()
    output_dir = Path(output_dir).resolve()
    preflight = validate_contract(lab_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_trace = output_dir / "candidate-frame00-50.h5"
    replay_trace = output_dir / "candidate-replay-frame00-50.h5"
    candidate_result_path = candidate_trace.with_suffix(".json")
    replay_result_path = replay_trace.with_suffix(".json")
    diagnosis_path = output_dir / "candidate-frame00-50-diagnosis.json"
    evidence_path = output_dir / "f4-reconstruction-gate-zoh-short-canary-v1.json"
    report_path = output_dir / "F4-RECONSTRUCTION-GATE-ZOH-SHORT-CANARY-2026-09-20.md"
    paths = (candidate_trace, replay_trace, candidate_result_path, replay_result_path,
             diagnosis_path, evidence_path, report_path)
    if any(path.exists() for path in paths):
        raise FileExistsError("refusing to overwrite an existing short-canary artifact")

    source = Path(preflight["source"]["path"])
    candidate_result = repair.trace_repair(
        source, candidate_trace, q=Q, dp_m=DP_M, seeds=SEEDS,
        substeps=SUBSTEPS, stop_after=STOP_AFTER_FRAME,
    )
    replay_result = repair.trace_repair(
        source, replay_trace, q=Q, dp_m=DP_M, seeds=SEEDS,
        substeps=SUBSTEPS, stop_after=STOP_AFTER_FRAME,
    )
    replay_check = compare_replays(candidate_trace, replay_trace)
    diag = diagnosis.diagnose(
        source, candidate_trace, diagnosis_path, q=Q, dp_m=DP_M,
        substeps=SUBSTEPS, provider_factory=_provider,
    )
    candidate_summary = _result_summary(candidate_result)
    replay_summary = _result_summary(replay_result)
    first = diag["first_failure"]
    interval = _interval_summary(diag)
    zero_new = (
        interval["trace_replay_reliable_match"]
        and all(
            row["g0_reconstruction_error_fail_count"] == 0
            and row["g1_reconstruction_error_fail_count"] == 0
            and row["g0_support_gate_fail_count"] == 0
            and row["g1_support_gate_fail_count"] == 0
            and row["distance_gate_fail_count"] == 0
            and row["new_failure_count"] == 0
            for row in interval["substeps"]
        )
    )
    evidence = {
        "schema": SCHEMA,
        "record_id": "f4-reconstruction-gate-zoh-short-canary-v1-20260920",
        "created_at_utc": utc_now(),
        "status": "completed_bounded_cpu_replay",
        "qualification_claim": "none",
        "qualification_credit": "none",
        "t2_status": "not_qualified",
        "T2_macro": False,
        "T2_path": False,
        "preflight": preflight,
        "candidate": preflight["candidate"],
        "candidate_result": candidate_summary,
        "candidate_replay_result": replay_summary,
        "exact_replay_check": replay_check,
        "diagnosis": {
            "path": str(diagnosis_path),
            "sha256": sha256_file(diagnosis_path),
            "first_failure": first,
            "replay_mismatches": diag["replay_mismatches"],
            "first_loss_interval": interval,
            "provider": diag["provider"],
        },
        "acceptance_checks": {
            "preflight_pass": True,
            "exact_replay_pass": bool(replay_check["exact"]),
            "candidate_trace_result_replay_pass": candidate_result.get("replay_mismatches", []) == [],
            "zero_new_failure_at_first_loss_interval": bool(zero_new),
            "unknown_denominator_preserved": True,
            "unknown_gate_pass": bool(candidate_summary["unknown_gate_pass"]),
            "mass_closed": bool(candidate_summary["mass_closed"]),
            "full_event_window_complete": bool(candidate_summary["event_window_complete"]),
            "qualification_eligible": False,
        },
        "coverage": {
            "source_cells": 1,
            "seed_denominator": SEEDS,
            "source_frames_committed": int(candidate_summary["committed_frame"] + 1),
            "registered_f4_overlay_rows": 33,
            "registered_f4_event_window_s": EVENT_WINDOW_S,
            "observed_window_s": candidate_summary["committed_time_s"],
            "coverage_claim": "bounded temporal implementation diagnostic only; no matrix numerator credit",
        },
        "root_review_closure": {
            "solver_canary_root_review_required": True,
            "solver_canary_root_review_status": "not_submitted",
            "required_hashes": {
                "source": {"path": preflight["source"]["path"], "sha256": preflight["source"]["sha256"]},
                "source_audit": {"path": preflight["source"]["audit_path"], "sha256": preflight["source"]["audit_sha256"]},
                "repair_implementation": {"path": str(repair.__file__), "sha256": sha256_file(Path(repair.__file__))},
                "runner": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
            },
            "queue_submission": False,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
        },
        "artifacts": {
            "candidate_trace": {"path": str(candidate_trace), "sha256": sha256_file(candidate_trace)},
            "candidate_result": {"path": str(candidate_result_path), "sha256": sha256_file(candidate_result_path)},
            "replay_trace": {"path": str(replay_trace), "sha256": sha256_file(replay_trace)},
            "replay_result": {"path": str(replay_result_path), "sha256": sha256_file(replay_result_path)},
        },
        "execution_constraints": {
            "cpu_only": True,
            "read_only_source_h5": True,
            "new_solver_started": False,
            "new_job_submitted": False,
            "gpu_started": False,
            "full_event_window_started": False,
            "matrix_started": False,
            "thresholds_changed": False,
            "historical_scores_modified": False,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
        },
        "resource_accounting": {
            "wrapper_wall_seconds": time.perf_counter() - started,
            "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "blocking_reasons": [
            "the short replay does not cover the registered 4.34 s event window",
            "T2 still requires a material reference path that passes the fixed 1% unknown gate",
            "F3 per-source unknown/CDF gates remain unresolved and exact native cadence source closure is incomplete",
            "the 33-row F4 overlay and independent material calibration remain incomplete",
        ],
    }
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    report_path.write_text(build_report(evidence, evidence_path), encoding="utf-8")
    return evidence, evidence_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument(
        "--output-dir", type=Path,
        default=LAB_ROOT / "campaigns/core-v1/material/evidence/f4-reconstruction-gate-zoh-short-canary-v1-20260920",
    )
    args = parser.parse_args(argv)
    evidence, path = run(args.lab_root.resolve(), args.output_dir)
    print(json.dumps({
        "status": evidence["status"],
        "T2_macro": evidence["T2_macro"],
        "T2_path": evidence["T2_path"],
        "unknown_fraction_max": evidence["candidate_result"]["unknown_fraction_max"],
        "committed_time_s": evidence["candidate_result"]["committed_time_s"],
        "first_failure_count": evidence["diagnosis"]["first_failure"]["failed_seed_count"],
        "exact_replay": evidence["acceptance_checks"]["exact_replay_pass"],
        "evidence": str(path),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
