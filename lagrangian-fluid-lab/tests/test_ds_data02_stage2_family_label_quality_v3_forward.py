from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_label_quality_v3_forward.py"
spec = importlib.util.spec_from_file_location("family_label_quality_v3_forward", SCRIPT)
assert spec and spec.loader
QUALITY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(QUALITY)


def test_cross_family_request_uses_runtime_infra_namespace() -> None:
    entries = [
        {"family_id": "F1", "physical_case_id": "one"},
        {"family_id": "F5", "physical_case_id": "two"},
    ]
    runtime_family, case_id, families = QUALITY._request_identity(entries)
    assert runtime_family == "infra"
    assert case_id == "DS02_STAGE2_FAMILY_LABEL_QUALITY_V3_F1_F5"
    assert families == ["F1", "F5"]
    assert QUALITY._attempt_id(families) == "family-label-quality-v3-f1-f5-forward-002"


def test_single_family_request_retains_runtime_family() -> None:
    runtime_family, case_id, families = QUALITY._request_identity([
        {"family_id": "F4", "physical_case_id": "anchor"},
    ])
    assert runtime_family == "F4"
    assert case_id.endswith("_F4")
    assert families == ["F4"]


@pytest.mark.skipif(
    not Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "family-label-quality-v3/f1-f5-source-role-manifest-forward-001.json"
    ).is_file(),
    reason="forward F1-F5 manifest is not mounted",
)
def test_actual_f1_f5_manifest_has_explicit_source_roles_and_chord_boundary() -> None:
    path = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "family-label-quality-v3/f1-f5-source-role-manifest-forward-001.json"
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["family_id"] for entry in manifest["entries"]] == ["F1", "F2", "F3", "F4", "F5"]
    assert {entry["source_role"] for entry in manifest["entries"]} == {
        "native_initial_mk", "initial_spatial_region"
    }
    assert all(entry["producer_receipt_sha256"] for entry in manifest["entries"])
    assert all(entry["label_semantics"]["saved_frame_chords"] is True for entry in manifest["entries"])
    assert manifest["label_semantics_policy"]["continuous_first_arrival"] == "UNKNOWN"
    assert manifest["label_semantics_policy"]["hidden_recrossings"] == "UNKNOWN"


@pytest.mark.skipif(
    not Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
    ).is_file(),
    reason="forward F1-F7 manifest is not mounted",
)
def test_actual_f1_f7_manifest_has_complete_family_scope() -> None:
    path = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["family_id"] for entry in manifest["entries"]] == [
        "F1", "F2", "F3", "F4", "F5", "F6", "F7"
    ]
    assert manifest["coverage"]["pending_families"] == []
    assert manifest["coverage"]["qualification_credit"] == "none"
    assert manifest["label_semantics_policy"]["physical_fate"] == "UNKNOWN"


@pytest.mark.skipif(
    not (
        Path(
            "/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/"
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
            "family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
        ).is_file()
        and Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
                 "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py").is_file()
    ),
    reason="actual F1-F7 manifest or root v8 sources are not mounted",
)
def test_actual_make_request_binds_seven_scope_without_h5_prepare_hash(tmp_path: Path) -> None:
    manifest = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
    )
    runtime_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    worker_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics")
    request = QUALITY.make_request(manifest, tmp_path / "request.json", runtime_root, worker_root)
    assert request["family_id"] == "infra"
    assert request["dataset_families"] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    assert request["attempt_id"].endswith("f1-f2-f3-f4-f5-f6-f7-forward-002")
    assert request["launch_allowed"] is True
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert len(request["entries"]) == 7
    assert len(request["input_files"]) == len(request["input_sha256"])
    assert all(Path(path).is_file() for path in request["input_files"])
    label_inputs = [path for path in request["input_files"] if path.endswith("native-labels.h5")]
    assert len(label_inputs) == 6  # F2's recovered product has its historical H5 filename.
    assert request["command"][1].startswith(str(worker_root))
