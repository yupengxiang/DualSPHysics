from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_full_goal_edge_link_correction_v2.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "full-goal-edge-link-correction-v2-root-prepared-168-001/"
    / "full-goal-edge-link-correction-v2-manifest.json"
)
REQUEST = MANIFEST.with_name("full-goal-edge-link-correction-v2-request.json")
ROOT133_TERMINAL_SHA = "5d459c01728e83178903695b39f131b1c0b9ea30293454454c6c8c17f7be4706"
ROOT133_RECEIPT_SHA = "10df2f69977034ca3be8d6b7fd388bd7a565049af1c225a78f9937bc7ef8cc75"
ROOT140_TERMINAL_SHA = "0e0f868d3eb9b18c8e067eaac1392e35590837c4bb558294f49c5b54bd3749f1"
ROOT140_RECEIPT_SHA = "2da203a0a03192d70a18817c1b6b9e4ae02a533415bdd9f1d4e98beb8b1d31c6"


def module():
    spec = importlib.util.spec_from_file_location("edge_link_correction_v2", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_historical_launches_use_same_attempt_terminal_proof_and_receipt() -> None:
    result = module().build(MANIFEST, Path("/tmp/unused-edge-link-correction-v2.json"))
    assert result["schema"] == "ds02.stage2.full-goal-rollup.edge-link-correction.v2"
    assert result["status"] == "CORRECTED_EDGE_LINKS_SOURCE_BOUND_NO_NEW_SCIENCE"

    root133 = result["historical_edges"]["ROOT133"]
    assert root133["same_attempt"] is True
    assert root133["terminal_source"]["sha256"] == ROOT133_TERMINAL_SHA
    assert root133["terminal_source"]["receipt_status"] == "COMPLETED_DEVELOPMENT_UNKNOWN"
    assert root133["terminal_source"]["receipt"]
    assert root133["old_root159_terminal_alias"]["node"] == "ROOT150"
    assert root133["old_root159_terminal_alias"]["same_attempt"] is False

    root140 = result["historical_edges"]["ROOT140"]
    assert root140["same_attempt"] is True
    assert root140["terminal_source"]["sha256"] == ROOT140_TERMINAL_SHA
    assert root140["terminal_source"]["receipt_status"] == "FAILED_PARENT_EXECUTOR"
    assert root140["terminal_source"]["receipt"]
    assert root140["old_root159_terminal_alias"]["node"] == "ROOT145"
    assert root140["old_root159_terminal_alias"]["same_attempt"] is False


def test_later_attempts_remain_independent_and_no_science_credit() -> None:
    result = module().build(MANIFEST, Path("/tmp/unused-edge-link-correction-v2-b.json"))
    independent = result["independent_edges"]
    assert independent["ROOT150"]["same_attempt_as_ROOT133"] is False
    assert independent["ROOT145"]["same_attempt_as_ROOT140"] is False
    assert independent["ROOT150"]["scientific_credit"] == "NONE"
    assert independent["ROOT145"]["scientific_credit"] == "NONE"
    assert result["scope_preservation"]["root159_report_edited"] is False
    assert result["scope_preservation"]["arrays_or_solver_read"] is False
    assert result["scope_preservation"]["qualification"] == {
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "dynamics": "UNKNOWN",
    }


def test_v2_request_closes_all_json_and_worker_hashes_without_payload_inputs() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert request["schema"] == request["request_schema"] == "ds02.request.v1"
    assert request["case_id"] == "DS02_STAGE2_FULL_GOAL_EDGE_LINK_CORRECTION_V2"
    assert request["status"] == "prepared_edge_link_correction_v2_guard_pending"
    assert request["launch_allowed"] is False
    assert len(request["input_files"]) == len(request["input_sha256"]) == 28
    # The immutable request may retain the producer's forensics checkout path
    # after the worker is cherry-picked elsewhere.  Bind by declared path,
    # recorded digest, and byte identity rather than requiring this checkout's
    # absolute path.
    assert request["command"][2] == "--manifest"
    declared_manifest = Path(request["command"][3])
    # The immutable request can retain the producer checkout's absolute path.
    # Preserve the role (argv position, basename, prepared-attempt directory)
    # and prove the recorded content digest equals this checkout's manifest;
    # do not require the producer path to exist after cherry-pick.
    assert declared_manifest.name == MANIFEST.name
    assert declared_manifest.parent.name == MANIFEST.parent.name
    declared_key = str(declared_manifest)
    assert declared_key in request["input_sha256"]
    assert request["input_sha256"][declared_key] == sha256_file(MANIFEST)
    assert manifest["schema"] == "ds02.stage2.full-goal-rollup.edge-link-correction.manifest.v2"
    assert manifest["correction_contract"]["same_attempt_requires_request_path_and_sha_equality"] is True
    for raw_path, expected in request["input_sha256"].items():
        path = Path(raw_path)
        assert path.is_file(), path
        assert path.suffix.lower() == ".json" or path.name.endswith(".py"), path
        assert sha256_file(path) == expected, path
    assert request["hdf5_read"] is False
    assert request["read_policy"]["h5_opened"] is False
    assert request["read_policy"]["bi4_opened"] is False
    assert request["read_policy"]["solver_started"] is False

