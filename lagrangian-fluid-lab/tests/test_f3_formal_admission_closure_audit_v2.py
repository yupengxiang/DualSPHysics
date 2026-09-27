"""Synthetic and static regression tests for the F3 admission-closure audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f3_formal_admission_closure_audit_v2 import (
    MANIFEST_REL,
    REPORT_SCHEMA,
    audit_repository,
)


ROOT = Path(__file__).resolve().parents[1]


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture(root: Path, *, formal_release: bool = False,
             claimed_capability: bool = False) -> None:
    source = root / "scripts"
    tests = root / "tests"
    _write(source / "f3_formal_reader_capability_contract_v1.py", "\n".join((
        "def validate_capability_contract(contract):",
        '    return {"authorizes_formal": False, "formal_eligible": False, "qualification_credit": 0, "opens_source_fd": False}',
        '"authorizes_formal": False',
        '"formal_eligible": False',
        '"qualification_credit": 0',
        '"opens_source_fd": False',
    )))
    _write(source / "f3_formal_reader_strict_capability_contract_v1.py", "\n".join((
        "def validate_strict_capability_contract(contract):",
        '    return {"formal_eligible": False, "qualification_credit": 0, "opens_source_fd": False}',
        'bundle.get("access_mode") == "held_fd_only"',
        "attempt_history",
        '"formal_eligible": False',
        '"qualification_credit": 0',
        '"opens_source_fd": False',
    )))
    _write(tests / "test_f3_formal_reader_capability_contract_v1.py",
           "test_complete_synthetic_envelope_is_structural_only_and_non_authorizing\n")
    _write(tests / "test_f3_formal_reader_strict_capability_contract_v1.py",
           "test_complete_strict_envelope_checks_bindings_but_never_authorizes\n")
    _write(source / "core_dataset.py", "\n".join((
        "snapshot_fds=None",
        "snapshot_measurements=None",
        "self.formal_eligible = False",
        "caller-provided measurements are",
        "still not authenticated capabilities",
        "producer or prove immutability",
    )))
    _write(source / "core_fsverity.py", "\n".join((
        "def verify_fd(fd, expected):",
        "authenticate who produced a file",
        "mint a capability",
    )))
    _write(source / "core_learning.py", "\n".join((
        "def _manifest_formal_release(dataset):",
        "    return False",
        "V13 verified-reader capability",
        "formal training requires a V13 verified-reader capability",
        "formal Core evaluation requires a V13 verified-reader capability",
    )))
    _write(source / "core_campaign.py", "\n".join((
        "def _reject_nonformal_or_nonroot(payload, label):",
        'receipt.get("formal_eligible") is not True',
        'config.get("manifest_formal_release") is not True',
        '"can_finalize": all(checks.values())',
    )))
    source_sha = _sha("source")
    descriptor_sha = _sha("descriptor")
    row = {
        "case_id": "F3_SYNTH_00",
        "hdf5": "data/source.h5",
        "sha256": source_sha,
        "bytes": 100,
        "known_inputs_ref": {
            "geometry": {"path": "inputs/geometry.npz", "sha256": descriptor_sha},
            "control": {"path": "inputs/control.npz", "sha256": descriptor_sha},
        },
    }
    manifest = {
        "schema": "core.dataset.v2",
        "case_count": 1,
        "cases": [row],
        "formal_release": formal_release,
    }
    if claimed_capability:
        manifest.update({
            "capability_contract_ref": "synthetic-claim.json",
            "source_trust": {"attested": True},
            "producer_identity": {"identity": "synthetic-producer"},
            "broker_identity": {"identity": "synthetic-broker"},
            "worker_identity": {"identity": "synthetic-worker"},
            "session_nonce": _sha("session"),
        })
    _write(root / MANIFEST_REL, json.dumps(manifest, sort_keys=True))
    _write(root / "campaigns/core-v1/registry.json", json.dumps({
        "schema": "core.registry.v1",
        "scopes": [], "scope_studies": [], "training_runs": [], "evaluations": [],
    }, sort_keys=True))


def _check_map(report: dict) -> dict:
    return {item["id"]: item for item in report["checks"]}


def test_current_repository_closure_is_blocked_without_authority() -> None:
    report = audit_repository(ROOT)

    assert report["schema"] == REPORT_SCHEMA
    assert report["formal_eligible"] is False
    assert report["qualification_credit"] == 0
    assert report["runtime_evidence_layer"]["trusted_runtime_evidence_exists"] is False
    assert report["contract_layer"]["v1_present"] is True
    assert report["contract_layer"]["strict_present"] is True
    assert report["contract_layer"]["production_sidecar_integration_present"] is False
    assert report["subject"]["manifest_declared_formal_release"] is False

    codes = {item["code"] for item in report["blockers"]}
    assert {
        "F3_MANIFEST_FORMAL_RELEASE_FALSE",
        "FORMAL_CAPABILITY_RELEASE_UNBOUND",
        "SOURCE_MEASUREMENT_RUNTIME_AUTHORITY_MISSING",
        "PRODUCER_IDENTITY_RUNTIME_AUTHORITY_MISSING",
        "BROKER_IDENTITY_RUNTIME_AUTHORITY_MISSING",
        "WORKER_IDENTITY_RUNTIME_AUTHORITY_MISSING",
        "READER_CAPABILITY_INTEGRATION_MISSING",
        "CORE_CAMPAIGN_FORMAL_GATE_UNSATISFIED",
    } <= codes


def test_contract_shape_and_runtime_evidence_are_separate() -> None:
    report = audit_repository(ROOT)
    checks = _check_map(report)

    assert checks["v1_capability_shape"]["code_contract_exists"] is True
    assert checks["v1_capability_shape"]["synthetic_contract_exists"] is True
    assert checks["v1_capability_shape"]["trusted_runtime_evidence_exists"] is False
    assert checks["strict_held_fd_bundle_shape"]["code_contract_exists"] is True
    assert checks["strict_held_fd_bundle_shape"]["trusted_runtime_evidence_exists"] is False
    assert checks["source_measurement_runtime_authority"]["code_contract_exists"] is True
    assert checks["source_measurement_runtime_authority"]["trusted_runtime_evidence_exists"] is False
    assert checks["producer_identity_runtime_authority"]["code_contract_exists"] is False
    assert checks["producer_identity_runtime_authority"]["synthetic_contract_exists"] is True


def test_manifest_claims_cannot_mint_trusted_authority(tmp_path: Path) -> None:
    _fixture(tmp_path, formal_release=True, claimed_capability=True)

    report = audit_repository(tmp_path)
    checks = _check_map(report)
    codes = {item["code"] for item in report["blockers"]}

    assert report["runtime_evidence_layer"]["trusted_runtime_evidence_exists"] is False
    assert report["formal_eligible"] is False
    assert report["qualification_credit"] == 0
    assert report["runtime_evidence_layer"]["manifest"]["runtime_capability_fields"]
    assert checks["formal_capability_release"]["trusted_runtime_evidence_exists"] is False
    assert checks["reader_capability_integration"]["code_contract_exists"] is False
    assert "SOURCE_MEASUREMENT_RUNTIME_AUTHORITY_MISSING" in codes
    assert "PRODUCER_IDENTITY_RUNTIME_AUTHORITY_MISSING" in codes
    assert "READER_CAPABILITY_INTEGRATION_MISSING" in codes
    assert "F3_MANIFEST_FORMAL_RELEASE_FALSE" not in codes


def test_nonformal_manifest_is_reported_without_mutating_it(tmp_path: Path) -> None:
    _fixture(tmp_path)
    manifest_path = tmp_path / MANIFEST_REL
    before = manifest_path.read_bytes()

    report = audit_repository(tmp_path)

    assert manifest_path.read_bytes() == before
    assert report["side_effects"]["production_files_written"] is False
    assert report["execution_constraints"]["opens_source_fd"] is False
    assert report["execution_constraints"]["starts_worker"] is False
    assert report["execution_constraints"]["mutates_gate"] is False


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    _fixture(tmp_path)
    (tmp_path / MANIFEST_REL).unlink()

    report = audit_repository(tmp_path)
    codes = {item["code"] for item in report["blockers"]}

    assert report["formal_eligible"] is False
    assert report["qualification_credit"] == 0
    assert "F3_MANIFEST_INVENTORY_INVALID" in codes
    assert "FORMAL_CAPABILITY_RELEASE_UNBOUND" in codes
