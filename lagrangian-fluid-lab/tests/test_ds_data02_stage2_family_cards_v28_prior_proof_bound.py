from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_family_cards_v28_prior_proof_bound.py"
SPEC = importlib.util.spec_from_file_location("family_cards_v28_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _unknown() -> dict[str, str]:
    return {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_reference_field_rejects_payload_suffix(tmp_path: Path) -> None:
    payload = tmp_path / "payload.h5"
    payload.write_bytes(b"fixture")
    with pytest.raises(MODULE.PriorProofError, match="JSON metadata reference"):
        MODULE._reference_field(
            {"report": str(payload), "report_sha256": MODULE._sha(payload, "fixture", 1024)},
            "report", "fixture",
        )


def test_base_catalog_requires_335_canonical_rows_and_keeps_alias_out(tmp_path: Path) -> None:
    cards = {family: {} for family in MODULE.FAMILIES}
    cases = []
    for index in range(336):
        family = MODULE.FAMILIES[index % 7]
        physical = f"{family}_CASE_{index:03d}"
        cases.append({"family_id": family, "physical_case_id": physical,
                      "canonical_case_id": None if index == 335 else physical})
    catalog = {
        "schema": "fixture", "case_count": 336, "cards": cards, "cases": cases,
        "qualification": _unknown(),
        "claim_boundary": {"split_safe": False, "qualification_credit": "NONE"},
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    value = MODULE._verify_base_catalog(path)
    assert value["case_count"] == 336


def test_gencase_proof_stays_metadata_only(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    receipt = tmp_path / "receipt.json"
    request.write_text("{}\n", encoding="utf-8")
    receipt.write_text("{}\n", encoding="utf-8")
    proof = {
        "schema": MODULE.GENCASE_PROOF_SCHEMA,
        "status": MODULE.GENCASE_STATUS,
        "H5_BI4_read_by_root": False,
        "generated_native_vtk_payload_read_by_root": False,
        "parent_reservation_released": True,
        "scientific_Q_credit": 0,
        "scientific_qualification": _unknown(),
        "physical_case_id": "F2_FIXTURE_OWNER_GRID",
        "request": str(request), "request_sha256": MODULE._sha(request, "request", 1024),
        "receipt": str(receipt), "receipt_sha256": MODULE._sha(receipt, "receipt", 1024),
    }
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    result = MODULE._verify_gencase(proof_path)
    assert result["family_id"] == "F2"
    assert result["products_read"] is False
    assert result["qualification"] == _unknown()
