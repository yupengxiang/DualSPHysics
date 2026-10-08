from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_f6_family_card_v1.py"
REQUEST = ROOT / "campaigns/ds-data-02/stage2/requests/f3-f6-family-card-v1-root-forward-113-001/f3-f6-family-card-v1-request.json"


def module():
    spec = importlib.util.spec_from_file_location("f3_f6_family_card_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _row(family: str, index: int, *, native: int | None = None) -> dict:
    row = {
        "case_key": f"{family}/case-{index:03d}",
        "current": {"family_id": family},
        "qualification_dimensions": {"error_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
    }
    if native is not None:
        row["native_omission"] = {
            "native_count": native,
            "native_exit_cause_counts": {"NUMERICAL_POSITION_EXCLUSION": native},
            "native_motive": "position",
        }
    return row


def sources(tmp_path: Path):
    files: dict[str, Path] = {}
    files["v27_product"] = write_json(tmp_path / "v27-product.json", {
        "schema": "ds02.stage2.final-family-product.v27",
        "status": "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION",
        "coverage": {
            "current_case_count": 336,
            "native_alias_cases": 118,
            "native_alias_ids": 1328,
            "family_counts": {f"F{i}": 48 for i in range(1, 8)},
        },
        "family_cards": {
            family: {
                "schema": "ds02.stage2.family-card.v27",
                "family_id": family,
                "task_eligibility": {
                    "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                    "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
                    "saved_frame_artifact": "ELIGIBLE_LIMITED_SAVED_FRAME_DIAGNOSTICS",
                    "source_role_mass_bookkeeping": "ELIGIBLE_SOURCE_ROLE_BOOKKEEPING_ONLY",
                    "native_cause_alias_join": "ELIGIBLE_EXACT_118_ALIAS_CASES",
                },
            }
            for family in ("F3", "F6")
        },
    })
    files["v27_manifest"] = write_json(tmp_path / "v27-manifest.json", {"schema": "manifest"})
    files["v27_receipt"] = write_json(tmp_path / "v27-receipt.json", {"schema": "receipt"})
    rows = [_row("F3", i) for i in range(48)]
    rows.extend(_row("F6", i, native=4 if i < 47 else 11) for i in range(48))
    files["v29_catalog"] = write_json(tmp_path / "v29.json", {
        "schema": "ds02.stage2.final-qualification-catalog.v29",
        "status": "ACTUAL_336_CASE_AUDIT_AND_118_NATIVE_IMPACT_BOUND_NO_SCIENTIFIC_QUALIFICATION",
        "coverage": {"current_cases": 336, "audit_native_intersection": 118, "all_qn_qe_qi_unknown": True},
        "cases": rows,
    })
    files["impact_ledger"] = write_json(tmp_path / "impact.json", {
        "schema": "ds02.stage2.omission-impact-ledger.v2",
        "status": "IMPACT_LEDGER_SOURCE_CLOSED_WITH_FATE_AND_DYNAMICS_UNKNOWN",
        "coverage": {
            "case_count": 118, "full_source_case_count": 118,
            "family_counts": {"F2": 48, "F4": 22, "F6": 48},
            "native_cause_counts": {"NUMERICAL_DENSITY_EXCLUSION": 51, "NUMERICAL_POSITION_EXCLUSION": 1277},
        },
    })
    files["access_provenance"] = write_json(tmp_path / "access.json", {
        "schema": "ds02.stage2.product-access-provenance.v1",
        "status": "ACTUAL_V28_V30_METADATA_PROVENANCE_NO_REDISTRIBUTION_DETERMINATION",
        "access_boundary": {
            "internal_workspace_access": "OBSERVED_READ_ONLY",
            "external_access": "UNKNOWN_NOT_ESTABLISHED",
            "redistribution": "UNKNOWN_NOT_ESTABLISHED; legal review and artifact policy are outside this sidecar",
        },
    })
    files["f3_gencase_report"] = write_json(tmp_path / "f3-gencase.json", {
        "schema": "ds02.stage2.f3.s2.commensurate-dp003-gencase.v1",
        "status": "COMPLETED_F3_S2_COMMENSURATE_DP003_GENCASE",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "scope": {"solver_started": False, "trajectory_h5_read": False},
        "prior_support_summary": {"historical_dp0048_hardfail_preserved": True},
    })
    files["f3_gencase_receipt"] = write_json(tmp_path / "f3-gencase-receipt.json", {"status": "completed"})
    f3_owner = {"low_m": [-0.45, -0.09, 0.0], "size_m": [0.9, 0.18, 0.09], "tank_size_m": [0.9, 0.18, 0.51], "mass_kg": 14.58}
    files["f3_support_report"] = write_json(tmp_path / "f3-support.json", {
        "schema": "ds02.stage2.f3.s2.dp003.initial-support-qa.v1",
        "status": "COMPLETED_F3_S2_DP003_INITIAL_SUPPORT_SOURCE_CLOSED",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "source": {"continuous_owner": f3_owner},
        "candidate": {
            "actual_counts_authoritative": True,
            "preflight_estimate_is_not_count_evidence": True,
            "generated_xml_summary_actual": {"dp_m": 0.003, "counts": {"fluid": 540000}, "sample_fluid_mass_kg": 14.58, "massfluid_kg": 0.000027},
        },
        "vtk_support": {
            "fluid": {
                "point_count": 540000, "idp_count": 540000,
                "axis_summary": {axis: {"unique_count": count} for axis, count in (("x", 300), ("y", 60), ("z", 30))},
                "owner_relation": {"outside_closed_count": 0},
            },
        },
        "scope": {"solver_started": False},
        "scientific_status": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
    })
    files["f3_support_receipt"] = write_json(tmp_path / "f3-support-receipt.json", {"status": "completed"})
    f6_rows = []
    for sentinel in ("F6-1", "F6-2"):
        for grid, dp, count, mass in (("coarse", 0.03125, 166400, 5078.125), ("original", 0.025, 327680, 5120.0), ("fine", 0.02, 613119, 4904.952)):
            f6_rows.append({
                "sentinel_id": sentinel, "grid_id": grid, "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025", "dp_m": dp,
                "continuous_fluid_owner_authority": "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT",
                "drawbox_volume_mass_is_not_owner": True,
                "generated_particle_summary": {"counts": {"fluid": count}, "massfluid_kg": mass / count, "fluid_sample_mass_kg": mass},
                "body_contract": {"massbody_kg": 128.0},
                "fluid_sample": {"gate": "PASS_TARGET_ONE_PERCENT_DIAGNOSTIC", "basis": "discrete sample; not continuum owner"},
            })
    files["f6_owner_report"] = write_json(tmp_path / "f6-owner.json", {
        "schema": "ds02.stage2.f6.fluid-owner-authority-audit.v3",
        "status": "COMPLETED_F6_FLUID_OWNER_AUTHORITY_XML_SOURCE_PROJECTION_AUDIT",
        "owner_authority": {
            "continuous_fluid_owner": "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT",
            "reason": "drawbox selector has no linked continuous owner contract",
            "body_mass_is_separate": True, "physical_body_mass_kg": 128.0,
            "drawbox_volume_or_rho_volume_must_not_be_promoted": True,
        },
        "rows": f6_rows,
    })
    files["f6_owner_receipt"] = write_json(tmp_path / "f6-owner-receipt.json", {"status": "completed"})
    files["f6_mass_semantics"] = write_json(tmp_path / "f6-mass.json", {
        "schema": "ds02.stage2.sentinel.initial-frame-equivalence.v2.3", "status": "PASS",
        "scope": {"solver_started": False},
        "mass_semantics": {
            "sample_mass": {"by_type": {
                "2": {"sample_mass_total_kg": 256.0}, "3": {"sample_mass_total_kg": 5120.0},
            }},
            "physical_rigid_body": {"bodies": [{"massbody_kg": 128.0}]},
            "interpretation": "sample_mass and physical_rigid_body.massbody are separate quantities; no floating-particle sum is used as rigid-body mass",
        },
    })
    return files


def manifest_for(tmp_path: Path, files: dict[str, Path]) -> Path:
    loaded = module()
    refs = [{"key": key, "path": str(path), "sha256": loaded.sha256_file(path)} for key, path in files.items()]
    return write_json(tmp_path / "manifest.json", {"schema": "ds02.stage2.f3-f6.family-card.manifest.v1", "source_refs": refs})


def test_derives_f3_f6_initial_metadata_and_preserves_unknowns(tmp_path: Path):
    loaded = module()
    result = loaded.derive(manifest_for(tmp_path, sources(tmp_path)))
    assert result["status"] == "PREPARED_F3_F6_ADDITIVE_CARD_METADATA_ONLY"
    assert result["current336_identity_preservation"]["current_case_count"] == 336
    assert result["native_exclusion_accounting"]["F3"]["native_id_count"] == 0
    assert result["native_exclusion_accounting"]["F6"]["native_id_count"] == 199
    assert result["family_cards"]["F3"]["source_closed_initial_owner"]["mass_kg"] == pytest.approx(14.58)
    assert result["family_cards"]["F3"]["root104_initial_support"]["actual_support_axis_counts"] == {"x": 300, "y": 60, "z": 30}
    f6 = result["family_cards"]["F6"]
    assert f6["generated_owner_semantics"]["continuous_fluid_owner"] == "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT"
    assert f6["mass_semantics"]["physical_rigid_body_mass_kg"] == pytest.approx(128.0)
    assert f6["mass_semantics"]["floating_sample_mass_total_kg"] == pytest.approx(256.0)
    assert f6["task_eligibility"]["QN"] == "UNKNOWN"


def test_rejects_f3_support_axis_mismatch(tmp_path: Path):
    loaded = module()
    files = sources(tmp_path)
    path = files["f3_support_report"]
    value = json.loads(path.read_text(encoding="utf-8"))
    value["vtk_support"]["fluid"]["axis_summary"]["x"]["unique_count"] = 301
    write_json(path, value)
    with pytest.raises(loaded.CardError, match="axis counts differ"):
        loaded.derive(manifest_for(tmp_path, files))


def test_rejects_f6_owner_promotion(tmp_path: Path):
    loaded = module()
    files = sources(tmp_path)
    path = files["f6_owner_report"]
    value = json.loads(path.read_text(encoding="utf-8"))
    value["owner_authority"]["continuous_fluid_owner"] = "EXPLICIT_CONTINUOUS_OWNER"
    write_json(path, value)
    with pytest.raises(loaded.CardError, match="unexpectedly promotes"):
        loaded.derive(manifest_for(tmp_path, files))


def test_v8_request_uses_cpu_audit_contract():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["schema"] == "ds02.request.v1"
    assert request["cpu_task_kind"] == "audit"
    assert request["kind"] == "cpu"
    assert request["hdf5_read"] is False
    assert request["bi4_read"] is False
    assert request["estimated_native_read_bytes"] == 0
    assert request["estimated_hdf5_read_bytes"] == 0
    assert request["estimated_bi4_read_bytes"] == 0
    assert request["source_binding"]["root_rebasable_cli"] is True
    assert all(Path(path).suffix.lower() not in {".h5", ".hdf5", ".bi4", ".obi4"} for path in request["input_files"])
