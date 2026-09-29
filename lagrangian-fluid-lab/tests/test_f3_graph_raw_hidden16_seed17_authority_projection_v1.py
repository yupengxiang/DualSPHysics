"""Synthetic-only tests for the F3 seed17 authority projection boundary."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import f3_graph_raw_hidden16_seed17_authority_projection_v1 as projection
from scripts import f3_graph_raw_hidden16_seed17_diagnostic_admission_v1 as admission
from scripts import f3_graph_raw_hidden16_seed17_diagnostic_runner_v2 as runner


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import test_f3_graph_raw_hidden16_seed17_diagnostic_runner_v2 as runner_fixture_module  # noqa: E402


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def signed_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    scheduler_root = tmp_path / "scheduler-ledger"
    scheduler_root.mkdir(mode=0o700)
    trust_root = tmp_path / "scheduler-trust"
    trust_root.mkdir(mode=0o700)
    public_key_path = trust_root / "scheduler-ed25519-public.key"
    key = Ed25519PrivateKey.generate()
    public_key_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    )
    public_key_path.chmod(0o600)
    monkeypatch.setattr(admission, "EXTERNAL_SCHEDULER_ROOT", scheduler_root)
    monkeypatch.setattr(admission, "TRUSTED_SCHEDULER_PUBLIC_KEY_PATH", public_key_path)
    previous_key = runner_fixture_module._TEST_SCHEDULER_KEY
    runner_fixture_module._TEST_SCHEDULER_KEY = key
    try:
        return runner_fixture_module._fixture(tmp_path)
    finally:
        runner_fixture_module._TEST_SCHEDULER_KEY = previous_key


def _legacy_projection_candidate(fixture: dict[str, object], path: Path) -> dict[str, object]:
    receipt_path = Path(fixture["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["receipt_path"] = str(path)
    receipt.pop("authority", None)
    for key in (
        "gpu",
        "gpu_identity_sha256",
        "environment",
        "executable",
        "owner",
        "namespace_descriptor",
        "plan_sha256",
        "rollout_snapshot",
        "rollout_snapshot_sha256",
        "external_authority",
    ):
        receipt["identity"].pop(key, None)
    for key in ("state_file", "lock_path", "external_claim_path"):
        receipt["consumption"].pop(key, None)
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = projection.canonical_digest(receipt)
    _write_json(path, receipt)
    return receipt


def test_actual_gap_shape_is_precise_without_external_claim(tmp_path: Path, signed_fixture: dict[str, object]) -> None:
    legacy_path = tmp_path / "legacy-admission-receipt.json"
    _legacy_projection_candidate(signed_fixture, legacy_path)
    report = projection.build_report(legacy_path)

    assert report["status"] == "blocked_projection_gap"
    assert "authority" in report["projectable_missing_fields"]
    assert "identity.external_authority" in report["non_projectable_missing_fields"]
    assert report["external_authority"]["verified"] is False
    assert report["historical_receipt_rewritten"] is False
    assert report["durable_receipt_written"] is False
    assert report["popen_allowed"] is False
    assert report["credit"] == 0
    assert projection.validate_report(report) == []


def test_signed_authority_projects_only_non_authorizing_envelope(
    signed_fixture: dict[str, object],
) -> None:
    receipt_path = Path(signed_fixture["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("authority")
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = projection.canonical_digest(receipt)
    original = copy.deepcopy(receipt)
    authority_path = Path(receipt["identity"]["external_authority"]["path"])

    result = projection.project_authority(
        receipt,
        external_authority=authority_path,
        resource_admission=signed_fixture["resource"],
    )

    assert "authority" not in original
    assert receipt == original
    assert "authority" in result["projected_receipt"]
    assert result["projected_receipt"]["authority"]["launch_allowed"] is False
    assert result["projected_receipt"]["authority"]["formal_promotion_allowed"] is False
    assert result["projected_receipt"]["authority"]["credit"] == 0
    assert result["external_authority"]["authority_id"]
    assert result["bindings"]["nonce"] == receipt["identity"]["nonce"]
    assert result["bindings"]["namespace"] == receipt["identity"]["namespace"]
    assert result["bindings"]["source_sha256"]
    assert result["bindings"]["resource_snapshot_sha256"]
    assert result["durable_receipt_written"] is False
    assert result["runner_consumable"] is False
    for key, expected in projection.ZERO_CREDIT.items():
        assert result[key] == expected


def test_signed_projection_report_validator_keeps_zero_side_effect_contract(
    signed_fixture: dict[str, object],
) -> None:
    receipt_path = Path(signed_fixture["receipt"])
    report = projection.build_report(
        receipt_path,
        external_authority=json.loads(receipt_path.read_text(encoding="utf-8"))["identity"]["external_authority"]["path"],
        resource_admission=signed_fixture["resource"],
    )
    assert report["status"] == "authority_projection_ready"
    assert report["historical_receipt_rewritten"] is False
    assert report["durable_receipt_written"] is False
    assert report["runner_consumable"] is False
    assert report["popen_allowed"] is False
    assert projection.validate_report(report) == []


def test_forged_existing_authority_is_rejected(signed_fixture: dict[str, object]) -> None:
    receipt_path = Path(signed_fixture["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["authority"]["credit"] = 1
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = projection.canonical_digest(receipt)
    authority_path = Path(receipt["identity"]["external_authority"]["path"])

    with pytest.raises(projection.ProjectionError, match="authority.credit"):
        projection.project_authority(
            receipt,
            external_authority=authority_path,
            resource_admission=signed_fixture["resource"],
        )


def test_nonce_and_resource_mismatch_cannot_be_supplied_as_caller_claim(
    signed_fixture: dict[str, object],
) -> None:
    receipt_path = Path(signed_fixture["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("authority")
    receipt["identity"]["nonce"] = "f" * 32
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = projection.canonical_digest(receipt)
    authority_path = Path(receipt["identity"]["external_authority"]["path"])

    with pytest.raises(projection.ProjectionError, match="plan_sha256|namespace|nonce"):
        projection.project_authority(
            receipt,
            external_authority=authority_path,
            resource_admission=signed_fixture["resource"],
        )

    valid_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    valid_receipt.pop("authority")
    forged_resource = copy.deepcopy(signed_fixture["resource"])
    forged_resource["gpu"]["free_mib"] -= 1
    forged_resource["gpu"]["identity_sha256"] = admission.canonical_digest(
        admission._gpu_identity(forged_resource["gpu"])
    )
    valid_receipt.pop("receipt_sha256")
    valid_receipt["receipt_sha256"] = projection.canonical_digest(valid_receipt)
    with pytest.raises(projection.ProjectionError, match="resource snapshot"):
        projection.project_authority(
            valid_receipt,
            external_authority=authority_path,
            resource_admission=forged_resource,
        )


def test_runner_reports_projection_gap_without_popen(tmp_path: Path, signed_fixture: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_path = tmp_path / "legacy-runner-receipt.json"
    _legacy_projection_candidate(signed_fixture, legacy_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("projection gap must not call Popen")

    monkeypatch.setattr(runner, "_REAL_POPEN", forbidden)
    report = runner.build_report(legacy_path, execute_requested=True)
    assert report["status"] == "blocked_fail_closed"
    assert report["popen_attempted"] is False
    assert report["wait_attempted"] is False
    assert any("projection-gap:" in reason for reason in report["blocked_reasons"])
    assert report["credit"] == 0
