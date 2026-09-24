from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from scripts import f8_r008_d_artifact_producer_v2 as producer
from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as table_chain
from scripts import f8_r008_native_fluid_table_producer_v2 as table_producer
from scripts import f8_r008_native_fluid_table_schema_review_v2 as table_review
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from tests import test_f8_r008_per_case_bundle_verifier_v1 as fixtures


RECEIPT_TIME = "2026-09-24T00:00:30Z"


def _canonical(value: object) -> bytes:
    return fixtures._canonical(value)


def _write_canonical(path: Path, value: dict) -> bytes:
    payload = _canonical(value)
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def _prepare_b_c(tmp_path: Path) -> tuple[dict[str, Path], dict[str, bytes], dict[str, dict]]:
    roots: dict[str, Path] = {}
    auth_bytes: dict[str, bytes] = {}
    auth: dict[str, dict] = {}
    for stage in ("B", "C"):
        roots[stage], auth_bytes[stage], auth[stage] = fixtures._build_bundle(tmp_path, stage)

    b_receipt_path = roots["B"] / "receipt.json"
    b_receipt = json.loads(b_receipt_path.read_text(encoding="utf-8"))
    row = bundle._frozen_qualification_row(fixtures.CASE_ID)
    for field in ("definition", "control"):
        b_receipt[f"{field}_binding"] = {
            key: row[field][key] for key in ("path", "bytes", "sha256")
        }
    _write_canonical(b_receipt_path, b_receipt)

    c_receipt_path = roots["C"] / "receipt.json"
    c_receipt = json.loads(c_receipt_path.read_text(encoding="utf-8"))
    fixtures._update_reference(c_receipt, "materialization_receipt_binding", b_receipt_path)
    _write_canonical(c_receipt_path, c_receipt)
    return roots, auth_bytes, auth


def _prepare_empty_d(tmp_path: Path) -> tuple[Path, bytes, dict]:
    root = tmp_path / "bundle-D"
    root.mkdir(mode=0o700)
    (root / "manifests").mkdir(mode=0o700)
    (root / "outputs").mkdir(mode=0o700)
    auth = {
        "schema": "core.cfd.f8.r008_execution_authorization.v1",
        "authority_id": "authority-d",
        "stage": "D",
        "scope_id": bundle.SCOPE_ID,
        "case_id": fixtures.CASE_ID,
        "attempt_id": "attempt-d",
        "nonce": "nonce-d",
        "exclusive_output_root": str(root),
        "executable_sha256": "1" * 64,
        "wrapper_sha256": "2" * 64,
        "argv": ["/synthetic/python-only-d-producer", "--bounded"],
        "input_bindings": {"fixture": {"sha256": "3" * 64}},
        "invocation_budget": 1,
        "resource_limits": {"cpu_seconds": 10, "memory_bytes": 1048576},
        "issued_at_utc": fixtures.TIMES[0],
        "expires_at_utc": fixtures.TIMES[2],
    }
    auth_path = root / "authorization.json"
    auth_bytes = _write_canonical(auth_path, auth)
    auth_path.chmod(0o600)
    lock = {
        "schema": "core.cfd.f8.r008_one_shot_lock.v1",
        "authority_sha256": hashlib.sha256(auth_bytes).hexdigest(),
        "stage": "D",
        "scope_id": bundle.SCOPE_ID,
        "case_id": fixtures.CASE_ID,
        "attempt_id": "attempt-d",
        "nonce": "nonce-d",
        "exclusive_output_root": str(root),
        "created_at_utc": fixtures.TIMES[0],
        "exclusive_create_succeeded": True,
    }
    lock_path = root / "one-shot-lock.json"
    _write_canonical(lock_path, lock)
    lock_path.chmod(0o600)
    return root, auth_bytes, auth


def _inputs(tmp_path: Path) -> dict:
    roots, auth_bytes, auth = _prepare_b_c(tmp_path)
    roots["D"], auth_bytes["D"], auth["D"] = _prepare_empty_d(tmp_path)
    return {
        "b_bundle_root": roots["B"],
        "c_bundle_root": roots["C"],
        "d_target_root": roots["D"],
        "trusted_authorization_bytes": auth_bytes,
        "trusted_authorization_sha256": {
            stage: hashlib.sha256(payload).hexdigest() for stage, payload in auth_bytes.items()
        },
        "expected_authorization_envelopes": auth,
        "decoder_code_binding": fixtures._trusted_code_bindings(),
        "trusted_code_review_receipt_bytes": fixtures._trusted_code_review_receipt_bytes(),
        "trusted_runtime_assumption": fixtures._trusted_runtime_assumption(),
        "started_at_utc": RECEIPT_TIME,
        "ended_at_utc": RECEIPT_TIME,
    }


def _table_inputs(call: dict) -> dict:
    table_review_bytes = table_review.OUTPUT.read_bytes()
    return {
        "bundle_roots": {
            "B": call["b_bundle_root"], "C": call["c_bundle_root"], "D": call["d_target_root"],
        },
        "trusted_authorization_bytes": call["trusted_authorization_bytes"],
        "trusted_authorization_sha256": call["trusted_authorization_sha256"],
        "expected_authorization_envelopes": call["expected_authorization_envelopes"],
        "trusted_table_review_receipt_bytes": table_review_bytes,
        "trusted_table_review_receipt_sha256": hashlib.sha256(table_review_bytes).hexdigest(),
        "trusted_code_review_receipt_bytes": call["trusted_code_review_receipt_bytes"],
        "trusted_runtime_assumption": call["trusted_runtime_assumption"],
    }


def test_producer_creates_closed_synthetic_d_bundle_and_v2_table(tmp_path: Path) -> None:
    call = _inputs(tmp_path)

    result = producer.produce_d_artifacts_v2(**call)

    assert result["D_candidate_precommit_validated"] is True
    assert result["independent_postpublication_bundle_verification_performed"] is False
    assert result["frame_count"] == 321
    assert result["native_integrity_evaluated"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0

    d_result = bundle.verify_stage_bundle(
        call["d_target_root"], "D",
        trusted_authorization_bytes=call["trusted_authorization_bytes"]["D"],
        trusted_authorization_sha256=call["trusted_authorization_sha256"]["D"],
        expected_authorization_envelope=call["expected_authorization_envelopes"]["D"],
        trusted_code_review_receipt_bytes=call["trusted_code_review_receipt_bytes"],
        trusted_runtime_assumption=call["trusted_runtime_assumption"],
    )
    assert d_result["decoded_frame_count"] == 321
    chain = bundle.verify_provenance_chain(
        {"B": call["b_bundle_root"], "C": call["c_bundle_root"], "D": call["d_target_root"]},
        trusted_authorization_bytes=call["trusted_authorization_bytes"],
        trusted_authorization_sha256=call["trusted_authorization_sha256"],
        expected_authorization_envelopes=call["expected_authorization_envelopes"],
        trusted_code_review_receipt_bytes=call["trusted_code_review_receipt_bytes"],
        trusted_runtime_assumption=call["trusted_runtime_assumption"],
    )
    assert chain["all_stages_passed"] is True
    table_result = table_chain.verify_native_fluid_table_chain(**_table_inputs(call))
    assert table_result["native_fluid_table"]["raw_frames_recomputed"] == 321
    assert table_result["qualification_credit"] == 0


def test_producer_rejects_source_mutation_during_second_table_pass(tmp_path: Path, monkeypatch) -> None:
    call = _inputs(tmp_path)
    original = table_producer.table_v2.read_native_source_frame_fd
    seen = 0

    def mutate_after_first_pass(fd, *args, **kwargs):
        nonlocal seen
        frame = original(fd, *args, **kwargs)
        seen += 1
        if seen == 321:
            raw = call["c_bundle_root"] / "outputs/frames/Part_0000.bi4"
            raw.write_bytes(raw.read_bytes() + b"x")
        return frame

    monkeypatch.setattr(table_producer.table_v2, "read_native_source_frame_fd", mutate_after_first_pass)
    with pytest.raises(Exception, match="size|hash|changed|input"):
        producer.produce_d_artifacts_v2(**call)

    # The new target is terminal/incomplete: materialized decode evidence is
    # retained, but there is no receipt to make it look like a completed D run.
    assert (call["d_target_root"] / "outputs/decode-receipts/frame-0000.json").is_file()
    assert not (call["d_target_root"] / "receipt.json").exists()


def test_producer_refuses_nonempty_caller_prepared_d_target(tmp_path: Path) -> None:
    call = _inputs(tmp_path)
    (call["d_target_root"] / "outputs/unexpected.txt").write_text("not fresh", encoding="utf-8")

    with pytest.raises(producer.DArtifactProducerError, match="outputs directory is not empty"):
        producer.produce_d_artifacts_v2(**call)

    assert not (call["d_target_root"] / "receipt.json").exists()


def test_precommit_failure_does_not_publish_passed_d_receipt(tmp_path: Path, monkeypatch) -> None:
    call = _inputs(tmp_path)

    def reject_candidate(*_args, **_kwargs):
        raise bundle.BundleVerificationError("synthetic precommit rejection")

    monkeypatch.setattr(producer, "_validate_candidate_before_receipt", reject_candidate)
    with pytest.raises(bundle.BundleVerificationError, match="precommit rejection"):
        producer.produce_d_artifacts_v2(**call)

    assert not (call["d_target_root"] / "receipt.json").exists()
    assert (call["d_target_root"] / "manifests/outputs-manifest.json").is_file()


@pytest.mark.parametrize("target", ["root", "manifests", "outputs"])
def test_producer_rejects_group_world_writable_d_directories(tmp_path: Path, target: str) -> None:
    call = _inputs(tmp_path)
    directory = call["d_target_root"] if target == "root" else call["d_target_root"] / target
    directory.chmod(0o777)

    with pytest.raises(producer.DArtifactProducerError, match="not group/world-writable"):
        producer.produce_d_artifacts_v2(**call)

    assert not (call["d_target_root"] / "receipt.json").exists()


@pytest.mark.parametrize("target", ["root", "manifests", "outputs"])
def test_precommit_rechecks_d_directory_permissions(tmp_path: Path, monkeypatch, target: str) -> None:
    call = _inputs(tmp_path)
    original = producer._validate_candidate_before_receipt

    def weaken_then_validate(**kwargs):
        fd = kwargs[{"root": "root_fd", "manifests": "manifests_fd", "outputs": "outputs_fd"}[target]]
        os.fchmod(fd, 0o777)
        return original(**kwargs)

    monkeypatch.setattr(producer, "_validate_candidate_before_receipt", weaken_then_validate)
    with pytest.raises(producer.DArtifactProducerError, match="permissions changed before receipt"):
        producer.produce_d_artifacts_v2(**call)

    assert not (call["d_target_root"] / "receipt.json").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("invocation_budget", "exact v1 prelude contract"),
        ("argv", "exact v1 prelude contract"),
        ("executable_sha256", "executable_sha256 is malformed"),
        ("expiry", "validity interval is empty"),
    ],
)
def test_prelude_rejects_authorization_v1_contract_violations(
    tmp_path: Path, mutation: str, message: str,
) -> None:
    call = _inputs(tmp_path)
    root = call["d_target_root"]
    auth = dict(call["expected_authorization_envelopes"]["D"])
    if mutation == "invocation_budget":
        auth["invocation_budget"] = 2
    elif mutation == "argv":
        auth["argv"] = "not-an-argv-array"
    elif mutation == "executable_sha256":
        auth["executable_sha256"] = "z" * 64
    else:
        auth["expires_at_utc"] = auth["issued_at_utc"]
    auth_bytes = _write_canonical(root / "authorization.json", auth)
    (root / "authorization.json").chmod(0o600)
    call["trusted_authorization_bytes"]["D"] = auth_bytes
    call["trusted_authorization_sha256"]["D"] = hashlib.sha256(auth_bytes).hexdigest()
    call["expected_authorization_envelopes"]["D"] = auth
    lock_path = root / "one-shot-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["authority_sha256"] = call["trusted_authorization_sha256"]["D"]
    _write_canonical(lock_path, lock)
    lock_path.chmod(0o600)

    with pytest.raises(producer.DArtifactProducerError, match=message):
        producer._read_target_prelude(
            root,
            trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=call["trusted_authorization_sha256"]["D"],
            expected_authorization_envelope=auth,
        )

    assert not list((root / "outputs").iterdir())


@pytest.mark.parametrize("name", ["authorization.json", "one-shot-lock.json"])
def test_prelude_rejects_group_writable_authorization_or_lock(tmp_path: Path, name: str) -> None:
    call = _inputs(tmp_path)
    path = call["d_target_root"] / name
    path.chmod(0o660)

    with pytest.raises(producer.DArtifactProducerError, match="not group/world-writable"):
        producer._read_target_prelude(
            call["d_target_root"],
            trusted_authorization_bytes=call["trusted_authorization_bytes"]["D"],
            trusted_authorization_sha256=call["trusted_authorization_sha256"]["D"],
            expected_authorization_envelope=call["expected_authorization_envelopes"]["D"],
        )


def test_precommit_rejects_group_writable_output_file(tmp_path: Path, monkeypatch) -> None:
    call = _inputs(tmp_path)
    original = producer._validate_candidate_before_receipt

    def weaken_then_validate(**kwargs):
        output = call["d_target_root"] / "outputs/decode-receipts/frame-0000.json"
        output.chmod(0o660)
        return original(**kwargs)

    monkeypatch.setattr(producer, "_validate_candidate_before_receipt", weaken_then_validate)
    with pytest.raises(producer.DArtifactProducerError, match="D output file .*not group/world-writable"):
        producer.produce_d_artifacts_v2(**call)

    assert not (call["d_target_root"] / "receipt.json").exists()


def test_table_semantics_are_rechecked_before_passed_receipt_publication(
    tmp_path: Path, monkeypatch,
) -> None:
    call = _inputs(tmp_path)
    original = table_producer.table_v2.verify_native_fluid_table_fd
    calls = 0

    def reject_precommit_semantic_pass(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic precommit table semantic rejection")
        return original(*args, **kwargs)

    monkeypatch.setattr(table_producer.table_v2, "verify_native_fluid_table_fd", reject_precommit_semantic_pass)
    with pytest.raises(RuntimeError, match="precommit table semantic rejection"):
        producer.produce_d_artifacts_v2(**call)

    assert calls == 2
    assert not (call["d_target_root"] / "receipt.json").exists()


@pytest.mark.parametrize("fault", ["directory_fsync", "file_close"])
def test_receipt_publication_reports_postcommit_io_fault_without_raising(
    tmp_path: Path, monkeypatch, fault: str,
) -> None:
    payload = b'{"schema":"synthetic-receipt"}\n'
    root_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    real_fsync = os.fsync
    real_close = os.close
    root_stat = os.fstat(root_fd)
    try:
        if fault == "directory_fsync":
            def fail_postcommit_directory_fsync(fd: int) -> None:
                opened = os.fstat(fd)
                receipt_exists = (tmp_path / "receipt.json").exists()
                if (stat.S_ISDIR(opened.st_mode)
                        and (opened.st_dev, opened.st_ino) == (root_stat.st_dev, root_stat.st_ino)
                        and receipt_exists):
                    raise OSError("synthetic postcommit directory fsync failure")
                real_fsync(fd)

            monkeypatch.setattr(producer.os, "fsync", fail_postcommit_directory_fsync)
        else:
            did_raise = False

            def close_then_report_file_error(fd: int) -> None:
                nonlocal did_raise
                opened = os.fstat(fd)
                if stat.S_ISREG(opened.st_mode) and not did_raise:
                    did_raise = True
                    real_close(fd)
                    raise OSError("synthetic postcommit receipt-file close failure")
                real_close(fd)

            monkeypatch.setattr(producer.os, "close", close_then_report_file_error)

        result = producer._publish_passed_receipt(root_fd, payload)
    finally:
        real_close(root_fd)

    assert (tmp_path / "receipt.json").read_bytes() == payload
    assert [path.name for path in tmp_path.iterdir()] == ["receipt.json"]
    if fault == "directory_fsync":
        assert result["receipt_parent_directory_fsync_succeeded"] is False
    else:
        assert result["receipt_file_close_succeeded"] is False
