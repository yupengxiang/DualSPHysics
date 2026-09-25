"""Strict, non-authorizing in-memory codec for the future F4 V3 bundle.

This module validates serialization, metadata reference graphs, and digest
consistency only. It does not verify evaluation-source semantics, read
paths/descriptors, establish producer identity, mint a capability, verify
fs-verity, or authorize a batch.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


DOMAIN_SEPARATOR = b"CORE-F4-QUALIFICATION-BUNDLE-V3\n"
ROLE_ORDER = ("binding_admission", "evaluation_admission", "evaluation_source_raw")
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
OUTER_SCHEMA = "core.f4.tallwall120.production_qualification_admission.v1"
BINDING_ADMISSION_SCHEMA = "core.f4.tallwall120.production_qualification_binding_admission.v2"
EVALUATION_ADMISSION_SCHEMA = "core.f4.tallwall120.qualification_evaluation_admission.v1"
EVALUATION_SOURCE_SCHEMA = "core.f4.tallwall120.qualification_evaluation.v2"
F4_SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
F4_REVISION_ID = "F4_tallwall120_13plus2_v2"
_OBJECT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REF_KEYS = frozenset({
    "stage", "role", "object_id", "target_schema", "bytes", "raw_sha256",
    "canonical_json_sha256",
})
_CHECK_KEYS = (
    "static_contract", "matrix_complete", "all_case_hard_mass_event_gates",
    "spatial", "independent_checks", "time_and_output",
    "cell12_reuse_verified", "cell12_reuse_does_not_inherit_qualification",
)
_BINDING_KEYS = frozenset({
    "schema", "scope_id", "revision_id", "manifest_sha256", "evaluation_raw_sha256",
    "reevaluation_sha256", "evaluation_admission_canonical_json_sha256",
    "matrix_complete", "T1_numerical", "cell_indices", "passed_cell_indices",
    "missing_indices", "failure_indices", "checks", "artifact_bindings_verified",
    "declaration_consistent",
})
_EVALUATION_KEYS = frozenset({
    "schema", "scope_id", "revision_id", "manifest_sha256", "evaluation_source_ref",
    "evaluation_raw_sha256", "evaluation_canonical_json_sha256", "cell_indices",
    "passed_cell_indices", "missing_indices", "failure_indices", "checks",
    "matrix_complete", "T1_numerical", "artifact_bindings_verified",
    "declaration_consistent", "promotion_status",
})
_BINDING_WRAPPER_KEYS = frozenset({"schema", "binding", "evaluation_ref"})
_OUTER_KEYS = frozenset({"schema", "mode", "scope_id", "binding_ref", "evaluation_ref"})
_EVALUATION_SOURCE_BASE_KEYS = frozenset({
    "schema", "scope_id", "revision_id", "qualification_claim", "static_manifest",
    "static_manifest_sha256", "static_contract_pass", "static_issues", "binding_results",
    "cell_count", "scheduled_solver_cells", "reused_canary_cells", "matrix_complete",
    "T1_numerical", "promotion_status",
})
_EVALUATION_SOURCE_MATRIX_KEYS = _EVALUATION_SOURCE_BASE_KEYS | frozenset({"cells", "missing", "failures"})
_EVALUATION_SOURCE_COMPLETE_KEYS = _EVALUATION_SOURCE_MATRIX_KEYS | frozenset({"comparisons", "checks"})
_SCHEDULED_INDICES = frozenset((*range(12), 13, 14))
_ALL_INDICES = tuple(range(15))
_MAX_REF_BYTES = 1_073_741_824


class BundleCodecError(ValueError):
    """Raw bundle bytes or serialization fields violate the codec contract."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleCodecError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise BundleCodecError(f"non-finite JSON constant is forbidden: {value}")


def _parse_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise BundleCodecError("JSON number is outside the finite float domain")
    return value


def strict_json_object(raw: bytes, *, label: str = "JSON document") -> dict[str, Any]:
    """Parse exact raw UTF-8 bytes, rejecting duplicate keys and non-finite values."""
    if type(raw) is not bytes:
        raise BundleCodecError(f"{label} must be exact bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise BundleCodecError(f"{label} is not strict UTF-8") from error
    try:
        value = json.loads(
            text,
            strict=True,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
        )
    except BundleCodecError:
        raise
    except (json.JSONDecodeError, ValueError, OverflowError, RecursionError) as error:
        raise BundleCodecError(f"{label} is not valid strict JSON") from error
    if type(value) is not dict:
        raise BundleCodecError(f"{label} top level must be a JSON object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Encode V12 canonical JSON bytes (default ASCII escaping, no newline)."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise BundleCodecError("value is not canonically JSON-serializable") from error
    return encoded


def document_digests(raw: bytes, *, label: str = "JSON document") -> tuple[str, str]:
    """Return (raw-byte SHA-256, canonical-parsed-object SHA-256)."""
    parsed = strict_json_object(raw, label=label)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    canonical_sha256 = hashlib.sha256(canonical_json_bytes(parsed)).hexdigest()
    return raw_sha256, canonical_sha256


def qualification_bundle_sha256(envelope_raw: bytes, role_documents: dict[str, bytes]) -> str:
    """Compute the V13 domain-separated object-graph digest, without authorizing it."""
    if type(role_documents) is not dict or set(role_documents) != set(ROLE_ORDER):
        raise BundleCodecError("role_documents must contain exactly the three V3 roles")
    if type(envelope_raw) is not bytes:
        raise BundleCodecError("qualification envelope must be exact bytes")
    strict_json_object(envelope_raw, label="qualification envelope")
    if len(envelope_raw) >= 1 << 64:
        raise BundleCodecError("qualification envelope exceeds U64 length")

    encoded = bytearray(DOMAIN_SEPARATOR)
    encoded.extend(len(envelope_raw).to_bytes(8, "big"))
    encoded.extend(envelope_raw)
    for role in ROLE_ORDER:
        role_bytes = role.encode("ascii")
        if len(role_bytes) >= 1 << 16:
            raise BundleCodecError("bundle role exceeds U16 length")
        raw = role_documents[role]
        raw_sha256, canonical_sha256 = document_digests(raw, label=role)
        if not _LOWER_SHA256.fullmatch(raw_sha256) or not _LOWER_SHA256.fullmatch(canonical_sha256):
            raise BundleCodecError("internal digest encoding is invalid")
        encoded.extend(len(role_bytes).to_bytes(2, "big"))
        encoded.extend(role_bytes)
        encoded.extend(bytes.fromhex(raw_sha256))
        encoded.extend(bytes.fromhex(canonical_sha256))
    return hashlib.sha256(encoded).hexdigest()


def positive_builtin_int(value: Any, *, name: str) -> int:
    """Validate an exact positive JSON integer; bool is deliberately rejected."""
    if type(value) is not int or value <= 0:
        raise BundleCodecError(f"{name} must be an exact positive integer")
    return value


def _require_exact_object(value: Any, keys: frozenset[str], *, name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise BundleCodecError(f"{name} fields do not match the exact schema")
    return value


def _require_string(value: Any, *, name: str, expected: str | None = None) -> str:
    if type(value) is not str or not value or (expected is not None and value != expected):
        raise BundleCodecError(f"{name} is invalid")
    return value


def _require_sha256(value: Any, *, name: str) -> str:
    if type(value) is not str or not _LOWER_SHA256.fullmatch(value):
        raise BundleCodecError(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _validate_ref(value: Any, *, role: str, target_schema: str) -> dict[str, Any]:
    ref = _require_exact_object(value, _REF_KEYS, name=f"{role} ref")
    _require_string(ref["stage"], name=f"{role}.stage", expected="qualification")
    _require_string(ref["role"], name=f"{role}.role", expected=role)
    object_id = _require_string(ref["object_id"], name=f"{role}.object_id")
    if not _OBJECT_ID.fullmatch(object_id) or object_id in {".", ".."}:
        raise BundleCodecError(f"{role}.object_id is outside the identifier domain")
    _require_string(ref["target_schema"], name=f"{role}.target_schema", expected=target_schema)
    size = positive_builtin_int(ref["bytes"], name=f"{role}.bytes")
    if size > _MAX_REF_BYTES:
        raise BundleCodecError(f"{role}.bytes exceeds the reference limit")
    _require_sha256(ref["raw_sha256"], name=f"{role}.raw_sha256")
    _require_sha256(ref["canonical_json_sha256"], name=f"{role}.canonical_json_sha256")
    return ref


def _parse_referenced_document(
    ref: dict[str, Any], raw: bytes, *, role: str, target_schema: str
) -> tuple[dict[str, Any], str]:
    if type(raw) is not bytes or len(raw) != ref["bytes"]:
        raise BundleCodecError(f"{role} raw byte length does not match its ref")
    parsed = strict_json_object(raw, label=role)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    canonical_sha256 = hashlib.sha256(canonical_json_bytes(parsed)).hexdigest()
    if raw_sha256 != ref["raw_sha256"]:
        raise BundleCodecError(f"{role} raw SHA-256 does not match its ref")
    if canonical_sha256 != ref["canonical_json_sha256"]:
        raise BundleCodecError(f"{role} canonical JSON SHA-256 does not match its ref")
    if parsed.get("schema") != target_schema or type(parsed.get("schema")) is not str:
        raise BundleCodecError(f"{role} target schema mismatch")
    return parsed, canonical_sha256


def _validate_evaluation_source_shape(value: dict[str, Any]) -> None:
    """Validate the legacy evaluator-v2 serialization shape, never its claims."""
    fields = frozenset(value)
    if fields not in {
        _EVALUATION_SOURCE_BASE_KEYS,
        _EVALUATION_SOURCE_MATRIX_KEYS,
        _EVALUATION_SOURCE_COMPLETE_KEYS,
    }:
        raise BundleCodecError("evaluation source fields do not match an exact evaluator-v2 result shape")
    _require_string(value["schema"], name="source.schema", expected=EVALUATION_SOURCE_SCHEMA)
    _require_string(value["scope_id"], name="source.scope_id", expected=F4_SCOPE_ID)
    _require_string(value["revision_id"], name="source.revision_id", expected=F4_REVISION_ID)
    _require_string(value["qualification_claim"], name="source.qualification_claim", expected="none")
    _require_string(value["static_manifest"], name="source.static_manifest")
    _require_sha256(value["static_manifest_sha256"], name="source.static_manifest_sha256")
    if type(value["static_contract_pass"]) is not bool:
        raise BundleCodecError("source.static_contract_pass must be an exact boolean")
    if type(value["static_issues"]) is not list or any(type(item) is not str for item in value["static_issues"]):
        raise BundleCodecError("source.static_issues must be an array of strings")
    if type(value["binding_results"]) is not dict or any(type(key) is not str for key in value["binding_results"]):
        raise BundleCodecError("source.binding_results must be an object with string keys")
    if positive_builtin_int(value["cell_count"], name="source.cell_count") != 15:
        raise BundleCodecError("source.cell_count must equal the frozen 15-cell denominator")
    if _validate_indices(value["scheduled_solver_cells"], name="source.scheduled_solver_cells") != sorted(_SCHEDULED_INDICES):
        raise BundleCodecError("source scheduled solver cells differ from the frozen set")
    if _validate_indices(value["reused_canary_cells"], name="source.reused_canary_cells") != [12]:
        raise BundleCodecError("source reused canary cells differ from the frozen set")
    for key in ("matrix_complete", "T1_numerical"):
        if type(value[key]) is not bool:
            raise BundleCodecError(f"source.{key} must be an exact boolean")
    promotion_status = value["promotion_status"]
    if type(promotion_status) is not str or promotion_status not in {
        "blocked_until_14_scheduled_products_and_all_gates",
        "blocked_until_all_gates",
        "qualified_candidate_pending_root_review",
    }:
        raise BundleCodecError("source.promotion_status is outside the frozen enum")
    if fields != _EVALUATION_SOURCE_BASE_KEYS:
        for key in ("cells", "missing", "failures"):
            if type(value[key]) is not list or any(type(item) is not dict for item in value[key]):
                raise BundleCodecError(f"source.{key} must be an array of objects")
    if fields == _EVALUATION_SOURCE_COMPLETE_KEYS:
        if type(value["comparisons"]) is not list or any(type(item) is not dict for item in value["comparisons"]):
            raise BundleCodecError("source.comparisons must be an array of objects")
        _validate_checks(value["checks"], name="source.checks")


def _validate_indices(value: Any, *, name: str) -> list[int]:
    if type(value) is not list or any(type(item) is not int or item not in _ALL_INDICES for item in value):
        raise BundleCodecError(f"{name} must contain exact builtin indices in 0..14")
    if value != sorted(set(value)):
        raise BundleCodecError(f"{name} must be sorted and unique")
    return value


def _validate_checks(value: Any, *, name: str) -> dict[str, bool]:
    checks = _require_exact_object(value, frozenset(_CHECK_KEYS), name=name)
    if any(type(checks[key]) is not bool for key in _CHECK_KEYS):
        raise BundleCodecError(f"{name} values must be exact booleans")
    return checks


def _validate_evaluation_projection(
    value: dict[str, Any], *, evaluation_source_ref: dict[str, Any]
) -> None:
    projection = _require_exact_object(value, _EVALUATION_KEYS, name="evaluation admission")
    _require_string(projection["schema"], name="evaluation.schema", expected=EVALUATION_ADMISSION_SCHEMA)
    _require_string(projection["scope_id"], name="evaluation.scope_id", expected=F4_SCOPE_ID)
    _require_string(projection["revision_id"], name="evaluation.revision_id", expected=F4_REVISION_ID)
    for key in ("manifest_sha256", "evaluation_raw_sha256", "evaluation_canonical_json_sha256"):
        _require_sha256(projection[key], name=f"evaluation.{key}")
    source_ref = _validate_ref(
        projection["evaluation_source_ref"],
        role="qualification_evaluation_raw",
        target_schema=EVALUATION_SOURCE_SCHEMA,
    )
    if source_ref != evaluation_source_ref:
        raise BundleCodecError("evaluation source ref does not match its resolved document")
    for key in ("matrix_complete", "T1_numerical", "artifact_bindings_verified", "declaration_consistent"):
        if type(projection[key]) is not bool:
            raise BundleCodecError(f"evaluation.{key} must be an exact boolean")
    cells = _validate_indices(projection["cell_indices"], name="evaluation.cell_indices")
    passed = _validate_indices(projection["passed_cell_indices"], name="evaluation.passed_cell_indices")
    missing = _validate_indices(projection["missing_indices"], name="evaluation.missing_indices")
    failures = _validate_indices(projection["failure_indices"], name="evaluation.failure_indices")
    if (set(passed) & set(missing) or set(passed) & set(failures)
            or set(missing) & set(failures)
            or set(passed) | set(missing) | set(failures) != set(_ALL_INDICES)):
        raise BundleCodecError("evaluation cell index sets are not a complete disjoint partition")
    if cells != sorted((*passed, *failures)):
        raise BundleCodecError("evaluation.cell_indices is not passed union failures")
    checks = _validate_checks(projection["checks"], name="evaluation.checks")
    matrix_complete = passed == list(_ALL_INDICES) and not missing and not failures
    if projection["matrix_complete"] is not matrix_complete:
        raise BundleCodecError("evaluation.matrix_complete does not match the cell partition")
    expected_t1 = bool(
        matrix_complete and all(checks.values())
        and projection["artifact_bindings_verified"]
        and projection["declaration_consistent"]
    )
    if projection["T1_numerical"] is not expected_t1:
        raise BundleCodecError("evaluation.T1_numerical does not match the frozen predicate")
    if projection["evaluation_raw_sha256"] != source_ref["raw_sha256"]:
        raise BundleCodecError("evaluation raw digest does not match its source ref")
    if projection["evaluation_canonical_json_sha256"] != source_ref["canonical_json_sha256"]:
        raise BundleCodecError("evaluation canonical digest does not match its source ref")
    if projection["promotion_status"] != _promotion_status(missing, expected_t1):
        raise BundleCodecError("evaluation promotion_status is not canonically derived")


def _promotion_status(missing: list[int], t1_numerical: bool) -> str:
    if _SCHEDULED_INDICES.intersection(missing):
        return "blocked_until_14_scheduled_products_and_all_gates"
    if t1_numerical:
        return "qualified_candidate_pending_root_review"
    return "blocked_until_all_gates"


def inspect_untrusted_admission_envelope(
    envelope_raw: bytes, role_documents: dict[str, bytes]
) -> dict[str, Any]:
    """Check the V12/V13 in-memory reference graph without minting trust.

    Bytes are caller-supplied here, not descriptor-root snapshots. A successful
    report is therefore content-consistency evidence only and can never be
    consumed as a qualification capability.
    """
    envelope = strict_json_object(envelope_raw, label="qualification envelope")
    envelope = _require_exact_object(envelope, _OUTER_KEYS, name="qualification envelope")
    _require_string(envelope["schema"], name="envelope.schema", expected=OUTER_SCHEMA)
    mode = envelope["mode"]
    if type(mode) is not str or mode not in {"preparation_only", "formal_release"}:
        raise BundleCodecError("qualification envelope mode is invalid")
    _require_string(envelope["scope_id"], name="envelope.scope_id", expected=F4_SCOPE_ID)
    if type(role_documents) is not dict or set(role_documents) != set(ROLE_ORDER):
        raise BundleCodecError("role_documents must contain exactly the three V3 roles")

    binding_ref = _validate_ref(
        envelope["binding_ref"], role="qualification_binding_admission",
        target_schema=BINDING_ADMISSION_SCHEMA,
    )
    outer_evaluation_ref = envelope["evaluation_ref"]
    if mode == "preparation_only":
        if outer_evaluation_ref is not None:
            raise BundleCodecError("preparation_only envelope must have a null outer evaluation_ref")
        outer_evaluation_ref = None
    else:
        outer_evaluation_ref = _validate_ref(
            outer_evaluation_ref, role="qualification_evaluation_admission",
            target_schema=EVALUATION_ADMISSION_SCHEMA,
        )

    binding_raw = role_documents["binding_admission"]
    evaluation_raw = role_documents["evaluation_admission"]
    source_raw = role_documents["evaluation_source_raw"]
    binding, _ = _parse_referenced_document(
        binding_ref, binding_raw, role="qualification_binding_admission",
        target_schema=BINDING_ADMISSION_SCHEMA,
    )
    binding = _require_exact_object(binding, _BINDING_WRAPPER_KEYS, name="binding admission wrapper")
    nested_binding = _require_exact_object(binding["binding"], _BINDING_KEYS, name="binding projection")
    _require_string(nested_binding["schema"], name="binding.schema", expected=BINDING_ADMISSION_SCHEMA)
    _require_string(nested_binding["scope_id"], name="binding.scope_id", expected=F4_SCOPE_ID)
    _require_string(nested_binding["revision_id"], name="binding.revision_id", expected=F4_REVISION_ID)
    for key in (
        "manifest_sha256", "evaluation_raw_sha256", "reevaluation_sha256",
        "evaluation_admission_canonical_json_sha256",
    ):
        _require_sha256(nested_binding[key], name=f"binding.{key}")
    nested_evaluation_ref = _validate_ref(
        binding["evaluation_ref"], role="qualification_evaluation_admission",
        target_schema=EVALUATION_ADMISSION_SCHEMA,
    )
    for key in ("matrix_complete", "T1_numerical", "artifact_bindings_verified", "declaration_consistent"):
        if type(nested_binding[key]) is not bool:
            raise BundleCodecError(f"binding.{key} must be an exact boolean")
    binding_cells = _validate_indices(nested_binding["cell_indices"], name="binding.cell_indices")
    binding_passed = _validate_indices(nested_binding["passed_cell_indices"], name="binding.passed_cell_indices")
    binding_missing = _validate_indices(nested_binding["missing_indices"], name="binding.missing_indices")
    binding_failures = _validate_indices(nested_binding["failure_indices"], name="binding.failure_indices")
    binding_checks = _validate_checks(nested_binding["checks"], name="binding.checks")

    evaluation_ref, evaluation_canonical_sha256 = _parse_referenced_document(
        nested_evaluation_ref, evaluation_raw, role="qualification_evaluation_admission",
        target_schema=EVALUATION_ADMISSION_SCHEMA,
    )
    if mode == "formal_release" and outer_evaluation_ref != nested_evaluation_ref:
        raise BundleCodecError("outer and binding evaluation refs differ in formal_release mode")
    source_ref = _validate_ref(
        evaluation_ref.get("evaluation_source_ref"),
        role="qualification_evaluation_raw", target_schema=EVALUATION_SOURCE_SCHEMA,
    )
    source_value, _ = _parse_referenced_document(
        source_ref, source_raw, role="qualification_evaluation_raw",
        target_schema=EVALUATION_SOURCE_SCHEMA,
    )
    _validate_evaluation_source_shape(source_value)
    _validate_evaluation_projection(evaluation_ref, evaluation_source_ref=source_ref)

    projection_fields = (
        "scope_id", "revision_id", "manifest_sha256", "evaluation_raw_sha256",
        "matrix_complete", "T1_numerical", "cell_indices", "passed_cell_indices",
        "missing_indices", "failure_indices", "checks", "artifact_bindings_verified",
        "declaration_consistent",
    )
    if any(nested_binding[key] != evaluation_ref[key] for key in projection_fields):
        raise BundleCodecError("binding and evaluation projection fields differ")
    if (binding_cells != evaluation_ref["cell_indices"]
            or binding_passed != evaluation_ref["passed_cell_indices"]
            or binding_missing != evaluation_ref["missing_indices"]
            or binding_failures != evaluation_ref["failure_indices"]
            or binding_checks != evaluation_ref["checks"]):
        raise BundleCodecError("binding and evaluation projection collections differ")
    if nested_binding["reevaluation_sha256"] != evaluation_ref["evaluation_canonical_json_sha256"]:
        raise BundleCodecError("binding reevaluation digest does not match evaluation projection")
    if nested_binding["evaluation_admission_canonical_json_sha256"] != evaluation_canonical_sha256:
        raise BundleCodecError("binding evaluation-admission digest does not match referenced object")

    return {
        "status": "metadata_ref_graph_consistent_untrusted",
        "mode": mode,
        "qualification_bundle_sha256": qualification_bundle_sha256(envelope_raw, role_documents),
        "formal_qualification_admitted": False,
        "capability_minted": False,
        "evaluation_source_semantics_verified": False,
        "object_allowlist_verified": False,
        "descriptor_root_verified": False,
        "producer_identity_verified": False,
    }
