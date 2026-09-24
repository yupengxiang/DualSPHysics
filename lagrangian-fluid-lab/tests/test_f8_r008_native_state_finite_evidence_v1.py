from __future__ import annotations

import hashlib
import json
import os
import struct

import pytest

from scripts import f8_r008_native_state_finite_evidence_v1 as evidence
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from tests import test_f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_fixtures
from tests import test_f8_r008_per_case_bundle_verifier_v1 as bundle_fixtures


def _inject_nonfluid_nonfinites(payload: bytes, tmp_path) -> bytes:
    source = tmp_path / "raw-frame-for-array-offsets.bi4"
    source.write_bytes(payload)
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        scan = decoder.scan_bi4_fd(fd, hashlib.sha256(payload).hexdigest())
        arrays = {item.name: item for item in scan.arrays}
    finally:
        os.close(fd)
    changed = bytearray(payload)
    # Particle ID 1 is the fixed/non-fluid member of the frozen synthetic pair.
    struct.pack_into("<d", changed, arrays["Posd"].offset + (3 + 1) * 8, float("nan"))
    struct.pack_into("<f", changed, arrays["Vel"].offset + (3 + 1) * 4, float("inf"))
    struct.pack_into("<f", changed, arrays["Rhop"].offset + 4, float("-inf"))
    return bytes(changed)


def _synthetic_bundle_with_nonfluid_nonfinites(tmp_path, monkeypatch):
    original = bundle_fixtures._synthetic_bi4
    call_count = 0

    def synthetic_with_nonfinites(time_s, particle_ids=(0, 1), case_counts=None):
        nonlocal call_count
        payload = original(time_s, particle_ids, case_counts)
        # _build_chain creates B first, then all C frames and all D decode inputs.
        call_count += 1
        if call_count == 1:
            return payload
        return _inject_nonfluid_nonfinites(payload, tmp_path)

    monkeypatch.setattr(bundle_fixtures, "_synthetic_bi4", synthetic_with_nonfinites)
    roots, auth_bytes, auth, _frames = bundle_fixtures._build_chain(tmp_path)
    metric_fixtures.table_fixtures._freeze_b_source_bindings(roots)
    metric_fixtures.table_fixtures._materialize_synthetic_v2_table(roots)
    return roots, auth_bytes, auth


def test_publishes_full_axis_evidence_for_nonfluid_nonfinites(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth = _synthetic_bundle_with_nonfluid_nonfinites(tmp_path, monkeypatch)
    inputs = {
        key: value for key, value in metric_fixtures._inputs(roots, auth_bytes, auth).items()
        if not key.startswith("trusted_metric_review_receipt_")
    }
    output_directory = tmp_path / "finite-evidence"
    output_directory.mkdir(mode=0o700)

    result = evidence.collect_and_publish_native_state_finite_evidence(
        **inputs,
        evidence_directory=output_directory,
    )

    record = result["evidence"]
    publication = result["publication"]
    assert record["schema"] == evidence.SCHEMA
    assert record["status"] == evidence.STATUS
    assert record["native_state_finite_status"] == "observed_nonfinite"
    assert record["native_integrity_gate_status"] == "open_not_adjudicated"
    assert record["native_integrity_evaluated"] is False
    assert record["T1_numerical"] is False
    assert record["readiness_pass"] is False
    assert record["qualification_credit"] == 0
    assert record["table_semantics_status"] == "passed"
    assert record["stage_statuses"] == {stage: "passed" for stage in ("B", "C", "D")}
    assert record["qualification_scope"]["qualification_row_count"] == 15
    assert record["qualification_scope"]["qualification_only"] is True
    assert record["qualification_scope"]["full_frame_count"] == len(record["frames"])
    assert len(record["frames"]) == len(bundle.expected_time_axis_hex(
        bundle._frozen_qualification_row(record["case_id"]),
    ))

    first = record["frames"][0]
    state = {item["array_name"]: item for item in first["native_arrays"]}
    assert state["Posd"]["nan_count"] == 1
    assert state["Vel"]["positive_infinity_count"] == 1
    assert state["Rhop"]["negative_infinity_count"] == 1
    assert all(item["required_state_values_finite"] is False for item in state.values())
    assert first["observation_window_member"] is False
    assert record["frames"][record["qualification_scope"]["observation_window_start_ordinal"]][
        "observation_window_member"
    ] is True

    output_path = output_directory / publication["path"]
    payload = output_path.read_bytes()
    assert json.loads(payload) == record
    assert bundle._canonical_json(record) == payload
    assert hashlib.sha256(payload).hexdigest() == publication["sha256"]
    assert publication["published"] is True
    assert publication["post_publish_validation_ok"] is True
    assert publication["evidence_directory_path_still_bound"] is True
    output_stat = output_path.stat(follow_symlinks=False)
    assert output_stat.st_nlink == 1
    assert output_stat.st_mode & 0o777 == 0o600


def test_refuses_to_overwrite_existing_case_evidence(tmp_path) -> None:
    output_directory = tmp_path / "finite-evidence"
    output_directory.mkdir(mode=0o700)
    directory_fd = os.open(
        output_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        first = evidence._publish_no_replace(directory_fd, "space-q0-dp0p0090", b"first\n")
        before = (output_directory / first["path"]).read_bytes()
        try:
            evidence._publish_no_replace(directory_fd, "space-q0-dp0p0090", b"second\n")
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing evidence path was overwritten")
        assert (output_directory / first["path"]).read_bytes() == before
    finally:
        os.close(directory_fd)


def test_reports_post_commit_validation_failure_without_claiming_integrity(
    tmp_path, monkeypatch,
) -> None:
    output_directory = tmp_path / "finite-evidence"
    output_directory.mkdir(mode=0o700)
    directory_fd = os.open(
        output_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    original_link = evidence._link_unnamed_noreplace

    def corrupt_after_link(dir_fd: int, source_fd: int, destination: str) -> None:
        original_link(dir_fd, source_fd, destination)
        os.pwrite(source_fd, b"X", 0)

    monkeypatch.setattr(evidence, "_link_unnamed_noreplace", corrupt_after_link)
    try:
        result = evidence._publish_no_replace(
            directory_fd, "space-q0-dp0p0090", b"canonical evidence\n",
        )
    finally:
        os.close(directory_fd)

    assert result["published"] is True
    assert result["post_publish_validation_ok"] is False
    assert result["post_publish_validation_error"] == "NativeStateFiniteEvidenceError"
    assert result["directory_fsync_after_publish_ok"] is True


def test_evidence_directory_path_rebinding_is_detected(tmp_path) -> None:
    output_directory = tmp_path / "finite-evidence"
    output_directory.mkdir(mode=0o700)
    directory_fd = os.open(
        output_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    st = os.fstat(directory_fd)
    identity = (st.st_dev, st.st_ino)
    try:
        assert evidence._evidence_directory_path_matches(
            str(output_directory), identity, require_private=True,
        )
        moved_directory = tmp_path / "held-evidence-directory"
        output_directory.rename(moved_directory)
        output_directory.mkdir(mode=0o700)
        assert not evidence._evidence_directory_path_matches(
            str(output_directory), identity, require_private=True,
        )
    finally:
        os.close(directory_fd)


def test_rejects_d_safe_decode_array_manifest_mismatch_without_publish(
    tmp_path, monkeypatch,
) -> None:
    roots, auth_bytes, auth = _synthetic_bundle_with_nonfluid_nonfinites(tmp_path, monkeypatch)
    inputs = {
        key: value for key, value in metric_fixtures._inputs(roots, auth_bytes, auth).items()
        if not key.startswith("trusted_metric_review_receipt_")
    }
    output_directory = tmp_path / "finite-evidence"
    output_directory.mkdir(mode=0o700)
    original_chain = evidence.table_chain.verify_native_fluid_table_chain
    original_safe_check = bundle._verify_safe_decode_against_scan
    allow_mismatch = False

    def enable_after_first_chain(*args, **kwargs):
        nonlocal allow_mismatch
        result = original_chain(*args, **kwargs)
        allow_mismatch = True
        return result

    def reject_mismatch(raw_fd, scan, safe_receipt, frame, *args, **kwargs):
        if allow_mismatch:
            corrupted = dict(safe_receipt)
            corrupted_arrays = [dict(item) for item in safe_receipt["arrays"]]
            corrupted_arrays[0]["sha256"] = "0" * 64
            corrupted["arrays"] = corrupted_arrays
            return original_safe_check(
                raw_fd, scan, corrupted, frame, *args, **kwargs,
            )
        return original_safe_check(raw_fd, scan, safe_receipt, frame, *args, **kwargs)

    monkeypatch.setattr(evidence.table_chain, "verify_native_fluid_table_chain", enable_after_first_chain)
    monkeypatch.setattr(bundle, "_verify_safe_decode_against_scan", reject_mismatch)
    with pytest.raises(evidence.NativeStateFiniteEvidenceError):
        evidence.collect_and_publish_native_state_finite_evidence(
            **inputs, evidence_directory=output_directory,
        )
    assert list(output_directory.iterdir()) == []


def test_rejects_raw_frame_truncation_during_collection_without_publish(
    tmp_path, monkeypatch,
) -> None:
    roots, auth_bytes, auth = _synthetic_bundle_with_nonfluid_nonfinites(tmp_path, monkeypatch)
    inputs = {
        key: value for key, value in metric_fixtures._inputs(roots, auth_bytes, auth).items()
        if not key.startswith("trusted_metric_review_receipt_")
    }
    output_directory = tmp_path / "finite-evidence"
    output_directory.mkdir(mode=0o700)
    original_summarize = evidence.state_scan.summarize_native_state_fd

    def truncate_held_frame(raw_fd, expected_sha256, scan, *, case_np):
        writable_fd = os.open(f"/proc/self/fd/{raw_fd}", os.O_WRONLY)
        try:
            os.ftruncate(writable_fd, scan.input_bytes - 1)
        finally:
            os.close(writable_fd)
        return original_summarize(
            raw_fd, expected_sha256, scan, case_np=case_np,
        )

    monkeypatch.setattr(evidence.state_scan, "summarize_native_state_fd", truncate_held_frame)
    with pytest.raises(evidence.NativeStateFiniteEvidenceError):
        evidence.collect_and_publish_native_state_finite_evidence(
            **inputs, evidence_directory=output_directory,
        )
    assert list(output_directory.iterdir()) == []
