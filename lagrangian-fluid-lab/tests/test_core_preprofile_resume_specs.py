import hashlib
import json
from pathlib import Path

from scripts.core_runtime import input_inventory, validate_spec


ROOT = Path(__file__).resolve().parents[1]
RESUME_ROOT = ROOT / "campaigns/core-v1/learning/formal-preprofile-v3/resume-canary-v1"
CONTROL_ROOT = ROOT / "campaigns/core-v1/learning/formal-preprofile-v3/continuous-control"
RESUME_V2_ROOT = ROOT / "campaigns/core-v1/learning/formal-preprofile-v3/resume-canary-v2"
CONTROL_V2_ROOT = ROOT / "campaigns/core-v1/learning/formal-preprofile-v3/continuous-control-v2"
FROZEN_ROOT = ROOT / "campaigns/core-v1/learning/formal-preprofile-v3/root-frozen"
POST_FIX_SNAPSHOT_SHA = "1180503728c33e2180ca7c86d25a585a7cad6634ecdc9f4c9beefe3b1600d58d"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_ready_resume_canaries_bind_real_v3_checkpoints_and_frozen_source():
    index = json.loads((RESUME_ROOT / "index.json").read_text())
    assert index["schema"] == "core.preprofile_resume_canary_set.v1"
    assert index["status"] == "ready_diagnostic_only"
    assert index["formal_training"] is False
    assert index["formal_job_count"] == 0
    assert index["submitted"] is False
    assert len(index["jobs"]) == 3
    for row in index["jobs"]:
        spec = json.loads(Path(row["path"]).read_text())
        validate_spec(spec)
        assert all(item["matches"] for item in input_inventory(spec))
        assert _sha(Path(row["path"])) == row["sha256"]
        assert spec["source_snapshot"]["sha256"] == index["source_snapshot"]["sha256"]
        assert spec["training_protocol"]["updates"] == 18
        assert spec["training_protocol"]["resume_from_update"] == 16
        assert spec["training_protocol"]["run_id"] == f"{row['model_kind']}-seed17"
        assert spec["launch_allowed_for_diagnostic_preprofile"] is True
        assert spec["formal_training"] is False
        assert spec["writes_ledger"] is False
        assert spec["resume_binding"]["immutable_copy_verified"] is True
        assert spec["resume_binding"]["sha256"] == row["checkpoint"]["sha256"]
        staged = Path(spec["resume_binding"]["staged_path"])
        assert staged.is_file()
        assert _sha(staged) == spec["resume_binding"]["sha256"]
        assert any(item["path"] == str(staged) and item["sha256"] == _sha(staged)
                   for item in spec["input_files"])


def test_continuous_controls_are_unsubmitted_same_snapshot_diagnostics():
    index = json.loads((CONTROL_ROOT / "index.json").read_text())
    assert index["schema"] == "core.preprofile_continuous_control_set.v1"
    assert index["status"] == "prepared_not_submitted"
    assert index["formal_training"] is False
    assert index["formal_job_count"] == 0
    assert index["submitted"] is False
    assert len(index["jobs"]) == 3
    for row in index["jobs"]:
        spec = json.loads(Path(row["path"]).read_text())
        frozen = json.loads((FROZEN_ROOT / f"h200-core-preprofile-{row['model_kind']}-seed17-v3.json").read_text())
        validate_spec(spec)
        assert all(item["matches"] for item in input_inventory(spec))
        assert _sha(Path(row["path"])) == row["sha256"]
        assert spec["source_snapshot"] == frozen["source_snapshot"]
        assert spec["training_protocol"]["updates"] == 18
        assert spec["training_protocol"]["run_id"] == f"{row['model_kind']}-seed17"
        assert spec["launch_allowed_for_diagnostic_preprofile"] is False
        assert spec["formal_training"] is False
        assert spec["writes_ledger"] is False
        assert "--resume" not in spec["argv"]
        assert spec["continuous_control"]["terminal_update"] == 18


def test_post_fix_resume_canaries_bind_new_snapshot_and_rng_restore_contract():
    index = json.loads((RESUME_V2_ROOT / "index.json").read_text())
    assert index["schema"] == "core.preprofile_resume_canary_set.v2"
    assert index["status"] == "ready_diagnostic_only"
    assert index["source_snapshot"]["sha256"] == POST_FIX_SNAPSHOT_SHA
    assert index["formal_training"] is False
    assert index["formal_job_count"] == 0
    assert index["diagnostic_job_count"] == 3
    assert index["submitted"] is False
    assert index["writes_ledger"] is False
    assert {row["job_id"].rsplit("-", 1)[-1] for row in index["jobs"]} == {"v3"}
    for row in index["jobs"]:
        spec_path = Path(row["path"])
        spec = json.loads(spec_path.read_text())
        validate_spec(spec)
        assert all(item["matches"] for item in input_inventory(spec))
        assert _sha(spec_path) == row["sha256"]
        assert spec["schema"] == "core.preprofile_resume_canary.v2"
        assert spec["source_snapshot"]["sha256"] == POST_FIX_SNAPSHOT_SHA
        assert spec["launch_allowed_for_diagnostic_preprofile"] is True
        assert spec["resume_rng_restore"] == {
            "schema": "core.training.rng_restore.v2",
            "cpu_byte_tensor_before_torch_set_rng_state": True,
            "cuda_state_sequence_cpu_normalized_before_set_rng_state_all": True,
            "purpose": "resume after map_location=cuda must restore serialized RNG bytes without device type errors",
        }
        assert spec["training_protocol"]["resume_rng_restore"] == spec["resume_rng_restore"]
        assert spec["resume_binding"]["immutable_copy_verified"] is True
        staged = Path(spec["resume_binding"]["staged_path"])
        assert staged.is_file()
        assert _sha(staged) == spec["resume_binding"]["sha256"]
        assert len(spec["input_files"]) == 19
        assert any(item["path"] == str(staged) and item["sha256"] == _sha(staged)
                   for item in spec["input_files"])


def test_post_fix_continuous_controls_bind_actual_v3_recovery_specs():
    index = json.loads((CONTROL_V2_ROOT / "index.json").read_text())
    resume_index = json.loads((RESUME_V2_ROOT / "index.json").read_text())
    assert index["schema"] == "core.preprofile_continuous_control_set.v2"
    assert index["status"] == "ready_diagnostic_only"
    assert index["source_snapshot"]["sha256"] == POST_FIX_SNAPSHOT_SHA
    assert index["resume_canary_index"] == str(RESUME_V2_ROOT / "index.json")
    assert index["resume_canary_index_sha256"] == _sha(RESUME_V2_ROOT / "index.json")
    assert index["launch_allowed_for_diagnostic_preprofile"] is True
    assert index["diagnostic_job_count"] == 3
    assert index["formal_job_count"] == 0
    assert index["submitted"] is False
    assert index["writes_ledger"] is False
    resume_by_model = {row["model_kind"]: row["job_id"] for row in resume_index["jobs"]}
    for row in index["jobs"]:
        spec_path = Path(row["path"])
        spec = json.loads(spec_path.read_text())
        validate_spec(spec)
        assert all(item["matches"] for item in input_inventory(spec))
        assert _sha(spec_path) == row["sha256"]
        model = row["model_kind"]
        expected_resume = resume_by_model[model]
        assert spec["schema"] == "core.preprofile_continuous_control.v2"
        assert spec["launch_allowed_for_diagnostic_preprofile"] is True
        assert spec["source_snapshot"]["sha256"] == POST_FIX_SNAPSHOT_SHA
        assert spec["continuous_control"]["resume_canary_job_id"] == expected_resume
        assert spec["continuous_control"]["resume_canary_index_sha256"] == index["resume_canary_index_sha256"]
        assert spec["training_protocol"]["continuous_control_for"]["resume_canary_job_id"] == expected_resume
        assert "--resume" not in spec["argv"]
        assert len(spec["input_files"]) == 18
        assert spec["formal_training"] is False
        assert spec["formal_job_count"] == 0
        assert spec["writes_ledger"] is False
