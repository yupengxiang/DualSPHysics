from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_native_raw_to_typed_v2.py"
SPEC = importlib.util.spec_from_file_location("family_native_v2_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


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


def test_remaining_family_requests_are_source_bound_streams_only(tmp_path: Path) -> None:
    expected = {"F1": (161, 141636), "F3": (836, 179208), "F5": (801, 194427), "F7": (601, 70179)}
    for family, (frames, particles) in expected.items():
        request = _request(tmp_path, family)
        assert request["schema"].endswith("request.v2")
        assert request["raw_binding"]["expected_raw_tree_sha256"] is None
        assert request["raw_binding"]["producer_tree_digest_invented"] is False
        assert len(request["raw_binding"]["frames"]) == frames
        assert request["typed_output_contract"]["expected_shape"] == {"frames": frames, "particles": particles}
        assert request["labels"]["status"] == "PENDING_FAMILY_SPECIFIC_OPERATOR"
        assert request["labels"]["f2_receiver_operator_imported"] is False
        assert request["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
        assert worker._validate_request(request, verify_sources=False)["family"] == family


def test_f5_retains_actual_16_second_curve_tail_without_nominal_inference(tmp_path: Path) -> None:
    request = _request(tmp_path, "F5")
    tail = request["raw_binding"]["motion_control_tail"]
    assert tail["actual_time_window_s"] == [0.0, 16.00014612682076]
    assert tail["motion_source_role"] == "raw_header_PartMotionRef.ibi4"
    assert tail["tail_policy"].startswith("preserve native PartMotionRef")
    assert tail["nominal_case_alias_is_not_control"] is True
    assert "PartMotionRef.ibi4" in [Path(path).name for path in request["raw_binding"]["required_source_arrays"]]


def test_f5_missing_motion_source_or_wrong_window_is_rejected(tmp_path: Path) -> None:
    request = _request(tmp_path, "F5")
    bad = copy.deepcopy(request)
    bad["raw_binding"]["required_source_arrays"] = [
        path for path in bad["raw_binding"]["required_source_arrays"]
        if Path(path).name != "PartMotionRef.ibi4"
    ]
    bad["sha256"] = worker.canonical_sha({key: item for key, item in bad.items() if key != "sha256"})
    try:
        worker._validate_request(bad, verify_sources=False)
    except worker.FamilyNativeV2Error as error:
        assert "motion source" in str(error)
    else:
        raise AssertionError("F5 without PartMotionRef must be rejected")

    bad_plan = json.loads(_plan("F5").read_text())
    bad_plan["anchor_case"]["actual_time_window_s"] = [0.0, 0.9]
    plan_file = tmp_path / "bad-f5-plan.json"
    plan_file.write_text(json.dumps(bad_plan))
    try:
        worker.build_request(plan_file, tmp_path / "bad-f5.json")
    except worker.FamilyNativeV2Error as error:
        assert "16 s" in str(error)
    else:
        raise AssertionError("a nominal/control duration must not replace F5 saved coverage")


def test_partout_cannot_be_substituted_for_a_raw_frame(tmp_path: Path) -> None:
    request = _request(tmp_path, "F3")
    bad = copy.deepcopy(request)
    bad["raw_binding"]["frames"][0]["path"] = next(
        item["path"] for item in bad["source_files"] if item["role"] == "raw_provenance_partout"
    )
    bad["sha256"] = worker.canonical_sha({key: item for key, item in bad.items() if key != "sha256"})
    try:
        worker._validate_request(bad, verify_sources=False)
    except worker.FamilyNativeV2Error as error:
        assert "raw frame 0" in str(error)
    else:
        raise AssertionError("PartOut must not satisfy a Part_0000 frame binding")


def test_f2_receiver_plan_is_not_accepted_by_remaining_family_worker(tmp_path: Path) -> None:
    f2_plan = ROOT / "campaigns/ds-data-02/stage2/lineage/v14/raw-anchor-plans/F2-raw-anchor-plan-v1.json"
    try:
        worker.build_request(f2_plan, tmp_path / "F2.json")
    except worker.FamilyNativeV2Error as error:
        assert "F1/F3/F5/F7" in str(error)
    else:
        raise AssertionError("v2 remaining-family stream must not import F2 receiver semantics")


def test_committed_requests_have_exact_content_hashes_and_metadata_preflight() -> None:
    request_root = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/generic-v2"
    for family in ("f1", "f3", "f5", "f7"):
        path = next(request_root.glob(f"{family}-s1-native-raw-to-typed-compare-request-v2-001.json"))
        request = json.loads(path.read_text())
        assert worker._validate_request(request, verify_sources=False)["family"] == family.upper()
        assert request["input_files"]
        for source in request["input_files"]:
            assert Path(source).is_file(), source
        assert request["source_hashes_preverified_by_parent"] is False
        assert request["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
        body = dict(request)
        declared = body.pop("sha256")
        assert declared == worker.canonical_sha(body)

