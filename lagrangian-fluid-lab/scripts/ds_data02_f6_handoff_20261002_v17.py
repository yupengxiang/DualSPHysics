#!/usr/bin/env python3
"""Additive F6 rigid-body torque-reference contract for post-processing.

The v16 CPU requests are already frozen.  This module records the exact
ComputeForces moment options and the rule for deriving a current-centre
torque.  It never edits v16 requests, raw BI4 trees, or completed receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V16 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v16.py")
import importlib.util

spec = importlib.util.spec_from_file_location("f6_handoff_20261002_v16_for_torque", V16)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load frozen v16 module: {V16}")
V16_MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V16_MODULE)

FAMILY_ROOT = V16_MODULE.FAMILY_ROOT
POST_ROOT = FAMILY_ROOT / "postprocessing_002"
TORQUE_CONTRACT = POST_ROOT / "torque_reference_contract_001.json"
SOURCE_REQUEST_MANIFEST = V16_MODULE.POST_ROOT / "request_manifest.json"
MECHANISMS = ("simple_free_response", "wave_no_contact")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _request_rows() -> list[dict[str, Any]]:
    manifest = read_json(SOURCE_REQUEST_MANIFEST)
    rows = []
    for entry in manifest.get("requests", []):
        path = Path(entry["path"])
        request = read_json(path)
        rows.append({
            "path": str(path.resolve()),
            "sha256": sha256(path),
            "attempt_id": request["attempt_id"],
            "cpu_task_kind": request["cpu_task_kind"],
            "case_id": request["case_id"],
            "mechanism_id": request["mechanism_id"],
        })
    return rows


def prepare() -> dict[str, Any]:
    if not SOURCE_REQUEST_MANIFEST.is_file():
        raise FileNotFoundError(SOURCE_REQUEST_MANIFEST)
    request_rows = _request_rows()
    force_rows = [row for row in request_rows if row["cpu_task_kind"] == "audit" and "COMPUTEFORCES" in row["attempt_id"]]
    floating_rows = [row for row in request_rows if row["cpu_task_kind"] == "audit" and "FLOATINGINFO" in row["attempt_id"]]
    if {row["mechanism_id"] for row in force_rows} != set(MECHANISMS):
        raise ValueError("frozen v16 ComputeForces requests are incomplete")
    if {row["mechanism_id"] for row in floating_rows} != set(MECHANISMS):
        raise ValueError("frozen v16 FloatingInfo requests are incomplete")

    result = {
        "schema": "ds-data-02.f6.rigid003.domain_xy_repair_02.torque_reference_contract_001.v1",
        "family_id": "F6",
        "created_at": V16_MODULE.MODULE.now(),
        "source_scope": "completed DOMAIN_X_REPAIR_01 medium raw solver trees and frozen v16 post-processing requests",
        "source_request_manifest": str(SOURCE_REQUEST_MANIFEST.resolve()),
        "source_request_manifest_sha256": sha256(SOURCE_REQUEST_MANIFEST),
        "source_requests": request_rows,
        "raw_compute_forces": {
            "tool": str(V16_MODULE.COMPUTE_FORCES.resolve()),
            "floating_mk": 60,
            "reference_coordinates_m": [2.4, 1.2, 1.08],
            "reference_coordinate_source": "generated native aggregate rigid center at t=0; serialized center is hash-bound in each v16 request",
            "raw_output_frames": {
                "momentin_xyz": "official intrinsic moment output: the selected axis follows the floating body and rotates with it",
                "momentex_xyz": "official extrinsic moment output: the selected axis follows the floating body origin but remains world aligned",
            },
            "raw_force_components": ["ForceFluid", "Weight", "ForceTotal"],
            "raw_torque_claim": "raw official tool output only; it is not labelled instantaneous-COM torque",
            "v16_underlying_options": [
                "-momentin_xyz:2.4:1.2:1.08",
                "-momentex_xyz:2.4:1.2:1.08",
                "-viscoauto",
                "-gravity:0:0:-9.81",
            ],
        },
        "current_com_reframe": {
            "allowed": True,
            "requires": [
                "completed FloatingInfo output for the same 241 native saved frames",
                "the actual current COM position from FloatingInfo at each frame",
                "the force component matching the torque component and frame",
                "explicit conversion between world and body axes when using momentin_xyz",
            ],
            "world_frame_formula": "tau_COM(t) = tau_reference(t) - cross(r_COM(t) - r_reference(t), F_matching(t))",
            "reference_origin_rule": "use the origin actually reported by the selected official moment output; do not substitute the initial center if the selected moving axis has translated",
            "same_component_rule": "ForceFluid pairs with fluid torque; ForceTotal pairs with total torque; never mix components",
            "current_com_label_allowed_only_after_reframe": True,
            "raw_output_preserved": True,
        },
        "join_contract": {
            "mechanisms": list(MECHANISMS),
            "frame_count": 241,
            "time_window_s": [0.0, 12.0],
            "join_key": "native saved frame index and time",
            "required_columns": ["frame", "time_s", "com_world_m", "linear_velocity_world_m_s", "angular_velocity_world_rad_s", "force_matching_N", "raw_torque", "torque_reference_frame", "torque_reference_origin_m", "torque_com_reframed"],
        },
        "q_n_status": "pending actual FloatingInfo and ComputeForces CPU outputs plus independent torque-frame review",
        "qualification_claim": "none",
        "gpu_launch": False,
    }
    write_json(TORQUE_CONTRACT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare"])
    args = parser.parse_args()
    result = prepare()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
