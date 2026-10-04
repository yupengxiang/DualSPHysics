from __future__ import annotations

import hashlib
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025",
]


def load(rel: str) -> dict:
    value = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_actual_gencase_metadata_is_terminal_and_direct_root():
    audit = load("gencase/actual-gencase-metadata-audit.json")
    assert audit["status"] == "actual_receipts_metadata_checked"
    assert audit["checks"] == {
        "all_direct_root_prefixes": True,
        "all_official_runtime_counts": True,
        "all_receipts_completed_0": True,
        "all_xml_counts_geometry_omega": True,
    }
    assert [x["case_id"] for x in audit["cases"]] == CASES
    for row in audit["cases"]:
        assert "/prepared/" not in row["gencase_prefix"]
        assert len(row["generated_bi4_sha256"]) == 64
        assert len(row["generated_xml_sha256"]) == 64
        assert len(row["execution_receipt_sha256"]) == 64
        assert row["runtime_counts"] == {"dimension": 3, "fluid": 327680, "total": 417505}


def test_all_runtime_requests_are_disabled_and_exact_recipe():
    qa = load("qa/initial-native-qa-request.json")
    state = load("floatinginfo/requests/f6_first8_five_omega_state0_request.json")
    qualification = load("qualification/qualification-binding.json")
    assert qa["launch"] is False and qa["launch_allowed"] is False
    assert state["launch"] is False and state["launch_allowed"] is False
    assert qualification["launch_allowed"] is False
    requests = sorted((ROOT / "qualification/requests").glob("*.json"))
    assert len(requests) == 5
    for path in requests:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["command"][-2:] == ["-tmax:12", "-tout:0.05"]
        assert request["expected_native_frames"] == 241
        assert "-mdbc" not in request["command"]
        assert "-forcing" not in request["command"]
        assert "/prepared/" not in request["gencase_prefix"]


def test_mass_and_omega_claim_boundaries():
    binding = load("qa/qa-binding.json")
    assert len(binding["endpoints"]) == 5
    for endpoint in binding["endpoints"]:
        assert endpoint["physical_condition_sha256"] is None
        assert endpoint["source_plan_condition_sha256"] is None
        assert endpoint["expected_physical_mass_kg"] == 128.0
        assert endpoint["expected_native_support_mass_kg"] == 256.0
        assert endpoint["expected_masspart_kg"] == 0.015625
    strict = load("strict/actual-receipts-binder.json")
    assert strict["mass_policy"]["equality_required"] is False
    assert strict["angular_policy"].startswith("V0=0 cannot")


def test_workers_are_source_only_and_compile():
    workers = sorted((ROOT / "workers").glob("*.py"))
    assert {p.name for p in workers} == {
        "bind_f6_actual_receipts_v1.py",
        "run_f6_initial_native_qa_internal_v1.py",
        "run_f6_state0_omega_internal_v1.py",
    }
    for path in workers:
        py_compile.compile(str(path), doraise=True)


def test_future_hashes_remain_unfabricated():
    strict = load("strict/actual-receipts-binder.json")
    for case in strict["cases"]:
        assert case["canonical_owner_sha256"] is None
        assert case["physical_condition_sha256"] is None
        assert case["initial_qa_receipt"] is None
        assert case["full241_receipt_sha256"] is None
        assert case["state0_audit"] is None

