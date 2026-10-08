from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_task_split_audit_v2.py"
spec = importlib.util.spec_from_file_location("task_split_audit_v2", SCRIPT)
assert spec and spec.loader
AUDIT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AUDIT)


def test_nested_binding_accepts_actual_proof_object_and_checks_sha(tmp_path: Path) -> None:
    nested = tmp_path / "output.json"
    nested.write_text('{"status":"accounting-only"}\n', encoding="utf-8")
    digest = hashlib.sha256(nested.read_bytes()).hexdigest()
    path, actual = AUDIT._nested_binding(
        {"path": str(nested), "sha256": digest}, None, "proof output"
    )
    assert path == nested.resolve()
    assert actual == digest
    with pytest.raises(AUDIT._BASE.TaskSplitError, match="digest differs"):
        AUDIT._nested_binding(
            {"path": str(nested), "sha256": "0" * 64}, None, "proof output"
        )


@pytest.mark.skipif(
    not Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/"
        "v19-source-closure/CURRENT336-effective-lineage-audit-v19-source-closure.json"
    ).is_file(),
    reason="primary task-split evidence sources are not mounted",
)
def test_actual_make_request_binds_nested_impact_paths_without_h5(tmp_path: Path) -> None:
    current = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
    lineage = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/"
        "v19-source-closure/CURRENT336-effective-lineage-audit-v19-source-closure.json"
    )
    source_index = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v22-source-proof/"
        "SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V22.json"
    )
    evidence = ROOT / "campaigns/ds-data-02/stage2/requests/current336-task-split-evidence-v1.json"
    runtime_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    worker_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics")
    runtime_paths = [
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
    ]
    request = AUDIT.make_request(
        current, lineage, source_index, evidence, tmp_path / "request.json", worker_root,
        runtime_paths=runtime_paths,
    )
    assert request["family_id"] == "infra"
    assert request["dataset_families"] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    assert request["launch_allowed"] is True
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert request["nested_evidence_bindings"]
    impact_roles = {
        row["role"] for row in request["nested_evidence_bindings"]
        if row["evidence_id"] == "all118_impact_v8"
    }
    assert impact_roles == {"output", "receipt"}
    assert all(Path(path).is_file() for path in request["input_files"])
    assert len(request["input_files"]) == len(request["input_sha256"])
