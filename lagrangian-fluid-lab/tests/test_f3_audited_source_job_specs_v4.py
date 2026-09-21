from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "campaigns/core-v1/material/evidence/f3-native-mls-audited-source-job-specs-v4-prepared-adapter-20260920.json"
JOB_DIR = ROOT / "campaigns/core-v1/material/jobs/f3-native-mls-audited-adapter-v1"
ADAPTER = ROOT / "scripts/core_f3_native_volume_mls_prepared_adapter_v1.py"


def test_v4_specs_use_fresh_adapter_snapshot_and_pinned_backend() -> None:
    bundle = json.loads(BUNDLE.read_text())
    assert [item["matrix_row"] for item in bundle["configs"]] == [16, 17, 18, 19, 20, 21, 22, 23, 29, 31]
    adapter_hash = hashlib.sha256(ADAPTER.read_bytes()).hexdigest()
    assert bundle["prepared_adapter"]["sha256"] == adapter_hash
    for item in bundle["configs"]:
        spec_path = ROOT / Path(item["path"]).relative_to(ROOT)
        spec = json.loads(spec_path.read_text())
        assert "source_snapshot" not in spec
        assert spec["freeze_policy"]["entrypoint"] == "fresh_snapshot_required"
        assert spec["freeze_policy"]["entrypoint_sha256"] == adapter_hash
        assert "PYTHONPATH" not in spec["env"]
        pinned = spec["freeze_policy"]["backend_snapshot_pinned"]
        assert "d4eb3d7d125c8753" in pinned["path"]
        assert pinned["sha256"] == "cd1c050757df7b0d5832181464d446cf6e8c678e2b150aa07bae0ddb0ee3b5f9"
        roles = {entry["role"] for entry in spec["input_files"]}
        assert {
            "versioned_prepared_adapter_v1",
            "frozen_material_runner_v2",
            "prepared_candidate_definition_xml",
            "terminal_audited_native_source",
            "terminal_prepared_record",
            "independent_source_audit_v2",
            "terminal_source_worker_receipt",
            "audited_matrix_manifest",
        } <= roles
        assert "--backend-script" in spec["argv"]
        assert spec["resources"]["gpu_peak_mib"] == 0
        assert spec["central_ledger_mutation"] == 0
        assert all("result.json" not in output for output in spec["required_outputs"])


def test_v4_specs_keep_4096_s4_timeout_bound() -> None:
    bundle = json.loads(BUNDLE.read_text())
    for item in bundle["configs"]:
        if item["matrix_row"] in (29, 31):
            assert item["timeout_seconds"] == 24000
            assert item["estimate"]["method"].startswith("2.0x the measured 4096-seed s2")
