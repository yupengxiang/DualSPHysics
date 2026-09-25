"""Post-run, single-case bridge from a verified R008 table to a Core trajectory.

This additive bridge composes the reviewed v2 B/C/D table-and-metric verifier
with the qualification-only Core trajectory adapter.  It accepts completed
bundle roots only: it has no solver, GenCase, native-decoder, worker-launch,
GPU, queue, registry, ledger, or receipt-writing path.  The caller-supplied
output directory FD is consumed and closed before this function returns.

The returned artifact remains diagnostic qualification data.  This module
does not authenticate external authorization, a supervisor, or loaded Python
module identity and never awards native-integrity, T1, readiness, or credit.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from typing import Any, Mapping

from scripts import f8_r008_core_trajectory_adapter_v1 as trajectory_adapter
from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as table_bundle
from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_bundle
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_native_integrity_registry_v1 as registry
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_postrun_case_worker.v1"
STAGES = ("B", "C", "D")


class PostrunCaseWorkerError(ValueError):
    """The diagnostic post-run artifacts are not closed over one R008 case."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PostrunCaseWorkerError(message)


def _copy_exact_mapping(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping) and set(value) == keys,
             f"{label} must contain exactly {sorted(keys)}")
    return {key: value[key] for key in keys}


def _sha256_fd(fd: int, expected_bytes: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < expected_bytes:
        block = os.pread(fd, min(1024 * 1024, expected_bytes - offset), offset)
        _require(bool(block), "trajectory artifact was truncated while hashing")
        digest.update(block)
        offset += len(block)
    _require(os.pread(fd, 1, expected_bytes) == b"",
             "trajectory artifact grew while hashing")
    return digest.hexdigest()


def _validate_output_directory_fd(directory_fd: int) -> None:
    _require(type(directory_fd) is int and directory_fd >= 0,
             "output directory FD must be a nonnegative builtin integer")
    try:
        info = os.fstat(directory_fd)
        flags = fcntl.fcntl(directory_fd, fcntl.F_GETFL)
        descriptor_flags = fcntl.fcntl(directory_fd, fcntl.F_GETFD)
    except OSError as error:
        raise PostrunCaseWorkerError("output directory FD is not open") from error
    _require(stat.S_ISDIR(info.st_mode)
             and info.st_uid == os.geteuid()
             and not (info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
             "output directory must be current-user-owned and not group/world-writable")
    _require(flags & os.O_ACCMODE == os.O_RDONLY
             and descriptor_flags & fcntl.FD_CLOEXEC,
             "output directory FD must be read-only and close-on-exec")
    _require(all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY")),
             "platform lacks required no-follow/close-on-exec directory primitives")


def _require_output_absent(directory_fd: int) -> None:
    try:
        os.stat(trajectory_adapter.OUTPUT_FILENAME,
                dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise FileExistsError(trajectory_adapter.OUTPUT_FILENAME)


def _verify_v2_result(result: Any, case_id: str) -> dict[str, Any]:
    required_false = (
        "loaded_module_code_identity_verified", "native_integrity_evaluated",
        "readiness_pass", "T1_numerical",
    )
    _require(isinstance(result, dict)
             and result.get("schema") == metric_bundle.SCHEMA
             and result.get("case_id") == case_id
             and result.get("provenance_chain_references_closed") is True
             and result.get("metrics_evaluated") is True
             and result.get("qualification_credit") == 0
             and all(result.get(name) is False for name in required_false)
             and result.get("authorization_authenticity") == "external_gate_not_checked_here",
             "v2 verifier result is incomplete or overstates authentication/qualification")
    references = {}
    for name in ("receipt_sha256", "manifest_sha256"):
        values = result.get(name)
        _require(isinstance(values, dict) and set(values) == set(STAGES)
                 and all(isinstance(values[stage], str)
                         and len(values[stage]) == 64
                         and all(c in "0123456789abcdef" for c in values[stage])
                         for stage in STAGES),
                 f"v2 verifier {name} is not an exact B/C/D reference map")
        references[name] = dict(values)
    table = result.get("native_fluid_table")
    _require(isinstance(table, dict)
             and table.get("schema") == table_v2.SCHEMA
             and table.get("case_id") == case_id
             and type(table.get("table_bytes")) is int and table["table_bytes"] > 0
             and isinstance(table.get("table_sha256"), str)
             and len(table["table_sha256"]) == 64
             and all(c in "0123456789abcdef" for c in table["table_sha256"])
             and table.get("native_integrity_evaluated") is False
             and table.get("T1_numerical") is False
             and table.get("qualification_credit") == 0,
             "v2 verifier native-table result is malformed or qualification-positive")
    metrics = result.get("case_metrics")
    _require(isinstance(metrics, dict)
             and metrics.get("case_id") == case_id
             and metrics.get("native_integrity_gates_evaluated") is False
             and metrics.get("full_t1_decision") is False
             and metrics.get("qualification_credit") == 0,
             "v2 case metrics are malformed or qualification-positive")
    return {"references": references, "table": table, "metrics": metrics}


def _verify_stages(
    roots: Mapping[str, Any],
    *,
    auth_bytes: Mapping[str, Any],
    auth_sha256: Mapping[str, Any],
    envelopes: Mapping[str, Any],
    code_review_bytes: bytes,
    runtime_assumption: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    checked: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        result = bundle.verify_stage_bundle(
            roots[stage], stage,
            trusted_authorization_bytes=auth_bytes[stage],
            trusted_authorization_sha256=auth_sha256[stage],
            expected_authorization_envelope=envelopes[stage],
            trusted_code_review_receipt_bytes=(code_review_bytes if stage == "D" else None),
            trusted_runtime_assumption=(runtime_assumption if stage == "D" else None),
        )
        _require(result.get("status") == "passed",
                 f"{stage} stage is no longer in the v2-passed state")
        checked[stage] = result
    _require({checked[stage].get("case_id") for stage in STAGES} ==
             {checked["B"].get("case_id")},
             "B/C/D stage case identities differ")
    return checked


def _check_stage_refs(checked: Mapping[str, Mapping[str, Any]],
                      v2_refs: Mapping[str, Mapping[str, str]],
                      case_id: str) -> None:
    _require(all(checked[stage].get("case_id") == case_id for stage in STAGES),
             "held B/C/D stage roots do not match the requested frozen case")
    for reference_name, field_name in (("receipt_sha256", "receipt_sha256"),
                                       ("manifest_sha256", "manifest_sha256")):
        observed = {stage: checked[stage].get(field_name) for stage in STAGES}
        _require(observed == v2_refs[reference_name],
                 f"held B/C/D {reference_name} differ from full v2 verification")


def _open_final_artifact(directory_fd: int, expected: Mapping[str, Any]) -> tuple[int, os.stat_result]:
    name = trajectory_adapter.OUTPUT_FILENAME
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                 and (info.st_dev, info.st_ino, info.st_size)
                 == (named.st_dev, named.st_ino, named.st_size)
                 and info.st_size == expected.get("bytes")
                 and _sha256_fd(fd, info.st_size) == expected.get("sha256"),
                 "final trajectory path is not the exact adapter-created inode/SHA")
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def materialize_postrun_case_worker_v1(
    bundle_roots: Mapping[str, str | os.PathLike[str]],
    *,
    case_id: str,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
    trusted_table_review_receipt_bytes: bytes,
    trusted_table_review_receipt_sha256: str,
    trusted_metric_review_receipt_bytes: bytes,
    trusted_metric_review_receipt_sha256: str,
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
    output_directory_fd: int,
) -> dict[str, Any]:
    """Verify one completed R008 B/C/D chain and publish its diagnostic Core trajectory.

    ``output_directory_fd`` ownership transfers to this function and it is
    closed in ``finally`` on both success and failure.  The only published
    filename is the Core adapter's fixed no-replace output name.  If the
    post-materialization chain check fails, the artifact is retained for
    diagnosis: unlink-by-name cannot atomically prove an inode identity, so
    deleting it here could remove a concurrently substituted file.
    """
    owns_directory_fd = type(output_directory_fd) is int and output_directory_fd >= 0
    directory_fd = output_directory_fd
    stage_roots: dict[str, int] = {}
    stage_outputs: dict[str, int] = {}
    lab_fd: int | None = None
    table_fd: int | None = None
    artifact_fd: int | None = None
    artifact_info: os.stat_result | None = None
    artifact_binding: dict[str, Any] | None = None
    try:
        _require(type(case_id) is str and case_id in set(registry.frozen_qualification_case_ids()),
                 "case_id is outside the frozen R008 qualification denominator")
        _validate_output_directory_fd(directory_fd)
        _require_output_absent(directory_fd)

        roots = _copy_exact_mapping(bundle_roots, set(STAGES), "bundle_roots")
        _require(all(isinstance(path, (str, os.PathLike)) for path in roots.values()),
                 "each B/C/D bundle root must be an absolute path-like value")
        auth_bytes = _copy_exact_mapping(trusted_authorization_bytes, set(STAGES),
                                         "trusted_authorization_bytes")
        auth_sha256 = _copy_exact_mapping(trusted_authorization_sha256, set(STAGES),
                                          "trusted_authorization_sha256")
        envelopes_raw = _copy_exact_mapping(expected_authorization_envelopes, set(STAGES),
                                            "expected_authorization_envelopes")
        envelopes = {
            stage: dict(envelopes_raw[stage])
            if isinstance(envelopes_raw[stage], Mapping) else envelopes_raw[stage]
            for stage in STAGES
        }
        _require(isinstance(trusted_table_review_receipt_bytes, bytes)
                 and isinstance(trusted_metric_review_receipt_bytes, bytes)
                 and isinstance(trusted_code_review_receipt_bytes, bytes)
                 and isinstance(trusted_runtime_assumption, Mapping),
                 "review receipts must be bytes and runtime assumption a mapping")
        runtime_assumption = dict(trusted_runtime_assumption)

        verifier_inputs = {
            "trusted_authorization_bytes": auth_bytes,
            "trusted_authorization_sha256": auth_sha256,
            "expected_authorization_envelopes": envelopes,
            "trusted_table_review_receipt_bytes": trusted_table_review_receipt_bytes,
            "trusted_table_review_receipt_sha256": trusted_table_review_receipt_sha256,
            "trusted_metric_review_receipt_bytes": trusted_metric_review_receipt_bytes,
            "trusted_metric_review_receipt_sha256": trusted_metric_review_receipt_sha256,
            "trusted_code_review_receipt_bytes": trusted_code_review_receipt_bytes,
            "trusted_runtime_assumption": runtime_assumption,
        }
        before_raw = metric_bundle.verify_native_fluid_table_chain_and_metrics(
            roots, **verifier_inputs,
        )
        before = _verify_v2_result(before_raw, case_id)

        checked = _verify_stages(
            roots, auth_bytes=auth_bytes, auth_sha256=auth_sha256,
            envelopes=envelopes,
            code_review_bytes=trusted_code_review_receipt_bytes,
            runtime_assumption=runtime_assumption,
        )
        _check_stage_refs(checked, before["references"], case_id)
        stage_roots, stage_outputs = table_bundle._open_stage_outputs(checked)

        lab_fd, _lab_path = bundle._open_absolute_directory(bundle.LAB)
        table_review_binding = table_bundle._validate_table_review_document(
            trusted_table_review_receipt_bytes,
            trusted_table_review_receipt_sha256,
        )
        metric_review_bindings = metric_bundle._validate_metric_review_document(
            trusted_metric_review_receipt_bytes,
            trusted_metric_review_receipt_sha256,
        )
        table_bundle._verify_table_review_source(table_review_binding, lab_fd)
        metric_bundle._verify_metric_review_sources(metric_review_bindings, lab_fd)

        frozen_row = bundle._frozen_qualification_row(case_id)
        b_receipt = checked["B"]["_receipt_document"]
        definition_binding = table_bundle._check_frozen_source_binding(
            b_receipt, frozen_row, "definition", lab_fd,
        )
        table_bundle._check_frozen_source_binding(
            b_receipt, frozen_row, "control", lab_fd,
        )
        parameter_contract = bundle._stable_read_beneath(
            lab_fd, table_bundle.PARAMETER_CONTRACT_RELATIVE, bundle.MAX_RECEIPT_BYTES,
        )
        _require(hashlib.sha256(parameter_contract).hexdigest()
                 == table_bundle.PARAMETER_CONTRACT_SHA256,
                 "frozen F8 parameter contract differs from its pinned SHA-256")

        cohorts, mass_bits_hex = bundle._verify_b_materialization_semantics(
            stage_outputs["B"], checked["B"]["_output_file_manifest"], b_receipt,
        )
        fluid_ids = table_bundle._fluid_ids_from_cohorts(cohorts)
        _require(isinstance(mass_bits_hex, str)
                 and bool(table_bundle.HEX16.fullmatch(mass_bits_hex)),
                 "B initial MassFluid is not exact canonical binary64 hexadecimal")
        initial_mass_bits = bytes.fromhex(mass_bits_hex)
        c_manifest = checked["C"].get("_manifest_document")
        c_frames = c_manifest.get("frames") if isinstance(c_manifest, dict) else None
        frozen_axis = bundle.expected_time_axis_hex(frozen_row)
        _require(isinstance(c_frames, list) and len(c_frames) == len(frozen_axis),
                 "C source-frame manifest does not cover the complete frozen time axis")

        c_manifest_sha256 = checked["C"].get("manifest_sha256")
        expected_attributes = table_v2.expected_root_attributes(
            case_id=case_id,
            generated_xml_sha256=b_receipt["generated_xml_path"]["sha256"],
            definition_sha256=definition_binding["sha256"],
            materialization_receipt_sha256=checked["B"]["receipt_sha256"],
            raw_solver_manifest_sha256=c_manifest_sha256,
            scope_receipt_sha256=bundle.FROZEN_INPUT_SHA256["scope"],
            parameter_contract_sha256=table_bundle.PARAMETER_CONTRACT_SHA256,
        )
        d_receipt = checked["D"]["_receipt_document"]
        table_binding = d_receipt.get("native_fluid_table_binding")
        _require(isinstance(table_binding, dict)
                 and table_binding.get("path") == "outputs/native-fluid-frame-table-v2.h5"
                 and table_binding.get("bytes") == before["table"]["table_bytes"]
                 and table_binding.get("sha256") == before["table"]["table_sha256"],
                 "D table binding differs from the pre-materialization v2 verification")
        table_fd = decoder.open_regular_beneath(
            stage_outputs["D"], table_binding["path"][len("outputs/"):],
        )
        table_stat = os.fstat(table_fd)
        _require(stat.S_ISREG(table_stat.st_mode) and table_stat.st_nlink == 1
                 and table_stat.st_size == table_binding["bytes"]
                 and table_v2._sha256_fd(table_fd, table_binding["bytes"])
                 == table_binding["sha256"],
                 "held D table FD differs from the verified exact D bytes/SHA")

        def source_frames_factory():
            def iterate():
                for ordinal, entry in enumerate(c_frames):
                    _require(isinstance(entry, dict)
                             and entry.get("ordinal") == ordinal
                             and entry.get("expected_time_s_ieee754_hex") == frozen_axis[ordinal],
                             "C raw frame ordinal/time differs from the complete frozen axis")
                    raw_fd = decoder.open_regular_beneath(stage_outputs["C"], entry["path"])
                    try:
                        yield table_v2.read_native_source_frame_fd(
                            raw_fd, entry["sha256"], expected_bytes=entry["bytes"],
                        )
                    finally:
                        os.close(raw_fd)
            return iterate()

        materialized = trajectory_adapter.materialize_diagnostic_core_trajectory_v1_at(
            table_fd, directory_fd,
            case_id=case_id,
            expected_table_bytes=table_binding["bytes"],
            expected_table_sha256=table_binding["sha256"],
            expected_attributes=expected_attributes,
            expected_time_axis_hex=frozen_axis,
            expected_fluid_ids=fluid_ids,
            expected_case_np=cohorts["case_np"],
            initial_massfluid_binary64_le=initial_mass_bits,
            source_frames_factory=source_frames_factory,
        )
        _require(isinstance(materialized, dict)
                 and materialized.get("schema") == trajectory_adapter.SCHEMA
                 and materialized.get("status")
                 == "diagnostic_qualification_trajectory_written_and_reverified"
                 and materialized.get("case_id") == case_id
                 and materialized.get("trajectory_schema")
                 == trajectory_adapter.CORE_TRAJECTORY_SCHEMA
                 and materialized.get("source_table_sha256") == table_binding["sha256"]
                 and materialized.get("split") == "qualification"
                 and materialized.get("source_provenance_authenticated") is False
                 and materialized.get("formal_eligible") is False
                 and materialized.get("full_t1_decision") is False
                 and materialized.get("qualification_credit") == 0,
                 "Core trajectory adapter returned malformed or qualification-positive output")
        trajectory_binding = materialized.get("trajectory_binding")
        _require(isinstance(trajectory_binding, dict)
                 and set(trajectory_binding) == {"path", "bytes", "sha256"}
                 and trajectory_binding.get("path") == trajectory_adapter.OUTPUT_FILENAME
                 and type(trajectory_binding.get("bytes")) is int
                 and trajectory_binding["bytes"] > 0
                 and isinstance(trajectory_binding.get("sha256"), str)
                 and len(trajectory_binding["sha256"]) == 64
                 and all(c in "0123456789abcdef" for c in trajectory_binding["sha256"]),
                 "Core trajectory binding is malformed")
        artifact_binding = dict(trajectory_binding)
        artifact_fd, artifact_info = _open_final_artifact(directory_fd, artifact_binding)
        _require(os.fstat(table_fd).st_size == table_binding["bytes"]
                 and table_v2._sha256_fd(table_fd, table_binding["bytes"])
                 == table_binding["sha256"],
                 "held D table changed after trajectory materialization")

        after_raw = metric_bundle.verify_native_fluid_table_chain_and_metrics(
            roots, **verifier_inputs,
        )
        after = _verify_v2_result(after_raw, case_id)
        _require(after["references"] == before["references"],
                 "B/C/D receipt or manifest references changed after materialization")
        _require(after["table"]["table_bytes"] == before["table"]["table_bytes"]
                 and after["table"]["table_sha256"] == before["table"]["table_sha256"],
                 "D native-fluid table bytes/SHA changed after materialization")
        _require(after["metrics"] == before["metrics"],
                 "v2 case metrics changed across post-materialization revalidation")
        _require(os.fstat(table_fd).st_size == table_binding["bytes"]
                 and table_v2._sha256_fd(table_fd, table_binding["bytes"])
                 == table_binding["sha256"],
                 "held D table bytes/SHA changed during post-materialization revalidation")
        current_artifact_fd, current_artifact_info = _open_final_artifact(
            directory_fd, artifact_binding,
        )
        try:
            _require(artifact_info is not None
                     and (current_artifact_info.st_dev, current_artifact_info.st_ino)
                     == (artifact_info.st_dev, artifact_info.st_ino),
                     "final trajectory path changed inode during post-materialization revalidation")
        finally:
            os.close(current_artifact_fd)

        return {
            "schema": SCHEMA,
            "status": "diagnostic_postrun_trajectory_and_v2_metrics_revalidated",
            "case_id": case_id,
            "trajectory_schema": trajectory_adapter.CORE_TRAJECTORY_SCHEMA,
            "trajectory_binding": artifact_binding,
            "split": "qualification",
            "case_metrics": after["metrics"],
            "metric_gates_passed": after["metrics"]["metric_gates_passed"],
            "provenance_chain_references_closed_before_and_after": True,
            "receipt_sha256": after["references"]["receipt_sha256"],
            "manifest_sha256": after["references"]["manifest_sha256"],
            "native_fluid_table_bytes": after["table"]["table_bytes"],
            "native_fluid_table_sha256": after["table"]["table_sha256"],
            "external_authorization_authenticated": False,
            "supervisor_identity_authenticated": False,
            "loaded_module_code_identity_verified": False,
            "native_integrity_evaluated": False,
            "native_integrity_pass": False,
            "T1_numerical": False,
            "readiness_pass": False,
            "formal_eligible": False,
            "solver_invoked": False,
            "worker_or_scheduler_launch_invoked": False,
            "gpu_or_queue_invoked": False,
            "qualification_credit": 0,
        }
    finally:
        for fd in (artifact_fd, table_fd, lab_fd,
                   *stage_outputs.values(), *stage_roots.values()):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if owns_directory_fd:
            try:
                os.close(directory_fd)
            except OSError:
                pass


__all__ = ["PostrunCaseWorkerError", "SCHEMA", "materialize_postrun_case_worker_v1"]
