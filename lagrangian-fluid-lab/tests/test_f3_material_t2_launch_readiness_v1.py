import hashlib
import json
from pathlib import Path

from scripts.f3_material_t2_launch_readiness_v1 import (
    DEFAULT_OUTPUT,
    INPUTS,
    QUALIFICATION_SCHEMA,
    SCHEMA,
    _require_qualification_schema,
    build_audit,
)


ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_qualification_rejected_before_readiness_extraction() -> None:
    class SchemaReadProbe(dict):
        reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            if key != "schema":
                raise AssertionError(f"qualification field read before schema rejection: {key}")
            return super().get(key, default)

    qualification = SchemaReadProbe({
        "schema": "core.f8.synthetic_diagnostic.v1",
        "T1_numerical": True,
        "T2_macro": True,
        "T2_path": True,
        "scope_id": "synthetic-scope",
    })
    try:
        _require_qualification_schema(qualification)
    except ValueError as exc:
        assert "schema mismatch" in str(exc)
    else:
        raise AssertionError("synthetic qualification schema was accepted")
    assert qualification.reads == ["schema"]
    assert QUALIFICATION_SCHEMA == "core.qualification.v1"


def test_readiness_maps_all_plan_rows_without_t2_promotion() -> None:
    value = build_audit(ROOT)
    assert value["schema"] == SCHEMA
    assert value["canonical_and_qualification"]["T1_numerical"] is True
    assert value["canonical_and_qualification"]["T2_macro"] is False
    assert value["canonical_and_qualification"]["T2_path"] is False
    assert value["plan_15_diagnostics"]["mapped_count"] == 15
    assert value["plan_33_logical_configurations"]["mapped_count"] == 33
    assert [row["matrix_index"] for row in value["plan_33_logical_configurations"]["rows"]] == list(range(33))
    assert value["hard_boundaries"]["qualification_credit"] == "none"
    assert value["hard_boundaries"]["T2_macro"] is False


def test_evidence_types_keep_reusable_sources_separate_from_authorization() -> None:
    value = build_audit(ROOT)
    rows = {row["matrix_index"]: row for row in value["plan_33_logical_configurations"]["rows"]}
    assert rows[28]["evidence_class"] == "reusable_source_not_executed"
    assert rows[30]["evidence_class"] == "noncanonical_related_failure_not_a_canonical_result"
    assert rows[30]["exact_cfd_source_reusable"] is True
    assert rows[29]["evidence_class"] == "terminal_scientific_failure"
    assert rows[31]["evidence_class"] == "terminal_scientific_failure"
    assert rows[16]["evidence_class"] == "missing_exact_cfd_source"
    assert rows[26]["evidence_class"] == "missing_exact_cfd_source"
    next_step = value["next_executable_step"]
    assert next_step["candidate_matrix_row"] == 30
    assert next_step["status"] == "authorization_required_before_execution"
    assert value["root_and_resource_authorization_gaps"]["current_launch_authorization_proven"] is False


def test_receipt_hash_binds_every_declared_input_and_is_read_only() -> None:
    receipt = ROOT / DEFAULT_OUTPUT
    assert receipt.is_file()
    value = json.loads(receipt.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert set(value["input_bindings"]) == set(INPUTS)
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
    scope = value["scope"]
    assert scope["hdf5_opened"] is False
    assert scope["external_binary_invocations"] == 0
    assert scope["solver_started"] is False
    assert scope["cuda_started"] is False
    assert scope["queue_submissions"] == 0
    assert scope["material_workers_started"] == 0
    assert value["hard_boundaries"]["registry_mutation"] == 0
    assert value["hard_boundaries"]["ledger_mutation"] == 0
