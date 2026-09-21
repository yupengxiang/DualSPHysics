"""Build a read-only evidence report for the bounded F3 high-seed canary.

The report generator consumes terminal artifacts only.  It rechecks the
high-seed trace reader contract, mass closure, checkpoint hash, event
denominators, and source hash, then records the already completed 4096-seed
full-window row29/31 results and the fixed CDF bounds from the source-window
audit.  It writes evidence and a Markdown report; it never submits work or
changes a registry, ledger, score, or historical artifact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f3_f4_t2_cpu_source_window_audit_v1 import audit_f3_trace_h5
from scripts.f3_native_volume_mls_high_seed_v1 import high_seed_binding


SCHEMA = "core.material.f3.native_volume_mls.high_seed_quadrature_report.v1"
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
FULL_WINDOW_S = 8.350012828223477


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _quantiles(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        return {"count": 0, "p50": None, "p90": None,
                "p95": None, "p99": None}
    q = np.quantile(values, [0.50, 0.90, 0.95, 0.99])
    return {"count": int(len(values)), "p50": float(q[0]),
            "p90": float(q[1]), "p95": float(q[2]), "p99": float(q[3])}


def _event_metrics(times: np.ndarray, values: np.ndarray, select: np.ndarray,
                   seed_mass: float, window_end_s: float) -> dict[str, Any]:
    selected = np.asarray(values, dtype=np.float64)[select]
    finite = np.isfinite(selected)
    event_times = selected[finite]
    count = int(np.count_nonzero(finite))
    return {
        "event_count": count,
        "event_mass_kg": float(count * seed_mass),
        "cdf_at_window_end": float(count / np.count_nonzero(select)),
        "cdf_denominator_policy": "all geometric seeds carrying this source label",
        "censored_fraction": float(1.0 - count / np.count_nonzero(select)),
        "window_end_s": float(window_end_s),
        "time_quantiles_s": _quantiles(event_times),
        "event_time_min_s": float(np.min(event_times)) if count else None,
        "event_time_max_s": float(np.max(event_times)) if count else None,
        "time_axis_frame_count": int(len(times)),
    }


def _source_mass_metrics(handle: h5py.File, summary: dict[str, Any]) -> dict[str, Any]:
    labels = np.asarray(handle["source_label"][:], dtype=np.int8)
    times = np.asarray(handle["time"][:], dtype=np.float64)
    first = np.asarray(handle["first_passage"][-1], dtype=np.float64)
    returned = np.asarray(handle["return_time"][-1], dtype=np.float64)
    residence = np.asarray(handle["residence_opposite"][-1], dtype=np.float64)
    position = np.asarray(handle["position"][-1], dtype=np.float64)
    total_mass = float(summary["native_initial_mass_kg"])
    seed_mass = total_mass / len(labels)
    rows = []
    for source in (0, 1):
        select = labels == source
        destination = (position[:, 0] >= 0.0) if source == 0 else (position[:, 0] < 0.0)
        destination &= select
        source_mass = float(np.count_nonzero(select) * seed_mass)
        residence_selected = residence[select]
        rows.append({
            "source": source,
            "seed_count": int(np.count_nonzero(select)),
            "source_mass_kg": source_mass,
            "destination_current_mass_kg": float(np.count_nonzero(destination) * seed_mass),
            "first_passage": _event_metrics(times, first, select, seed_mass,
                                              float(times[-1])),
            "return": _event_metrics(times, returned, select, seed_mass,
                                      float(times[-1])),
            "residence_opposite_mass_weighted_mean_s": float(
                np.mean(residence_selected)),
            "residence_opposite_quantiles_s": _quantiles(residence_selected),
            "residence_censored_fraction": float(
                np.count_nonzero(~np.isfinite(first[select])) /
                np.count_nonzero(select)),
        })
    return {
        "total_initial_mass_kg": total_mass,
        "seed_mass_kg": seed_mass,
        "mass_by_source_kg": {str(row["source"]): row["source_mass_kg"] for row in rows},
        "mass_sum_error_kg": float(sum(row["source_mass_kg"] for row in rows) - total_mass),
        "by_source": rows,
    }


def _checkpoint_inventory(product: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(product.glob("trace.h5.checkpoint*.npz")):
        result.append({"path": str(path), "sha256": sha256_file(path),
                       "bytes": int(path.stat().st_size)})
    manifest = product / "trace.h5.checkpoint.json"
    if manifest.is_file():
        result.append({"path": str(manifest), "sha256": sha256_file(manifest),
                       "bytes": int(manifest.stat().st_size)})
    return result


def _compact_full_row(summary_path: Path, *, row: int,
                      cdf_audit: dict[str, Any]) -> dict[str, Any]:
    summary = read_json(summary_path)
    trace_path = Path(summary["output"]["path"])
    terminal_events: dict[str, dict[str, float]] = {}
    if trace_path.is_file():
        with h5py.File(trace_path, "r") as handle:
            labels = np.asarray(handle["source_label"][:], dtype=np.int8)
            terminal_position = np.asarray(handle["position"][-1], dtype=np.float64)
            terminal_first = np.asarray(handle["first_passage"][-1], dtype=np.float64)
            terminal_return = np.asarray(handle["return_time"][-1], dtype=np.float64)
        seed_mass = float(summary["native_initial_mass_kg"]) / len(labels)
        for source in (0, 1):
            select = labels == source
            destination = (terminal_position[:, 0] >= 0.0) if source == 0 else (
                terminal_position[:, 0] < 0.0)
            destination &= select
            terminal_events[str(source)] = {
                "destination_current_mass_kg": float(np.count_nonzero(destination) * seed_mass),
                "first_passage_mass_kg": float(np.count_nonzero(
                    np.isfinite(terminal_first) & select) * seed_mass),
                "return_mass_kg": float(np.count_nonzero(
                    np.isfinite(terminal_return) & select) * seed_mass),
            }
    source_rows = []
    for item in summary.get("source_rows", []):
        source_key = str(int(item["source"]))
        source_rows.append({
            "source": int(item["source"]),
            "source_mass_kg": float(summary["native_initial_mass_kg"] *
                                     item["initial_mass_fraction"]),
            **terminal_events.get(source_key, {}),
            "seed_denominator": int(round(summary["seed_count"] *
                                           item["initial_mass_fraction"])),
            "unknown_fraction": float(item["unknown_fraction"]),
            "unknown_mass_kg": float(summary["native_initial_mass_kg"] *
                                      item["initial_mass_fraction"] *
                                      item["unknown_fraction"]),
            "reliable_path_coverage": float(item["reliable_path_coverage"]),
            "observed_first_passage_fraction": float(item["observed_first_passage_fraction"]),
            "observed_return_fraction": float(item["observed_return_fraction"]),
            "residence_opposite_quantiles_s_lower_bound": item[
                "residence_opposite_quantiles_s_lower_bound"],
            "first_failure_frame": item["first_failure_frame"],
            "first_failure_time_s": item["first_failure_time_s"],
            "failure_reason_counts": item["final_failure_reason_counts"],
        })
    cdf_row = next(item for item in cdf_audit["f3"]["rows"]
                   if int(item["row"]) == row)
    return {
        "matrix_row": row,
        "summary_path": str(summary_path),
        "summary_sha256": sha256_file(summary_path),
        "trace_path": str(trace_path),
        "trace_exists": trace_path.is_file(),
        "trace_sha256_recorded": summary["output"]["sha256"],
        "trace_sha256_recomputed": sha256_file(trace_path) if trace_path.is_file() else None,
        "seed_count": int(summary["seed_count"]),
        "substeps": int(summary["binding"]["substeps"]),
        "source_window": summary["source_window"],
        "total_initial_mass_kg": float(summary["native_initial_mass_kg"]),
        "native_mass_closed": bool(summary["mass_closed"]),
        "source_rows": source_rows,
        "global_common_reliable_path_coverage": float(
            summary["common_reliable_path_coverage"]),
        "terminal_unknown_fraction_max": float(summary["unknown_fraction_max"]),
        "unknown_gate_pass": bool(all(row_data["unknown_fraction"] <= UNKNOWN_LIMIT
                                       for row_data in source_rows)),
        "event_window_complete": bool(float(summary["source_window"]["time_end_s"]) >=
                                       FULL_WINDOW_S and
                                       int(summary["source_window"]["frame_count_committed"]) == 836),
        "reader_integrity_pass": bool(cdf_row["trace_audit"]["integrity_pass"] and
                                       cdf_row["source_audit"]["integrity_pass"]),
        "checkpoint_integrity_pass": bool(cdf_row["trace_audit"]["checkpoint"]["pass"]),
        "cdf_comparison_bounds": cdf_row["cdf_comparison"],
        "cdf_gate_pass": bool(cdf_row["cdf_comparison"]["0"]["pass"] and
                               cdf_row["cdf_comparison"]["1"]["pass"]),
        "diagnostics": summary["diagnostics"],
        "qualification_claim": summary["qualification_claim"],
    }


def build_report(*, canary_summary_path: Path, canary_h5_path: Path,
                 source_path: Path, source_audit_path: Path,
                 t2_audit_path: Path, full_row29_summary_path: Path,
                 full_row31_summary_path: Path, evidence_path: Path,
                 report_path: Path, resource_ledger: dict[str, Any]) -> dict[str, Any]:
    canary_summary = read_json(canary_summary_path)
    canary_receipt = read_json(canary_h5_path.with_name("trace.high-seed-receipt.json"))
    source_audit = read_json(source_audit_path)
    t2_audit = read_json(t2_audit_path)
    with h5py.File(source_path, "r") as source_handle:
        source_times = np.asarray(source_handle["time"][:], dtype=np.float64)
        source_mass = float(np.asarray(source_handle["mass"][0], dtype=np.float64).sum())
    source_sha = sha256_file(source_path)
    source_audit["_times"] = source_times.tolist()
    source_audit["hash"] = {"sha256": source_sha}
    source_audit["mass"] = {"reference_mass_kg": source_mass}
    canary_hash = sha256_file(canary_h5_path)
    canary_summary_hash = sha256_file(canary_summary_path)
    canary_trace_audit = audit_f3_trace_h5(
        canary_h5_path,
        summary=canary_summary,
        source_audit=source_audit,
        expected_sha256=canary_hash,
        expected_source_sha256=source_sha,
        expected_frames=int(canary_summary["source_window"]["frame_count_committed"]),
        expected_seed_count=8192,
    )
    with h5py.File(canary_h5_path, "r") as canary_handle:
        canary_mass = _source_mass_metrics(canary_handle, canary_summary)
        canary_shapes = {name: list(canary_handle[name].shape)
                         for name in canary_handle}
        committed = int(canary_handle.attrs["committed"])
        canary_binding = json.loads(str(canary_handle.attrs["binding"]))

    high_binding = dict(canary_receipt["high_seed_quadrature"])
    high_binding["seed_hash_from_trace"] = canary_binding["seed_hash"]
    high_binding["walls_sha256_from_trace"] = canary_binding["walls_sha256"]
    full29 = _compact_full_row(full_row29_summary_path, row=29, cdf_audit=t2_audit)
    full31 = _compact_full_row(full_row31_summary_path, row=31, cdf_audit=t2_audit)

    evidence = {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "diagnostic_complete; no_t2_closure",
        "qualification_claim": "none",
        "t2_decision": {
            "acceptable_closure_path": False,
            "T2_macro": False,
            "T2_path": False,
            "reason_codes": [
                "high_seed_window_only_0p0400199586s",
                "registered_f3_native_dense_pair_not_available_for_amp0p95_amp1p05",
                "existing_4096_row29_row31_unknown_gate_failure",
                "existing_row29_row31_cdf_sup_failure",
                "registered_f3_matrix_scope_not_complete",
            ],
            "fixed_thresholds": {
                "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
                "cdf_sup_abs_difference_max": CDF_LIMIT,
                "event_window_required": True,
            },
        },
        "high_seed_binding": high_binding,
        "inputs": {
            "source_h5": {"path": str(source_path), "sha256": source_sha,
                           "frames": int(len(source_times)),
                           "time_end_s": float(source_times[-1]),
                           "mass_kg": source_mass,
                           "mass_by_seed_source_kg": source_mass / 2.0},
            "source_audit": {"path": str(source_audit_path),
                              "sha256": sha256_file(source_audit_path)},
            "t2_source_window_audit": {"path": str(t2_audit_path),
                                        "sha256": sha256_file(t2_audit_path)},
            "prepared": {
                "path": canary_summary["audit"]["prepared_case"]["path"],
                "sha256": canary_summary["audit"]["prepared_case"]["sha256"],
            },
            "base_runner": {
                "path": str(Path(__file__).with_name("f3_native_volume_mls_v2.py")),
                "sha256": canary_summary["code_sha256"],
            },
            "high_seed_wrapper": {
                "path": str(Path(__file__).with_name("f3_native_volume_mls_high_seed_v1.py")),
                "sha256": canary_receipt["wrapper_code_sha256"],
            },
        },
        "high_seed_canary": {
            "run_id": f"{canary_h5_path.parent.parent.parent.name}/"
                      f"{canary_h5_path.parent.parent.name}",
            "summary_path": str(canary_summary_path),
            "summary_sha256": canary_summary_hash,
            "trace_path": str(canary_h5_path),
            "trace_sha256": canary_hash,
            "trace_schema": canary_summary["schema"],
            "checkpoint_manifest": canary_summary["checkpoint_manifest"],
            "checkpoint_inventory": _checkpoint_inventory(canary_h5_path.parent),
            "committed_frame": committed,
            "frame_count": int(canary_summary["source_window"]["frame_count_committed"]),
            "time_end_s": float(canary_summary["source_window"]["time_end_s"]),
            "seed_count": int(canary_summary["seed_count"]),
            "substeps": int(canary_summary["binding"]["substeps"]),
            "mass_events_coverage": canary_mass,
            "integrity_audit": canary_trace_audit,
            "shapes": canary_shapes,
            "qualification_claim": "none; bounded CPU high-seed diagnostic only",
        },
        "resource_ledger": resource_ledger,
        "existing_full_window_rows": [full29, full31],
        "registered_cdf_failure": {
            "source_window_audit": str(t2_audit_path),
            "by_source": t2_audit["f3"]["cdf_gate"]["by_source"],
            "pass": bool(t2_audit["f3"]["cdf_gate"]["pass"]),
        },
        "executable_next_legal_path": {
            "status": "blocked_pending_native_dense_source_and_compute_budget",
            "steps": [
                "Produce native F3 CFD output at 0.002 s for the same amp0.95 and amp1.05 source geometries through 8.35 s; retain 4176 native frames and full source mass audit.",
                "Create a direct native frame map [0,5,...,4175] for the matched 0.01 s comparison; no interpolation or synthesized frames.",
                "Run one registered source row at a time with the fixed 8192 midpoint quadrature, current-frame mass/density semantics, fixed walls, fixed thresholds, and resumable checkpoints.",
                "Before any full horizon run, replace per-query neighbor scans with a per-frame reusable spatial index or an explicitly reviewed equivalent; preserve candidate backend outputs and verify against a short same-frame replay.",
                "Recompute source/destination mass, all-seed first-passage/return/residence CDFs, unknown mass, event-window completeness, and checkpoint integrity. Grant no credit if any source cell, CDF bound, or dense cadence precondition fails.",
            ],
            "do_not": [
                "Do not infer full-window unknown or CDF from the 0.04002 s canary.",
                "Do not renormalize away unknown seeds or change any fixed gate.",
                "Do not start the projected 10-15 hour 8192 full run from this diagnostic receipt.",
            ],
        },
        "code_sha256": sha256_file(__file__),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")

    report = _markdown_report(evidence, evidence_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return evidence


def _markdown_report(evidence: dict[str, Any], evidence_path: Path) -> str:
    canary = evidence["high_seed_canary"]
    mass = canary["mass_events_coverage"]
    rows = evidence["existing_full_window_rows"]
    lines = [
        "# F3 high-seed quadrature repair diagnostic",
        "",
        "This report records a bounded CPU diagnostic and does not grant material T2 credit.",
        "The run used the registered F3 source box, finite walls, half-space source labels,",
        "current native mass/density semantics, all-seed event denominators, and unchanged gates.",
        "",
        "## Result",
        "",
        f"The 8192-seed canary committed {canary['frame_count']} frames through "
        f"{canary['time_end_s']:.12f} s. It was deliberately stopped before the 8.350012828223477 s "
        "qualification horizon. Both source cells had zero unknown seeds in this short window, "
        "but no first-passage or return event occurred, so its CDF and residence results are "
        "censored diagnostics. The acceptable T2 closure path remains **blocked**.",
        "",
        "| item | value |",
        "|---|---:|",
        f"| seeds | {canary['seed_count']} (4096 per source) |",
        f"| source mass | {mass['total_initial_mass_kg']:.12f} kg |",
        f"| source 0 / source 1 mass | {mass['mass_by_source_kg']['0']:.12f} / {mass['mass_by_source_kg']['1']:.12f} kg |",
        f"| destination current mass | {sum(row['destination_current_mass_kg'] for row in mass['by_source']):.12f} kg |",
        f"| first-passage mass | {sum(row['first_passage']['event_mass_kg'] for row in mass['by_source']):.12f} kg |",
        f"| return mass | {sum(row['return']['event_mass_kg'] for row in mass['by_source']):.12f} kg |",
        f"| terminal unknown fraction | {canary['integrity_audit']['unknown_gate']['maximum_source_unknown_fraction']:.12f} |",
        f"| common reliable coverage | {canary['integrity_audit']['source_rows'][0]['terminal_reliable_fraction']:.12f} / {canary['integrity_audit']['source_rows'][1]['terminal_reliable_fraction']:.12f} |",
        f"| mass closure error | {mass['mass_sum_error_kg']:.3e} kg |",
        f"| reader/checkpoint integrity | {canary['integrity_audit']['integrity_pass']} / {canary['integrity_audit']['checkpoint']['pass']} |",
        "",
        "The first process was intentionally killed after frame 2 append. Its frame 0/1 generations "
        "remain in the checkpoint inventory; the resume process restored frame 1 from the manifest "
        "and committed frames 2–4 with the same seed hash. This demonstrates recoverability, not "
        "qualification.",
        "",
        "## Existing full-window evidence",
        "",
        "The completed 4096-seed row29/31 traces cover the 8.350012828223477 s .01 s source window, "
        "with closed native mass and valid reader/checkpoint artifacts. They still fail the fixed "
        "per-source unknown gate and the registered CDF bound:",
        "",
        "| row | source unknown fractions | unknown gate | CDF maximum by source | CDF gate |",
        "|---:|---|---|---|---|",
    ]
    for row in rows:
        unknown = ", ".join(f"s{item['source']}={item['unknown_fraction']:.9f}"
                             for item in row["source_rows"])
        cdf = ", ".join(f"s{source}={bound['maximum']:.9f}"
                         for source, bound in row["cdf_comparison_bounds"].items())
        lines.append(f"| {row['matrix_row']} | {unknown} | {row['unknown_gate_pass']} | {cdf} | {row['cdf_gate_pass']} |")
    lines += [
        "",
        "For both full-window rows, each source denominator represents "
        "7.290000189096 kg. The evidence JSON records terminal destination mass, "
        "first-passage mass, return mass, residence quantiles, reader integrity, "
        "checkpoint integrity, and the all-seed CDF bounds per source.",
        "",
        "The source-window audit records CDF sup bounds of 0.06103515625 for source 0 and "
        "0.06005859375 for source 1 against the fixed 0.02 limit. The 4096 traces also expose "
        "wall-occlusion and low-effective-sample-size failures; increasing the denominator alone "
        "cannot be treated as a repair.",
        "",
        "## Resource and stopping record",
        "",
        f"The controlled first attempt used {evidence['resource_ledger']['first_attempt']['wall_seconds']:.2f} s wall time "
        f"and {evidence['resource_ledger']['first_attempt']['max_rss_kib']} KiB peak RSS before SIGKILL. "
        f"Resume used {evidence['resource_ledger']['resume_attempt']['wall_seconds']:.2f} s wall time "
        f"and {evidence['resource_ledger']['resume_attempt']['max_rss_kib']} KiB peak RSS. "
        f"The measured recovery work projects to about {evidence['resource_ledger']['full_window_projection']['hours']:.2f} h "
        "for one 8192-seed, 835-interval trace, so no full high-seed run was started.",
        "",
        "## Legal next path",
        "",
        "The next qualification attempt needs native .002 s CFD output for the same amp0.95 and "
        "amp1.05 source geometries, a direct [0,5,...,4175] matched .01 s selection, and a "
        "resumable 8192-seed run after a reviewed spatial-index optimization. The optimization "
        "must preserve current-frame fields, fixed walls, event semantics, denominator policy, "
        "and gates. The existing amp1.0 dense pair is an engineering diagnostic with a none claim "
        "and cannot substitute for those source rows.",
        "",
        f"Evidence: `{evidence_path}`",
        "",
        f"Evidence generator SHA256: `{evidence['code_sha256']}`",
        "",
    ]
    return "\n".join(lines)


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canary-summary", type=Path, required=True)
    parser.add_argument("--canary-h5", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--t2-audit", type=Path, required=True)
    parser.add_argument("--full-row29-summary", type=Path, required=True)
    parser.add_argument("--full-row31-summary", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    ledger = {
        "run_id": "f3-high-seed-quadrature-row29-v1-8192-s4-stop4-resume",
        "policy": "short CPU diagnostic only; no large matrix; no solver/GPU/registry/ledger mutation",
        "first_attempt": {
            "purpose": "checkpoint recovery setup; SIGKILL after frame 2 HDF5 append",
            "return_code": 137,
            "wall_seconds": 102.55,
            "user_seconds": 116.21,
            "system_seconds": 1.99,
            "max_rss_kib": 622936,
            "committed_checkpoint_frames_before_kill": [0, 1],
        },
        "resume_attempt": {
            "purpose": "resume manifest frame 1 and commit frames 2 through 4",
            "return_code": 0,
            "wall_seconds": 148.08,
            "user_seconds": 161.64,
            "system_seconds": 1.74,
            "max_rss_kib": 739688,
            "final_committed_frame": 4,
        },
        "full_window_projection": {
            "basis": "five interval computations across killed setup plus resume; includes one recomputed interval",
            "measured_work_seconds": 250.63,
            "projected_intervals": 835,
            "projected_seconds": 41855.525,
            "hours": 11.626534722222223,
            "decision": "stop before full 8192 run; projected CPU/RAM cost is disproportionate for this diagnostic",
        },
    }
    evidence = build_report(
        canary_summary_path=args.canary_summary,
        canary_h5_path=args.canary_h5,
        source_path=args.source,
        source_audit_path=args.source_audit,
        t2_audit_path=args.t2_audit,
        full_row29_summary_path=args.full_row29_summary,
        full_row31_summary_path=args.full_row31_summary,
        evidence_path=args.evidence,
        report_path=args.report,
        resource_ledger=ledger,
    )
    print(json.dumps({"schema": evidence["schema"],
                      "status": evidence["status"],
                      "acceptable_closure_path": evidence["t2_decision"]["acceptable_closure_path"],
                      "evidence": str(args.evidence),
                      "report": str(args.report),
                      "evidence_sha256": sha256_file(args.evidence),
                      "report_sha256": sha256_file(args.report)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
