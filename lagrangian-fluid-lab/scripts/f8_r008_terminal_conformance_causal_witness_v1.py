#!/usr/bin/env python3
"""Validate one synthetic-only F8/R008 static conformance witness.

This additive contract joins static V17/V18, source, kernel/config, ABI, and
fanotify disposition claims with caller-supplied supervisor and final-fput
diagnostic projections.  It checks only exact declarations and an explicit
causal witness order.  It never authenticates a runtime source, a kernel,
fanotify, a supervisor, an observer, or an authority, and it can never mint
execution/readiness capability.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SCHEMA = "core.cfd.f8.r008_terminal_conformance_causal_witness.v1"
RESULT_SCHEMA = "core.cfd.f8.r008_terminal_conformance_causal_witness_result.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_terminal_conformance_causal_witness_report.v1"
RECORD_ID = "f8-r008-terminal-conformance-causal-witness-v1"
REPORT_RECORD_ID = "f8-r008-terminal-conformance-causal-witness-report-v1"
STATUS = "synthetic_only_static_conformance_witness"
RESULT_STATUS = "synthetic_static_conformance_consistent_untrusted"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
MAX_INPUT_BYTES = 512 * 1024
MAX_TIMELINE_ROWS = 32
MAX_EDGES = 64
MAX_U64 = (1 << 64) - 1

_SHA256 = re.compile(r"^[0-9a-f]{64}\Z", re.ASCII)
_HEX32 = re.compile(r"^[0-9a-f]{32}\Z", re.ASCII)
_HEX64 = re.compile(r"^[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}\Z", re.ASCII)

V17_PATH = "reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V17-2026-09-26.zh-CN.md"
V18_PATH = "reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V18-2026-09-26.zh-CN.md"
PROFILE_MANIFEST_PATH = "reports/F8-R008-TERMINAL-FANOTIFY-PROFILES-V1-2026-09-27.json"
SOURCE_AUDIT_PATH = "reports/F8-R008-FINAL-FPUT-LINUX-V6.8-SOURCE-AUDIT-V1.json"
READINESS_AUDIT_PATH = "reports/F8-R008-READINESS-GAP-AUDIT-2026-09-28.json"
RAW_PARSER_PATH = "scripts/f8_r008_fanotify_raw_parser_v1.py"
FINAL_FPUT_V1_PATH = "scripts/f8_r008_final_fput_join_reducer_v1.py"
FINAL_FPUT_V3_PATH = "scripts/f8_r008_final_fput_join_reducer_v3.py"
SUPERVISOR_CLAIMS_PATH = "scripts/f8_r008_supervisor_session_claims_v1.py"
PROFILE_VERIFIER_PATH = "scripts/f8_r008_terminal_fanotify_profile_verifier_v1.py"

# These are source-artifact bindings, not a claim that the corresponding
# artifact is trusted.  The target kernel/config/ABI values intentionally
# remain unpinned below.
STATIC_BINDINGS = {
    "v17": {"path": V17_PATH, "sha256": "5cf9e082765081582163e4d7f88b7900657c9436c3263b6552be6f4bcf5a6111"},
    "v18": {"path": V18_PATH, "sha256": "7d479bb012c3846eee51e29ed7bd822cde14ff34e225e445d65dd1e62b99c87f"},
    "fanotify_profile_manifest": {"path": PROFILE_MANIFEST_PATH, "sha256": "107111fd2ab5d68645951ef9ff2885825e53f49ebe12d7bf6cdb7358ca95c059"},
    "source_audit": {"path": SOURCE_AUDIT_PATH, "sha256": "54108309dbc78cbbda306439b498321ea295769b56bf3003e99439d55e13e5f9"},
    "readiness_gap_audit": {"path": READINESS_AUDIT_PATH, "sha256": "659e6b7fd340467cd0738fe3f6a18e8db74fd004f6c0560e23b29b362924a514"},
    "fanotify_raw_parser": {"path": RAW_PARSER_PATH, "sha256": "189aa4e7e4590de5e8b4a68d0791ea55a61cff428213ad02e18222bdfcfa1308"},
    "final_fput_reducer_v1": {"path": FINAL_FPUT_V1_PATH, "sha256": "c0dd05a3b66d8e0e502e7812f6dd560dae0ca108677f22cb0525ec572cafb7fd"},
    "final_fput_reducer_v3": {"path": FINAL_FPUT_V3_PATH, "sha256": "80daf381e8f8cb9da095b6967841e1f9b33b150a4b19a4db0b3a930cfc247338"},
    "supervisor_session_claims": {"path": SUPERVISOR_CLAIMS_PATH, "sha256": "c89ab1ce049ca8ff7faf4f2de231c2d91f33637845caccee18583e71be30c8f3"},
    "fanotify_profile_verifier": {"path": PROFILE_VERIFIER_PATH, "sha256": "216260acb8fe5714c3db1cbba157aa824eb951b33763906380e688325d1d2d73"},
}

SOURCE_CLAIMS = {
    "audit_schema": "core.cfd.f8.r008_final_fput_linux_v6_8_source_audit.v1",
    "audit_status": "upstream_static_source_audit_only",
    "repository": "https://github.com/torvalds/linux",
    "tag": "v6.8",
    "tag_object": "90d1f30371ae3337beb01666b226320728d35c70",
    "peeled_commit": "e8f897f4afef0031fe618a8e94127a0934896aba",
    "tag_signature_verified": False,
    "target_kernel_source_pinned": False,
    "direct_close_requires_final_fput_observer": True,
    "close_exit_alone_proves_final_fput": False,
    "fanotify_fid_name_merge_can_or_masks": True,
    "single_bit_parser_rejects_combined_masks": True,
    "fanotify_close_write_mapping": "FAN_CLOSE_WRITE == FS_CLOSE_WRITE",
    "fanotify_close_nowrite_mapping": "FAN_CLOSE_NOWRITE == FS_CLOSE_NOWRITE",
}

KERNEL_CLAIMS = {
    "family": "linux",
    "release": "6.8",
    "arch": "x86_64",
    "source_audit_sha256": STATIC_BINDINGS["source_audit"]["sha256"],
    "source_tag": "v6.8",
    "peeled_commit": "e8f897f4afef0031fe618a8e94127a0934896aba",
    "target_source_pinned": False,
    "target_build_id": None,
    "target_config_sha256": None,
    "config_pinned": False,
    "config_source": "not_supplied",
    "kernel_probe_performed": False,
    "runtime_conformance_verified": False,
}

ABI_CLAIMS = {
    "userspace_abi": "x86-64",
    "audit_arch": "AUDIT_ARCH_X86_64",
    "profile_manifest_sha256": STATIC_BINDINGS["fanotify_profile_manifest"]["sha256"],
    "permission_init_flags_symbolic": [
        "FAN_CLASS_CONTENT", "FAN_REPORT_PIDFD", "FAN_CLOEXEC", "FAN_NONBLOCK",
    ],
    "permission_init_flags_observed_hex": "0x0087",
    "name_init_flags_symbolic": [
        "FAN_CLASS_NOTIF", "FAN_REPORT_PIDFD", "FAN_REPORT_DFID_NAME_TARGET",
        "FAN_CLOEXEC", "FAN_NONBLOCK",
    ],
    "name_init_flags_observed_hex": "0x1e83",
    "event_f_flags_symbolic": ["O_RDONLY", "O_CLOEXEC", "O_LARGEFILE"],
    "event_f_flags_observed_hex": "0x80000",
    "target_abi_raw_values": {
        "permission_init_flags_hex": None,
        "name_init_flags_hex": None,
        "event_f_flags_hex": None,
    },
    "target_abi_raw_values_pinned": False,
    "abi_probe_performed": False,
    "runtime_conformance_verified": False,
    "pidfd_required_for_both_groups": True,
}

PROFILE_CLAIMS = {
    "schema": "core.cfd.f8.r008_terminal_fanotify_profiles.v1",
    "record_id": "f8-r008-terminal-fanotify-profiles-v1",
    "profile_manifest_sha256": STATIC_BINDINGS["fanotify_profile_manifest"]["sha256"],
    "mark_scope": "closed_directory_inode",
    "mark_flags": ["FAN_MARK_ADD", "FAN_MARK_ONLYDIR"],
    "event_on_child": True,
    "on_dir": False,
    "combined_mask_policy": "reject",
    "unknown_mask_policy": "reject",
    "both_groups_capability": {
        "capability": "CAP_SYS_ADMIN",
        "user_namespace": "init_user_ns",
    },
    "capability_probe_performed": False,
    "runtime_profile_conformance_verified": False,
}

EXPECTED_DISPOSITIONS = (
    {
        "group_kind": "permission",
        "event_symbol": "FAN_OPEN_PERM",
        "mask_hex": "0x00010000",
        "disposition": "permission_response_required",
        "metadata_fd_rule": "nonnegative",
        "event_fd_ref_rule": "required",
        "required_info_types": ["PIDFD"],
        "forbidden_info_types": ["FID", "DFID", "DFID_NAME", "DFID_NAME_TARGET"],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
    {
        "group_kind": "permission",
        "event_symbol": "FAN_ACCESS_PERM",
        "mask_hex": "0x00020000",
        "disposition": "permission_response_required",
        "metadata_fd_rule": "nonnegative",
        "event_fd_ref_rule": "required",
        "required_info_types": ["PIDFD"],
        "forbidden_info_types": ["FID", "DFID", "DFID_NAME", "DFID_NAME_TARGET"],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
    {
        "group_kind": "permission",
        "event_symbol": "FAN_OPEN_EXEC_PERM",
        "mask_hex": "0x00040000",
        "disposition": "permission_response_required",
        "metadata_fd_rule": "nonnegative",
        "event_fd_ref_rule": "required",
        "required_info_types": ["PIDFD"],
        "forbidden_info_types": ["FID", "DFID", "DFID_NAME", "DFID_NAME_TARGET"],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
    {
        "group_kind": "name",
        "event_symbol": "FAN_ACCESS",
        "mask_hex": "0x00000001",
        "disposition": "notification_single_bit_observation",
        "metadata_fd_rule": "FAN_NOFD",
        "event_fd_ref_rule": "null",
        "required_info_types": ["PIDFD", "FID", "DFID_NAME"],
        "forbidden_info_types": [],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
    {
        "group_kind": "name",
        "event_symbol": "FAN_MODIFY",
        "mask_hex": "0x00000002",
        "disposition": "notification_single_bit_observation",
        "metadata_fd_rule": "FAN_NOFD",
        "event_fd_ref_rule": "null",
        "required_info_types": ["PIDFD", "FID", "DFID_NAME"],
        "forbidden_info_types": [],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
    {
        "group_kind": "name",
        "event_symbol": "FAN_CLOSE_WRITE",
        "mask_hex": "0x00000008",
        "disposition": "notification_single_bit_close_join_required",
        "metadata_fd_rule": "FAN_NOFD",
        "event_fd_ref_rule": "null",
        "required_info_types": ["PIDFD", "FID", "DFID_NAME"],
        "forbidden_info_types": [],
        "actor_pidfd_required": True,
        "close_join_required": True,
    },
    {
        "group_kind": "name",
        "event_symbol": "FAN_CLOSE_NOWRITE",
        "mask_hex": "0x00000010",
        "disposition": "notification_single_bit_observation",
        "metadata_fd_rule": "FAN_NOFD",
        "event_fd_ref_rule": "null",
        "required_info_types": ["PIDFD", "FID", "DFID_NAME"],
        "forbidden_info_types": [],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
    {
        "group_kind": "name",
        "event_symbol": "FAN_OPEN",
        "mask_hex": "0x00000020",
        "disposition": "notification_single_bit_observation",
        "metadata_fd_rule": "FAN_NOFD",
        "event_fd_ref_rule": "null",
        "required_info_types": ["PIDFD", "FID", "DFID_NAME"],
        "forbidden_info_types": [],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
    {
        "group_kind": "name",
        "event_symbol": "FAN_CREATE",
        "mask_hex": "0x00000100",
        "disposition": "notification_single_bit_observation",
        "metadata_fd_rule": "FAN_NOFD",
        "event_fd_ref_rule": "null",
        "required_info_types": ["PIDFD", "FID", "DFID_NAME"],
        "forbidden_info_types": [],
        "actor_pidfd_required": True,
        "close_join_required": False,
    },
)

TRUST_BOUNDARY = {
    "trusted_authority_present": False,
    "trusted_authority_ref": None,
    "runtime_claim_policy": "reject_without_external_trusted_authority",
    "candidate_claims_accepted_as_runtime": False,
    "runtime_claims": {
        "target_kernel_conformance": False,
        "fanotify_conformance": False,
        "terminal_supervisor_identity": False,
        "final_fput_observation": False,
        "causal_bridge_verified": False,
        "execution_authority": False,
        "readiness_pass": False,
    },
}

SUPERVISOR_PROJECTION_FIELDS = {
    "schema", "status", "projection_source", "attempt_id", "nonce_hex",
    "process_terminal_seq", "ledger_process_generation_id",
    "process_journal_raw_sha256", "c_journal_raw_sha256",
    "candidate_key_is_active", "active_key_registry_verified",
    "trusted_root_capability_present", "supervisor_identity_authenticated",
    "worker_execution_authenticated", "runtime_identity_verified",
    "event_source_completeness_verified", "readiness_pass", "T1_numerical",
    "qualification_credit",
}

FINAL_FPUT_PROJECTION_FIELDS = {
    "schema", "status", "projection_source", "attempt_id", "close_token_ref",
    "object_id", "file_cookie_digest", "observer_event_order",
    "fanotify_name_group_seq_range", "pre_close_barrier_group_seq",
    "post_close_barrier_group_seq", "fanotify_close_write_group_seq",
    "fanotify_raw_bytes_reparsed", "queue_barrier_declared_order_consistent",
    "queue_barrier_source_authenticated", "shared_journal_contract_implemented",
    "final_close_claim", "trusted_observation", "kernel_source_pinned",
    "observer_runtime_authenticated", "close_token_cookie_bridge_authenticated",
    "runtime_observation_authenticated", "readiness_pass", "T1_numerical",
    "execution_authority", "qualification_credit",
}

CAUSAL_FIELDS = {
    "schema", "attempt_id", "nonce_hex", "supervisor_terminal_seq",
    "close_token_ref", "object_id", "file_cookie_digest",
    "pre_close_barrier_group_seq", "fanotify_close_write_group_seq",
    "post_close_barrier_group_seq", "witness_origin", "trusted_authority_ref",
    "runtime_conformance_verified", "runtime_claims", "loss_counters",
    "timeline", "edges",
}

CAUSAL_ROW_FIELDS = {
    "seq", "kind", "attempt_id", "ref_id", "token_ref", "object_id",
    "file_cookie_digest", "group_seq", "event_symbol", "trusted",
}

CAUSAL_EDGE_FIELDS = {"edge_id", "from_seq", "to_seq", "relation", "contract_ref", "trusted"}

EXPECTED_CAUSAL_KINDS = (
    "supervisor_gate_token_consumed",
    "terminal_exit",
    "cgroup_empty",
    "pre_close_eagain",
    "close_entry",
    "fput_entry",
    "fsnotify_close",
    "fput_return",
    "close_exit",
    "fanotify_close_write",
    "post_close_eagain",
    "terminal_seal",
)

EXPECTED_CAUSAL_REFS = {
    "supervisor_gate_token_consumed": "gate-token-1",
    "terminal_exit": "terminal-exit-1",
    "cgroup_empty": "cgroup-empty-1",
    "pre_close_eagain": "pre-close-eagain-1",
    "close_entry": "close-entry-1",
    "fput_entry": "fput-entry-1",
    "fsnotify_close": "fsnotify-close-1",
    "fput_return": "fput-return-1",
    "close_exit": "close-exit-1",
    "fanotify_close_write": "fanotify-close-write-1",
    "post_close_eagain": "post-close-eagain-1",
    "terminal_seal": "terminal-seal-1",
}

EXPECTED_EDGE_ROWS = (
    (1, 2, "supervisor_gate_to_terminal_exit", "v17"),
    (2, 3, "terminal_exit_to_cgroup_empty", "v17"),
    (3, 4, "cgroup_empty_to_pre_close_barrier", "v17_v3"),
    (4, 5, "pre_close_barrier_to_close_entry", "v3"),
    (5, 6, "close_token_to_fput_entry", "v17"),
    (6, 7, "fput_entry_to_fsnotify_close", "source_audit"),
    (7, 8, "fsnotify_close_to_fput_return", "source_audit"),
    (8, 9, "fput_return_to_close_exit_upper_bound", "source_audit"),
    (7, 10, "fsnotify_close_to_fanotify_close_write", "source_audit"),
    (9, 10, "close_exit_to_fanotify_observation", "v3"),
    (10, 11, "fanotify_close_write_to_post_close_barrier", "v3"),
    (11, 12, "post_close_barrier_to_terminal_seal", "v17"),
)


class TerminalConformanceWitnessError(ValueError):
    """The synthetic envelope is malformed or makes an unauthorized claim."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TerminalConformanceWitnessError(message)


def _exact_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} must be an exact JSON object")
    _require(all(type(key) is str for key in value), f"{label} keys must be strings")
    actual = set(value)
    _require(actual == fields,
             f"{label} fields differ (missing={sorted(fields - actual)}, extra={sorted(actual - fields)})")
    return value


def _text(value: Any, label: str, *, identifier: bool = False) -> str:
    _require(type(value) is str and value and value.strip() == value,
             f"{label} must be a non-empty canonical string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise TerminalConformanceWitnessError(f"{label} is not valid UTF-8") from error
    _require(len(encoded) <= 2048, f"{label} exceeds the fixed text bound")
    if identifier:
        _require(_IDENTIFIER.fullmatch(value) is not None, f"{label} is not a bounded identifier")
    return value


def _sha256(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA256.fullmatch(value) is not None,
             f"{label} must be lowercase SHA-256 hex")
    return value


def _hex32(value: Any, label: str) -> str:
    _require(type(value) is str and _HEX32.fullmatch(value) is not None,
             f"{label} must be exactly 16-byte lowercase hex")
    return value


def _uint(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{label} must be an integer >= {minimum}")
    _require(value <= MAX_U64, f"{label} exceeds the unsigned 64-bit bound")
    return value


def _canonical_sha256(value: Any, label: str) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise TerminalConformanceWitnessError(f"{label} is not canonical JSON") from error
    return hashlib.sha256(raw).hexdigest()


def _validate_bindings(value: Any) -> dict[str, Any]:
    bindings = _exact_object(value, set(STATIC_BINDINGS), "bindings")
    _require(bindings == STATIC_BINDINGS,
             "source/contract implementation bindings differ from the fixed static artifacts")
    return bindings


def _validate_source_claims(value: Any, bindings: dict[str, Any]) -> dict[str, Any]:
    claims = _exact_object(value, set(SOURCE_CLAIMS), "source_claims")
    _require(claims == SOURCE_CLAIMS, "source claims differ from the source-audit static facts")
    _require(bindings["source_audit"]["sha256"] == KERNEL_CLAIMS["source_audit_sha256"],
             "source-audit binding is not the fixed kernel claim anchor")
    return claims


def _validate_kernel_claims(value: Any, bindings: dict[str, Any]) -> dict[str, Any]:
    claims = _exact_object(value, set(KERNEL_CLAIMS), "kernel_claims")
    _require(claims == KERNEL_CLAIMS, "kernel/config claims differ from the fixed unpinned target contract")
    _require(claims["source_audit_sha256"] == bindings["source_audit"]["sha256"],
             "kernel claims do not bind the source-audit artifact")
    _require(claims["target_source_pinned"] is False and claims["config_pinned"] is False,
             "target source/config must remain explicitly unpinned")
    _require(claims["target_build_id"] is None and claims["target_config_sha256"] is None,
             "untrusted target build/config values may not be promoted")
    _require(claims["kernel_probe_performed"] is False
             and claims["runtime_conformance_verified"] is False,
             "kernel runtime claims require a trusted authority and are rejected")
    return claims


def _validate_abi_claims(value: Any, bindings: dict[str, Any]) -> dict[str, Any]:
    claims = _exact_object(value, set(ABI_CLAIMS), "abi_claims")
    _require(claims == ABI_CLAIMS, "ABI claims differ from the fixed observed-only profile")
    _require(claims["profile_manifest_sha256"] == bindings["fanotify_profile_manifest"]["sha256"],
             "ABI claims do not bind the fanotify profile manifest")
    raw_values = _exact_object(claims["target_abi_raw_values"], set(ABI_CLAIMS["target_abi_raw_values"]),
                               "abi_claims.target_abi_raw_values")
    _require(raw_values == {key: None for key in raw_values},
             "target ABI raw values must remain null until the target ABI is pinned")
    _require(claims["target_abi_raw_values_pinned"] is False
             and claims["abi_probe_performed"] is False
             and claims["runtime_conformance_verified"] is False,
             "ABI runtime claims require a trusted authority and are rejected")
    return claims


def _validate_profile(value: Any, bindings: dict[str, Any]) -> dict[str, Any]:
    profile = _exact_object(value, set(PROFILE_CLAIMS), "fanotify_profile_claims")
    _require(profile == PROFILE_CLAIMS,
             "fanotify profile claims differ from the V17/V18 static profile")
    _require(profile["profile_manifest_sha256"] == bindings["fanotify_profile_manifest"]["sha256"],
             "fanotify profile does not bind its manifest")
    _require(profile["capability_probe_performed"] is False
             and profile["runtime_profile_conformance_verified"] is False,
             "fanotify runtime capability/conformance claims require trusted authority")


def _validate_dispositions(value: Any) -> tuple[dict[str, Any], ...]:
    _require(type(value) is list and len(value) == len(EXPECTED_DISPOSITIONS),
             "event_dispositions must enumerate exactly the frozen event bits")
    expected_fields = set(EXPECTED_DISPOSITIONS[0])
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(value):
        row = _exact_object(candidate, expected_fields, f"event_dispositions[{index}]")
        _require(row == EXPECTED_DISPOSITIONS[index],
                 f"event_dispositions[{index}] changes the frozen V17/V18 disposition")
        rows.append(row)
    _require(tuple(row["event_symbol"] for row in rows if row["group_kind"] == "permission")
             == ("FAN_OPEN_PERM", "FAN_ACCESS_PERM", "FAN_OPEN_EXEC_PERM"),
             "permission event disposition is incomplete or reordered")
    _require(sum(row["event_symbol"] == "FAN_CLOSE_WRITE" for row in rows) == 1,
             "exactly one close-write disposition is required")
    return tuple(rows)


def _validate_trust_boundary(value: Any) -> dict[str, Any]:
    boundary = _exact_object(value, set(TRUST_BOUNDARY), "trust_boundary")
    _require(boundary["trusted_authority_present"] is False
             and boundary["trusted_authority_ref"] is None
             and boundary["candidate_claims_accepted_as_runtime"] is False,
             "runtime claims cannot be accepted without an external trusted authority")
    _require(all(flag is False for flag in boundary["runtime_claims"].values()),
             "runtime claim is asserted without a trusted authority")
    _require(boundary == TRUST_BOUNDARY,
             "runtime/trust boundary is not the fixed deny-without-authority boundary")
    return boundary


def _validate_supervisor_projection(value: Any) -> dict[str, Any]:
    projection = _exact_object(value, SUPERVISOR_PROJECTION_FIELDS, "supervisor_projection")
    _require(projection["schema"] == "core.cfd.f8.r008_untrusted_supervisor_session_claim_projection.v1",
             "supervisor projection schema is unsupported")
    _require(projection["status"] == "untrusted_candidate_signed_supervisor_session_claims_consistent",
             "supervisor projection is not the existing untrusted claims result")
    _require(projection["projection_source"] == "f8_r008_supervisor_session_claims_v1",
             "supervisor projection source is not the existing session-claims bridge")
    _text(projection["attempt_id"], "supervisor_projection.attempt_id", identifier=True)
    _hex32(projection["nonce_hex"], "supervisor_projection.nonce_hex")
    _uint(projection["process_terminal_seq"], "supervisor_projection.process_terminal_seq", minimum=1)
    _text(projection["ledger_process_generation_id"],
          "supervisor_projection.ledger_process_generation_id", identifier=True)
    _sha256(projection["process_journal_raw_sha256"], "supervisor_projection.process_journal_raw_sha256")
    _sha256(projection["c_journal_raw_sha256"], "supervisor_projection.c_journal_raw_sha256")
    _require(projection["process_journal_raw_sha256"] == projection["c_journal_raw_sha256"],
             "supervisor process and C-journal hashes are not joined")
    for field in (
        "candidate_key_is_active", "active_key_registry_verified",
        "trusted_root_capability_present", "supervisor_identity_authenticated",
        "worker_execution_authenticated", "runtime_identity_verified",
        "event_source_completeness_verified", "readiness_pass", "T1_numerical",
    ):
        _require(projection[field] is False,
                 f"supervisor projection {field} is an unauthorized runtime claim")
    _require(type(projection["qualification_credit"]) is int
             and projection["qualification_credit"] == 0,
             "supervisor projection cannot claim qualification credit")
    return projection


def _validate_final_fput_projection(value: Any) -> dict[str, Any]:
    projection = _exact_object(value, FINAL_FPUT_PROJECTION_FIELDS, "final_fput_projection")
    _require(projection["schema"] == "core.cfd.f8.r008_final_fput_join_diagnostic.v3",
             "final-fput projection schema is unsupported")
    _require(projection["status"] == "diagnostic_raw_bytes_and_declared_queue_barrier_order_consistent_untrusted",
             "final-fput projection is not the existing V3 untrusted result")
    _require(projection["projection_source"] == "f8_r008_final_fput_join_reducer_v3",
             "final-fput projection source is not the existing V3 reducer")
    _text(projection["attempt_id"], "final_fput_projection.attempt_id", identifier=True)
    _text(projection["close_token_ref"], "final_fput_projection.close_token_ref", identifier=True)
    _text(projection["object_id"], "final_fput_projection.object_id", identifier=True)
    _sha256(projection["file_cookie_digest"], "final_fput_projection.file_cookie_digest")
    seq_range = projection["fanotify_name_group_seq_range"]
    _require(type(seq_range) is list and len(seq_range) == 2,
             "final-fput fanotify sequence range must contain two integers")
    first_seq = _uint(seq_range[0], "final_fput_projection.first_group_seq", minimum=1)
    last_seq = _uint(seq_range[1], "final_fput_projection.last_group_seq", minimum=first_seq)
    for field in ("pre_close_barrier_group_seq", "post_close_barrier_group_seq",
                  "fanotify_close_write_group_seq"):
        _uint(projection[field], f"final_fput_projection.{field}", minimum=1)
    _require(first_seq <= projection["pre_close_barrier_group_seq"]
             < projection["fanotify_close_write_group_seq"] <= last_seq,
             "final-fput group/barrier/close-write sequence relation is invalid")
    _require(projection["post_close_barrier_group_seq"] == last_seq,
             "final-fput post-close barrier does not close the declared group range")
    _require(projection["fanotify_raw_bytes_reparsed"] is True
             and projection["queue_barrier_declared_order_consistent"] is True,
             "final-fput projection did not include the existing raw/barrier diagnostics")
    for field in (
        "queue_barrier_source_authenticated", "shared_journal_contract_implemented",
        "final_close_claim", "trusted_observation", "kernel_source_pinned",
        "observer_runtime_authenticated", "close_token_cookie_bridge_authenticated",
        "runtime_observation_authenticated", "readiness_pass", "T1_numerical",
        "execution_authority",
    ):
        _require(projection[field] is False,
                 f"final-fput projection {field} is an unauthorized runtime claim")
    _require(type(projection["qualification_credit"]) is int
             and projection["qualification_credit"] == 0,
             "final-fput projection cannot claim qualification credit")
    _require(projection["observer_event_order"] == [
        "fd_install_entry", "__fput_entry", "fsnotify_close", "__fput_return",
    ], "final-fput observer order differs from the existing reducer contract")
    return projection


def _validate_causal_witness(
    value: Any,
    supervisor: dict[str, Any],
    final_fput: dict[str, Any],
) -> dict[str, Any]:
    witness = _exact_object(value, CAUSAL_FIELDS, "causal_witness")
    _require(witness["schema"] == "core.cfd.f8.r008_terminal_supervisor_final_fput_causal_witness.v1",
             "causal witness schema is unsupported")
    _require(witness["attempt_id"] == supervisor["attempt_id"] == final_fput["attempt_id"],
             "causal witness attempt does not join supervisor and final-fput projections")
    _require(witness["nonce_hex"] == supervisor["nonce_hex"],
             "causal witness nonce does not join the supervisor session")
    _require(witness["supervisor_terminal_seq"] == supervisor["process_terminal_seq"],
             "causal witness terminal sequence is not supervisor-derived")
    _require(witness["close_token_ref"] == final_fput["close_token_ref"]
             and witness["object_id"] == final_fput["object_id"]
             and witness["file_cookie_digest"] == final_fput["file_cookie_digest"],
             "causal witness close token/object/file-cookie join differs from final-fput projection")
    _require(witness["pre_close_barrier_group_seq"] == final_fput["pre_close_barrier_group_seq"]
             and witness["fanotify_close_write_group_seq"] == final_fput["fanotify_close_write_group_seq"]
             and witness["post_close_barrier_group_seq"] == final_fput["post_close_barrier_group_seq"],
             "causal witness queue markers differ from the final-fput projection")
    _require(witness["witness_origin"] == "synthetic_fixture",
             "causal witness must remain synthetic-only")
    _require(witness["trusted_authority_ref"] is None
             and witness["runtime_conformance_verified"] is False,
             "causal runtime claim is not permitted without trusted authority")

    runtime_claims = _exact_object(witness["runtime_claims"], {
        "source_authenticated", "kernel_conformance_verified", "fanotify_runtime_verified",
        "terminal_supervisor_runtime_verified", "final_fput_runtime_verified",
        "causal_bridge_verified",
    }, "causal_witness.runtime_claims")
    _require(all(flag is False for flag in runtime_claims.values()),
             "causal witness contains a runtime claim without trusted authority")

    loss = _exact_object(witness["loss_counters"], {
        "fanotify_overflow", "fanotify_lost", "observer_lost", "journal_loss",
        "short_read", "sequence_gap",
    }, "causal_witness.loss_counters")
    for field, counter in loss.items():
        _require(type(counter) is int and counter == 0,
                 f"causal witness {field} is non-zero or not an integer")

    rows = witness["timeline"]
    _require(type(rows) is list and 0 < len(rows) <= MAX_TIMELINE_ROWS,
             "causal witness timeline is outside its fixed bound")
    _require(len(rows) == len(EXPECTED_CAUSAL_KINDS),
             "causal witness timeline must cover the complete frozen lifecycle")
    row_by_kind: dict[str, dict[str, Any]] = {}
    seen_refs: set[str] = set()
    for index, candidate in enumerate(rows):
        row = _exact_object(candidate, CAUSAL_ROW_FIELDS, f"causal_witness.timeline[{index}]")
        _require(row["seq"] == index + 1, "causal witness timeline sequence has a gap or reorder")
        kind = row["kind"]
        _require(kind == EXPECTED_CAUSAL_KINDS[index],
                 "causal witness timeline lifecycle kind is missing, duplicated, or reordered")
        _require(row["attempt_id"] == witness["attempt_id"],
                 "causal witness timeline attempt differs from the envelope")
        _require(row["trusted"] is False, "causal witness timeline row is marked trusted")
        _text(row["ref_id"], f"causal_witness.timeline[{index}].ref_id", identifier=True)
        _require(row["ref_id"] == EXPECTED_CAUSAL_REFS[kind],
                 "causal witness timeline ref is not the fixed synthetic witness ref")
        _require(row["ref_id"] not in seen_refs, "causal witness timeline ref is duplicated")
        seen_refs.add(row["ref_id"])
        row_by_kind[kind] = row
        if kind == "fanotify_close_write":
            _require(row["event_symbol"] == "FAN_CLOSE_WRITE"
                     and row["group_seq"] == witness["fanotify_close_write_group_seq"],
                     "causal witness close-write row does not bind the name-group disposition")
        else:
            _require(row["event_symbol"] is None,
                     f"causal witness {kind} unexpectedly carries a fanotify event symbol")
        if kind in {"pre_close_eagain", "post_close_eagain"}:
            expected_group = (
                witness["pre_close_barrier_group_seq"] if kind == "pre_close_eagain"
                else witness["post_close_barrier_group_seq"]
            )
            _require(row["group_seq"] == expected_group,
                     f"causal witness {kind} watermark does not bind the final-fput projection")
        elif kind == "fanotify_close_write":
            # The event row was checked against the close-write group sequence
            # above; unlike lifecycle rows it necessarily carries that group
            # sequence.
            pass
        else:
            _require(row["group_seq"] is None,
                     f"causal witness {kind} unexpectedly carries a group sequence")
        if kind in {"close_entry", "fput_entry", "fsnotify_close", "fput_return",
                    "close_exit", "fanotify_close_write"}:
            _require(row["token_ref"] == witness["close_token_ref"]
                     and row["object_id"] == witness["object_id"]
                     and row["file_cookie_digest"] == witness["file_cookie_digest"],
                     f"causal witness {kind} does not bind the close token/object/cookie")
        elif kind == "terminal_seal":
            _require(row["token_ref"] is None and row["object_id"] == witness["object_id"]
                     and row["file_cookie_digest"] == witness["file_cookie_digest"],
                     "terminal seal does not bind the final output object")
        else:
            _require(row["token_ref"] is None and row["object_id"] is None
                     and row["file_cookie_digest"] is None,
                     f"causal witness {kind} invents a file lifecycle identity")

    edges = witness["edges"]
    _require(type(edges) is list and len(edges) == len(EXPECTED_EDGE_ROWS) <= MAX_EDGES,
             "causal witness edges do not cover the frozen relation set")
    for index, candidate in enumerate(edges):
        edge = _exact_object(candidate, CAUSAL_EDGE_FIELDS, f"causal_witness.edges[{index}]")
        from_seq, to_seq, relation, contract_ref = EXPECTED_EDGE_ROWS[index]
        _require(edge["edge_id"] == f"edge-{index + 1}", "causal witness edge id is not canonical")
        _require(edge["from_seq"] == from_seq and edge["to_seq"] == to_seq
                 and edge["relation"] == relation and edge["contract_ref"] == contract_ref,
                 "causal witness edge differs from the frozen causal relation")
        _require(edge["trusted"] is False,
                 "causal witness edge is marked trusted without an authority")
        _require(edge["from_seq"] in range(1, len(rows) + 1)
                 and edge["to_seq"] in range(1, len(rows) + 1),
                 "causal witness edge references an unknown timeline row")

    _require(row_by_kind["fput_entry"]["seq"] < row_by_kind["fsnotify_close"]["seq"]
             < row_by_kind["fput_return"]["seq"] < row_by_kind["close_exit"]["seq"],
             "causal witness violates source-level fput/fsnotify/close order")
    _require(row_by_kind["close_exit"]["seq"] < row_by_kind["fanotify_close_write"]["seq"]
             < row_by_kind["post_close_eagain"]["seq"],
             "causal witness reader observation/barrier order is invalid")
    return witness


def _validate_input(value: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    top = _exact_object(value, {
        "schema", "record_id", "status", "synthetic_only", "input_origin", "scope_id",
        "bindings", "source_claims", "kernel_claims", "abi_claims", "fanotify_profile_claims",
        "event_dispositions", "trust_boundary", "supervisor_projection",
        "final_fput_projection", "causal_witness",
    }, "conformance envelope")
    _require(top["schema"] == SCHEMA, "conformance envelope schema is unsupported")
    _require(top["record_id"] == RECORD_ID, "conformance envelope record_id is unsupported")
    _require(top["status"] == STATUS, "conformance envelope status is not the fixed static status")
    _require(top["synthetic_only"] is True and top["input_origin"] == "synthetic_fixture",
             "conformance envelope must be synthetic-only")
    _require(top["scope_id"] == SCOPE_ID, "conformance envelope scope differs from F8 R008")

    bindings = _validate_bindings(top["bindings"])
    _validate_source_claims(top["source_claims"], bindings)
    _validate_kernel_claims(top["kernel_claims"], bindings)
    _validate_abi_claims(top["abi_claims"], bindings)
    _validate_profile(top["fanotify_profile_claims"], bindings)
    dispositions = _validate_dispositions(top["event_dispositions"])
    _validate_trust_boundary(top["trust_boundary"])
    supervisor = _validate_supervisor_projection(top["supervisor_projection"])
    final_fput = _validate_final_fput_projection(top["final_fput_projection"])
    witness = _validate_causal_witness(top["causal_witness"], supervisor, final_fput)

    close_rows = [row for row in dispositions if row["event_symbol"] == "FAN_CLOSE_WRITE"]
    _require(close_rows[0]["close_join_required"] is True,
             "FAN_CLOSE_WRITE must retain a close-token/object join requirement")
    _require(final_fput["fanotify_close_write_group_seq"] == witness["fanotify_close_write_group_seq"],
             "final-fput close-write sequence is not joined to the causal witness")
    return top, bindings, supervisor, final_fput


def build_diagnostic_receipt(value: Any) -> dict[str, Any]:
    """Return a deterministic, permanently non-authorizing static result."""
    top, bindings, supervisor, final_fput = _validate_input(value)
    input_sha256 = _canonical_sha256(top, "conformance envelope")
    return {
        "schema": RESULT_SCHEMA,
        "status": RESULT_STATUS,
        "scope_id": SCOPE_ID,
        "input_sha256": input_sha256,
        "source_bindings_consistent": True,
        "source_claims_authenticated": False,
        "kernel_config_abi_claims_bound": True,
        "target_kernel_source_pinned": False,
        "target_kernel_config_pinned": False,
        "target_abi_raw_values_pinned": False,
        "fanotify_event_disposition_consistent": True,
        "fanotify_runtime_conformance_verified": False,
        "terminal_supervisor_projection_consistent": True,
        "terminal_supervisor_runtime_authenticated": False,
        "final_fput_projection_consistent": True,
        "final_fput_runtime_authenticated": False,
        "causal_witness_declared_order_consistent": True,
        "causal_witness_source_authenticated": False,
        "trusted_authority_present": False,
        "runtime_claims_accepted": False,
        "attempt_id": supervisor["attempt_id"],
        "close_token_ref": final_fput["close_token_ref"],
        "object_id": final_fput["object_id"],
        "final_fput_close_write_group_seq": final_fput["fanotify_close_write_group_seq"],
        "final_close_claim": False,
        "execution_authority": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }


def build_report() -> dict[str, Any]:
    """Return the checked-in contract description without reading any inputs."""
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": "synthetic_only_static_non_authorizing_contract",
        "contract_schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "static_bindings": STATIC_BINDINGS,
        "bound_claims": [
            "V17/V18 terminal completion contract hashes",
            "fanotify profile manifest and verifier source hash",
            "Linux v6.8 final-fput source audit and readiness-gap audit hashes",
            "raw parser, final-fput V1/V3 reducer, and supervisor-session claim source hashes",
            "observed x86-64 symbolic/raw ABI values with null target ABI values",
            "source-level close -> final __fput -> fsnotify_close ordering facts",
        ],
        "event_disposition": {
            "groups": ["permission", "name"],
            "rows": len(EXPECTED_DISPOSITIONS),
            "combined_mask_policy": "reject",
            "unknown_mask_policy": "reject",
            "close_write_requires_object_cookie_token_join": True,
            "both_groups_require_cap_sys_admin_in_init_user_ns": True,
        },
        "causal_witness": {
            "timeline_kinds": list(EXPECTED_CAUSAL_KINDS),
            "edge_count": len(EXPECTED_EDGE_ROWS),
            "source_order": "fput_entry < fsnotify_close < fput_return < close_exit",
            "reader_order": "close_exit < fanotify_close_write_observed < post_close_eagain",
            "runtime_source_authenticated": False,
        },
        "trust_boundary": TRUST_BOUNDARY,
        "non_authorizing_boundary": {
            "diagnostic_only": True,
            "trusted_authority_present": False,
            "runtime_claims_accepted": False,
            "final_close_claim": False,
            "execution_authority": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "prohibited_operations": [
            "root_or_sudo", "ptrace_or_seccomp", "fanotify_or_kernel_probe",
            "native_or_solver", "worker_gpu_or_queue",
        ],
        "non_overlap": {
            "raw_parser": "not reimplemented; only source hash and disposition contract are bound",
            "final_fput_reducer": "not reimplemented; only V3 projection and cross-module witness are checked",
            "supervisor_session_claims": "not reimplemented; candidate-key result remains untrusted",
            "trusted_identity_contract": "not consumed or replaced",
            "readiness_registry_ledger_denominator_gate_completion": "not read for mutation and never written",
        },
        "open_runtime_gaps": [
            "target kernel/source/config pin and runtime ABI expansion",
            "trusted authority and supervisor/runtime identity",
            "real fanotify queue/FID/PIDFD/permission conformance",
            "continuous final-fput observer and close-token/file-cookie causal authentication",
        ],
    }


__all__ = [
    "ABI_CLAIMS", "EXPECTED_CAUSAL_KINDS", "EXPECTED_DISPOSITIONS", "KERNEL_CLAIMS",
    "PROFILE_CLAIMS", "RESULT_SCHEMA", "SCHEMA", "SOURCE_CLAIMS", "STATIC_BINDINGS",
    "STATUS", "SCOPE_ID", "TRUST_BOUNDARY", "TerminalConformanceWitnessError",
    "build_diagnostic_receipt", "build_report",
]


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
