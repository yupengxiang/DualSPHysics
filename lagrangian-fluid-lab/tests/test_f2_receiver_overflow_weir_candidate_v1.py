import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1"


def _read(name):
    return json.loads((BASE / name).read_text())


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_receiver_overflow_candidate_is_root_review_only_and_zero_credit():
    card = _read("candidate-card-v1.json")
    matrix = _read("fixed-matrix-v1.json")
    denominator = _read("failure-denominator-v1.json")
    preflight = _read("cpu-native-preflight-v1.json")
    job = _read("root-review-only-job-spec-v1.json")
    job_v2 = _read("root-review-only-job-spec-v2.json")
    adapter = _read("adapter-contract-preflight-v1.json")
    route = _read("route-audit-v1.json")

    assert card["scope_id"] == "F2_receiver_overflow_weir_v1"
    assert card["qualification_claim"] == "none"
    assert card["qualified"] is False
    assert card["T1_numerical"] is False
    assert card["matrix_credit"] == 0
    assert card["execution_controls"]["controls_executed"] is False

    assert matrix["cell_count"] == 15
    assert matrix["denominator"] == {
        "planned": 15,
        "executed": 0,
        "passed": 0,
        "failed": 0,
        "event_censored": 0,
        "unattempted": 15,
        "credit": 0,
    }
    assert len(matrix["rows"]) == 15
    assert {row["status"] for row in matrix["rows"]} == {"not_started"}

    assert denominator["planned"] == 15
    assert denominator["unattempted"] == 15
    assert denominator["credit"] == 0
    assert denominator["preservation"]["all_rows_retained"] is True
    assert denominator["preservation"]["same_input_retry"] is False

    assert preflight["preflight_pass"] is True
    assert preflight["matrix_credit"] == 0
    assert preflight["native_initial"]["ids_unique"] is True
    assert preflight["native_initial"]["arrays_finite"] is True
    assert preflight["native_initial"]["boundary_zero_normal_count"] == 0
    assert preflight["execution_controls"]["solver_invoked"] is False
    assert preflight["execution_controls"]["gpu_invoked"] is False
    assert preflight["execution_controls"]["queue_mutation"] == 0

    assert job["job_spec_status"] == "root_review_only_not_submitted"
    assert job["execution_policy"]["submit_allowed"] is False
    assert job["execution_policy"]["one_anchor_only"] is True
    assert job["execution_policy"]["qualification_claim_none"] is True
    assert job["sha256_binding"]["candidate_card"] == _sha(BASE / "candidate-card-v1.json")
    assert job["sha256_binding"]["fixed_matrix"] == _sha(BASE / "fixed-matrix-v1.json")
    assert job["sha256_binding"]["failure_denominator"] == _sha(BASE / "failure-denominator-v1.json")
    assert job["sha256_binding"]["cpu_native_preflight"] == _sha(BASE / "cpu-native-preflight-v1.json")

    assert job_v2["job_spec_status"] == "root_review_only_adapter_implemented_not_submitted"
    assert job_v2["adapter"]["present"] is True
    assert job_v2["adapter"]["sha256"] == _sha(LAB / "scripts/core_f2_receiver_overflow_weir_v1.py")
    assert job_v2["execution_policy"]["runtime_preparation_allowed"] is False
    assert job_v2["sha256_binding"]["adapter_contract_preflight"] == _sha(
        BASE / "adapter-contract-preflight-v1.json"
    )
    assert adapter["status"] == "adapter_contract_only_root_review_required"
    assert adapter["adapter"]["sha256"] == _sha(LAB / "scripts/core_f2_receiver_overflow_weir_v1.py")

    assert route["status"] == "candidate_design_audit_complete_root_review_only"
    assert route["matrix_and_credit"]["matrix_credit"] == 0
    assert route["execution_controls"]["runtime_submitted"] is False
