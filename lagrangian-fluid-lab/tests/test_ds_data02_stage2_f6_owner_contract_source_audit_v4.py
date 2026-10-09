from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_owner_contract_source_audit_v4.py"
REQUEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f6-owner-contract-source-audit-v4-root-prepared-170-001/"
    / "f6-owner-contract-source-audit-v4-request.json"
)
MANIFEST = REQUEST.with_name("f6-owner-contract-source-audit-v4-manifest.json")


def module():
    spec = importlib.util.spec_from_file_location("f6_owner_contract_source_audit_v4", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_source_audit_binds_parser_and_keeps_owner_unknown():
    loaded = module()
    report = loaded.derive(MANIFEST)
    assert report["schema"] == loaded.SCHEMA
    assert report["status"] == "F6_OWNER_CONTRACT_SOURCE_BOUND_BODY_EXPLICIT_FLUID_OWNER_UNLINKED"
    assert len(report["definition_rows"]) == 6
    assert sorted(report["source_contract_findings"]["dp_values_m"]) == [0.02, 0.025, 0.03125]
    assert report["source_contract_findings"]["body_mass_kg"] == pytest.approx(128.0)
    assert report["source_contract_findings"]["fluid_selector_volume_is_not_owner_mass"] is True
    assert report["source_contract_findings"]["continuous_fluid_owner_contract"] == loaded.UNKNOWN_OWNER
    assert report["parser_evidence"]["interpretation"]["fluid_owner_contract_in_parser"] is False
    assert report["qualification"] == {
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "dynamics": "UNKNOWN",
    }
    assert report["read_policy"]["particle_arrays_read"] is False


def test_source_contract_rejects_owner_marker_in_xml(tmp_path: Path):
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    definition_ref = next(ref for ref in manifest["source_refs"] if ref["key"] == "definition_f6_s1_coarse")
    source = Path(definition_ref["path"]).read_text(encoding="utf-8")
    modified = tmp_path / "owner-marked.xml"
    modified.write_text(source.replace('<drawbox cmt=', '<drawbox owner="continuum" cmt=', 1), encoding="utf-8")
    definition_ref.update(loaded.record(modified))
    definition_ref["key"] = "definition_f6_s1_coarse"
    altered_manifest = tmp_path / "manifest.json"
    altered_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(loaded.ContractError, match="unexpectedly declares owner token"):
        loaded.derive(altered_manifest)


def test_manifest_and_request_are_portable_and_payload_free():
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    declared_manifest = Path(request["command"][3]).resolve()
    assert declared_manifest == MANIFEST.resolve()
    assert loaded.sha256_file(declared_manifest) == request["input_sha256"][str(declared_manifest)]
    assert request["cpu_task_kind"] == "audit"
    assert request["launch_allowed"] is False
    assert request["hdf5_read"] is False
    assert request["estimated_native_read_bytes"] == 0
    assert request["estimated_hdf5_read_bytes"] == 0
    assert request["estimated_bi4_read_bytes"] == 0
    assert request["estimated_obi4_read_bytes"] == 0
    assert manifest["contract"]["h5_bi4_obi4_vtk_forbidden"] is True
    assert manifest["contract"]["solver_or_gencase_forbidden"] is True
    assert all(Path(ref["path"]).suffix.lower() not in loaded.FORBIDDEN_SUFFIXES for ref in manifest["source_refs"])
    assert all(Path(ref["path"]).suffix.lower() in {".xml", ".cpp", ".h", ".json"} for ref in manifest["source_refs"])


def test_parser_source_contract_does_not_accept_fluid_body_fields():
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths, records = loaded.load_sources(manifest)
    evidence = loaded.source_parser_evidence(paths, records)
    assert evidence["JCasePartBlock_Fluid"]["body_or_owner_fields"] == []
    assert evidence["JCaseParts_dispatch"]["separate_fluid_and_floating_blocks"] is True
