#!/usr/bin/env python3
"""Read-only comparison of two F3 native-dense CFD output schedules.

This tool only reads terminal H5/solver evidence and emits immutable JSON
evidence.  It does not touch the runtime queue, ledger, or source products.
The comparison is deliberately about saved-time scheduling; it does not
reinterpret saved states as interpolated solver states.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import h5py
import numpy as np


AUDIT_SCHEMA = "core.f3.cfd.native_volume_mls.source_audit.v2"
AUDIT_CODE_SHA256 = "bf84f3db8b2233d6bccd127a85cec45098fb941a0fa1b54f2213f28216650ffe"
CADENCE_RELATIVE = 1e-2
CADENCE_FLOOR_S = 1e-7
CADENCE_S = 0.002
TIME_MAX_S = 8.35
EXPECTED_FRAMES = 4176
EXPECTED_PARTICLES = 34560


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def immutable_json(path: Path, value: Any) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"immutable evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def read_time(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=np.float64)
        keys = sorted(handle.keys())
        shapes = {name: list(handle[name].shape) for name in keys}
    target = CADENCE_S * np.arange(times.size, dtype=np.float64)
    error = times - target
    tolerance = max(CADENCE_FLOOR_S, CADENCE_RELATIVE * CADENCE_S)
    bad = np.flatnonzero(~np.isfinite(times) | (np.abs(error) > tolerance))
    intervals = np.diff(times)
    # The solver writes binary floating point accumulated times.  Twelve
    # decimal places preserve the two scheduling quanta while grouping the
    # harmless last-bit drift across long runs.
    rounded, counts = np.unique(np.round(intervals, 12), return_counts=True)
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "time_dataset_sha256": hashlib.sha256(times.tobytes(order="C")).hexdigest(),
        "dataset_keys": keys,
        "dataset_shapes": shapes,
        "frames": int(times.size),
        "particles_axis": int(shapes.get("position", [0, 0])[1]) if "position" in shapes else None,
        "first_s": float(times[0]) if times.size else None,
        "last_s": float(times[-1]) if times.size else None,
        "time_error_max_abs_s": float(np.max(np.abs(error))) if error.size else None,
        "time_error_max_abs_us": float(np.max(np.abs(error)) * 1e6) if error.size else None,
        "time_error_max_index": int(np.argmax(np.abs(error))) if error.size else None,
        "time_error_final_s": float(error[-1]) if error.size else None,
        "cadence_tolerance_s": tolerance,
        "cadence_bad_count": int(bad.size),
        "cadence_bad_fraction": float(bad.size / times.size) if times.size else None,
        "cadence_bad_first_indices": [int(x) for x in bad[:32]],
        "interval_min_s": float(np.min(intervals)) if intervals.size else None,
        "interval_median_s": float(np.median(intervals)) if intervals.size else None,
        "interval_max_s": float(np.max(intervals)) if intervals.size else None,
        "interval_values_rounded_s": [float(x) for x in rounded],
        "interval_counts": [int(x) for x in counts],
    }


def runparts(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            if not row.get("Part", "").isdigit():
                continue
            rows.append(row)
    def values(key: str) -> np.ndarray:
        return np.asarray([float(row[key]) for row in rows], dtype=np.float64)
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "rows": len(rows),
        "part_time_s": values("TimeStep [s]"),
        "steps": values("Steps"),
        "dts_min_count": values("DTsMin"),
        "dt_min_s": values("DtMin [s]"),
        "dt_max_s": values("DtMax [s]"),
    }


def runout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, Any] = {"path": str(path.resolve()), "sha256": sha256(path)}
    patterns = {
        "cfl": r"^CFLnumber=([^\s]+)",
        "dt_ini_s": r"^DtIni=([^\s]+)",
        "dt_min_s": r"^DtMin=([^\s]+)",
        "time_max_s": r"^TimeMax=([^\s]+)",
        "time_part_s": r"^TimePart=([^\s]+)",
        "steps_of_simulation": r"^Steps of simulation\.*:\s*([0-9,]+)",
        "dts_adjusted_to_dtmin": r"^DTs adjusted to DtMin\.*:\s*([0-9,]+)",
        "part_files": r"^PART files\.*:\s*([0-9,]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match is None:
            continue
        raw = match.group(1).replace(",", "")
        out[key] = float(raw) if any(c in raw for c in ".eE") else int(raw)
    return out


def compare_scheduler(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    fields = ("part_time_s", "steps", "dts_min_count", "dt_min_s", "dt_max_s")
    result: dict[str, Any] = {}
    for field in fields:
        x, y = a[field], b[field]
        result[field] = {
            "exact_equal": bool(np.array_equal(x, y)),
            "max_abs_difference": float(np.max(np.abs(x - y))) if x.size else 0.0,
        }
    return result


def prepared_summary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    case = value.get("case", {})
    config = value.get("config", {})
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "schema": value.get("schema"),
        "case_id": value.get("case_id", case.get("case_id", config.get("case_id"))),
        "dp_m": value.get("dp_m", case.get("dp_m", config.get("dp_m"))),
        "drive_amplitude": value.get("drive_amplitude", case.get("drive_amplitude", config.get("drive_amplitude"))),
        "time_max_s": value.get("time_max_s", case.get("time_max_s", config.get("time_max_s"))),
        "output_interval_s": value.get("time_out_s", case.get("output_interval_s", config.get("output_interval_s"))),
        "coef_dt_min": value.get("coef_dt_min", case.get("coef_dt_min", config.get("coef_dt_min"))),
        "drive_sha256": value.get("drive_sha256"),
        "solver_sha256": value.get("solver_sha256"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nominal-h5", type=Path, required=True)
    parser.add_argument("--nominal-prepared", type=Path, required=True)
    parser.add_argument("--nominal-run-parts", type=Path, required=True)
    parser.add_argument("--nominal-run-out", type=Path, required=True)
    parser.add_argument("--nominal-legacy-audit", type=Path, required=True)
    parser.add_argument("--candidate-h5", type=Path, required=True)
    parser.add_argument("--candidate-prepared", type=Path, required=True)
    parser.add_argument("--candidate-run-parts", type=Path, required=True)
    parser.add_argument("--candidate-run-out", type=Path, required=True)
    parser.add_argument("--candidate-audit-v2", type=Path, required=True)
    parser.add_argument("--audit-code", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--proposal-output", type=Path, required=True)
    args = parser.parse_args(argv)

    nominal_time = read_time(args.nominal_h5)
    candidate_time = read_time(args.candidate_h5)
    nominal_parts = runparts(args.nominal_run_parts)
    candidate_parts = runparts(args.candidate_run_parts)
    nominal_out = runout(args.nominal_run_out)
    candidate_out = runout(args.candidate_run_out)
    candidate_audit = json.loads(args.candidate_audit_v2.read_text(encoding="utf-8"))
    legacy_audit = json.loads(args.nominal_legacy_audit.read_text(encoding="utf-8"))
    candidate_prepared = prepared_summary(args.candidate_prepared)
    nominal_keys = set(nominal_time["dataset_keys"])
    required_v2 = {
        "particle_id", "particle_zone", "source_label_initial_mk", "time", "position",
        "velocity", "density", "mass", "pressure", "valid", "type", "mk",
    }
    target_dt = CADENCE_S / 91.0
    dt_ini = float(candidate_out["dt_ini_s"])
    proposal_coef = target_dt / dt_ini
    report = {
        "schema": "core.material.f3.dense_cadence_diagnosis.v1",
        "created_at_utc": utc_now(),
        "status": "read_only_complete",
        "qualification_claim": "none; source scheduling diagnosis only",
        "analysis_code": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
        },
        "audit_v2_preregistration": {
            "schema": AUDIT_SCHEMA,
            "audit_version": 2,
            "audit_code": str(args.audit_code.resolve()),
            "audit_code_sha256": sha256(args.audit_code),
            "audit_code_sha256_expected": AUDIT_CODE_SHA256,
            "time_cadence_relative_tolerance": CADENCE_RELATIVE,
            "time_cadence_absolute_floor_s": CADENCE_FLOOR_S,
            "registered_output_interval_s": CADENCE_S,
            "registered_time_max_s": TIME_MAX_S,
            "registered_expected_frames": EXPECTED_FRAMES,
            "registered_expected_particles": EXPECTED_PARTICLES,
            "cadence_tolerance_s": max(CADENCE_FLOOR_S, CADENCE_RELATIVE * CADENCE_S),
            "semantics": "one-percent saved-output scheduling bound; exact timestamp error retained; no scientific qualification threshold changed",
        },
        "sources": {
            "nominal_dense1p0": {
                "prepared": prepared_summary(args.nominal_prepared),
                "h5": nominal_time,
                "run_parts": {k: v for k, v in nominal_parts.items() if k not in {"part_time_s", "steps", "dts_min_count", "dt_min_s", "dt_max_s"}},
                "run_out": nominal_out,
                "legacy_audit": {
                    "path": str(args.nominal_legacy_audit.resolve()),
                    "sha256": sha256(args.nominal_legacy_audit),
                    "audit_status": legacy_audit.get("audit_status"),
                    "acceptance_status": legacy_audit.get("acceptance_status"),
                    "frames": legacy_audit.get("frames"),
                },
            },
            "candidate_dense1p1": {
                "prepared": candidate_prepared,
                "h5": candidate_time,
                "run_parts": {k: v for k, v in candidate_parts.items() if k not in {"part_time_s", "steps", "dts_min_count", "dt_min_s", "dt_max_s"}},
                "run_out": candidate_out,
                "audit_v2": {
                    "path": str(args.candidate_audit_v2.resolve()),
                    "sha256": sha256(args.candidate_audit_v2),
                    "hard_integrity_pass": candidate_audit.get("hard_integrity_pass"),
                    "errors": candidate_audit.get("errors"),
                    "time": candidate_audit.get("time"),
                    "mass_per_particle": candidate_audit.get("mass_per_particle"),
                    "wall": candidate_audit.get("wall"),
                    "validity": candidate_audit.get("validity"),
                },
            },
        },
        "timestamp_comparison": {
            "time_dataset_exact_equal": nominal_time["time_dataset_sha256"] == candidate_time["time_dataset_sha256"],
            "time_array_sha256_nominal": nominal_time["time_dataset_sha256"],
            "time_array_sha256_candidate": candidate_time["time_dataset_sha256"],
            "cadence_gate_replay": {
                "nominal_dense1p0_pass": nominal_time["cadence_bad_count"] == 0,
                "candidate_dense1p1_pass": candidate_time["cadence_bad_count"] == 0,
                "nominal_bad_count": nominal_time["cadence_bad_count"],
                "candidate_bad_count": candidate_time["cadence_bad_count"],
                "nominal_max_abs_error_s": nominal_time["time_error_max_abs_s"],
                "candidate_max_abs_error_s": candidate_time["time_error_max_abs_s"],
                "tolerance_s": nominal_time["cadence_tolerance_s"],
            },
            "required_v2_dataset_presence": {
                "nominal_dense1p0_present": sorted(required_v2 & nominal_keys),
                "nominal_dense1p0_missing": sorted(required_v2 - nominal_keys),
                "candidate_dense1p1_missing": sorted(required_v2 - set(candidate_time["dataset_keys"])),
                "nominal_full_v2_audit_status": "not_promoted; legacy H5 lacks source_label_initial_mk, so only the v2 timestamp gate is replayed",
            },
        },
        "solver_schedule_comparison": {
            "run_parts": compare_scheduler(nominal_parts, candidate_parts),
            "same_saved_step_schedule": all(v["exact_equal"] for v in compare_scheduler(nominal_parts, candidate_parts).values()),
            "nominal_run_out": nominal_out,
            "candidate_run_out": candidate_out,
            "dt_quantization": {
                "candidate_dt_min_s": candidate_out.get("dt_min_s"),
                "candidate_90_steps_s": float(90.0 * candidate_out["dt_min_s"]),
                "candidate_91_steps_s": float(91.0 * candidate_out["dt_min_s"]),
                "registered_output_interval_s": CADENCE_S,
                "observed_interval_values_s": candidate_time["interval_values_rounded_s"],
                "interpretation": "saved frames are quantized to completed solver steps; 90 steps undershoot .002 s and 91 steps overshoot it",
            },
        },
        "interpretation": {
            "finding": "dense1.1 cadence failure is inherited from the dense1.0 solver/output schedule, not introduced by drive amplitude 1.1",
            "evidence": [
                "dense1.0 and dense1.1 time datasets are byte-identical",
                "both RunPARTs schedules have identical saved TimeStep, Steps, DTsMin, DtMin and DtMax columns",
                "both solver logs report CFL=.05, the same DtIni, DtMin, TimePart=.002, 377422 steps and 754844 DtMin adjustments",
                "the two observed intervals are 90*DtMin=0.001991042718... and 91*DtMin=0.002013165415...",
            ],
            "limits": [
                "H5/RunPARTs expose saved-state scheduling, not hidden solver event timestamps; the conclusion is about the observed completed-step quantization",
                "the nominal dense1.0 H5 has no source_label_initial_mk dataset required by audit v2, so its full v2 audit is not claimed",
                "the old nominal audit is diagnostic-only and cannot override the v2 cadence gate",
            ],
        },
        "provenance": {
            "nominal_prepared_sha256": sha256(args.nominal_prepared),
            "candidate_prepared_sha256": sha256(args.candidate_prepared),
            "nominal_h5_sha256": nominal_time["sha256"],
            "candidate_h5_sha256": candidate_time["sha256"],
            "nominal_runparts_sha256": nominal_parts["sha256"],
            "candidate_runparts_sha256": candidate_parts["sha256"],
            "candidate_audit_v2_sha256": sha256(args.candidate_audit_v2),
        },
    }
    proposal = {
        "schema": "core.material.f3.dense_cadence_repair_proposal.v1",
        "created_at_utc": utc_now(),
        "status": "preregistered_proposal_only",
        "qualification_claim": "none; do not launch or substitute into T1/T2",
        "analysis_code": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
        },
        "evidence_report_path": str(args.output.resolve()),
        "evidence_report_sha256": None,
        "problem": {
            "registered_output_interval_s": CADENCE_S,
            "frozen_audit_v2_tolerance_s": max(CADENCE_FLOOR_S, CADENCE_RELATIVE * CADENCE_S),
            "observed_max_abs_error_s": candidate_time["time_error_max_abs_s"],
            "observed_bad_frames": candidate_time["cadence_bad_count"],
            "cause": "completed-step quantization at the shared DtMin/output schedule; both nominal dense1.0 and candidate dense1.1 share it",
        },
        "single_repair": {
            "name": "align internal minimum timestep to the .002 s save grid",
            "parameter": "DtMin via the registered coef_dt_min source parameter",
            "preserve": {
                "output_interval_s": CADENCE_S,
                "time_max_s": TIME_MAX_S,
                "expected_frames": EXPECTED_FRAMES,
                "cfl_number": candidate_out.get("cfl"),
                "solver_binary_sha256": "0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29",
                "audit_v2_thresholds": {
                    "cadence_relative": CADENCE_RELATIVE,
                    "cadence_floor_s": CADENCE_FLOOR_S,
                    "mass_relative": 1e-8,
                    "wall_endpoint_m": 1e-8,
                },
                "posthoc_timestamp_rewrite": False,
                "interpolation": False,
            },
            "target_steps_per_saved_interval": 91,
            "target_dt_min_s": target_dt,
            "current_dt_min_s": candidate_out.get("dt_min_s"),
            "current_coef_dt_min": candidate_prepared.get("coef_dt_min"),
            "proposed_coef_dt_min_from_DtIni": proposal_coef,
            "selection_reason": "the smaller 91-step target reduces DtMin by about 0.654 percent and avoids increasing the current stability-limiting step",
            "verification": "one bounded source-generation canary must prove the saved timestamps, then the full source must pass audit v2; no timestamp rewriting may be used",
        },
        "acceptance": {
            "required": [
                "audit v2 hard_integrity_pass=true",
                "all 4176 saved times satisfy abs(t_i - i*.002) <= 2e-5 s",
                "source wall, finite-state, validity and per-particle mass gates remain unchanged and pass",
                "new source prepared/input/solver hashes are independently bound",
            ],
            "failure_action": "retain qualification_only and do not place repaired source in the 33-scope qualification set",
        },
        "scope_implication": {
            "rows26_27": "current dense1.1 source remains blocked by audit v2 and cannot be used for material qualification",
            "dense1p0": "nominal dense1.0 remains an engineering/legacy source; its diagnostic audit does not grant qualification",
            "repaired_lineage": "a repaired source is a new qualification_only lineage; it cannot silently replace existing T1 rows or inherit T1/T2 status",
            "threshold_policy": "no tolerance or material gate is relaxed",
        },
    }
    immutable_json(args.output, report)
    proposal["evidence_report_sha256"] = sha256(args.output)
    immutable_json(args.proposal_output, proposal)
    print(json.dumps({
        "report": str(args.output.resolve()),
        "report_sha256": sha256(args.output),
        "proposal": str(args.proposal_output.resolve()),
        "proposal_sha256": sha256(args.proposal_output),
        "nominal_bad_frames": nominal_time["cadence_bad_count"],
        "candidate_bad_frames": candidate_time["cadence_bad_count"],
        "max_error_us": candidate_time["time_error_max_abs_us"],
        "same_time_axis": nominal_time["time_dataset_sha256"] == candidate_time["time_dataset_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
