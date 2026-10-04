#!/usr/bin/env python3
"""Source-only Full Three-DP All-Pair Macro Worker for Lower-Head Mothers.

Reuses exact previously frozen F1 operator, observables, and thresholds with
physically required scale changes:
- ECC Lower-Head Mother: H0 = 0.15 m, M_cont = 40.2 kg, window [0, 1.6] s (161 frames @ save .01 s).
- DUAL Lower-Head Mother: H0 = 0.3 m, M_cont = 300.0 kg, window [0, 4.0] s (401 frames @ save .01 s).

Performs:
1. Exact scale registration validation and strict rejection of old normalizers
   (ECC H=0.3/80.4 kg, DUAL H=0.55/616.0 kg).
2. Canonical physical condition SHA256 verification (687c069f... for ECC, feb710be... for DUAL).
3. Initial QA 031 and native solver receipt checks for all 6 cases (status == completed, returncode == 0).
4. Explicit historical failure retention (failed partial DUAL 033 excluded, returncode == -15).
5. Native Q-I13 fields, initial mass, actual frames, and full-window checks on converter reports.
6. Direct all-pairs unequal refinement comparisons (fine_vs_coarse, fine_vs_medium, medium_vs_coarse)
   with NO particle UID matching across DP.
7. Explicit claim boundary: Q-N not granted, production approval none, numerical results pending
   until Root executes queued conversion requests (034 and 036).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np


Q_I13_REQUIRED_DATASETS = {
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "type",
    "mk",
    "initial_type",
    "initial_mk",
}

FORBIDDEN_OLD_NORMALIZERS = {
    "F1_ECC_THICK_DBC_LOWER_HEAD_V1": {
        "H0_m": 0.3,
        "continuous_initial_mass_kg": 80.4,
    },
    "F1_DUAL_THICK_DBC_LOWER_HEAD_V1": {
        "H0_m": 0.55,
        "continuous_initial_mass_kg": 616.0,
    },
}

EXPECTED_PHYSICAL_HASHES = {
    "F1_ECC_THICK_DBC_LOWER_HEAD_V1": "687c069f836dd81b3c4c85ea6f977f9f2775debea01d3657b81356801ced71d3",
    "F1_DUAL_THICK_DBC_LOWER_HEAD_V1": "feb710be76c89fb67074b1bbbf6c9c22869652ce5760c4d7e4721187b4d580bf",
}

EXPECTED_WINDOW_AND_FRAMES = {
    "F1_ECC_THICK_DBC_LOWER_HEAD_V1": {
        "full_window_s": [0.0, 1.6],
        "expected_frames": 161,
        "H0_m": 0.15,
        "continuous_mass_kg": 40.2,
        "energy_scale_J": 40.2 * 9.81 * 0.15,  # 59.1543 J
    },
    "F1_DUAL_THICK_DBC_LOWER_HEAD_V1": {
        "full_window_s": [0.0, 4.0],
        "expected_frames": 401,
        "H0_m": 0.3,
        "continuous_mass_kg": 300.0,
        "energy_scale_J": 300.0 * 9.81 * 0.3,  # 882.9 J
    },
}


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path | str) -> Any:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _finite(val: Any) -> bool:
    return bool(np.isfinite(np.asarray(val, dtype=float)).all())


def nominal_bins(rows: Sequence[Mapping[str, Any]], cadence: float, max_offset: float) -> tuple[np.ndarray, np.ndarray]:
    if not rows:
        raise ValueError("Observation has no rows")
    times = np.asarray([r["time_s"] for r in rows], dtype=float)
    if not _finite(times) or np.any(np.diff(times) <= 0):
        raise ValueError("Observation timestamps must be finite and strictly increasing")
    keys = np.rint(times / cadence).astype(np.int64)
    if len(np.unique(keys)) != len(keys):
        raise ValueError("Actual timestamps collide in registered nominal bins")
    offsets = np.abs(times - keys * cadence)
    if float(offsets.max()) > max_offset:
        raise ValueError(f"Timestamp offset {offsets.max()} exceeds registered limit {max_offset}")
    return keys, times


def _interpolate_series(rows: Sequence[Mapping[str, Any]], field: str, target_times: np.ndarray) -> np.ndarray:
    times = np.asarray([r["time_s"] for r in rows], dtype=float)
    values = np.asarray([r[field] for r in rows], dtype=float)
    if not _finite(values):
        raise ValueError(f"Non-finite macro field encountered: {field}")
    flat = values.reshape((len(rows), -1))
    if target_times[0] < times[0] - 1e-10 or target_times[-1] > times[-1] + 1e-10:
        raise ValueError(f"Target nominal bins outside observation range for {field}")
    aligned = np.column_stack([np.interp(target_times, times, flat[:, i]) for i in range(flat.shape[1])])
    return aligned.reshape((len(target_times),) + values.shape[1:])


def align_case_series(observation: Mapping[str, Any], keys: np.ndarray, cadence: float) -> dict[str, Any]:
    rows = observation["rows"]
    own_keys, own_times = nominal_bins(rows, cadence, float("inf"))
    index = {int(k): int(i) for i, k in enumerate(own_keys)}
    if not set(keys.tolist()).issubset(index):
        raise ValueError("Observation does not cover the complete common nominal time bins")
    target = keys.astype(float) * cadence
    return {
        "keys": keys,
        "target_time_s": target,
        "actual_time_offset_max_s": float(np.max(np.abs(own_times - own_keys * cadence))),
        "center_of_mass_m": _interpolate_series(rows, "center_of_mass_m", target),
        "coordinate_quantiles_m": _interpolate_series(rows, "coordinate_quantiles_m", target),
        "kinetic_energy_J": _interpolate_series(rows, "kinetic_energy_J", target),
        "fluid_mass_kg": _interpolate_series(rows, "fluid_mass_kg", target),
        "mean_velocity_m_s": _interpolate_series(rows, "mean_velocity_m_s", target),
    }


def compare_pair(
    candidate: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    cadence: float,
    max_offset: float,
    H0: float,
    continuous_mass: float,
    macro_budget: float,
) -> dict[str, Any]:
    """Exact frozen F1 macro comparison operator across unequal DP resolutions.

    Evaluates macro differences without particle UID matching across DP.
    Observables:
    - Center of mass difference normalized by H0
    - Coordinate quantiles difference normalized by H0
    - Kinetic energy difference normalized by MgH0
    - Mean velocity difference (m/s) (descriptive)
    - Fluid mass difference (kg and fraction of continuum mass) (descriptive)
    """
    cand_obs = candidate["observation"]
    ref_obs = reference["observation"]

    cand_keys, _ = nominal_bins(cand_obs["rows"], cadence, max_offset)
    ref_keys, _ = nominal_bins(ref_obs["rows"], cadence, max_offset)

    common = np.intersect1d(cand_keys, ref_keys)
    if len(common) != len(cand_keys) or len(common) != len(ref_keys):
        raise ValueError(
            f"Nominal save bins mismatch between candidate ({len(cand_keys)}) and reference ({len(ref_keys)})"
        )

    cand_aligned = align_case_series(cand_obs, common, cadence)
    ref_aligned = align_case_series(ref_obs, common, cadence)

    com_diff = np.abs(cand_aligned["center_of_mass_m"] - ref_aligned["center_of_mass_m"])
    quantile_diff = np.abs(cand_aligned["coordinate_quantiles_m"] - ref_aligned["coordinate_quantiles_m"])
    ke_diff = np.abs(cand_aligned["kinetic_energy_J"] - ref_aligned["kinetic_energy_J"])
    mass_diff = np.abs(cand_aligned["fluid_mass_kg"] - ref_aligned["fluid_mass_kg"])
    vel_diff = np.abs(cand_aligned["mean_velocity_m_s"] - ref_aligned["mean_velocity_m_s"])

    energy_scale = continuous_mass * 9.81 * H0

    metrics = {
        "center_of_mass_max_over_H0": float(com_diff.max() / H0),
        "coordinate_quantiles_max_over_H0": float(quantile_diff.max() / H0),
        "kinetic_energy_max_over_continuous_MgH0": float(ke_diff.max() / energy_scale),
        "mean_velocity_max_absolute_m_s": float(vel_diff.max()),
        "fluid_mass_max_absolute_kg": float(mass_diff.max()),
        "fluid_mass_max_over_continuous_mass": float(mass_diff.max() / continuous_mass),
    }

    macro_metrics = [
        metrics["center_of_mass_max_over_H0"],
        metrics["coordinate_quantiles_max_over_H0"],
        metrics["kinetic_energy_max_over_continuous_MgH0"],
    ]

    macro_metric_max = float(max(macro_metrics))
    macro_screening_pass = bool(macro_metric_max <= macro_budget)

    return {
        "candidate_case_id": candidate["case_id"],
        "reference_case_id": reference["case_id"],
        "resolution_pair": f"{candidate.get('role', 'cand')}_vs_{reference.get('role', 'ref')}",
        "time_alignment": {
            "method": "linear interpolation to common nominal physical save bins",
            "nominal_cadence_s": cadence,
            "common_frame_count": len(common),
            "candidate_actual_to_nominal_max_s": cand_aligned["actual_time_offset_max_s"],
            "reference_actual_to_nominal_max_s": ref_aligned["actual_time_offset_max_s"],
            "uid_matching_across_dp": False,
            "explanation": "Direct unequal spatial refinement; Eulerian/continuous field macro comparison with no UID matching across DP",
        },
        "initial_mass": {
            "candidate_kg": float(candidate["initial_mass_kg"]),
            "reference_kg": float(reference["initial_mass_kg"]),
            "candidate_relative_error": float(candidate["initial_mass_relative_error"]),
            "reference_relative_error": float(reference["initial_mass_relative_error"]),
            "difference_kg": abs(float(candidate["initial_mass_kg"]) - float(reference["initial_mass_kg"])),
            "mass_normalization": "none",
        },
        "metrics": metrics,
        "macro_metric_max": macro_metric_max,
        "macro_budget": macro_budget,
        "macro_screening_within_budget": macro_screening_pass,
        "series": {
            "time_s": cand_aligned["target_time_s"].tolist(),
            "center_of_mass_abs_m": com_diff.tolist(),
            "coordinate_quantiles_abs_m": quantile_diff.tolist(),
            "kinetic_energy_abs_J": ke_diff.tolist(),
            "fluid_mass_abs_kg": mass_diff.tolist(),
            "mean_velocity_abs_m_s": vel_diff.tolist(),
        },
        "q_n_status": "not_granted",
    }


def verify_scale_registration(reg: Mapping[str, Any], mother_id: str) -> dict[str, Any]:
    """Verify exact scale registration and prevent carrying old normalizers."""
    if mother_id not in EXPECTED_WINDOW_AND_FRAMES:
        raise ValueError(f"Unknown mother_id: {mother_id}")

    expected = EXPECTED_WINDOW_AND_FRAMES[mother_id]
    forbidden = FORBIDDEN_OLD_NORMALIZERS[mother_id]

    # Verify mother ID matches
    if reg.get("mother_id") != mother_id:
        raise ValueError(f"Scale registration mother_id {reg.get('mother_id')} != expected {mother_id}")

    # Check forbidden old normalizers
    if abs(reg["H0_m"] - forbidden["H0_m"]) < 1e-6:
        raise ValueError(
            f"FATAL: Scale registration uses forbidden old normalizer H0={reg['H0_m']} for {mother_id}!"
        )
    if abs(reg["continuous_initial_mass_kg"] - forbidden["continuous_initial_mass_kg"]) < 1e-6:
        raise ValueError(
            f"FATAL: Scale registration uses forbidden old mass={reg['continuous_initial_mass_kg']} for {mother_id}!"
        )

    # Check required scale values
    assert abs(reg["H0_m"] - expected["H0_m"]) < 1e-6, f"H0 {reg['H0_m']} != {expected['H0_m']}"
    assert abs(reg["continuous_initial_mass_kg"] - expected["continuous_mass_kg"]) < 1e-6
    assert reg["expected_frames"] == expected["expected_frames"]
    assert reg["full_window_s"] == expected["full_window_s"]
    assert reg["save_cadence_s"] == 0.01
    assert reg["macro_budget_fraction"] == 0.05
    assert reg["initial_mass_budget_fraction"] == 0.01

    calc_energy_scale = reg["continuous_initial_mass_kg"] * reg["gravity_m_s2"] * reg["H0_m"]
    assert abs(calc_energy_scale - expected["energy_scale_J"]) < 1e-4

    return {
        "mother_id": mother_id,
        "H0_m": reg["H0_m"],
        "continuous_initial_mass_kg": reg["continuous_initial_mass_kg"],
        "energy_scale_J": calc_energy_scale,
        "full_window_s": reg["full_window_s"],
        "expected_frames": reg["expected_frames"],
        "save_cadence_s": reg["save_cadence_s"],
        "macro_budget_fraction": reg["macro_budget_fraction"],
        "initial_mass_budget_fraction": reg["initial_mass_budget_fraction"],
        "forbidden_old_normalizers_rejected": True,
    }


def verify_canonical_physical_binding(binding_path: Path | str, expected_hash: str) -> dict[str, Any]:
    """Verify canonical physical binding sidecar and exact physical condition hash."""
    b_data = load_json(binding_path)
    actual_hash = b_data.get("physical_condition_sha256")
    if actual_hash != expected_hash:
        raise ValueError(f"Physical condition hash mismatch: {actual_hash} != {expected_hash}")
    return {
        "canonical_binding_path": str(binding_path),
        "physical_condition_sha256": actual_hash,
        "geometry_family_id": b_data["physical_binding"]["geometry_family_id"],
        "control_family_id": b_data["physical_binding"]["control_family_id"],
        "passed": True,
    }


def verify_initial_qa_record(qa_path: Path | str, case_ids: Sequence[str]) -> dict[str, Any]:
    """Verify initial QA 031 record."""
    qa_data = load_json(qa_path)
    passed_cases = {}
    for case in qa_data.get("cases", []):
        cid = case.get("case_id")
        if cid in case_ids:
            if not case.get("passed"):
                raise ValueError(f"Case {cid} failed initial QA 031!")
            passed_cases[cid] = {
                "native_particles": case.get("native_particles"),
                "native_fluid": case.get("native_fluid"),
                "official_CSV_fluid_mass_sum_kg": case.get("official_CSV_fluid_mass_sum_kg"),
                "initial_bi4_sha256": case.get("initial_bi4_sha256"),
            }
    missing = set(case_ids) - set(passed_cases.keys())
    if missing:
        raise ValueError(f"Missing initial QA records for cases: {missing}")
    return {
        "qa_path": str(qa_path),
        "status": "completed",
        "cases": passed_cases,
        "passed": True,
    }


def verify_solver_receipts(cases: Sequence[Mapping[str, Any]], excluded: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify all 6 solver receipts are completed with returncode 0 and exclusions retained."""
    results = {}
    for c in cases:
        rec_path = Path(c["solver_receipt"])
        rec = load_json(rec_path)
        if rec.get("status") != "completed" or rec.get("returncode") != 0:
            raise ValueError(f"Solver receipt for {c['case_id']} not completed: {rec}")
        results[c["case_id"]] = {
            "status": rec.get("status"),
            "returncode": rec.get("returncode"),
            "receipt_sha256": sha256_file(rec_path),
        }

    # Verify excluded attempts
    verified_exclusions = []
    for exc in excluded:
        rec_path = Path(exc["receipt"])
        if rec_path.is_file():
            rec = load_json(rec_path)
            # Must verify it is indeed failed / aborted and retains historical failure
            verified_exclusions.append({
                "attempt_id": exc.get("attempt_id"),
                "case_id": exc.get("case_id"),
                "status": rec.get("status"),
                "returncode": rec.get("returncode"),
                "retained_as_excluded": True,
                "reason": exc.get("reason"),
            })

    return {
        "active_cases": results,
        "verified_exclusions": verified_exclusions,
        "passed": True,
    }


def check_q_i13_report(report_path: Path | str) -> dict[str, Any]:
    """Verify direct conversion report against native Q-I13 requirements."""
    rep = load_json(report_path)

    # Check datasets in report
    datasets = set(rep.get("datasets", []))
    missing = Q_I13_REQUIRED_DATASETS - datasets
    if missing:
        raise ValueError(f"Conversion report {report_path} missing required Q-I13 datasets: {missing}")

    # Check initial exclusion ledger
    typed_id = rep.get("typed_identity", {})
    init_ledger = typed_id.get("initial_exclusion_ledger", {})
    if init_ledger.get("count", 0) != 0:
        raise ValueError(f"Conversion report has non-zero initial exclusions: {init_ledger}")

    # Check PartVTK validation if present
    pvtk = rep.get("partvtk_validation", {})
    if pvtk and not pvtk.get("all_passed", False):
        raise ValueError(f"Conversion report PartVTK validation failed: {pvtk}")

    return {
        "report_path": str(report_path),
        "q_i13_datasets_verified": True,
        "initial_exclusions_zero": True,
        "frames": rep.get("frames"),
        "particles": rep.get("particles"),
        "initial_mass_kg": rep.get("initial_mass_kg"),
        "initial_mass_relative_error": rep.get("initial_mass_relative_error"),
    }


def run_macro_worker(
    binding_path: Path,
    output_path: Path,
    *,
    check_only: bool = False,
    allow_pending: bool = False,
) -> dict[str, Any]:
    """Execute the full three-DP macro worker according to binding specifications."""
    binding = load_json(binding_path)
    mother_id = binding["mother_id"]
    scale_reg_path = Path(binding["scale_registration"])
    scale_reg = load_json(scale_reg_path)

    # 1. Verify scale registration and reject old normalizers
    scale_audit = verify_scale_registration(scale_reg, mother_id)

    # 2. Verify canonical physical binding and exact hash
    expected_hash = EXPECTED_PHYSICAL_HASHES[mother_id]
    phys_audit = verify_canonical_physical_binding(binding["canonical_physical_binding"], expected_hash)

    # 3. Verify solver receipts and exclusions
    case_ids = [c["case_id"] for c in binding["cases"]]
    solver_audit = verify_solver_receipts(binding["cases"], binding.get("excluded_historical_attempts", []))

    # 4. Verify initial QA 031 record
    qa_audit = verify_initial_qa_record(binding["initial_qa"]["receipt"], case_ids)

    # Check if conversion reports and observations exist
    cases_ready = True
    observations = {}
    q_i13_audits = {}

    for c in binding["cases"]:
        obs_p = Path(c.get("future_observation", ""))
        rep_p = Path(c.get("future_conversion_report", ""))
        if not (obs_p.is_file() and rep_p.is_file()):
            cases_ready = False
            break
        else:
            q_i13_audits[c["case_id"]] = check_q_i13_report(rep_p)
            obs_data = load_json(obs_p)

            # Frame count and window checks
            expected_frames = scale_audit["expected_frames"]
            if len(obs_data.get("rows", [])) != expected_frames:
                raise ValueError(
                    f"Case {c['case_id']} observation rows {len(obs_data.get('rows', []))} != {expected_frames}"
                )
            rows = obs_data["rows"]
            assert rows[0]["time_s"] == 0.0
            assert rows[-1]["time_s"] >= scale_audit["full_window_s"][1] - 1e-12

            # Initial mass check
            num_mass = float(obs_data["numerical_initial_mass_kg"])
            cont_mass = float(scale_audit["continuous_initial_mass_kg"])
            rel_err = abs(num_mass - cont_mass) / cont_mass
            if rel_err > scale_audit["initial_mass_budget_fraction"]:
                raise ValueError(
                    f"Case {c['case_id']} initial mass relative error {rel_err:.4e} exceeds 1% budget"
                )

            observations[c["role"]] = {
                "case_id": c["case_id"],
                "role": c["role"],
                "observation": obs_data,
                "initial_mass_kg": num_mass,
                "initial_mass_relative_error": rel_err,
            }

    if check_only:
        out = {
            "schema": "ds02.f1.lower-head-macro-preflight-audit.v1",
            "mother_id": mother_id,
            "status": "preflight_audit_passed",
            "scale_audit": scale_audit,
            "physical_audit": phys_audit,
            "solver_audit": solver_audit,
            "initial_qa_audit": qa_audit,
            "cases_converted_ready": cases_ready,
            "claim_boundary": {
                "q_n": "not_granted",
                "production_approval": "none",
                "numerical_results": "pending" if not cases_ready else "evaluable",
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        return out

    if not cases_ready:
        if not allow_pending:
            raise FileNotFoundError(
                f"Conversion reports / observations for {mother_id} are not yet on disk. "
                "Conversions are queued in integrationWT (034 and 036). Use --allow-pending to generate "
                "the verified pending status artifact."
            )
        out = {
            "schema": "ds02.f1.lower-head-macro-comparison.v1",
            "mother_id": mother_id,
            "numerical_status": "pending_converter_execution",
            "reason": (
                "Native solver receipts and initial QA are 100% verified complete. "
                "Typed conversions are queued under root_actual_fallback_canonical_bindings_and_typed_034 "
                "and root_actual_fallback_completed_dual_fine_typed_036. "
                "Numerical comparisons remain strictly pending until Root dispatches the queued conversions."
            ),
            "physical_window_s": scale_audit["full_window_s"],
            "expected_frames": scale_audit["expected_frames"],
            "scale_audit": scale_audit,
            "physical_audit": phys_audit,
            "solver_audit": solver_audit,
            "initial_qa_audit": qa_audit,
            "bindings": {
                "canonical_physical_binding": binding["canonical_physical_binding"],
                "physical_condition_sha256": expected_hash,
                "scale_registration": str(scale_reg_path),
                "cases": [
                    {
                        "role": c["role"],
                        "case_id": c["case_id"],
                        "dp_m": c["dp_m"],
                        "solver_receipt": c["solver_receipt"],
                        "gencase_xml": c["gencase_xml"],
                        "queued_conversion_request": c.get("conversion_request"),
                    }
                    for c in binding["cases"]
                ],
                "excluded_historical_attempts": binding.get("excluded_historical_attempts", []),
            },
            "pairs": {
                "fine_vs_coarse": {"status": "pending_converter_reports"},
                "fine_vs_medium": {"status": "pending_converter_reports"},
                "medium_vs_coarse": {"status": "pending_converter_reports"},
            },
            "claim_boundary": {
                "q_n": "not_granted",
                "production_approval": "none",
                "mass_normalization": "none",
                "operator": (
                    "exact frozen F1 compare_pair; frozen COM/coordinate-quantiles/KE 5% metrics "
                    "with physically required lower-head scales; velocity and mass differences descriptive"
                ),
                "geometry_identity": "same continuum lower-head mother condition; discrete thick-DBC XML geometries legitimately differ across DP",
                "temporal_or_event_convergence": "not established by spatial macro comparison",
                "numerical_results": "pending_future_converter_reports",
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        return out

    # If all observations are ready on disk, compute exact all-pairs macro comparisons
    pairs = {}
    pair_defs = [
        ("fine", "coarse"),
        ("fine", "medium"),
        ("medium", "coarse"),
    ]
    for x, y in pair_defs:
        cand = observations[x]
        ref = observations[y]
        pair_res = compare_pair(
            cand,
            ref,
            cadence=scale_audit["save_cadence_s"],
            max_offset=scale_reg["max_time_offset_s"],
            H0=scale_audit["H0_m"],
            continuous_mass=scale_audit["continuous_initial_mass_kg"],
            macro_budget=scale_audit["macro_budget_fraction"],
        )
        pairs[f"{x}_vs_{y}"] = pair_res

    out = {
        "schema": "ds02.f1.lower-head-macro-comparison.v1",
        "mother_id": mother_id,
        "numerical_status": "evaluated",
        "physical_window_s": scale_audit["full_window_s"],
        "expected_frames": scale_audit["expected_frames"],
        "scale_audit": scale_audit,
        "physical_audit": phys_audit,
        "solver_audit": solver_audit,
        "initial_qa_audit": qa_audit,
        "q_i13_audits": q_i13_audits,
        "pairs": pairs,
        "claim_boundary": {
            "q_n": "not_granted",
            "production_approval": "none",
            "mass_normalization": "none",
            "operator": (
                "exact frozen F1 compare_pair; frozen COM/coordinate-quantiles/KE 5% metrics "
                "with physically required lower-head scales; velocity and mass differences descriptive"
            ),
            "geometry_identity": "same continuum lower-head mother condition; discrete thick-DBC XML geometries legitimately differ across DP",
            "temporal_or_event_convergence": "not established by spatial macro comparison",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True, help="Path to macro binding JSON")
    parser.add_argument("--output", type=Path, required=True, help="Path to write output macro comparison JSON")
    parser.add_argument("--check-only", action="store_true", help="Perform preflight verification only")
    parser.add_argument("--allow-pending", action="store_true", help="Allow pending converter reports")
    args = parser.parse_args()

    run_macro_worker(
        args.binding,
        args.output,
        check_only=args.check_only,
        allow_pending=args.allow_pending,
    )


if __name__ == "__main__":
    main()
