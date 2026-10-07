from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ds_data02_stage2_family_native_raw_to_typed_v1 as worker  # noqa: E402


def _plan(family: str) -> Path:
    return ROOT / (
        "campaigns/ds-data-02/stage2/lineage/v14/raw-anchor-plans/"
        f"{family}-raw-anchor-plan-v1.json"
    )


def _request(tmp_path: Path, family: str) -> dict:
    result = worker.build_request(_plan(family), tmp_path / f"{family}.json")
    assert result["family_id"] == family
    return json.loads((tmp_path / f"{family}.json").read_text())


def _freeze(value: dict) -> dict:
    value = copy.deepcopy(value)
    value["sha256"] = worker.canonical_sha({key: item for key, item in value.items() if key != "sha256"})
    return value


def test_f4_and_f6_requests_are_metadata_only_and_source_bound(tmp_path: Path) -> None:
    f4 = _request(tmp_path, "F4")
    f6 = _request(tmp_path, "F6")
    assert f4["raw_binding"]["expected_raw_tree_sha256"] is None
    assert f4["raw_binding"]["expected_raw_tree_status"] == "UNKNOWN_PENDING_PARENT_WORKER"
    assert len(f4["raw_binding"]["frames"]) == 1201
    assert len(f6["raw_binding"]["frames"]) == 241
    assert f6["mass_semantics"]["rigid_body_inference_from_particle_sum"] is False
    assert f6["mass_semantics"]["rigid_body"]["massbody_records"][0]["massbody_kg"] == 128.0
    assert f6["mass_semantics"]["typed_particle_block_records"][0]["masspart_kg"] == "0.015625"
    assert f6["labels"]["status"] == "PENDING_FAMILY_SPECIFIC_OPERATOR"
    assert f4["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_partout_cannot_be_substituted_for_a_raw_frame(tmp_path: Path) -> None:
    request = _request(tmp_path, "F4")
    bad = copy.deepcopy(request)
    bad["raw_binding"]["frames"][0]["path"] = next(
        item["path"] for item in bad["source_files"] if item["role"] == "raw_provenance_partout"
    )
    bad["sha256"] = worker.canonical_sha({key: item for key, item in bad.items() if key != "sha256"})
    try:
        worker._validate_request(bad, verify_sources=False)
    except worker.FamilyNativeError as error:
        assert "raw frame 0" in str(error)
    else:
        raise AssertionError("PartOut must not satisfy a Part_0000 frame binding")


def test_rigid_mass_inference_is_rejected_even_with_a_valid_request_sha(tmp_path: Path) -> None:
    request = _request(tmp_path, "F6")
    bad = copy.deepcopy(request)
    bad["mass_semantics"]["rigid_body_inference_from_particle_sum"] = True
    bad = _freeze(bad)
    try:
        worker._validate_request(bad, verify_sources=False)
    except worker.FamilyNativeError as error:
        assert "particle sums" in str(error)
    else:
        raise AssertionError("rigid body mass must not be inferred from particle sums")


def test_raw_tree_digest_is_not_silently_invented(tmp_path: Path) -> None:
    request = _request(tmp_path, "F6")
    assert request["raw_binding"]["producer_tree_digest_invented"] is False
    assert request["source_closure"]["raw_source_expected_tree"] == (
        "UNKNOWN; no producer digest was available in the anchor plan"
    )


def test_committed_f4_f6_requests_validate_without_dataset_reads() -> None:
    request_root = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/generic-v1"
    for family in ("f4", "f6"):
        path = next(request_root.glob(f"{family}-s1-native-raw-to-typed-compare-request-v1-001.json"))
        request = json.loads(path.read_text())
        bound = worker._validate_request(request, verify_sources=False)
        assert bound["family"] == family.upper()
        assert bound["expected_raw_tree"] is None
        assert request["source_hashes_preverified_by_parent"] is False
