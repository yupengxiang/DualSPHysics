"""Primary ROOT191 builder tests against the real main-worktree metadata."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_root191_v3_primary_builder.py"
MAIN_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
MAIN_STAGE2 = MAIN_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"


def _load():
    spec = importlib.util.spec_from_file_location("root191_primary_builder_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_inputs():
    paths = [
        MAIN_STAGE2 / "requests/f2-root200-profile-output-fresh-proof-root-prepared-200-001/root200-profile-proof-request.json",
        MAIN_STAGE2 / "requests/f2-root200-profile-output-fresh-proof-root-forward-200-001.json",
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/f2-s1-root200-v14-profile-output-001-root-forward-030-001/execution-receipt.json"),
        MAIN_STAGE2 / "checkpoints/F2_FRESH_V16_PROFILE_OUTPUT_ROOT_PROOF_V12_ACTUAL_ROOT_VERIFICATION_200.json",
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/f2-s1-root200-v14-profile-output-001-root-forward-030-001/fresh-v16-proof-v12.json"),
        MAIN_STAGE2 / "requests/f2-s1-root145-v66-root179c-primary-prepared-003.json",
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/f2-s1-v66-root179c-003/actual-returned-parent-report.json"),
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/f2-s1-v66-root179c-003/execution-receipt.json"),
        MAIN_STAGE2 / "checkpoints/F2_ROOT179C_V66_ACTUAL_CONVERSION_LABEL_INTERFACE_ROOT_VERIFICATION.json",
        MAIN_STAGE2 / "replay/v15/f2-s1-replay-request-v15-001.json",
    ]
    return paths


def test_real_primary_build_uses_main_root_and_actual_v15(tmp_path: Path):
    if not all(path.is_file() for path in _real_inputs()):
        pytest.skip("ROOT200/179C metadata is not mounted")
    builder = _load()
    output = tmp_path / "root191-v3-primary.json"
    value = builder.build_primary(
        output=output,
        fresh_output_root=tmp_path / "STAGE2_F2_ROOT191_V3_PRIMARY_FRESH",
        case_id="f2-s1-root191-v3-primary-test",
        attempt_id="f2-s1-root191-v3-primary-test-root-forward-030-001",
    )
    assert value["payload_read"] is False
    checked = builder.validate_primary(output)
    assert checked["status"] == "ROOT191_V3_PRIMARY_METADATA_VALIDATED_READY_FOR_PARENT"
    request = builder._json(output, "request")
    assert request["root191_primary_builder"]["main_worktree_root"] == str(MAIN_ROOT)
    assert request["source_frozen_request"]["schema"] == "ds02.stage2.f2-s1-replay-request.v15"
    assert request["root191_primary_builder"]["v15_lineage"]["outer_v66_request_used_as_frozen_v15"] is False
    assert request["execution"]["python_executable"] == str(builder.LITERAL_VENV)
    assert not (tmp_path / "STAGE2_F2_ROOT191_V3_PRIMARY_FRESH").exists()


def test_v66_outer_request_cannot_be_frozen_v15(tmp_path: Path):
    builder = _load()
    with pytest.raises(builder.PrimaryBuilderError, match="frozen replay input must be the actual V15"):
        builder._v15_lineage(builder.PRODUCER_REQUEST, builder.PRODUCER_REQUEST)

