from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py"
REQUEST = ROOT / "campaigns" / "ds-data-02" / "stage2" / "native-reconstruction" / "typed-only-fresh-proof-root-055" / "f2-s1-fresh-v16-proof-request-v9-root-059-root-consumer.json"
REPORT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TYPED_LABELS_ONLY_V1_ROOT_051/f2-s1-typed-labels-only-v1-root-051-001-root-forward-030-001/labels/typed-label-only-report-v1.json")

spec = importlib.util.spec_from_file_location("proof_v10_under_test", SCRIPT)
assert spec is not None and spec.loader is not None
v10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v10)


def _request_with_contract() -> dict:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    sha = v10._sha_file(REPORT)
    request["v10_mass_scope_contract"] = {
        "accepted_result_missing_scope": v10.ACCEPTED_MISSING_SCOPE,
        "semantics": v10.ACCEPTED_SCOPE_SEMANTICS,
        "source_report": {"path": str(REPORT), "sha256": sha},
    }
    return request


def test_root051_small_report_and_expected_contract_are_closed():
    request = _request_with_contract()
    _, report = v10._json(REPORT, "producer report")
    scope = v10._validate_mass_contract(request, report)
    assert scope["accepted_result_missing_scope"] == v10.ACCEPTED_MISSING_SCOPE
    assert scope["denominator_kg"] == 21.114001002861187
    assert scope["later_missing_unique_count"] == 3


def test_scope_adapter_accepts_only_exact_source_bound_spelling():
    request = _request_with_contract()
    _, report = v10._json(REPORT, "producer report")
    v10._ACTIVE_SCOPE_CONTRACT = v10._validate_mass_contract(request, report)
    original = v10._V8_VALIDATE_RESULT
    seen = {}

    def fake_validate(result, bound, result_sha, result_bytes):
        seen["scope"] = result["initial_mass_denominator"]["missing_scope"]
        return {"ok": True}

    v10._V8_VALIDATE_RESULT = fake_validate
    try:
        result = {"initial_mass_denominator": {"missing_scope": v10.ACCEPTED_MISSING_SCOPE}}
        assert v10._validate_result_v10(result, {}, "a" * 64, 1) == {"ok": True}
        assert seen["scope"].startswith("initial denominator mass; ")
        bad = {"initial_mass_denominator": {"missing_scope": "later missing only"}}
        try:
            v10._validate_result_v10(bad, {}, "a" * 64, 1)
        except v10.V10ProofConsumerError:
            pass
        else:
            raise AssertionError("non-source-bound missing_scope was accepted")
    finally:
        v10._V8_VALIDATE_RESULT = original
        v10._ACTIVE_SCOPE_CONTRACT = None


def test_producer_field_and_censor_contract_cannot_be_downgraded():
    request = _request_with_contract()
    _, report = v10._json(REPORT, "producer report")
    bad = dict(report)
    bad["typed_validation"] = dict(report["typed_validation"])
    bad["typed_validation"]["typed_fields_validated"] = ["time", "position"]
    try:
        v10._validate_mass_contract(request, bad)
    except v10.V10ProofConsumerError as error:
        assert "typed fields" in str(error)
    else:
        raise AssertionError("incomplete typed field contract was accepted")
