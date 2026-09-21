#!/usr/bin/env python3
"""Create the v4 eight-cell CPU solver-canary authorization plan.

The output is a root-review artifact only.  It binds every input by hash and
describes one exact-one CPU attempt per selected cell, but it never starts a
solver, GPU process, queue submission, registry update, ledger update, or
qualification matrix submission.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
DESIGN_DIR = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921"
)
DESIGN = DESIGN_DIR / "design.json"
AUDIT = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-preflight-v4-20260921/qualification-preflight-audit.json"
)
PREFLIGHT_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-preflight-v4-20260921"
CANARY_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921"
WORKER = LAB / "scripts/f6_physical_anchor_observation_axis_v10_cell_solver_canary.py"
SOLVER = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4CPU_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
FLOATING_INFO = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64"

SELECTED_INDICES = (0, 4, 5, 8, 9, 12, 13, 14)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        display = path.relative_to(LAB.resolve()).as_posix()
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def build() -> dict[str, Any]:
    design = load(DESIGN)
    audit = load(AUDIT)
    if audit.get("matrix_complete") is not True or audit.get("T1") is not False:
        raise ValueError("v4 native preflight audit is not complete and nonqualifying")
    if not SOLVER.is_file() or not DECODER.is_file() or not FLOATING_INFO.is_file() or not WORKER.is_file():
        raise FileNotFoundError("pinned solver/decoder/FloatingInfo/worker input missing")
    cells = design["cells"]
    rows = audit["cells"]
    plans: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for index in SELECTED_INDICES:
        cell = cells[index]
        row = rows[index]
        cell_root = CANARY_ROOT / f"cell-{index:02d}"
        preflight_root = PREFLIGHT_ROOT / f"cell-{index:02d}"
        receipt = load(preflight_root / "native" / "preflight.json")
        event_path = preflight_root / "source/event-window-contract.json"
        event = load(event_path)
        input_refs = {
            "definition": ref(preflight_root / "source" / f"{receipt['cell_binding']['definition_id']}_Def.xml", "fresh cell Definition"),
            "definition_contract": ref(preflight_root / "source/definition-contract.json", "fresh cell Definition contract"),
            "sidecar_schema": ref(preflight_root / "source/body-state-force-torque-sidecar-schema.json", "fresh cell sidecar schema"),
            "event_window": ref(event_path, "fresh cell event-window contract"),
            "proposal": ref(preflight_root / "source/proposal.json", "fresh cell proposal"),
            "root_preflight": ref(preflight_root / "source/preflight-static.json", "fresh cell static preflight"),
            "native_preflight": ref(preflight_root / "native/preflight.json", "fresh cell native preflight"),
            "generated_xml": ref(preflight_root / "native/generated" / f"{receipt['cell_binding']['case_id']}.xml", "fresh GenCase XML"),
            "generated_bi4": ref(preflight_root / "native/generated" / f"{receipt['cell_binding']['case_id']}.bi4", "fresh GenCase BI4"),
        }
        window = {
            "start_s": 0.0,
            "target_end_s": 1.5,
            "requested_output_interval_s": float(cell["time_contract"]["output_interval_s"]),
            "expected_frames": int(cell["time_contract"]["expected_frame_count"]),
            "max_gap_s": float(cell["time_contract"]["max_native_gap_s"]),
            "terminal_target_s": 1.5,
            "terminal_overshoot_max_s": float(cell["time_contract"]["terminal_overshoot_max_s"]),
            "observation_window_s": [1.0, 1.5],
            "contact_window_s": event["predicted_events"]["contact_prediction_window_s"],
            "equilibrium_status": "not_claimed",
        }
        job_id = f"f6-v10-v4-solver-canary-cell-{index:02d}"
        review = {
            "schema": "core.f6.observation_axis.protected_solver_canary_root_review.v1",
            "review_id": f"{job_id}-root-review",
            "created_at_utc": stamp(),
            "status": "root_review_authorized_one_cpu_solver_canary_not_started",
            "family": "F6",
            "scope_id": design["scope_id"],
            "revision_id": design["revision_id"],
            "cell_id": cell["cell_id"],
            "case_id": receipt["cell_binding"]["case_id"],
            "decision": {
                "authorized_solver": True,
                "authorized_cpu_solver": True,
                "authorized_gpu": False,
                "authorized_queue": False,
                "authorized_registry": False,
                "authorized_ledger": False,
                "authorized_matrix": False,
                "exactly_one_solver_attempt": True,
                "same_input_retry": False,
                "resume": False,
            },
            "basis": {
                "design": ref(DESIGN, "frozen v4 13+2 design"),
                "preflight_audit": ref(AUDIT, "all-15 v4 native preflight audit"),
                "native_preflight": input_refs["native_preflight"],
            },
            "window": window,
            "qualification_claim": "none",
            "qualification_credit": 0,
            "T1": False,
            "execution_controls": {
                "solver_invoked": False,
                "gpu_started": False,
                "queue_mutation": 0,
                "registry_mutation": 0,
                "ledger_mutation": 0,
                "matrix_submission": False,
            },
        }
        review_path = cell_root / "root-review.json"
        write(review_path, review)
        job = {
            "schema": "core.f6.observation_axis.protected_solver_canary_job.v1",
            "job_id": job_id,
            "logical_id": job_id,
            "job_status": "root_authorized_not_started",
            "attempt": 1,
            "family": "F6",
            "scope_id": design["scope_id"],
            "revision_id": design["revision_id"],
            "cell_id": cell["cell_id"],
            "case_id": receipt["cell_binding"]["case_id"],
            "matrix_index": index,
            "q": cell["parameter"]["q"],
            "dp_m": cell["resolution"]["dp_m"],
            "design_cell": cell["design_cell"],
            "root_review": ref(review_path, "independent root authorization"),
            "window": window,
            "solver": {
                "binary": ref(SOLVER, "pinned CPU DualSPHysics solver"),
                "threads": 8,
                "timeout_seconds": 3600,
                "cuda_visible_devices": "",
            },
            "floating_info": ref(FLOATING_INFO, "pinned FloatingInfo converter"),
            "decoder": ref(DECODER, "pinned native BI4 decoder"),
            "runtime_worker": ref(WORKER, "single-use cell solver worker"),
            "inputs": input_refs,
            "output": {"attempt_dir": str((cell_root / "attempt-001").resolve()), "overwrite": False},
            "execution_policy": {
                "exactly_one_solver_attempt": True,
                "same_input_retry": False,
                "resume": False,
                "queue_submission": False,
                "registry_mutation": False,
                "ledger_mutation": False,
                "matrix_submission": False,
                "failure_credit": 0,
            },
            "qualification_only": True,
            "qualification_claim": "none",
            "qualification_credit": 0,
            "T1": False,
        }
        job_path = cell_root / "job.json"
        write(job_path, job)
        plans.append({"index": index, "cell_id": cell["cell_id"], "job_id": job_id, "job": ref(job_path, "cell solver canary job"), "review": ref(review_path, "cell root review"), "output": job["output"], "preflight_sha256": input_refs["native_preflight"]["sha256"]})
        reviews.append({"index": index, "cell_id": cell["cell_id"], "review_id": review["review_id"], "authorized": True, "qualification_credit": 0})
    return {
        "schema": "core.f6.observation_axis.solver_canary_plan.v1",
        "plan_id": "F6_observation_axis_v10_solver_canary_plan_v4_20260921",
        "created_at_utc": stamp(),
        "status": "root_review_authorized_not_started",
        "family": "F6",
        "scope_id": design["scope_id"],
        "revision_id": design["revision_id"],
        "selected_indices": list(SELECTED_INDICES),
        "selected_count": len(SELECTED_INDICES),
        "selection_rationale": "three spatial anchors, center fine reference, two held-out points, internal-time and native-output cadence controls",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "queue_submission": False,
        "gpu_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
        "exactly_one_attempt_per_cell": True,
        "same_input_retry": False,
        "jobs": plans,
        "reviews": reviews,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=CANARY_ROOT / "plan.json")
    args = parser.parse_args(argv)
    value = build()
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "selected_count": value["selected_count"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
