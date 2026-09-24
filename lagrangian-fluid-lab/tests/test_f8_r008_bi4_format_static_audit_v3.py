from __future__ import annotations

import copy

from scripts import f8_r008_bi4_format_static_audit_v3 as audit


def test_v3_binds_canonical_receipt_and_rejects_mutated_bounds() -> None:
    receipt = audit.build_receipt()

    assert audit.verify_receipt(receipt)
    for key in (
        "raw_input_bytes_max",
        "item_nodes_max_including_root",
        "arrays_total_max",
        "array_count_max",
        "single_array_payload_bytes_max",
        "aggregate_numeric_payload_bytes_max",
    ):
        changed = copy.deepcopy(receipt)
        changed["bounded_streaming_preflight"]["resource_limits"][key] = 1
        assert not audit.verify_receipt(changed)


def test_v3_places_all_bounds_before_any_decode_allocation_or_write() -> None:
    receipt = audit.build_receipt()
    order = receipt["bounded_streaming_preflight"]["required_order"]

    assert "fstat and bind its SHA-256" in order[0]
    assert "Before full load or large allocation" in order[1]
    assert "Before allocating any item/array/value object or payload" in order[2]
    assert "before the first output filesystem mutation" in order[3]
    assert "second pass from the same stable input descriptor" in order[4]
    assert "XML-to-file manifest equality" in order[5]
    assert receipt["bounded_streaming_preflight"]["resource_limits"]["header_bytes_exact"] == 64
    assert receipt["bounded_streaming_preflight"]["resource_limits"]["aggregate_numeric_payload_bytes_max"] == 16 * 1024 * 1024


def test_v3_keeps_safe_decoder_and_solver_authority_closed() -> None:
    receipt = audit.build_receipt()

    assert receipt["bounded_streaming_preflight"]["existing_parser_caveat"]["JBinaryData_LoadFile_memory_true"].startswith("allocates a buffer")
    assert receipt["readiness_effect"]["bounded_safe_decoder_implemented"] is False
    assert receipt["readiness_effect"]["readiness_pass"] is False
    assert receipt["readiness_effect"]["qualification_credit"] == 0
    assert receipt["execution_controls_for_this_audit"]["bi4_dump_invoked"] is False
