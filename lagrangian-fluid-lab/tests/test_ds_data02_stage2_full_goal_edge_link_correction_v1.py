from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_full_goal_edge_link_correction_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "full-goal-edge-link-correction-v1-root-prepared-164-001/"
    / "full-goal-edge-link-correction-v1-manifest.json"
)
REQUEST = MANIFEST.with_name("full-goal-edge-link-correction-v1-request.json")
ROOT159_REPORT_SHA = "d431d03da23a345c7bc0b223f5d8f38644c0534a3ba2dbc4b14831d22b615b08"
ROOT159_PROOF_SHA = "4a68f73838937aadd595a206a41146097a09c0f1a364595b947759639fbb9860"
ROOT138_PROOF_SHA = "c3808bdcaf8387e57b4a4f0b533f5e58372a30ac5e3ded83ede369cfb5c3becd"
ROOT130_PROOF_SHA = "e894c4bf40358a51a0d5eba6c3ef77e2129ddc433e8e1c4a077cc8ff95a8c943"
ROOT142_PROOF_SHA = "d8e27f29185c176af70a8fffea4b4790afaacc10413fe6e2762b6d9bd1cff56e"


def module():
    spec = importlib.util.spec_from_file_location("edge_link_correction_v1", SCRIPT)
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


def test_corrects_root138_source_role_without_rerunning_rollup() -> None:
    loaded = module()
    result = loaded.build(MANIFEST, Path("/tmp/unused-edge-link-correction.json"))
    assert result["schema"] == "ds02.stage2.full-goal-rollup.edge-link-correction.v1"
    assert result["status"] == "CORRECTED_EDGE_LINKS_SOURCE_BOUND_NO_NEW_SCIENCE"
    assert result["root159_baseline"]["immutable"] is True
    assert result["scope_preservation"]["root159_report_edited"] is False
    assert result["scope_preservation"]["arrays_or_solver_read"] is False
    assert result["scope_preservation"]["qualification"] == {
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "dynamics": "UNKNOWN",
    }

    corrected = result["corrected_edges"]
    assert corrected["ROOT138_STREAM"]["prior_root159_source"]["sha256"] == ROOT130_PROOF_SHA
    assert corrected["ROOT138_STREAM"]["corrected_source"]["sha256"] == ROOT138_PROOF_SHA
    assert corrected["ROOT138_STREAM"]["ROOT130_solver_control_is_separate"] is True
    assert corrected["ROOT142_MOTIVES"]["source"]["sha256"] == ROOT142_PROOF_SHA
    assert corrected["ROOT142_MOTIVES"]["source_remains_distinct"] is True


def test_historical_edges_and_root159_baseline_are_pinned() -> None:
    loaded = module()
    result = loaded.build(MANIFEST, Path("/tmp/unused-edge-link-correction-2.json"))
    assert result["root159_baseline"]["proof"]["sha256"] == ROOT159_PROOF_SHA
    assert result["root159_baseline"]["report"]["sha256"] == ROOT159_REPORT_SHA
    assert result["historical_edges"]["ROOT133"]["superseded_by"] == "ROOT150"
    assert result["historical_edges"]["ROOT133"]["same_attempt"] is False
    assert result["historical_edges"]["ROOT140"]["superseded_by"] == "ROOT145"
    assert result["historical_edges"]["ROOT140"]["same_attempt"] is False
    assert result["historical_edges"]["ROOT150"]["scientific_credit"] == "NONE"
    assert result["historical_edges"]["ROOT145"]["scientific_credit"] == "NONE"

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["correction_contract"]["root159_report_must_remain_unchanged"] is True
    assert manifest["correction_contract"]["historical_terminal_attempts_are_distinct"] is True
    assert manifest["correction_contract"]["new_science_credit"] is False


def test_request_binds_the_json_only_correction_inputs() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["schema"] == request["request_schema"] == "ds02.request.v1"
    assert request["case_id"] == "DS02_STAGE2_FULL_GOAL_EDGE_LINK_CORRECTION_V1"
    assert request["status"] == "prepared_edge_link_correction_guard_pending"
    assert len(request["input_files"]) == len(request["input_sha256"]) == 20
    assert request["command"][3] == str(MANIFEST.resolve())
    assert request["command"][-1] == request["output"]["path"]
    for raw_path, expected in request["input_sha256"].items():
        path = Path(raw_path)
        assert path.is_file(), path
        assert path.suffix.lower() == ".json" or path.name.endswith(".py"), path
        assert sha256_file(path) == expected, path
    assert request["hdf5_read"] is False
    assert request["read_policy"]["h5_opened"] is False
    assert request["read_policy"]["bi4_opened"] is False
    assert request["read_policy"]["solver_started"] is False
