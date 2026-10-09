from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_producer_role_contract_v1.py"
SPEC = importlib.util.spec_from_file_location("f6_producer_role_contract_v1_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    def metadata(name: str, value: dict) -> tuple[str, str]:
        path = tmp_path / name
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        return str(path), _sha(path)

    xml_path, xml_sha = metadata("case.xml.json", {"schema": "xml-metadata", "case": "F6_CASE_A"})
    def_path, def_sha = metadata("case.def.json", {"schema": "def-metadata", "case": "F6_CASE_A"})
    receipt_path, receipt_sha = metadata("producer-receipt.json", {"schema": "receipt", "status": "COMPLETED"})
    owner_path, owner_sha = metadata("owner.json", {"schema": "owner", "status": "PASS"})
    rigid_path, rigid_sha = metadata("rigid.json", {"schema": "rigid", "status": "PASS"})
    source_manifest = {
        "schema": "ds02.stage2.f6-initial-native-support-manifest.v8",
        "source_binding": {
            "continuous_owner_basis": "explicit XML fluid drawbox volume times rhop0",
            "continuous_owner_mass_kg": 1.25,
            "physical_massbody_kg": 0.5,
            "no_rescale": True,
        },
        "cases": [{
            "grid": "source_current", "identity_status": "PASS",
            "physical_case_id": "F6_CASE_A", "producer_case_id": "F6_CASE_A",
            "producer_attempt_id": "attempt-a", "producer_identity_v6": {
                "physical_case_id": "F6_CASE_A", "case_id": "F6_CASE_A",
                "attempt_id": "attempt-a", "physical_case_status": "PASS_ACTUAL_PRODUCER_REQUEST",
            },
            "domain_equivalence_v8": {
                "status": "PASS_DIRECT_PRODUCER_PHYSICAL_ID",
                "source_identity": {
                    "physical_case_id": "F6_CASE_A",
                    "source_bi4_path": str(tmp_path / "source.bi4"),
                    "source_bi4_sha256": "a" * 64,
                    "source_def_record": {"path": def_path, "sha256": def_sha},
                    "source_xml": {"path": xml_path, "sha256": xml_sha},
                    "source_receipt_path": receipt_path,
                    "source_receipt_sha256": receipt_sha,
                },
            },
            "domain_mapping_v6": {
                "owner_proof": {"path": owner_path, "sha256": owner_sha},
                "rigid_proof": {"path": rigid_path, "sha256": rigid_sha},
            },
            "deferred": {
                "native_bi4": {"path": str(tmp_path / "source.bi4"), "known_sha256": "a" * 64,
                                "stat_at_prepare": {"bytes": 10}}
            },
        }, {
            "grid": "coarse", "identity_status": "PASS", "physical_case_id": "F6_CASE_A",
        }],
    }
    manifest_path, _ = metadata("manifest.json", source_manifest)
    parent_path, _ = metadata("parent.json", {"schema": "ds02.request.v1", "case_id": "ROOT276"})
    plan_path, _ = metadata("plan.json", {"schema": "plan", "case_records": [{
        "physical_case_id": "F6_CASE_A", "historical_alias": "NONE",
        "actual_saved_mask_coverage": True,
        "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
        "status": "COMPLETED",
    }]})
    return Path(manifest_path), Path(parent_path), Path(plan_path), xml_path


def test_builds_source_only_contract_with_real_parent_entry(tmp_path: Path) -> None:
    manifest, parent, plan, _ = _fixture(tmp_path)
    output = tmp_path / "contract.json"
    result = MODULE.build_contract(manifest, parent, output_path=output, plan_path=plan)
    assert result["schema"] == MODULE.SCHEMA
    assert result["status"] == "SOURCE_PREPARED_CURRENT_PLAN_CHECKED"
    assert result["production_eligible"] is False
    assert result["cases"][0]["case_identity"]["historical_alias"] == "REQUIRE_CURRENT_PLAN_EXACT_NO_ALIAS"
    assert result["cases"][0]["owner_predicate"]["status"] == "SOURCE_BOUND_INITIAL_GEOMETRY_ONLY"
    assert result["cases"][0]["event_roles"]["region_owner"].startswith("UNKNOWN")
    assert result["plan_admission"]["F6_CASE_A"]["admitted"] is True
    assert json.loads(output.read_text())["launch_performed"] is False


def test_historical_alias_is_not_admitted(tmp_path: Path) -> None:
    manifest, parent, plan, _ = _fixture(tmp_path)
    value = json.loads(plan.read_text())
    value["case_records"][0]["historical_alias"] = "HISTORICAL_ALIAS_UNRESOLVED"
    plan.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.F6ProducerRoleContractError, match="CURRENT plan case.*not admissible"):
        MODULE.build_contract(manifest, parent, plan_path=plan)


def test_payload_sources_are_deferred_without_content_read(tmp_path: Path) -> None:
    manifest, parent, _, _ = _fixture(tmp_path)
    result = MODULE.build_contract(manifest, parent)
    case = result["cases"][0]
    deferred = case["producer_role"]["deferred_roles"]
    assert deferred and all(item["content_read_by_builder"] is False for item in deferred)
    assert all(item["deferred_until_parent_after_reservation"] for item in deferred)
