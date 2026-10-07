#!/usr/bin/env python3
"""Build a source-bound, diagnostic status for all fourteen sentinels.

This forward-only status joins the immutable v1 status snapshot with the
current SaveDt same/half-CFL request bindings and the completed F4 text
receipt audit. It records spatial/mass gates, exact source controls and full
window plans separately from integration/output evidence. It does not read
HDF5 or native Part payloads, launch a solver, or grant QI/QN/QE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from stage2_fourteen_reference_status_v1 import build as build_v1


SCHEMA = "ds02.stage2.fourteen-reference-status.v2"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
SAVEDT_BINDING = REFERENCE / "stage2_savedt_cfl_pair_binding_v1.json"
F4_SAVEDT_BINDING = REFERENCE / "stage2_f4_dp0_savedt_pair_binding_v1.json"
ROW_SEMANTICS = REFERENCE / "stage2_savedt_row_count_semantics_v2.json"
LOSSLESS_MANIFEST = REFERENCE / "stage2_f4_full_lossless_roundtrip_inputs_v1/manifest_v2.json"
LOSSLESS_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-full-lossless-roundtrip-v2/f4_s1_full_window_native_lossless_roundtrip_v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def optional_record(path_text: str | None) -> dict[str, Any] | str:
    if not path_text:
        return "UNKNOWN"
    path = Path(path_text)
    return file_record(path) if path.is_file() else {"path": str(path), "status": "MISSING"}


def compact_mass_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gates: dict[str, int] = {}
    candidates: list[Any] = []
    for row in rows:
        gate = row.get("whole_initial_mass_gate", "UNKNOWN")
        gates[gate] = gates.get(gate, 0) + 1
        candidates.append({
            "label": row.get("label"),
            "candidate_dp_m": row.get("candidate_dp_m"),
            "whole_initial_mass_error_pct": row.get("whole_initial_mass_error_pct"),
            "whole_initial_mass_gate": gate,
            "per_source_mass_status": row.get("per_source_mass_status", "UNKNOWN"),
            "scientific_qualification": row.get("scientific_qualification", {}),
        })
    return {"counts_by_gate": gates, "candidates": candidates}


def generic_savedt_rows(binding: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in binding.get("requests", []):
        request_path = Path(row["request_path"])
        request = load(request_path)
        result.setdefault(row["sentinel_id"], []).append({
            "mode": row["mode"],
            "execution_state": "PREPARED_LAUNCH_DISABLED",
            "request": file_record(request_path),
            "case_id": request.get("case_id"),
            "attempt_id": request.get("attempt_id"),
            "physical_window_s": request.get("physical_window_s"),
            "requested_tmax_text": request.get("requested_tmax_text", row.get("requested_tmax_text")),
            "requested_tout_s": request.get("save_interval_s", row.get("requested_tout_s")),
            "planned_frames": request.get("planned_frames", row.get("planned_frames")),
            "estimated_storage_bytes": request.get("estimated_storage_bytes"),
            "overlay_xml": optional_record((row.get("overlay_xml") or {}).get("path")),
            "overlay_bi4": {
                "path": (row.get("overlay_bi4") or {}).get("path", "UNKNOWN"),
                "bytes": (row.get("overlay_bi4") or {}).get("bytes", "UNKNOWN"),
                "sha256": (row.get("overlay_bi4") or {}).get("sha256", "UNKNOWN"),
                "digest_scope": "source-bound metadata; no payload read by this report",
            },
            "xml_diff_proof": row.get("xml_diff_proof", "UNKNOWN"),
            "old_preflight_control_window": row.get("old_preflight_window", "UNKNOWN"),
            "dt_trace_status": "PENDING_GUARDED_RUN; overlay is prepared but has no actual output",
            "clamp_status": "PENDING_GUARDED_RUN; no clamp result inferred from old RunPARTs",
            "launch_disabled": request.get("launch_disabled", True),
            "solver_started": False,
            "hdf5_read": False,
        })
    return result


def f4_savedt_rows(binding: dict[str, Any], semantics: dict[str, Any]) -> list[dict[str, Any]]:
    actual_by_mode = semantics.get("runs", {})
    rows: list[dict[str, Any]] = []
    for item in binding.get("modes", []):
        mode = item["mode"]
        req = item.get("request", {})
        request_path = Path(req["path"])
        actual = actual_by_mode.get(mode)
        row: dict[str, Any] = {
            "mode": mode,
            "execution_state": "COMPLETED_TEXT_AUDIT" if actual else "PREPARED_LAUNCH_DISABLED",
            "request": file_record(request_path),
            "case_id": req.get("case_id"),
            "attempt_id": req.get("attempt_id"),
            "physical_window_s": [0.0, item.get("tmax_s")],
            "requested_tmax_text": str(item.get("tmax_s")),
            "requested_tout_s": item.get("tout_s"),
            "planned_frames": item.get("planned_frames"),
            "estimated_storage_bytes": item.get("storage_reservation_bytes"),
            "overlay_xml": optional_record((item.get("overlay", {}).get("xml") or {}).get("path")),
            "overlay_bi4": {
                "path": (item.get("overlay", {}).get("bi4") or {}).get("path", "UNKNOWN"),
                "bytes": (item.get("overlay", {}).get("bi4") or {}).get("bytes", "UNKNOWN"),
                "sha256": (item.get("overlay", {}).get("bi4") or {}).get("sha256", "UNKNOWN"),
                "digest_scope": "source-bound metadata; no payload read by this report",
            },
            "xml_diff_proof": item.get("overlay", {}).get("diff", "UNKNOWN"),
            "dt_trace_status": item.get("per_step_dt_status", "UNKNOWN"),
            "clamp_status": item.get("clamp_status", "UNKNOWN"),
            "launch_disabled": not bool(actual),
            "solver_started": bool(actual),
            "hdf5_read": False,
        }
        if actual:
            row["actual_text_audit"] = {
                "receipt": actual.get("receipt"),
                "output_text": actual.get("output_text"),
                "counts": actual.get("counts"),
                "time_integrity": actual.get("time_integrity"),
                "dt_bounds": actual.get("dt_bounds"),
                "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            }
        rows.append(row)
    return rows


def by_mode(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["mode"]: row for row in rows}


def evidence_matrix(old: dict[str, Any], savedt_modes: dict[str, dict[str, Any]],
                    semantics: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    """Return explicit bounded statuses with stable evidence identifiers.

    PASS here means the named source/preparation check is evidenced. It never
    means QI/QN/QE or a physical observer result passed.
    """
    source = old.get("source", {})
    source_xml = source.get("xml", {})
    source_receipt = source.get("solver_receipt", {})
    source_window = "PASS" if source_xml.get("accessible") and source_receipt.get("accessible") and source.get("full_window_s") else "UNKNOWN"
    control_status = "PASS" if len(savedt_modes) == 2 and all(
        isinstance(row.get("xml_diff_proof"), dict) for row in savedt_modes.values()
    ) else "UNKNOWN"
    spatial = old.get("spatial_candidates_from_exact_graph", [])
    gates = [str(row.get("whole_initial_mass_gate", "UNKNOWN")) for row in spatial]
    if len(spatial) < 3 or any(g == "None" or g == "UNKNOWN" for g in gates):
        mass_status = "UNKNOWN"
    elif any("HARD_FAIL" in g for g in gates):
        mass_status = "FAIL"
    else:
        mass_status = "PASS"

    if sentinel_id == "F4-S1":
        pair = semantics.get("pair_comparison", {})
        # Keep the conditional explicit and avoid treating text endpoint
        # agreement as a scientific time result.
        time_status = "FAIL" if pair.get("pair_diagnostic", {}).get("half_endpoint_shortfall_s", 0.0) > 0 else "PASS"
        time_reason = "F4 half-CFL text run ended short of requested/source endpoint and had aggregate DtMin clamps" if time_status == "FAIL" else "F4 same/half text endpoints agree"
        time_ids = ["f4.same.DtAllInfo.RunPARTs.Run.out", "f4.half.DtAllInfo.RunPARTs.Run.out", "f4.savedt.row_semantics_v2"]
    else:
        time_status = "UNKNOWN"
        time_reason = "SaveDt same/half pair is launch-disabled; no actual dt sequence or clamp result"
        time_ids = [f"{sentinel_id}.savedt.same.request", f"{sentinel_id}.savedt.half.request"]
    return {
        "source_window": {
            "status": source_window,
            "scope": "exact CURRENT source XML/solver receipt window binding",
            "evidence_ids": [f"{sentinel_id}.current.generated_xml", f"{sentinel_id}.current.solver_receipt"],
        },
        "control": {
            "status": control_status,
            "scope": "SaveDt XML overlay and CFL-difference proof; does not prove solver execution",
            "evidence_ids": [f"{sentinel_id}.savedt.same.request", f"{sentinel_id}.savedt.half.request"],
        },
        "initial_mass_3grid": {
            "status": mass_status,
            "scope": "three exact-graph source/candidate mass gates only; no geometry or scientific qualification",
            "evidence_ids": [f"{sentinel_id}.minimal14.graph", f"{sentinel_id}.mass-fit-reports"],
            "gate_values": gates,
        },
        "time_integration": {
            "status": time_status,
            "scope": "text receipt/DtAll row and endpoint diagnostic; observer/time scientific credit remains UNKNOWN",
            "reason": time_reason,
            "evidence_ids": time_ids,
        },
        "output_observables": {
            "status": "UNKNOWN",
            "scope": "planned native/typed output is source-bound; physical observer calibration and comparison are absent",
            "evidence_ids": [f"{sentinel_id}.savedt.output-plan", f"{sentinel_id}.observer-calibration"],
        },
    }


def build() -> dict[str, Any]:
    base = build_v1()
    savedt = load(SAVEDT_BINDING)
    f4 = load(F4_SAVEDT_BINDING)
    semantics = load(ROW_SEMANTICS)
    lossless_manifest = load(LOSSLESS_MANIFEST)
    generic = generic_savedt_rows(savedt)
    f4_rows = f4_savedt_rows(f4, semantics)
    sentinels: list[dict[str, Any]] = []
    for old in base["sentinels"]:
        sid = old["sentinel_id"]
        rows = f4_rows if sid == "F4-S1" else generic.get(sid, [])
        savedt_modes = by_mode(rows)
        candidate_mass = compact_mass_gate(old.get("completed_mass_audits", []))
        source = old.get("source", {})
        old_time = old.get("time_output", {})
        sentinels.append({
            "sentinel_id": sid,
            "family_id": old.get("family_id"),
            "physical_case_id": old.get("physical_case_id"),
            "identity": {
                "current_identity_status": old.get("current_identity_status", "UNKNOWN"),
                "source_xml": source.get("xml", "UNKNOWN"),
                "source_solver_receipt": source.get("solver_receipt", "UNKNOWN"),
                "continuous_geometry_control": "SOURCE_BOUND; dp/h/mass/count are resolution fields and do not prove continuous-region equivalence",
            },
            "initial_state": {
                "status": "SOURCE_BOUND_WITH_MASS_AND_GEOMETRY_CAVEATS",
                "source_dp_m": source.get("dp_m"),
                "source_particles": source.get("particles"),
                "source_fluid_particles": source.get("fluid_particles"),
                "source_sample_mass_kg": source.get("sample_mass_kg"),
                "spatial_candidates": old.get("spatial_candidates_from_exact_graph", []),
                "completed_mass_audits": old.get("completed_mass_audits", []),
                "mass_gate_summary": candidate_mass,
                "geometry_motion_status": "SOURCE_INPUT_BINDING_ONLY; no solver qualification",
            },
            "control_window": {
                "source_cfl": source.get("cfl"),
                "source_half_cfl": source.get("half_cfl"),
                "source_full_window_s": source.get("full_window_s"),
                "source_dense_output_cadence_s": source.get("dense_output_cadence_s"),
                "old_preflight_control_window": old_time.get("original_same_half_cfl_dense", "UNKNOWN"),
                "savedt_request_controls": {
                    mode: {
                        "physical_window_s": row.get("physical_window_s"),
                        "requested_tmax_text": row.get("requested_tmax_text"),
                        "requested_tout_s": row.get("requested_tout_s"),
                        "xml_diff_proof": row.get("xml_diff_proof"),
                        "execution_state": row.get("execution_state"),
                    }
                    for mode, row in savedt_modes.items()
                },
            },
            "tolerance": {
                "registered_budget": base.get("quality_error_budget"),
                "observer_calibration": "UNKNOWN; consumer calibration must freeze field/time gates before scientific result",
                "time_and_output_rule": "time and output errors each <= one quarter of total gate after actual observer calibration; no result-specific widening",
            },
            "space": {
                "candidate_gate_summary": candidate_mass,
                "intentional_resolution_fields": "dp/h/mass/count/particle_blocks may differ by grid and are not themselves physical mismatch",
                "continuous_geometry_status": "UNKNOWN beyond exact source bindings",
                "scientific_spatial_qualification": "UNKNOWN",
            },
            "integration": {
                "savedt_same_cfl": savedt_modes.get("same_cfl", "NOT_BOUND"),
                "savedt_half_cfl": savedt_modes.get("half_cfl", "NOT_BOUND"),
                "dt_row_semantics": semantics.get("runs", {}).get("same_cfl") if sid == "F4-S1" else "PENDING_GUARDED_RUN",
                "half_cfl_clamp_or_endpoint_caveat": semantics.get("pair_comparison", {}).get("half_cfl") if sid == "F4-S1" else "PENDING_GUARDED_RUN",
                "actual_dt_sequence": "UNKNOWN for this sentinel until its guarded SaveDt run; F4 text audit is local to F4-S1",
                "per_step_clamp_locations": "UNKNOWN",
            },
            "output": {
                "full_window_retained": old_time.get("full_sentinel_window_retained", "UNKNOWN"),
                "planned_dense_requests": {
                    mode: {
                        "planned_frames": row.get("planned_frames"),
                        "estimated_storage_bytes": row.get("estimated_storage_bytes"),
                        "status": row.get("execution_state"),
                    }
                    for mode, row in savedt_modes.items()
                },
                "raw_native_preservation": "SOURCE IMMUTABLE; no deletion or replacement",
                "typed_observer_output": "UNKNOWN until separately dispatched and consumer-calibrated",
                "lossless_archive": ({
                    "status": "PREPARED_LAUNCH_DISABLED",
                    "manifest": file_record(LOSSLESS_MANIFEST),
                    "request": file_record(LOSSLESS_REQUEST),
                    "expected_frame_count": lossless_manifest["source_binding"]["expected_frame_count"],
                    "expected_raw_part_bytes": lossless_manifest["source_binding"]["expected_raw_part_bytes"],
                    "archive_bytes": "UNKNOWN_UNTIL_WORKER",
                    "per_frame_sha256": "WORKER_COMPUTED_PER_FRAME_AND_ROUNDTRIP_VERIFIED",
                    "two_frame_ratio_used_as_full_bound": False,
                } if sid == "F4-S1" else "UNKNOWN; no compression ratio inferred from two frames"),
            },
            "observer_calibration": old.get("observer_calibration", {"status": "UNKNOWN", "field_observables": "UNKNOWN"}),
            "evidence_matrix": evidence_matrix(old, savedt_modes, semantics, sid),
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "prior_v1_snapshot": old,
        })

    source_inputs = [
        {"path": str(SAVEDT_BINDING.resolve()), "sha256": sha256_file(SAVEDT_BINDING)},
        {"path": str(F4_SAVEDT_BINDING.resolve()), "sha256": sha256_file(F4_SAVEDT_BINDING)},
        {"path": str(ROW_SEMANTICS.resolve()), "sha256": sha256_file(ROW_SEMANTICS)},
        {"path": str(LOSSLESS_MANIFEST.resolve()), "sha256": sha256_file(LOSSLESS_MANIFEST)},
        {"path": str(LOSSLESS_REQUEST.resolve()), "sha256": sha256_file(LOSSLESS_REQUEST)},
        *base.get("source_inputs", []),
    ]
    return {
        "schema": SCHEMA,
        "status": "PREPARED_DIAGNOSTIC_ONLY_14_SENTINEL_STATUS_WITH_SAVEDT_PAIR_BINDINGS",
        "current_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                        capture_output=True, text=True).stdout.strip(),
        "scope": {
            "sentinel_count": len(sentinels),
            "reads_hdf5": False,
            "reads_native_payloads": False,
            "starts_solver": False,
            "starts_gpu": False,
            "source_policy": "exact CURRENT XML/BI4/GenCase/solver receipt bindings; no latest-glob fallback",
            "spatial_policy": "mass/geometry/control gates remain separate; whole initial mass <=1% is diagnostic input compatibility only",
            "integration_policy": "same/half CFL SaveDt overlays are executable requests; only F4 text audits are actual and do not grant qualification",
            "qualification_policy": "QI/QN/QE remain UNKNOWN for every sentinel",
        },
        "source_inputs": source_inputs,
        "quality_error_budget": base.get("quality_error_budget"),
        "savedt_pair_binding": {
            "generic_13": file_record(SAVEDT_BINDING),
            "f4_s1": file_record(F4_SAVEDT_BINDING),
            "f4_row_semantics_v2": file_record(ROW_SEMANTICS),
            "f4_lossless_manifest_v2": file_record(LOSSLESS_MANIFEST),
            "f4_lossless_request_v2": file_record(LOSSLESS_REQUEST),
        },
        "sentinels": sentinels,
        "global_unknowns": [
            "No sentinel receives QI/QN/QE or field-observer scientific credit from this status.",
            "Only F4-S1 has completed same/half SaveDt text audits; other 26 requests are launch-disabled and pending parent scheduling.",
            "F4 half-CFL has 1384 aggregate DtMin clamps and ends 6.0803431169986766e-05 s short of the requested/source endpoint; no per-row clamp locations are inferred.",
            "F4 same-CFL DtAll rows are 10035 while RunPARTs sum Steps and Run.out report 10036; the helper preserves this as a scoped convention, not one-row-per-reported-step proof.",
            "Full-window lossless archive bytes and observer calibration remain UNKNOWN until separate parent-guarded CPU work and consumer calibration.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build()
    if args.output.exists():
        raise FileExistsError(f"refuse to overwrite {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "sentinels": len(result["sentinels"]),
                      "output": str(args.output), "solver_started": False,
                      "hdf5_read": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
