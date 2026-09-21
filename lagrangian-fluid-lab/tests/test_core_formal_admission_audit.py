"""Regression tests for the read-only F3/F4 formal admission audit."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.core_formal_admission_audit import _is_qualification, audit_admission, main


ROOT = Path(__file__).resolve().parents[1]
F3_MANIFEST = ROOT / "campaigns/core-v1/f3-dataset-v2.json"
F4_MANIFEST = ROOT / (
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "f4-tallwall120-formal-reader-manifest-v2-compact.json"
)
F3_QUALIFICATION = ROOT / "campaigns/core-v1/evidence/f3-inherited-qualification.json"
F3_ADAPTER = ROOT / "campaigns/core-v1/evidence/f3-legacy-hard-audit-adapter-v1.json"
F3_STRUCTURAL_ADAPTER = ROOT / "campaigns/core-v1/evidence/f3-structural-audit-adapter-v1.json"
F4_QUALIFICATION = ROOT / "campaigns/core-v1/evidence/f4-tallwall120-formal-qualification-20260920.json"
PROFILE = ROOT / "campaigns/core-v1/learning/backward-resource-measurements.json"
PREPROFILE = ROOT / "campaigns/core-v1/learning/formal-preprofile-v3/index.json"
RESOURCE_DRYRUN = ROOT / (
    "campaigns/core-v1/learning/formal-release-candidate-v1/"
    "resource-frontier-dryrun-mlp-seed17-32000.json"
)
GRAPH_PROBE = ROOT / (
    "campaigns/core-v1/learning/formal-release-candidate-v2/"
    "full-field-graph-raw-capacity-probe-f4-train0-4updates-v2.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _real_audit() -> dict:
    return audit_admission(
        [F3_MANIFEST, F4_MANIFEST],
        evidence=[F3_QUALIFICATION, F3_ADAPTER, F3_STRUCTURAL_ADAPTER, F4_QUALIFICATION],
        data_root=ROOT,
        code_root=ROOT,
        preprofile_index=PREPROFILE,
        resource_profile=PROFILE,
        resource_dryrun=RESOURCE_DRYRUN,
        graph_probe=GRAPH_PROBE,
    )


def test_real_f3_f4_audit_keeps_the_hard_and_structural_denominators() -> None:
    report = _real_audit()

    assert report["status"] == "blocked"
    assert report["formal_admission"] is False
    assert report["formal_job_count"] == 0
    assert report["required_formal_job_count"] == 9
    assert report["family_summary"]["families"] == ["F3", "F4"]
    assert report["family_summary"]["split_counts"] == {
        "F3": {"train": 16, "validation": 4, "test": 12},
        "F4": {"train": 16, "validation": 4, "test": 12},
    }
    denominator = report["production_denominator"]
    assert denominator["included_case_count"] == 64
    assert denominator["hard_integrity_pass_bound_count"] == 64
    assert denominator["structural_pass_bound_count"] == 64
    assert denominator["formal_audit_pass_count"] == 64
    assert denominator["failed_or_unresolved_case_count"] == 0
    assert denominator["structural_gap_case_ids"] == []
    assert denominator["failure_denominator_preserved"] is True
    assert report["resource_dryrun"]["valid"] is True
    assert report["resource_dryrun"]["updates_completed"] == 32000
    assert report["graph_probe"]["valid"] is True
    assert report["graph_probe"]["updates"]["estimate_is_extrapolation"] is True
    assert report["graph_probe"]["updates"]["estimated_32000_full_pipeline_hours"] > 100
    assert {item["code"] for item in report["blockers"]} == {
        "FORMAL_RELEASE_REQUIRED",
        "RESOURCE_FRONTIER_UNPROVEN",
        "STALE_SOURCE_CLOSURE",
        "THIRD_FAMILY_REQUIRED",
        "VALIDATION_DENOMINATOR",
    }


def test_structural_receipt_set_has_32_immutable_case_bindings() -> None:
    adapter = json.loads(F3_STRUCTURAL_ADAPTER.read_text())
    assert adapter["schema"] == "core.f3.structural_audit_adapter.v1"
    assert adapter["case_count"] == 32
    assert adapter["structural_pass"] is True
    for reference in adapter["cases"]:
        receipt_path = ROOT / reference["path"]
        assert receipt_path.is_file()
        assert _sha256(receipt_path) == reference["sha256"]
        receipt = json.loads(receipt_path.read_text())
        assert receipt["schema"] == "core.f3.structural_audit_receipt.v1"
        assert receipt["manifest_binding"]["sha256"] == adapter["manifest_sha256"]
        assert receipt["structural_pass"] is True
        assert set(receipt["checks"]) == {
            "particle_axis", "finite_values", "lifecycle", "units", "wall_opening",
        }


def test_tampered_structural_receipt_reference_is_rejected(tmp_path: Path) -> None:
    adapter = json.loads(F3_STRUCTURAL_ADAPTER.read_text())
    adapter["cases"][0]["sha256"] = "0" * 64
    tampered = tmp_path / "structural-adapter.json"
    tampered.write_text(json.dumps(adapter))

    report = audit_admission(
        [F3_MANIFEST, F4_MANIFEST],
        evidence=[F3_ADAPTER, tampered, F4_QUALIFICATION],
        data_root=ROOT,
        code_root=ROOT,
        preprofile_index=PREPROFILE,
        resource_profile=PROFILE,
        graph_probe=GRAPH_PROBE,
    )

    assert "STRUCTURAL_RECEIPT_BINDING_GAP" in {item["code"] for item in report["blockers"]}
    assert report["production_denominator"]["structural_pass_bound_count"] == 63


def test_unbound_external_adapter_cannot_mask_audit_failure(tmp_path: Path) -> None:
    manifest = {
        "schema": "core.dataset.v2",
        "dataset_id": "fixture",
        "formal_release": False,
        "cases": [{
            "case_id": "F3_fixture_00",
            "physical_case_id": "physical-00",
            "lineage_group_id": "lineage-00",
            "family": "F3",
            "split": "validation",
            "known_inputs_ref": {
                "geometry": {"path": "geometry.npz"},
                "control": {"path": "control.npz"},
            },
        }],
    }
    adapter = {
        "schema": "core.f3.legacy_hard_audit_adapter.v1",
        "manifest_sha256": "0" * 64,
        "cases": [{"case_id": "F3_fixture_00", "family": "F3",
                    "hard_integrity_pass": True, "structural_pass": True}],
    }

    report = audit_admission([manifest], data_root=tmp_path, evidence=[adapter])

    assert report["production_denominator"]["included_case_count"] == 1
    assert report["production_denominator"]["hard_integrity_pass_bound_count"] == 0
    assert report["production_denominator"]["structural_pass_bound_count"] == 0
    assert report["production_denominator"]["failure_denominator_preserved"] is True
    assert "HARD_AUDIT_GAP" in {item["code"] for item in report["blockers"]}
    assert "STRUCTURAL_AUDIT_GAP" in {item["code"] for item in report["blockers"]}


def test_explanatory_none_claim_remains_in_the_production_denominator() -> None:
    assert _is_qualification({
        "stage": "production",
        "qualification_claim": "none; one case cannot establish range qualification",
    }) is False
    assert _is_qualification({
        "stage": "production",
        "qualification_claim": "formal range qualification",
    }) is True


def test_cli_writes_a_digest_and_never_emits_formal_jobs(tmp_path: Path) -> None:
    output = tmp_path / "admission.json"
    digest = tmp_path / "admission.json.sha256"
    exit_code = main([
        "--manifest", str(F3_MANIFEST), "--manifest", str(F4_MANIFEST),
        "--evidence", str(F3_QUALIFICATION), "--evidence", str(F3_ADAPTER),
        "--evidence", str(F3_STRUCTURAL_ADAPTER), "--evidence", str(F4_QUALIFICATION),
        "--data-root", str(ROOT),
        "--code-root", str(ROOT), "--preprofile-index", str(PREPROFILE),
        "--resource-profile", str(PROFILE), "--output", str(output),
        "--resource-dryrun", str(RESOURCE_DRYRUN),
        "--graph-probe", str(GRAPH_PROBE),
        "--sha256-output", str(digest),
    ])

    assert exit_code == 2
    report = json.loads(output.read_text())
    assert report["execution_constraints"]["read_only"] is True
    assert report["execution_constraints"]["formal_runs_started"] == 0
    assert report["execution_constraints"]["central_registry_mutation"] == 0
    assert report["execution_constraints"]["central_ledger_mutation"] == 0
    assert report["diagnostic_exclusion"]["diagnostic_runs_counted_as_formal"] is False
    assert report["production_denominator"]["structural_pass_bound_count"] == 64
    digest_text = digest.read_text().strip()
    assert digest_text.endswith("  admission.json")
    assert digest_text.split()[0]
