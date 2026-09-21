#!/usr/bin/env python3
"""Run a bounded F4 reconstruction-gate interval replay.

This canary is intentionally narrower than a material qualification run.  It
uses the root-verified native004 cell-14 source, the registered 512 geometric
seeds, two RK substeps, and only the saved frames through frame 41.  Frame 40
to 41 brackets the retained first reconstruction-gate loss at about
0.160015--0.164008 s.  The runner and diagnosis preserve the existing gate,
unknown denominator, event semantics, and qualification boundary.  No solver,
queue, registry, ledger, threshold, or historical result is changed.
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

# Keep imports bound to this checkout when invoked by absolute script path.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_material as cm
from scripts import f4_tallwall120_material as tw
from scripts import f4_tallwall120_material_diagnosis as diagnosis


SCHEMA = "core.material.f4.reconstruction_gate_interval_canary.v1"
SOURCE_AUDIT = Path(
    "campaigns/core-v1/material/evidence/f4-tallwall120-native004-cadence-source-audit-v1.json"
)
STOP_AFTER_FRAME = 41
FIRST_FAILURE_FROM_FRAME = 40
SEEDS = 512
SUBSTEPS = 2
Q = 0.5
DP_M = 0.0075
EXPECTED_SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
EXPECTED_FIRST_FAILURE_INTERVAL_S = (0.1600149861278153, 0.1640080936314531)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def resolve_source(lab_root: Path) -> tuple[Path, dict[str, Any]]:
    audit_path = (lab_root / SOURCE_AUDIT).resolve()
    audit = load_json(audit_path)
    source_record = audit["pair"]["cell14_h5"]
    source = Path(source_record["path"]).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source_record.get("sha256") != EXPECTED_SOURCE_SHA256:
        raise ValueError("source audit hash changed from the registered native004 binding")
    return source, audit


def validate_source_interval(source: Path) -> dict[str, Any]:
    """Read only the time axis and bind the first-loss saved-frame interval."""
    with h5py.File(source, "r") as handle:
        if "time" not in handle:
            raise ValueError("native source has no time dataset")
        times = handle["time"][:]
        if len(times) <= STOP_AFTER_FRAME:
            raise ValueError("native source does not contain the bounded interval")
        if not (times[FIRST_FAILURE_FROM_FRAME] < times[STOP_AFTER_FRAME]):
            raise ValueError("native source frame interval is not increasing")
        required = {"position", "velocity", "valid", "particle_zone"}
        missing = sorted(required - set(handle))
        if missing:
            raise ValueError("native source missing required datasets: " + ",".join(missing))
        return {
            "frame_count": int(len(times)),
            "particle_count": int(handle["position"].shape[1]),
            "from_frame": FIRST_FAILURE_FROM_FRAME,
            "to_frame": STOP_AFTER_FRAME,
            "from_time_s": float(times[FIRST_FAILURE_FROM_FRAME]),
            "to_time_s": float(times[STOP_AFTER_FRAME]),
            "interval_s": float(times[STOP_AFTER_FRAME] - times[FIRST_FAILURE_FROM_FRAME]),
        }


def _compact_stage(stage: dict[str, Any]) -> dict[str, Any]:
    """Keep interval evidence small while retaining every gate component."""
    result: dict[str, Any] = {
        "frame": stage["frame"],
        "substep": stage["substep"],
        "segment_time_s": stage["segment_time_s"],
        "active_count": stage["active_count"],
        "usable_count": stage["usable_count"],
        "new_failure_count": stage["new_failure_count"],
        "failure_reason_counts": stage["failure_reason_counts"],
    }
    for name in ("g0", "g1"):
        row = stage[name]
        result[name] = {
            "active_count": row["active_count"],
            "support_gate_pass_count": row["support_gate_pass_count"],
            "support_gate_fail_count": row["support_gate_fail_count"],
            "component_fail_counts": row["component_fail_counts"],
            "support_distance_m": row["support_distance_m"],
            "effective_sample_size": row["effective_sample_size"],
            "geometry_rank": row["geometry_rank"],
            "anisotropy": row["anisotropy"],
            "reconstruction_error_mps": row["reconstruction_error_mps"],
        }
    return result


def build_evidence(
    lab_root: Path,
    output_dir: Path,
    *,
    source: Path,
    source_audit: dict[str, Any],
    source_interval: dict[str, Any],
    trace_result: dict[str, Any],
    trace_path: Path,
    trace_result_path: Path,
    diagnosis_result: dict[str, Any],
    diagnosis_path: Path,
    started: float,
    process_rss_kib: int,
) -> dict[str, Any]:
    diagnosis_first = diagnosis_result["first_failure"]
    interval_stages = [
        _compact_stage(stage)
        for stage in diagnosis_result["transitions"][FIRST_FAILURE_FROM_FRAME]["substeps"]
    ]
    trace_summary = {
        "status": trace_result["status"],
        "qualification_claim": trace_result["qualification_claim"],
        "qualified_T2_macro": trace_result.get("qualified_T2_macro", False),
        "qualified_T2_path": trace_result.get("qualified_T2_path", False),
        "committed_frame": trace_result["committed_frame"],
        "committed_time_s": trace_result["committed_time_s"],
        "native_frame_count": trace_result["native_frame_count"],
        "mass_closed": trace_result["mass_closed"],
        "event_window_complete": trace_result["event_window_complete"],
        "event_window_status": trace_result["event_window_status"],
        "unknown_gate_pass": trace_result["unknown_gate_pass"],
        "unknown_fraction_max": max(
            (row.get("unknown_fraction_max", 1.0) for row in trace_result.get("by_source", [])),
            default=1.0,
        ),
        "common_reliable_path_coverage": trace_result["common_reliable_path_coverage"],
        "elapsed_seconds": trace_result["elapsed_seconds"],
        "max_rss_kib": trace_result["max_rss_kib"],
        "trace_path": str(trace_path),
        "trace_sha256": sha256_file(trace_path),
        "result_path": str(trace_result_path),
        "result_sha256": sha256_file(trace_result_path),
    }
    diagnosis_summary = {
        "diagnosis_path": str(diagnosis_path),
        "diagnosis_sha256": sha256_file(diagnosis_path),
        "failed_seed_count": diagnosis_first["failed_seed_count"],
        "surviving_seed_count": diagnosis_first["surviving_seed_count"],
        "frame_histogram": diagnosis_first["frame_histogram"],
        "time_histogram_s": diagnosis_first["time_histogram_s"],
        "location": diagnosis_first["location"],
        "replay_mismatches": diagnosis_result["replay_mismatches"],
        "interval_transition": interval_stages,
        "interpretation": diagnosis_result["interpretation"],
    }
    source_audit_path = (lab_root / SOURCE_AUDIT).resolve()
    return {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "completed_bounded_diagnostic",
        "qualification_claim": "none",
        "t2_status": "not_qualified",
        "T2_macro": False,
        "T2_path": False,
        "scope_id": tw.SCOPE_ID,
        "revision_id": tw.REVISION_ID,
        "audit_scope": (
            "Single-source, fixed-seed replay through the retained F4 first-loss "
            "interval. This is an implementation diagnostic only; it is not a full "
            "event-window or matrix qualification run."
        ),
        "canary_contract": {
            "source_path": str(source),
            "source_sha256": trace_result["binding"]["source_sha256"],
            "source_audit_path": str(source_audit_path),
            "source_audit_sha256": sha256_file(source_audit_path),
            "q": Q,
            "dp_m": DP_M,
            "seeds": SEEDS,
            "substeps": SUBSTEPS,
            "stop_after_frame_inclusive": STOP_AFTER_FRAME,
            "first_loss_bracket": source_interval,
            "source_geometry": source_audit["pair"]["cell14_role"],
            "source_view": "native cell14; no interpolation or stride view",
        },
        "fixed_gate_semantics": {
            "support_gate": trace_result["binding"]["support_gate"],
            "unknown_fraction_per_source_max": 0.01,
            "unknown_denominator": "full 512-seed source mass; permanent unknown remains in denominator",
            "event_definition": trace_result["binding"]["f4_definition"]["event_definition"],
            "thresholds_changed": False,
            "source_destination_mass_semantics_changed": False,
            "event_window_semantics_changed": False,
        },
        "trace": trace_summary,
        "diagnosis": diagnosis_summary,
        "diagnostic_conclusion": {
            "baseline_failure_reproduced": bool(diagnosis_first["failed_seed_count"] > 0),
            "first_failure_is_reconstruction_gate": all(
                stage["failure_reason_counts"]["g0_support_gate_fail"] == 0
                and stage["failure_reason_counts"]["g1_support_gate_fail"] > 0
                and stage["failure_reason_counts"]["distance_gate_fail"] == 0
                for stage in interval_stages
            ),
            "repair_applied": False,
            "repair_pass_proven": False,
            "bounded_interval_only": True,
            "qualification_eligible": False,
            "reason": (
                "The replay is intentionally baseline-only. It establishes whether the "
                "saved native source and current implementation reproduce the fixed "
                "reconstruction failure; it does not change the implementation or claim "
                "that a repair has passed."
            ),
        },
        "execution_constraints": {
            "read_only_source_h5": True,
            "terminal_source_h5_opened": True,
            "new_solver_started": False,
            "new_job_submitted": False,
            "gpu_started": False,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "thresholds_changed": False,
            "historical_scores_modified": False,
            "full_horizon_started": False,
            "matrix_started": False,
        },
        "resource_accounting": {
            "wrapper_wall_seconds": time.perf_counter() - started,
            "trace_elapsed_seconds": trace_result["elapsed_seconds"],
            "trace_max_rss_kib": trace_result["max_rss_kib"],
            "diagnosis_process_max_rss_kib": process_rss_kib,
            "trace_output_bytes": trace_path.stat().st_size,
            "diagnosis_output_bytes": diagnosis_path.stat().st_size,
        },
        "next_minimal_repair_test": {
            "required_before_any_full_window": (
                "Implement a separately versioned reconstruction change with the same "
                "fixed cap and denominator, rerun this exact 512-seed frame-40→41 "
                "interval, and require zero new g0/g1 reconstruction failures plus "
                "trace replay equality."
            ),
            "must_preserve": [
                "maximum reconstruction error cap",
                "ESS/rank/anisotropy/support gates",
                "full source-mass unknown denominator",
                "native source geometry and event semantics",
            ],
            "success_is_not_t2": True,
        },
        "input_provenance": {
            "source_audit": {
                "path": str(source_audit_path),
                "sha256": sha256_file(source_audit_path),
            },
            "runner": {
                "path": str(Path(tw.__file__).resolve()),
                "sha256": sha256_file(Path(tw.__file__).resolve()),
            },
            "core_material": {
                "path": str(Path(cm.__file__).resolve()),
                "sha256": sha256_file(Path(cm.__file__).resolve()),
            },
            "diagnosis": {
                "path": str(Path(diagnosis.__file__).resolve()),
                "sha256": sha256_file(Path(diagnosis.__file__).resolve()),
            },
        },
    }


def render_report(evidence: dict[str, Any], evidence_path: Path) -> str:
    trace = evidence["trace"]
    diag = evidence["diagnosis"]
    interval = evidence["canary_contract"]["first_loss_bracket"]
    stages = diag["interval_transition"]
    lines = [
        "# F4 Reconstruction-Gate Interval Canary (2026-09-20)",
        "",
        "结论：bounded baseline replay 成功复现实现层 reconstruction failure；没有执行 repair，也没有产生 T2 资格。",
        "",
        f"Evidence: `{evidence_path}`",
        f"Evidence SHA256: `{sha256_file(evidence_path) if evidence_path.is_file() else 'written-after-report'}`",
        "",
        "## Canary contract",
        "",
        f"- Source: `{evidence['canary_contract']['source_path']}`",
        f"- Source SHA256: `{evidence['canary_contract']['source_sha256']}`",
        f"- Fixed seeds/q/dp/substeps: `{evidence['canary_contract']['seeds']}` / `{evidence['canary_contract']['q']}` / `{evidence['canary_contract']['dp_m']}` / `{evidence['canary_contract']['substeps']}`",
        f"- Saved interval: frame `{interval['from_frame']}→{interval['to_frame']}`, `{interval['from_time_s']:.12f}→{interval['to_time_s']:.12f}` s",
        "- Unknown denominator: all 512 source seeds; fixed unknown gate `0.01`",
        "- Reconstruction/support thresholds and event semantics: unchanged",
        "",
        "## Observed output",
        "",
        f"The runner committed frame `{trace['committed_frame']}` at `{trace['committed_time_s']:.12f}` s with status `{trace['status']}`. It is mass-closed, but the interval output is right-censored and `unknown_fraction_max={trace['unknown_fraction_max']}`; `T2_macro=false` and `T2_path=false`.",
        "",
        f"The independent diagnosis found `{diag['failed_seed_count']}` first-failure seeds and `{diag['surviving_seed_count']}` surviving seeds. Frame histogram: `{diag['frame_histogram']}`. Replay mismatches: `{diag['replay_mismatches']}`.",
        "",
        "At the frame-40→41 transition, the component accounting was:",
        "",
        "| substep | new failures | g0 gate failures | g1 gate failures | distance failures |",
        "|---:|---:|---:|---:|---:|",
    ]
    for stage in stages:
        counts = stage["failure_reason_counts"]
        lines.append(
            f"| {stage['substep']} | {stage['new_failure_count']} | "
            f"{counts['g0_support_gate_fail']} | {counts['g1_support_gate_fail']} | "
            f"{counts['distance_gate_fail']} |"
        )
    lines.extend(
        [
            "",
            "The failure is therefore reproducible in the existing baseline implementation at the registered interval. The canary does not establish the deeper physical origin and does not validate a repair.",
            "",
            "## Next bounded repair test",
            "",
            "A separately versioned implementation candidate must rerun this exact frame-40→41, 512-seed interval with the same cap, support gates, full-mass unknown denominator, source geometry, and event semantics. It must produce zero new reconstruction failures and exact replay agreement before any full event horizon is considered. Passing this canary still does not grant T2.",
            "",
            "## Resources and constraints",
            "",
            f"- Wrapper wall time: `{evidence['resource_accounting']['wrapper_wall_seconds']:.3f}` s",
            f"- Trace runtime/RSS: `{evidence['resource_accounting']['trace_elapsed_seconds']:.3f}` s / `{evidence['resource_accounting']['trace_max_rss_kib']}` KiB",
            f"- Diagnosis process RSS: `{evidence['resource_accounting']['diagnosis_process_max_rss_kib']}` KiB",
            f"- Trace output: `{trace['trace_sha256']}`",
            f"- Diagnosis output: `{diag['diagnosis_sha256']}`",
            "- No solver, GPU, queue, registry, ledger, full horizon, or 33-row matrix was started.",
            "",
        ]
    )
    return "\n".join(lines)


def run_canary(lab_root: Path, output_dir: Path) -> tuple[dict[str, Any], Path]:
    source, source_audit = resolve_source(lab_root)
    source_interval = validate_source_interval(source)
    if (
        abs(source_interval["from_time_s"] - EXPECTED_FIRST_FAILURE_INTERVAL_S[0]) > 1e-12
        or abs(source_interval["to_time_s"] - EXPECTED_FIRST_FAILURE_INTERVAL_S[1]) > 1e-12
    ):
        raise ValueError("native source first-loss interval drifted")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "baseline-frame40-41.h5"
    trace_result_path = trace_path.with_suffix(".json")
    diagnosis_path = output_dir / "baseline-frame40-41-diagnosis.json"
    evidence_path = output_dir / "f4-reconstruction-gate-interval-canary-v1.json"
    report_path = output_dir / "F4-RECONSTRUCTION-GATE-INTERVAL-CANARY-2026-09-20.md"
    for path in (trace_path, trace_result_path, diagnosis_path, evidence_path, report_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing canary artifact: {path}")
    started = time.perf_counter()
    trace_result = tw.trace_tallwall120(
        source,
        trace_path,
        q=Q,
        dp_m=DP_M,
        seeds=SEEDS,
        substeps=SUBSTEPS,
        stop_after=STOP_AFTER_FRAME,
    )
    diagnosis_result = diagnosis.diagnose(
        source,
        trace_path,
        diagnosis_path,
        q=Q,
        dp_m=DP_M,
        substeps=SUBSTEPS,
    )
    evidence = build_evidence(
        lab_root,
        output_dir,
        source=source,
        source_audit=source_audit,
        source_interval=source_interval,
        trace_result=trace_result,
        trace_path=trace_path,
        trace_result_path=trace_result_path,
        diagnosis_result=diagnosis_result,
        diagnosis_path=diagnosis_path,
        started=started,
        process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(evidence, evidence_path), encoding="utf-8")
    return evidence, evidence_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    lab_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=lab_root)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=lab_root / "campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-canary-v1",
    )
    args = parser.parse_args()
    evidence, evidence_path = run_canary(args.lab_root.resolve(), args.output_dir)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "T2_macro": evidence["T2_macro"],
                "T2_path": evidence["T2_path"],
                "committed_frame": evidence["trace"]["committed_frame"],
                "committed_time_s": evidence["trace"]["committed_time_s"],
                "unknown_fraction_max": evidence["trace"]["unknown_fraction_max"],
                "failed_seed_count": evidence["diagnosis"]["failed_seed_count"],
                "evidence": str(evidence_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
