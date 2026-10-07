#!/usr/bin/env python3
"""Guarded v9 observer probe over F2 sidecar and small F6 telemetry inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_observer_v9 import (  # noqa: E402
    bind_first_passage_first_bracket,
    load_f6_source_bound_telemetry,
    manufactured_mass_calibration,
    manufactured_so3_calibration,
    points_in_frame,
    sha256,
    summarize_f2_scan_sidecar,
    validate_observation_contract,
    validate_profile,
)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--f2-profile", type=Path, required=True)
    parser.add_argument("--f6-profile", type=Path, required=True)
    parser.add_argument("--f2-scan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    f2 = json.loads(args.f2_profile.read_text(encoding="utf-8"))
    f6 = json.loads(args.f6_profile.read_text(encoding="utf-8"))

    # Source verification occurs before any report is written.  The profile
    # source lists intentionally contain no trajectory HDF5 path.
    f2_validated = validate_profile(f2, verify_sources=True)
    f6_validated = validate_profile(f6, verify_sources=True)
    mass_calibration = manufactured_mass_calibration()
    so3_calibration = manufactured_so3_calibration()
    f2_summary = summarize_f2_scan_sidecar(args.f2_scan, f2_validated)
    f6_telemetry = load_f6_source_bound_telemetry(f6_validated)

    # A fixed-shape macro contract is checked with hand-authored arrays.  This
    # exercises the same contract used by a future source-bound evaluator.
    f2_contract = f2_validated["observation_contract"]
    contract_payload = {
        "query_times_s": f2_contract["query_times_s"],
        "active_fluid_mass_kg": [1.0] * 4,
        "active_fluid_com_m": [[0.0, 0.0, 0.0]] * 4,
        "active_fluid_mean_velocity_m_s": [[0.0, 0.0, 0.0]] * 4,
        "active_fluid_kinetic_energy_J": [0.0] * 4,
        "scales": f2_contract["fixed_scales"],
        "feature_time_s": f2_contract["feature_time_s"],
    }
    # The contract requires exactly the fixed macro names; build a second
    # payload with those names for validation while retaining the explicit
    # source summary above.
    contract_validation = validate_observation_contract(f2_validated, contract_payload)
    first_passage = bind_first_passage_first_bracket(
        crossing_times_s=[0.4, 1.5], saved_brackets=[[0.0, 1.0], [1.0, 2.0]])
    moving_frame_probe = points_in_frame(
        [[2.0, 3.0, 4.0], [2.0, 4.0, 4.0]], source_frame="world", target_frame="body",
        pose={"rotation_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
              "translation_m": [2.0, 3.0, 4.0]})

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    _write(output_root / "manufactured-mass-observer-calibration-v9.json", mass_calibration)
    _write(output_root / "manufactured-so3-observer-calibration-v9.json", so3_calibration)
    _write(output_root / "f2-scan-summary-v9.json", f2_summary)
    _write(output_root / "f6-rigid-telemetry-v9.json", f6_telemetry)
    _write(output_root / "frozen-contract-validation-v9.json", contract_validation)
    _write(output_root / "first-passage-bracket-binding-v9.json", first_passage)
    _write(output_root / "moving-frame-probe-v9.json", {"body_points_m": moving_frame_probe.tolist(),
                                                          "pose_semantics": "explicit world_to_body; no arbitrary latest frame"})
    report = {
        "schema": "ds02.stage2.reference-observer-probe-report.v9",
        "f2_profile_path": str(args.f2_profile.resolve()),
        "f2_profile_sha256": sha256(args.f2_profile),
        "f6_profile_path": str(args.f6_profile.resolve()),
        "f6_profile_sha256": sha256(args.f6_profile),
        "f2_scan_path": str(args.f2_scan.resolve()),
        "f2_scan_sha256": sha256(args.f2_scan),
        "profile_source_verification": {"f2_count": len(f2_validated["_verified_sources"]),
                                         "f6_count": len(f6_validated["_verified_sources"])},
        "manufactured_mass_status": mass_calibration["mass_status"],
        "manufactured_so3_status": so3_calibration["so3_status"],
        "contract_status": contract_validation["status"],
        "first_passage_status": first_passage["status"],
        "f2_summary_status": f2_summary["mass_observer_status"],
        "f2_frames": f2_summary["frames"],
        "f6_frames": f6_telemetry["frames"],
        "f6_massbody_kg": f6_telemetry["mass_semantics"]["massbody_kg"],
        "f6_support_particle_weight_sum_kg": f6_telemetry["mass_semantics"]["support_particle_weight_sum_kg"],
        "f6_family_binding_status": f6_telemetry["family_binding"]["status"],
        "f6_pose_velocity_status": f6_telemetry["pose_velocity_status"],
        "f6_force_pose_credit": f6_telemetry["force_pose_credit"],
        "trajectory_hdf5_read": False,
        "model_invoked": False,
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
    }
    _write(output_root / "reference-observer-probe-report-v9.json", report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
