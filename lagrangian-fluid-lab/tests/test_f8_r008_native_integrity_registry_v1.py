from __future__ import annotations

import copy
import hashlib
import json

import pytest

from scripts import f8_r008_native_integrity_registry_v1 as registry


EVIDENCE_SHA256 = "a" * 64


def _cell(status: str, evidence: str | None = None) -> dict:
    return {"status": status, "evidence_sha256": evidence}


def _rows(default_status: str = "defined_pass") -> list[dict]:
    results = []
    for case_id in registry.EXPECTED_QUALIFICATION_CASE_IDS:
        gates = {}
        for gate_id in registry.GATE_IDS:
            definition_status, _outcomes = registry._GATE_BY_ID[gate_id]
            status = "open" if definition_status == "open" else default_status
            gates[gate_id] = _cell(
                status,
                EVIDENCE_SHA256 if status in ("defined_pass", "defined_fail") else None,
            )
        results.append({"case_id": case_id, "gate_results": gates})
    return results


def test_frozen_case_registry_matches_both_pinned_receipts() -> None:
    assert registry.frozen_qualification_case_ids() == registry.EXPECTED_QUALIFICATION_CASE_IDS
    assert len(registry.GATE_IDS) == 8
    assert registry.GATE_IDS == (
        "native_state_finite", "density_range", "mach_limit", "wall_penetration_limit",
        "excluded_fluid_particles_zero", "particle_overlap_absent",
        "inclusive_three_period_window_complete", "control_no_extrapolation",
    )


def test_15_by_8_matrix_is_incomplete_while_four_definitions_are_open() -> None:
    result = registry.aggregate_native_integrity_statuses(_rows())

    assert result["schema"] == registry.SCHEMA
    assert result["aggregation_status"] == "incomplete"
    assert result["case_count"] == 15
    assert result["gate_count"] == 8
    assert result["denominator_cells"] == 120
    assert result["state_counts"] == {
        "defined_pass": 60, "defined_fail": 0, "open": 60, "missing": 0,
    }
    assert result["native_integrity_evaluated"] is False
    assert result["T1_numerical"] is False
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0
    assert result["evidence_bindings_verified"] is False
    registry_payload = json.dumps(
        result["gate_registry"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(registry_payload).hexdigest() == result["gate_registry_sha256"]
    assert all(set(item) == {"gate_id", "definition_status", "outcomes"}
               for item in result["gate_registry"])


def test_defined_failure_is_preserved_without_shrinking_denominator() -> None:
    rows = _rows()
    rows[2]["gate_results"]["density_range"] = _cell("defined_fail", EVIDENCE_SHA256)

    result = registry.aggregate_native_integrity_statuses(rows)

    assert result["aggregation_status"] == "failed"
    assert result["denominator_cells"] == 120
    assert result["state_counts"]["defined_fail"] == 1
    assert len(result["case_results"]) == 15


def test_missing_evidence_remains_incomplete_and_keeps_its_cell() -> None:
    rows = _rows()
    rows[4]["gate_results"]["density_range"] = _cell("missing")

    result = registry.aggregate_native_integrity_statuses(rows)

    assert result["aggregation_status"] == "incomplete"
    assert result["state_counts"]["missing"] == 1
    assert result["denominator_cells"] == 120
    assert result["case_results"][4]["gate_results"]["density_range"]["status"] == "missing"


@pytest.mark.parametrize("gate_id", ["native_state_finite", "excluded_fluid_particles_zero"])
def test_unresolved_gates_allow_only_one_sided_defined_failure(gate_id: str) -> None:
    rows = _rows()
    rows[0]["gate_results"][gate_id] = _cell("defined_fail", EVIDENCE_SHA256)

    result = registry.aggregate_native_integrity_statuses(rows)

    assert result["aggregation_status"] == "failed"
    assert result["state_counts"]["defined_fail"] == 1
    assert result["native_integrity_evaluated"] is False


@pytest.mark.parametrize("gate_id", [
    "native_state_finite", "wall_penetration_limit", "excluded_fluid_particles_zero",
    "particle_overlap_absent",
])
def test_unresolved_gate_cannot_claim_defined_pass(gate_id: str) -> None:
    rows = _rows()
    rows[0]["gate_results"][gate_id] = _cell("defined_pass", EVIDENCE_SHA256)

    with pytest.raises(registry.NativeIntegrityRegistryError, match="cannot report defined_pass"):
        registry.aggregate_native_integrity_statuses(rows)


def test_registry_is_deeply_immutable_and_cannot_open_a_pass_bypass() -> None:
    with pytest.raises(TypeError):
        registry.GATE_REGISTRY[0][1] = "defined"  # type: ignore[index]
    with pytest.raises(TypeError):
        registry._GATE_BY_ID["native_state_finite"] = ("defined", registry.VALID_STATES)  # type: ignore[index]

    rows = _rows()
    rows[0]["gate_results"]["native_state_finite"] = _cell("defined_pass", EVIDENCE_SHA256)
    with pytest.raises(registry.NativeIntegrityRegistryError, match="cannot report defined_pass"):
        registry.aggregate_native_integrity_statuses(rows)


@pytest.mark.parametrize("gate_id", ["wall_penetration_limit", "particle_overlap_absent"])
def test_unresolved_gate_without_frozen_failure_predicate_cannot_claim_failure(gate_id: str) -> None:
    rows = _rows()
    rows[0]["gate_results"][gate_id] = _cell("defined_fail", EVIDENCE_SHA256)

    with pytest.raises(registry.NativeIntegrityRegistryError, match="cannot report defined_fail"):
        registry.aggregate_native_integrity_statuses(rows)


def test_adjudicated_status_requires_a_sha256_evidence_binding() -> None:
    rows = _rows()
    rows[0]["gate_results"]["density_range"] = _cell("defined_pass")

    with pytest.raises(registry.NativeIntegrityRegistryError, match="lacks a valid evidence SHA-256"):
        registry.aggregate_native_integrity_statuses(rows)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "substitution", "reordered"])
def test_case_denominator_rejects_missing_duplicate_substitute_or_reordered_rows(mutation: str) -> None:
    rows = _rows()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    elif mutation == "substitution":
        rows[-1]["case_id"] = "unregistered-case"
    else:
        rows[0], rows[1] = rows[1], rows[0]

    with pytest.raises(registry.NativeIntegrityRegistryError):
        registry.aggregate_native_integrity_statuses(rows)


def test_case_and_gate_records_reject_unregistered_fields_or_states() -> None:
    rows = _rows()
    rows[0]["extra"] = False
    with pytest.raises(registry.NativeIntegrityRegistryError, match="unexpected or missing fields"):
        registry.aggregate_native_integrity_statuses(rows)

    rows = _rows()
    rows[0]["gate_results"]["density_range"]["status"] = "pass"
    with pytest.raises(registry.NativeIntegrityRegistryError, match="invalid state"):
        registry.aggregate_native_integrity_statuses(rows)


def test_valid_evidence_hash_format_is_strict() -> None:
    rows = _rows()
    rows[0]["gate_results"]["density_range"] = _cell("defined_pass", "A" * 64)

    with pytest.raises(registry.NativeIntegrityRegistryError, match="valid evidence SHA-256"):
        registry.aggregate_native_integrity_statuses(rows)


@pytest.mark.parametrize("which", ["scope", "definition_pack"])
def test_frozen_receipt_byte_change_fails_hash_check(which: str, monkeypatch) -> None:
    original = registry.bundle._stable_read_beneath
    target_path = (
        registry.bundle.FROZEN_SCOPE_RECEIPT if which == "scope"
        else registry.bundle.FROZEN_DEFINITION_PACK
    ).relative_to(registry.bundle.LAB).as_posix()

    def altered(root_fd: int, relative_path: str, max_bytes: int) -> bytes:
        payload = original(root_fd, relative_path, max_bytes)
        return payload + b" " if relative_path == target_path else payload

    monkeypatch.setattr(registry.bundle, "_stable_read_beneath", altered)
    with pytest.raises(registry.NativeIntegrityRegistryError, match="receipt hash changed|pack hash changed"):
        registry.frozen_qualification_case_ids()


@pytest.mark.parametrize("which", ["scope", "definition_pack"])
def test_frozen_qualification_case_order_mismatch_fails_closed(which: str, monkeypatch) -> None:
    expected = registry.EXPECTED_QUALIFICATION_CASE_IDS
    reordered = (expected[1], expected[0], *expected[2:])
    scope = {"matrix": {"rows": [
        {"case_id": case_id, "qualification_only": True}
        for case_id in (reordered if which == "scope" else expected)
    ]}}
    pack = {"cases": [
        {"case_id": case_id, "qualification_only": True}
        for case_id in (reordered if which == "definition_pack" else expected)
    ]}
    monkeypatch.setattr(registry, "_read_frozen_inputs", lambda: (scope, pack))

    with pytest.raises(registry.NativeIntegrityRegistryError, match="IDs/order differ"):
        registry.frozen_qualification_case_ids()
