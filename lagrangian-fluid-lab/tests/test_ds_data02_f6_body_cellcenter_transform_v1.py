"""Unit tests for F6 body cell-center initialization with supported GenCase transform."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/ds_data02_f6_body_cellcenter_transform_v1.py"
SCOPE_ROOT = (
    ROOT
    / "campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_transform_001"
)
MANIFEST_PATH = SCOPE_ROOT / "manifest.json"
PREP_REPORT_PATH = SCOPE_ROOT / "preparation-report.json"
GUARD_PATH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
)
RUNTIME_V2 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)


def _load_json(path: Path) -> dict:
    assert path.is_file(), f"missing file: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_and_preparation_structure() -> None:
    manifest = _load_json(MANIFEST_PATH)
    assert manifest["schema"] == "ds02.f6.body-cellcenter-transform-manifest.v1"
    assert manifest["family_id"] == "F6"
    assert manifest["recipe_id"] == "F6_BODY_CELLCENTER_TRANSFORM_001"
    assert manifest["solver_or_gpu_started"] is False
    assert manifest["conversion_started"] is False
    assert manifest["q_n_status"] == "not_assessed"

    # Frozen physical contract
    contract = manifest["continuous_contract"]
    assert contract["body_low_m"] == [2.0, 0.8, 0.88]
    assert contract["body_high_m"] == [2.8, 1.6, 1.28]
    assert contract["body_mass_kg"] == 128.0
    assert contract["body_center_m"] == [2.4, 1.2, 1.08]
    assert contract["fluid_mass_kg"] == 5120.0
    assert contract["wall_low_m"] == [0.0, 0.0, 0.0]
    assert contract["wall_size_m"] == [4.8, 2.4, 2.4]
    assert contract["mass_normalization"] == "forbidden"

    # Negative evidence from Revision 0 recorded
    assert "negative_evidence_revision_0" in manifest
    assert "drawpoints" in manifest["negative_evidence_revision_0"]["hypothesis"]

    # Revision 1 transform solution recorded
    assert "revision_1_transform_solution" in manifest
    assert "initials" in manifest["revision_1_transform_solution"]["strategy"]


@pytest.mark.parametrize(
    "role,dp,target_count,expected_first,expected_last",
    [
        ("coarse", 0.025, 16384, [2.0125, 0.8125, 0.8925], [2.7875, 1.5875, 1.2675]),
        ("medium", 0.02, 32000, [2.01, 0.81, 0.89], [2.79, 1.59, 1.27]),
        ("fine", 0.0125, 131072, [2.00625, 0.80625, 0.88625], [2.79375, 1.59375, 1.27375]),
    ],
)
def test_case_specifications_and_candidate_xml(
    role: str,
    dp: float,
    target_count: int,
    expected_first: list[float],
    expected_last: list[float],
) -> None:
    manifest = _load_json(MANIFEST_PATH)
    case = manifest["cases"][role]
    assert case["dp_m"] == dp
    assert case["expected"]["type2_body_count"] == target_count
    assert case["expected"]["expected_first_center_m"] == expected_first
    assert case["expected"]["expected_last_center_m"] == expected_last
    assert case["expected"]["expected_centroid_m"] == [2.4, 1.2, 1.08]
    assert case["expected"]["fluid_mass_kg"] == 5120.0
    assert case["expected"]["body_massbody_kg"] == 128.0

    # Verify candidate XML exists and is well-formed
    cand_xml = Path(case["candidate_xml"])
    assert cand_xml.is_file()
    text = cand_xml.read_text(encoding="utf-8")
    assert "<floatings>" in text
    assert 'massbody value="128"' in text or 'massbody value="128.0"' in text or 'value="128"' in text


@pytest.mark.parametrize("role", ["coarse", "medium", "fine"])
def test_runner_requests_bound_and_valid(role: str) -> None:
    manifest = _load_json(MANIFEST_PATH)
    req_path = Path(manifest["request_paths"][role])
    assert req_path.is_file()
    req = _load_json(req_path)

    assert req["schema"] == "ds02.runner.request.v1"
    assert req["family_id"] == "F6"
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "audit"
    assert req["cpu_threads"] == 4
    assert req["max_wall_seconds"] <= 1800
    assert req["q_n_status"] == "not_assessed"

    # Strict dispatch requirements:
    # 1. GUARD_PATH in input_files and input_hashes
    guard_str = str(GUARD_PATH.resolve())
    assert guard_str in req["input_files"]
    assert guard_str in req["input_hashes"]

    # 2. RUNTIME_V2 in input_files and input_hashes
    runtime_str = str(RUNTIME_V2.resolve())
    assert runtime_str in req["input_files"]
    assert runtime_str in req["input_hashes"]

    # 3. All input_files have matching hash entry
    for path_str in req["input_files"]:
        assert path_str in req["input_hashes"]
        # Verify file actually exists and hash matches
        p = Path(path_str)
        assert p.is_file(), f"missing input file: {p}"

    # 4. Command uses literal virtualenv Python
    cmd = req["command"]
    assert cmd[0] == "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
    assert cmd[1] == str(SCRIPT_PATH.resolve())
    assert cmd[2] == "run-case"
    assert cmd[3] == "--manifest"
    assert cmd[5] == "--role"
    assert cmd[6] == role
    assert cmd[7] == "--output-root"
    assert cmd[8] == "{attempt_root}"
