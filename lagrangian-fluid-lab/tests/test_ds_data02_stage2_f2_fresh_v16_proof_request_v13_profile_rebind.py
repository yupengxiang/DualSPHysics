"""Source-bound ROOT197 observer-profile rebind tests.

The real test reads only the failed ROOT194 request, the copied V66 worker
request, and small semantic metadata.  It must never read the typed HDF5,
V16 result, BI4, or native arrays.  The V13 bridge replaces the stale
ROOT194 profile digest with the producer's canonical digest while preserving
ROOT194 as failed provenance.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_request_v13_profile_rebind.py"
ROOT191 = ROOT / "scripts" / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v1.py"
V8_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"

ROOT194_REQUEST = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f2-root194-v67-fresh-proof-root-prepared-194-002/root194-proof-request.json"
)
ACTUAL_WORKER = Path(
    "/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/"
    "bundle-target/runtime/native/f2-s1-v64-worker-request.json"
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load_module(SCRIPT, "root197_profile_rebind_test_module")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(not ROOT194_REQUEST.is_file() or not ACTUAL_WORKER.is_file(),
                    reason="real ROOT194/V66 source metadata is not mounted")
def test_real_root194_profile_rebind_and_v8_metadata_preflight(tmp_path: Path):
    sidecar = tmp_path / "root197-profile-sidecar.json"
    request = tmp_path / "root197-v13-request.json"
    result = S.build_request(
        root194_request=ROOT194_REQUEST,
        producer_worker_request=ACTUAL_WORKER,
        sidecar_output=sidecar,
        output=request,
        case_id="STAGE2_F2_ROOT197_V13_PROFILE_REBIND_20261009",
        attempt_id="f2-s1-root197-v13-profile-rebind-001",
        fresh_output_root=tmp_path / "STAGE2_F2_ROOT197_FRESH_PROOF",
    )
    assert result["payload_read"] is False
    assert result["hdf5_or_bi4_read"] is False
    assert result["root194_failed_profile_sha256"] == (
        "4863f4cdd73c28a140b0152c79dd622d2e41c8da47b6cac996f7c852622ce774"
    )
    assert result["actual_profile_sha256"] == S.EXPECTED_PROFILE_SHA
    assert S.validate_request(request, sidecar)["status"] == (
        "ROOT197_PROFILE_METADATA_VALIDATED_READY_FOR_PARENT"
    )

    # The actual V8 validator accepts the new request at metadata stage.  Its
    # result/typed paths are producer bindings and intentionally do not exist
    # in this test's process.
    v8 = load_module(V8_SCRIPT, "root197_v8_metadata_preflight")
    value = json.loads(request.read_text(encoding="utf-8"))
    checked = v8._validate_request(value, verify_result_stat=False)
    assert checked["expected"]["time"]["observer_profile_sha256"] == S.EXPECTED_PROFILE_SHA
    assert not (tmp_path / "STAGE2_F2_ROOT197_FRESH_PROOF").exists()


@pytest.mark.skipif(not ROOT194_REQUEST.is_file() or not ACTUAL_WORKER.is_file(),
                    reason="real ROOT194/V66 source metadata is not mounted")
def test_real_profile_sha_mismatch_is_rejected_before_output(tmp_path: Path):
    worker = json.loads(ACTUAL_WORKER.read_text(encoding="utf-8"))
    worker["v15_request"]["observer_profile"]["sha256"] = "0" * 64
    bad_worker = tmp_path / "bad-worker-request.json"
    bad_worker.write_text(json.dumps(worker, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(S.ProfileRebindError, match="canonical SHA differs"):
        S.build_request(
            root194_request=ROOT194_REQUEST,
            producer_worker_request=bad_worker,
            sidecar_output=tmp_path / "sidecar.json",
            output=tmp_path / "request.json",
            case_id="STAGE2_F2_ROOT197_V13_PROFILE_REBIND_BAD_20261009",
            attempt_id="f2-s1-root197-profile-bad-001",
            fresh_output_root=tmp_path / "STAGE2_F2_ROOT197_BAD",
        )
    assert not (tmp_path / "sidecar.json").exists()
    assert not (tmp_path / "request.json").exists()


@pytest.mark.skipif(not ROOT194_REQUEST.is_file() or not ACTUAL_WORKER.is_file(),
                    reason="real ROOT194/V66 source metadata is not mounted")
def test_real_profile_rebind_cli_build_and_validate(tmp_path: Path):
    sidecar = tmp_path / "sidecar.json"
    request = tmp_path / "request.json"
    build = subprocess.run(
        [sys.executable, str(SCRIPT), "build-request",
         "--root194-request", str(ROOT194_REQUEST),
         "--producer-worker-request", str(ACTUAL_WORKER),
         "--sidecar-output", str(sidecar), "--output", str(request),
         "--case-id", "STAGE2_F2_ROOT197_V13_PROFILE_REBIND_CLI_20261009",
         "--attempt-id", "f2-s1-root197-profile-rebind-cli-001",
         "--fresh-output-root", str(tmp_path / "STAGE2_F2_ROOT197_CLI")],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert build.returncode == 0, build.stderr
    validate = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--request", str(request),
         "--sidecar", str(sidecar)],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert validate.returncode == 0, validate.stderr
    assert "ROOT197_PROFILE_METADATA_VALIDATED_READY_FOR_PARENT" in validate.stdout


def test_profile_source_binding_schema_preserves_actual_sha_and_rejects_existing_output(tmp_path: Path):
    # A small, deterministic contract check protects the no-overwrite rule
    # even when the real source metadata is unavailable in a CI checkout.
    binding = {
        "schema": S.PROFILE_BINDING_SCHEMA,
        "actual_profile_sha256": S.EXPECTED_PROFILE_SHA,
        "current_catalog_sha256": S.CURRENT_SHA,
    }
    assert binding["actual_profile_sha256"] != (
        "4863f4cdd73c28a140b0152c79dd622d2e41c8da47b6cac996f7c852622ce774"
    )
    destination = tmp_path / "existing.json"
    destination.write_text("immutable\n", encoding="utf-8")
    with pytest.raises(S.ProfileRebindError, match="existing profile-rebind output"):
        S._write_new(destination, binding)
