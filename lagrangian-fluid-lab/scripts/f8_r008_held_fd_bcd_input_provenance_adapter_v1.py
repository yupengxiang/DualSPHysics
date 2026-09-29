"""Synthetic-only held-FD provenance binding for the F8/R008 B/C/D input layer.

This adapter is intentionally below the solver-output -> Core-input boundary.
It does not create a Core trajectory plan and it never imports or calls that
gate.  The caller supplies a canonical, pathless descriptor plus already held
file descriptors for synthetic B/C/D receipts, manifests, and frame records.
The adapter reads only through those descriptors with ``fstat``/``pread``;
there is no pathname reopen, directory walk, symlink resolution, or file
creation here.

The result is a diagnostic provenance snapshot.  It is not producer,
authority, runtime, native-integrity, terminal, T1, readiness, or
qualification evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from typing import Any, Mapping


SCHEMA = "core.cfd.f8.r008_held_fd_bcd_input_provenance_adapter.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_held_fd_bcd_input_provenance_report.v1"
RECORD_ID = "f8-r008-held-fd-bcd-input-provenance-adapter-v1"
REPORT_RECORD_ID = "f8-r008-held-fd-bcd-input-provenance-report-v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
STAGES = ("B", "C", "D")
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FRAMES = 1497
READ_CHUNK_BYTES = 1024 * 1024

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
NONCE_RE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z", re.ASCII)
SLOT_RE = re.compile(r"[BCD]\.[a-z][a-z0-9_-]*(?:\.[0-9]{4})?\Z", re.ASCII)

TOP_LEVEL_FIELDS = frozenset({
    "schema", "scope_id", "case_id", "attempt", "source", "stages", "frames",
    "time_axis_sha256", "raw_frame_manifest_sha256", "decoded_frame_manifest_sha256",
    "held_fd_contract",
})
ATTEMPT_FIELDS = frozenset({"attempt_id", "nonce_hex"})
SOURCE_FIELDS = frozenset({"source_id", "fd_slot", "bytes", "sha256"})
STAGE_FIELDS = frozenset({
    "stage", "scope_id", "case_id", "attempt_id", "nonce_hex", "source_id", "source_sha256",
    "receipt", "manifest",
    "upstream_receipt_sha256", "time_axis_sha256", "raw_frame_manifest_sha256",
    "decoded_frame_manifest_sha256",
})
FRAME_FIELDS = frozenset({
    "ordinal", "scope_id", "case_id", "attempt_id", "nonce_hex", "source_id", "time_ieee754_hex",
    "raw", "decoded",
})
ARTIFACT_FIELDS = frozenset({"slot", "role", "bytes", "sha256"})
HELD_FD_CONTRACT_FIELDS = frozenset({
    "mode", "pathname_reopen", "opened_with_o_nofollow", "symlink_follow", "hardlink_allowed",
})

SOURCE_DOCUMENT_SCHEMA = "core.cfd.f8.r008.synthetic_b_source.v1"
B_RECEIPT_SCHEMA = "core.cfd.f8.r008.synthetic_b_receipt.v1"
B_MANIFEST_SCHEMA = "core.cfd.f8.r008.synthetic_b_manifest.v1"
C_RECEIPT_SCHEMA = "core.cfd.f8.r008.synthetic_c_receipt.v1"
C_MANIFEST_SCHEMA = "core.cfd.f8.r008.synthetic_c_manifest.v1"
D_RECEIPT_SCHEMA = "core.cfd.f8.r008.synthetic_d_receipt.v1"
D_MANIFEST_SCHEMA = "core.cfd.f8.r008.synthetic_d_manifest.v1"
C_FRAME_SCHEMA = "core.cfd.f8.r008.synthetic_c_raw_frame.v1"
D_FRAME_SCHEMA = "core.cfd.f8.r008.synthetic_d_decoded_frame.v1"

EXPECTED_HELD_FD_CONTRACT = {
    "mode": "held_fd_only",
    "pathname_reopen": False,
    "opened_with_o_nofollow": True,
    "symlink_follow": False,
    "hardlink_allowed": False,
}


class HeldFdInputProvenanceError(ValueError):
    """The pathless B/C/D held-FD input provenance contract is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HeldFdInputProvenanceError(message)


def _canonical(value: Any, label: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise HeldFdInputProvenanceError(f"{label} is not canonical JSON") from error


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HeldFdInputProvenanceError(f"duplicate JSON key in held-FD artifact: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise HeldFdInputProvenanceError(f"non-finite JSON constant is forbidden: {value}")


def _parse_canonical_document(payload: bytes, label: str) -> dict[str, Any]:
    _require(type(payload) is bytes and 0 < len(payload) <= MAX_ARTIFACT_BYTES,
             f"{label} is outside the bounded artifact size")
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HeldFdInputProvenanceError(f"{label} is not strict UTF-8 JSON") from error
    _require(type(value) is dict, f"{label} must be a JSON object")
    _require(_canonical(value, label) == payload,
             f"{label} is not in the exact canonical JSON encoding")
    return value


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_json(value: Any, label: str) -> str:
    return _sha256(_canonical(value, label))


def _identifier(value: Any, label: str) -> None:
    _require(type(value) is str and len(value.encode("utf-8")) <= 128
             and bool(IDENTIFIER_RE.fullmatch(value)),
             f"{label} is not a bounded lowercase identifier")


def _sha(value: Any, label: str) -> None:
    _require(type(value) is str and bool(SHA256_RE.fullmatch(value)),
             f"{label} is not a lowercase SHA-256")


def _nonce(value: Any, label: str) -> None:
    _require(type(value) is str and bool(NONCE_RE.fullmatch(value)),
             f"{label} is not a lowercase 128-bit nonce")


def _slot(value: Any, label: str) -> None:
    _require(type(value) is str and bool(SLOT_RE.fullmatch(value))
             and "/" not in value and "\\" not in value,
             f"{label} is not a pathless held-FD slot")


def _time_hex(value: Any, label: str) -> float:
    _require(type(value) is str and 0 < len(value) <= 32,
             f"{label} is not a bounded binary64 hexadecimal value")
    try:
        parsed = float.fromhex(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise HeldFdInputProvenanceError(f"{label} is not binary64 hexadecimal") from error
    _require(math.isfinite(parsed) and parsed.hex() == value,
             f"{label} is non-finite or non-canonical")
    return parsed


def _reject_path_claims(value: Any, label: str = "descriptor") -> None:
    """Reject path-shaped claims before any exact-field validation.

    Logical FD slots are deliberately dot-separated identifiers, not paths.
    Keeping path keys out of the contract makes accidental pathname reopening
    impossible for this adapter's API.
    """
    forbidden = {
        "path", "pathname", "relative_path", "absolute_path", "bundle_root", "root_path",
        "file_path", "directory_path", "symlink", "hardlink", "fd_path",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            _require(key not in forbidden, f"{label} contains a forbidden pathname claim: {key}")
            _reject_path_claims(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_path_claims(item, f"{label}[{index}]")


def _fd_identity(st: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        st.st_dev, st.st_ino, st.st_mode, st.st_size,
        st.st_mtime_ns, st.st_ctime_ns, st.st_nlink,
    )


def _read_held_fd(fd: Any, expected_bytes: int, label: str) -> tuple[bytes, str, tuple[int, ...]]:
    """Read a caller-held descriptor without any pathname operation."""
    _require(type(fd) is int and not isinstance(fd, bool) and fd >= 0,
             f"{label} must be a nonnegative held file descriptor")
    _require(type(expected_bytes) is int and not isinstance(expected_bytes, bool)
             and 0 < expected_bytes <= MAX_ARTIFACT_BYTES,
             f"{label} declared bytes are outside the bounded artifact size")
    try:
        before = os.fstat(fd)
    except OSError as error:
        raise HeldFdInputProvenanceError(f"{label} held FD cannot be inspected") from error
    _require(stat.S_ISREG(before.st_mode), f"{label} held FD is not a regular file")
    _require(before.st_nlink == 1, f"{label} held FD is a hard-linked file")
    _require(before.st_size == expected_bytes, f"{label} held FD size differs from its descriptor")

    digest = hashlib.sha256()
    payload = bytearray()
    offset = 0
    try:
        while offset < expected_bytes:
            block = os.pread(fd, min(READ_CHUNK_BYTES, expected_bytes - offset), offset)
            _require(bool(block), f"{label} held FD was truncated while reading")
            payload.extend(block)
            digest.update(block)
            offset += len(block)
        _require(os.pread(fd, 1, expected_bytes) == b"",
                 f"{label} held FD grew while reading")
        after = os.fstat(fd)
    except OSError as error:
        raise HeldFdInputProvenanceError(f"{label} held FD is not readable by pread") from error
    _require(_fd_identity(before) == _fd_identity(after),
             f"{label} held FD identity changed while reading")
    _require(after.st_nlink == 1, f"{label} held FD became hard-linked while reading")
    return bytes(payload), digest.hexdigest(), _fd_identity(after)


def _artifact(value: Any, *, stage: str, role: str, slot: str, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == ARTIFACT_FIELDS,
             f"{label} fields are not exact")
    _require(value["slot"] == slot, f"{label} slot is not the fixed held-FD slot {slot}")
    _slot(value["slot"], f"{label}.slot")
    _require(value["role"] == role, f"{label} role is not {role}")
    _require(type(value["bytes"]) is int and not isinstance(value["bytes"], bool)
             and 0 < value["bytes"] <= MAX_ARTIFACT_BYTES,
             f"{label}.bytes is outside the artifact bound")
    _sha(value["sha256"], f"{label}.sha256")
    _require(value["slot"].startswith(f"{stage}."), f"{label} crosses its stage slot namespace")
    return dict(value)


def _identity_fields(value: Mapping[str, Any], *, case_id: str, attempt: Mapping[str, Any],
                     source_id: str, label: str) -> None:
    _require(value.get("scope_id") == SCOPE_ID, f"{label} scope differs from F8/R008")
    _require(value.get("case_id") == case_id, f"{label} case identity drifted")
    _require(value.get("attempt_id") == attempt["attempt_id"],
             f"{label} attempt identity drifted")
    _require(value.get("nonce_hex") == attempt["nonce_hex"], f"{label} nonce drifted")
    _require(value.get("source_id") == source_id, f"{label} source identity drifted")


def _validate_document_identity(document: Mapping[str, Any], *, case_id: str,
                                attempt: Mapping[str, Any], source_id: str, label: str) -> None:
    _identity_fields(document, case_id=case_id, attempt=attempt, source_id=source_id, label=label)


def _validate_frame_rows(rows: Any, *, decoded: bool, label: str) -> list[dict[str, Any]]:
    _require(type(rows) is list and 2 <= len(rows) <= MAX_FRAMES,
             f"{label} must contain a bounded complete synthetic frame list")
    result: list[dict[str, Any]] = []
    previous_time: float | None = None
    expected_fields = (
        {"ordinal", "time_ieee754_hex", "raw_frame_sha256", "decoded_frame_sha256"}
        if decoded else {"ordinal", "time_ieee754_hex", "raw_frame_sha256"}
    )
    for ordinal, row in enumerate(rows):
        _require(type(row) is dict and set(row) == expected_fields,
                 f"{label}[{ordinal}] fields are not exact")
        _require(type(row["ordinal"]) is int and not isinstance(row["ordinal"], bool)
                 and row["ordinal"] == ordinal,
                 f"{label} ordinals are not a contiguous zero-based sequence")
        current_time = _time_hex(row["time_ieee754_hex"], f"{label}[{ordinal}].time_ieee754_hex")
        _require(previous_time is None or current_time > previous_time,
                 f"{label} times are not strictly increasing")
        previous_time = current_time
        _sha(row["raw_frame_sha256"], f"{label}[{ordinal}].raw_frame_sha256")
        if decoded:
            _sha(row["decoded_frame_sha256"], f"{label}[{ordinal}].decoded_frame_sha256")
        result.append(dict(row))
    return result


def _validate_descriptor(descriptor: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    _require(type(descriptor) is dict, "held-FD provenance descriptor must be a builtin dict")
    _reject_path_claims(descriptor)
    _require(set(descriptor) == TOP_LEVEL_FIELDS,
             "held-FD provenance descriptor fields are not exact")
    _require(descriptor["schema"] == SCHEMA, "held-FD provenance descriptor schema is unsupported")
    _require(descriptor["scope_id"] == SCOPE_ID, "held-FD provenance descriptor scope is unsupported")
    _identifier(descriptor["case_id"], "case_id")

    attempt = descriptor["attempt"]
    _require(type(attempt) is dict and set(attempt) == ATTEMPT_FIELDS,
             "attempt fields are not exact")
    _identifier(attempt["attempt_id"], "attempt.attempt_id")
    _nonce(attempt["nonce_hex"], "attempt.nonce_hex")

    source = descriptor["source"]
    _require(type(source) is dict and set(source) == SOURCE_FIELDS,
             "source fields are not exact")
    _identifier(source["source_id"], "source.source_id")
    _require(source["fd_slot"] == "B.source", "source must use the fixed B.source held-FD slot")
    _slot(source["fd_slot"], "source.fd_slot")
    _require(type(source["bytes"]) is int and not isinstance(source["bytes"], bool)
             and 0 < source["bytes"] <= MAX_ARTIFACT_BYTES,
             "source.bytes is outside the artifact bound")
    _sha(source["sha256"], "source.sha256")

    contract = descriptor["held_fd_contract"]
    _require(type(contract) is dict and set(contract) == HELD_FD_CONTRACT_FIELDS
             and contract == EXPECTED_HELD_FD_CONTRACT,
             "held-FD contract does not reject pathname reopen/symlink/hardlink access")

    stages = descriptor["stages"]
    _require(type(stages) is dict and set(stages) == set(STAGES),
             "stages must contain exactly B, C, and D")
    checked_stages: dict[str, Any] = {}
    for stage in STAGES:
        value = stages[stage]
        _require(type(value) is dict and set(value) == STAGE_FIELDS,
                 f"{stage} stage fields are not exact")
        _require(value["stage"] == stage, f"{stage} stage marker is inconsistent")
        _validate_document_identity(value, case_id=descriptor["case_id"], attempt=attempt,
                                    source_id=source["source_id"], label=f"{stage} descriptor")
        _artifact(value["receipt"], stage=stage, role=f"{stage}_receipt",
                  slot=f"{stage}.receipt", label=f"{stage}.receipt")
        _artifact(value["manifest"], stage=stage, role=f"{stage}_manifest",
                  slot=f"{stage}.manifest", label=f"{stage}.manifest")
        upstream = value["upstream_receipt_sha256"]
        if stage == "B":
            _require(upstream is None, "B stage must not claim an upstream receipt")
        else:
            _sha(upstream, f"{stage}.upstream_receipt_sha256")
        _sha(value["time_axis_sha256"], f"{stage}.time_axis_sha256")
        _sha(value["raw_frame_manifest_sha256"], f"{stage}.raw_frame_manifest_sha256")
        _sha(value["decoded_frame_manifest_sha256"], f"{stage}.decoded_frame_manifest_sha256")
        checked_stages[stage] = dict(value)

    frames = descriptor["frames"]
    _require(type(frames) is list and 2 <= len(frames) <= MAX_FRAMES,
             "descriptor frames are outside the bounded synthetic domain")
    checked_frames: list[dict[str, Any]] = []
    previous_time: float | None = None
    slots: set[str] = {"B.source"}
    for ordinal, value in enumerate(frames):
        _require(type(value) is dict and set(value) == FRAME_FIELDS,
                 f"frames[{ordinal}] fields are not exact")
        _require(value["ordinal"] == ordinal and type(value["ordinal"]) is int
                 and not isinstance(value["ordinal"], bool),
                 "frame ordinals are not a contiguous zero-based sequence")
        _validate_document_identity(value, case_id=descriptor["case_id"], attempt=attempt,
                                    source_id=source["source_id"], label=f"frames[{ordinal}]")
        current_time = _time_hex(value["time_ieee754_hex"], f"frames[{ordinal}].time_ieee754_hex")
        _require(previous_time is None or current_time > previous_time,
                 "descriptor frame times are not strictly increasing")
        previous_time = current_time
        raw = _artifact(value["raw"], stage="C", role="raw_frame",
                        slot=f"C.frame.{ordinal:04d}", label=f"frames[{ordinal}].raw")
        decoded = _artifact(value["decoded"], stage="D", role="decoded_frame",
                            slot=f"D.frame.{ordinal:04d}", label=f"frames[{ordinal}].decoded")
        for artifact in (raw, decoded):
            _require(artifact["slot"] not in slots, "held-FD slots are reused across artifacts")
            slots.add(artifact["slot"])
        checked_frames.append({**dict(value), "raw": raw, "decoded": decoded})

    times = [row["time_ieee754_hex"] for row in checked_frames]
    _require(descriptor["time_axis_sha256"] == _sha256_json(times, "descriptor time axis"),
             "descriptor time-axis digest does not cover the exact ordered times")
    _sha(descriptor["time_axis_sha256"], "time_axis_sha256")
    raw_rows = [
        {"ordinal": row["ordinal"], "time_ieee754_hex": row["time_ieee754_hex"],
         "raw_frame_sha256": row["raw"]["sha256"]}
        for row in checked_frames
    ]
    decoded_rows = [
        {"ordinal": row["ordinal"], "time_ieee754_hex": row["time_ieee754_hex"],
         "raw_frame_sha256": row["raw"]["sha256"],
         "decoded_frame_sha256": row["decoded"]["sha256"]}
        for row in checked_frames
    ]
    _require(descriptor["raw_frame_manifest_sha256"] == _sha256_json(raw_rows, "raw frame manifest"),
             "descriptor raw frame manifest digest drifted")
    _require(descriptor["decoded_frame_manifest_sha256"] == _sha256_json(decoded_rows, "decoded frame manifest"),
             "descriptor decoded frame manifest digest drifted")
    _sha(descriptor["raw_frame_manifest_sha256"], "raw_frame_manifest_sha256")
    _sha(descriptor["decoded_frame_manifest_sha256"], "decoded_frame_manifest_sha256")
    return dict(descriptor), dict(source), checked_stages, checked_frames


def _document_common_fields(*, schema: str, stage: str, case_id: str,
                            attempt: Mapping[str, Any], source_id: str,
                            source_sha256: str) -> dict[str, Any]:
    return {
        "schema": schema,
        "stage": stage,
        "scope_id": SCOPE_ID,
        "case_id": case_id,
        "attempt_id": attempt["attempt_id"],
        "nonce_hex": attempt["nonce_hex"],
        "source_id": source_id,
        "source_sha256": source_sha256,
    }


def _check_artifact_bytes(
    artifact: Mapping[str, Any], held_fds: Mapping[str, int], *, label: str,
    seen_identities: dict[tuple[int, ...], str], total: list[int],
) -> tuple[bytes, str]:
    slot = artifact["slot"]
    _require(slot in held_fds, f"{label} has no supplied held FD for slot {slot}")
    payload, actual_sha256, identity = _read_held_fd(held_fds[slot], artifact["bytes"], label)
    _require(actual_sha256 == artifact["sha256"], f"{label} bytes differ from its declared digest")
    previous = seen_identities.get(identity)
    _require(previous is None, f"held FD identity is aliased between {previous} and {label}")
    seen_identities[identity] = label
    total[0] += len(payload)
    _require(total[0] <= MAX_TOTAL_BYTES, "held-FD input bytes exceed the aggregate bound")
    return payload, actual_sha256


def _check_common_document(document: Mapping[str, Any], *, expected_schema: str, stage: str,
                           case_id: str, attempt: Mapping[str, Any], source_id: str,
                           source_sha256: str, label: str) -> None:
    _require(document.get("schema") == expected_schema, f"{label} schema is unsupported")
    _require(document.get("stage") == stage, f"{label} stage marker drifted")
    _validate_document_identity(document, case_id=case_id, attempt=attempt,
                                source_id=source_id, label=label)
    _require(document.get("source_sha256") == source_sha256,
             f"{label} source digest drifted")


def _check_source_document(document: Mapping[str, Any], *, case_id: str,
                           attempt: Mapping[str, Any], source_id: str) -> None:
    expected = {"schema", "scope_id", "case_id", "attempt_id", "nonce_hex", "source_id", "input_kind"}
    _require(set(document) == expected, "B source document fields are not exact")
    _require(document["schema"] == SOURCE_DOCUMENT_SCHEMA and document["input_kind"] == "synthetic_b_source",
             "B source document schema/kind is unsupported")
    _identity_fields(document, case_id=case_id, attempt=attempt, source_id=source_id,
                     label="B source document")


def _check_frame_document(document: Mapping[str, Any], *, stage: str, ordinal: int,
                          time_hex: str, case_id: str, attempt: Mapping[str, Any],
                          source_id: str, raw_sha256: str | None = None) -> None:
    if stage == "C":
        expected = {"schema", "stage", "scope_id", "case_id", "attempt_id", "nonce_hex",
                    "source_id", "ordinal", "time_ieee754_hex", "frame_kind"}
        schema = C_FRAME_SCHEMA
        kind = "synthetic_raw_frame"
    else:
        expected = {"schema", "stage", "scope_id", "case_id", "attempt_id", "nonce_hex",
                    "source_id", "ordinal", "time_ieee754_hex", "frame_kind",
                    "raw_frame_sha256"}
        schema = D_FRAME_SCHEMA
        kind = "synthetic_decoded_frame"
    _require(set(document) == expected, f"{stage} frame document fields are not exact")
    _require(document["schema"] == schema and document["frame_kind"] == kind,
             f"{stage} frame document schema/kind is unsupported")
    _identity_fields(document, case_id=case_id, attempt=attempt, source_id=source_id,
                     label=f"{stage} frame {ordinal}")
    _require(document["ordinal"] == ordinal and document["time_ieee754_hex"] == time_hex,
             f"{stage} frame {ordinal} ordinal/time drifted")
    if stage == "D":
        _require(document["raw_frame_sha256"] == raw_sha256,
                 f"D frame {ordinal} raw source digest drifted")


def _check_stage_documents(
    *, stage: str, receipt: Mapping[str, Any], manifest: Mapping[str, Any],
    receipt_sha256: str, manifest_sha256: str, source_sha256: str,
    case_id: str, attempt: Mapping[str, Any], source_id: str,
    upstream_receipt_sha256: str | None, time_axis_sha256: str,
    raw_frame_manifest_sha256: str, decoded_frame_manifest_sha256: str,
    frames: list[dict[str, Any]],
) -> None:
    receipt_schema = {"B": B_RECEIPT_SCHEMA, "C": C_RECEIPT_SCHEMA, "D": D_RECEIPT_SCHEMA}[stage]
    manifest_schema = {"B": B_MANIFEST_SCHEMA, "C": C_MANIFEST_SCHEMA, "D": D_MANIFEST_SCHEMA}[stage]
    _check_common_document(receipt, expected_schema=receipt_schema, stage=stage,
                           case_id=case_id, attempt=attempt, source_id=source_id,
                           source_sha256=source_sha256, label=f"{stage} receipt")
    _check_common_document(manifest, expected_schema=manifest_schema, stage=stage,
                           case_id=case_id, attempt=attempt, source_id=source_id,
                           source_sha256=source_sha256, label=f"{stage} manifest")
    receipt_expected = {
        "schema", "stage", "scope_id", "case_id", "attempt_id", "nonce_hex", "source_id",
        "source_sha256", "manifest_sha256", "upstream_receipt_sha256", "time_axis_sha256",
        "raw_frame_manifest_sha256", "decoded_frame_manifest_sha256",
    }
    manifest_common = {
        "schema", "stage", "scope_id", "case_id", "attempt_id", "nonce_hex", "source_id",
        "source_sha256",
    }
    _require(set(receipt) == receipt_expected, f"{stage} receipt fields are not exact")
    _require(set(manifest) == manifest_common | ({
        "time_axis_sha256", "raw_frame_manifest_sha256", "decoded_frame_manifest_sha256",
    } if stage == "B" else {
        "upstream_receipt_sha256", "time_axis_sha256", "raw_frame_manifest_sha256", "frames",
    } if stage == "C" else {
        "upstream_receipt_sha256", "time_axis_sha256", "raw_frame_manifest_sha256",
        "decoded_frame_manifest_sha256", "frames",
    }), f"{stage} manifest fields are not exact")
    _require(receipt["manifest_sha256"] == manifest_sha256,
             f"{stage} receipt manifest digest does not match held manifest bytes")
    _require(receipt["upstream_receipt_sha256"] == upstream_receipt_sha256,
             f"{stage} receipt upstream digest drifted")
    _require(receipt["time_axis_sha256"] == time_axis_sha256
             and receipt["raw_frame_manifest_sha256"] == raw_frame_manifest_sha256
             and receipt["decoded_frame_manifest_sha256"] == decoded_frame_manifest_sha256,
             f"{stage} receipt frame/time digest binding drifted")
    if stage == "B":
        _require(manifest["time_axis_sha256"] == time_axis_sha256
                 and manifest["raw_frame_manifest_sha256"] == raw_frame_manifest_sha256
                 and manifest["decoded_frame_manifest_sha256"] == decoded_frame_manifest_sha256,
                 "B manifest frame/time digest binding drifted")
    elif stage == "C":
        _require(manifest["upstream_receipt_sha256"] == upstream_receipt_sha256
                 and manifest["time_axis_sha256"] == time_axis_sha256
                 and manifest["raw_frame_manifest_sha256"] == raw_frame_manifest_sha256,
                 "C manifest upstream/frame digest binding drifted")
        actual_rows = _validate_frame_rows(manifest["frames"], decoded=False, label="C manifest.frames")
        expected_rows = [
            {"ordinal": row["ordinal"], "time_ieee754_hex": row["time_ieee754_hex"],
             "raw_frame_sha256": row["raw"]["sha256"]}
            for row in frames
        ]
        _require(actual_rows == expected_rows, "C manifest frame digest/time rows drifted")
    else:
        _require(manifest["upstream_receipt_sha256"] == upstream_receipt_sha256
                 and manifest["time_axis_sha256"] == time_axis_sha256
                 and manifest["raw_frame_manifest_sha256"] == raw_frame_manifest_sha256
                 and manifest["decoded_frame_manifest_sha256"] == decoded_frame_manifest_sha256,
                 "D manifest upstream/frame digest binding drifted")
        actual_rows = _validate_frame_rows(manifest["frames"], decoded=True, label="D manifest.frames")
        expected_rows = [
            {"ordinal": row["ordinal"], "time_ieee754_hex": row["time_ieee754_hex"],
             "raw_frame_sha256": row["raw"]["sha256"],
             "decoded_frame_sha256": row["decoded"]["sha256"]}
            for row in frames
        ]
        _require(actual_rows == expected_rows, "D manifest frame digest/time rows drifted")


def verify_held_fd_bcd_input_provenance(
    descriptor: Mapping[str, Any], *, held_fds: Mapping[str, int],
) -> dict[str, Any]:
    """Verify one synthetic pathless B/C/D input provenance chain.

    ``held_fds`` is the only file access surface.  The caller owns every FD;
    this function neither opens nor closes descriptors and never accepts a
    pathname.  A successful result is deliberately diagnostic-only.
    """
    value, source, stages, frames = _validate_descriptor(descriptor)
    _require(type(held_fds) is dict, "held_fds must be a builtin dict of caller-held descriptors")
    expected_slots = {source["fd_slot"]}
    for stage in STAGES:
        expected_slots.update({stages[stage]["receipt"]["slot"], stages[stage]["manifest"]["slot"]})
    for frame in frames:
        expected_slots.update({frame["raw"]["slot"], frame["decoded"]["slot"]})
    _require(set(held_fds) == expected_slots,
             "held_fds slots differ from the exact pathless descriptor inventory")
    for slot in held_fds:
        _slot(slot, f"held_fds[{slot!r}]")

    seen_identities: dict[tuple[int, ...], str] = {}
    total = [0]
    payloads: dict[str, bytes] = {}
    digests: dict[str, str] = {}

    source_payload, source_sha256, source_identity = _read_held_fd(
        held_fds[source["fd_slot"]], source["bytes"], "B.source",
    )
    _require(source_sha256 == source["sha256"], "B.source bytes differ from its declared digest")
    seen_identities[source_identity] = "B.source"
    total[0] += len(source_payload)
    _require(total[0] <= MAX_TOTAL_BYTES, "held-FD input bytes exceed the aggregate bound")
    source_document = _parse_canonical_document(source_payload, "B source document")
    _check_source_document(
        source_document, case_id=value["case_id"], attempt=value["attempt"],
        source_id=source["source_id"],
    )

    for stage in STAGES:
        for role in ("receipt", "manifest"):
            artifact = stages[stage][role]
            payload, digest = _check_artifact_bytes(
                artifact, held_fds, label=f"{stage}.{role}",
                seen_identities=seen_identities, total=total,
            )
            payloads[f"{stage}.{role}"] = payload
            digests[f"{stage}.{role}"] = digest
        if stage in {"C", "D"}:
            for frame in frames:
                if stage == "C":
                    artifact = frame["raw"]
                    label = f"C.frame.{frame['ordinal']:04d}"
                else:
                    artifact = frame["decoded"]
                    label = f"D.frame.{frame['ordinal']:04d}"
                payload, digest = _check_artifact_bytes(
                    artifact, held_fds, label=label,
                    seen_identities=seen_identities, total=total,
                )
                payloads[artifact["slot"]] = payload
                digests[artifact["slot"]] = digest

    _require(digests["B.receipt"] == stages["B"]["receipt"]["sha256"], "B receipt digest drifted")
    _require(digests["B.manifest"] == stages["B"]["manifest"]["sha256"], "B manifest digest drifted")
    _require(digests["C.receipt"] == stages["C"]["receipt"]["sha256"], "C receipt digest drifted")
    _require(digests["C.manifest"] == stages["C"]["manifest"]["sha256"], "C manifest digest drifted")
    _require(digests["D.receipt"] == stages["D"]["receipt"]["sha256"], "D receipt digest drifted")
    _require(digests["D.manifest"] == stages["D"]["manifest"]["sha256"], "D manifest digest drifted")

    documents = {
        key: _parse_canonical_document(payload, f"{key} document")
        for key, payload in payloads.items()
        if key in {"B.receipt", "B.manifest", "C.receipt", "C.manifest", "D.receipt", "D.manifest"}
    }
    source_sha256 = source["sha256"]
    raw_manifest_rows = [
        {"ordinal": frame["ordinal"], "time_ieee754_hex": frame["time_ieee754_hex"],
         "raw_frame_sha256": frame["raw"]["sha256"]}
        for frame in frames
    ]
    decoded_manifest_rows = [
        {"ordinal": frame["ordinal"], "time_ieee754_hex": frame["time_ieee754_hex"],
         "raw_frame_sha256": frame["raw"]["sha256"],
         "decoded_frame_sha256": frame["decoded"]["sha256"]}
        for frame in frames
    ]
    times = [frame["time_ieee754_hex"] for frame in frames]
    time_axis_sha256 = _sha256_json(times, "verified time axis")
    raw_frame_manifest_sha256 = _sha256_json(raw_manifest_rows, "verified raw frame manifest")
    decoded_frame_manifest_sha256 = _sha256_json(decoded_manifest_rows, "verified decoded frame manifest")
    _require(value["time_axis_sha256"] == time_axis_sha256, "verified time-axis digest drifted")
    _require(value["raw_frame_manifest_sha256"] == raw_frame_manifest_sha256,
             "verified raw frame manifest digest drifted")
    _require(value["decoded_frame_manifest_sha256"] == decoded_frame_manifest_sha256,
             "verified decoded frame manifest digest drifted")

    for stage in STAGES:
        stage_value = stages[stage]
        _require(stage_value["source_sha256"] == source_sha256,
                 f"{stage} descriptor source digest drifted")
        _require(stage_value["time_axis_sha256"] == time_axis_sha256,
                 f"{stage} descriptor time-axis digest drifted")
        _require(stage_value["raw_frame_manifest_sha256"] == raw_frame_manifest_sha256,
                 f"{stage} descriptor raw frame digest drifted")
        _require(stage_value["decoded_frame_manifest_sha256"] == decoded_frame_manifest_sha256,
                 f"{stage} descriptor decoded frame digest drifted")

    b_receipt_sha256 = digests["B.receipt"]
    c_receipt_sha256 = digests["C.receipt"]
    _require(stages["C"]["upstream_receipt_sha256"] == b_receipt_sha256,
             "C descriptor upstream receipt digest drifted")
    _require(stages["D"]["upstream_receipt_sha256"] == c_receipt_sha256,
             "D descriptor upstream receipt digest drifted")
    _check_stage_documents(
        stage="B", receipt=documents["B.receipt"], manifest=documents["B.manifest"],
        receipt_sha256=b_receipt_sha256, manifest_sha256=digests["B.manifest"],
        source_sha256=source_sha256, case_id=value["case_id"], attempt=value["attempt"],
        source_id=source["source_id"], upstream_receipt_sha256=None,
        time_axis_sha256=time_axis_sha256, raw_frame_manifest_sha256=raw_frame_manifest_sha256,
        decoded_frame_manifest_sha256=decoded_frame_manifest_sha256, frames=frames,
    )
    _require(stages["B"]["upstream_receipt_sha256"] is None, "B upstream receipt must remain null")
    _check_stage_documents(
        stage="C", receipt=documents["C.receipt"], manifest=documents["C.manifest"],
        receipt_sha256=c_receipt_sha256, manifest_sha256=digests["C.manifest"],
        source_sha256=source_sha256, case_id=value["case_id"], attempt=value["attempt"],
        source_id=source["source_id"], upstream_receipt_sha256=b_receipt_sha256,
        time_axis_sha256=time_axis_sha256, raw_frame_manifest_sha256=raw_frame_manifest_sha256,
        decoded_frame_manifest_sha256=decoded_frame_manifest_sha256, frames=frames,
    )
    _check_stage_documents(
        stage="D", receipt=documents["D.receipt"], manifest=documents["D.manifest"],
        receipt_sha256=digests["D.receipt"], manifest_sha256=digests["D.manifest"],
        source_sha256=source_sha256, case_id=value["case_id"], attempt=value["attempt"],
        source_id=source["source_id"], upstream_receipt_sha256=c_receipt_sha256,
        time_axis_sha256=time_axis_sha256, raw_frame_manifest_sha256=raw_frame_manifest_sha256,
        decoded_frame_manifest_sha256=decoded_frame_manifest_sha256, frames=frames,
    )

    for frame in frames:
        ordinal = frame["ordinal"]
        raw_document = _parse_canonical_document(
            payloads[frame["raw"]["slot"]], f"C frame {ordinal} document",
        )
        decoded_document = _parse_canonical_document(
            payloads[frame["decoded"]["slot"]], f"D frame {ordinal} document",
        )
        _check_frame_document(
            raw_document, stage="C", ordinal=ordinal, time_hex=frame["time_ieee754_hex"],
            case_id=value["case_id"], attempt=value["attempt"], source_id=source["source_id"],
        )
        _check_frame_document(
            decoded_document, stage="D", ordinal=ordinal, time_hex=frame["time_ieee754_hex"],
            case_id=value["case_id"], attempt=value["attempt"], source_id=source["source_id"],
            raw_sha256=frame["raw"]["sha256"],
        )
        _require(frame["raw"]["sha256"] == digests[frame["raw"]["slot"]],
                 f"C frame {ordinal} descriptor digest drifted")
        _require(frame["decoded"]["sha256"] == digests[frame["decoded"]["slot"]],
                 f"D frame {ordinal} descriptor digest drifted")

    chain_payload = {
        "scope_id": SCOPE_ID,
        "case_id": value["case_id"],
        "attempt": value["attempt"],
        "source_sha256": source_sha256,
        "receipt_sha256": {stage: digests[f"{stage}.receipt"] for stage in STAGES},
        "manifest_sha256": {stage: digests[f"{stage}.manifest"] for stage in STAGES},
        "time_axis_sha256": time_axis_sha256,
        "raw_frame_manifest_sha256": raw_frame_manifest_sha256,
        "decoded_frame_manifest_sha256": decoded_frame_manifest_sha256,
        "frames": decoded_manifest_rows,
    }
    chain_digest = _sha256_json(chain_payload, "B/C/D held-FD chain")
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "synthetic_held_fd_bcd_input_provenance_bound_diagnostic",
        "scope_id": SCOPE_ID,
        "input_origin": "synthetic_pathless_descriptor_and_caller_held_fds",
        "case_id": value["case_id"],
        "attempt": dict(value["attempt"]),
        "source_id": source["source_id"],
        "stage_statuses": {stage: "bound" for stage in STAGES},
        "held_fd_only": True,
        "pathname_reopen_attempted": False,
        "symlink_followed": False,
        "hardlink_accepted": False,
        "fd_identity_aliases": False,
        "source_digest_bound": True,
        "attempt_identity_bound": True,
        "case_identity_bound": True,
        "time_axis_bound": True,
        "raw_frame_digests_bound": True,
        "decoded_frame_digests_bound": True,
        "upstream_receipt_digests_bound": True,
        "chain_digest_sha256": chain_digest,
        "artifact_count": len(expected_slots),
        "frame_count": len(frames),
        "total_held_fd_bytes": total[0],
        "production_bundle_read": False,
        "production_hdf5_or_bi4_read": False,
        "native_integrity_evaluated": False,
        "terminal_observation_verified": False,
        "source_authenticated": False,
        "runtime_authenticated": False,
        "readiness_pass": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "diagnostic_only": True,
        "qualification_credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }


def build_report() -> dict[str, Any]:
    """Return the immutable implementation report for this adapter."""
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": "synthetic_only_held_fd_bcd_input_provenance_adapter_implemented",
        "component": {
            "schema": SCHEMA,
            "scope_id": SCOPE_ID,
            "input": "pathless canonical descriptor plus caller-held regular-file FDs",
            "stages": list(STAGES),
            "artifact_roles": [
                "B_source", "B_receipt", "B_manifest", "C_receipt", "C_manifest",
                "C_raw_frame", "D_receipt", "D_manifest", "D_decoded_frame",
            ],
            "output": "diagnostic B/C/D input provenance snapshot; no Core projection",
        },
        "checks": [
            "exact pathless descriptor fields and forbidden pathname-key rejection",
            "held-FD-only access using fstat/pread with no pathname reopen",
            "regular-file, single-link, bounded-size, stable-FD identity checks",
            "unique held-FD inode identity across every B/C/D artifact",
            "canonical synthetic source, receipt, manifest, and frame documents",
            "case/attempt/nonce/source identity equality across B/C/D and every frame",
            "B-to-C-to-D upstream receipt SHA-256 closure",
            "binary64 time-axis, raw-frame, and decoded-frame manifest digest closure",
            "raw C frame bytes cross-bound to decoded D frame provenance",
            "fixed diagnostic-only and zero-credit boundary",
        ],
        "non_authorizing_boundary": {
            "synthetic_only": True,
            "production_bundle_read": False,
            "production_hdf5_or_bi4_read": False,
            "pathname_reopen": False,
            "symlink_follow": False,
            "hardlink_acceptance": False,
            "gencase_invoked": False,
            "native_invoked": False,
            "solver_invoked": False,
            "worker_or_scheduler_launch_invoked": False,
            "gpu_or_queue_invoked": False,
            "privileged_probe_invoked": False,
            "native_integrity_evaluated": False,
            "terminal_observation_verified": False,
            "readiness_pass": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "diagnostic_only": True,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "remaining_blockers": [
            "the synthetic holder is not an authenticated B/C/D producer or authority",
            "production bundle/HDF5/BI4 provenance and trusted worker/runtime identity remain external",
            "native-integrity, terminal, metric, T1, and qualification adjudication are not performed",
        ],
    }


def verify_report_bytes(payload: bytes) -> dict[str, Any]:
    """Verify report bytes without adding a pathname I/O surface."""
    value = _parse_canonical_document(payload, "held-FD adapter report")
    _require(value == build_report(), "held-FD adapter report differs from build_report()")
    return value


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-report", action="store_true")
    parser.add_argument("--verify-report-stdin", action="store_true")
    args = parser.parse_args()
    if args.verify_report_stdin:
        import sys
        verify_report_bytes(sys.stdin.buffer.read())
        print("verified")
    elif args.print_report:
        print(json.dumps(build_report(), indent=2, sort_keys=True, allow_nan=False))
    else:
        print(json.dumps({
            "schema": SCHEMA,
            "status": "synthetic_only",
            "diagnostic_only": True,
            "qualification_credit": 0,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "B_MANIFEST_SCHEMA", "B_RECEIPT_SCHEMA", "C_FRAME_SCHEMA", "C_MANIFEST_SCHEMA",
    "C_RECEIPT_SCHEMA", "D_FRAME_SCHEMA", "D_MANIFEST_SCHEMA", "D_RECEIPT_SCHEMA",
    "EXPECTED_HELD_FD_CONTRACT", "HeldFdInputProvenanceError", "REPORT_RECORD_ID",
    "REPORT_SCHEMA", "RECORD_ID", "SCHEMA", "SCOPE_ID", "STAGES", "build_report",
    "verify_held_fd_bcd_input_provenance", "verify_report_bytes",
]
