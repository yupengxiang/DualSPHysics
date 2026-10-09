"""ROOT191 V3 tests.

The real metadata test consumes the successful ROOT200 receipt/checkpoint and
179C source-side evidence, but never opens the 62 MB V16 JSON, HDF5, BI4, or
native inputs.  The callable-run test uses a bounded manufactured child result
and executes the V3 run path end to end; the semantic hooks are deliberately
small stand-ins so the test cannot grant scientific credit.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v3.py"
ROOT_DATA = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab")
INNER = ROOT_DATA / "campaigns/ds-data-02/stage2/requests/f2-root200-profile-output-fresh-proof-root-prepared-200-001/root200-profile-proof-request.json"
WRAPPER = ROOT_DATA / "campaigns/ds-data-02/stage2/requests/f2-root200-profile-output-fresh-proof-root-forward-200-001.json"
RECEIPT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/f2-s1-root200-v14-profile-output-001-root-forward-030-001/execution-receipt.json")
CHECKPOINT = ROOT_DATA / "campaigns/ds-data-02/stage2/checkpoints/F2_FRESH_V16_PROFILE_OUTPUT_ROOT_PROOF_V12_ACTUAL_ROOT_VERIFICATION_200.json"
PROOF = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/f2-s1-root200-v14-profile-output-001-root-forward-030-001/fresh-v16-proof-v12.json")
PRODUCER = ROOT_DATA / "campaigns/ds-data-02/stage2/requests/f2-s1-root145-v66-root179c-primary-prepared-003.json"
PRODUCER_DIR = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/f2-s1-v66-root179c-003")
PRODUCER_PARENT = PRODUCER_DIR / "actual-returned-parent-report.json"
PRODUCER_RECEIPT = PRODUCER_DIR / "execution-receipt.json"
PRODUCER_PROOF = ROOT_DATA / "campaigns/ds-data-02/stage2/checkpoints/F2_ROOT179C_V66_ACTUAL_CONVERSION_LABEL_INTERFACE_ROOT_VERIFICATION.json"
FROZEN = ROOT_DATA / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"


def load_module():
    spec = importlib.util.spec_from_file_location("root191_v3_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load_module()


def _require_real_inputs():
    paths = [INNER, WRAPPER, RECEIPT, CHECKPOINT, PROOF, PRODUCER,
             PRODUCER_PARENT, PRODUCER_RECEIPT, PRODUCER_PROOF, FROZEN]
    if not all(path.is_file() for path in paths):
        pytest.skip("ROOT200/179C actual metadata is not mounted")


def test_root200_receipt_is_guard_report_without_closedledger():
    _require_real_inputs()
    pair = S._load_pair(INNER, WRAPPER)
    info = S._validate_root200_receipt(RECEIPT, pair)
    checkpoint = S._validate_root200_checkpoint(CHECKPOINT, pair, info, PROOF)
    assert info["schema"] == "ds02.execution-receipt.v1"
    assert info["status"] == "completed"
    assert checkpoint["parent_charge"]["status"] == "completed"
    assert checkpoint["repeat_fee_idempotent"] is True


def test_root200_v12_request_hash_is_inner_file_sha_not_canonical():
    _require_real_inputs()
    pair = S._load_pair(INNER, WRAPPER)
    info = S._validate_v12_proof_v3(PROOF, pair)
    assert info["request_file_sha256"] == pair["inner_file_sha"]
    assert pair["inner_file_sha"] != pair["inner_canonical_sha"]


def test_v3_real_metadata_build_and_validate(tmp_path: Path):
    _require_real_inputs()
    output = tmp_path / "root191-v3-request.json"
    result = S._build_request(
        root200_inner=INNER, root200_wrapper=WRAPPER, root200_receipt=RECEIPT,
        root200_checkpoint=CHECKPOINT, root200_v12_proof=PROOF,
        producer_request=PRODUCER, producer_parent_report=PRODUCER_PARENT,
        producer_receipt=PRODUCER_RECEIPT, producer_root_proof=PRODUCER_PROOF,
        frozen_request=FROZEN, output=output,
        case_id="STAGE2_F2_ROOT191_V3_TYPED_ONLY_NO_MODEL_20261009",
        attempt_id="f2-s1-root191-v3-typed-only-no-model-001",
        fresh_output_root=tmp_path / "STAGE2_F2_ROOT191_V3_FRESH",
    )
    assert result["payload_read"] is False
    checked = S.validate_request(output)
    assert checked["status"] == "ROOT191_V3_METADATA_VALIDATED_READY_FOR_PARENT"
    assert checked["root200_receipt"]["status"] == "completed"
    assert not (tmp_path / "STAGE2_F2_ROOT191_V3_FRESH").exists()


def test_v3_callable_run_manufactured_child_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Exercise run, report writing, parent check, and output containment.

    The real V8/V12 scorer is intentionally not replaced in production code.
    This bounded test replaces only the semantic child hooks with a small
    manufactured result, so no test fixture can be mistaken for ROOT200
    scientific evidence.
    """
    _require_real_inputs()
    request = {
        "schema": S.REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "family_id": "F2",
        "case_id": "STAGE2_F2_ROOT191_V3_MANUFACTURED",
        "attempt_id": "f2-s1-root191-v3-manufactured-001",
        "model_invoked": False, "cfd_invoked": False,
        "quality": dict(S.UNKNOWN), "qualification": dict(S.UNKNOWN),
        "root200_binding": {
            "inner_request": {"path": str(INNER)}, "outer_wrapper": {"path": str(WRAPPER)},
            "result": {"path": str(tmp_path / "tiny-result.json"), "sha256": "0" * 64, "bytes": 2},
            "completed_execution_receipt": {}, "actual_verification_checkpoint": {}, "fresh_v12_proof": {},
        },
        "source_frozen_request": {"path": str(FROZEN), "file_sha256": S.sha256_file(FROZEN)},
        "producer_179c_binding": {},
        "source_binding": {"current_catalog_sha256": S.CURRENT_SHA, "observer_profile_sha256": S.PROFILE_SHA,
                           "cohort_selected_count": S.COHORT_COUNT, "cohort_identity_sha256": S.COHORT_IDENTITY_SHA},
        "fresh_output_namespace": {"root": str(tmp_path / "STAGE2_F2_ROOT191_V3_MANUFACTURED"), "is_new": True},
        "execution": {"max_wall_seconds": 30.0, "read_hdf5_or_bi4": False, "raw_opened": False,
                       "original_path_fallback": "FORBIDDEN"},
        "old_proof_reuse": False, "fresh_cold_credit": False,
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    tiny = tmp_path / "tiny-result.json"
    tiny.write_text("{}", encoding="utf-8")
    tiny_sha = S.sha256_file(tiny)
    request["root200_binding"]["result"].update({"sha256": tiny_sha, "bytes": tiny.stat().st_size})
    request["sha256"] = S.canonical_sha(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    tiny_result = {"schema": "manufactured.v16", "cohort": {"selected_count": 0},
                   "initial_mass_denominator": {}, "frame_observations": [],
                   "event_summary": {}, "quality": dict(S.UNKNOWN)}
    pair = {"inner_path": INNER, "inner": {"result": request["root200_binding"]["result"]},
            "outer_wrapper": {}, "wrapper_path": WRAPPER}
    monkeypatch.setattr(S, "validate_request", lambda _path: {})
    monkeypatch.setattr(S, "_load_pair", lambda _inner, _outer: pair)
    monkeypatch.setattr(S, "_validate_result_binding", lambda _request, _pair: (tiny, tiny_sha, tiny.stat().st_size))
    monkeypatch.setattr(S.V8, "_load_object", lambda _path: {})
    monkeypatch.setattr(S.V8, "_validate_request", lambda *_args, **_kwargs: {"max_result_bytes": 1000})
    monkeypatch.setattr(S.V8, "_read_result", lambda *_args, **_kwargs: (tiny_result, tiny_sha, tiny.stat().st_size))
    monkeypatch.setattr(S.V12, "_load_marker", lambda _path: (INNER, {}, {}))
    monkeypatch.setattr(S.V12, "_validate_result_v12", lambda *_args, **_kwargs: {"status": "MANUFACTURED_SEMANTIC_PASS"})
    monkeypatch.setattr(S.EVALUATOR, "_score_typed_result", lambda *_args, **_kwargs: {"status": "MANUFACTURED_OPERATOR_PASS", "model_invoked": False})
    output = tmp_path / "STAGE2_F2_ROOT191_V3_MANUFACTURED" / "report.json"
    report = S.run_trial(request_path, output=output, parent_pid=os.getppid())
    assert report["status"].startswith("PASS_DEVELOPMENT_TYPED_ONLY")
    assert report["typed_only_product"]["result_sha256"] == tiny_sha
    assert report["model_invoked"] is False
    assert json.loads(output.read_text())["sha256"] == S.canonical_sha(report)
