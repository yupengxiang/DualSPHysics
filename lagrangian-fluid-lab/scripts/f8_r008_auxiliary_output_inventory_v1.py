"""Read-only auxiliary-output inventory for a closed R008 B/C bundle pair.

This diagnostic verifies B and C bundle membership, binds C to the exact B
receipt, derives boundary populations from B, and scans every manifest-bound
PartExtra file. Other known auxiliary formats are reported as unscanned, and
unknown files remain explicitly unclassified. Optional-output activation is
not authenticated here, so absence never means that an output mode was off.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Mapping

from scripts import f8_r008_part_extra_finite_inventory_v1 as part_extra
from scripts import f8_r008_partout_runparts_diagnostic_v1 as partout
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from scripts import f8_r008_runparts_timestep_diagnostic_v1 as runparts


SCHEMA = "core.cfd.f8.r008_auxiliary_output_inventory.v1"
STATUS = "partial_auxiliary_output_inventory_not_adjudicated"
PART_EXTRA_NAME = re.compile(r"PartExtra_([0-9]{4,})\.bi4\Z", re.ASCII)
PRIMARY_FRAME_PATH = re.compile(r"frames/Part_([0-9]{4})\.bi4\Z", re.ASCII)
PART_OUT_NAME = re.compile(r"PartOut_(?:p[0-9]{2,}_)?[0-9]{3,}\.obi4\Z", re.ASCII)
KNOWN_UNSCANNED_ROOT_NAMES = frozenset({
    "Part_Head.ibi4", "PartInfo.ibi4",
    "PartMotionRef.ibi4", "PartMotionRef2.ibi4",
    "PartFloatInfo.ibi4", "PartFloatInfo2.ibi4",
})
STAGES = ("B", "C")


class AuxiliaryOutputInventoryError(ValueError):
    """The held B/C bundle pair or one of its classified outputs is invalid."""


def _open_root_output(outputs_fd: int, path: str) -> tuple[int, tuple[int, int, int, int, int, int]]:
    _require("/" not in path and path not in {"", ".", ".."},
             "auxiliary diagnostic inputs must be root-level C outputs")
    try:
        fd = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
            dir_fd=outputs_fd,
        )
    except OSError as error:
        raise AuxiliaryOutputInventoryError(
            f"manifest-bound auxiliary output {path} cannot be opened safely"
        ) from error
    try:
        return fd, _file_identity(fd)
    except Exception:
        os.close(fd)
        raise


def _open_and_read_runparts(
    outputs_fd: int, path: str, expected: Mapping[str, Any],
) -> tuple[int, bytes, tuple[int, int, int, int, int, int]]:
    _require(path == "RunPARTs.csv", "RunPARTs must be a root-level C output")
    fd, identity = _open_root_output(outputs_fd, path)
    try:
        size = identity[2]
        _require(0 < size <= runparts.MAX_RUNPARTS_BYTES,
                 "manifest-bound RunPARTs.csv size is outside its parser cap")
        _require(size == expected["bytes"],
                 "held RunPARTs.csv size differs from the C output manifest")
        payload = bytearray()
        offset = 0
        while offset < size:
            block = os.pread(fd, min(1024 * 1024, size - offset), offset)
            _require(bool(block), "manifest-bound RunPARTs.csv was truncated while reading")
            payload.extend(block)
            offset += len(block)
        digest = hashlib.sha256(payload).hexdigest()
        _require(digest == expected["sha256"],
                 "held RunPARTs.csv SHA-256 differs from the C output manifest")
        _require(_file_identity(fd) == identity,
                 "held RunPARTs.csv identity changed during bounded read")
        return fd, bytes(payload), identity
    except Exception:
        os.close(fd)
        raise


def _recheck_manifest_file(
    outputs_fd: int,
    path: str,
    expected: Mapping[str, Any],
    identity: tuple[int, int, int, int, int, int],
) -> None:
    fd, observed_identity = _open_root_output(outputs_fd, path)
    try:
        max_bytes = (
            runparts.MAX_RUNPARTS_BYTES if path == "RunPARTs.csv"
            else partout.MAX_PARTOUT_TOTAL_BYTES
        )
        _require(
            observed_identity == identity
            and observed_identity[2] == expected["bytes"]
            and observed_identity[2] <= max_bytes,
            f"{path} identity/size differs before final bounded hash",
        )
        digest = hashlib.sha256()
        offset = 0
        while offset < expected["bytes"]:
            block = os.pread(fd, min(1024 * 1024, expected["bytes"] - offset), offset)
            _require(bool(block), f"{path} was truncated during final identity verification")
            digest.update(block)
            offset += len(block)
        _require(
            _file_identity(fd) == identity
            and os.fstat(fd).st_size == expected["bytes"]
            and digest.hexdigest() == expected["sha256"],
            f"{path} no longer resolves to the exact scanned C-manifest inode/bytes",
        )
    finally:
        os.close(fd)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuxiliaryOutputInventoryError(message)


def _directory_identity(fd: int) -> tuple[int, int, int, int, int, int]:
    observed = os.fstat(fd)
    _require(stat.S_ISDIR(observed.st_mode), "held bundle/output root is not a directory")
    return (
        observed.st_dev, observed.st_ino, observed.st_size,
        observed.st_mtime_ns, observed.st_ctime_ns, observed.st_nlink,
    )


def _file_identity(fd: int) -> tuple[int, int, int, int, int, int]:
    observed = os.fstat(fd)
    _require(stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1,
             "bound auxiliary output must be a single-link regular file")
    return (
        observed.st_dev, observed.st_ino, observed.st_size,
        observed.st_mtime_ns, observed.st_ctime_ns, observed.st_nlink,
    )


def _verify_stages(
    roots: Mapping[str, str],
    root_fds: Mapping[str, int],
    output_fds: Mapping[str, int],
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    checked: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        result = bundle.verify_stage_bundle(
            roots[stage], stage,
            trusted_authorization_bytes=trusted_authorization_bytes[stage],
            trusted_authorization_sha256=trusted_authorization_sha256[stage],
            expected_authorization_envelope=expected_authorization_envelopes[stage],
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


def _bind_c_to_b(checked: Mapping[str, Mapping[str, Any]]) -> None:
    b_result = checked["B"]
    c_result = checked["C"]
    _require(b_result["case_id"] == c_result["case_id"],
             "B and C bundles refer to different qualification cases")
    _require(b_result["case_is_frozen_qualification_only"] is True
             and c_result["case_is_frozen_qualification_only"] is True,
             "B/C bundle pair is not one frozen qualification-only case")
    try:
        bundle._binding_matches(
            c_result["_receipt_document"].get("materialization_receipt_binding"),
            b_result["receipt_path"], b_result["_receipt_bytes"], "C-to-B materialization receipt",
        )
    except bundle.BundleVerificationError as error:
        raise AuxiliaryOutputInventoryError(str(error)) from error


def _case_boundary_populations(b_result: Mapping[str, Any]) -> tuple[int, int]:
    counts = b_result.get("particle_group_counts")
    _require(isinstance(counts, dict)
             and set(counts) == {"fixed", "moving", "floating", "fluid"},
             "verified B materialization does not expose exact particle cohorts")
    for name, count in counts.items():
        _require(type(count) is int and count >= 0,
                 f"verified B {name} population is not a nonnegative integer")
    case_nbound = counts["fixed"] + counts["moving"] + counts["floating"]
    case_nfloat = counts["floating"]
    return case_nbound, case_nfloat


def _one_native_integer(item: decoder.ItemRecord, name: str, type_code: int) -> int:
    matches = [value for value in item.values if value.name == name]
    _require(len(matches) == 1 and matches[0].type_code == type_code
             and type(matches[0].value) is int and matches[0].value >= 0,
             f"native {item.name}.{name} must be one unique unsigned integer value")
    return matches[0].value


def _raw_frame_identity(
    c_outputs_fd: int,
    frame: Mapping[str, Any],
    *,
    expected_part: int,
    expected_group_counts: Mapping[str, int],
) -> tuple[str, int, tuple[int, int, int, int, int]]:
    raw_fd = decoder.open_regular_beneath(c_outputs_fd, frame["path"])
    try:
        scan = decoder.scan_bi4_fd(raw_fd, frame["sha256"])
        _require(scan.input_bytes == frame["bytes"],
                 "PartExtra peer frame byte length differs from the C manifest")
        root = scan.root
        _require(root.name == "JPartDataBi4" and len(root.children) == 1,
                 "PartExtra peer frame does not have one native JPartDataBi4 PART")
        part = root.children[0]
        _require(part.name == f"PART_{expected_part:04d}",
                 "PartExtra peer frame PART item does not match its ordinal")
        native_count_names = {
            "case_np": "CaseNp", "fluid": "CaseNfluid", "fixed": "CaseNfixed",
            "moving": "CaseNmoving", "floating": "CaseNfloat",
        }
        native_counts: dict[str, int] = {}
        for key, name in native_count_names.items():
            native_counts[key] = _one_native_integer(root, name, 10)
        _require(native_counts["case_np"] == sum(expected_group_counts.values())
                 and {name: native_counts[name] for name in expected_group_counts}
                 == dict(expected_group_counts),
                 "PartExtra peer frame particle populations differ from verified B cohorts")
        native_identity = {
            name: _one_native_integer(part, name, 8)
            for name in ("Cpart", "Step")
        }
        _require(native_identity["Cpart"] == expected_part,
                 "PartExtra peer frame native Cpart differs from its filename ordinal")
        matches = [value for value in part.values if value.name == "TimeStep"]
        _require(len(matches) == 1 and matches[0].type_code == 12,
                 "PartExtra peer frame lacks one binary64 TimeStep")
        value = float(matches[0].value)
        _require(math.isfinite(value), "PartExtra peer frame TimeStep is non-finite")
        observed_bits = struct.pack("<d", value).hex()
        expected_value = float.fromhex(frame["expected_time_s_ieee754_hex"])
        _require(math.isfinite(expected_value)
                 and observed_bits == struct.pack("<d", expected_value).hex(),
                 "PartExtra peer frame TimeStep differs from the frozen C output axis")
        return observed_bits, native_identity["Step"], scan.input_identity
    finally:
        os.close(raw_fd)


def _classify_other_file(path: str) -> tuple[str, str]:
    basename = path.rsplit("/", 1)[-1]
    if "/" not in path and basename in KNOWN_UNSCANNED_ROOT_NAMES:
        return "known_auxiliary_not_finite_scanned", (
            "recognized native auxiliary format; its numeric payload is outside current scans"
        )
    return "unclassified_output", "no frozen output-class parser is registered for this path"


def inventory_c_outputs_with_part_extra(
    bundle_roots: Mapping[str, Path | str],
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify a read-only B/C bundle pair and scan bound auxiliary outputs.

    Trust inputs must come from a caller-controlled authorization store. The
    returned record is diagnostic only: it never writes into either bundle,
    starts a worker/native executable, closes output-mode expectations, or
    grants qualification credit.
    """
    _require(set(bundle_roots) == set(STAGES)
             and set(trusted_authorization_bytes) == set(STAGES)
             and set(trusted_authorization_sha256) == set(STAGES)
             and set(expected_authorization_envelopes) == set(STAGES),
             "auxiliary inventory requires exact B/C roots and authorization bindings")
    roots: dict[str, str] = {}
    root_fds: dict[str, int] = {}
    output_fds: dict[str, int] = {}
    auxiliary_input_fds: list[int] = []
    try:
        for stage in STAGES:
            root_fd, absolute = bundle._open_absolute_directory(bundle_roots[stage])
            roots[stage] = absolute
            root_fds[stage] = root_fd
        _require(len({(os.fstat(root_fds[stage]).st_dev, os.fstat(root_fds[stage]).st_ino)
                      for stage in STAGES}) == len(STAGES),
                 "B and C bundle roots are not distinct directory objects")
        for stage in STAGES:
            output_fds[stage] = bundle._open_child_directory(root_fds[stage], "outputs")

        before_root_ids = {stage: _directory_identity(root_fds[stage]) for stage in STAGES}
        before_output_ids = {stage: _directory_identity(output_fds[stage]) for stage in STAGES}
        checked_before = _verify_stages(
            roots, root_fds, output_fds,
            trusted_authorization_bytes=trusted_authorization_bytes,
            trusted_authorization_sha256=trusted_authorization_sha256,
            expected_authorization_envelopes=expected_authorization_envelopes,
        )
        _bind_c_to_b(checked_before)
        case_nbound, case_nfloat = _case_boundary_populations(checked_before["B"])
        case_np = sum(checked_before["B"]["particle_group_counts"].values())

        c_files = checked_before["C"]["_output_file_manifest"]
        c_manifest = checked_before["C"]["_manifest_document"]
        frames = c_manifest.get("frames")
        _require(isinstance(frames, list) and len(frames) == checked_before["C"]["expected_frame_count"],
                 "verified C manifest lacks its complete primary frame axis")
        frame_by_part: dict[int, Mapping[str, Any]] = {}
        frame_paths: set[str] = set()
        for ordinal, frame in enumerate(frames):
            _require(isinstance(frame, dict) and frame.get("ordinal") == ordinal,
                     "verified C frame axis is not in exact ordinal order")
            match = PRIMARY_FRAME_PATH.fullmatch(frame.get("path", ""))
            _require(match is not None and int(match.group(1)) == ordinal,
                     "verified C primary frame filename does not encode its ordinal")
            _require(frame["path"] in c_files and frame["path"] not in frame_paths,
                     "verified C primary frame is absent from or duplicated in the closed file manifest")
            frame_paths.add(frame["path"])
            frame_by_part[ordinal] = frame

        classifications: list[dict[str, Any]] = []
        part_extra_records: list[dict[str, Any]] = []
        known_unscanned_paths: list[str] = []
        unclassified_paths: list[str] = []
        part_numbers: set[int] = set()
        held_primary_frame_identities: dict[str, tuple[int, int, int, int, int]] = {}
        held_part_extra_identities: dict[str, tuple[int, int, int, int, int, int]] = {}
        held_auxiliary_input_identities: dict[str, tuple[int, int, int, int, int, int]] = {}
        runparts_payload = b""
        partout_sources: list[partout.PartOutSource] = []
        partout_total_bytes = 0
        classification_by_path: dict[str, dict[str, Any]] = {}

        for path in sorted(c_files):
            binding = c_files[path]
            if path in frame_paths:
                classifications.append({
                    "path": path,
                    "bytes": binding["bytes"],
                    "sha256": binding["sha256"],
                    "classification": "primary_native_frame",
                    "finite_scan": "not_scanned_by_this_auxiliary_inventory",
                })
                continue

            basename = path.rsplit("/", 1)[-1]
            part_match = PART_EXTRA_NAME.fullmatch(basename) if "/" not in path else None
            if part_match is not None:
                part_number = int(part_match.group(1))
                _require(part_number > 0 and part_number not in part_numbers,
                         "PartExtra part numbers must be positive and unique")
                part_numbers.add(part_number)
                peer = frame_by_part.get(part_number)
                _require(peer is not None,
                         f"PartExtra part {part_number} has no same-ordinal C primary frame")
                fd = decoder.open_regular_beneath(output_fds["C"], path)
                try:
                    identity_before = _file_identity(fd)
                    try:
                        diagnostic = part_extra.summarize_part_extra_fd(
                            fd, binding["sha256"],
                            expected_part=part_number,
                            expected_case_nbound=case_nbound,
                            expected_case_nfloat=case_nfloat,
                        )
                    except part_extra.PartExtraFiniteInventoryError as error:
                        raise AuxiliaryOutputInventoryError(
                            f"PartExtra {path} failed its bound finite inventory: {error}"
                        ) from error
                    identity_after = _file_identity(fd)
                    _require(identity_after == identity_before,
                             f"held {path} identity changed during its finite scan")
                    _require(diagnostic["source_part_extra_bytes"] == binding["bytes"]
                             and diagnostic["source_part_extra_sha256"] == binding["sha256"],
                             f"held {path} differs from its exact C output-manifest binding")
                    frame_time_bits, frame_step, frame_identity = _raw_frame_identity(
                        output_fds["C"], peer,
                        expected_part=part_number,
                        expected_group_counts=checked_before["B"]["particle_group_counts"],
                    )
                    _require(diagnostic["metadata"]["time_step_raw_bits_le_hex"] == frame_time_bits,
                             f"{path} TimeStep differs from its same-part C primary frame")
                    _require(diagnostic["metadata"]["step"] == frame_step,
                             f"{path} Step differs from its same-part C primary frame")
                    held_primary_frame_identities[peer["path"]] = frame_identity
                    held_part_extra_identities[path] = identity_after
                finally:
                    os.close(fd)
                part_extra_records.append({
                    "path": path,
                    "primary_frame_path": peer["path"],
                    "part_extra": diagnostic,
                })
                classifications.append({
                    "path": path,
                    "bytes": binding["bytes"],
                    "sha256": binding["sha256"],
                    "classification": "part_extra_normals_finite_scanned",
                    "finite_scan_status": diagnostic["floating_value_inventory"][
                        "all_floating_values_finite"
                    ],
                })
                continue

            if "/" not in path and basename == "RunPARTs.csv":
                fd, payload, identity = _open_and_read_runparts(
                    output_fds["C"], path, binding,
                )
                auxiliary_input_fds.append(fd)
                held_auxiliary_input_identities[path] = identity
                runparts_payload = payload
                entry = {
                    "path": path,
                    "bytes": binding["bytes"],
                    "sha256": binding["sha256"],
                    "classification": "runparts_pending_partout_diagnostic",
                }
                classifications.append(entry)
                classification_by_path[path] = entry
                continue

            if "/" not in path and PART_OUT_NAME.fullmatch(basename):
                _require(len(partout_sources) < partout.MAX_PARTOUT_BLOCKS,
                         "manifest-bound PartOut file count exceeds the diagnostic cap")
                fd, identity = _open_root_output(output_fds["C"], path)
                auxiliary_input_fds.append(fd)
                partout_total_bytes += identity[2]
                _require(partout_total_bytes <= partout.MAX_PARTOUT_TOTAL_BYTES,
                         f"manifest-bound {path} exceeds the PartOut diagnostic aggregate cap")
                held_auxiliary_input_identities[path] = identity
                partout_sources.append(partout.PartOutSource(
                    filename=basename, fd=fd, expected_sha256=binding["sha256"],
                ))
                entry = {
                    "path": path,
                    "bytes": binding["bytes"],
                    "sha256": binding["sha256"],
                    "classification": "partout_pending_runparts_join",
                }
                classifications.append(entry)
                classification_by_path[path] = entry
                continue

            classification, reason = _classify_other_file(path)
            entry = {
                "path": path,
                "bytes": binding["bytes"],
                "sha256": binding["sha256"],
                "classification": classification,
                "reason": reason,
            }
            classifications.append(entry)
            classification_by_path[path] = entry
            if classification == "known_auxiliary_not_finite_scanned":
                known_unscanned_paths.append(path)
            else:
                unclassified_paths.append(path)

        expected_part_time_hex: dict[int, str] = {}
        expected_part_time_reference_requested = False
        if runparts_payload and partout_sources:
            try:
                _parsed_runparts, runparts_rows = partout._parse_runparts(runparts_payload)
            except partout.PartOutDiagnosticError:
                runparts_rows = []
            event_parts = {row["Part"] for row in runparts_rows if row["NpOut"] > 0}
            expected_part_time_reference_requested = bool(event_parts)
            for part_number in sorted(event_parts):
                peer = frame_by_part.get(part_number)
                if peer is None:
                    continue
                observed_bits, _frame_step, frame_identity = _raw_frame_identity(
                    output_fds["C"], peer,
                    expected_part=part_number,
                    expected_group_counts=checked_before["B"]["particle_group_counts"],
                )
                frame_time = float.fromhex(peer["expected_time_s_ieee754_hex"])
                _require(observed_bits == struct.pack("<d", frame_time).hex(),
                         f"C frame PART {part_number} raw time differs from the frozen frame axis")
                expected_part_time_hex[part_number] = frame_time.hex()
                held_primary_frame_identities[peer["path"]] = frame_identity
        partout_diagnostic = partout.diagnose(
            runparts_payload, tuple(partout_sources), expected_pos_double=None,
            expected_case_np=case_np,
            expected_part_time_s_ieee754_hex=(
                expected_part_time_hex if expected_part_time_reference_requested else None
            ),
        )
        if runparts_payload:
            for path, entry in classification_by_path.items():
                if path == "RunPARTs.csv":
                    runparts_scan = partout_diagnostic.get("runparts_input", {})
                    if runparts_scan.get("all_26_numeric_fields_finite") is True:
                        entry["classification"] = "runparts_numeric_fields_scanned"
                    else:
                        entry["classification"] = "runparts_parse_incomplete"
                        known_unscanned_paths.append(path)
        for source in partout_sources:
            path = source.filename
            entry = classification_by_path[path]
            if partout_diagnostic.get("status") == "diagnostic_only_consistent_inputs_gate_open":
                entry["classification"] = "partout_structure_and_float_values_scanned"
                entry["finite_scan_status"] = partout_diagnostic[
                    "partout_float_value_inventory"
                ]["all_observed_floating_values_finite"]
            else:
                entry["classification"] = "partout_diagnostic_incomplete"
                entry["reason"] = "RunPARTs/PartOut structural join did not close"
                known_unscanned_paths.append(path)

        checked_after = _verify_stages(
            roots, root_fds, output_fds,
            trusted_authorization_bytes=trusted_authorization_bytes,
            trusted_authorization_sha256=trusted_authorization_sha256,
            expected_authorization_envelopes=expected_authorization_envelopes,
        )
        _bind_c_to_b(checked_after)
        for stage in STAGES:
            _require(checked_after[stage]["receipt_sha256"] == checked_before[stage]["receipt_sha256"]
                     and checked_after[stage]["manifest_sha256"] == checked_before[stage]["manifest_sha256"],
                     f"{stage} receipt or output manifest changed during auxiliary scan")
            _require(checked_after[stage]["_receipt_bytes"] == checked_before[stage]["_receipt_bytes"]
                     and checked_after[stage]["_manifest_document"] == checked_before[stage]["_manifest_document"],
                     f"{stage} bound receipt or manifest document changed during auxiliary scan")
            _require(_directory_identity(root_fds[stage]) == before_root_ids[stage]
                     and _directory_identity(output_fds[stage]) == before_output_ids[stage],
                     f"{stage} held bundle/output directory changed during auxiliary scan")
            reopened_fd, reopened_path = bundle._open_absolute_directory(roots[stage])
            try:
                held_stat = os.fstat(root_fds[stage])
                reopened_stat = os.fstat(reopened_fd)
                _require(reopened_path == roots[stage]
                         and (held_stat.st_dev, held_stat.st_ino)
                         == (reopened_stat.st_dev, reopened_stat.st_ino),
                         f"{stage} bundle path no longer resolves to its held directory")
            finally:
                os.close(reopened_fd)

        for path, identity in held_part_extra_identities.items():
            reopened_fd = decoder.open_regular_beneath(output_fds["C"], path)
            try:
                _require(_file_identity(reopened_fd) == identity
                         and decoder._hash_fd(reopened_fd, identity[2])
                         == c_files[path]["sha256"],
                         f"{path} no longer resolves to the exact scanned PartExtra inode/bytes")
            finally:
                os.close(reopened_fd)

        for path, identity in held_primary_frame_identities.items():
            reopened_fd = decoder.open_regular_beneath(output_fds["C"], path)
            try:
                observed_stat = decoder._check_input_stat(reopened_fd)
                _require(decoder._identity(observed_stat) == identity
                         and observed_stat.st_size == c_files[path]["bytes"]
                         and decoder._hash_fd(reopened_fd, observed_stat.st_size)
                         == c_files[path]["sha256"],
                         f"{path} no longer resolves to the exact scanned peer-frame inode/bytes")
            finally:
                os.close(reopened_fd)

        for path, identity in held_auxiliary_input_identities.items():
            _recheck_manifest_file(
                output_fds["C"], path, c_files[path], identity,
            )

        unknown_presence = not part_extra_records
        return {
            "schema": SCHEMA,
            "status": STATUS,
            "scope_id": bundle.SCOPE_ID,
            "case_id": checked_before["B"]["case_id"],
            "stage_statuses": {stage: "passed" for stage in STAGES},
            "bundle_receipt_bindings": {
                stage: {
                    "receipt_sha256": checked_before[stage]["receipt_sha256"],
                    "output_manifest_sha256": checked_before[stage]["manifest_sha256"],
                }
                for stage in STAGES
            },
            "verified_case_populations": {
                "case_np": case_np,
                "case_nbound": case_nbound,
                "case_nfloat": case_nfloat,
                "derived_from": "B generated XML and initial BI4 particle cohorts",
            },
            "c_output_tree_closed": True,
            "c_manifest_file_count": len(c_files),
            "primary_frame_count": len(frame_paths),
            "output_classifications": classifications,
            "part_extra_records": part_extra_records,
            "partout_runparts_diagnostic": partout_diagnostic,
            "runparts_presence": (
                "manifest_member_scanned_and_bound" if "RunPARTs.csv" in classification_by_path
                else "no_manifest_member_observed_expectation_unknown"
            ),
            "partout_presence": (
                "one_or_more_manifest_members_scanned_or_classified_incomplete"
                if partout_sources else "no_manifest_member_observed_expectation_unknown"
            ),
            "part_extra_presence": (
                "no_manifest_member_observed_expectation_unknown" if unknown_presence
                else "one_or_more_manifest_members_scanned"
            ),
            "part_extra_presence_expectation_resolved": False,
            "part_extra_observed_all_floating_values_finite": (
                all(record["part_extra"]["floating_value_inventory"][
                    "all_floating_values_finite"
                ] for record in part_extra_records) if part_extra_records else None
            ),
            "known_but_unscanned_auxiliary_paths": sorted(set(known_unscanned_paths)),
            "unclassified_output_paths": sorted(set(unclassified_paths)),
            "all_present_output_paths_have_known_class": not unclassified_paths,
            "all_native_auxiliary_float_sources_scanned": False,
            "native_integrity_evaluated": False,
            "T1_numerical": False,
            "readiness_pass": False,
            "qualification_credit": 0,
        }
    except AuxiliaryOutputInventoryError:
        raise
    except (OSError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise AuxiliaryOutputInventoryError(
            "F8 R008 auxiliary output inventory failed closed"
        ) from error
    finally:
        for fd in output_fds.values():
            os.close(fd)
        for fd in auxiliary_input_fds:
            os.close(fd)
        for fd in root_fds.values():
            os.close(fd)


__all__ = [
    "AuxiliaryOutputInventoryError", "SCHEMA", "STATUS",
    "inventory_c_outputs_with_part_extra",
]
