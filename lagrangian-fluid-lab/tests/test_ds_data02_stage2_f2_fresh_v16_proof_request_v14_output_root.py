"""ROOT200 V14 output-root rebinding tests.

The real ROOT197 request and copied V66 worker metadata are reused only as
bounded source metadata.  The test proves V8/V12 preflight sees the new
ROOT200 output root while the producer result root remains unchanged.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_request_v14_output_root.py"
ROOT194 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f2-root194-v67-fresh-proof-root-prepared-194-002/root194-proof-request.json"
)
WORKER = Path(
    "/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/"
    "bundle-target/runtime/native/f2-s1-v64-worker-request.json"
)


def load_module():
    spec = importlib.util.spec_from_file_location("root200_v14_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load_module()


@pytest.mark.skipif(not ROOT194.is_file() or not WORKER.is_file(),
                    reason="ROOT194/V66 source metadata is not mounted")
def test_real_root200_output_root_rebind_passes_v8_v12_preflight(tmp_path: Path):
    sidecar = tmp_path / "root200-sidecar.json"
    request = tmp_path / "root200-request.json"
    output_root = tmp_path / "STAGE2_F2_ROOT200_FRESH_PROOF"
    result = S.build_request(
        root194_request=ROOT194,
        producer_worker_request=WORKER,
        sidecar_output=sidecar,
        output=request,
        case_id="STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009",
        attempt_id="f2-s1-root200-v14-profile-output-001",
        fresh_output_root=output_root,
    )
    assert result["payload_read"] is False
    value = json.loads(request.read_text(encoding="utf-8"))
    assert value["relocation"]["output_root"] == str(output_root.resolve())
    assert value["relocation"]["target_root"] != value["relocation"]["output_root"]
    assert value["relocation"]["proof_output_root_binding"]["proof_output_only"] is True
    checked = S.validate_request(request)
    assert checked["status"] == "ROOT200_PROFILE_OUTPUT_ROOT_METADATA_VALIDATED_READY_FOR_PARENT"
    assert checked["fresh_output_root"] == str(output_root.resolve())
    assert not output_root.exists()


def test_root200_rejects_broad_or_old_output_root(tmp_path: Path):
    with pytest.raises(S.OutputRootRebindError, match="ROOT200"):
        S._root200("/home/jade", "output root")
    with pytest.raises(S.OutputRootRebindError, match="ROOT200"):
        S._root200("/var/tmp/STAGE2_F2_ROOT197_OLD", "output root")
