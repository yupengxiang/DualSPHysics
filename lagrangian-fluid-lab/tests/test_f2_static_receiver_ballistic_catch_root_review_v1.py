from __future__ import annotations

from scripts import f2_static_receiver_ballistic_catch_root_review_v1 as review


def test_root_review_receipt_is_closed_and_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT_RECEIPT", tmp_path / "root-review.json")
    receipt = review.build_receipt()
    assert receipt["status"] == "authorized_one_fresh_cpu_native_preflight_only"
    assert receipt["qualification_claim"] == "none"
    assert receipt["matrix_credit"] == 0
    assert receipt["authorization"]["gencase_invocations"] == 1
    assert receipt["authorization"]["native_decode_invocations"] == 1
    assert receipt["authorization"]["solver_launch"] is False
    assert receipt["authorization"]["gpu_launch"] is False
    assert receipt["authorization"]["queue_mutation"] == 0
    assert receipt["fresh_input"]["same_input_retry"] is False


def test_root_review_binds_new_namespace(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT_RECEIPT", tmp_path / "root-review.json")
    receipt = review.build_receipt()
    case = receipt["case"]
    assert case["definition"].endswith("F2_STATIC_RECEIVER_BALLISTIC_CATCH_q0p50000000_dp0p007500000000_anchor_Def.xml")
    assert "f2-static-receiver-ballistic-catch-v1" in case["generated_prefix"]
    assert case["contract"].endswith("definition-contract-v1.json")
