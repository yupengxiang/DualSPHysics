#!/usr/bin/env python3
"""Project F8/R008 target-kernel intake into a non-authorizing readiness view.

This module consumes only bounded JSON reports and their small-file metadata:
the checked-in target-kernel evidence-intake report, the static terminal
causal witness, readiness-audit v8, and the two trusted worker/runtime
contract reports.  It never follows an intake artifact reference and never
opens a target source tree, header tree, build binary, kernel state, or
runtime path.

The result is deliberately fail-closed.  A complete static intake would bind
identity pins, but it cannot authenticate an authority/runtime identity or
prove ABI, source-callgraph, or target-kernel runtime conformance.  This
projection therefore always remains diagnostic-only, readiness=false,
T1=false, and qualification credit=0.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INTAKE_REPORT = Path("reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json")
DEFAULT_CAUSAL_WITNESS_REPORT = Path("reports/F8-R008-TERMINAL-CONFORMANCE-CAUSAL-WITNESS-V1.json")
DEFAULT_READINESS_AUDIT_V8 = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "t1-execution-readiness-audit-v8/receipt.json"
)
DEFAULT_TRUSTED_IDENTITY_REPORT = Path(
    "reports/F8-R008-TRUSTED-AUTHORITY-WORKER-RUNTIME-IDENTITY-CONTRACT-V1.json"
)
DEFAULT_TRUSTED_HANDOFF_REPORT = Path(
    "reports/F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json"
)
DEFAULT_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-READINESS-PROJECTION-V1-2026-09-28.json"
)

REPORT_SCHEMA = "core.cfd.f8.r008.target_kernel_readiness_projection_report.v1"
REPORT_RECORD_ID = "f8-r008-target-kernel-readiness-projection-v1"
R008_SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"

INTAKE_SCHEMA = "core.cfd.f8.r008.target_kernel_evidence_intake_report.v1"
INTAKE_RECORD_ID = "f8-r008-target-kernel-evidence-intake-report-v1"
INTAKE_VALID_STATUS = "external_target_evidence_intake_valid_non_authorizing"

CAUSAL_SCHEMA = "core.cfd.f8.r008_terminal_conformance_causal_witness_report.v1"
CAUSAL_RECORD_ID = "f8-r008-terminal-conformance-causal-witness-report-v1"
CAUSAL_STATUS = "synthetic_only_static_non_authorizing_contract"

READINESS_SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v8"
READINESS_RECORD_ID = "f8-r008-execution-readiness-audit-v8"

TRUSTED_IDENTITY_SCHEMA = "core.cfd.f8.r008_trusted_authority_worker_runtime_identity_contract.v1"
TRUSTED_IDENTITY_STATUS = "synthetic_only_non_authorizing_contract_design"
TRUSTED_HANDOFF_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_handoff_contract.v1"
TRUSTED_HANDOFF_STATUS = "synthetic_only_non_authorizing_handoff_contract_design"

STATUS = "diagnostic_only_target_kernel_readiness_blocked"
MAX_JSON_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
SHA1_RE = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
BUILD_ID_RE = re.compile(r"[0-9a-f]{16,128}\Z", re.ASCII)

TARGET_FIELDS = (
    "kernel_release",
    "source_commit",
    "source_tree_sha256",
    "uapi_sha256",
    "config_sha256",
    "build_id",
)
PIN_FIELDS = (
    "build_id_pinned",
    "config_pinned",
    "kernel_release_pinned",
    "source_commit_pinned",
    "source_tree_pinned",
    "uapi_pinned",
)
ARTIFACT_ROLES = ("build", "config", "source", "uapi")

# These are the immutable checked-in dependency digests used by the default
# projection.  A caller supplying fixture paths may provide an explicit
# expected_input_digests mapping; arbitrary target paths are never inferred.
EXPECTED_INPUT_SHA256 = {
    "intake": "a170e911f42a5544bdb2adea30ed96fd29f3f83b1e36a7e2481dec03a8d81f8c",
    "causal_witness": "60aebabcb7dc2294ab2f37b0d30f674ec0f08dbd2e0f93c406a53ee293faeed5",
    "readiness_v8": "80b6df23bf8e118e60608dae9f64dd6967e2e9978e64f554ac5087651bee894c",
    "trusted_identity": "8f7188e0dea2d90b4a6eed6c1a8254eae6bc012dd6483e867717c2cb9070f89f",
    "trusted_handoff": "8a2c3535b403eeb0aae35579b2c5882eadb7c00b9cde0a047b7cc5c95120bca3",
}

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class TargetKernelReadinessProjectionError(ValueError):
    """The bounded projection inputs or report are inconsistent."""

    def __init__(self, message: str, *, code: str = "invalid_projection_input") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "invalid_projection_input") -> None:
    raise TargetKernelReadinessProjectionError(message, code=code)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not permitted: {token}", code="non_strict_json")


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _display_path(path: Path) -> str:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        return absolute.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return absolute.as_posix()


def _canonical_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        if path.as_posix() != str(path) or any(part in {"", ".", ".."} for part in path.parts):
            _fail("absolute input path is not canonical", code="path_traversal")
        return path
    if path.as_posix() != str(path) or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        _fail("relative input path is not canonical", code="path_traversal")
    return LAB_ROOT / path


def _assert_no_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            _fail(f"could not inspect input path: {path}")
            raise AssertionError from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"input path contains a symlink: {path}", code="symlink_path")


def _read_bounded_json(path: str | Path, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one bounded, single-link JSON file without following links."""

    target = _canonical_path(path)
    _assert_no_symlink_components(target)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(target), os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    except FileNotFoundError as error:
        _fail(f"{label} is missing: {_display_path(target)}", code="missing_input")
        raise AssertionError from error
    except OSError as error:
        _fail(f"{label} cannot be opened safely: {_display_path(target)}")
        raise AssertionError from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{label} must be a regular file", code="not_regular_file")
        if before.st_nlink != 1:
            _fail(f"{label} must have exactly one hard link", code="hardlink")
        if before.st_size > MAX_JSON_BYTES:
            _fail(f"{label} exceeds the bounded JSON limit", code="oversize")

        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, MAX_JSON_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > MAX_JSON_BYTES:
                _fail(f"{label} exceeds the bounded JSON limit", code="oversize")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(target, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named) or total != before.st_size:
            _fail(f"{label} changed while being read", code="input_drift")
        raw = b"".join(chunks)
    except TargetKernelReadinessProjectionError:
        raise
    except OSError as error:
        _fail(f"{label} could not be read safely", code="read_error")
        raise AssertionError from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except TargetKernelReadinessProjectionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not strict UTF-8 JSON", code="invalid_json")
        raise AssertionError from error
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object", code="json_not_object")
    return value, {
        "path": _display_path(target),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _require(condition: bool, message: str, *, code: str = "invalid_projection_input") -> None:
    if not condition:
        _fail(message, code=code)


def _require_keys(value: Any, expected: set[str], label: str) -> None:
    _require(type(value) is dict and set(value) == expected, f"{label} fields differ")


def _sha256(value: Any, label: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"{label} is not lowercase SHA-256")
    return value


def _sha1_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    _require(isinstance(value, str) and SHA1_RE.fullmatch(value) is not None, f"{label} is not SHA-1")
    return value


def _sha256_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, label)


def _build_id_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    _require(isinstance(value, str) and BUILD_ID_RE.fullmatch(value) is not None, f"{label} is malformed")
    return value


def _ref(meta: dict[str, Any], value: Mapping[str, Any], *, schema_key: str = "schema") -> dict[str, Any]:
    schema = value.get(schema_key)
    record_id = value.get("record_id")
    _require(isinstance(schema, str) and schema, "dependency schema is missing")
    _require(isinstance(record_id, str) and record_id, "dependency record_id is missing")
    return {
        "path": meta["path"],
        "bytes": meta["bytes"],
        "sha256": meta["sha256"],
        "schema": schema,
        "record_id": record_id,
    }


def _expected_digest(
    key: str,
    path: str | Path,
    expected_input_digests: Mapping[str, str] | None,
) -> str | None:
    if expected_input_digests is not None and key in expected_input_digests:
        return _sha256(expected_input_digests[key], f"expected {key} digest")
    canonical = _canonical_path(path)
    default = _canonical_path({
        "intake": DEFAULT_INTAKE_REPORT,
        "causal_witness": DEFAULT_CAUSAL_WITNESS_REPORT,
        "readiness_v8": DEFAULT_READINESS_AUDIT_V8,
        "trusted_identity": DEFAULT_TRUSTED_IDENTITY_REPORT,
        "trusted_handoff": DEFAULT_TRUSTED_HANDOFF_REPORT,
    }[key])
    if canonical == default:
        return EXPECTED_INPUT_SHA256[key]
    return None


def _check_digest(key: str, meta: Mapping[str, Any], expected_input_digests: Mapping[str, str] | None,
                  path: str | Path) -> None:
    expected = _expected_digest(key, path, expected_input_digests)
    if expected is not None and meta["sha256"] != expected:
        _fail(f"{key} dependency digest drift", code="dependency_digest_drift")


def _validate_intake(value: dict[str, Any]) -> dict[str, Any]:
    _require_keys(
        value,
        {"schema", "record_id", "status", "manifest", "declared_target", "artifacts", "validation", "pins", "authorization", "side_effects"},
        "target-kernel intake report",
    )
    _require(value["schema"] == INTAKE_SCHEMA, "target-kernel intake report schema drift", code="schema_drift")
    _require(value["record_id"] == INTAKE_RECORD_ID, "target-kernel intake report record drift", code="schema_drift")
    _require(isinstance(value["status"], str), "target-kernel intake status is malformed")

    _require_keys(value["manifest"], {"path", "exists", "bytes", "sha256"}, "intake manifest")
    _require(isinstance(value["manifest"]["path"], str) and value["manifest"]["path"], "intake manifest path is malformed")
    _require(type(value["manifest"]["exists"]) is bool, "intake manifest exists is malformed")

    _require_keys(value["declared_target"], set(TARGET_FIELDS) | {"required_options"}, "intake declared target")
    target = value["declared_target"]
    _require(isinstance(target["kernel_release"], str) or target["kernel_release"] is None, "kernel release is malformed")
    _sha1_or_none(target["source_commit"], "source commit")
    for field in ("source_tree_sha256", "uapi_sha256", "config_sha256"):
        _sha256_or_none(target[field], field)
    _build_id_or_none(target["build_id"], "build id")
    _require(isinstance(target["required_options"], list), "required options are malformed")

    _require(type(value["artifacts"]) is dict and set(value["artifacts"]) == set(ARTIFACT_ROLES), "intake artifact roles differ")
    for role in ARTIFACT_ROLES:
        item = value["artifacts"][role]
        _require_keys(item, {"path", "declared_bytes", "declared_sha256", "observed_bytes", "observed_sha256", "verified"}, f"intake artifact {role}")
        _require(type(item["verified"]) is bool, f"intake artifact {role} verified flag is malformed")
        if item["verified"]:
            _require(isinstance(item["path"], str) and item["path"], f"intake artifact {role} path is malformed")
            _require(type(item["declared_bytes"]) is int and item["declared_bytes"] > 0, f"intake artifact {role} bytes are malformed")
            _require(type(item["observed_bytes"]) is int and item["observed_bytes"] == item["declared_bytes"], f"intake artifact {role} bytes drift")
            _sha256(item["declared_sha256"], f"intake artifact {role} declared digest")
            _sha256(item["observed_sha256"], f"intake artifact {role} observed digest")
            _require(item["declared_sha256"] == item["observed_sha256"], f"intake artifact {role} digest drift")
        else:
            _require(all(item[field] is None for field in ("path", "declared_bytes", "declared_sha256", "observed_bytes", "observed_sha256")), f"intake artifact {role} has partial blocked evidence")

    _require_keys(value["validation"], {"manifest_present", "manifest_valid", "artifact_files_verified", "external_target_evidence_complete", "blockers"}, "intake validation")
    validation = value["validation"]
    for field in ("manifest_present", "manifest_valid", "artifact_files_verified", "external_target_evidence_complete"):
        _require(type(validation[field]) is bool, f"intake validation {field} is malformed")
    _require(isinstance(validation["blockers"], list) and all(isinstance(item, str) and item for item in validation["blockers"]), "intake blockers are malformed")

    _require_keys(value["pins"], set(PIN_FIELDS), "intake pins")
    _require(all(type(value["pins"][field]) is bool for field in PIN_FIELDS), "intake pins are malformed")

    expected_authorization = {
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }
    _require(value["authorization"] == expected_authorization, "intake authorization boundary was promoted", code="authorization_drift")
    _require(isinstance(value["side_effects"], dict), "intake side-effects section is malformed")
    for field in ("gate_mutation", "ledger_mutation", "registry_mutation", "plan_mutation"):
        _require(value["side_effects"].get(field) == 0, f"intake {field} is non-zero", code="side_effect_drift")
    for field in ("kernel_started", "native_started", "worker_started", "gpu_started", "queue_started"):
        _require(value["side_effects"].get(field) is False, f"intake {field} is true", code="side_effect_drift")

    pins = {field: value["pins"][field] for field in PIN_FIELDS}
    target_copy = {field: copy.deepcopy(target[field]) for field in TARGET_FIELDS}
    all_pins = all(pins.values())
    complete = (
        value["status"] == INTAKE_VALID_STATUS
        and validation["manifest_present"]
        and validation["manifest_valid"]
        and validation["artifact_files_verified"]
        and validation["external_target_evidence_complete"]
        and all_pins
    )
    return {
        "ref_fields": {
            "schema": value["schema"],
            "record_id": value["record_id"],
            "status": value["status"],
        },
        "target": target_copy,
        "pins": pins,
        "all_pins": all_pins,
        "complete": complete,
        "partial_pins": any(pins.values()) and not all_pins,
        "validation": {
            "manifest_present": validation["manifest_present"],
            "manifest_valid": validation["manifest_valid"],
            "artifact_files_verified": validation["artifact_files_verified"],
            "external_target_evidence_complete": validation["external_target_evidence_complete"],
            "blockers": list(validation["blockers"]),
        },
    }


def _validate_causal(value: dict[str, Any]) -> dict[str, Any]:
    _require(value.get("schema") == CAUSAL_SCHEMA, "causal witness schema drift", code="schema_drift")
    _require(value.get("record_id") == CAUSAL_RECORD_ID, "causal witness record drift", code="schema_drift")
    _require(value.get("scope_id") == R008_SCOPE_ID, "causal witness scope drift", code="scope_drift")
    _require(value.get("status") == CAUSAL_STATUS, "causal witness status drift", code="causal_witness_drift")

    witness = value.get("causal_witness")
    _require(isinstance(witness, dict), "causal witness body is missing")
    _require(type(witness.get("runtime_source_authenticated")) is bool and witness["runtime_source_authenticated"] is False, "causal witness runtime trust was promoted", code="causal_witness_drift")
    _require(type(witness.get("edge_count")) is int and witness["edge_count"] > 0, "causal witness edge count is malformed")

    boundary = value.get("non_authorizing_boundary")
    _require(isinstance(boundary, dict), "causal non-authorizing boundary is missing")
    for field in ("T1_numerical", "readiness_pass", "execution_authority", "trusted_authority_present", "runtime_claims_accepted", "final_close_claim"):
        _require(boundary.get(field) is False, f"causal boundary {field} was promoted", code="authorization_drift")
    for field in ("completion_mutation", "denominator_mutation", "gate_mutation", "ledger_mutation", "registry_mutation", "qualification_credit"):
        _require(boundary.get(field) == 0, f"causal boundary {field} is non-zero", code="side_effect_drift")

    trust = value.get("trust_boundary")
    _require(isinstance(trust, dict), "causal trust boundary is missing")
    _require(trust.get("trusted_authority_present") is False, "causal trusted authority was promoted", code="authorization_drift")
    runtime_claims = trust.get("runtime_claims")
    _require(isinstance(runtime_claims, dict), "causal runtime claims are missing")
    for field in ("causal_bridge_verified", "execution_authority", "fanotify_conformance", "final_fput_observation", "readiness_pass", "target_kernel_conformance", "terminal_supervisor_identity"):
        _require(runtime_claims.get(field) is False, f"causal runtime claim {field} was promoted", code="causal_witness_drift")

    static_bindings = value.get("static_bindings")
    _require(isinstance(static_bindings, dict) and static_bindings, "causal static bindings are missing")
    normalized_bindings: dict[str, dict[str, str]] = {}
    for name, item in static_bindings.items():
        _require(isinstance(name, str) and name, "causal static binding name is malformed")
        _require_keys(item, {"path", "sha256"}, f"causal static binding {name}")
        _require(isinstance(item["path"], str) and item["path"], f"causal static binding {name} path is malformed")
        normalized_bindings[name] = {"path": item["path"], "sha256": _sha256(item["sha256"], f"causal static binding {name} digest")}

    return {
        "scope_id": value["scope_id"],
        "status": value["status"],
        "edge_count": witness["edge_count"],
        "runtime_source_authenticated": witness["runtime_source_authenticated"],
        "static_bindings": normalized_bindings,
        "open_runtime_gaps": list(value.get("open_runtime_gaps", [])),
        "trusted_authority_present": False,
        "target_kernel_conformance": False,
    }


def _validate_readiness(value: dict[str, Any]) -> dict[str, Any]:
    _require(value.get("schema") == READINESS_SCHEMA, "readiness v8 schema drift", code="schema_drift")
    _require(value.get("record_id") == READINESS_RECORD_ID, "readiness v8 record drift", code="schema_drift")
    _require(value.get("scope_id") == R008_SCOPE_ID, "readiness v8 scope drift", code="scope_drift")
    _require(value.get("readiness_pass") is False, "readiness v8 was promoted", code="authorization_drift")
    _require(value.get("full_t1_decision") is False, "readiness v8 full T1 was promoted", code="authorization_drift")
    _require(value.get("T1_numerical") is False, "readiness v8 T1 was promoted", code="authorization_drift")
    _require(value.get("qualification_credit") == 0, "readiness v8 credit was promoted", code="authorization_drift")

    authority = value.get("execution_authority")
    _require(isinstance(authority, dict), "readiness v8 execution authority is missing")
    for field in ("solver", "worker", "gpu", "queue", "root_or_capability_probe", "fanotify_init_or_mark"):
        _require(authority.get(field) is False, f"readiness v8 authority {field} was promoted", code="authorization_drift")
    for field in ("registry_mutation", "ledger_mutation", "denominator_mutation"):
        _require(authority.get(field) == 0, f"readiness v8 authority {field} is non-zero", code="side_effect_drift")

    gaps = value.get("blocking_gaps")
    _require(isinstance(gaps, list) and all(isinstance(item, dict) and isinstance(item.get("code"), str) for item in gaps), "readiness v8 blockers are malformed")
    gap_codes = [item["code"] for item in gaps]
    required_gap_codes = {
        "terminal_fanotify_profiles_lack_pinned_kernel_runtime_conformance",
        "trusted_terminal_supervisor_and_final_fput_observer_missing",
        "native_syscall_per_number_policy_and_target_pin_missing",
        "ptrace_seccomp_selector_runtime_conformance_missing",
    }
    _require(required_gap_codes.issubset(set(gap_codes)), "readiness v8 blocker inventory drift", code="readiness_gap_drift")
    return {
        "scope_id": value["scope_id"],
        "status": value.get("status"),
        "readiness_pass": value["readiness_pass"],
        "full_t1_decision": value["full_t1_decision"],
        "T1_numerical": value["T1_numerical"],
        "qualification_credit": value["qualification_credit"],
        "blocking_gap_codes": gap_codes,
    }


def _validate_trusted_identity(value: dict[str, Any]) -> dict[str, Any]:
    _require(value.get("contract_schema") == TRUSTED_IDENTITY_SCHEMA, "trusted identity schema drift", code="schema_drift")
    _require(value.get("scope_id") == R008_SCOPE_ID, "trusted identity scope drift", code="scope_drift")
    _require(value.get("status") == TRUSTED_IDENTITY_STATUS, "trusted identity status drift", code="trusted_identity_drift")
    boundary = value.get("non_authorizing_boundary")
    _require(isinstance(boundary, dict), "trusted identity boundary is missing")
    _require(boundary.get("readiness_pass") is False and boundary.get("T1_numerical") is False, "trusted identity readiness was promoted", code="authorization_drift")
    _require(boundary.get("qualification_credit") == 0, "trusted identity credit was promoted", code="authorization_drift")
    input_boundary = value.get("input_boundary")
    _require(isinstance(input_boundary, dict) and input_boundary.get("synthetic_only") is True, "trusted identity is not marked synthetic-only", code="trusted_identity_drift")
    return {
        "scope_id": value["scope_id"],
        "contract_schema": value["contract_schema"],
        "status": value["status"],
        "synthetic_only": True,
        "production_identity_authenticated": False,
        "execution_authority": False,
    }


def _validate_trusted_handoff(value: dict[str, Any]) -> dict[str, Any]:
    _require(value.get("contract_schema") == TRUSTED_HANDOFF_SCHEMA, "trusted handoff schema drift", code="schema_drift")
    _require(value.get("scope_id") == R008_SCOPE_ID, "trusted handoff scope drift", code="scope_drift")
    _require(value.get("status") == TRUSTED_HANDOFF_STATUS, "trusted handoff status drift", code="trusted_identity_drift")
    boundary = value.get("non_authorizing_boundary")
    _require(isinstance(boundary, dict), "trusted handoff boundary is missing")
    for field in ("readiness_pass", "T1_numerical", "execution_authority", "formal_admission", "capability_minted"):
        _require(boundary.get(field) is False, f"trusted handoff boundary {field} was promoted", code="authorization_drift")
    _require(boundary.get("qualification_credit") == 0, "trusted handoff credit was promoted", code="authorization_drift")
    input_boundary = value.get("input_boundary")
    _require(isinstance(input_boundary, dict), "trusted handoff input boundary is missing")
    _require(input_boundary.get("synthetic_only") is True and input_boundary.get("production_paths_read") is False, "trusted handoff production boundary drift", code="trusted_identity_drift")
    constraints = value.get("fail_closed_constraints")
    _require(isinstance(constraints, dict), "trusted handoff fail-closed constraints are missing")
    _require(constraints.get("production_identity") == "not_authenticated", "trusted handoff production identity was promoted", code="trusted_identity_drift")
    _require(constraints.get("runtime") == "not_measured", "trusted handoff runtime measurement was promoted", code="trusted_identity_drift")
    return {
        "scope_id": value["scope_id"],
        "contract_schema": value["contract_schema"],
        "status": value["status"],
        "synthetic_only": True,
        "production_identity_authenticated": False,
        "runtime_measured": False,
        "execution_authority": False,
    }


def _dependency_ref(meta: dict[str, Any], value: dict[str, Any], *, schema_key: str = "schema") -> dict[str, Any]:
    result = _ref(meta, value, schema_key=schema_key)
    result["scope_id"] = value.get("scope_id")
    result["status"] = value.get("status")
    return result


def _gap(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "severity": "high", "detail": detail}


def _derive_gaps(intake: dict[str, Any], causal: dict[str, Any], readiness: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if not intake["complete"]:
        gaps.append(_gap(
            "external_target_evidence_missing",
            "The intake report does not prove a complete external target source/UAPI/config/build evidence set; static intake cannot substitute for the missing external evidence.",
        ))
    if intake["partial_pins"]:
        gaps.append(_gap(
            "partial_target_kernel_pin_set",
            "The intake report contains only a partial kernel release/source/UAPI/config/build pin set; partial identity cannot be projected as target readiness.",
        ))
    elif not intake["all_pins"]:
        gaps.append(_gap(
            "target_kernel_identity_pins_incomplete",
            "At least one required kernel release/source/UAPI/config/build identity pin is absent.",
        ))
    gaps.append(_gap(
        "causal_witness_static_only_untrusted",
        "The causal witness is a static contract projection with runtime_source_authenticated=false and trusted_authority_present=false.",
    ))
    gaps.append(_gap(
        "untrusted_authority_runtime_identity",
        "The trusted authority/worker/runtime contracts are synthetic-only; production authority and loaded runtime identity are not authenticated or measured.",
    ))
    gaps.append(_gap(
        "target_abi_conformance_missing",
        "No target-kernel ABI evidence proves the deployed audit ABI, fanotify/FID/PIDFD behavior, or selector semantics on the target kernel.",
    ))
    gaps.append(_gap(
        "source_callgraph_conformance_missing",
        "No independently trusted target source/build callgraph evidence proves the required close/final-fput/observer path for the deployed runtime.",
    ))
    gaps.append(_gap(
        "target_kernel_runtime_conformance_missing",
        "The intake pins are static metadata only; target-kernel runtime conformance and terminal fanotify/final-fput behavior remain unevaluated.",
    ))
    if readiness["qualification_credit"] != 0 or readiness["readiness_pass"] or readiness["T1_numerical"]:
        gaps.append(_gap(
            "readiness_v8_zero_credit_boundary_drift",
            "The bound readiness v8 receipt no longer retains its zero-credit, non-authorizing boundary.",
        ))
    return gaps


def build_projection(
    intake_report_path: str | Path = DEFAULT_INTAKE_REPORT,
    causal_witness_path: str | Path = DEFAULT_CAUSAL_WITNESS_REPORT,
    readiness_audit_path: str | Path = DEFAULT_READINESS_AUDIT_V8,
    trusted_identity_report_path: str | Path = DEFAULT_TRUSTED_IDENTITY_REPORT,
    trusted_handoff_report_path: str | Path = DEFAULT_TRUSTED_HANDOFF_REPORT,
    *,
    expected_input_digests: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the deterministic, diagnostic-only readiness projection."""

    intake_value, intake_meta = _read_bounded_json(intake_report_path, label="target-kernel intake report")
    causal_value, causal_meta = _read_bounded_json(causal_witness_path, label="causal witness report")
    readiness_value, readiness_meta = _read_bounded_json(readiness_audit_path, label="readiness v8 receipt")
    identity_value, identity_meta = _read_bounded_json(trusted_identity_report_path, label="trusted identity report")
    handoff_value, handoff_meta = _read_bounded_json(trusted_handoff_report_path, label="trusted handoff report")

    _check_digest("intake", intake_meta, expected_input_digests, intake_report_path)
    _check_digest("causal_witness", causal_meta, expected_input_digests, causal_witness_path)
    _check_digest("readiness_v8", readiness_meta, expected_input_digests, readiness_audit_path)
    _check_digest("trusted_identity", identity_meta, expected_input_digests, trusted_identity_report_path)
    _check_digest("trusted_handoff", handoff_meta, expected_input_digests, trusted_handoff_report_path)

    intake = _validate_intake(intake_value)
    causal = _validate_causal(causal_value)
    readiness = _validate_readiness(readiness_value)
    identity = _validate_trusted_identity(identity_value)
    handoff = _validate_trusted_handoff(handoff_value)

    input_refs = {
        "target_kernel_evidence_intake": _dependency_ref(intake_meta, intake_value),
        "causal_witness": _dependency_ref(causal_meta, causal_value),
        "readiness_audit_v8": _dependency_ref(readiness_meta, readiness_value),
        "trusted_identity_contract": _dependency_ref(identity_meta, identity_value, schema_key="contract_schema"),
        "trusted_worker_runtime_handoff": _dependency_ref(handoff_meta, handoff_value, schema_key="contract_schema"),
    }
    gaps = _derive_gaps(intake, causal, readiness)
    gap_codes = [item["code"] for item in gaps]

    target_kernel = {field: intake["target"][field] for field in TARGET_FIELDS}
    target_kernel["pins"] = copy.deepcopy(intake["pins"])
    target_kernel["all_pins_complete"] = intake["all_pins"]
    target_kernel["external_evidence_complete"] = intake["complete"]

    authorization = {
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }
    side_effects = {
        "kernel_started": False,
        "native_started": False,
        "privileged_probe_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "gate_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "completion_mutation": 0,
        "plan_mutation": 0,
    }

    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "scope_id": R008_SCOPE_ID,
        "status": STATUS,
        "inputs": input_refs,
        "target_kernel": target_kernel,
        "causal_witness": {
            "report_sha256": causal_meta["sha256"],
            "scope_id": causal["scope_id"],
            "status": causal["status"],
            "edge_count": causal["edge_count"],
            "runtime_source_authenticated": causal["runtime_source_authenticated"],
            "trusted_authority_present": causal["trusted_authority_present"],
            "target_kernel_conformance": causal["target_kernel_conformance"],
            "static_bindings": causal["static_bindings"],
        },
        "trusted_runtime": {
            "identity_contract_report_sha256": identity_meta["sha256"],
            "handoff_contract_report_sha256": handoff_meta["sha256"],
            "production_authority_authenticated": identity["production_identity_authenticated"],
            "production_runtime_identity_authenticated": handoff["production_identity_authenticated"],
            "runtime_measured": handoff["runtime_measured"],
            "execution_authority": False,
        },
        "validation": {
            "intake_report_schema_valid": True,
            "intake_report_digest_bound": True,
            "r008_scope_bound": True,
            "external_target_evidence_complete": intake["complete"],
            "target_kernel_pin_set_complete": intake["all_pins"],
            "causal_witness_refs_bound": True,
            "trusted_authority_runtime_identity_verified": False,
            "target_abi_conformance": False,
            "source_callgraph_conformance": False,
            "target_kernel_runtime_conformance": False,
            "readiness_v8_zero_credit_preserved": True,
            "blockers": gap_codes,
        },
        "blocking_gaps": gaps,
        "authorization": authorization,
        "side_effects": side_effects,
    }


def _validate_projection(value: Any) -> dict[str, Any]:
    expected = {
        "schema", "record_id", "scope_id", "status", "inputs", "target_kernel",
        "causal_witness", "trusted_runtime", "validation", "blocking_gaps",
        "authorization", "side_effects",
    }
    _require_keys(value, expected, "target-kernel readiness projection")
    _require(value["schema"] == REPORT_SCHEMA, "projection schema drift", code="schema_drift")
    _require(value["record_id"] == REPORT_RECORD_ID, "projection record drift", code="schema_drift")
    _require(value["scope_id"] == R008_SCOPE_ID, "projection scope drift", code="scope_drift")
    _require(value["status"] == STATUS, "projection status is not diagnostic-only", code="authorization_drift")

    input_names = {
        "target_kernel_evidence_intake",
        "causal_witness",
        "readiness_audit_v8",
        "trusted_identity_contract",
        "trusted_worker_runtime_handoff",
    }
    _require(isinstance(value["inputs"], dict) and set(value["inputs"]) == input_names, "projection input refs differ")
    for name, ref in value["inputs"].items():
        _require_keys(ref, {"path", "bytes", "sha256", "schema", "record_id", "scope_id", "status"}, f"projection input ref {name}")
        _require(isinstance(ref["path"], str) and ref["path"], f"projection input ref {name} path is malformed")
        _require(type(ref["bytes"]) is int and ref["bytes"] > 0, f"projection input ref {name} bytes are malformed")
        _sha256(ref["sha256"], f"projection input ref {name} digest")
        _require(isinstance(ref["schema"], str) and ref["schema"], f"projection input ref {name} schema is malformed")
        _require(isinstance(ref["record_id"], str) and ref["record_id"], f"projection input ref {name} record is malformed")
        _require(ref["scope_id"] in {None, R008_SCOPE_ID}, f"projection input ref {name} scope drift", code="scope_drift")
        _require(ref["status"] is None or isinstance(ref["status"], str), f"projection input ref {name} status is malformed")

    target = value["target_kernel"]
    _require_keys(target, set(TARGET_FIELDS) | {"pins", "all_pins_complete", "external_evidence_complete"}, "projection target kernel")
    _require_keys(target["pins"], set(PIN_FIELDS), "projection target pins")
    _require(all(type(target["pins"][field]) is bool for field in PIN_FIELDS), "projection target pins are malformed")
    _require(type(target["all_pins_complete"]) is bool and target["all_pins_complete"] == all(target["pins"].values()), "projection target pin completeness drift")
    _require(type(target["external_evidence_complete"]) is bool, "projection target evidence flag is malformed")
    _sha1_or_none(target["source_commit"], "projection source commit")
    for field in ("source_tree_sha256", "uapi_sha256", "config_sha256"):
        _sha256_or_none(target[field], f"projection {field}")
    _build_id_or_none(target["build_id"], "projection build id")

    causal = value["causal_witness"]
    _require(type(causal) is dict, "projection causal witness is malformed")
    _sha256(causal.get("report_sha256"), "projection causal report digest")
    _require(causal.get("scope_id") == R008_SCOPE_ID and causal.get("runtime_source_authenticated") is False and causal.get("trusted_authority_present") is False and causal.get("target_kernel_conformance") is False, "projection causal witness was promoted", code="causal_witness_drift")
    _require(isinstance(causal.get("static_bindings"), dict) and causal["static_bindings"], "projection causal refs are missing")

    trusted = value["trusted_runtime"]
    _require(type(trusted) is dict, "projection trusted runtime is malformed")
    for field in ("identity_contract_report_sha256", "handoff_contract_report_sha256"):
        _sha256(trusted.get(field), f"projection {field}")
    for field in ("production_authority_authenticated", "production_runtime_identity_authenticated", "runtime_measured", "execution_authority"):
        _require(trusted.get(field) is False, f"projection trusted runtime {field} was promoted", code="authorization_drift")

    validation = value["validation"]
    _require(type(validation) is dict, "projection validation is malformed")
    for field in (
        "intake_report_schema_valid", "intake_report_digest_bound", "r008_scope_bound",
        "external_target_evidence_complete", "target_kernel_pin_set_complete",
        "causal_witness_refs_bound", "trusted_authority_runtime_identity_verified",
        "target_abi_conformance", "source_callgraph_conformance",
        "target_kernel_runtime_conformance", "readiness_v8_zero_credit_preserved",
    ):
        _require(type(validation.get(field)) is bool, f"projection validation {field} is malformed")
    _require(isinstance(validation.get("blockers"), list) and all(isinstance(item, str) for item in validation["blockers"]), "projection blocker codes are malformed")

    _require(isinstance(value["blocking_gaps"], list), "projection blocking gaps are malformed")
    gap_codes = []
    for item in value["blocking_gaps"]:
        _require_keys(item, {"code", "severity", "detail"}, "projection blocking gap")
        _require(isinstance(item["code"], str) and item["code"], "projection gap code is malformed")
        _require(item["severity"] == "high", "projection gap severity drift")
        _require(isinstance(item["detail"], str) and item["detail"], "projection gap detail is malformed")
        gap_codes.append(item["code"])
    _require(validation["blockers"] == gap_codes, "projection blocker list is not bound to gaps")

    expected_authorization = {
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }
    _require(value["authorization"] == expected_authorization, "projection authorization boundary was promoted", code="authorization_drift")
    expected_side_effects = {
        "kernel_started": False,
        "native_started": False,
        "privileged_probe_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "gate_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "completion_mutation": 0,
        "plan_mutation": 0,
    }
    _require(value["side_effects"] == expected_side_effects, "projection side effects are non-zero", code="side_effect_drift")
    return value


def validate_projection(value: Any) -> dict[str, Any]:
    """Public structural validator used by tests and downstream readers."""

    return _validate_projection(value)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    """Verify the checked-in projection byte-for-byte against its inputs."""

    value, _ = _read_bounded_json(path, label="target-kernel readiness projection report")
    _validate_projection(value)
    expected = build_projection()
    if value != expected:
        _fail("checked-in readiness projection does not match its bound inputs", code="report_binding_drift")
    return value


def write_report(path: str | Path = DEFAULT_REPORT) -> Path:
    """Write one deterministic report; no execution or registry state is touched."""

    output = _canonical_path(path)
    payload = (json.dumps(build_projection(), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return output


# Compatibility aliases used by adjacent evidence contracts.
build_report = build_projection
verify_projection = verify_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write the deterministic projection report")
    group.add_argument("--verify", action="store_true", help="verify the checked-in projection report")
    args = parser.parse_args(argv)
    if args.write:
        print(write_report().relative_to(LAB_ROOT))
        return 0
    result = verify_report() if args.verify else build_projection()
    print(json.dumps({key: result[key] for key in ("schema", "status", "scope_id", "blocking_gaps", "authorization")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
