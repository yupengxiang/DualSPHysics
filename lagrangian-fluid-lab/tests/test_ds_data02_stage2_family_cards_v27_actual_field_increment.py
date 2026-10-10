from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_cards_v27_actual_field_increment.py"


def _load():
    spec = importlib.util.spec_from_file_location("family_cards_v27_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha(path)}


def _fixture(tmp_path: Path):
    module = _load()
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    cards = {}
    for family in module.FAMILIES:
        path = base_dir / f"{family}-card.json"
        _write(path, {"schema": "base.card", "family_id": family,
                      "claim_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
        cards[family] = _ref(path)
    base = base_dir / "index.json"
    _write(base, {"schema": "base.overlay", "card_count": 7, "family_cards": cards})
    proofs: list[Path] = []
    for index, family in enumerate(module.FAMILIES):
        # The eighth proof is a second F1 case, matching ROOT370's actual
        # family distribution while retaining distinct case identity.
        if index == 0:
            cases = [("F1", "F1_CASE_A"), ("F1", "F1_CASE_B")]
        else:
            cases = [(family, f"{family}_CASE")]
        for row_index, (row_family, case_id) in enumerate(cases):
            stem = f"proof-{len(proofs)}"
            request = tmp_path / f"{stem}-request.json"; _write(request, {})
            receipt = tmp_path / f"{stem}-receipt.json"; _write(receipt, {})
            report = tmp_path / f"{stem}-report.json"; _write(report, {})
            manifest = tmp_path / f"{stem}-manifest.json"; _write(manifest, {})
            source_index = tmp_path / f"{stem}-source-index.json"; _write(source_index, {})
            independent = tmp_path / f"{stem}-independent.json"
            _write(independent, {
                "schema": module.INDEPENDENT_SCHEMA,
                "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT",
                "scientific_payload_content_read_by_verifier": False,
            })
            proof = tmp_path / f"{stem}.json"
            _write(proof, {
                "schema": module.ROOT_PROOF_SCHEMA,
                "status": "VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q",
                "request": _ref(request), "receipt": _ref(receipt), "report": _ref(report),
                "manifest": _ref(manifest), "independent_verification": _ref(independent),
                "source_index": _ref(source_index), "H5_BI4_read_by_root": False,
                "root_h5_payload_content_read": False, "parent_reservation_released": True,
                "actual_production_h5_scan": True, "scientific_Q_credit": 0,
                "scientific_qualification": dict(module.UNKNOWN),
                "case_verifications": [{"family_id": row_family, "physical_case_id": case_id,
                                        "active_finite_status": "ALL_ACTIVE_REQUIRED_FIELDS_FINITE",
                                        "initial_mass_status": "PRESENT_FINITE_POSITIVE"}],
            })
            proofs.append(proof)
    assert len(proofs) == 8
    return module, base, proofs


def test_adds_eight_actual_field_proofs_and_preserves_base(tmp_path: Path) -> None:
    module, base, proofs = _fixture(tmp_path)
    output = module.build(base_index=base, proofs=proofs,
                          output_dir=tmp_path / "increment", previous_field_count=15)
    assert output["actual_field_count"] == 23
    assert output["increment_field_count"] == 8
    assert output["claim_boundary"]["production_scientific_Q_credit"] == 0
    assert json.loads(base.read_text())["card_count"] == 7
    f1 = json.loads((tmp_path / "increment/F1-card.json").read_text())
    assert len(f1["actual_field_increment"]) == 2
    assert all(item["qualification"] == module.UNKNOWN for item in f1["actual_field_increment"])


def test_rejects_a_promoted_or_payload_read_field_proof(tmp_path: Path) -> None:
    module, base, proofs = _fixture(tmp_path)
    value = json.loads(proofs[0].read_text())
    value["scientific_Q_credit"] = 1
    _write(proofs[0], value)
    with pytest.raises(module.FieldIncrementError, match="scientific Q credit"):
        module.build(base_index=base, proofs=proofs, output_dir=tmp_path / "increment")


def test_requires_all_eight_distinct_case_rows(tmp_path: Path) -> None:
    module, base, proofs = _fixture(tmp_path)
    with pytest.raises(module.FieldIncrementError, match="exactly eight"):
        module.build(base_index=base, proofs=proofs[:7], output_dir=tmp_path / "increment")
