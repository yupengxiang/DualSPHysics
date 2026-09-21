from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_normal_remediation_v3 import (
    CASE_ID,
    DEFAULT_AUDIT,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT,
    DEFAULT_DEFINITION,
    DEFAULT_PREFLIGHT,
    PARENT_V4_CASE_ID,
    SOURCE_LATTICE_COUNTS,
    SOURCE_LATTICE_PARTICLES,
    inspect_definition,
    verify_contract,
    write_definition,
)
from scripts.f2_submerged_orifice_v4_failure_audit_v1 import (
    DEFAULT_BOUND,
    audit_bound_vtk,
)


LAB = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_read_only_v4_failure_audit_is_partitioned_and_runtime_closed(tmp_path: Path):
    output = tmp_path / "v4-audit.json"
    audit = audit_bound_vtk(DEFAULT_BOUND, DEFAULT_PREFLIGHT, output)
    assert audit["status"] == "read_only_v4_boundnor_failure_audited"
    assert audit["input_scope"]["definition_read"] is False
    assert audit["input_scope"]["bi4_read"] is False
    assert audit["input_scope"]["native_decoder_invoked"] is False
    assert audit["input_scope"]["gencase_invoked"] is False
    assert audit["input_scope"]["solver_invoked"] is False
    assert audit["input_scope"]["gpu_invoked"] is False
    assert audit["input_scope"]["queue_mutation"] == 0
    assert audit["input_scope"]["ledger_mutation"] == 0
    assert audit["input_scope"]["registry_mutation"] == 0
    assert audit["generated_field_summary"]["global_zero_boundnor_count"] == 64899
    parts = {row["mk"]: row for row in audit["mk_partitions"]}
    assert parts[17]["particle_count"] == 226422
    assert parts[17]["zero_boundnor_count"] == 64899
    assert parts[18]["particle_count"] == 29484
    assert parts[18]["zero_boundnor_count"] == 0


def test_v3_literal_definition_mirrors_shell_and_closes_source_lattice(tmp_path: Path):
    target = tmp_path / f"{CASE_ID}_Def.xml"
    record = write_definition(target)
    assert record["case_id"] == CASE_ID
    inspection = inspect_definition(target)
    assert inspection["normal_geometry"] == {
        "outer_boxfill": "bottom | left | right | front | back",
        "gate_boxfill": "bottom | top | left | right | front | back",
        "outer_layers_vdp": "0,1,2",
        "gate_layers_vdp": "0,-1,-2",
    }
    assert inspection["source_lattice"]["expected_counts_xyz"] == list(SOURCE_LATTICE_COUNTS)
    assert inspection["source_lattice"]["expected_particle_count"] == SOURCE_LATTICE_PARTICLES
    assert inspection["runtime_invoked"] is False
    text = target.read_text(encoding="utf-8")
    assert PARENT_V4_CASE_ID not in text
    assert ".bi4" not in text


def test_v3_candidate_binds_only_one_hypothesis_and_keeps_hard_gates():
    candidate = _read(DEFAULT_CANDIDATE)
    assert candidate["case_id"] == CASE_ID
    assert candidate["parent_failed_case_id"] == PARENT_V4_CASE_ID
    assert candidate["candidate_status"] == "root_review_only_static_candidate_not_run"
    assert candidate["matrix_credit"] == 0
    assert len(candidate["one_hypothesis"]["evidence"]) == 3
    assert candidate["hard_preflight_gates"]["zero_boundnor_count_max"] == 0
    assert candidate["hard_preflight_gates"]["zero_normal_size_count_max"] == 0
    assert candidate["hard_preflight_gates"]["native_mass_relative_error_max"] == 0.025
    assert candidate["source_lattice_closure"]["expected_particle_count"] == 231168
    assert candidate["source_lattice_closure"]["runtime_count_observed"] is False
    assert candidate["denominator_preservation"]["planned_rows"] == 15
    assert candidate["denominator_preservation"]["qualification_numerator"] == 0
    controls = candidate["execution_controls"]
    assert controls["gencase_invoked"] is False
    assert controls["native_decoder_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["job_created"] is False
    assert controls["matrix_submission"] is False
    assert controls["queue_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0


def test_v3_contract_is_hash_bound_and_runtime_closed():
    contract = verify_contract(
        DEFAULT_CONTRACT,
        candidate_path=DEFAULT_CANDIDATE,
        audit_path=DEFAULT_AUDIT,
        preflight_path=DEFAULT_PREFLIGHT,
        definition_path=DEFAULT_DEFINITION,
        test_path=Path(__file__),
    )
    assert contract["status"] == "root_review_only_static_contract_runtime_closed"
    assert contract["decision"] == "candidate_requires_independent_root_review_before_any_runtime"
    assert contract["case_id"] == CASE_ID
    assert contract["authorized_now"] is False
    assert contract["preflight"]["status"] == "not_run"
    assert contract["fresh_input"]["generated_products_present"] is False
    assert contract["fresh_input"]["native_input_present"] is False
    assert contract["failure_denominator"]["planned_rows"] == 15
    assert contract["failure_denominator"]["qualification_numerator"] == 0
    auth = contract["authorization"]
    assert all(auth[key] is False for key in (
        "cpu_gencase", "native_decode", "solver_launch", "gpu_launch",
        "job_spec_creation", "matrix_submission",
    ))
    assert auth["queue_mutation"] == 0
    assert auth["ledger_mutation"] == 0
    assert auth["registry_mutation"] == 0
    assert ".bi4" not in json.dumps(contract, sort_keys=True).lower()

