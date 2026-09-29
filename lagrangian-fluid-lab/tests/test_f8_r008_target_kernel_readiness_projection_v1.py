from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import f8_r008_target_kernel_readiness_projection_v1 as projection


LAB = Path(__file__).parents[1]


def _load(relative: str) -> dict:
    return json.loads((LAB / relative).read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_input(relative: str, tmp_path: Path, name: str) -> Path:
    destination = tmp_path / name
    destination.write_bytes((LAB / relative).read_bytes())
    return destination


def test_missing_external_evidence_is_explicitly_blocked_and_zero_credit() -> None:
    report = projection.build_projection()

    assert report["status"] == projection.STATUS
    assert report["scope_id"] == projection.R008_SCOPE_ID
    assert "external_target_evidence_missing" in report["validation"]["blockers"]
    assert "untrusted_authority_runtime_identity" in report["validation"]["blockers"]
    assert "target_abi_conformance_missing" in report["validation"]["blockers"]
    assert "source_callgraph_conformance_missing" in report["validation"]["blockers"]
    assert "target_kernel_runtime_conformance_missing" in report["validation"]["blockers"]
    assert report["target_kernel"]["external_evidence_complete"] is False
    assert report["authorization"] == {
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def test_intake_schema_drift_fails_closed(tmp_path: Path) -> None:
    value = _load("reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json")
    value["schema"] = "core.cfd.f8.r008.target_kernel_evidence_intake_report.tampered"
    path = tmp_path / "intake.json"
    _write_json(path, value)

    with pytest.raises(projection.TargetKernelReadinessProjectionError, match="schema drift"):
        projection.build_projection(intake_report_path=path)


def test_intake_digest_drift_is_rejected_when_previous_digest_is_pinned(tmp_path: Path) -> None:
    original = (LAB / "reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json").read_bytes()
    value = json.loads(original)
    value["validation"]["blockers"] = ["different bounded diagnostic"]
    path = tmp_path / "intake.json"
    _write_json(path, value)

    with pytest.raises(projection.TargetKernelReadinessProjectionError, match="digest drift"):
        projection.build_projection(
            intake_report_path=path,
            expected_input_digests={"intake": hashlib.sha256(original).hexdigest()},
        )


def test_inconsistent_partial_pin_report_fails_closed(tmp_path: Path) -> None:
    value = _load("reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json")
    value["pins"]["kernel_release_pinned"] = True
    path = tmp_path / "intake.json"
    _write_json(path, value)

    with pytest.raises(projection.TargetKernelReadinessProjectionError, match="without kernel_release"):
        projection.build_projection(intake_report_path=path)


def test_parent_directory_swap_after_component_check_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_dir = tmp_path / "trusted"
    evil_dir = tmp_path / "evil"
    trusted_dir.mkdir()
    evil_dir.mkdir()
    trusted_input = trusted_dir / "input.json"
    trusted_input.write_text('{"source":"trusted"}', encoding="utf-8")
    (evil_dir / trusted_input.name).write_bytes(trusted_input.read_bytes())

    original_open = projection.os.open
    swapped = False

    def race_open(path, flags, *args, **kwargs):
        nonlocal swapped
        is_target_component = kwargs.get("dir_fd") is not None and path == trusted_dir.name
        is_legacy_target_open = kwargs.get("dir_fd") is None and path == os.fspath(trusted_input)
        if not swapped and (is_target_component or is_legacy_target_open):
            real_dir = tmp_path / "trusted-real"
            trusted_dir.rename(real_dir)
            trusted_dir.symlink_to(evil_dir, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(projection.os, "open", race_open)
    with pytest.raises(projection.TargetKernelReadinessProjectionError, match="cannot be opened safely|symlink"):
        projection._read_bounded_json(trusted_input, label="target-kernel fixture")
    assert swapped is True


def test_causal_witness_scope_drift_is_not_projected(tmp_path: Path) -> None:
    value = _load("reports/F8-R008-TERMINAL-CONFORMANCE-CAUSAL-WITNESS-V1.json")
    value["scope_id"] = "F8-R008-WRONG-SCOPE"
    path = tmp_path / "causal.json"
    _write_json(path, value)

    with pytest.raises(projection.TargetKernelReadinessProjectionError, match="scope drift"):
        projection.build_projection(causal_witness_path=path)


def test_causal_runtime_claim_drift_is_not_authorized(tmp_path: Path) -> None:
    value = _load("reports/F8-R008-TERMINAL-CONFORMANCE-CAUSAL-WITNESS-V1.json")
    value["trust_boundary"]["runtime_claims"]["target_kernel_conformance"] = True
    path = tmp_path / "causal.json"
    _write_json(path, value)

    with pytest.raises(projection.TargetKernelReadinessProjectionError, match="causal"):
        projection.build_projection(causal_witness_path=path)


def test_zero_credit_and_checked_in_report_binding_are_strict() -> None:
    expected = projection.build_projection()
    projection.validate_projection(expected)

    checked_in = _load("reports/F8-R008-TARGET-KERNEL-READINESS-PROJECTION-V1-2026-09-28.json")
    assert checked_in == expected
    assert projection.verify_report() == expected

    tampered = copy.deepcopy(expected)
    tampered["authorization"]["qualification_credit"] = 1
    with pytest.raises(projection.TargetKernelReadinessProjectionError, match="authorization"):
        projection.validate_projection(tampered)


def test_all_dependency_refs_bind_schema_digest_and_r008_scope() -> None:
    report = projection.build_projection()
    refs = report["inputs"]

    assert refs["target_kernel_evidence_intake"]["schema"] == projection.INTAKE_SCHEMA
    assert refs["causal_witness"]["schema"] == projection.CAUSAL_SCHEMA
    assert refs["readiness_audit_v8"]["schema"] == projection.READINESS_SCHEMA
    assert refs["trusted_identity_contract"]["schema"] == projection.TRUSTED_IDENTITY_SCHEMA
    assert refs["trusted_worker_runtime_handoff"]["schema"] == projection.TRUSTED_HANDOFF_SCHEMA
    assert refs["causal_witness"]["scope_id"] == projection.R008_SCOPE_ID
    assert refs["readiness_audit_v8"]["scope_id"] == projection.R008_SCOPE_ID
    assert refs["trusted_identity_contract"]["scope_id"] == projection.R008_SCOPE_ID
    assert refs["trusted_worker_runtime_handoff"]["scope_id"] == projection.R008_SCOPE_ID
    for item in refs.values():
        assert len(item["sha256"]) == 64
        assert item["bytes"] > 0
