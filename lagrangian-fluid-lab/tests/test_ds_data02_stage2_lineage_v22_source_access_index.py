"""Small exact-path validation for the v22 seven-family evidence index.

This test deliberately hashes JSON/cards/manifests only.  It never opens H5,
BI4, Part_*.bi4, native arrays, or a solver output.  The external evidence
paths are provenance bindings produced by the parent guard and are therefore
checked fail-closed when present.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
INDEX = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v22-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V22.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load() -> dict:
    value = json.loads(INDEX.read_text(encoding="utf-8"))
    assert value["schema"] == "ds02.stage2.seven-family-source-access-index.v22"
    assert value["role"] == "DEVELOPMENT"
    assert value["model_invoked"] is False
    return value


def _resolve_repo_relative(path_text: str) -> Path:
    path = REPO / path_text
    assert path.is_file(), path
    return path


def _resolve_external(path_text: str) -> Path:
    path = Path(path_text)
    assert path.is_absolute(), path
    assert path.is_file(), path
    return path


def test_all_seven_cards_and_current_are_exactly_bound() -> None:
    index = _load()
    current = index["current_binding"]
    current_path = _resolve_repo_relative(current["repo_relative_path"])
    assert _sha(current_path) == current["sha256"]

    cards = index["family_cards"]
    assert set(cards) == {f"F{i}" for i in range(1, 8)}
    for family, card in cards.items():
        card_path = _resolve_repo_relative(card["repo_relative_path"])
        assert _sha(card_path) == card["sha256"], family
        assert card["case_count"] == 48
        assert card["split_safe"] is False
        assert card["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_proof_and_output_hashes_are_exact_and_scope_is_explicit() -> None:
    index = _load()
    bindings = index["evidence_bindings"]
    for name, binding in bindings.items():
        proof = _resolve_external(binding["path"])
        assert _sha(proof) == binding["sha256"], name
        if "output_path" in binding:
            output = _resolve_external(binding["output_path"])
            assert _sha(output) == binding["output_sha256"], name
        if "receipt_path" in binding:
            receipt = _resolve_external(binding["receipt_path"])
            assert _sha(receipt) == binding["receipt_sha256"], name

    calibration = bindings["all118_label_calibration"]
    assert calibration["coverage"]["selected_case_count"] == 118
    assert calibration["status"] == "LABEL_CALIBRATED_SOURCE_MK_CENSORING_NO_MODEL"
    assert bindings["portable_v27_boundary"]["portable_trial_completed"] is False


def test_dependency_and_request_bindings_do_not_authorize_array_reads() -> None:
    index = _load()
    deps = index["dependencies_and_licenses"]
    for item in (deps["repository_license"], deps["reader_dependency_license_index_v13"]):
        path = _resolve_repo_relative(item["repo_relative_path"])
        assert _sha(path) == item["sha256"]

    request = index["guard_ready_requests"]["f7_initial_qa_outer_v9"]
    request_path = _resolve_repo_relative(request["repo_relative_path"])
    assert _sha(request_path) == request["sha256"]
    assert request["h5_or_bi4_read_by_index"] is False
    policy = index["access_policy"]
    assert policy["exact_paths_only"] is True
    assert policy["latest_or_glob_fallback"] is False
    assert policy["external_paths_are_provenance_only_until_parent_guard"] is True
    assert "H5" in policy["requires_parent_guard_for"]
    assert "BI4" in policy["requires_parent_guard_for"]
