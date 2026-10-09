from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_domain_active_stream_v10.py"
SPEC = importlib.util.spec_from_file_location("f2_coarse_domain_active_stream_v10", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REQUEST_DIR = ROOT / (
    "campaigns/ds-data-02/stage2/requests/"
    "f2-coarse-domain-active-stream-v10-root-prepared-138-001"
)
MANIFEST = REQUEST_DIR / "f2-coarse-domain-active-stream-v10-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-domain-active-stream-v10-request.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_root130_metadata_and_v7_source_closure_pass_without_frame_decode() -> None:
    manifest = MODULE.read_json(MANIFEST, "manifest")
    paths, raw_root = MODULE._validate_manifest(manifest)
    request, receipt, proof, runparts = MODULE._validate_domain_binding(manifest, paths, raw_root)
    v7 = MODULE._validate_v7(paths)

    assert request["case_id"] == MODULE.CASE_KEY
    assert receipt["status"] == "COMPLETED_DEVELOPMENT_UNKNOWN"
    assert proof["native_frame_files_stat_only_count"] == 401
    assert runparts["saved_window_new_exclusion_sums"]["NpOut"] == 67.0
    assert len(manifest["frames"]) == 401
    assert all(frame["sha256"] == "PARENT_GUARD_COMPUTED" for frame in manifest["frames"])
    assert v7["expected_native_massfluid_bits_hex"] == "000000009a54463f"
    assert manifest["source_scope"]["runparts_67_is_log_check_only"] is True


def test_root138_request_binds_worker_helper_and_deferred_frame_policy() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared_script = str(Path(request["command"][1]).resolve())
    declared_helper = next(
        key for key in request["input_sha256"] if key.endswith("ds_data02_stage2_f2_coarse_active_stream_v10.py")
    )
    assert request["input_sha256"][declared_script] == _sha(SCRIPT)
    assert request["input_sha256"][declared_helper] == _sha(ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v10.py")
    assert request["source_binding"]["root130_scope_exact"] is True
    assert request["guard_policy"]["raw_frame_pre_post_full_sha_required"] is True
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert manifest["expected"]["expected_native_loss_is_runparts_count_only"] is True
    assert manifest["expected"]["expected_native_loss_count"] == 67


def test_root130_case_mutation_is_rejected() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["case_key"] = "F2_WRONG_REFERENCE_CASE"
    with pytest.raises(MODULE.DomainStreamError, match="case identity differs"):
        MODULE._validate_manifest(manifest)


def test_root130_proof_count_is_not_accepted_as_identity_rows(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["source_scope"]["runparts_67_is_log_check_only"] = False
    altered = tmp_path / "manifest.json"
    altered.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = MODULE.read_json(altered, "altered manifest")
    # The source contract itself must carry this distinction; a future worker
    # cannot silently turn the aggregate 67 into fabricated Idp rows.
    assert loaded["source_scope"]["runparts_67_is_log_check_only"] is False
    assert loaded["expected"]["expected_native_loss_count"] == 67
    with pytest.raises(MODULE.DomainStreamError, match="runparts_67_is_log_check_only"):
        MODULE._validate_manifest(loaded)
