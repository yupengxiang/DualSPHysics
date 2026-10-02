#!/usr/bin/env python3
"""Read-only audit of enriched rigid H5 and native labels receipts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import h5py
    import numpy as np
except (ImportError, OSError, ValueError):
    h5py = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]


SCRIPT = Path(__file__).resolve()
V21 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v21.py")
import importlib.util

SPEC = importlib.util.spec_from_file_location("f6_handoff_v21_for_h5_labels_audit", V21)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load v21: {V21}")
V21_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V21_MODULE)

FAMILY_ROOT = V21_MODULE.FAMILY_ROOT
RAW_ROOT = V21_MODULE.RAW_ROOT
POST_ROOT = V21_MODULE.POST_ROOT


def sha256(path: Path) -> str:
    return V21_MODULE.sha256(path)


def write_json(path: Path, value: Any) -> None:
    V21_MODULE.write_json(path, value)


def audit() -> dict[str, Any]:
    if h5py is None or np is None:
        raise RuntimeError("H5 audit requires the integration .venv Python with compatible h5py/numpy")
    cases = []
    for mechanism in ("simple_free_response", "wave_no_contact"):
        case = V21_MODULE.V16_MODULE._old_medium_case(mechanism)
        cid = str(case["case_id"])
        root = RAW_ROOT / cid
        trajectory = root / f"{cid}_NATIVE_H5_004/trajectory.h5"
        conversion_report = root / f"{cid}_NATIVE_H5_004/conversion-report.json"
        labels = root / f"{cid}_LABELS_004/native-labels.h5"
        label_receipt = root / f"{cid}_LABELS_004/labels-receipt.json"
        label_execution = root / f"{cid}_LABELS_004/execution-receipt.json"
        with h5py.File(trajectory, "r") as h5, h5py.File(labels, "r") as lab:
            valid = np.asarray(h5["valid"][:], dtype=bool)
            initial_type = np.asarray(h5["initial_type"][:], dtype=np.int8)
            fluid = initial_type == 3
            rb = h5["rigid_body"]
            center = json.loads(str(h5.attrs["floating_center_m"]))
            inertia = json.loads(str(h5.attrs["floating_inertia_kg_m2"]))
            saved_pose = np.asarray(rb["position"][0], dtype=np.float64).tolist()
            force_norm = np.linalg.norm(np.asarray(rb["fluid_force"][:], dtype=np.float64), axis=1)
            torque_norm = np.linalg.norm(np.asarray(rb["fluid_torque"][:], dtype=np.float64), axis=1)
            categories, category_counts = np.unique(np.asarray(lab["final_category"][:], dtype=np.int16), return_counts=True)
            label_attrs = {str(key): (value.item() if hasattr(value, "item") else str(value)) for key, value in lab.attrs.items()}
            source_hdf5_hash = str(label_attrs.get("source_hdf5_sha256", ""))
            row = {
                "case_id": cid,
                "mechanism_id": mechanism,
                "trajectory": {"path": str(trajectory.resolve()), "sha256": sha256(trajectory), "frames": int(valid.shape[0]), "particles": int(valid.shape[1]), "valid_false_rows": int((~valid).sum()), "valid_false_fluid_rows": int((~valid[:, fluid]).sum()), "lifecycle_mode": str(h5.attrs["lifecycle_mode"])},
                "rigid_state": {"massbody_kg": float(h5.attrs["floating_massbody_kg"]), "masspart_kg": float(h5.attrs["floating_masspart_kg"]), "center_m": center, "inertia_tensor_kg_m2": inertia, "saved_pose_t0_m": saved_pose, "pose_center_max_abs_m": max(abs(a - b) for a, b in zip(saved_pose, center)), "force_norm_max": float(force_norm.max()), "torque_norm_max": float(torque_norm.max()), "fields": sorted(rb.keys())},
                "labels": {"path": str(labels.resolve()), "sha256": sha256(labels), "receipt": str(label_receipt.resolve()), "receipt_sha256": sha256(label_receipt), "execution_receipt": str(label_execution.resolve()), "execution_receipt_sha256": sha256(label_execution), "schema": str(lab.attrs["schema"]), "complete": bool(lab.attrs["complete"]), "model_invoked": bool(lab.attrs["model_invoked"]), "initial_fluid_mass_kg": float(lab.attrs["initial_fluid_mass_kg"]), "source_hdf5_sha256_matches": source_hdf5_hash == sha256(trajectory), "unknown_mass_last_kg": float(lab["unknown_mass_kg"][-1]), "numerical_loss_mass_last_kg": float(lab["numerical_loss_mass_kg"][-1]), "invalid_state_mass_last_kg": float(lab["invalid_state_mass_kg"][-1]), "final_category_counts": {str(int(key)): int(value) for key, value in zip(categories, category_counts)}},
                "conversion_report_sha256": sha256(conversion_report),
                "q_n_status": "pending_native_exclusion_reconciliation",
            }
        row["checks"] = {"positive_inertia": all(float(inertia[i][i]) > 0 for i in range(3)), "pose_center_fit": row["rigid_state"]["pose_center_max_abs_m"] <= 1.0e-5, "force_nonzero": row["rigid_state"]["force_norm_max"] > 0, "torque_nonzero": row["rigid_state"]["torque_norm_max"] > 0, "complete_rigid_fields": {"position", "orientation_quaternion", "linear_velocity", "angular_velocity", "fluid_force", "fluid_torque"}.issubset(set(row["rigid_state"]["fields"])), "labels_complete": row["labels"]["complete"], "labels_no_model": row["labels"]["model_invoked"] is False, "labels_source_h5_hash_bound": row["labels"]["source_hdf5_sha256_matches"], "initial_fluid_mass_kg_5120": abs(row["labels"]["initial_fluid_mass_kg"] - 5120.0) < 1.0e-6}
        cases.append(row)
    result = {"schema": "ds-data-02.f6.rigid003.h5-labels-audit.v1", "family_id": "F6", "status": "actual_cpu_postprocessing_review_only", "cases": cases, "gpu_launch": False, "qualification_claim": "none", "production_claim": "none", "q_n_status": "pending native exclusion reconciliation and scientific review"}
    write_json(POST_ROOT / "h5_labels_audit_001.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
