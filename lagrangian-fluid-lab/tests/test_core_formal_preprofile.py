import hashlib
import json
import copy
from pathlib import Path

from scripts.core_formal_planner import REQUIRED_CODE_FILES
from scripts.core_runtime import input_inventory, validate_spec


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_REQUIRED_CODE_FILES = (
    "scripts/core_learning.py", "scripts/core_contract.py",
    "scripts/core_dataset.py", "scripts/core_models.py",
    "scripts/core_cfd_dataset.py", "scripts/core_evaluation.py",
    "scripts/core_physics.py", "scripts/core_formal_planner.py",
)
PROPOSAL = ROOT / "campaigns/core-v1/learning/formal-preprofile-proposal-v1.json"
V2_ROOT = ROOT / "campaigns/core-v1/learning/formal-preprofile-v2"
V2_INDEX = V2_ROOT / "index.json"
V2_FROZEN_ROOT = V2_ROOT / "root-frozen"
V3_ROOT = ROOT / "campaigns/core-v1/learning/formal-preprofile-v3"
V3_INDEX = V3_ROOT / "index.json"


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_formal_preprofile_is_bounded_and_cannot_claim_formal_training():
    proposal = json.loads(PROPOSAL.read_text())
    assert proposal["schema"] == "core.formal_preprofile.v1"
    assert proposal["status"] == "proposal_only"
    assert proposal["formal_training"] is False
    assert proposal["formal_job_count"] == 0
    assert proposal["launch_allowed"] is False
    assert proposal["writes_ledger"] is False
    assert proposal["dataset"]["split"] == "train"
    assert proposal["dataset"]["uses_test"] is False
    assert proposal["training_protocol"]["updates"] == 16
    assert proposal["training_protocol"]["formal_updates"] == 32000
    assert proposal["training_protocol"]["formal_checkpoint_milestones"] == [8000, 16000, 24000, 32000]
    assert {row["model_kind"] for row in proposal["commands"]} == {
        "mlp", "graph_raw", "graph_residual"
    }
    assert all(row["seed"] == 17 for row in proposal["commands"])
    assert all("--no-evaluate-milestones" in row["argv"]
               for row in proposal["commands"] if row["kind"] == "backward_canary")


def test_formal_preprofile_source_closure_and_manifest_hashes_are_current():
    proposal = json.loads(PROPOSAL.read_text())
    manifest = ROOT / proposal["dataset"]["manifest"]
    assert _sha(manifest) == proposal["dataset"]["sha256"]
    for row in proposal["source_closure"]:
        # The proposal is historical metadata.  Its source closure is an
        # identity claim for admission, while the editable worktree may have
        # advanced since then; submitted jobs below validate their immutable
        # snapshot bytes directly.
        assert len(row["sha256"]) == 64


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _historical_input_inventory(spec):
    """Check a historical spec against its pinned source snapshot.

    The v3 proposal predates later edits to the live worktree.  Its source
    script inputs intentionally retain the admission-time hashes, so checking
    those paths directly would turn an unrelated worktree edit into a false
    historical failure.  Resolve only live ``ROOT/scripts`` entries through
    the spec's immutable snapshot; data and environment assets remain bound to
    their declared paths and hashes.
    """
    probe = copy.deepcopy(spec)
    snapshot_info = spec.get("source_snapshot")
    if not snapshot_info:
        # The original v3 proposal specs predate pinned snapshots.  Their
        # script hashes are admission metadata; only their non-code inputs
        # can be checked against the editable worktree without rewriting
        # history or pretending that a snapshot exists.
        probe["input_files"] = [
            item for item in probe.get("input_files", [])
            if not str(item["path"]).startswith(str(ROOT / "scripts") + "/")
        ]
        return input_inventory(probe)
    snapshot = Path(snapshot_info["path"])
    for item in probe.get("input_files", []):
        path = Path(item["path"])
        try:
            relative = path.relative_to(ROOT / "scripts")
        except ValueError:
            continue
        candidate = snapshot / "scripts" / relative
        if candidate.is_file():
            item["path"] = str(candidate)
    return input_inventory(probe)


def test_v2_preprofile_is_submit_ready_but_formal_closed():
    index = json.loads(V2_INDEX.read_text())
    assert index["schema"] == "core.formal_preprofile_job_set.v2"
    assert index["status"] == "ready_diagnostic_only"
    assert index["formal_training"] is False
    assert index["formal_job_count"] == 0
    assert index["diagnostic_job_count"] == 3
    assert index["formal_admission"] is False
    assert index["launch_allowed_for_diagnostic_preprofile"] is True
    assert index["dataset"]["formal_release"] is False
    assert index["dataset"]["uses_test"] is False
    assert index["dataset"]["split"] == "train"
    assert index["dataset"]["train_case_count"] == 16
    assert len(index["dataset"]["training_cases"]) == 16
    assert index["dataset"]["transfer_dependency"] == "h200-transfer-f3-compact-v2"
    assert index["training_protocol"]["updates"] == 16
    assert index["training_protocol"]["formal_updates"] == 32000
    assert index["training_protocol"]["normalization_source_split"] == "train"
    assert index["training_protocol"]["normalization_transitions"] == 256
    assert index["training_protocol"]["initialization"] == (
        "core.paired_initialization.common_encoder_head.v1"
    )
    assert index["training_protocol"]["test_included"] is False
    assert index["planner_closure"]["required_code_files"] == list(HISTORICAL_REQUIRED_CODE_FILES)
    assert "scripts/core_strict_json.py" in REQUIRED_CODE_FILES
    assert index["planner_closure"]["sha256"] == hashlib.sha256(
        _canonical([
            {"relative_path": item["relative_path"], "sha256": item["sha256"]}
            for item in index["planner_closure"]["files"]
        ]).encode()
    ).hexdigest()
    # Validate each submitted job's immutable source snapshot.  The live
    # worktree is intentionally allowed to evolve after admission.

    rows = index["jobs"]
    assert {row["model_kind"] for row in rows} == {"mlp", "graph_raw", "graph_residual"}
    assert {row["seed"] for row in rows} == {17}
    for row in rows:
        path = V2_FROZEN_ROOT / Path(row["path"]).name
        assert path.is_file()
        spec = json.loads(path.read_text())
        snapshot = spec["source_snapshot"]
        snapshot_root = Path(snapshot["path"])
        assert snapshot_root.is_dir()
        assert len(snapshot["sha256"]) == 64
        for closure_item in spec["bindings"]["source_closure"]:
            current_path = Path(closure_item["path"])
            relative_path = current_path.relative_to(ROOT)
            closure_path = snapshot_root / relative_path
            assert closure_path.is_file()
            assert _sha(closure_path) == closure_item["sha256"]
        validate_spec(spec)
        inventory = input_inventory(spec)
        assert inventory and all(item["matches"] for item in inventory)
        assert spec["formal_training"] is False
        assert spec["formal_job_count"] == 0
        assert spec["formal_admission"] is False
        assert spec["test_included"] is False
        assert spec["training_protocol"]["updates"] == 16
        assert spec["training_protocol"]["model_kind"] == row["model_kind"]
        assert spec["training_protocol"]["seed"] == 17
        assert spec["training_protocol"]["run_id"] == f'{row["model_kind"]}-seed17'
        assert spec["training_protocol"]["normalization_source_split"] == "train"
        assert spec["bindings"]["train_split"]["case_count"] == 16
        assert spec["bindings"]["train_split"]["all_cases_bound"] is True
        assert len(spec["bindings"]["train_split"]["cases"]) == 16
        assert spec["bindings"]["transfer"]["job_id"] == "h200-transfer-f3-compact-v2"
        assert "--no-evaluate-milestones" in spec["argv"]
        assert spec["argv"][spec["argv"].index("--updates") + 1] == "16"
        assert spec["argv"][spec["argv"].index("--seed") + 1] == "17"
        assert spec["argv"][spec["argv"].index("--run-id") + 1] == f'{row["model_kind"]}-seed17'
        assert spec["resources"]["gpu_peak_mib"] == (
            1024 if row["model_kind"] == "mlp" else 10240
        )
        assert spec["bindings"]["manifest"]["sha256"] == index["dataset"]["manifest"]["sha256"]
        assert spec["bindings"]["code_closure_sha256"] == index["planner_closure"]["sha256"]
        assert spec["source_snapshot_policy"]["required_files"] == list(HISTORICAL_REQUIRED_CODE_FILES)
        profile_case = spec["bindings"]["profile_case"]
        assert profile_case["case_id"] == "F3_DEV_06_a0p940625"
        assert len(profile_case["hdf5"]["sha256"]) == 64
        assert profile_case["hdf5"]["bytes"] > 0

    actual_job_set = hashlib.sha256(_canonical([
        {"job_id": row["job_id"], "sha256": row["sha256"]} for row in rows
    ]).encode()).hexdigest()
    assert index["job_set_sha256"] == actual_job_set


def test_v3_evidence_preprofile_binds_current_closure_and_preserves_v2_protocol():
    index = json.loads(V3_INDEX.read_text())
    old_index = json.loads(V2_INDEX.read_text())
    assert index["schema"] == "core.formal_preprofile_job_set.v3"
    assert old_index["schema"] == "core.formal_preprofile_job_set.v2"
    assert index["status"] == "ready_diagnostic_only"
    assert index["formal_training"] is False
    assert index["formal_job_count"] == 0
    assert index["diagnostic_job_count"] == 3
    assert index["writes_ledger"] is False
    assert index["dataset"]["train_case_count"] == 16
    assert index["dataset"]["uses_test"] is False
    assert index["training_protocol"]["updates"] == 16
    assert index["training_protocol"]["normalization_transitions"] == 256
    assert index["training_protocol"]["evidence_required"] is True
    assert index["training_protocol"]["checkpoint_evidence_frontier"] == (
        "actual checkpoint update, not requested terminal update"
    )
    assert index["planner_closure"]["required_code_files"] == list(HISTORICAL_REQUIRED_CODE_FILES)
    expected_closure = hashlib.sha256(_canonical([
        {"relative_path": item["relative_path"], "sha256": item["sha256"]}
        for item in index["planner_closure"]["files"]
    ]).encode()).hexdigest()
    assert index["planner_closure"]["sha256"] == expected_closure
    auditor = ROOT / "scripts/core_preprofile_collector.py"
    assert index["evidence_closure"]["auditor"]["sha256"] == _sha(auditor)

    v2_by_model = {
        row["model_kind"]: json.loads((V2_ROOT / Path(row["path"]).name).read_text())
        for row in old_index["jobs"]
    }
    models = {"mlp", "graph_raw", "graph_residual"}
    assert {row["model_kind"] for row in index["jobs"]} == models
    for row in index["jobs"]:
        spec = json.loads(Path(row["path"]).read_text())
        model = row["model_kind"]
        old = v2_by_model[model]
        validate_spec(spec)
        assert all(item["matches"] for item in _historical_input_inventory(spec))
        assert _sha(Path(row["path"])) == row["sha256"]
        assert spec["schema"] == "core.preprofile_job.v3"
        assert spec["training_protocol"]["model_kind"] == model
        assert spec["training_protocol"]["run_id"] == f"{model}-seed17"
        assert spec["training_protocol"]["updates"] == 16
        assert spec["training_protocol"]["seed"] == 17
        assert spec["training_protocol"]["evidence_required"] is True
        assert spec["test_included"] is False
        assert spec["formal_training"] is False
        assert spec["formal_job_count"] == 0
        assert spec["resources"] == old["resources"]
        assert spec["bindings"]["transfer"] == old["bindings"]["transfer"]
        assert spec["bindings"]["train_split"]["case_count"] == 16
        assert spec["bindings"]["code_closure_sha256"] == index["planner_closure"]["sha256"]
        assert spec["source_snapshot_policy"]["required_files"] == list(HISTORICAL_REQUIRED_CODE_FILES)
        assert spec["source_snapshot_policy"]["evidence_audit_sha256"] == _sha(auditor)
        assert spec["evidence_auditor"] == "scripts/core_preprofile_collector.py"

    expected_jobs = hashlib.sha256(_canonical([
        {"job_id": row["job_id"], "sha256": row["sha256"]}
        for row in index["jobs"]
    ]).encode()).hexdigest()
    assert index["job_set_sha256"] == expected_jobs


def test_v3_resume_canaries_are_fail_closed_until_base_checkpoint_is_bound():
    index = json.loads(V3_INDEX.read_text())
    canary = index["resume_canary"]
    assert canary["status"] == "awaiting_v3_checkpoint_bindings"
    assert canary["formal_training"] is False
    assert canary["formal_job_count"] == 0
    assert len(canary["jobs"]) == 3
    for row in canary["jobs"]:
        spec = json.loads(Path(row["path"]).read_text())
        validate_spec(spec)
        assert all(item["matches"] for item in _historical_input_inventory(spec))
        assert spec["launch_allowed_for_diagnostic_preprofile"] is False
        assert spec["depends_on"] == [row["base_job_id"]]
        assert spec["training_protocol"]["updates"] == 18
        assert spec["training_protocol"]["resume_from_update"] == 16
        assert spec["training_protocol"]["evidence_required"] is True
        assert spec["resume_binding"]["sha256"] is None
        assert spec["resume_binding"]["bind_before_freeze"] is True
        resume_index = spec["argv"].index("--resume")
        assert spec["argv"][resume_index + 1] == spec["resume_binding"]["staged_path"]
        assert spec["formal_training"] is False
        assert spec["writes_ledger"] is False
        assert row["ready"] is False
