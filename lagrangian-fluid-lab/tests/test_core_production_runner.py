import json
from pathlib import Path

import pytest

from scripts.core_production import next_batch
from scripts.core_production_runner import (
    FAMILY,
    REVISION_ID,
    SCOPE_ID,
    VerificationError,
    _sha256,
    _write_json,
    build_proposal,
    inspect_qualification_matrix,
    production_case_config,
    production_design,
    _batch_decision,
    verify_qualification_receipt,
    load_production_audits,
)


LAB = Path(__file__).resolve().parents[1]
MATRIX_ROOT = LAB / "campaigns/core-v1/cfd/prepared/F4_resting_pool_qualification_v2"


def test_f4_resting_scope_registers_32_noncolliding_points():
    matrix = inspect_qualification_matrix(MATRIX_ROOT)
    design = production_design(matrix)
    assert design["scope_id"] == SCOPE_ID
    assert design["revision_id"] == REVISION_ID
    assert len(design["cases"]) == 32
    assert design["first_batch_indices"] == [0, 4, 8, 13, 18, 23, 27, 31]
    assert not set(design["qualification_parameters"]).intersection(
        row["parameter"] for row in design["cases"]
    )
    assert all(row["qualification_only"] is False for row in design["cases"])


def test_old_scope_qualification_receipt_is_rejected(tmp_path):
    matrix = inspect_qualification_matrix(MATRIX_ROOT)
    receipt = {
        "schema": "core.qualification.v1",
        "family": FAMILY,
        "scope_id": "F4_drop_pool_x_v1",
        "design_sha256": matrix["design_sha256"],
        "T1_numerical": True,
        "matrix_complete": True,
        "_hash_verified": True,
    }
    path = tmp_path / "old-qualification.json"
    _write_json(path, receipt)
    with pytest.raises(VerificationError, match="only .* may enter production"):
        verify_qualification_receipt(path, matrix)


@pytest.mark.parametrize("schema", ["core.f8.synthetic_diagnostic.v1", None])
def test_synthetic_qualification_schema_rejected_before_scope_or_family_guard(tmp_path, schema):
    receipt = {
        "family": "synthetic-family",
        "scope_id": "unregistered-synthetic-scope",
        "T1_numerical": True,
        "matrix_complete": True,
    }
    if schema is not None:
        receipt["schema"] = schema
    path = tmp_path / "synthetic-qualification.json"
    _write_json(path, receipt)

    with pytest.raises(VerificationError, match="qualification receipt schema/family mismatch"):
        verify_qualification_receipt(path, matrix={})


def test_hash_verified_complete_receipt(tmp_path):
    matrix = inspect_qualification_matrix(MATRIX_ROOT)
    cells = []
    for case_id in matrix["case_ids"]:
        audit = tmp_path / f"{case_id}.audit.json"
        observations = tmp_path / f"{case_id}.observations.json"
        _write_json(audit, {"schema": "core.case_audit.v1", "case_id": case_id,
                            "hard_integrity_pass": True, "source_mass_gate_pass": True,
                            "event_window_complete": True})
        _write_json(observations, {"schema": "core.observations.v1", "case_id": case_id})
        cells.append(
            {
                "case_id": case_id,
                "audit": {"path": str(audit), "sha256": _sha256(audit)},
                "observations": {"path": str(observations), "sha256": _sha256(observations)},
            }
        )
    calibration = tmp_path / "calibration.json"
    _write_json(
        calibration,
        {"schema": "core.observation_calibration.v1", "passed": True},
    )
    receipt = tmp_path / "qualification.json"
    _write_json(
        receipt,
        {
            "schema": "core.qualification.v1",
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "design_sha256": matrix["design_sha256"],
            "prepared_matrix_sha256": matrix["matrix_sha256"],
            "T1_numerical": True,
            "matrix_complete": True,
            "checks": {key: True for key in ("static_matrix", "matrix_complete",
                "all_case_hard_mass_event_gates", "spatial", "independent_checks",
                "time_and_output", "observation_calibrated")},
            "missing": [],
            "failures": [],
            "cells": cells,
            "observation_calibration": {
                "path": str(calibration),
                "sha256": _sha256(calibration),
            },
        },
    )
    checked = verify_qualification_receipt(receipt, matrix)
    assert checked["_hash_verified"] is True
    assert checked["T1_numerical"] is True
    assert checked["_receipt_sha256"] == _sha256(receipt)

    original = json.loads(receipt.read_text())
    contradicted = json.loads(receipt.read_text())
    contradicted['checks']['spatial'] = False
    _write_json(receipt, contradicted)
    with pytest.raises(VerificationError, match='scientific gate matrix'):
        verify_qualification_receipt(receipt, matrix)
    _write_json(receipt, original)

    # A self-consistent hash must not hide a failed scientific case gate.
    audit_path = Path(cells[0]['audit']['path'])
    good_audit = json.loads(audit_path.read_text())
    bad_audit = dict(good_audit, hard_integrity_pass=False)
    _write_json(audit_path, bad_audit)
    contradicted = json.loads(receipt.read_text())
    contradicted['cells'][0]['audit']['sha256'] = _sha256(audit_path)
    _write_json(receipt, contradicted)
    with pytest.raises(VerificationError, match='underlying case gates'):
        verify_qualification_receipt(receipt, matrix)
    _write_json(audit_path, good_audit)
    _write_json(receipt, original)

    observations = Path(cells[0]["observations"]["path"])
    observations.write_text(observations.read_text() + "\nchanged")
    with pytest.raises(VerificationError, match="hash mismatch"):
        verify_qualification_receipt(receipt, matrix)


def test_batch_failure_keeps_the_fixed_denominator():
    matrix = inspect_qualification_matrix(MATRIX_ROOT)
    design = production_design(matrix)
    qualification = {
        "schema": "core.qualification.v1",
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "T1_numerical": True,
        "matrix_complete": True,
        "_hash_verified": True,
    }
    first = next_batch(design, qualification, {})
    assert first["status"] == "first_8"
    assert len(first["ready"]) == 8
    audits = {
        case_id: {
            "schema": "core.case_audit.v1",
            "case_id": case_id,
            "hard_integrity_pass": True,
            "full_temporal_scan": True,
            "full_particle_axis": True,
        }
        for case_id in first["ready"]
    }
    audits[first["ready"][0]]["full_particle_axis"] = False
    failed = _batch_decision(design, qualification, audits)
    assert failed["status"] == "scope_review_required"
    assert failed["ready"] == []
    assert failed["registered_denominator"] == 32
    assert len(failed["missing"]) == 24


def test_production_config_uses_resting_pool_and_new_scope():
    matrix = inspect_qualification_matrix(MATRIX_ROOT)
    design = production_design(matrix)
    cfg = production_case_config(design["cases"][0], matrix)
    assert cfg["scope_id"] == SCOPE_ID
    assert cfg["stage"] == "production"
    assert cfg["qualification_only"] is False
    assert cfg["recipe_id"] == "F4_resting_pool_mdbc_native_v2"
    assert cfg["pool"] == {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18], "mkfluid": 0}
    assert cfg["time_max_s"] == 4.34
    assert cfg["dp_m"] == 0.0075


def test_pending_proposal_does_not_create_jobs_or_touch_ledger(tmp_path):
    output = tmp_path / "proposal.json"
    result = build_proposal(
        matrix_root=MATRIX_ROOT,
        lab_root=LAB,
        output=output,
        prepare_cases=False,
    )
    assert result["batch_decision"]["status"] == "awaiting_T1"
    assert result["batch_decision"]["ready"] == []
    assert result["registered_denominator"] == 32
    assert result["central_ledger_mutation"] == 0
    assert result["prepared_batch"] is None
    assert output.exists()


def test_prepare_batch_reentry_verifies_and_reuses_inputs(tmp_path):
    from scripts.core_production_runner import prepare_batch
    matrix = inspect_qualification_matrix(MATRIX_ROOT)
    row = production_design(matrix)['cases'][0]
    solver = tmp_path / 'solver'; solver.write_text('fixed binary')
    calls = []
    def prepare(config, lab, directory):
        calls.append(config['case_id']); directory.mkdir(parents=True)
        source = directory / 'native.bi4'; source.write_bytes(b'fixed input')
        record = {'config': config, 'preflight_pass': True,
                  'solver_binary': str(solver),
                  'inputs': {str(source): _sha256(source)}}
        _write_json(directory / 'prepared.json', record)
        return record
    kwargs = dict(matrix=matrix, lab_root=LAB, prepared_root=tmp_path/'prepared',
                  batch_status='first_8', qualification={},
                  production_design_sha256='test', prepare_fn=prepare)
    first = prepare_batch([row], **kwargs)
    assert first['status'] == 'first_8'
    second = prepare_batch([row], **kwargs)
    assert second['jobs'] == first['jobs'] and len(calls) == 1
    (tmp_path/'prepared/DEV_00/native.bi4').write_bytes(b'changed')
    rejected = prepare_batch([row], **kwargs)
    assert rejected['status'] == 'scope_review_required' and not rejected['ready']


def test_production_batch_requires_executed_bound_evidence(tmp_path):
    case = 'production-case'
    design = {'family': FAMILY, 'scope_id': SCOPE_ID, 'recipe_id': 'recipe',
              'cases': [{'case_id': case, 'parameter': .3, 'split': 'train', 'index': 3}]}
    product = tmp_path / 'product'; product.mkdir()
    trajectory = product / 'trajectory.h5'; trajectory.write_bytes(b'fixture trajectory')
    prepared = product / 'prepared.json'
    _write_json(prepared, {'config': {'case_id': case, 'family': FAMILY,
        'scope_id': SCOPE_ID, 'stage': 'production', 'qualification_only': False,
        'parameter': {'value': .3}, 'split': 'train', 'production_index': 3,
        'recipe_id': 'recipe', 'lineage_group_id': case, 'physical_case_id': case}})
    audit_path = product / 'audit.json'
    audit = {'schema': 'core.cfd.v1', 'case_id': case,
             'hard_integrity_pass': True, 'source_mass_gate_pass': True,
             'event_window_complete': True, 'requested_horizon_reached': True,
             'structural': {'path': str(trajectory), 'full_scan': True}}
    _write_json(audit_path, audit)
    receipt_path = tmp_path / 'execution.json'
    receipt = {'schema': 'core.execution_receipt.v1',
               'execution_status': 'succeeded', 'returncode': 0, 'timeout': False,
               'missing_outputs': [], 'artifact_index': []}
    manifest = tmp_path / 'audits.json'

    def write_bound():
        receipt['artifact_index'] = [{'path': str(p.relative_to(tmp_path)),
            'sha256': _sha256(p)} for p in (prepared, audit_path, trajectory)]
        _write_json(receipt_path, receipt)
        row = {'case_id': case, 'hard_integrity_pass': True,
               **{k: {'path': str(p), 'sha256': _sha256(p)} for k, p in (
                   ('execution', receipt_path), ('prepared', prepared),
                   ('audit', audit_path), ('trajectory', trajectory))}}
        _write_json(manifest, {'audits': {case: row}})
        return row

    row = write_bound()
    assert load_production_audits(manifest, design=design)[case]['hard_integrity_pass']
    # A manifest's passing flag cannot hide an actual event-window failure.
    audit['event_window_complete'] = False
    _write_json(audit_path, audit); write_bound()
    assert not load_production_audits(manifest, design=design)[case]['hard_integrity_pass']
    # Rehashing a swapped output in the manifest cannot bypass the worker receipt.
    trajectory.write_bytes(b'swapped output')
    document = json.loads(manifest.read_text())
    document['audits'][case]['trajectory']['sha256'] = _sha256(trajectory)
    _write_json(manifest, document)
    with pytest.raises(VerificationError, match='not bound to execution'):
        load_production_audits(manifest, design=design)
    _write_json(manifest, {'audits': {case: {'case_id': case,
        'hard_integrity_pass': True, 'full_temporal_scan': True,
        'full_particle_axis': True}}})
    with pytest.raises(VerificationError, match='requires execution evidence'):
        load_production_audits(manifest, design=design)


def test_laminar_production_is_separate_and_waits_for_qualification(tmp_path):
    from scripts.core_production_runner import LAMINAR_SCOPE_ID
    root = LAB / 'campaigns/core-v1/cfd/prepared/F4_resting_pool_laminar_qualification_v1'
    matrix = inspect_qualification_matrix(root)
    design = production_design(matrix)
    assert design['scope_id'] == LAMINAR_SCOPE_ID
    assert len(design['cases']) == 32
    assert not set(row['case_id'] for row in design['cases']).intersection(
        row['case_id'] for row in production_design(inspect_qualification_matrix(MATRIX_ROOT))['cases'])
    cfg = production_case_config(design['cases'][0], matrix)
    assert cfg['physical_kinematic_viscosity_m2_s'] == 1e-6
    assert cfg['viscosity_formulation'] == 'laminar'
    assert cfg['recipe_id'] == 'F4_resting_pool_laminar_nu1e6_mdbc_v1'
    assert cfg['lineage_group_id'].startswith(LAMINAR_SCOPE_ID)
    proposal = build_proposal(matrix_root=root, lab_root=LAB,
                             output=tmp_path/'laminar.json', prepare_cases=True)
    assert proposal['batch_decision']['status'] == 'awaiting_T1'
    assert proposal['prepared_batch'] is None
    assert proposal['central_ledger_mutation'] == 0
    receipt = tmp_path/'wrong-scope.json'
    _write_json(receipt, {'scope_id': SCOPE_ID})
    with pytest.raises(VerificationError, match='another registered scope'):
        verify_qualification_receipt(receipt, matrix)
