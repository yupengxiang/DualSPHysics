from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_family_card_v1.py"


def module():
    spec = importlib.util.spec_from_file_location("f2_family_card_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def sources(tmp_path: Path):
    rows = []
    for index in range(48):
        count = 118 if index == 0 else 20
        if index == 47:
            count = 40
        rows.append({
            "case_key": f"F2/case-{index:03d}",
            "native_omission": {
                "native_count": count,
                "native_exit_cause_counts": {"NUMERICAL_POSITION_EXCLUSION": count},
                "native_motive": "position",
                "conversion_omission": "UNKNOWN_NOT_BOUND_BY_CONVERSION_RECEIPT",
                "source_closure": {"status": "FULL_PROBE_SOURCE_CLOSED"},
                "source_visible_mass": {"screen": "mass_screen_subset_below_gate"},
            },
        })
    assert sum(row["native_omission"]["native_count"] for row in rows) == 1078
    files = {}
    files["v27_product"] = write_json(tmp_path / "v27-product.json", {
        "schema": "ds02.stage2.final-family-product.v27",
        "status": "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION",
        "coverage": {"current_case_count": 336, "native_alias_cases": 118},
        "family_cards": {"F2": {"schema": "ds02.stage2.family-card.v27", "family_id": "F2", "task_eligibility": {"QN": "UNKNOWN"}}},
    })
    files["v27_manifest"] = write_json(tmp_path / "v27-manifest.json", {"schema": "manifest"})
    files["v27_receipt"] = write_json(tmp_path / "v27-receipt.json", {"schema": "receipt"})
    files["v29_catalog"] = write_json(tmp_path / "v29.json", {
        "schema": "ds02.stage2.final-qualification-catalog.v29",
        "status": "ACTUAL_336_CASE_AUDIT_AND_118_NATIVE_IMPACT_BOUND_NO_SCIENTIFIC_QUALIFICATION",
        "cases": rows,
    })
    files["v30_catalog"] = write_json(tmp_path / "v30.json", {
        "schema": "ds02.stage2.task-scope-catalog.v30",
        "status": "ACTUAL_V29_TASK_SCOPE_INDEX_WITH_QN_QE_QI_UNKNOWN",
        "cases": [{"case_key": f"F2/case-{index:03d}", "error_qualification": {"QN": "UNKNOWN"}} for index in range(48)],
    })
    files["v30_manifest"] = write_json(tmp_path / "v30-manifest.json", {"schema": "manifest"})
    files["native_identity_audit"] = write_json(tmp_path / "identity.json", {
        "schema": "ds02.stage2.native-identity-audit.v2",
        "native_id_count": 1328,
        "family_counts": {"F2": {"cases": 48}},
    })
    files["impact_ledger"] = write_json(tmp_path / "impact.json", {
        "schema": "ds02.stage2.omission-impact-ledger.v2",
        "status": "IMPACT_LEDGER_SOURCE_CLOSED_WITH_FATE_AND_DYNAMICS_UNKNOWN",
        "coverage": {"case_count": 118, "family_counts": {"F2": 48}},
    })
    files["root105_report"] = write_json(tmp_path / "root105.json", {
        "schema": "ds02.stage2.f2.coarse-canary-native-qa.v1",
        "status": "COMPLETED_F2_COARSE_CANARY_NATIVE_IDENTITY_MOTIVE_QA",
        "generated_particles": {
            "fluid_count": 27750,
            "massfluid_kg": 0.000681472,
            "fluid_blocks": [{"count": 9250, "mk": mk} for mk in (1, 2, 3)],
        },
        "native_identity": {"rows": [{"motive": "position", "mk": 1, "initial_mass_kg": 0.000681472} for _ in range(153)]},
    })
    files["access_provenance"] = write_json(tmp_path / "access.json", {
        "schema": "ds02.stage2.product-access-provenance.v1",
        "status": "ACTUAL_V28_V30_METADATA_PROVENANCE_NO_REDISTRIBUTION_DETERMINATION",
        "access_boundary": {
            "redistribution": "UNKNOWN_NOT_ESTABLISHED; legal review and artifact policy are outside this sidecar",
            "internal_workspace_access": "OBSERVED_READ_ONLY_FOR_BOUND_METADATA_AND_LICENSE_PATHS",
            "external_access": "UNKNOWN_NOT_ESTABLISHED",
        },
    })
    return files


def manifest_for(tmp_path: Path, files: dict[str, Path], *, pending_status="PENDING_GUARDED_EXECUTION") -> Path:
    loaded = module()
    source_refs = []
    for key, path in files.items():
        source_refs.append({"key": key, "path": str(path), "sha256": loaded.sha256_file(path)})
    return write_json(tmp_path / "manifest.json", {
        "schema": "ds02.stage2.f2.family-card.manifest.v1",
        "source_refs": source_refs,
        "pending_root111": {"status": pending_status, "scientific_credit": "NONE_UNTIL_COMPLETED_RECEIPT"},
    })


def test_family_card_binds_current_ledgers_and_preserves_pending_stream(tmp_path: Path):
    loaded = module()
    source_files = sources(tmp_path)
    manifest = manifest_for(tmp_path, source_files)
    result = loaded.derive(manifest)
    assert result["status"] == "PREPARED_F2_ADDITIVE_CARD_ROOT111_PENDING"
    assert result["current336_and_118"]["f2_historical_native_id_count"] == 1078
    assert result["f2_source_owner_initial_axis"]["initial_fluid_count"] == 27750
    assert result["f2_source_owner_initial_axis"]["native153_lower_bound_fraction_whole_initial"] == pytest.approx(0.005513513513513513)
    assert result["root111_stream"]["execution_credit"] == "NONE_UNTIL_COMPLETED_RECEIPT"
    assert result["task_eligibility"]["QN"] == "UNKNOWN"
    assert result["access_and_permissions"]["redistribution"].startswith("UNKNOWN_NOT_ESTABLISHED")


def test_family_card_rejects_non_position_root105_motive(tmp_path: Path):
    loaded = module()
    source_files = sources(tmp_path)
    root105 = json.loads(source_files["root105_report"].read_text(encoding="utf-8"))
    root105["native_identity"]["rows"][0]["motive"] = "density"
    source_files["root105_report"] = write_json(source_files["root105_report"], root105)
    manifest = manifest_for(tmp_path, source_files)
    with pytest.raises(loaded.CardError, match="ROOT105 motive counts"):
        loaded.derive(manifest)


def test_family_card_rejects_pending_stream_as_completed(tmp_path: Path):
    loaded = module()
    source_files = sources(tmp_path)
    manifest = manifest_for(tmp_path, source_files, pending_status="COMPLETED")
    with pytest.raises(loaded.CardError, match="ROOT111 pending status"):
        loaded.derive(manifest)

