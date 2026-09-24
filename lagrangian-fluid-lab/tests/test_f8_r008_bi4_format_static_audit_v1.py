from __future__ import annotations

import json

import pytest

from scripts import f8_r008_bi4_format_static_audit_v1 as audit


def test_static_audit_freezes_observed_format_without_claiming_binary_lineage() -> None:
    receipt = audit.build_receipt()

    assert audit.verify_receipt(receipt)
    assert receipt["schema"] == "core.cfd.f8.r008_bi4_format_static_audit.v1"
    assert receipt["historical_build_linkage"]["binary_sha256"] == (
        "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
    )
    assert receipt["historical_build_linkage"]["binary_built_from_pinned_cpp_and_header_proven"] is False
    assert receipt["historical_build_linkage"]["r008_preflight_pins_decoder_binary_at_invocation"] is False
    assert receipt["readiness_effect"]["readiness_pass"] is False
    assert receipt["execution_controls_for_this_audit"]["bi4_dump_invoked"] is False


def test_observed_initial_layout_and_future_solver_contract_are_explicit() -> None:
    receipt = audit.build_receipt()
    observed = receipt["observed_initial_decode"]

    assert {item["array_name"]: item["bytes"] for item in observed["array_files"]} == {
        "BoundNor": 49152,
        "Idp": 43008,
        "Posd": 258048,
        "Rhop": 43008,
        "Vel": 129024,
    }
    assert observed["array_shape_and_type"]["Posd"] == {
        "xml_type": "double3",
        "numpy_contract": "<f8",
        "shape": [10752, 3],
    }
    future = receipt["future_per_case_acceptance_contract"]
    assert future["required_arrays"] == [
        "Idp",
        "Vel",
        "Rhop",
        "exactly_one_of(Pos, Posd)",
    ]
    assert "complete emitted-array set" in future["not_yet_evidenced"][0]


def test_static_audit_never_overwrites_an_existing_receipt(tmp_path) -> None:
    target = tmp_path / "receipt.json"
    target.write_text('{"preserve": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        audit.write_immutable_receipt(target)

    assert json.loads(target.read_text(encoding="utf-8")) == {"preserve": True}
