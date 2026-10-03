"""Unit tests for F2 RV4 matched CENTER coarse & medium terminal NVMe postprocess v2.

Preparation-only tests verifying:
1. Physical binding invariants & negative rejection on corrupted geometry/hash.
2. Source hash transition & streaming verification failure on mismatch.
3. Strict compliance with shared runner validate_request (scripts/ds_data02_runtime_v2.py).
4. No execute_all bypass, no fabricated execution receipts.
5. Byte-for-byte preservation of all v1 historical evidence and artifacts.
6. Safe failure of build-labels prior to completed pose execution.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "f2_rv4eq_matched_center_terminal_nvme_postprocess_v2.py"
spec = importlib.util.spec_from_file_location("f2_matched_center_postprocess_v2", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
postprocess_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(postprocess_mod)

FAMILY_ROOT = postprocess_mod.FAMILY_ROOT
INTEGRATION_LAB = postprocess_mod.INTEGRATION_LAB
HANDOFF_ROOT = postprocess_mod.HANDOFF_ROOT
OWNER_DIR = postprocess_mod.OWNER_DIR
CONFIGS_DIR = postprocess_mod.CONFIGS_DIR
REQUESTS_DIR = postprocess_mod.REQUESTS_DIR
CASES = postprocess_mod.CASES
DATA_ROOT = postprocess_mod.DATA_ROOT
F2_DATA = postprocess_mod.F2_DATA

# Import shared runtime validator
sys.path.insert(0, str(INTEGRATION_LAB / "scripts"))
from ds_data02_runtime_v2 import validate_request


def test_v2_module_structure_and_no_execute_all():
    # v2 must NOT provide an execute_all function or bypass
    assert not hasattr(postprocess_mod, "execute_all"), "execute_all bypass must be removed in v2"
    
    # Read script text to ensure no execution-receipt.json writer logic
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "execution-receipt.json" not in script_text or "dump_json" not in script_text.split("execution-receipt.json")[0][-50:], (
        "v2 must never write execution-receipt.json; execution receipts belong exclusively to the shared runner"
    )


def test_verified_copy_stream_hashing_and_permissions(tmp_path: Path):
    source = tmp_path / "test_source.bin"
    payload = b"center-v2-stream-hash-test" * 2048
    source.write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest()

    target = tmp_path / "private_target.bin"
    evidence = postprocess_mod.verified_copy(source, target, expected_sha, len(payload))

    assert target.is_file()
    assert target.read_bytes() == payload
    assert evidence["private_reader_sha256"] == expected_sha
    assert evidence["private_reader_bytes"] == len(payload)
    assert evidence["copy_verified_during_stream"] is True
    # Permissions must be 0400 read-only
    assert target.stat().st_mode & 0o777 == 0o400

    # Negative test 1: byte size mismatch raises PostprocessError
    bad_size_target = tmp_path / "bad_size_target.bin"
    with pytest.raises(postprocess_mod.PostprocessError, match="byte size"):
        postprocess_mod.verified_copy(source, bad_size_target, expected_sha, len(payload) + 10)

    # Negative test 2: SHA mismatch raises PostprocessError and cleans up target
    bad_sha_target = tmp_path / "bad_sha_target.bin"
    with pytest.raises(postprocess_mod.PostprocessError, match="SHA mismatch"):
        postprocess_mod.verified_copy(source, bad_sha_target, "0" * 64, len(payload))
    assert not bad_sha_target.exists(), "unverified target must be removed on hash mismatch"


def test_owner_metadata_physical_binding_and_invariants():
    for name, info in CASES.items():
        owner = postprocess_mod.build_owner_metadata(info)
        assert owner["schema"] == "ds02.f2.case-owner-metadata.v2"
        assert owner["family_id"] == "F2"
        assert owner["case_id"] == info["case_id"]
        assert owner["resolution"] == info["resolution"]
        assert math.isclose(owner["mass_reference"]["continuous_mass_kg"], 24.576, rel_tol=1e-9)
        assert owner["physical_binding"]["physical_condition_hash_declared"] == "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43"
        
        # Geometry bounding boxes
        geom = owner["geometry"]
        assert geom["cup_low_m"] == [0.0, -0.15, 0.65]
        assert geom["cup_size_m"] == [0.425, 0.3, 0.45]
        assert geom["receiver_low_m"] == [0.45, -0.3, 0.0]
        assert geom["receiver_size_m"] == [1.1, 0.6, 0.45]
        assert geom["tray_low_m"] == [-1.2, -1.0, -0.2]
        assert geom["tray_size_m"] == [4.0, 2.0, 0.15]


def test_source_hash_transition_and_binding_integrity():
    for name, info in CASES.items():
        source_h5 = Path(info["source_h5"])
        assert source_h5.is_file(), f"canonical source trajectory missing: {source_h5}"
        assert source_h5.stat().st_size == info["source_h5_bytes"]

        # Binding helper must succeed with known SHA
        b = postprocess_mod.binding(source_h5, "source trajectory", known_sha=info["source_h5_sha256"])
        assert b["sha256"] == info["source_h5_sha256"]
        assert b["bytes"] == info["source_h5_bytes"]

        # Negative test: simulated source mutation / corrupted SHA raises PostprocessError
        corrupted_sha = "f" * 64
        with pytest.raises(postprocess_mod.PostprocessError, match="SHA mismatch"):
            postprocess_mod.binding(source_h5, "corrupted check", known_sha=corrupted_sha)


def test_v2_pose_requests_pass_shared_runner_validation():
    postprocess_mod.build_all()

    for name, info in CASES.items():
        short = info["short_name"]
        req_path = REQUESTS_DIR / f"{short}_pose_nvme_request_v2.json"
        assert req_path.is_file(), f"missing request: {req_path}"
        req = json.loads(req_path.read_text(encoding="utf-8"))

        # 1. Shared runtime validation
        verified_hashes = validate_request(req)
        assert len(verified_hashes) == len(req["input_files"])

        # 2. Schema and fields
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["family_id"] == "F2"
        assert req["case_id"] == info["case_id"]
        assert req["attempt_id"] == f"matched-center-{name}-nvme-pose-v2-001"
        assert req["kind"] == "cpu"
        assert req["cpu_task_kind"] == "labels"
        assert req["cpu_threads"] == 2
        assert req["max_wall_seconds"] <= 3600
        assert req["conversion_launch_forbidden"] is True
        assert req["claim_boundary"]["q_n"] == "not_assessed"
        assert req["independent_case_count_increment"] == 0


def test_build_labels_fails_safely_when_pose_not_yet_executed(tmp_path: Path):
    # build-labels must strictly refuse to generate requests if pose stage is not completed
    with pytest.raises(postprocess_mod.PostprocessError, match="missing"):
        postprocess_mod.build_labels_for_case("coarse", pose_attempt_dir=tmp_path / "nonexistent-pose-dir")


def test_preserve_all_v1_files_byte_for_byte():
    v1_script = FAMILY_ROOT / "f2_rv4eq_matched_center_terminal_nvme_postprocess_v1.py"
    assert v1_script.is_file()
    assert postprocess_mod.sha256_file(v1_script) == "78db3c54eacbf40106c4148e2117e82bb14c691f9575213f0a6ac5fc9fdaeefb"

    v1_artifact = FAMILY_ROOT / "handoff_20261003/matched_center_terminal_nvme_v1/artifacts/f2_rv4eq_matched_center_3dp_macro_synthesis_v1.json"
    assert v1_artifact.is_file()
    assert postprocess_mod.sha256_file(v1_artifact) == "dbda3de796cff4cdf827397150e170f2053ec810e7ada24df746bdabbecd2955"

    v1_coarse_pose_req = FAMILY_ROOT / "handoff_20261003/matched_center_terminal_nvme_v1/requests/center_coarse_pose_nvme_request_v1.json"
    assert v1_coarse_pose_req.is_file()
    assert postprocess_mod.sha256_file(v1_coarse_pose_req) == "fecb38d516880ed735acad2e87c63b39340daa4ac860ece588bb5e8bdfe5955f"


def test_root_review_reconciliation_medium_hash():
    # Verify Root review finding: actual canonical medium pose H5 in v1-001 has SHA 24b01864... and 2139748514 bytes
    v1_medium_pose_h5 = F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/matched-center-medium-nvme-pose-v1-001/trajectory-with-actual-pose.h5"
    if v1_medium_pose_h5.is_file():
        assert postprocess_mod.sha256_file(v1_medium_pose_h5) == "24b01864051a6b9b73d582d772e4d52d8cc01f1a19d833dc33d9e4cf2a298b67"
        assert v1_medium_pose_h5.stat().st_size == 2139748514
