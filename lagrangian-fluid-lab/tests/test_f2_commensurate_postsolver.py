from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


LAB_ROOT = Path(__file__).resolve().parents[1]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
SCOPE_ROOT = FAMILY_ROOT / "commensurate_cellcenter_v4"
POSTSOLVER_PATH = FAMILY_ROOT / "f2_commensurate_postsolver.py"
PREVIEW_PATH = FAMILY_ROOT / "f2_commensurate_preview.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deferred_plan_freezes_cpu_resources_and_has_no_gpu_launch() -> None:
    plan = json.loads((SCOPE_ROOT / "postsolver_plan.json").read_text(encoding="utf-8"))
    assert plan["status"] == "deferred_until_six_solver_receipts_are_terminal"
    assert plan["planner_launches_solver"] is False
    assert plan["resource_plan"]["gpu_requests"] == 0
    assert plan["resource_plan"]["per_request"] == {
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 8 * 1024**3,
    }
    assert [row["stage"] for row in plan["resource_plan"]["stages"]] == ["conversion", "labels", "qi", "preview"]
    assert "placeholder input paths are rejected" in plan["input_policy"]


def test_postsolver_binds_all_six_actual_qualification_cases() -> None:
    planner = _load(POSTSOLVER_PATH, "f2_commensurate_postsolver_test")
    rows = planner.load_qualification_requests()
    assert len(rows) == 6
    assert {row["case_id"] for row in rows} == {
        "F2_COMM4_CENTER_V1_COARSE", "F2_COMM4_CENTER_V1_MEDIUM", "F2_COMM4_CENTER_V1_FINE",
        "F2_COMM4_OFFSET_V1_COARSE", "F2_COMM4_OFFSET_V1_MEDIUM", "F2_COMM4_OFFSET_V1_FINE",
    }
    assert all(row["gencase_input_prefix"].endswith(row["case_id"]) for row in rows)
    assert all(row["gencase_artifacts"][name]["sha256"] for row in rows for name in ("receipt", "xml", "bi4", "copied_motion"))
    assert planner._stage_attempt("F2_COMM4_CENTER_V1_COARSE", "conversion").startswith("conversion-f2-comm4-center")


def test_nonterminal_solver_receipt_cannot_materialize_downstream_requests(tmp_path: Path) -> None:
    planner = _load(POSTSOLVER_PATH, "f2_commensurate_postsolver_reject_test")
    receipt_path = tmp_path / "execution-receipt.json"
    receipt_path.write_text(json.dumps({
        "status": "running",
        "returncode": None,
        "output_root": str(tmp_path),
        "request": {"family_id": "F2", "case_id": "F2_COMM4_CENTER_V1_COARSE"},
    }), encoding="utf-8")
    with pytest.raises(planner.PlanError, match="not completed successfully"):
        planner.load_solver_receipts([receipt_path])


def test_preview_phase_parser_uses_copied_motion_boundaries() -> None:
    preview = _load(PREVIEW_PATH, "f2_commensurate_preview_test")
    motion = SCOPE_ROOT / "definitions/F2_COMM4_CENTER_V1_COARSE/F2_COMM4_CENTER_V1_COARSE_motion.dat"
    phases = preview._motion_phases(motion)
    assert phases["static_hold_end_s"] == 0.5
    assert phases["rotation_start_s"] == 0.5
    assert phases["rotation_stop_s"] == 1.7
    assert phases["event_window_end_s"] == 4.0
