from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path

import pytest

from scripts import f8_r008_held_fd_bcd_input_provenance_adapter_v1 as adapter


CASE_ID = "space-q0p5-dp0p0075"
ATTEMPT_ID = "synthetic-attempt-001"
NONCE_HEX = "0123456789abcdef0123456789abcdef"
SOURCE_ID = "synthetic-b-source-001"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_json(value: object) -> str:
    return _sha(_canonical(value))


def _identity() -> dict[str, str]:
    return {
        "scope_id": adapter.SCOPE_ID,
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "nonce_hex": NONCE_HEX,
        "source_id": SOURCE_ID,
    }


def _write_and_hold(root: Path, slot: str, payload: bytes) -> tuple[int, Path]:
    path = root / slot.replace(".", "_")
    path.write_bytes(payload)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags), path


def _artifact(slot: str, role: str, payload: bytes) -> dict[str, object]:
    return {"slot": slot, "role": role, "bytes": len(payload), "sha256": _sha(payload)}


def _build_fixture(tmp_path: Path, frame_count: int = 3) -> dict[str, object]:
    identity = _identity()
    times = [float(index).hex() for index in range(frame_count)]

    source_document = {
        "schema": adapter.SOURCE_DOCUMENT_SCHEMA,
        **identity,
        "input_kind": "synthetic_b_source",
    }
    source_payload = _canonical(source_document)
    source_sha256 = _sha(source_payload)

    raw_payloads: list[bytes] = []
    decoded_payloads: list[bytes] = []
    raw_rows: list[dict[str, object]] = []
    decoded_rows: list[dict[str, object]] = []
    for ordinal, time_hex in enumerate(times):
        raw_document = {
            "schema": adapter.C_FRAME_SCHEMA,
            "stage": "C",
            **identity,
            "ordinal": ordinal,
            "time_ieee754_hex": time_hex,
            "frame_kind": "synthetic_raw_frame",
        }
        raw_payload = _canonical(raw_document)
        raw_sha256 = _sha(raw_payload)
        decoded_document = {
            "schema": adapter.D_FRAME_SCHEMA,
            "stage": "D",
            **identity,
            "ordinal": ordinal,
            "time_ieee754_hex": time_hex,
            "frame_kind": "synthetic_decoded_frame",
            "raw_frame_sha256": raw_sha256,
        }
        decoded_payload = _canonical(decoded_document)
        decoded_sha256 = _sha(decoded_payload)
        raw_payloads.append(raw_payload)
        decoded_payloads.append(decoded_payload)
        raw_rows.append({
            "ordinal": ordinal,
            "time_ieee754_hex": time_hex,
            "raw_frame_sha256": raw_sha256,
        })
        decoded_rows.append({
            "ordinal": ordinal,
            "time_ieee754_hex": time_hex,
            "raw_frame_sha256": raw_sha256,
            "decoded_frame_sha256": decoded_sha256,
        })

    time_axis_sha256 = _sha_json(times)
    raw_frame_manifest_sha256 = _sha_json(raw_rows)
    decoded_frame_manifest_sha256 = _sha_json(decoded_rows)

    def common(schema: str, stage: str) -> dict[str, object]:
        return {
            "schema": schema,
            "stage": stage,
            **identity,
            "source_sha256": source_sha256,
        }

    b_manifest = {
        **common(adapter.B_MANIFEST_SCHEMA, "B"),
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
    }
    b_manifest_payload = _canonical(b_manifest)
    b_receipt = {
        **common(adapter.B_RECEIPT_SCHEMA, "B"),
        "manifest_sha256": _sha(b_manifest_payload),
        "upstream_receipt_sha256": None,
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
    }
    b_receipt_payload = _canonical(b_receipt)

    c_manifest = {
        **common(adapter.C_MANIFEST_SCHEMA, "C"),
        "upstream_receipt_sha256": _sha(b_receipt_payload),
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "frames": raw_rows,
    }
    c_manifest_payload = _canonical(c_manifest)
    c_receipt = {
        **common(adapter.C_RECEIPT_SCHEMA, "C"),
        "manifest_sha256": _sha(c_manifest_payload),
        "upstream_receipt_sha256": _sha(b_receipt_payload),
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
    }
    c_receipt_payload = _canonical(c_receipt)

    d_manifest = {
        **common(adapter.D_MANIFEST_SCHEMA, "D"),
        "upstream_receipt_sha256": _sha(c_receipt_payload),
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
        "frames": decoded_rows,
    }
    d_manifest_payload = _canonical(d_manifest)
    d_receipt = {
        **common(adapter.D_RECEIPT_SCHEMA, "D"),
        "manifest_sha256": _sha(d_manifest_payload),
        "upstream_receipt_sha256": _sha(c_receipt_payload),
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
    }
    d_receipt_payload = _canonical(d_receipt)

    payload_by_slot = {
        "B.source": source_payload,
        "B.receipt": b_receipt_payload,
        "B.manifest": b_manifest_payload,
        "C.receipt": c_receipt_payload,
        "C.manifest": c_manifest_payload,
        "D.receipt": d_receipt_payload,
        "D.manifest": d_manifest_payload,
    }
    for ordinal, (raw_payload, decoded_payload) in enumerate(zip(raw_payloads, decoded_payloads)):
        payload_by_slot[f"C.frame.{ordinal:04d}"] = raw_payload
        payload_by_slot[f"D.frame.{ordinal:04d}"] = decoded_payload

    fds: dict[str, int] = {}
    paths: dict[str, Path] = {}
    try:
        for slot, payload in payload_by_slot.items():
            fds[slot], paths[slot] = _write_and_hold(tmp_path, slot, payload)
    except BaseException:
        for fd in fds.values():
            os.close(fd)
        raise

    descriptor = {
        "schema": adapter.SCHEMA,
        "scope_id": adapter.SCOPE_ID,
        "case_id": CASE_ID,
        "attempt": {"attempt_id": ATTEMPT_ID, "nonce_hex": NONCE_HEX},
        "source": {
            "source_id": SOURCE_ID,
            "fd_slot": "B.source",
            "bytes": len(source_payload),
            "sha256": source_sha256,
        },
        "stages": {},
        "frames": [],
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
        "held_fd_contract": dict(adapter.EXPECTED_HELD_FD_CONTRACT),
    }
    for stage, receipt_payload, manifest_payload in (
        ("B", b_receipt_payload, b_manifest_payload),
        ("C", c_receipt_payload, c_manifest_payload),
        ("D", d_receipt_payload, d_manifest_payload),
    ):
        descriptor["stages"][stage] = {
            "stage": stage,
            "scope_id": adapter.SCOPE_ID,
            "case_id": CASE_ID,
            "attempt_id": ATTEMPT_ID,
            "nonce_hex": NONCE_HEX,
            "source_id": SOURCE_ID,
            "source_sha256": source_sha256,
            "receipt": _artifact(f"{stage}.receipt", f"{stage}_receipt", receipt_payload),
            "manifest": _artifact(f"{stage}.manifest", f"{stage}_manifest", manifest_payload),
            "upstream_receipt_sha256": (
                None if stage == "B" else _sha(b_receipt_payload if stage == "C" else c_receipt_payload)
            ),
            "time_axis_sha256": time_axis_sha256,
            "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
            "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
        }
    for ordinal, time_hex in enumerate(times):
        raw_payload = raw_payloads[ordinal]
        decoded_payload = decoded_payloads[ordinal]
        descriptor["frames"].append({
            "ordinal": ordinal,
            "scope_id": adapter.SCOPE_ID,
            "case_id": CASE_ID,
            "attempt_id": ATTEMPT_ID,
            "nonce_hex": NONCE_HEX,
            "source_id": SOURCE_ID,
            "time_ieee754_hex": time_hex,
            "raw": _artifact(f"C.frame.{ordinal:04d}", "raw_frame", raw_payload),
            "decoded": _artifact(f"D.frame.{ordinal:04d}", "decoded_frame", decoded_payload),
        })
    return {"descriptor": descriptor, "fds": fds, "paths": paths}


def _close_fixture(fixture: dict[str, object]) -> None:
    for fd in fixture["fds"].values():
        os.close(fd)


def test_synthetic_bcd_input_provenance_binds_through_held_fds(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    try:
        result = adapter.verify_held_fd_bcd_input_provenance(
            fixture["descriptor"], held_fds=fixture["fds"],
        )
    finally:
        _close_fixture(fixture)

    assert result["stage_statuses"] == {"B": "bound", "C": "bound", "D": "bound"}
    assert result["held_fd_only"] is True
    assert result["pathname_reopen_attempted"] is False
    assert result["symlink_followed"] is False
    assert result["hardlink_accepted"] is False
    assert result["source_digest_bound"] is True
    assert result["attempt_identity_bound"] is True
    assert result["case_identity_bound"] is True
    assert result["time_axis_bound"] is True
    assert result["raw_frame_digests_bound"] is True
    assert result["decoded_frame_digests_bound"] is True
    assert result["upstream_receipt_digests_bound"] is True
    assert result["frame_count"] == 3
    assert result["artifact_count"] == 13
    assert result["diagnostic_only"] is True
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_adapter_has_no_pathname_reopen_or_core_gate_surface() -> None:
    source = inspect.getsource(adapter)
    tree = ast.parse(source)
    forbidden_os_calls = {"open", "stat", "lstat", "readlink", "scandir"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                assert node.func.attr not in forbidden_os_calls
    assert "solver_output_core_input_gate" not in source
    assert "production_bundle_read\": False" in source


def test_path_claims_are_rejected_before_any_fd_read(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    try:
        descriptor = copy.deepcopy(fixture["descriptor"])
        descriptor["source"]["path"] = "production/bundle"
        with pytest.raises(adapter.HeldFdInputProvenanceError, match="pathname claim"):
            adapter.verify_held_fd_bcd_input_provenance(descriptor, held_fds=fixture["fds"])
    finally:
        _close_fixture(fixture)


@pytest.mark.parametrize("mutation", [
    lambda value: value.__setitem__("case_id", "space-q0p5-dp0p0080"),
    lambda value: value["attempt"].__setitem__("attempt_id", "synthetic-attempt-other"),
    lambda value: value["attempt"].__setitem__("nonce_hex", "f" * 32),
    lambda value: value["source"].__setitem__("sha256", "0" * 64),
    lambda value: value["stages"]["C"].__setitem__("upstream_receipt_sha256", "1" * 64),
    lambda value: value["frames"][1].__setitem__("time_ieee754_hex", "0x1.0p+0"),
    lambda value: value["frames"][1]["raw"].__setitem__("sha256", "2" * 64),
    lambda value: value.__setitem__("time_axis_sha256", "3" * 64),
])
def test_source_attempt_case_time_and_frame_digest_drift_fail_closed(tmp_path: Path, mutation) -> None:
    fixture = _build_fixture(tmp_path)
    try:
        descriptor = copy.deepcopy(fixture["descriptor"])
        mutation(descriptor)
        with pytest.raises(adapter.HeldFdInputProvenanceError):
            adapter.verify_held_fd_bcd_input_provenance(descriptor, held_fds=fixture["fds"])
    finally:
        _close_fixture(fixture)


def test_actual_frame_bytes_drift_fails_against_held_fd_digest(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    try:
        slot = "C.frame.0001"
        fixture["paths"][slot].write_bytes(b"{}" * (fixture["paths"][slot].stat().st_size // 2))
        with pytest.raises(adapter.HeldFdInputProvenanceError, match="bytes differ from its declared digest"):
            adapter.verify_held_fd_bcd_input_provenance(
                fixture["descriptor"], held_fds=fixture["fds"],
            )
    finally:
        _close_fixture(fixture)


def test_hardlink_is_rejected_from_fstat_identity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    alias = tmp_path / "external_alias"
    os.link(fixture["paths"]["D.manifest"], alias)
    try:
        with pytest.raises(adapter.HeldFdInputProvenanceError, match="hard-linked"):
            adapter.verify_held_fd_bcd_input_provenance(
                fixture["descriptor"], held_fds=fixture["fds"],
            )
    finally:
        _close_fixture(fixture)


def test_symlink_fd_is_rejected_as_non_regular_without_following_it(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    link = tmp_path / "symlink-input"
    link.symlink_to(fixture["paths"]["B.source"])
    o_path = getattr(os, "O_PATH", None)
    if o_path is None:
        _close_fixture(fixture)
        pytest.skip("O_PATH is unavailable on this platform")
    symlink_fd = os.open(link, o_path | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    original_fd = fixture["fds"]["B.source"]
    fixture["fds"]["B.source"] = symlink_fd
    try:
        with pytest.raises(adapter.HeldFdInputProvenanceError, match="not a regular file"):
            adapter.verify_held_fd_bcd_input_provenance(
                fixture["descriptor"], held_fds=fixture["fds"],
            )
    finally:
        os.close(original_fd)
        _close_fixture(fixture)


def test_report_is_deterministic_and_non_authorizing() -> None:
    report = adapter.build_report()
    assert report["schema"] == adapter.REPORT_SCHEMA
    assert report["record_id"] == adapter.REPORT_RECORD_ID
    assert report["non_authorizing_boundary"]["pathname_reopen"] is False
    assert report["non_authorizing_boundary"]["production_hdf5_or_bi4_read"] is False
    assert report["non_authorizing_boundary"]["diagnostic_only"] is True
    assert report["non_authorizing_boundary"]["qualification_credit"] == 0


def test_checked_report_and_campaign_contract_match_this_adapter() -> None:
    lab = Path(adapter.__file__).resolve().parents[1]
    report_path = lab / "reports/F8-R008-HELD-FD-BCD-INPUT-PROVENANCE-ADAPTER-V1.json"
    campaign_path = lab / (
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
        "held-fd-input-provenance-v1/contract.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == adapter.build_report()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    assert campaign["schema"] == (
        "core.cfd.f8.r008_held_fd_bcd_input_provenance_adapter_contract.v1"
    )
    assert campaign["scope_id"] == adapter.SCOPE_ID
    assert campaign["boundary"]["pathname_reopen"] is False
    assert campaign["boundary"]["qualification_credit"] == 0
