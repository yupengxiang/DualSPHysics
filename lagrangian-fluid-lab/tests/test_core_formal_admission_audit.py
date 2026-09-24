"""Regression tests for the read-only F3/F4 formal admission audit."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.core_formal_admission_audit import (
    _bound_adapter_cases,
    _evidence_rows,
    _is_qualification,
    audit_admission,
    main,
    sha256_file,
)


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

    implementation = report["audit_implementation"]
    implementation_path = ROOT / implementation["path"]
    assert implementation_path == ROOT / "scripts/core_formal_admission_audit.py"
    assert implementation["sha256"] == _sha256(implementation_path)
    assert implementation["bytes"] == implementation_path.stat().st_size
    assert report["status"] == "blocked"
    assert report["formal_admission"] is False
    assert report["formal_job_count"] == 0
    assert report["required_formal_job_count"] == 9
    assert report["family_summary"]["families"] == ["F3", "F4"]
    assert report["family_summary"]["t1_families"] == {"F3": True, "F4": True}
    assert report["family_summary"]["t1_family_count"] == 2
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


def test_synthetic_evidence_rejected_before_global_t1_extraction(tmp_path: Path) -> None:
    manifest = {
        "schema": "core.dataset.v2",
        "dataset_id": "global-evidence-schema-fixture",
        "formal_release": False,
        "cases": [{
            "case_id": "F3-fixture-00",
            "physical_case_id": "physical-F3-fixture-00",
            "lineage_group_id": "lineage-F3-fixture-00",
            "family": "F3",
            "scope_id": "scope-F3-fixture",
            "split": "train",
            "hdf5": "assets/F3-fixture-00.h5",
            "known_inputs_ref": {
                "geometry": {"path": "assets/F3-fixture-00-geometry.npz"},
                "control": {"path": "assets/F3-fixture-00-control.npz"},
            },
        }],
    }
    schemas = [
        "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v8",
        "unknown.evidence.v1",
        None,
        "core.qualification.v1",
    ]

    for schema in schemas:
        evidence = {
            "family": "F3",
            "scope_id": "scope-F3-fixture",
            "T1_numerical": True,
        }
        if schema is not None:
            evidence["schema"] = schema
        report = audit_admission([manifest], data_root=tmp_path, evidence=[evidence])
        accepted = schema == "core.qualification.v1"
        assert report["family_summary"]["t1_families"] == {"F3": accepted}
        assert report["family_summary"]["t1_family_count"] == int(accepted)
        assert report["formal_job_count"] == 0


def test_synthetic_case_rows_rejected_before_case_audit_binding(tmp_path: Path) -> None:
    case = {
        "case_id": "F3-synthetic-00",
        "physical_case_id": "physical-F3-synthetic-00",
        "lineage_group_id": "lineage-F3-synthetic-00",
        "family": "F3",
        "scope_id": "scope-F3-synthetic",
        "split": "train",
        "hdf5": "assets/F3-synthetic-00.h5",
        "known_inputs_ref": {
            "geometry": {"path": "assets/F3-synthetic-00-geometry.npz"},
            "control": {"path": "assets/F3-synthetic-00-control.npz"},
        },
    }
    diagnostic_rewrap = {
        "schema": "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v8",
        "mode": "synthetic_only",
        "evidence_class": "synthetic_non_qualifying",
        "diagnostic_outcome": "non_qualifying",
        "cases": [{
            "schema": "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v8",
            "case_id": case["case_id"],
            "family": "F3",
            "physical_case_id": case["physical_case_id"],
            "lineage_group_id": case["lineage_group_id"],
            "scope_id": "scope-F3-synthetic",
            "hard_integrity_pass": True,
            "structural_pass": True,
        }],
    }

    by_case, global_rows = _evidence_rows(diagnostic_rewrap)

    assert by_case == {}
    assert global_rows == []

    manifest = {
        "schema": "core.dataset.v2",
        "dataset_id": "synthetic-case-evidence-fixture",
        "formal_release": False,
        "cases": [case],
    }
    report = audit_admission(
        [manifest], data_root=tmp_path, code_root=tmp_path,
        evidence=[diagnostic_rewrap],
    )

    denominator = report["production_denominator"]
    assert denominator["included_case_count"] == 1
    assert denominator["hard_integrity_pass_bound_count"] == 0
    assert denominator["structural_pass_bound_count"] == 0
    assert denominator["formal_audit_pass_count"] == 0
    assert report["family_summary"]["t1_families"] == {"F3": False}
    assert report["formal_job_count"] == 0


def test_synthetic_adapter_rejected_before_case_binding(tmp_path: Path) -> None:
    class SchemaReadProbe(dict):
        def __init__(self):
            super().__init__({
                "schema": "core.f8.synthetic_diagnostic.v1",
                "manifest_sha256": "known-manifest",
                "T1_numerical": True,
                "cases": [{"case_id": "synthetic-case", "structural_pass": True}],
            })
            self.reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            if key != "schema":
                raise AssertionError(f"adapter field read before schema rejection: {key}")
            return super().get(key, default)

    probe = SchemaReadProbe()
    bound, adapter_present, errors = _bound_adapter_cases(
        [(probe, None)], manifest_hashes={"known-manifest"}, root=tmp_path
    )
    assert bound == {}
    assert adapter_present is False
    assert errors == []
    assert probe.reads == ["schema"]


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


def test_cross_manifest_duplicate_case_id_cannot_pass_a_complete_denominator(
    tmp_path: Path,
) -> None:
    """A duplicate split row used to make the 3-family gate pass fail-open.

    The two F3 manifest fragments below contain 32 rows in total and retain
    the exact 16/4/12 split shape, but the first train row is repeated and a
    different train row disappears.  Before the blocker was added,
    ``duplicate_case_ids`` was only reported and the synthetic admission
    reached ``ready`` with 96 rows and 96 bound audits.
    """

    def manifest_rows(family: str) -> list[dict]:
        rows: list[dict] = []
        scope = f"scope-{family}"
        for split, count in (("train", 16), ("validation", 4), ("test", 12)):
            for index in range(count):
                case_id = f"{family}-{split}-{index:02d}"
                rows.append({
                    "case_id": case_id,
                    "physical_case_id": f"physical-{case_id}",
                    "lineage_group_id": f"lineage-{case_id}",
                    "family": family,
                    "scope_id": scope,
                    "split": split,
                    "hdf5": f"assets/{case_id}.h5",
                    "known_inputs_ref": {
                        "geometry": {"path": f"assets/{case_id}-geometry.npz"},
                        "control": {"path": f"assets/{case_id}-control.npz"},
                    },
                })
        return rows

    def materialize_manifest(path: Path, family: str, rows: list[dict]) -> Path:
        for row in rows:
            audit_path = tmp_path / "audits" / f"{row['case_id']}.json"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            if not audit_path.exists():
                audit_path.write_text(json.dumps({
                    "case_id": row["case_id"],
                    "family": family,
                    "scope_id": row["scope_id"],
                    "physical_case_id": row["physical_case_id"],
                    "lineage_group_id": row["lineage_group_id"],
                    "hard_integrity_pass": True,
                    "structural_pass": True,
                }))
            row["audit"] = {
                "path": f"audits/{row['case_id']}.json",
                "sha256": sha256_file(audit_path),
            }
        path.write_text(json.dumps({
            "schema": "core.dataset.v2",
            "dataset_id": f"dataset-{family}-{path.stem}",
            "formal_release": True,
            "cases": rows,
        }))
        return path

    def split_f3() -> tuple[list[dict], list[dict]]:
        rows = manifest_rows("F3")
        # Keep the aggregate split shape unchanged: each fragment has a
        # train row, so the replacement remains train rather than turning a
        # validation row into a second train row.
        first = rows[:15] + rows[16:17]
        second = rows[15:16] + rows[17:]
        duplicate = dict(first[0])
        second[0] = duplicate
        return first, second

    f3_a, f3_b = split_f3()
    manifest_specs = [
        ("F3", "f3-a.json", f3_a),
        ("F3", "f3-b.json", f3_b),
        ("F4", "f4.json", manifest_rows("F4")),
        ("F5", "f5.json", manifest_rows("F5")),
    ]
    manifests = [
        materialize_manifest(tmp_path / filename, family, rows)
        for family, filename, rows in manifest_specs
    ]
    evidence = [
        {
            "schema": "core.qualification.v1",
            "family": family,
            "scope_id": f"scope-{family}",
            "T1_numerical": True,
        }
        for family in ("F3", "F3", "F4", "F5")
    ]

    report = audit_admission(
        manifests,
        data_root=tmp_path,
        code_root=ROOT,
        evidence=evidence,
    )

    assert report["duplicate_case_ids"] == ["F3-train-00"]
    assert report["family_summary"]["split_shape_mismatches"] == {}
    assert report["family_summary"]["t1_family_count"] == 3
    denominator = report["production_denominator"]
    assert denominator["included_case_count"] == 96
    assert denominator["formal_audit_pass_count"] == 96
    assert report["formal_admission"] is False
    assert "MANIFEST_DUPLICATE_CASE_ID" in {
        item["code"] for item in report["blockers"]
    }


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
        "--record-id", "core-formal-admission-test-r001",
        "--sha256-output", str(digest),
    ])

    assert exit_code == 2
    report = json.loads(output.read_text())
    assert report["record_id"] == "core-formal-admission-test-r001"
    assert report["execution_constraints"]["read_only"] is True
    assert report["execution_constraints"]["formal_runs_started"] == 0
    assert report["execution_constraints"]["central_registry_mutation"] == 0
    assert report["execution_constraints"]["central_ledger_mutation"] == 0
    assert report["diagnostic_exclusion"]["diagnostic_runs_counted_as_formal"] is False
    assert report["production_denominator"]["structural_pass_bound_count"] == 64
    digest_text = digest.read_text().strip()
    assert digest_text.endswith("  admission.json")
    assert digest_text.split()[0]


def test_missing_resource_profile_cannot_satisfy_capacity_gate() -> None:
    report = audit_admission(
        [F3_MANIFEST, F4_MANIFEST],
        evidence=[F3_QUALIFICATION, F3_ADAPTER, F3_STRUCTURAL_ADAPTER, F4_QUALIFICATION],
        data_root=ROOT,
        code_root=ROOT,
        preprofile_index=PREPROFILE,
        resource_profile=None,
        resource_dryrun=RESOURCE_DRYRUN,
        graph_probe=GRAPH_PROBE,
    )
    assert "RESOURCE_FRONTIER_UNPROVEN" in {
        item["code"] for item in report["blockers"]
    }
    assert report["resource_profile"]["formal_capacity_evidence"] is False
