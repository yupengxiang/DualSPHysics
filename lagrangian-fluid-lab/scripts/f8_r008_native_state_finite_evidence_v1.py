"""Evidence-only full-raw-state finite scan for closed F8 R008 bundles.

The producer never executes native programs and never adjudicates native
integrity, T1, readiness, or qualification. Inputs are reopened and checked
through the existing B/C/D and table-v2 verifiers before and after streaming
raw state arrays from held C output roots.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import stat
import struct
from typing import Any, Mapping

from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as table_chain
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_native_state_finite_scan_v1 as state_scan
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_native_state_finite_evidence.v1"
STATUS = "partial_native_state_evidence_not_adjudicated"
GATE_STATUS = "open_not_adjudicated"
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
STAGES = ("B", "C", "D")
TOP_LEVEL_FIELDS = {
    "schema", "status", "native_state_finite_status", "native_integrity_gate_status",
    "native_integrity_evaluated", "T1_numerical", "readiness_pass", "qualification_credit",
    "scope_id", "case_id", "stage_statuses", "table_semantics_status", "bundle_bindings",
    "trust_context", "qualification_scope", "frames",
}
SHA256_RE = bundle.SHA256_RE
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_TMPFILE = getattr(os, "O_TMPFILE", 0)


class NativeStateFiniteEvidenceError(ValueError):
    """The held R008 evidence inputs do not close or changed during the scan."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeStateFiniteEvidenceError(message)


def _dir_identity(fd: int) -> tuple[int, int, int, int, int, int]:
    st = os.fstat(fd)
    _require(stat.S_ISDIR(st.st_mode), "bundle/evidence root FD is not a directory")
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def _file_identity(fd: int) -> tuple[int, int, int, int, int, int]:
    st = os.fstat(fd)
    _require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1,
             "bound evidence input must be a single-link regular file")
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def _hash_fd(fd: int, expected_bytes: int) -> str:
    _require(isinstance(expected_bytes, int) and not isinstance(expected_bytes, bool)
             and 0 <= expected_bytes <= table_v2.MAX_TABLE_FILE_BYTES,
             "held-file hash size is outside the finite-evidence bound")
    digest = hashlib.sha256()
    offset = 0
    while offset < expected_bytes:
        block = os.pread(fd, min(HASH_CHUNK_BYTES, expected_bytes - offset), offset)
        _require(bool(block), "held evidence input became short while hashing")
        digest.update(block)
        offset += len(block)
    _require(os.pread(fd, 1, expected_bytes) == b"", "held evidence input grew while hashing")
    return digest.hexdigest()


def _read_binding(root_fd: int, relative: str, expected_sha256: str) -> tuple[bytes, str]:
    payload = bundle._stable_read_beneath(root_fd, relative, bundle.MAX_RECEIPT_BYTES)
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    _require(observed_sha256 == expected_sha256,
             f"held bundle binding changed for {relative}")
    return payload, observed_sha256


def _open_output_root(root_fd: int, expected_identity: tuple[int, int]) -> int:
    output_fd = bundle._open_child_directory(root_fd, "outputs")
    observed = os.fstat(output_fd)
    if (observed.st_dev, observed.st_ino) != expected_identity:
        os.close(output_fd)
        raise NativeStateFiniteEvidenceError("held output-root identity differs from verified stage")
    return output_fd


def _stage_verification(
    roots: Mapping[str, str],
    root_fds: Mapping[str, int],
    output_fds: Mapping[str, int],
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    checked: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        result = bundle.verify_stage_bundle(
            roots[stage], stage,
            trusted_authorization_bytes=trusted_authorization_bytes[stage],
            trusted_authorization_sha256=trusted_authorization_sha256[stage],
            expected_authorization_envelope=expected_authorization_envelopes[stage],
            trusted_code_review_receipt_bytes=(trusted_code_review_receipt_bytes if stage == "D" else None),
            trusted_runtime_assumption=(trusted_runtime_assumption if stage == "D" else None),
        )
        _require(result.get("status") == "passed", f"{stage} stage receipt is not passed")
        root_stat = os.fstat(root_fds[stage])
        output_stat = os.fstat(output_fds[stage])
        _require(result.get("_root_identity") == (root_stat.st_dev, root_stat.st_ino),
                 f"{stage} verifier reopened a different bundle-root inode")
        _require(result.get("_outputs_identity") == (output_stat.st_dev, output_stat.st_ino),
                 f"{stage} verifier reopened a different outputs-root inode")
        checked[stage] = result
    return checked


def _stage_bindings(
    root_fds: Mapping[str, int], checked: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, bytes]]:
    bindings: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    for stage in STAGES:
        result = checked[stage]
        receipt_bytes, receipt_sha = _read_binding(
            root_fds[stage], "receipt.json", result["receipt_sha256"],
        )
        manifest_relative = bundle.STAGE_OUTPUT_MANIFESTS[stage][1]
        manifest_bytes, manifest_sha = _read_binding(
            root_fds[stage], manifest_relative, result["manifest_sha256"],
        )
        bindings[stage] = {
            "receipt_bytes": len(receipt_bytes),
            "receipt_sha256": receipt_sha,
            "manifest_bytes": len(manifest_bytes),
            "manifest_sha256": manifest_sha,
        }
        payloads[f"{stage}_receipt"] = receipt_bytes
        payloads[f"{stage}_manifest"] = manifest_bytes
    return bindings, payloads


def _stable_json(payload: bytes, label: str) -> Any:
    result = bundle._parse_json(payload, label)
    _require(bundle._canonical_json(result) == payload,
             f"{label} is not in the frozen canonical JSON encoding")
    return result


def _validate_scope(case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen_row = bundle._frozen_qualification_row(case_id)
    lab_fd, _lab_path = bundle._open_absolute_directory(bundle.LAB)
    try:
        relative = bundle.FROZEN_SCOPE_RECEIPT.relative_to(bundle.LAB).as_posix()
        scope_bytes = bundle._stable_read_beneath(lab_fd, relative, bundle.MAX_RECEIPT_BYTES)
    finally:
        os.close(lab_fd)
    _require(hashlib.sha256(scope_bytes).hexdigest() == bundle.FROZEN_INPUT_SHA256["scope"],
             "frozen R008 scope receipt hash changed")
    scope = bundle._parse_json(scope_bytes, "frozen R008 scope receipt")
    rows = scope.get("matrix", {}).get("rows")
    _require(isinstance(rows, list), "frozen R008 qualification matrix is absent")
    qualified = [row for row in rows if isinstance(row, dict) and row.get("qualification_only") is True]
    _require(len(qualified) == 15, "frozen R008 qualification denominator is not exactly 15")
    matches = [row for row in qualified if row.get("case_id") == case_id]
    _require(len(matches) == 1, "case_id is not exactly one frozen qualification row")
    row = matches[0]
    _require(frozen_row.get("qualification_only") is True,
             "frozen Definition/control case is not qualification-only")
    return frozen_row, row


def _binding_objects_unchanged(
    roots: Mapping[str, str], root_fds: Mapping[str, int], output_fds: Mapping[str, int],
    before_root_ids: Mapping[str, tuple[int, int, int, int, int, int]],
    before_output_ids: Mapping[str, tuple[int, int, int, int, int, int]],
) -> None:
    for stage in STAGES:
        _require(_dir_identity(root_fds[stage]) == before_root_ids[stage],
                 f"{stage} held bundle root changed during evidence collection")
        _require(_dir_identity(output_fds[stage]) == before_output_ids[stage],
                 f"{stage} held outputs root changed during evidence collection")
        root_fd, reopened = bundle._open_absolute_directory(roots[stage])
        try:
            st = os.fstat(root_fd)
            held = os.fstat(root_fds[stage])
            _require(reopened == roots[stage] and (st.st_dev, st.st_ino) == (held.st_dev, held.st_ino),
                     f"{stage} bundle path no longer resolves to its held root FD")
        finally:
            os.close(root_fd)


def _hash_frame_file(fd: int, size: int) -> str:
    return _hash_fd(fd, size)


def _link_unnamed_noreplace(directory_fd: int, source_fd: int, destination: str) -> None:
    _require(_O_TMPFILE != 0, "unnamed O_TMPFILE publication is unavailable")
    # Linking through procfs keeps the source inode unnamed until the single
    # no-replace link operation; the source descriptor remains open throughout.
    os.link(
        f"/proc/self/fd/{source_fd}", destination,
        dst_dir_fd=directory_fd, follow_symlinks=True,
    )


def _evidence_directory_path_matches(
    path: str, expected_identity: tuple[int, int], *, require_private: bool,
) -> bool:
    try:
        fd, reopened = bundle._open_absolute_directory(path)
    except (OSError, ValueError):
        return False
    try:
        st = os.fstat(fd)
        same_object = reopened == path and (st.st_dev, st.st_ino) == expected_identity
        private_enough = (
            st.st_uid == os.geteuid()
            and not (stat.S_IMODE(st.st_mode) & 0o022)
        )
        return same_object and (private_enough or not require_private)
    finally:
        try:
            os.close(fd)
        except OSError:
            return False


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        _require(written > 0, "short write while publishing finite evidence")
        offset += written


def _publish_no_replace(directory_fd: int, case_id: str, payload: bytes) -> dict[str, Any]:
    _require(len(payload) <= MAX_EVIDENCE_BYTES, "finite evidence JSON exceeds its size cap")
    filename = f"native-state-finite-evidence-{case_id}.json"
    fd: int | None = None
    committed = False
    _require(_O_TMPFILE != 0, "unnamed O_TMPFILE publication is unavailable")
    try:
        fd = os.open(
            ".", _O_TMPFILE | os.O_RDWR | _O_CLOEXEC, 0o600, dir_fd=directory_fd,
        )
        st = os.fstat(fd)
        _require(stat.S_ISREG(st.st_mode) and st.st_nlink == 0
                 and st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o600,
                 "finite evidence unnamed temporary inode has unsafe type, owner, link count, or mode")
        _write_all(fd, payload)
        os.fsync(fd)
        _require(os.fstat(fd).st_size == len(payload), "finite evidence unnamed temporary size is incorrect")
        expected_sha256 = hashlib.sha256(payload).hexdigest()
        _require(_hash_fd(fd, len(payload)) == expected_sha256,
                 "finite evidence unnamed temporary hash differs from the canonical record")

        # This link is the commit point. EEXIST leaves the existing evidence intact.
        # Keep fd open so the published name can be checked against this exact inode.
        _link_unnamed_noreplace(directory_fd, fd, filename)
        committed = True
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        raise

    post_publish_validation_ok = True
    post_publish_error: str | None = None
    final_fd: int | None = None
    try:
        final_fd = os.open(filename, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=directory_fd)
        identity = _file_identity(final_fd)
        source_identity = _file_identity(fd)
        _require(identity[:2] == source_identity[:2] and identity[2] == len(payload)
                 and _hash_fd(final_fd, len(payload)) == expected_sha256,
                 "published finite evidence differs from its canonical payload")
    except (OSError, NativeStateFiniteEvidenceError) as error:
        post_publish_validation_ok = False
        post_publish_error = type(error).__name__
    if final_fd is not None:
        try:
            os.close(final_fd)
        except OSError as error:
            post_publish_validation_ok = False
            post_publish_error = post_publish_error or type(error).__name__
    directory_fsync_ok = True
    try:
        os.fsync(directory_fd)
    except OSError as error:
        directory_fsync_ok = False
    descriptor_close_ok = True
    try:
        os.close(fd)
        fd = None
    except OSError as error:
        fd = None
        descriptor_close_ok = False
        post_publish_validation_ok = False
        post_publish_error = post_publish_error or type(error).__name__
    return {
        "path": filename,
        "bytes": len(payload),
        "sha256": expected_sha256,
        "published": committed,
        "post_publish_validation_ok": post_publish_validation_ok,
        "post_publish_validation_error": post_publish_error,
        "directory_fsync_after_publish_ok": directory_fsync_ok,
        "source_descriptor_close_ok": descriptor_close_ok,
    }


def collect_and_publish_native_state_finite_evidence(
    bundle_roots: Mapping[str, Path | str],
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
    trusted_table_review_receipt_bytes: bytes,
    trusted_table_review_receipt_sha256: str,
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
    evidence_directory: Path | str,
) -> dict[str, Any]:
    """Verify and publish one full-axis, single-qualification-case evidence file."""
    _require(set(bundle_roots) == set(STAGES)
             and set(trusted_authorization_bytes) == set(STAGES)
             and set(trusted_authorization_sha256) == set(STAGES)
             and set(expected_authorization_envelopes) == set(STAGES),
             "finite evidence requires exact B/C/D roots and authorization bindings")
    roots: dict[str, str] = {}
    root_fds: dict[str, int] = {}
    output_fds: dict[str, int] = {}
    evidence_fd: int | None = None
    table_fd: int | None = None
    try:
        for stage in STAGES:
            root_fd, absolute = bundle._open_absolute_directory(bundle_roots[stage])
            roots[stage] = absolute
            root_fds[stage] = root_fd
        _require(len({(os.fstat(root_fds[s]).st_dev, os.fstat(root_fds[s]).st_ino) for s in STAGES}) == 3,
                 "B/C/D bundle roots are not three distinct directory objects")
        for stage in STAGES:
            output_fds[stage] = bundle._open_child_directory(root_fds[stage], "outputs")
        evidence_fd, evidence_path = bundle._open_absolute_directory(evidence_directory)
        evidence_stat = os.fstat(evidence_fd)
        evidence_identity = (evidence_stat.st_dev, evidence_stat.st_ino)
        _require(evidence_stat.st_uid == os.geteuid()
                 and not (stat.S_IMODE(evidence_stat.st_mode) & 0o022),
                 "finite evidence directory must be caller-owned and not group/world writable")
        for root in roots.values():
            _require(os.path.commonpath((evidence_path, root)) not in {root, evidence_path}
                     and not Path(evidence_path).is_relative_to(Path(root)),
                     "finite evidence output directory must be outside every B/C/D bundle root")

        before_root_ids = {stage: _dir_identity(root_fds[stage]) for stage in STAGES}
        before_output_ids = {stage: _dir_identity(output_fds[stage]) for stage in STAGES}
        checked_before = _stage_verification(
            roots, root_fds, output_fds,
            trusted_authorization_bytes=trusted_authorization_bytes,
            trusted_authorization_sha256=trusted_authorization_sha256,
            expected_authorization_envelopes=expected_authorization_envelopes,
            trusted_code_review_receipt_bytes=trusted_code_review_receipt_bytes,
            trusted_runtime_assumption=trusted_runtime_assumption,
        )
        case_ids = {checked_before[stage]["case_id"] for stage in STAGES}
        _require(len(case_ids) == 1, "B/C/D stage case identities differ")
        case_id = next(iter(case_ids))
        frozen_row, scope_row = _validate_scope(case_id)
        expected_axis = bundle.expected_time_axis_hex(frozen_row)
        start_ordinal = scope_row.get("observation_start_output_index")
        end_ordinal = scope_row.get("observation_end_output_index")
        _require(isinstance(start_ordinal, int) and not isinstance(start_ordinal, bool)
                 and isinstance(end_ordinal, int) and not isinstance(end_ordinal, bool)
                 and 0 <= start_ordinal <= end_ordinal < len(expected_axis),
                 "frozen observation window ordinals are malformed")

        bundle_bindings, binding_payloads = _stage_bindings(root_fds, checked_before)
        c_manifest = _stable_json(binding_payloads["C_manifest"], "C raw solver manifest")
        d_receipt = _stable_json(binding_payloads["D_receipt"], "D stage receipt")
        d_manifest_path = "manifests/decoded-frame-manifest.json"
        d_frame_bytes = bundle._stable_read_beneath(
            root_fds["D"], d_manifest_path, bundle.MAX_RECEIPT_BYTES,
        )
        d_frame_sha = hashlib.sha256(d_frame_bytes).hexdigest()
        d_frame_manifest = _stable_json(d_frame_bytes, "D decoded-frame manifest")
        _require(d_frame_manifest == checked_before["D"]["_decoded_frame_manifest_document"],
                 "held D decoded-frame manifest differs from the verified stage document")
        bundle_bindings["D"].update({
            "decoded_frame_manifest_bytes": len(d_frame_bytes),
            "decoded_frame_manifest_sha256": d_frame_sha,
            "table_bytes": d_receipt["native_fluid_table_binding"]["bytes"],
            "table_sha256": d_receipt["native_fluid_table_binding"]["sha256"],
        })
        c_frames = c_manifest.get("frames")
        d_frames = d_frame_manifest.get("frames")
        _require(isinstance(c_frames, list) and isinstance(d_frames, list)
                 and len(c_frames) == len(expected_axis) == len(d_frames),
                 "C/D manifests do not contain the exact complete frozen frame axis")

        table_binding = d_receipt["native_fluid_table_binding"]
        _require(table_binding.get("path") == "outputs/native-fluid-frame-table-v2.h5",
                 "D receipt table path differs from the exact v2 registration")
        table_fd = decoder.open_regular_beneath(
            output_fds["D"], table_binding["path"][len("outputs/"):],
        )
        table_identity = _file_identity(table_fd)
        _require(table_identity[2] == table_binding["bytes"]
                 and _hash_fd(table_fd, table_binding["bytes"]) == table_binding["sha256"],
                 "held D table FD differs from its receipt/output-manifest binding")

        chain_args = {
            "bundle_roots": roots,
            "trusted_authorization_bytes": trusted_authorization_bytes,
            "trusted_authorization_sha256": trusted_authorization_sha256,
            "expected_authorization_envelopes": expected_authorization_envelopes,
            "trusted_table_review_receipt_bytes": trusted_table_review_receipt_bytes,
            "trusted_table_review_receipt_sha256": trusted_table_review_receipt_sha256,
            "trusted_code_review_receipt_bytes": trusted_code_review_receipt_bytes,
            "trusted_runtime_assumption": trusted_runtime_assumption,
        }
        table_before = table_chain.verify_native_fluid_table_chain(**chain_args)
        _require(table_before.get("case_id") == case_id
                 and table_before.get("stage_statuses") == {stage: "passed" for stage in STAGES}
                 and table_before.get("provenance_chain_references_closed") is True,
                 "B/C/D table-v2 pre-scan chain did not close with all stages passed")
        table_semantics = table_before.get("native_fluid_table")
        _require(isinstance(table_semantics, dict)
                 and table_semantics.get("table_sha256") == table_binding["sha256"]
                 and table_semantics.get("table_bytes") == table_binding["bytes"]
                 and table_semantics.get("all_valid") is True
                 and table_semantics.get("native_integrity_evaluated") is False,
                 "native-fluid-table-v2 semantic verification did not pass exactly")

        b_receipt = checked_before["B"]["_receipt_document"]
        cohorts, _mass_bits = bundle._verify_b_materialization_semantics(
            output_fds["B"], checked_before["B"]["_output_file_manifest"], b_receipt,
        )
        case_np = cohorts.get("case_np")
        _require(isinstance(case_np, int) and not isinstance(case_np, bool)
                 and 0 < case_np <= decoder.MAX_ARRAY_COUNT,
                 "B generated XML CaseNp is outside the native-state scan bound")

        frames: list[dict[str, Any]] = []
        raw_identities: dict[int, tuple[int, int, int, int, int, int]] = {}
        for ordinal, (raw_frame, decoded_frame) in enumerate(zip(c_frames, d_frames)):
            _require(raw_frame.get("ordinal") == ordinal
                     and decoded_frame.get("ordinal") == ordinal
                     and raw_frame.get("expected_time_s_ieee754_hex") == expected_axis[ordinal]
                     and decoded_frame.get("expected_time_s_ieee754_hex") == expected_axis[ordinal]
                     and decoded_frame.get("raw_path") == raw_frame.get("path")
                     and decoded_frame.get("raw_bytes") == raw_frame.get("bytes")
                     and decoded_frame.get("raw_sha256") == raw_frame.get("sha256")
                     and decoded_frame.get("safe_decode_input_sha256") == raw_frame.get("sha256"),
                     f"C/D frame {ordinal} is not paired to the frozen raw input")
            raw_fd = decoder.open_regular_beneath(output_fds["C"], raw_frame["path"])
            try:
                initial_identity = _file_identity(raw_fd)
                _require(initial_identity[2] == raw_frame["bytes"],
                         f"C frame {ordinal} size differs from its raw manifest")
                raw_identities[ordinal] = initial_identity
                scan = decoder.scan_bi4_fd(raw_fd, raw_frame["sha256"])
                _require(scan.input_bytes == raw_frame["bytes"],
                         f"C frame {ordinal} scanner size differs from its raw manifest")
                arrays = state_scan.summarize_native_state_fd(
                    raw_fd, raw_frame["sha256"], scan, case_np=case_np,
                )
                _safe_relative, safe_payload = bundle._read_bound_output(
                    output_fds["D"], checked_before["D"]["_output_file_manifest"],
                    decoded_frame["safe_decode_receipt_path"],
                    decoded_frame["safe_decode_receipt_bytes"],
                    decoded_frame["safe_decode_receipt_sha256"], "D safe-decode receipt",
                )
                safe_receipt = bundle._parse_json(safe_payload, "D safe-decode receipt")
                bundle._verify_safe_decode_against_scan(
                    raw_fd, scan, safe_receipt, decoded_frame, output_fds["D"],
                    checked_before["D"]["_output_file_manifest"],
                    checked_before["D"]["_output_directories"],
                )
            finally:
                os.close(raw_fd)
            try:
                observed_time = float.fromhex(decoded_frame["parser_observed_time_s_ieee754_hex"])
                expected_time = float.fromhex(expected_axis[ordinal])
            except (KeyError, TypeError, ValueError) as error:
                raise NativeStateFiniteEvidenceError(
                    f"C/D frame {ordinal} time is not canonical binary64 hexadecimal",
                ) from error
            observed_hex = decoded_frame["parser_observed_time_s_ieee754_hex"]
            _require(math.isfinite(observed_time) and observed_time.hex() == observed_hex
                     and not (observed_time == 0.0 and math.copysign(1.0, observed_time) < 0.0)
                     and math.isfinite(expected_time)
                     and expected_time.hex() == expected_axis[ordinal]
                     and not (expected_time == 0.0 and math.copysign(1.0, expected_time) < 0.0),
                     f"D frame {ordinal} has a noncanonical or negative-zero TimeStep")
            _require(struct.pack("<d", observed_time) == struct.pack("<d", expected_time),
                     f"D frame {ordinal} TimeStep bits differ from the frozen expected axis")
            member = start_ordinal <= ordinal <= end_ordinal
            frames.append({
                "ordinal": ordinal,
                "expected_time_s_ieee754_hex": expected_axis[ordinal],
                "observed_time_s_ieee754_hex": observed_hex,
                "observation_window_member": member,
                "native_arrays": arrays,
            })

        table_after = table_chain.verify_native_fluid_table_chain(**chain_args)
        _require(table_after.get("case_id") == case_id
                 and table_after.get("stage_statuses") == {stage: "passed" for stage in STAGES}
                 and table_after.get("provenance_chain_references_closed") is True
                 and table_after.get("receipt_sha256") == table_before.get("receipt_sha256")
                 and table_after.get("manifest_sha256") == table_before.get("manifest_sha256"),
                 "B/C/D provenance changed or failed during native-state scan")
        _require(table_after.get("native_fluid_table", {}).get("table_sha256") == table_binding["sha256"]
                 and table_after.get("native_fluid_table", {}).get("table_bytes") == table_binding["bytes"],
                 "D table binding changed during native-state scan")

        checked_after = _stage_verification(
            roots, root_fds, output_fds,
            trusted_authorization_bytes=trusted_authorization_bytes,
            trusted_authorization_sha256=trusted_authorization_sha256,
            expected_authorization_envelopes=expected_authorization_envelopes,
            trusted_code_review_receipt_bytes=trusted_code_review_receipt_bytes,
            trusted_runtime_assumption=trusted_runtime_assumption,
        )
        bindings_after, payloads_after = _stage_bindings(root_fds, checked_after)
        _require(bindings_after == {stage: {
            key: value for key, value in binding.items()
            if key not in {"decoded_frame_manifest_bytes", "decoded_frame_manifest_sha256", "table_bytes", "table_sha256"}
        } for stage, binding in bundle_bindings.items()},
                 "B/C/D receipt or output manifest bindings changed during finite scan")
        _require(payloads_after == {
            key: value for key, value in binding_payloads.items()
        }, "B/C/D receipt or output manifest bytes changed during finite scan")
        d_frame_after = bundle._stable_read_beneath(root_fds["D"], d_manifest_path, bundle.MAX_RECEIPT_BYTES)
        _require(d_frame_after == d_frame_bytes
                 and hashlib.sha256(d_frame_after).hexdigest() == d_frame_sha,
                 "D decoded-frame manifest changed during finite scan")
        for ordinal, raw_frame in enumerate(c_frames):
            saved_identity = raw_identities[ordinal]
            reopened_fd = decoder.open_regular_beneath(output_fds["C"], raw_frame["path"])
            try:
                _require(_file_identity(reopened_fd) == saved_identity
                         and _hash_frame_file(reopened_fd, raw_frame["bytes"]) == raw_frame["sha256"],
                         f"C frame {ordinal} identity or SHA changed after finite scan")
            finally:
                os.close(reopened_fd)
        _require(_file_identity(table_fd) == table_identity
                 and _hash_fd(table_fd, table_binding["bytes"]) == table_binding["sha256"],
                 "held D table identity or SHA changed after finite scan")
        named_table_fd = decoder.open_regular_beneath(
            output_fds["D"], table_binding["path"][len("outputs/"):],
        )
        try:
            _require(_file_identity(named_table_fd) == table_identity
                     and _hash_fd(named_table_fd, table_binding["bytes"]) == table_binding["sha256"],
                     "D table path no longer resolves to the same held table inode")
        finally:
            os.close(named_table_fd)
        _binding_objects_unchanged(
            roots, root_fds, output_fds, before_root_ids, before_output_ids,
        )
        _require(_evidence_directory_path_matches(
            evidence_path, evidence_identity, require_private=True,
        ), "evidence output path no longer identifies its held private directory")

        runtime_payload = bundle._canonical_json(dict(trusted_runtime_assumption))
        evidence = {
            "schema": SCHEMA,
            "status": STATUS,
            "native_state_finite_status": (
                "observed_finite" if all(
                    item["required_state_values_finite"]
                    for frame in frames for item in frame["native_arrays"]
                ) else "observed_nonfinite"
            ),
            "native_integrity_gate_status": GATE_STATUS,
            "native_integrity_evaluated": False,
            "T1_numerical": False,
            "readiness_pass": False,
            "qualification_credit": 0,
            "scope_id": bundle.SCOPE_ID,
            "case_id": case_id,
            "stage_statuses": {stage: "passed" for stage in STAGES},
            "table_semantics_status": "passed",
            "bundle_bindings": bundle_bindings,
            "trust_context": {
                "authorization_sha256": dict(trusted_authorization_sha256),
                "code_review_receipt_sha256": hashlib.sha256(
                    trusted_code_review_receipt_bytes,
                ).hexdigest(),
                "table_review_receipt_sha256": trusted_table_review_receipt_sha256,
                "runtime_assumption_sha256": hashlib.sha256(runtime_payload).hexdigest(),
            },
            "qualification_scope": {
                "qualification_only": True,
                "qualification_row_count": 15,
                "full_frame_count": len(expected_axis),
                "observation_window_start_ordinal": start_ordinal,
                "observation_window_end_ordinal": end_ordinal,
            },
            "frames": frames,
        }
        _require(set(evidence) == TOP_LEVEL_FIELDS,
                 "finite evidence top-level exact schema drifted")
        payload = bundle._canonical_json(evidence)
        _require(len(payload) <= MAX_EVIDENCE_BYTES, "finite evidence JSON exceeds its byte cap")
        output = _publish_no_replace(evidence_fd, case_id, payload)
        output["evidence_directory_path_still_bound"] = _evidence_directory_path_matches(
            evidence_path, evidence_identity, require_private=True,
        )
        return {"evidence": evidence, "publication": output}
    except NativeStateFiniteEvidenceError:
        raise
    except (OSError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise NativeStateFiniteEvidenceError("F8 R008 native-state evidence collection failed closed") from error
    finally:
        if table_fd is not None:
            os.close(table_fd)
        for fd in output_fds.values():
            os.close(fd)
        for fd in root_fds.values():
            os.close(fd)
        if evidence_fd is not None:
            os.close(evidence_fd)


__all__ = [
    "GATE_STATUS", "MAX_EVIDENCE_BYTES", "NativeStateFiniteEvidenceError", "SCHEMA", "STATUS",
    "collect_and_publish_native_state_finite_evidence",
]
