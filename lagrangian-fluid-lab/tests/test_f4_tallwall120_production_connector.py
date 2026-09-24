"""Fail-closed tests for the independent tall-wall production connector."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f4_tallwall120_production_connector as connector


LAB = Path(__file__).resolve().parents[1]
CFD = LAB / "campaigns/core-v1/cfd"
MANIFEST_PATH = CFD / "f4-tallwall120-qualification-evaluator-v2.json"
EVALUATION_PATH = CFD / "f4-tallwall120-qualification-evaluation-v2-root.json"
REVIEW_PATH = CFD / "f4-tallwall120-v2-integration-root-review.json"
DESIGN_PATH = CFD / "prepared/F4_tallwall120_qualification_v2/design.json"
REUSE_PATH = CFD / "prepared/F4_tallwall120_qualification_v2/canary-cell12-equivalence-v2.json"
RESOURCE_PATH = CFD / "f4-tallwall120-root-scheduled-v2/resource-plan.json"
TEMPLATE_PATH = CFD / "prepared/F4_tallwall120_qualification_v2/cell-04/prepared.json"
RUNTIME_ROOT = LAB / "campaigns/core-v1/runtime"
ARCHIVE_ROOT = CFD / "f4-tallwall120-archives-v2"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def real_inputs() -> dict:
    return {
        "manifest_path": MANIFEST_PATH,
        "evaluation_path": EVALUATION_PATH,
        "integration_review_path": REVIEW_PATH,
        "design_path": DESIGN_PATH,
        "reuse_path": REUSE_PATH,
        "resource_path": RESOURCE_PATH,
        "template_path": TEMPLATE_PATH,
        "runtime_root": RUNTIME_ROOT,
        "archive_root": ARCHIVE_ROOT,
    }


def synthetic_binding(matrix_complete: bool, t1: bool) -> dict:
    return {
        "schema": connector.QUALIFICATION_BINDING_SCHEMA,
        "verified": True,
        "artifact_bindings_verified": True,
        "manifest_sha256": "synthetic",
        "matrix_complete": matrix_complete,
        "T1_numerical": t1,
    }


def bound_production_receipt(tmp_path: Path, case_id: str, index: int) -> dict:
    """Build a minimal but fully bound native product receipt for unit tests."""
    product = tmp_path / f"case-{index:02d}" / "product"
    product.mkdir(parents=True)
    trajectory = product / "trajectory.h5"
    trajectory.write_bytes(b"synthetic-native-trajectory-" + case_id.encode())
    structural = {
        "path": str(trajectory),
        "datasets": {
            "particle_id": [3],
            "position": [2, 3, 3],
            "velocity": [2, 3, 3],
            "mass": [2, 3],
            "time": [2],
            "valid": [2, 3],
        },
        "attrs": {"identity_key": "particle_id"},
        "frame_count": 2,
        "particle_count": 3,
        "finite_active": {"position": True, "velocity": True, "mass": True},
        "full_scan": True,
        "initial_valid_count": 3,
        "identities_ever_valid": 3,
        "death_count": 0,
        "birth_count": 0,
    }
    audit = product / "audit.json"
    audit.write_text(
        json.dumps(
            {
                "schema": "core.cfd.v1",
                "case_id": case_id,
                "structural": structural,
                "requested_horizon_reached": True,
                "hard_integrity_pass": True,
                "source_mass_gate_pass": True,
                "event_window_complete": True,
            }
        )
    )
    result = product / "result.json"
    result.write_text(
        json.dumps(
            {
                "schema": "core.cfd.v1",
                "case_id": case_id,
                "hard_integrity_pass": True,
                "source_mass_gate_pass": True,
                "event_window_complete": True,
                "conversion": {"hdf5": str(trajectory), "sha256": connector.digest(trajectory)},
            }
        )
    )
    observations = product / "observations.json"
    observations.write_text(json.dumps({"time_s": [0.0, 1.0], "normalized_values": [[0.0], [0.0]]}))
    execution = product.parent / "archive.json"
    execution.write_text(
        json.dumps(
            {
                "schema": "core.verified_archive.v1",
                "execution_status": "succeeded",
                "job_id": f"production-{index:02d}",
                "outputs": [
                    {"path": f"product/{name}", "sha256": connector.digest(path)}
                    for name, path in (
                        ("result.json", result),
                        ("audit.json", audit),
                        ("observations.json", observations),
                        ("trajectory.h5", trajectory),
                    )
                ],
            }
        )
    )
    return {
        "schema": "core.case_audit.v1",
        "case_id": case_id,
        "hard_integrity_pass": True,
        "source_mass_gate_pass": True,
        "event_window_complete": True,
        "full_temporal_scan": True,
        "full_particle_axis": True,
        "result_artifact": {"path": str(result), "sha256": connector.digest(result)},
        "audit_artifact": {"path": str(audit), "sha256": connector.digest(audit)},
        "observations_artifact": {
            "path": str(observations),
            "sha256": connector.digest(observations),
        },
        "trajectory_artifact": {
            "path": str(trajectory),
            "sha256": connector.digest(trajectory),
        },
        "execution_receipt": {
            "path": str(execution),
            "sha256": connector.digest(execution),
        },
    }


def test_current_receipt_is_bound_and_status_tracks_readonly_qualification_tick():
    proposal = connector.build_proposal(**real_inputs())

    assert proposal["schema"] == connector.SCHEMA
    admission = proposal["qualification_admission"]
    assert admission["static_contract_pass"] is True
    if admission["T1_numerical"] is True:
        assert admission["matrix_complete"] is True
        assert proposal["status"] == "production_batch_ready_for_root_review"
        assert proposal["batches"]["decision"]["ready"] == [
            row["case_id"] for row in proposal["production_design"]["cases"]
            if row["first_batch"]
        ]
    elif admission["matrix_complete"] is False:
        assert admission["T1_numerical"] is False
        assert proposal["status"] == "awaiting_qualification"
        assert proposal["batches"]["decision"]["ready"] == []
    else:
        assert admission["T1_numerical"] is False
        assert proposal["status"] == "scope_review_required"
        assert proposal["batches"]["decision"]["ready"] == []
    assert proposal["production_design"]["case_count"] == 32
    assert proposal["batches"]["job_specs"] == []
    assert proposal["template_derivation"]["derived_container_heights_m"] == [1.2]
    assert {row["name"] for row in proposal["negative_tests"]} == {
        "partial_matrix",
        "old_scope_receipt",
        "changed_wall_height",
        "changed_observer",
        "production_parameter",
        "production_index",
        "production_split",
        "production_case_identity",
        "production_lineage",
    }
    assert all(row["rejected"] is True for row in proposal["negative_tests"])
    assert proposal["execution"] == {
        "gpu_launched": False,
        "job_specs_submitted": False,
        "ledger_written": False,
        "central_registry_written": False,
        "production_prepared_assets_written": False,
    }


def test_production_design_has_fixed32_and_staged_eight_to_twenty_four():
    design = load(DESIGN_PATH)
    registered = connector.build_production_design(design)

    assert len(registered["cases"]) == 32
    assert registered["first_batch_indices"] == list(connector.FIRST_EIGHT)
    assert sum(row["first_batch"] for row in registered["cases"]) == 8
    assert len(set(row["parameter"] for row in registered["cases"])) == 32
    assert not set(row["parameter"] for row in registered["cases"]).intersection(
        registered["qualification_parameters"]
    )
    assert all(row["container_height_m"] == 1.2 for row in registered["cases"])
    assert all(row["qualification_inheritance"] is False for row in registered["cases"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parameter", 0.251),
        ("index", 32),
        ("split", "tampered_split"),
        ("case_id", "tampered_case"),
        ("qualification_inheritance", True),
    ],
)
def test_tampered_fixed_production_registration_is_rejected(field, value):
    registered = connector.build_production_design(load(DESIGN_PATH))
    registered["cases"][0][field] = value

    with pytest.raises(connector.ConnectorError):
        connector.validate_production_design(registered)

    qualification = {
        "family": "F4",
        "scope_id": connector.SCOPE_ID,
        "matrix_complete": True,
        "T1_numerical": True,
        "manifest_sha256": "synthetic",
        "binding": synthetic_binding(True, True),
    }
    with pytest.raises(connector.ConnectorError):
        connector.batch_decision(registered, qualification)


def test_qualified_receipt_transitions_first_eight_then_remaining_24(tmp_path):
    registered = connector.build_production_design(load(DESIGN_PATH))
    qualification = {
        "schema": "core.qualification.v1",
        "family": "F4",
        "scope_id": connector.SCOPE_ID,
        "matrix_complete": True,
        "T1_numerical": True,
        "manifest_sha256": "synthetic",
        "binding": synthetic_binding(True, True),
    }

    first = connector.batch_decision(registered, qualification)
    assert first["status"] == "first_8"
    assert len(first["ready"]) == 8
    assert first["registered_denominator"] == 32

    audits = {}
    for row in registered["cases"]:
        if not row["first_batch"]:
            continue
        audits[row["case_id"]] = bound_production_receipt(
            tmp_path, row["case_id"], row["index"]
        )
    second = connector.batch_decision(registered, qualification, audits)
    assert second["status"] == "remaining_24"
    assert len(second["ready"]) == 24
    assert set(second["ready"]).isdisjoint(first["ready"])


def test_synthetic_qualification_schema_rejected_before_binding_and_gate_fields():
    registered = connector.build_production_design(load(DESIGN_PATH))

    class SchemaReadProbe(dict):
        reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            if key != "schema":
                raise AssertionError(f"qualification field read before schema rejection: {key}")
            return super().get(key, default)

    class AuditReadProbe:
        def keys(self):
            raise AssertionError("audits read before qualification schema rejection")

    qualification = SchemaReadProbe({
        "schema": "core.f8.synthetic_diagnostic.v1",
        "family": "F4",
        "scope_id": connector.SCOPE_ID,
        "matrix_complete": True,
        "T1_numerical": True,
        "binding": synthetic_binding(True, True),
    })

    decision = connector.batch_decision(registered, qualification, AuditReadProbe())
    assert decision["status"] == "scope_review_required"
    assert decision["failed"] == ["qualification:schema_mismatch"]
    assert decision["ready"] == []
    assert qualification.reads == ["schema"]


def test_synthetic_evaluation_rejected_before_t1_derivation():
    class SchemaReadProbe(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            if key != "schema":
                raise AssertionError(f"evaluation field read before schema rejection: {key}")
            return super().get(key, default)

    evaluation = SchemaReadProbe({
        "schema": "core.f8.synthetic_diagnostic.v1",
        "scope_id": connector.SCOPE_ID,
        "revision_id": connector.QUALIFICATION_REVISION_ID,
        "T1_numerical": True,
        "matrix_complete": True,
        "cells": [{"passed": True}],
    })
    with pytest.raises(connector.ConnectorError, match="qualification evaluation schema mismatch"):
        connector.validate_evaluation(evaluation, Path("unused-manifest.json"))
    assert evaluation.reads == ["schema"]


def test_bound_audit_rejects_unbound_wrapper_flags(tmp_path):
    registered = connector.build_production_design(load(DESIGN_PATH))
    row = registered["cases"][0]
    receipt = bound_production_receipt(tmp_path, row["case_id"], row["index"])
    receipt["full_particle_axis"] = False

    with pytest.raises(connector.ConnectorError, match="particle-axis flag is unbound"):
        connector.verify_bound_audits(registered, {row["case_id"]: receipt})


def test_bound_audit_requires_native_execution_output_index(tmp_path):
    registered = connector.build_production_design(load(DESIGN_PATH))
    row = registered["cases"][0]
    receipt = bound_production_receipt(tmp_path, row["case_id"], row["index"])
    execution = Path(receipt["execution_receipt"]["path"])
    payload = json.loads(execution.read_text())
    payload["outputs"] = [item for item in payload["outputs"] if item["path"] != "product/trajectory.h5"]
    execution.write_text(json.dumps(payload))
    receipt["execution_receipt"]["sha256"] = connector.digest(execution)

    with pytest.raises(connector.ConnectorError, match="does not bind product/trajectory.h5"):
        connector.verify_bound_audits(registered, {row["case_id"]: receipt})


def test_partial_matrix_cannot_open_first_batch():
    registered = connector.build_production_design(load(DESIGN_PATH))
    qualification = {
        "schema": connector.QUALIFICATION_SCHEMA,
        "family": "F4",
        "scope_id": connector.SCOPE_ID,
        "matrix_complete": False,
        "T1_numerical": True,
        "manifest_sha256": "synthetic",
        "binding": synthetic_binding(False, True),
    }

    decision = connector.batch_decision(registered, qualification)
    assert decision["status"] == "awaiting_qualification"
    assert decision["ready"] == []
    assert "qualification:matrix_incomplete" in decision["failed"]


def test_old_scope_receipt_is_rejected():
    manifest = load(MANIFEST_PATH)
    design = load(DESIGN_PATH)
    manifest["scope_id"] = "F4_drop_resting_pool_x_v2"

    with pytest.raises(connector.ConnectorError, match="scope_id mismatch"):
        connector.validate_manifest(manifest, design)


def test_changed_wall_height_is_rejected():
    template = load(TEMPLATE_PATH)["config"]
    template["container_height_m"] = 0.6
    template["wall_bounds"]["zmax"] = 0.6

    with pytest.raises(connector.ConnectorError, match="height"):
        connector.validate_template_config(template)


def test_changed_observer_is_rejected():
    template = load(TEMPLATE_PATH)["config"]
    template["observation_version"] = "legacy_060m_wall_observer_v1"

    with pytest.raises(connector.ConnectorError, match="observer version"):
        connector.validate_template_config(template)


def test_derived_production_config_keeps_tall_wall_and_marks_lineage():
    design = load(DESIGN_PATH)
    template = load(TEMPLATE_PATH)["config"]
    registered = connector.build_production_design(design)
    row = registered["cases"][0]
    config = connector.derive_production_config(
        template,
        row,
        qualification_receipt_sha256="a" * 64,
        template_prepared_sha256="b" * 64,
    )

    assert config["stage"] == "production"
    assert config["qualification_only"] is False
    assert config["split"] == row["split"]
    assert config["container_height_m"] == 1.2
    assert config["wall_bounds"]["zmax"] == 1.2
    assert config["observation_version"] == connector.OBSERVER_VERSION
    assert config["drop"]["low"][0] == row["parameter"]
    assert config["source_scope_qualification_inherited"] is False


def test_prepare_batch_refuses_current_unqualified_receipt_before_gen_case(tmp_path):
    design = load(DESIGN_PATH)
    template = load(TEMPLATE_PATH)["config"]
    registered = connector.build_production_design(design)
    evaluation = load(EVALUATION_PATH)
    qualification = {
        "family": "F4",
        "scope_id": connector.SCOPE_ID,
        "matrix_complete": evaluation["matrix_complete"],
        "T1_numerical": evaluation["T1_numerical"],
    }

    with pytest.raises(connector.ConnectorError, match="binding is missing"):
        connector.prepare_production_batch(
            production_design=registered,
            template_config=template,
            qualification=qualification,
            batch_status="first_8",
            lab_root=LAB,
            output_root=tmp_path / "should-not-be-created",
            qualification_receipt_sha256="a" * 64,
            template_prepared_sha256="b" * 64,
            manifest_path=MANIFEST_PATH,
            runtime_root=RUNTIME_ROOT,
            archive_root=ARCHIVE_ROOT,
        )
    assert not (tmp_path / "should-not-be-created").exists()
