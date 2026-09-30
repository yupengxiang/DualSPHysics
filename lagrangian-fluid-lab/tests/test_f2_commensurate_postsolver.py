from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


LAB_ROOT = Path(__file__).resolve().parents[1]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
SCOPE_ROOT = FAMILY_ROOT / "commensurate_cellcenter_v4"
POSTSOLVER_PATH = FAMILY_ROOT / "f2_commensurate_postsolver.py"
ADAPTER_PATH = FAMILY_ROOT / "f2_commensurate_conversion_adapter.py"
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
    assert planner._stage_attempt("F2_COMM4_CENTER_V1_COARSE", "conversion", compatibility=True).endswith("fullstate-compat-scratch-v4")
    assert planner._stage_attempt("F2_COMM4_CENTER_V1_COARSE", "conversion", compatibility=True, conversion_engine="direct").endswith("fullstate-compat-direct-v1")


def test_converter_compatibility_alias_binds_original_solver_and_gencase_without_rerun(tmp_path: Path) -> None:
    adapter = _load(ADAPTER_PATH, "f2_commensurate_conversion_adapter_test")
    planner = _load(POSTSOLVER_PATH, "f2_commensurate_postsolver_compatibility_test")
    output_dir = tmp_path / "compatibility"
    manifest_path = tmp_path / "compatibility-manifest.json"
    manifest = adapter.build_aliases(
        request_dir=SCOPE_ROOT / "requests",
        output_dir=output_dir,
        manifest_path=manifest_path,
    )
    assert manifest["status"] == "derived_provenance_aliases_ready"
    assert manifest["source_bytes_unchanged"] is True
    assert len(manifest["cases"]) == 6
    compatibility = planner.load_compatibility_manifest(manifest_path)
    assert len(compatibility) == 6
    row = compatibility["F2_COMM4_CENTER_V1_COARSE"]
    metadata = json.loads(Path(row["adapted_owner_metadata"]["path"]).read_text(encoding="utf-8"))
    assert metadata["schema"].endswith("generator.v1")
    assert metadata["compatibility_adapter"]["derived_only"] is True
    assert Path(row["adapted_owner_metadata"]["path"]).name.endswith(".metadata.json")
    gencase = json.loads(Path(row["adapted_gencase_receipt"]["path"]).read_text(encoding="utf-8"))
    assert any(
        Path(value).resolve() == Path(row["adapted_owner_metadata"]["path"]).resolve()
        for value in gencase["request"]["input_files"]
    )
    solver = json.loads(Path(row["adapted_solver_receipt"]["path"]).read_text(encoding="utf-8"))
    assert Path(solver["request"]["gencase_receipt"]).resolve() == Path(row["adapted_gencase_receipt"]["path"]).resolve()
    assert solver["compatibility_adapter"]["no_gencase_rerun"] is True


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
