#!/usr/bin/env python3
"""Audit immutable CELL3 T1 evidence and register its bounded adoption scope.

This reads the frozen gate/protocol/score files and native reference artifacts.
It verifies declared hashes, extracts actual full-window HDF5/RunPARTs values for
nominal, true-half-CFL, and output-only references, and emits an additive review.
It never changes any historical artifact and does not make a Q-N or production
claim.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

SCHEMA = "ds02.f3.historical-cell3-t1-adoption-review.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def record_hash(root: Path, rel: str, expected: str | None = None) -> dict[str, Any]:
    path = resolve(root, rel)
    result: dict[str, Any] = {
        "path": str(path),
        "relative_path": rel,
        "exists": path.is_file(),
        "expected_sha256": expected,
    }
    if path.is_file():
        result["bytes"] = path.stat().st_size
        result["actual_sha256"] = sha256(path)
        result["match"] = expected is None or result["actual_sha256"] == expected
    else:
        result["bytes"] = None
        result["actual_sha256"] = None
        result["match"] = False
    return result


def parse_runparts(path: Path) -> dict[str, Any]:
    rows: list[list[str]] = []
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or line.startswith("Part;"):
            continue
        rows.append(next(csv.reader([line], delimiter=";")))
    if not rows:
        raise ValueError(f"no RunPARTs data rows: {path}")
    # Part;TimeStep;Steps;...;DtMin is index 19; NpOutPos/Rho/Mov 16/17/18.
    times = np.asarray([float(row[1]) for row in rows], dtype=float)
    steps = np.asarray([int(row[2].replace(",", "")) for row in rows], dtype=np.int64)
    dts = np.asarray([float(row[19]) for row in rows], dtype=float)
    out_pos = np.asarray([int(row[16].replace(",", "")) for row in rows], dtype=np.int64)
    out_rho = np.asarray([int(row[17].replace(",", "")) for row in rows], dtype=np.int64)
    out_mov = np.asarray([int(row[18].replace(",", "")) for row in rows], dtype=np.int64)
    positive = dts[dts > 0]
    return {
        "rows": len(rows),
        "part_first": int(rows[0][0]),
        "part_last": int(rows[-1][0]),
        "time_start_s": float(times[0]),
        "time_end_s": float(times[-1]),
        "steps_sum": int(steps.sum()),
        "dt_min_s": float(positive.min()) if len(positive) else 0.0,
        "dt_max_s": float(positive.max()) if len(positive) else 0.0,
        "np_out_pos_sum": int(out_pos.sum()),
        "np_out_rho_sum": int(out_rho.sum()),
        "np_out_mov_sum": int(out_mov.sum()),
    }


def h5_header(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h5:
        required = ["density", "mass", "mk", "particle_id", "particle_zone", "position", "pressure", "time", "type", "valid", "velocity"]
        missing = [name for name in required if name not in h5]
        if missing:
            raise ValueError(f"{path} missing HDF5 datasets: {missing}")
        time = np.asarray(h5["time"][:], dtype=np.float64)
        frames = int(time.shape[0])
        particles = int(h5["position"].shape[1])
        return {
            "frames": frames,
            "particles": particles,
            "time_start_s": float(time[0]),
            "time_end_s": float(time[-1]),
            "keys": sorted(h5.keys()),
            "position_shape": list(h5["position"].shape),
            "valid_shape": list(h5["valid"].shape),
            "type_shape": list(h5["type"].shape),
            "attrs": {str(k): (v.decode() if isinstance(v, bytes) else v.item() if isinstance(v, np.generic) else v) for k, v in h5.attrs.items()},
            "finite_time": bool(np.isfinite(time).all()),
            "strict_time": bool(np.all(np.diff(time) > 0)),
        }


def parse_def(path: Path) -> dict[str, float | None]:
    text = path.read_text()
    def find(tag: str) -> float | None:
        if tag == "CFLnumber":
            match = re.search(r'<cflnumber\b[^>]*value="([^"]+)"', text, flags=re.IGNORECASE)
        else:
            match = re.search(rf'<parameter\b[^>]*key="{tag}"[^>]*value="([^"]+)"', text, flags=re.IGNORECASE)
        if not match:
            return None
        value = match.group(1)
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None
    return {"cfl": find("CFLnumber"), "coef_dt_min": find("CoefDtMin"), "time_out": find("TimeOut")}


def parse_control(path: Path) -> np.ndarray:
    rows: list[list[float]] = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append([float(value) for value in line.split(";")])
    array = np.asarray(rows, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 7 or not np.isfinite(array).all():
        raise ValueError(f"invalid control data: {path}")
    return array


def find_evidence(score: Mapping[str, Any], token: str, suffix: str | None = None) -> tuple[str, str]:
    for rel, digest in score["evidence_sha256"].items():
        if token in rel and (suffix is None or rel.endswith(suffix)):
            return rel, digest
    raise KeyError(f"evidence path not found: {token} {suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--revision-gate", type=Path, required=True)
    parser.add_argument("--revision-scores", type=Path, required=True)
    parser.add_argument("--legacy-plan", type=Path, required=True)
    parser.add_argument("--transport-operators", type=Path, required=True)
    parser.add_argument("--transport-config", type=Path, required=True)
    parser.add_argument("--drive", type=Path, required=True)
    parser.add_argument("--solver-lineage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root
    gate = read_json(args.gate)
    protocol = read_json(args.protocol)
    scores = read_json(args.scores)
    revision_gate = read_json(args.revision_gate)
    revision_scores = read_json(args.revision_scores)
    plan = read_json(args.legacy_plan)
    operators = read_json(args.transport_operators)
    transport = read_json(args.transport_config)
    solver_lineage = read_json(args.solver_lineage)

    top_bindings: list[dict[str, Any]] = []
    for path, expected in [
        (args.gate, None),
        (args.protocol, None),
        (args.scores, None),
        (args.revision_gate, None),
        (args.revision_scores, None),
        (args.legacy_plan, None),
        (args.transport_operators, None),
        (args.transport_config, None),
        (args.drive, protocol.get("forcing", {}).get("drive_sha256")),
        (args.solver_lineage, sha256(args.solver_lineage)),
    ]:
        top_bindings.append(record_hash(root, str(path), expected))

    pointer_bindings = []
    for field in ("scoring_evidence_path", "downstream_authorization_path", "downstream_preflight_path"):
        expected_field = field.replace("_path", "_sha256")
        pointer_bindings.append(record_hash(root, gate[field], gate.get(expected_field)))
    primary_evidence = [record_hash(root, rel, digest) for rel, digest in scores["evidence_sha256"].items()]

    # Exact native artifacts used by the temporal and output studies.
    case_tokens = {
        "nominal": "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen",
        "true_half_cfl": "F3_REV075_R075-TIME",
        "output_only": "F3_REV075_R075-OUTPUT",
        "zero_drive": "F3_REV075_R075-ZERO",
    }
    references: dict[str, Any] = {}
    for label, token in case_tokens.items():
        h5_rel, h5_expected = find_evidence(scores, token, ".h5")
        runparts_rel, runparts_expected = find_evidence(scores, token, "RunPARTs.csv")
        runout_rel, runout_expected = find_evidence(scores, token, "Run.out")
        solver_rel, solver_expected = find_evidence(scores, token, "-SOLVER.json")
        prepared_rel, prepared_expected = find_evidence(scores, token, "_PREPARED.json")
        def_rel, def_expected = find_evidence(scores, token, "_Def.xml")
        xml_rel, xml_expected = find_evidence(scores, token, ".xml")
        prepared = read_json(resolve(root, prepared_rel))
        asset_expected = prepared.get("input_assets", {}).get("CaseSloshingAccData.csv", prepared.get("drive_sha256"))
        generated_prefix = resolve(root, prepared.get("generated_prefix", ""))
        control_path = generated_prefix.parent / "CaseSloshingAccData.csv" if generated_prefix.name else generated_prefix / "CaseSloshingAccData.csv"
        control_rel = str(control_path)
        h5_path = resolve(root, h5_rel)
        runparts_path = resolve(root, runparts_rel)
        solver_path = resolve(root, solver_rel)
        solver = read_json(solver_path)
        references[label] = {
            "case_token": token,
            "prepared": record_hash(root, prepared_rel, prepared_expected),
            "h5": record_hash(root, h5_rel, h5_expected),
            "runparts": record_hash(root, runparts_rel, runparts_expected),
            "runout": record_hash(root, runout_rel, runout_expected),
            "solver_receipt": record_hash(root, solver_rel, solver_expected),
            "control": record_hash(root, control_rel, asset_expected),
            "definition": record_hash(root, def_rel, def_expected),
            "generated_xml": record_hash(root, xml_rel, xml_expected),
            "solver_status": {key: solver.get(key) for key in ("status", "returncode", "elapsed_seconds", "timed_out", "interrupted", "attempt_directory")},
            "h5_header": h5_header(h5_path),
            "runparts_values": parse_runparts(runparts_path),
            "def_parameters": parse_def(resolve(root, def_rel)),
            "prepared_recipe": {key: prepared.get(key) for key in ("recipe_id", "solver_mode", "expected_no_penetration", "native_velocity_displacement_correction", "posthoc_particle_projection", "coordinate_frame", "input_repair")},
        }

    nominal_control = parse_control(resolve(root, references["nominal"]["control"]["relative_path"]))
    half_control = parse_control(resolve(root, references["true_half_cfl"]["control"]["relative_path"]))
    output_control = parse_control(resolve(root, references["output_only"]["control"]["relative_path"]))
    control_max_abs = {
        "nominal_vs_true_half_cfl": float(np.max(np.abs(nominal_control - half_control))),
        "nominal_vs_output_only": float(np.max(np.abs(nominal_control - output_control))),
    }
    nominal_steps = references["nominal"]["runparts_values"]["steps_sum"]
    half_steps = references["true_half_cfl"]["runparts_values"]["steps_sum"]
    output_steps = references["output_only"]["runparts_values"]["steps_sum"]
    nominal_dt = references["nominal"]["runparts_values"]["dt_min_s"]
    half_dt = references["true_half_cfl"]["runparts_values"]["dt_min_s"]
    output_dt = references["output_only"]["runparts_values"]["dt_min_s"]

    panels = []
    for panel in scores.get("panels", []):
        panels.append({
            "kind": panel.get("kind"),
            "case_ids": panel.get("case_ids"),
            "time_window_s": panel.get("time_window_s"),
            "target_count": panel.get("target_count"),
            "threshold": panel.get("threshold"),
            "status": panel.get("status"),
            "maxima": panel.get("maxima"),
            "peak_times_s": panel.get("peak_times_s"),
            "grid_step_s": panel.get("grid_step_s"),
        })
    failed_revision_panels = [
        {"index": index + 1, "kind": panel.get("kind"), "case_ids": panel.get("case_ids"), "threshold": panel.get("threshold"), "maxima": panel.get("maxima"), "status": panel.get("status")}
        for index, panel in enumerate(revision_scores.get("panels", [])) if panel.get("status") != "passed"
    ]
    split_counts: dict[str, int] = {}
    for case in plan.get("cases", []):
        split = case.get("legacy_split")
        if split:
            split_counts[split] = split_counts.get(split, 0) + 1

    all_hash_records = top_bindings + pointer_bindings + primary_evidence + [
        references[label][key]
        for label in references
        for key in ("prepared", "h5", "runparts", "runout", "solver_receipt", "control", "definition", "generated_xml")
    ]
    hash_failures = [item for item in all_hash_records if not item.get("match")]
    result = {
        "schema": SCHEMA,
        "status": "completed_pass" if not hash_failures else "completed_hash_mismatch",
        "claim_boundary": {
            "adoption": "historical T1 numerical macro/reference scope only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
            "training": "not_authorized_by_this_review",
            "new_dual_axis_or_baffle_transfer": False,
            "transport_label_qualification": "pending_independent_T2",
            "model_invoked": False,
        },
        "source_binding": {
            "gate": record_hash(root, str(args.gate), sha256(args.gate)),
            "protocol": record_hash(root, str(args.protocol), sha256(args.protocol)),
            "scores": record_hash(root, str(args.scores), sha256(args.scores)),
            "revision_gate": record_hash(root, str(args.revision_gate), sha256(args.revision_gate)),
            "revision_scores": record_hash(root, str(args.revision_scores), sha256(args.revision_scores)),
            "legacy_plan": record_hash(root, str(args.legacy_plan), sha256(args.legacy_plan)),
            "transport_operators": record_hash(root, str(args.transport_operators), sha256(args.transport_operators)),
            "transport_config": record_hash(root, str(args.transport_config), sha256(args.transport_config)),
            "drive": record_hash(root, str(args.drive), protocol.get("forcing", {}).get("drive_sha256")),
            "solver_lineage": record_hash(root, str(args.solver_lineage), sha256(args.solver_lineage)),
        },
        "gate_state": {
            "status": gate.get("status"),
            "full_goal_complete": gate.get("full_goal_complete"),
            "development_launch_allowed_in_old_gate": gate.get("development_launch_allowed"),
            "material_production_allowed_in_old_gate": gate.get("material_production_allowed"),
            "training_launch_allowed_in_old_gate": gate.get("training_launch_allowed"),
            "review_interpretation": "old gate permissions are historical metadata and do not authorize this activity",
        },
        "frozen_recipe": {
            "geometry_m": protocol.get("geometry_m"),
            "water_depth_m": protocol.get("water_depth_m"),
            "target_mass_kg": protocol.get("target_mass_kg"),
            "coordinate_frame": protocol.get("coordinate_frame"),
            "time_window_s": protocol.get("long_window_s"),
            "control_domain": protocol.get("control_amplitudes"),
            "production_dp_m": gate.get("production_resolution_m"),
            "reference_dp_m": gate.get("reference_resolutions_m"),
            "save_interval_s": protocol.get("output_interval_s"),
            "control_interval_s": protocol.get("output_control_interval_s"),
            "cfl_options": protocol.get("cfl"),
            "time_output_error_budget": protocol.get("time_output_error_budget"),
            "reference_error_budget": protocol.get("reference_error_budget"),
            "energy_scale": protocol.get("energy_scale"),
            "forcing": protocol.get("forcing"),
            "formal_release": protocol.get("formal_release"),
        },
        "t1_panel_values": {
            "score_status": scores.get("status"),
            "panel_count": len(panels),
            "all_panels_passed": all(panel.get("status") == "passed" for panel in panels),
            "panels": panels,
        },
        "true_half_cfl_evidence": {
            "baseline_case": case_tokens["nominal"],
            "half_case": case_tokens["true_half_cfl"],
            "control_numeric_max_abs_difference": control_max_abs["nominal_vs_true_half_cfl"],
            "baseline_dt_min_s": nominal_dt,
            "half_dt_min_s": half_dt,
            "dt_ratio_half_over_baseline": half_dt / nominal_dt,
            "baseline_steps_sum": nominal_steps,
            "half_steps_sum": half_steps,
            "steps_ratio_half_over_baseline": half_steps / nominal_steps,
            "baseline_frames": references["nominal"]["h5_header"]["frames"],
            "half_frames": references["true_half_cfl"]["h5_header"]["frames"],
            "baseline_time_end_s": references["nominal"]["h5_header"]["time_end_s"],
            "half_time_end_s": references["true_half_cfl"]["h5_header"]["time_end_s"],
            "baseline_def_parameters": references["nominal"]["def_parameters"],
            "half_def_parameters": references["true_half_cfl"]["def_parameters"],
            "interpretation": "actual internal CFL/CoefDtMin reduction with RunPARTs dt and step-count evidence; not a save-frame claim",
        },
        "output_only_evidence": {
            "baseline_case": case_tokens["nominal"],
            "output_case": case_tokens["output_only"],
            "control_numeric_max_abs_difference": control_max_abs["nominal_vs_output_only"],
            "baseline_dt_min_s": nominal_dt,
            "output_dt_min_s": output_dt,
            "dt_ratio_output_over_baseline": output_dt / nominal_dt,
            "baseline_steps_sum": nominal_steps,
            "output_steps_sum": output_steps,
            "steps_ratio_output_over_baseline": output_steps / nominal_steps,
            "baseline_frames": references["nominal"]["h5_header"]["frames"],
            "output_frames": references["output_only"]["h5_header"]["frames"],
            "baseline_time_end_s": references["nominal"]["h5_header"]["time_end_s"],
            "output_time_end_s": references["output_only"]["h5_header"]["time_end_s"],
            "baseline_def_parameters": references["nominal"]["def_parameters"],
            "output_def_parameters": references["output_only"]["def_parameters"],
            "interpretation": "save cadence comparison only; it cannot establish internal time-step refinement",
        },
        "native_full_window_references": references,
        "solver_lineage": solver_lineage,
        "legacy_split_counts_in_reuse_plan": split_counts,
        "transport_t2_preregistration": {
            "required_fields": operators.get("required_label_fields"),
            "events": operators.get("finite_surfaces"),
            "source_assignment": transport.get("source_assignment"),
            "source_regions": transport.get("source_regions"),
            "destination_regions": transport.get("destination_regions"),
            "event_time_semantics": transport.get("semantics", {}).get("event_time"),
            "residence_semantics": transport.get("semantics", {}).get("residence"),
            "mass_policy": operators.get("mass_policy"),
            "normalization": "native per-typed-identity mass in kg; report raw kg and separately normalized by frozen initial fluid mass 14.58 kg only for dimensionless comparisons",
            "first_passage": "compare observed saved-frame bracket/chord times per event and censor flag; no T1 boolean substitutes",
            "residence": "compare per-identity residence_time_s and destination-time-series integrals over identical [0,8.35] window/save cadence",
            "spatial": "compare finite x=0 exchange and top z=0.51 legal-exit labels with identical tank-frame aperture; unknown remains unknown",
            "qualification_gate": "independent T2 macro/path reference and save/time/spatial comparison required",
        },
        "hash_closure": {
            "records_checked": len(all_hash_records),
            "matches": len(all_hash_records) - len(hash_failures),
            "failures": hash_failures,
            "primary_score_evidence_records": len(primary_evidence),
            "pointer_records": pointer_bindings,
        },
        "references": references,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "records_checked": len(all_hash_records), "hash_failures": len(hash_failures), "panel_count": len(panels), "failed_revision_panels": len(failed_revision_panels)}, indent=2))
    return 0 if not hash_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
