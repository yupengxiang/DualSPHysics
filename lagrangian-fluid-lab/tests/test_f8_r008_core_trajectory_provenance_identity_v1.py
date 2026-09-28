from __future__ import annotations

import copy
import hashlib
import inspect
import json
from typing import Any

import pytest

from scripts import f8_r008_core_trajectory_provenance_identity_v1 as contract
from tests import test_f8_r008_trusted_worker_runtime_handoff_v1 as handoff_fixtures


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _chain() -> tuple[dict[str, Any], bytes, bytes, bytes, bytes, bytes]:
    handoff, handoff_raw, root_public, _active_key, identity_raw = handoff_fixtures._handoff()
    attempt = handoff["attempt"]
    subject = handoff["subject"]
    execution = handoff["execution"]
    inputs = handoff["inputs"]
    outputs = handoff["outputs"]
    artifact_id = "synthetic-core-trajectory-001"
    dispatch = {
        "schema": contract.DISPATCH_SCHEMA,
        "record_id": contract.DISPATCH_RECORD_ID,
        "status": contract.DISPATCH_STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "scope_id": contract.SCOPE_ID,
        "dispatch": {
            "dispatch_id": "synthetic-dispatch-001",
            "attempt_id": attempt["attempt_id"],
            "case_id": attempt["case_id"],
            "nonce_hex": attempt["nonce_hex"],
            "handoff_sha256": hashlib.sha256(handoff_raw).hexdigest(),
            "scheduler_principal_id": "synthetic-scheduler-001",
            "scheduler_runtime_sha256": _sha("synthetic-scheduler-runtime-001"),
            "scheduler_manifest_sha256": _sha("synthetic-scheduler-manifest-001"),
            "worker_principal_id": subject["worker_principal_id"],
            "runtime_principal_id": subject["runtime_principal_id"],
            "source_manifest_sha256": execution["source_manifest_sha256"],
            "runtime_manifest_sha256": execution["runtime_manifest_sha256"],
            "definition_sha256": inputs["definition_sha256"],
            "control_sha256": inputs["control_sha256"],
            "initial_state_sha256": inputs["initial_state_sha256"],
            "configuration_sha256": inputs["configuration_sha256"],
            "output_manifest_sha256": outputs["output_manifest_sha256"],
            "output_schema": outputs["output_schema"],
            "core_trajectory_artifact_id": artifact_id,
            "core_trajectory_schema": contract.CORE_TRAJECTORY_SCHEMA,
        },
    }
    dispatch_raw = _canonical(dispatch)
    dispatch_binding = dispatch["dispatch"]
    provenance = {
        "dispatch_sha256": hashlib.sha256(dispatch_raw).hexdigest(),
        "handoff_sha256": hashlib.sha256(handoff_raw).hexdigest(),
        "attempt_id": dispatch_binding["attempt_id"],
        "case_id": dispatch_binding["case_id"],
        "nonce_hex": dispatch_binding["nonce_hex"],
        "scheduler_principal_id": dispatch_binding["scheduler_principal_id"],
        "scheduler_runtime_sha256": dispatch_binding["scheduler_runtime_sha256"],
        "scheduler_manifest_sha256": dispatch_binding["scheduler_manifest_sha256"],
        "worker_principal_id": dispatch_binding["worker_principal_id"],
        "runtime_principal_id": dispatch_binding["runtime_principal_id"],
        "source_manifest_sha256": dispatch_binding["source_manifest_sha256"],
        "runtime_manifest_sha256": dispatch_binding["runtime_manifest_sha256"],
        "definition_sha256": dispatch_binding["definition_sha256"],
        "control_sha256": dispatch_binding["control_sha256"],
        "initial_state_sha256": dispatch_binding["initial_state_sha256"],
        "configuration_sha256": dispatch_binding["configuration_sha256"],
        "output_manifest_sha256": dispatch_binding["output_manifest_sha256"],
    }
    trajectory = {
        "schema": contract.TRAJECTORY_MANIFEST_SCHEMA,
        "record_id": contract.TRAJECTORY_MANIFEST_RECORD_ID,
        "status": contract.TRAJECTORY_MANIFEST_STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "scope_id": contract.SCOPE_ID,
        "trajectory": {
            "artifact_id": artifact_id,
            "relative_path": "synthetic/core-trajectory-v1.h5",
            "trajectory_schema": contract.CORE_TRAJECTORY_SCHEMA,
            "case_id": dispatch_binding["case_id"],
            "split": "qualification",
            "bytes": 4096,
            "sha256": _sha("synthetic-core-trajectory-bytes-001"),
            "frame_count": 3,
            "particle_count": 4,
            "source_table_sha256": _sha("synthetic-native-table-001"),
            "particle_zone_semantics": "all_native_fluid_particles_zone_zero",
            "fluid_only": True,
        },
        "provenance": provenance,
        "authorization": copy.deepcopy(contract.NON_AUTHORIZATION),
    }
    trajectory_raw = _canonical(trajectory)
    return handoff, handoff_raw, identity_raw, root_public, dispatch_raw, trajectory_raw


def _verify(fixture):
    _handoff, handoff_raw, identity_raw, root_public, dispatch_raw, trajectory_raw = fixture
    return contract.verify_synthetic_core_trajectory_provenance(
        handoff_raw=handoff_raw,
        identity_bundle_raw=identity_raw,
        trust_root_public_key_bytes=root_public,
        scheduler_dispatch_raw=dispatch_raw,
        core_trajectory_manifest_raw=trajectory_raw,
    )


def test_valid_synthetic_chain_binds_scheduler_to_core_without_authority() -> None:
    fixture = _chain()
    before = tuple(bytes(value) if isinstance(value, bytes) else copy.deepcopy(value)
                   for value in fixture)
    result = _verify(fixture)

    assert result["status"] == contract.STATUS
    assert result["provenance_identity_verified"] is True
    assert result["handoff_binding"]["identity_chain_consistent"] is True
    assert result["scheduler_binding"]["dispatch_to_handoff_consistent"] is True
    assert result["scheduler_binding"]["scheduler_identity_authenticated"] is False
    assert result["core_trajectory_binding"]["manifest_to_dispatch_consistent"] is True
    assert result["core_trajectory_binding"]["artifact_content_verified"] is False
    assert result["diagnostic_only"] is True
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0
    assert result["registry_mutation"] == 0
    assert result["ledger_mutation"] == 0
    assert tuple(bytes(value) if isinstance(value, bytes) else copy.deepcopy(value)
                 for value in fixture) == before


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("dispatch", "handoff_sha256"), "0" * 64, "handoff_sha256"),
        (("dispatch", "case_id"), "synthetic-case-other", "case_id"),
        (("dispatch", "output_schema"), "production-output", "output schema"),
    ],
)
def test_scheduler_rebinding_fails_closed(path, value, message) -> None:
    _handoff, handoff_raw, identity_raw, root_public, dispatch_raw, trajectory_raw = _chain()
    dispatch = json.loads(dispatch_raw)
    target = dispatch
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match=message):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
            scheduler_dispatch_raw=_canonical(dispatch),
            core_trajectory_manifest_raw=trajectory_raw,
        )


def test_core_manifest_digest_and_identity_rebinding_fail_closed() -> None:
    _handoff, handoff_raw, identity_raw, root_public, dispatch_raw, trajectory_raw = _chain()
    trajectory = json.loads(trajectory_raw)
    trajectory["provenance"]["dispatch_sha256"] = "0" * 64
    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match="dispatch_sha256"):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
            scheduler_dispatch_raw=dispatch_raw,
            core_trajectory_manifest_raw=_canonical(trajectory),
        )

    trajectory = json.loads(trajectory_raw)
    trajectory["trajectory"]["relative_path"] = "../production/core.h5"
    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match="relative_path"):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
            scheduler_dispatch_raw=dispatch_raw,
            core_trajectory_manifest_raw=_canonical(trajectory),
        )


def test_authorization_promotion_and_production_origin_are_rejected() -> None:
    _handoff, handoff_raw, identity_raw, root_public, dispatch_raw, trajectory_raw = _chain()
    trajectory = json.loads(trajectory_raw)
    trajectory["authorization"]["qualification_credit"] = 1
    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match="authority"):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
            scheduler_dispatch_raw=dispatch_raw,
            core_trajectory_manifest_raw=_canonical(trajectory),
        )

    dispatch = json.loads(dispatch_raw)
    dispatch["input_origin"] = "production_solver"
    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match="synthetic_fixture"):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
            scheduler_dispatch_raw=_canonical(dispatch),
            core_trajectory_manifest_raw=trajectory_raw,
        )


def test_noncanonical_and_oversized_input_are_rejected_before_projection() -> None:
    fixture = _chain()
    _handoff, handoff_raw, identity_raw, root_public, dispatch_raw, trajectory_raw = fixture
    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match="canonical"):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
            scheduler_dispatch_raw=dispatch_raw + b"\n",
            core_trajectory_manifest_raw=trajectory_raw,
        )

    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match="bounded JSON"):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
            scheduler_dispatch_raw=dispatch_raw,
            core_trajectory_manifest_raw=b"{" + b"x" * contract.MAX_JSON_BYTES,
        )


def test_delegated_handoff_identity_failure_is_not_masked() -> None:
    _handoff, handoff_raw, identity_raw, root_public, dispatch_raw, trajectory_raw = _chain()
    with pytest.raises(contract.CoreTrajectoryProvenanceIdentityError, match="handoff verification"):
        contract.verify_synthetic_core_trajectory_provenance(
            handoff_raw=handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=bytes(32),
            scheduler_dispatch_raw=dispatch_raw,
            core_trajectory_manifest_raw=trajectory_raw,
        )


def test_contract_has_no_runtime_execution_or_artifact_read_surface() -> None:
    source = inspect.getsource(contract)
    for forbidden in ("subprocess", "os.system", "Popen", "h5py", "open(", "ctypes"):
        assert forbidden not in source


def test_checked_in_report_matches_deterministic_contract_report() -> None:
    report_path = contract.__file__.replace("/scripts/", "/reports/")
    report_path = report_path.replace(
        "f8_r008_core_trajectory_provenance_identity_v1.py",
        "F8-R008-CORE-TRAJECTORY-PROVENANCE-IDENTITY-CONTRACT-V1.json",
    )
    with open(report_path, encoding="utf-8") as stream:
        checked_in = json.load(stream)
    assert checked_in == contract.build_report()
    assert checked_in["non_authorizing_boundary"] == contract.NON_AUTHORIZATION
