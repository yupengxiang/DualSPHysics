from __future__ import annotations

import copy

from scripts import f8_r008_bi4_format_static_audit_v2 as audit


def test_v2_full_canonical_comparison_binds_all_contract_and_readiness_fields() -> None:
    receipt = audit.build_receipt()

    assert audit.verify_receipt(receipt)
    for path in (
        ("source_contract", "type_sizes_bytes"),
        ("future_per_case_acceptance_contract", "predecode_safety_gate"),
        ("readiness_effect", "qualification_credit"),
        ("decoder_path_security", "minimum_filesystem_policy"),
    ):
        changed = copy.deepcopy(receipt)
        node = changed
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = "tampered"
        assert not audit.verify_receipt(changed)


def test_v2_preserves_path_escape_finding_and_blocks_existing_decoder() -> None:
    receipt = audit.build_receipt()
    security = receipt["decoder_path_security"]

    assert security["postrun_manifest_prevents_escape_writes"] is False
    assert security["unsafe_decoder_authorized_for_future_input"] is False
    assert "validate the entire decoded item/array tree before creating any output" in (
        security["minimum_name_policy"]["validation_order"]
    )
    assert receipt["execution_controls_for_this_audit"]["bi4_dump_invoked"] is False
    assert receipt["readiness_effect"]["qualification_credit"] == 0


def test_v2_retains_v1_revise_receipt_as_historical_evidence() -> None:
    receipt = audit.build_receipt()

    assert receipt["supersedes"]["review"]["verdict"] == "REVISE"
    assert receipt["supersedes"]["review"]["execution_authority_granted"] is False
    assert receipt["supersedes"]["receipt"]["path"].endswith(
        "bi4-format-static-audit-v1/receipt.json"
    )
