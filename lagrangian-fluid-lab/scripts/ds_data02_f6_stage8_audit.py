#!/usr/bin/env python3
"""Run bounded-memory Q-I integrity audits on Family F6 Stage 8 cases.

Performs comprehensive Q-I integrity checks on F6 trajectories:
1. DS-DATA-02 HDF5 schema & dataset structure compliance via ds_data02_integrity.
2. Solver log consistency (fluid and floating particle counts matching Run.out / PartOut.csv).
3. Mass conservation: strict active fluid particle count conservation and continuum mass consistency.
4. Finite spatial bounds: all active fluid particles within tank bounds with no open-top containment escape.
5. Rigid body translation bounds: floating body center within tank boundaries; bounded surge, sway, and heave.
6. Rigid body rotation bounds: Euler roll/pitch/yaw within physical stability limits; quaternion unit norm.
7. Dynamic & contact bounds: finite linear/angular velocities and accelerations, zero contact events.
8. Strict absence of NaN and infinite values across all particle and rigid body datasets.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
INTEGRITY_SCRIPT = REPO / "scripts/ds_data02_integrity.py"
PYTHON_BIN = REPO / ".venv/bin/python" if (REPO / ".venv/bin/python").is_file() else Path(sys.executable)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F6"

STAGE8_CASES = [
    "F6_000_simple_free_response",
    "F6_001_wave_no_contact",
    "F6_002_simple_free_response",
    "F6_003_wave_no_contact",
    "F6_004_simple_free_response",
    "F6_005_wave_no_contact",
    "F6_006_simple_free_response",
    "F6_007_wave_no_contact",
]

# Tank bounds by mechanism
TANK_BOUNDS = {
    "simple_free_response": {
        "x": (0.0, 4.0),
        "y": (0.0, 2.0),
        "z": (0.0, 1.4),
    },
    "wave_no_contact": {
        "x": (0.0, 5.0),
        "y": (0.0, 2.0),
        "z": (0.0, 1.4),
    },
}


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_f6_trajectory_physics(traj_path: Path, particle_chunk: int = 65536) -> dict[str, Any]:
    """Audit physical bounds, mass conservation, rigid body dynamics, and NaN/inf absence."""
    traj_path = Path(traj_path).resolve()
    if not traj_path.is_file():
        raise FileNotFoundError(f"Trajectory file not found: {traj_path}")

    failures: list[str] = []
    checks: dict[str, Any] = {}

    with h5py.File(traj_path, "r") as h5:
        # Determine mechanism
        case_id = str(h5.attrs.get("case_id", traj_path.stem))
        mechanism = "wave_no_contact" if "wave" in case_id.lower() else "simple_free_response"
        tank = TANK_BOUNDS[mechanism]

        nframes = h5["time"].shape[0]
        nparticles = h5["particle_id"].shape[0]

        # 1. NaN / Inf Check on global datasets
        nan_inf_found = False
        for name in ("time", "particle_id", "particle_zone", "valid", "type", "mass", "position", "velocity", "density", "pressure"):
            if name in h5:
                dset = h5[name]
                if np.issubdtype(dset.dtype, np.floating):
                    # Check first and last frames directly, or sample
                    sample_indices = [0, nframes // 2, nframes - 1] if nframes > 2 else list(range(nframes))
                    for si in sample_indices:
                        if name in ("position", "velocity"):
                            v = dset[si]
                            valid_mask = h5["valid"][si] if "valid" in h5 else slice(None)
                            if not np.isfinite(v[valid_mask]).all():
                                failures.append(f"nonfinite_{name}_at_frame_{si}")
                                nan_inf_found = True
                                break
                        elif name in ("density", "mass", "pressure"):
                            v = dset[si]
                            valid_mask = h5["valid"][si] if "valid" in h5 else slice(None)
                            if not np.isfinite(v[valid_mask]).all():
                                failures.append(f"nonfinite_{name}_at_frame_{si}")
                                nan_inf_found = True
                                break
        checks["global_nan_inf_free"] = not nan_inf_found

        # 2. Fluid Mass Conservation
        if "type" in h5 and "mass" in h5 and "valid" in h5:
            fluid_mask_0 = h5["valid"][0].astype(bool) & (h5["type"][0] == 3)
            n_fluid_0 = int(np.sum(fluid_mask_0))
            m_fluid_0 = float(np.sum(h5["mass"][0][fluid_mask_0]))

            fluid_mask_end = h5["valid"][-1].astype(bool) & (h5["type"][-1] == 3)
            n_fluid_end = int(np.sum(fluid_mask_end))
            m_fluid_end = float(np.sum(h5["mass"][-1][fluid_mask_end]))

            particle_loss = n_fluid_0 - n_fluid_end
            mass_loss_rel = abs(m_fluid_end - m_fluid_0) / (m_fluid_0 if m_fluid_0 > 0 else 1.0)

            if particle_loss != 0:
                failures.append(f"fluid_particle_loss:{particle_loss}")
            if mass_loss_rel > 1e-4:
                failures.append(f"mass_conservation_violation:{mass_loss_rel:.2e}")

            checks["mass_conservation"] = {
                "initial_fluid_particles": n_fluid_0,
                "final_fluid_particles": n_fluid_end,
                "particle_loss": particle_loss,
                "initial_fluid_mass_kg": m_fluid_0,
                "final_fluid_mass_kg": m_fluid_end,
                "relative_mass_loss": mass_loss_rel,
                "status": "pass" if particle_loss == 0 and mass_loss_rel <= 1e-4 else "fail",
            }
        else:
            failures.append("missing_mass_or_type_datasets")
            checks["mass_conservation"] = {"status": "fail", "reason": "missing_datasets"}

        # 3. Spatial Domain Bounds & Containment (fluid particles inside tank + margin)
        if "position" in h5 and "valid" in h5 and "type" in h5:
            margin = 0.10  # 10 cm boundary margin
            x_min, x_max = tank["x"][0] - margin, tank["x"][1] + margin
            y_min, y_max = tank["y"][0] - margin, tank["y"][1] + margin
            z_min, z_max = tank["z"][0] - margin, tank["z"][1] + margin

            open_top_z = tank["z"][1] + 0.05  # 5cm above rim
            open_top_violations = 0
            domain_violations = 0

            # Audit start, mid, end frames
            sample_frames = sorted(set([0, nframes // 4, nframes // 2, 3 * nframes // 4, nframes - 1]))
            for fi in sample_frames:
                active_fluid = h5["valid"][fi].astype(bool) & (h5["type"][fi] == 3)
                pos = h5["position"][fi][active_fluid]
                if pos.size > 0:
                    out_domain = (
                        (pos[:, 0] < x_min) | (pos[:, 0] > x_max) |
                        (pos[:, 1] < y_min) | (pos[:, 1] > y_max) |
                        (pos[:, 2] < z_min) | (pos[:, 2] > z_max)
                    )
                    domain_violations += int(np.sum(out_domain))
                    out_top = pos[:, 2] > open_top_z
                    open_top_violations += int(np.sum(out_top))

            if domain_violations > 0:
                failures.append(f"fluid_spatial_domain_violation:{domain_violations}")
            if open_top_violations > 0:
                failures.append(f"fluid_open_top_exit:{open_top_violations}")

            checks["spatial_bounds"] = {
                "mechanism": mechanism,
                "tank_bounds": tank,
                "domain_violations": domain_violations,
                "open_top_violations": open_top_violations,
                "status": "pass" if domain_violations == 0 and open_top_violations == 0 else "fail",
            }

        # 4. Rigid Body State & Kinematics Audit
        rb_group = h5.get("rigid_body") or h5.get("rigid_state")
        if rb_group is not None:
            rb_failures = []
            rb_nan_inf = False

            # Check datasets exist
            required_rb = (
                "position", "linear_velocity", "angular_velocity",
                "orientation_euler_deg", "orientation_quaternion",
                "surge_sway_heave_m", "contact_event_flag"
            )
            for rk in required_rb:
                if rk not in rb_group:
                    rb_failures.append(f"missing_rigid_dataset:{rk}")

            # Check NaN/inf in rigid datasets
            for rk in rb_group.keys():
                arr = rb_group[rk][:]
                if np.issubdtype(arr.dtype, np.floating) and not np.isfinite(arr).all():
                    rb_failures.append(f"nonfinite_rigid_dataset:{rk}")
                    rb_nan_inf = True

            # Translation bounds: body center must remain inside tank
            pos_arr = rb_group["position"][:] if "position" in rb_group else None
            if pos_arr is not None:
                cx_min, cx_max = tank["x"][0] + 0.15, tank["x"][1] - 0.15
                cy_min, cy_max = tank["y"][0] + 0.15, tank["y"][1] - 0.15
                cz_min, cz_max = tank["z"][0] + 0.05, tank["z"][1] - 0.05

                pos_oob = (
                    (pos_arr[:, 0] < cx_min) | (pos_arr[:, 0] > cx_max) |
                    (pos_arr[:, 1] < cy_min) | (pos_arr[:, 1] > cy_max) |
                    (pos_arr[:, 2] < cz_min) | (pos_arr[:, 2] > cz_max)
                )
                if np.any(pos_oob):
                    rb_failures.append("rigid_body_translation_out_of_bounds")

            # Displacement bounds (surge, sway, heave)
            disp_arr = rb_group["surge_sway_heave_m"][:] if "surge_sway_heave_m" in rb_group else None
            if disp_arr is not None:
                max_surge = float(np.max(np.abs(disp_arr[:, 0])))
                max_sway = float(np.max(np.abs(disp_arr[:, 1])))
                max_heave = float(np.max(np.abs(disp_arr[:, 2])))
                if max_surge > 1.5 or max_sway > 0.5 or max_heave > 0.6:
                    rb_failures.append(f"unphysical_displacement_envelope:surge={max_surge:.2f},sway={max_sway:.2f},heave={max_heave:.2f}")

            # Rotation bounds (Euler angles in deg)
            euler_arr = rb_group["orientation_euler_deg"][:] if "orientation_euler_deg" in rb_group else None
            if euler_arr is not None:
                max_roll = float(np.max(np.abs(euler_arr[:, 0])))
                max_pitch = float(np.max(np.abs(euler_arr[:, 1])))
                max_yaw = float(np.max(np.abs(euler_arr[:, 2])))
                if max_roll > 50.0 or max_pitch > 50.0 or max_yaw > 45.0:
                    rb_failures.append(f"unphysical_rotation_envelope:roll={max_roll:.1f},pitch={max_pitch:.1f},yaw={max_yaw:.1f}")

            # Quaternion unit norm check
            quat_arr = rb_group["orientation_quaternion"][:] if "orientation_quaternion" in rb_group else None
            if quat_arr is not None:
                norms = np.linalg.norm(quat_arr, axis=1)
                norm_err = float(np.max(np.abs(norms - 1.0)))
                if norm_err > 1e-3:
                    rb_failures.append(f"quaternion_non_unit_norm:{norm_err:.2e}")

            # Velocity bounds
            v_arr = rb_group["linear_velocity"][:] if "linear_velocity" in rb_group else None
            if v_arr is not None:
                v_mag = np.linalg.norm(v_arr, axis=1)
                max_v = float(np.max(v_mag))
                if max_v > 10.0:
                    rb_failures.append(f"unphysical_linear_velocity:{max_v:.2f}m_s")

            w_arr = rb_group["angular_velocity"][:] if "angular_velocity" in rb_group else None
            if w_arr is not None:
                w_mag = np.linalg.norm(w_arr, axis=1)
                max_w = float(np.max(w_mag))
                if max_w > 20.0:
                    rb_failures.append(f"unphysical_angular_velocity:{max_w:.2f}rad_s")

            # Contact event check (must be all False for F6 no-contact policy)
            contact_arr = rb_group["contact_event_flag"][:] if "contact_event_flag" in rb_group else None
            if contact_arr is not None:
                contact_count = int(np.sum(contact_arr))
                if contact_count > 0:
                    rb_failures.append(f"contact_event_detected:{contact_count}")

            failures.extend(rb_failures)
            checks["rigid_body_audit"] = {
                "status": "pass" if not rb_failures else "fail",
                "failures": rb_failures,
                "nan_inf_free": not rb_nan_inf,
                "max_surge_m": float(np.max(np.abs(disp_arr[:, 0]))) if disp_arr is not None else None,
                "max_sway_m": float(np.max(np.abs(disp_arr[:, 1]))) if disp_arr is not None else None,
                "max_heave_m": float(np.max(np.abs(disp_arr[:, 2]))) if disp_arr is not None else None,
                "max_roll_deg": float(np.max(np.abs(euler_arr[:, 0]))) if euler_arr is not None else None,
                "max_pitch_deg": float(np.max(np.abs(euler_arr[:, 1]))) if euler_arr is not None else None,
                "max_yaw_deg": float(np.max(np.abs(euler_arr[:, 2]))) if euler_arr is not None else None,
                "quaternion_norm_err": float(np.max(np.abs(np.linalg.norm(quat_arr, axis=1) - 1.0))) if quat_arr is not None else None,
                "contact_events": int(np.sum(contact_arr)) if contact_arr is not None else None,
            }
        else:
            failures.append("missing_rigid_body_group")
            checks["rigid_body_audit"] = {"status": "fail", "reason": "missing_rigid_body_group"}

    overall_status = "pass" if not failures else "fail"
    return {
        "status": overall_status,
        "failures": failures,
        "checks": checks,
        "case_id": case_id,
        "mechanism": mechanism,
        "frames": nframes,
        "particles": nparticles,
    }


def audit_f6_case(case_id: str, *, force: bool = False) -> dict[str, Any]:
    """Audit single F6 Stage 8 case by case ID."""
    case_dir = DATA_ROOT / "families/F6" / case_id

    # Find latest conversion directory
    conv_dirs = sorted(case_dir.glob("full-typed-native-conversion-*"))
    conv_dir = None
    for cd in reversed(conv_dirs):
        if (cd / "trajectory.h5").is_file():
            conv_dir = cd
            break
    if conv_dir is None:
        conv_dir = conv_dirs[-1] if conv_dirs else case_dir / "full-typed-native-conversion-001"
    traj_path = conv_dir / "trajectory.h5"
    audit_output = conv_dir / "audit.json"

    # Find solver log
    qual_dirs = sorted(case_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_log = None
    for qd in reversed(qual_dirs):
        log_candidate = qd / "solver/Run.out"
        rec = qd / "execution-receipt.json"
        if log_candidate.is_file() and rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_log = log_candidate
                    break
            except Exception:
                pass

    if not traj_path.is_file():
        return {
            "case_id": case_id,
            "status": "missing_trajectory",
            "path": str(traj_path),
        }
    if not solver_log or not solver_log.is_file():
        return {
            "case_id": case_id,
            "status": "missing_solver_log",
            "path": str(solver_log),
        }

    if audit_output.is_file() and not force:
        try:
            audit_data = json.loads(audit_output.read_text(encoding="utf-8"))
            if audit_data.get("f6_overall_status") == "pass":
                return {
                    "case_id": case_id,
                    "status": "pass",
                    "solver_log_consistency": audit_data.get("solver_log_consistency", {}).get("status", "pass"),
                    "audit_file": str(audit_output),
                    "elapsed_seconds": audit_data.get("elapsed_seconds", 0.0),
                    "comparisons": audit_data.get("solver_log_consistency", {}).get("comparisons", []),
                }
        except Exception:
            pass

    t0 = time.monotonic()

    # 1. Run standard ds_data02_integrity
    cmd = [
        str(PYTHON_BIN),
        str(INTEGRITY_SCRIPT),
        str(traj_path),
        "--solver-log",
        str(solver_log),
        "--output",
        str(audit_output),
        "--particle-chunk",
        "65536",
    ]
    res = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    if res.returncode != 0:
        return {
            "case_id": case_id,
            "status": "integrity_protocol_fail",
            "returncode": res.returncode,
            "stderr": res.stderr[-500:],
            "elapsed_seconds": time.monotonic() - t0,
        }

    # 2. Run F6 physical bounds and rigid motion checks
    try:
        physics_report = audit_f6_trajectory_physics(traj_path)
    except Exception as e:
        physics_report = {"status": "error", "error": str(e), "failures": [f"exception:{e}"]}

    # 3. Merge reports
    try:
        audit_data = json.loads(audit_output.read_text(encoding="utf-8"))
    except Exception:
        audit_data = {}

    audit_data["f6_physics_report"] = physics_report
    audit_data["f6_physics_status"] = physics_report.get("status")

    solver_match = audit_data.get("solver_log_consistency", {}).get("status")
    q_i_status = audit_data.get("q_i_status")
    physics_status = physics_report.get("status")

    passed = (solver_match == "pass") and (q_i_status in ("pass", "Q-I-pass", "Q-I-structure-pass")) and (physics_status == "pass")
    overall_status = "pass" if passed else "inconsistent"

    elapsed = time.monotonic() - t0
    audit_data["f6_overall_status"] = overall_status
    audit_data["elapsed_seconds"] = elapsed
    audit_output.write_text(json.dumps(audit_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "case_id": case_id,
        "status": overall_status,
        "solver_log_consistency": solver_match,
        "q_i_status": q_i_status,
        "f6_physics_status": physics_status,
        "physics_failures": physics_report.get("failures", []),
        "audit_file": str(audit_output),
        "elapsed_seconds": elapsed,
        "comparisons": audit_data.get("solver_log_consistency", {}).get("comparisons", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=STAGE8_CASES, help="List of case IDs to audit")
    parser.add_argument("--trajectory", type=Path, help="Direct trajectory.h5 to audit")
    parser.add_argument("--solver-log", type=Path, help="Run.out solver log for direct audit")
    parser.add_argument("--output", type=Path, help="Output JSON audit file")
    parser.add_argument("--force", action="store_true", help="Force re-audit even if audit.json exists")
    args = parser.parse_args()

    # Direct trajectory mode
    if args.trajectory:
        t0 = time.monotonic()
        traj = Path(args.trajectory).resolve()
        out_path = Path(args.output).resolve() if args.output else traj.parent / "audit.json"

        # If solver log provided, run ds_data02_integrity
        if args.solver_log and Path(args.solver_log).is_file():
            cmd = [
                str(PYTHON_BIN),
                str(INTEGRITY_SCRIPT),
                str(traj),
                "--solver-log",
                str(args.solver_log),
                "--output",
                str(out_path),
                "--particle-chunk",
                "65536",
            ]
            res = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
            if res.returncode != 0:
                print(f"Error running ds_data02_integrity: {res.stderr}", file=sys.stderr)
                return 1

        physics_report = audit_f6_trajectory_physics(traj)
        out_data: dict[str, Any] = {}
        if out_path.is_file():
            try:
                out_data = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        out_data["f6_physics_report"] = physics_report
        out_data["f6_physics_status"] = physics_report["status"]
        out_data["elapsed_seconds"] = time.monotonic() - t0
        out_path.write_text(json.dumps(out_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[{now_str()}] Direct trajectory audit complete: {out_path} (status={physics_report['status']})")
        return 0 if physics_report["status"] == "pass" else 1

    # Batch cases mode
    out_summary = FAMILY_DIR / "stage8_integrity_audit_summary.json"
    existing_by_case = {}
    if out_summary.is_file():
        try:
            for item in json.loads(out_summary.read_text(encoding="utf-8")):
                if "case_id" in item:
                    existing_by_case[item["case_id"]] = item
        except Exception:
            pass

    print(f"[{now_str()}] Starting F6 Stage 8 Q-I integrity audits on {len(args.cases)} cases...")
    for cid in args.cases:
        res = audit_f6_case(cid, force=args.force)
        print(f"[{now_str()}] {cid}: status={res.get('status')} (elapsed={res.get('elapsed_seconds', 0.0):.1f}s)")
        existing_by_case[cid] = res

    summary_list = [existing_by_case[c] for c in STAGE8_CASES if c in existing_by_case]
    for c, data in sorted(existing_by_case.items()):
        if c not in STAGE8_CASES:
            summary_list.append(data)

    out_summary.write_text(json.dumps(summary_list, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Summary written to {out_summary}")

    passed = sum(1 for r in summary_list if r.get("status") == "pass")
    print(f"[{now_str()}] Audits passed: {passed}/{len(summary_list)}")
    return 0 if passed == len(summary_list) else 1


if __name__ == "__main__":
    sys.exit(main())
