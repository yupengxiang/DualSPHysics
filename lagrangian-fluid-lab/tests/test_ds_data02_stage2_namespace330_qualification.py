from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace330_qualification.py"


def _load():
    spec = importlib.util.spec_from_file_location("namespace330", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N330 = _load()


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> dict[str, Path]:
    current_rows = []
    audit_rows = []
    lifecycle_rows = []
    v26_rows = []
    for index in range(336):
        family = f"F{index // 48 + 1}"
        case_id = f"{family}_CANONICAL_{index:03d}"
        alias = f"legacy-{index:03d}" if index == 3 else "NONE"
        current_rows.append({
            "family_id": family,
            "physical_case_id": case_id,
            "runtime_case_alias": alias,
            "manifest": {"path": f"/provenance/{case_id}/manifest.json", "sha256": "a" * 64},
            "xmf": {"path": f"/provenance/{case_id}/case.xmf", "sha256": "b" * 64},
            "trajectory": {"path": f"/payload/{case_id}/trajectory.h5", "producer_declared_sha256": "c" * 64,
                           "bytes": 1024, "mtime_ns": 5},
            "conversion_report": {"path": f"/provenance/{case_id}/conversion-report.json", "sha256": "d" * 64},
            "raw_root": {"path": f"/payload/{case_id}/raw", "accessible": True},
            "source_bindings": {"owner_metadata": {"path": f"/provenance/{case_id}/owner.json", "sha256": "e" * 64}},
            "quality": {"visual": "STAGE1_PRESERVED"},
        })
        audit_rows.append({
            "family_id": family, "physical_case_id": case_id, "scan_status": "SCANNED",
            "frames": 8, "fluid_initial_mass_kg": 1.5 + index,
            "fluid_cumulative_unique_missing": 1 if index == 4 else 0,
            "fluid_missing_final_count": 1 if index == 4 else 0,
            "field_failures": ["density"] if index == 4 else [],
            "QI_dynamics": "NOT_ASSESSED", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
            "scan_sha256": "f" * 64, "receipt_sha256": "1" * 64,
        })
        lifecycle_rows.append({
            "current_index": index, "family_id": family, "physical_case_id": case_id,
            "historical_alias": "HISTORICAL_ALIAS_REVIEW_REQUIRED" if index == 3 else "NONE",
            "actual_saved_mask_coverage": index % 2 == 0,
            "attempt_lineage": [], "scientific_credit": "NONE",
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
            "status": "ACTUAL_SAVED_MASK_COMPLETED" if index % 2 == 0 else "UNSCHEDULED_EXACT_CURRENT_AUDIT",
            "group_id": f"{family}-group-{index % 4}",
        })
        v26_rows.append({
            "current_index": index, "family_id": family, "physical_case_id": case_id,
            "runtime_case_alias": alias, "group_id": f"{family}:UNKNOWN:{index % 4}",
            "group_status": "UNKNOWN_CONSERVATIVE_GROUP", "case_sha256": "2" * 64,
            "gaps": ["trajectory_h5_content_deferred_to_parent_guard"],
            "case_path": f"/metadata/{case_id}.json",
        })
    current = {"schema": "ds02.stage2.current336.v1", "source_catalog": "/provenance/CASES_336.json",
               "source_catalog_sha256": "3" * 64, "cases": current_rows,
               "scope": "metadata", "unresolved": 0}
    audit = {"schema": "ds02.stage2.scientific-audit-independent-verification.v23",
             "distinct_completed_cases": 336, "verified_cases": audit_rows,
             "current_catalog": {"path": "CURRENT336.json", "sha256": "4" * 64},
             "goal_complete": False}
    lifecycle = {"schema": "ds02.stage2.typed-lifecycle-continuation-plan.v4",
                 "case_records": lifecycle_rows,
                 "coverage": {"current_cases": 336, "exact_current_audit_rows": 335,
                              "actual_saved_mask_cases": 168},
                 "source_read_policy": {"native_or_bi4_opened": False,
                                         "trajectory_content_opened": False},
                 "qualification_boundary": dict(N330.UNKNOWN_QUALIFICATION)}
    v26 = {"schema": N330.V26_SCHEMA, "cases": v26_rows,
           "coverage": {"case_count": 336}, "sha256": "5" * 64}
    source_access = {"schema": "ds02.stage2.seven-family-source-access-index.v23",
                     "dependencies_and_licenses": {"repository_license": "UNKNOWN"}}
    native = {"schema": "proof.native.v1", "status": "PASS_SCOPE_ONLY",
              "scope": "native accounting only", "qualification": dict(N330.UNKNOWN_QUALIFICATION)}
    mass = {"schema": "proof.mass.v1", "status": "PASS_PREREQUISITE_ONLY",
            "scope": "mass support prerequisite", "qualification": dict(N330.UNKNOWN_QUALIFICATION)}
    paths = {
        "current": _write(tmp_path / "CURRENT336.json", current),
        "audit": _write(tmp_path / "audit23.json", audit),
        "lifecycle": _write(tmp_path / "lifecycle.json", lifecycle),
        "v26": _write(tmp_path / "v26.json", v26),
        "access": _write(tmp_path / "access.json", source_access),
        "native": _write(tmp_path / "native.json", native),
        "mass": _write(tmp_path / "mass.json", mass),
    }
    return paths


def test_namespace330_builds_loader_checked_336_case_cards(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    result = N330.build_namespace330(
        current_path=paths["current"], audit_path=paths["audit"], lifecycle_path=paths["lifecycle"],
        v26_path=paths["v26"], output_dir=tmp_path / "namespace330",
        source_access_path=paths["access"], native_proof_paths=[paths["native"]],
        mass_proof_paths=[paths["mass"]])
    assert result["case_count"] == 336
    loaded = N330.load_namespace330(tmp_path / "namespace330")
    assert loaded["case_count"] == 336
    assert loaded["family_counts"] == {f"F{i}": 48 for i in range(1, 8)}

    catalog = json.loads((tmp_path / "namespace330/namespace330-qualification-catalog.json").read_text())
    row = catalog["cases"][3]
    assert row["canonical_case_id"] == "F1_CANONICAL_003"
    assert row["identity"]["identity_status"] == "UNKNOWN_IDENTITY"
    assert row["identity"]["runtime_alias_status"] == "PROVENANCE_ONLY"
    assert row["identity"]["canonical_not_replaced_by_alias"] is True
    assert row["split"]["status"] == "UNASSIGNED"
    assert row["qualification"] == N330.UNKNOWN_QUALIFICATION
    assert row["quality"]["impact"]["fluid_initial_mass_kg"] == pytest.approx(4.5)
    assert row["physical"]["physical_fate"] == "UNKNOWN"


def test_namespace330_keeps_unknown_lineage_in_family_union(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    result = N330.build_namespace330(
        current_path=paths["current"], audit_path=paths["audit"], lifecycle_path=paths["lifecycle"],
        v26_path=paths["v26"], output_dir=tmp_path / "namespace330")
    catalog = json.loads(Path(result["catalog_path"]).read_text())
    family_groups = {row["split"]["leakage_union_group_id"] for row in catalog["cases"][:48]}
    assert family_groups == {"F1:UNKNOWN_PHYSICAL_LINEAGE"}
    assert all(row["split"]["role"] is None for row in catalog["cases"])
    assert all(row["hidden_test"] is False for row in catalog["cases"])


def test_namespace330_loader_rejects_promoted_quality_and_stale_card(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    N330.build_namespace330(current_path=paths["current"], audit_path=paths["audit"],
                            lifecycle_path=paths["lifecycle"], v26_path=paths["v26"],
                            output_dir=tmp_path / "namespace330")
    catalog_path = tmp_path / "namespace330/namespace330-qualification-catalog.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["cases"][0]["qualification"]["QI"] = "QUALIFIED"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(N330.Namespace330Error, match="schema/SHA mismatch"):
        N330.load_namespace330(tmp_path / "namespace330")


def test_namespace330_refuses_duplicate_canonical_ids(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    current = json.loads(paths["current"].read_text())
    current["cases"][1]["physical_case_id"] = current["cases"][0]["physical_case_id"]
    paths["current"].write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(N330.Namespace330Error, match="missing/duplicated"):
        N330.build_namespace330(current_path=paths["current"], audit_path=paths["audit"],
                                lifecycle_path=paths["lifecycle"], v26_path=paths["v26"],
                                output_dir=tmp_path / "namespace330")
