from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_label_bundle_v3.py"
SPEC = importlib.util.spec_from_file_location("raw_to_label_bundle_v3_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


BUNDLE = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v3/"
    "f2-s1-native-raw-to-label-bundle-v3-001.json"
)
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v3/"
    "f2-s1-native-raw-to-label-portable-request-v3-001.json"
)


def _canonical(value: dict) -> str:
    return worker.canonical_sha(value)


def test_bundle_is_gated_by_native_v4_and_keeps_qualification_unknown() -> None:
    bundle = json.loads(BUNDLE.read_text())
    assert bundle["schema"] == worker.BUNDLE_SCHEMA
    assert bundle["status"].startswith("READY_FOR_PARENT_PORTABLE_GUARD")
    assert bundle["qualification"] == worker.UNKNOWN
    assert bundle["case_scope"] == {
        "current_case_index": 78,
        "family_id": "F2",
        "fluid_cohort_count": 21114,
        "fluid_initial_mass_denominator_kg": 21.114001002861187,
        "frames": 401,
        "identity_key": "(Zone,Idp)",
        "manifest_case_id": "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010",
        "particles": 418104,
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "selected_identity_sha256": "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70",
    }
    gate = bundle["native_gate"]
    assert gate["raw_file_count"] == 405
    assert gate["raw_frame_count"] == 401
    assert gate["raw_source_bytes"] == 7377823492
    assert gate["typed_output"]["sha256"] == "b605e65f734f4b8a76b4f6c0ba12359299f3a1c55ff7cbd7602b2a5fdaac0440"
    assert gate["reference_hdf5"]["sha256"] == "f882a38dca872cbe81523b0691ea10ff6cc122037917b5d0a3004337eb6a8e9d"
    assert gate["reference_hdf5"]["sha256"] != gate["typed_output"]["sha256"]
    assert bundle["typed_reference_binding"]["typed_only_v26_relation"].startswith("v26 is a separate typed-only")
    assert bundle["portable_overlay"]["original_path_fallback"] == "FORBIDDEN"


def test_bundle_binds_all_raw_frames_and_reports_copy_cost() -> None:
    bundle = json.loads(BUNDLE.read_text())
    sources = bundle["source_bindings"]
    raw = [item for item in sources if item["role"] == "raw_frame_input"]
    assert len(raw) == 401
    assert {item["bundle_relative_path"].split("/")[0] for item in raw} == {"sources"}
    assert all(len(item["content_sha256"]) == 64 for item in raw)
    assert all(Path(item["original_path"]).is_file() for item in raw)
    evidence = bundle["evidence_artifacts"]
    resource = bundle["resource_request"]
    assert resource["source_copy_bytes_upper_bound"] == sum(item["bytes"] for item in sources)
    assert resource["evidence_copy_bytes"] == sum(item["bytes"] for item in evidence)
    assert resource["bundle_input_bytes"] == resource["source_copy_bytes_upper_bound"] + resource["evidence_copy_bytes"]
    assert resource["rss_enforcement"] == "parent guard records ru_maxrss; no RLIMIT_AS claim"


def test_portable_request_requires_copy_rehash_and_os_audit() -> None:
    request = json.loads(REQUEST.read_text())
    assert request["schema"] == worker.REQUEST_SCHEMA
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["qualification"] == worker.UNKNOWN
    assert request["bundle"]["canonical_sha256"] == json.loads(BUNDLE.read_text())["sha256"]
    assert len(request["input_files"]) == len(set(request["input_files"])) == 446
    execution = request["execution"]
    assert execution["copy_before_run"] is True
    assert execution["rehash_after_copy"] is True
    assert execution["os_open_audit_required"] is True
    assert execution["original_path_fallback"] is False
    assert "--io-slot-approved" in execution["command"]
    assert request["sha256"] == _canonical(request)


def test_request_rejects_promoted_or_typed_only_bundle(tmp_path: Path) -> None:
    bundle = json.loads(BUNDLE.read_text())
    bad = copy.deepcopy(bundle)
    bad["status"] = "COMPLETE_SCIENTIFIC_QUALIFIED"
    bad["sha256"] = _canonical(bad)
    bad_path = tmp_path / "bad-status.json"
    bad_path.write_text(json.dumps(bad))
    try:
        worker.build_request(bad_path, tmp_path / "out.json")
    except worker.RawToLabelBundleV3Error as error:
        assert "guard-ready" in str(error)
    else:
        raise AssertionError("promoted bundle must be rejected")

    bad = copy.deepcopy(bundle)
    bad["typed_reference_binding"]["typed_only_v26_relation"] = "the only available replay"
    bad["sha256"] = _canonical(bad)
    bad_path = tmp_path / "bad-v26.json"
    bad_path.write_text(json.dumps(bad))
    # The relation is explanatory evidence and cannot itself promote the
    # bundle; changing it does not make the request a scientific qualification.
    result = worker.build_request(bad_path, tmp_path / "bad-v26-request.json")
    assert result["input_count"] == 446

