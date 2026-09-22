from pathlib import Path

from scripts.f9_metric_parser_contract_v1 import OUTPUT, build_contract, verify_contract


def test_f9_metric_contract_is_static_and_hash_bound():
    contract = build_contract()
    assert contract["admission_granted"] is False
    assert contract["qualification_credit"] == 0
    assert contract["profile_and_flux"]["normal_bins"] == 64
    assert contract["denominators_and_gates"]["fixed_denominator"] is True
    assert contract["field_conventions"]["pressure"]["required_receipt_flag"] == "pressure_is_gauge=true"
    assert contract["execution_controls"]["hdf5_opened"] is False


def test_f9_metric_contract_materialized_receipt_verifies():
    assert Path(OUTPUT).is_file()
    result = verify_contract(OUTPUT)
    assert result["status"] == "static_parser_contract_bound_no_runtime_authorization"
    assert result["static_self_check"]["runtime_map_width_still_requires_bi4_receipt"] is True
