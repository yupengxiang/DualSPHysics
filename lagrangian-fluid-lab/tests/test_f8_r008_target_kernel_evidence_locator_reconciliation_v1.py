from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_r008_target_kernel_evidence_locator_reconciliation_v1 as locator


ROOT = locator.LAB_ROOT
INTAKE_REPORT = ROOT / "reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _valid_external_intake(tmp_path: Path) -> Path:
    value = _read(INTAKE_REPORT)
    value["status"] = "external_target_evidence_intake_valid_non_authorizing"
    value["manifest"] = {
        "path": "external/real-target/manifest.json",
        "exists": True,
        "bytes": 512,
        "sha256": hashlib.sha256(b"external manifest").hexdigest(),
    }
    source_hash = hashlib.sha256(b"source tree evidence").hexdigest()
    uapi_hash = hashlib.sha256(b"complete uapi evidence").hexdigest()
    config_hash = hashlib.sha256(b"external target config").hexdigest()
    value["declared_target"] = {
        "kernel_release": "6.8.0-target-20260928",
        "source_commit": hashlib.sha1(b"target source commit").hexdigest(),
        "source_tree_sha256": source_hash,
        "uapi_sha256": uapi_hash,
        "build_id": hashlib.sha256(b"target build identity").hexdigest(),
        "config_sha256": config_hash,
        "required_options": [
            {"name": "CONFIG_FANOTIFY", "value": "y"},
            {"name": "CONFIG_FANOTIFY_ACCESS_PERMISSIONS", "value": "y"},
            {"name": "CONFIG_SECCOMP", "value": "y"},
            {"name": "CONFIG_SECCOMP_FILTER", "value": "y"},
            {"name": "CONFIG_X86_X32_ABI", "value": "n"},
        ],
    }
    artifacts = {
        "source": ("source.json", source_hash),
        "uapi": ("uapi.json", uapi_hash),
        "config": ("config.txt", config_hash),
        "build": ("build.json", hashlib.sha256(b"build provenance").hexdigest()),
    }
    value["artifacts"] = {
        role: {
            "path": f"external/real-target/{name}",
            "declared_bytes": 32,
            "declared_sha256": digest,
            "observed_bytes": 32,
            "observed_sha256": digest,
            "verified": True,
        }
        for role, (name, digest) in artifacts.items()
    }
    value["validation"] = {
        "manifest_present": True,
        "manifest_valid": True,
        "artifact_files_verified": True,
        "external_target_evidence_complete": True,
        "blockers": [],
    }
    value["pins"] = {field: True for field in value["pins"]}
    path = tmp_path / "valid-intake.json"
    _write(path, value)
    return path


def test_default_locator_is_blocked_but_lists_local_only_candidates() -> None:
    report = locator.build_report()

    assert report["status"] == locator.STATUS
    assert report["reconciliation"]["external_target_binding"]["complete"] is False
    assert report["reconciliation"]["external_target_binding"]["missing_pins"] == list(locator.PIN_FIELDS)
    assert report["artifact_locator"]["bindable_artifacts"] == []
    assert report["artifact_locator"]["local_candidates_are_external_pin_eligible"] is False
    assert report["local_observation"]["matching_config_observed"] is True
    assert report["local_observation"]["uapi_sample_complete"] is True
    assert report["authorization"] == locator.AUTHORIZATION


def test_local_kernel_release_and_config_never_become_external_pins() -> None:
    report = locator.build_report()
    rows = {item["pin"]: item for item in report["pin_reconciliation"]}

    assert rows["kernel_release"]["local_observed"] is True
    assert rows["kernel_release"]["external_pin_verified"] is False
    assert rows["kernel_release"]["state"] == "local_observation_not_external_pin"
    assert rows["config"]["local_observed"] is True
    assert rows["config"]["external_pin_verified"] is False
    assert rows["uapi"]["local_sample_only"] is True
    assert rows["source_tree"]["local_observed"] is False
    assert rows["build_id"]["local_observed"] is False


def test_locator_does_not_follow_external_artifact_references() -> None:
    report = locator.build_report()
    external = [
        item for item in report["artifact_locator"]["candidates"]
        if item["origin"] == "external_target_evidence"
    ]

    assert all(item["read_by_locator"] is False for item in external)
    assert report["read_policy"]["external_artifact_reference_followed"] is False
    assert "external_artifact_reference_follow_or_open" in report["prohibited_operations"]


def test_valid_external_intake_closes_only_the_artifact_binding(tmp_path: Path) -> None:
    intake_path = _valid_external_intake(tmp_path)
    report = locator.build_report(
        dependency_paths={"target_kernel_evidence_intake": intake_path}
    )
    locator.validate_report(report)

    binding = report["reconciliation"]["external_target_binding"]
    assert binding["complete"] is True
    assert binding["state"] == "external_artifacts_bound_non_authorizing"
    assert set(binding["verified_artifact_roles"]) == {"source", "uapi", "config", "build"}
    assert binding["missing_pins"] == []
    assert set(report["artifact_locator"]["bindable_artifacts"]) == {
        "external_target_evidence_manifest",
        "external_source_artifact",
        "external_uapi_artifact",
        "external_config_artifact",
        "external_build_artifact",
    }
    assert report["runtime_reconciliation"]["all_runtime_identity_blockers_closed"] is False
    assert report["authorization"]["readiness_pass"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["qualification_credit"] == 0
    assert "admission_bridge_dependency_binding_drift" in report["reconciliation"]["stale_upstream_views"]


def test_target_intake_digest_drift_is_visible_when_binding_closes(tmp_path: Path) -> None:
    intake_path = _valid_external_intake(tmp_path)
    report = locator.build_report(
        dependency_paths={"target_kernel_evidence_intake": intake_path}
    )

    assert report["reconciliation"]["all_current_dependency_bindings_match"] is False
    assert report["reconciliation"]["runtime_identity_reconciled"] is False
    assert report["reconciliation"]["readiness_reconciled"] is False


def test_promoted_local_inventory_is_rejected(tmp_path: Path) -> None:
    local_path = ROOT / "reports/F8-R008-TARGET-KERNEL-LOCAL-INVENTORY-V1-2026-09-28.json"
    value = _read(local_path)
    value["validation"]["required_pins_complete"] = True
    path = tmp_path / "promoted-local.json"
    _write(path, value)

    with pytest.raises(locator.LocatorReconciliationError, match="complete pins"):
        locator.build_report(
            dependency_paths={"target_kernel_local_inventory": path}
        )


def test_promoted_readiness_or_handoff_is_rejected(tmp_path: Path) -> None:
    readiness_path = ROOT / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v8/receipt.json"
    readiness = _read(readiness_path)
    readiness["readiness_pass"] = True
    readiness_copy = tmp_path / "promoted-readiness.json"
    _write(readiness_copy, readiness)
    with pytest.raises(locator.LocatorReconciliationError, match="promoted"):
        locator.build_report(dependency_paths={"readiness_v8": readiness_copy})

    handoff_path = ROOT / "reports/F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json"
    handoff = _read(handoff_path)
    handoff["input_boundary"]["synthetic_only"] = False
    handoff_copy = tmp_path / "promoted-handoff.json"
    _write(handoff_copy, handoff)
    with pytest.raises(locator.LocatorReconciliationError, match="synthetic-only"):
        locator.build_report(dependency_paths={"trusted_handoff": handoff_copy})


def test_duplicate_json_dependency_fails_closed(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"schema":"one","schema":"two"}')

    with pytest.raises(locator.LocatorReconciliationError, match="duplicate JSON object key"):
        locator.build_report(dependency_paths={"target_kernel_evidence_intake": duplicate})


def test_report_contract_and_checked_in_report_bind() -> None:
    expected = locator.build_report()
    locator.validate_report(expected)
    checked_in = locator.verify_report()

    assert checked_in == expected
    assert checked_in["mutations"] == locator.MUTATIONS
    assert checked_in["side_effects"] == locator.SIDE_EFFECTS
    assert all(item["severity"] == "high" for item in checked_in["identity_blockers"])


def test_report_rejects_external_promotion_of_local_candidate() -> None:
    value = copy.deepcopy(locator.build_report())
    candidate = next(
        item for item in value["artifact_locator"]["candidates"]
        if item["origin"] == "local_host_observation"
    )
    candidate["external_pin_eligible"] = True

    with pytest.raises(locator.LocatorReconciliationError, match="local candidate was promoted"):
        locator.validate_report(value)


def test_report_rejects_nonzero_authority_or_missing_blocker() -> None:
    value = copy.deepcopy(locator.build_report())
    value["authorization"]["qualification_credit"] = 1
    with pytest.raises(locator.LocatorReconciliationError, match="authorization boundary"):
        locator.validate_report(value)

    value = copy.deepcopy(locator.build_report())
    value["identity_blockers"] = []
    with pytest.raises(locator.LocatorReconciliationError, match="identity blocker"):
        locator.validate_report(value)
