#!/usr/bin/env python3
"""Bind Core typed evidence to an existing cross-host root-review decision.

This is a disjoint, synthetic-only sidecar for the gap identified by the
independent-reproduction audit.  It does not import or invoke either of the
existing Core verifiers.  Instead it consumes bounded in-memory canonical JSON
bytes and re-checks the narrow boundary needed to join them:

* the five typed evidence categories and their six artifact roles;
* source/reproduction host identity and two distinct data roots;
* reader -> autonomous prediction -> scoring output hashes; and
* the diagnostic decision emitted by ``core_cross_host_root_review.py``.

Every artifact is content-addressed by a portable path, byte count and
SHA-256.  The adapter also checks an exact canonical binding claim that joins
the independent-preflight artifact, role/output artifacts and root-review
decision hash.  A caller cannot turn a boolean ``trusted_root`` claim into
authority: that field is rejected, and this sidecar never authenticates or
mints a trust root.  A successful result is therefore still diagnostic-only.

No production file, registry, ledger, gate, workload, solver, worker, GPU or
queue is read or mutated.  The CLI writes only the newly requested diagnostic
report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "core.reproduction.typed_evidence_root_review_adapter.v1"
REPORT_SCHEMA = "core.reproduction.typed_evidence_root_review_adapter_report.v1"
RECORD_ID = "core-independent-reproduction-typed-evidence-root-review-adapter-v1"
REPORT_ID = "core-independent-reproduction-typed-evidence-root-review-adapter-report-v1"
STATUS = "synthetic_only_typed_evidence_root_review_bound"
REPORT_STATUS = "synthetic_only_non_authorizing_typed_evidence_root_review"

PREFLIGHT_SCHEMA = "core.reproduction.independent_preflight.v1"
ROOT_REVIEW_SCHEMA = "core.reproduction.root_review.v1"
HOST_SCHEMA = "core.reproduction.host_identity.v1"
ROOT_SCHEMA = "core.reproduction.data_roots.v1"
MANIFEST_SCHEMA = "core.reproduction.package_manifest.v1"
COMPONENT_SCHEMA = "core.reproduction.component.v1"
BINDING_SCHEMA = "core.reproduction.typed_evidence_root_review_binding.v1"

CATEGORIES = ("host_pair", "data_roots", "reader", "prediction", "scoring")
ROLES = (
    "source_host",
    "reproduction_host",
    "data_roots",
    "reader",
    "prediction",
    "scoring",
)
COMPONENTS = ("reader", "prediction", "scoring")
ROLE_TO_CATEGORY = {
    "source_host": "host_pair",
    "reproduction_host": "host_pair",
    "data_roots": "data_roots",
    "reader": "reader",
    "prediction": "prediction",
    "scoring": "scoring",
}

MAX_ARTIFACT_BYTES = 64 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")

HOST_FIELDS = frozenset({
    "schema", "role", "category", "passed", "hostname", "physical_host_id",
    "diagnostic_only", "formal", "full_product_reproduction", "input_origin",
})
DATA_ROOT_FIELDS = frozenset({
    "schema", "role", "category", "passed", "source_data_root",
    "reproduction_data_root", "different_data_root", "source_manifest",
    "reproduction_manifest", "source_manifest_sha256",
    "reproduction_manifest_sha256", "diagnostic_only", "formal",
    "full_product_reproduction", "input_origin",
})
MANIFEST_FIELDS = frozenset({
    "schema", "data_root", "package_sha256", "diagnostic_only", "formal",
    "full_product_reproduction", "input_origin",
})
COMPONENT_FIELDS = frozenset({
    "schema", "role", "category", "component", "passed",
    "reader_reproduced", "prediction_reproduced", "scoring_reproduced",
    "physical_host_id", "data_root", "output_report", "bindings",
    "diagnostic_only", "formal", "full_product_reproduction", "input_origin",
})
READER_OUTPUT_FIELDS = frozenset({
    "schema", "component", "passed", "physical_host_id", "data_root",
    "diagnostic_only", "formal", "full_product_reproduction",
    "future_state_inputs", "input_origin",
})
PREDICTION_OUTPUT_FIELDS = frozenset({
    "schema", "component", "passed", "physical_host_id", "data_root",
    "diagnostic_only", "formal", "full_product_reproduction", "autonomous",
    "full_horizon", "future_state_inputs", "predictor_future_state_inputs",
    "input_origin",
})
SCORING_OUTPUT_FIELDS = frozenset({
    "schema", "component", "passed", "physical_host_id", "data_root",
    "diagnostic_only", "formal", "full_product_reproduction", "metrics",
    "cases", "predictor_future_state_inputs", "input_origin",
})
ROOT_REVIEW_FIELDS = frozenset({
    "all_eight_required_outputs_verified", "diagnostic_only",
    "formal_training_count", "full_core_reproduction_proven", "headline",
    "receipt_sha256", "registered_comparison_pass", "schema", "scope",
    "two_terminal_reports_verified",
})
ROOT_DECISION_FIELDS = (
    "schema", "registered_comparison_pass", "two_terminal_reports_verified",
    "all_eight_required_outputs_verified", "diagnostic_only",
    "formal_training_count", "full_core_reproduction_proven", "scope",
)
FIXTURE_FIELDS = frozenset({
    "typed_evidence", "manifest_artifacts", "component_outputs", "preflight",
    "root_review", "binding_claim",
})
ARTIFACT_FIELDS = frozenset({"path", "sha256", "bytes", "raw"})

FORBIDDEN_TRUST_FIELDS = frozenset({
    "trusted", "trusted_root", "root_trusted", "root_authority",
    "capability_minted", "execution_authority",
})

NON_AUTHORIZING_BOUNDARY = {
    "diagnostic_only": True,
    "capability_minted": False,
    "formal_training_count": 0,
    "formal_training_admission": False,
    "formal_admission": False,
    "full_product_reproduction": False,
    "real_cross_host_reproduction": False,
    "cross_host_claim": False,
    "credit": 0,
    "qualification_credit": 0,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
}


class TypedEvidenceRootReviewAdapterError(ValueError):
    """A synthetic typed-evidence/root-review contract failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise TypedEvidenceRootReviewAdapterError(code, message)


def canonical_json_bytes(value: Any, *, label: str = "value") -> bytes:
    """Encode the one canonical JSON representation used by every binding."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise TypedEvidenceRootReviewAdapterError(
            "NON_CANONICAL_JSON", f"{label} is not canonical JSON serializable"
        ) from error


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(value: Any, *, label: str) -> str:
    return _sha256(canonical_json_bytes(value, label=label))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _parse_canonical_object(raw: Any, *, label: str) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_ARTIFACT_BYTES,
             "ARTIFACT_BYTES_INVALID", f"{label} raw bytes exceed the synthetic bound")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise TypedEvidenceRootReviewAdapterError(
            "INVALID_CANONICAL_JSON", f"{label} is not valid canonical JSON"
        ) from error
    _require(type(value) is dict, "JSON_OBJECT_REQUIRED", f"{label} must be a JSON object")
    _require(canonical_json_bytes(value, label=label) == raw,
             "NON_CANONICAL_JSON", f"{label} bytes are not the exact canonical encoding")
    return value


def _validate_sha(value: Any, *, code: str, label: str) -> str:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             code, f"{label} is not a lowercase SHA-256")
    return value


def _portable_path(value: Any, *, label: str) -> str:
    _require(type(value) is str and bool(value), "PATH_INVALID", f"{label} path is missing")
    _require("\\" not in value and not value.startswith("/")
             and DRIVE_PATH_RE.match(value) is None,
             "PATH_NOT_PORTABLE", f"{label} path is not portable")
    parts = value.split("/")
    _require(all(part not in ("", ".", "..") for part in parts),
             "PATH_NOT_PORTABLE", f"{label} path contains an escaping component")
    return value


def _public_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("path", "sha256", "bytes")}


def _verify_artifact(row: Any, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(isinstance(row, Mapping) and set(row) == ARTIFACT_FIELDS,
             "ARTIFACT_FIELDS_NOT_EXACT", f"{label} artifact fields are not exact")
    path = _portable_path(row.get("path"), label=label)
    raw = row.get("raw")
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_ARTIFACT_BYTES,
             "ARTIFACT_BYTES_INVALID", f"{label} raw bytes are outside the bounded contract")
    declared_bytes = row.get("bytes")
    _require(type(declared_bytes) is int and declared_bytes >= 0,
             "ARTIFACT_BYTES_INVALID", f"{label} declared byte count is invalid")
    _require(declared_bytes == len(raw), "ARTIFACT_BYTES_MISMATCH",
             f"{label} declared byte count does not match raw bytes")
    declared_sha = _validate_sha(row.get("sha256"), code="ARTIFACT_HASH_INVALID",
                                 label=f"{label} artifact hash")
    observed_sha = _sha256(raw)
    _require(declared_sha == observed_sha, "ARTIFACT_HASH_MISMATCH",
             f"{label} declared hash does not match raw bytes")
    payload = _parse_canonical_object(raw, label=label)
    return payload, _public_ref(row)


def _require_exact_fields(payload: Mapping[str, Any], expected: frozenset[str], *,
                          label: str) -> None:
    _require(set(payload) == expected, "PAYLOAD_FIELDS_NOT_EXACT",
             f"{label} fields are not exact")


def _validate_non_formal(payload: Mapping[str, Any], *, label: str) -> None:
    _require(payload.get("diagnostic_only") is True,
             "DIAGNOSTIC_MARKER_MISSING", f"{label} is not diagnostic-only")
    _require(payload.get("formal") is False
             and payload.get("full_product_reproduction") is False,
             "DIAGNOSTIC_FORMAL_CONFLICT",
             f"{label} attempts to present diagnostic evidence as formal/product evidence")
    _require(payload.get("input_origin") == "synthetic_fixture",
             "NON_SYNTHETIC_INPUT", f"{label} is not marked synthetic_fixture")


def _canonical_data_root(value: Any, *, label: str) -> str:
    _require(type(value) is str and value.startswith("/") and "\\" not in value,
             "DATA_ROOT_INVALID", f"{label} is not an absolute POSIX root")
    parts = value.split("/")
    _require(".." not in parts, "DATA_ROOT_INVALID", f"{label} contains '..'")
    normalized = posixpath.normpath(value)
    _require(normalized.startswith("/") and normalized != ".",
             "DATA_ROOT_INVALID", f"{label} cannot be canonicalized")
    return normalized


def _validate_host(payload: Mapping[str, Any], *, role: str) -> dict[str, str]:
    _require_exact_fields(payload, HOST_FIELDS, label=role)
    _require(payload.get("schema") == HOST_SCHEMA, "HOST_SCHEMA_MISMATCH",
             f"{role} schema is unsupported")
    _require(payload.get("role") == role and payload.get("category") == "host_pair",
             "ROLE_BINDING_MISMATCH", f"{role} role/category binding is inconsistent")
    _require(payload.get("passed") is True, "HOST_EVIDENCE_NOT_PASSED",
             f"{role} evidence is not passed")
    _validate_non_formal(payload, label=role)
    hostname = payload.get("hostname")
    physical_host_id = payload.get("physical_host_id")
    _require(type(hostname) is str and bool(hostname.strip()), "HOSTNAME_MISSING",
             f"{role} hostname is missing")
    _require(type(physical_host_id) is str and bool(physical_host_id.strip()),
             "PHYSICAL_HOST_ID_MISSING", f"{role} physical host id is missing")
    return {"hostname": hostname.strip(), "physical_host_id": physical_host_id.strip()}


def _host_key(value: str) -> str:
    return value.rstrip(".").casefold()


def _validate_manifest_artifacts(
    rows: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    expected = {"source_manifest", "reproduction_manifest"}
    _require(set(rows) == expected, "MANIFEST_ROLE_SET_MISMATCH",
             "exactly source_manifest and reproduction_manifest are required")
    payloads: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    for name in ("source_manifest", "reproduction_manifest"):
        payload, ref = _verify_artifact(rows[name], label=name)
        _require_exact_fields(payload, MANIFEST_FIELDS, label=name)
        _require(payload.get("schema") == MANIFEST_SCHEMA, "MANIFEST_SCHEMA_MISMATCH",
                 f"{name} schema is unsupported")
        _validate_non_formal(payload, label=name)
        _validate_sha(payload.get("package_sha256"), code="PACKAGE_HASH_INVALID",
                      label=f"{name} package hash")
        payloads[name] = payload
        refs[name] = ref
    _require(payloads["source_manifest"]["package_sha256"]
             == payloads["reproduction_manifest"]["package_sha256"],
             "PACKAGE_IDENTITY_MISMATCH", "source/reproduction package hashes differ")
    return payloads, refs


def _validate_data_roots(
    payload: Mapping[str, Any], manifest_payloads: Mapping[str, Mapping[str, Any]],
    manifest_refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    _require_exact_fields(payload, DATA_ROOT_FIELDS, label="data_roots")
    _require(payload.get("schema") == ROOT_SCHEMA, "DATA_ROOT_SCHEMA_MISMATCH",
             "data_roots schema is unsupported")
    _require(payload.get("role") == "data_roots"
             and payload.get("category") == "data_roots",
             "ROLE_BINDING_MISMATCH", "data_roots role/category binding is inconsistent")
    _require(payload.get("passed") is True and payload.get("different_data_root") is True,
             "DATA_ROOT_EVIDENCE_NOT_PASSED", "data_roots does not pass its distinct-root marker")
    _validate_non_formal(payload, label="data_roots")
    source = _canonical_data_root(payload.get("source_data_root"), label="source_data_root")
    reproduction = _canonical_data_root(
        payload.get("reproduction_data_root"), label="reproduction_data_root"
    )
    _require(source != reproduction, "DATA_ROOTS_NOT_DISTINCT",
             "source and reproduction data roots are canonically identical")

    for name, expected_root in (("source_manifest", source), ("reproduction_manifest", reproduction)):
        _require(_canonical_data_root(manifest_payloads[name].get("data_root"), label=f"{name}.data_root")
                 == expected_root, "MANIFEST_ROOT_MISMATCH",
                 f"{name} does not bind its declared data root")
        _require(payload.get(name) == manifest_refs[name], "NESTED_ARTIFACT_BINDING_MISMATCH",
                 f"data_roots {name} reference differs from its artifact")
        key = f"{name}_sha256"
        _require(payload.get(key) == manifest_refs[name]["sha256"],
                 "NESTED_ARTIFACT_BINDING_MISMATCH",
                 f"data_roots {key} differs from its manifest artifact hash")
    return {
        "source_data_root": source,
        "reproduction_data_root": reproduction,
        "different_data_root": True,
        "package_sha256": manifest_payloads["source_manifest"]["package_sha256"],
        "manifests": {
            name: {
                "artifact": dict(manifest_refs[name]),
                "data_root": root,
                "package_sha256": manifest_payloads[name]["package_sha256"],
            }
            for name, root in (("source_manifest", source), ("reproduction_manifest", reproduction))
        },
    }


def _output_fields(component: str) -> frozenset[str]:
    if component == "reader":
        return READER_OUTPUT_FIELDS
    if component == "prediction":
        return PREDICTION_OUTPUT_FIELDS
    return SCORING_OUTPUT_FIELDS


def _validate_output(
    payload: Mapping[str, Any], *, component: str, reproduction_host_id: str,
    reproduction_root: str,
) -> dict[str, Any]:
    _require_exact_fields(payload, _output_fields(component), label=f"{component} output")
    expected_schema = {
        "reader": "core.reader_reproduction.v1",
        "prediction": "core.model_reproduction.v1",
        "scoring": "core.model_reproduction.score.v1",
    }[component]
    _require(payload.get("schema") == expected_schema and payload.get("component") == component,
             "OUTPUT_SCHEMA_MISMATCH", f"{component} output schema/component is unsupported")
    _require(payload.get("passed") is True, "OUTPUT_NOT_PASSED",
             f"{component} output is not passed")
    _require(payload.get("physical_host_id") == reproduction_host_id
             and _canonical_data_root(payload.get("data_root"), label=f"{component}.data_root")
             == reproduction_root, "OUTPUT_HOST_ROOT_MISMATCH",
             f"{component} output is not bound to the reproduction host/root")
    _validate_non_formal(payload, label=f"{component} output")
    if component == "reader":
        _require(payload.get("future_state_inputs") is False,
                 "READER_FUTURE_STATE_INPUT", "reader output permits future-state inputs")
    elif component == "prediction":
        _require(payload.get("autonomous") is True and payload.get("full_horizon") is True,
                 "PREDICTION_CONTRACT_INCOMPLETE", "prediction output is not autonomous/full-horizon")
        _require(payload.get("future_state_inputs") is False
                 and payload.get("predictor_future_state_inputs") is False,
                 "PREDICTION_FUTURE_STATE_INPUT", "prediction output permits future-state inputs")
    else:
        _require(payload.get("predictor_future_state_inputs") is False,
                 "SCORING_FUTURE_STATE_INPUT", "scoring output permits future-state inputs")
        _require(payload.get("metrics") == {
            "registered_cases": 1, "complete_fraction": 1.0, "missing_execution": 0,
        } and payload.get("cases") == ["synthetic-case-0"],
                 "SCORING_CONTRACT_INCOMPLETE", "scoring output denominator is not exact")
    return {"schema": payload["schema"], "component": component}


def _validate_components(
    payloads: Mapping[str, Mapping[str, Any]], output_payloads: Mapping[str, Mapping[str, Any]],
    output_refs: Mapping[str, Mapping[str, Any]], *, reproduction_host_id: str,
    reproduction_root: str, reproduction_manifest_sha256: str,
    reader_output_sha256: str | None = None, prediction_output_sha256: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for component in COMPONENTS:
        payload = payloads[component]
        _require_exact_fields(payload, COMPONENT_FIELDS, label=component)
        _require(payload.get("schema") == COMPONENT_SCHEMA
                 and payload.get("role") == component
                 and payload.get("category") == component
                 and payload.get("component") == component,
                 "ROLE_BINDING_MISMATCH", f"{component} evidence role/category is inconsistent")
        _require(payload.get("passed") is True
                 and payload.get(f"{component}_reproduced") is True,
                 "COMPONENT_EVIDENCE_NOT_PASSED", f"{component} typed evidence is not passed")
        _validate_non_formal(payload, label=component)
        _require(payload.get("physical_host_id") == reproduction_host_id
                 and _canonical_data_root(payload.get("data_root"), label=f"{component}.data_root")
                 == reproduction_root, "COMPONENT_HOST_ROOT_MISMATCH",
                 f"{component} evidence is not bound to the reproduction host/root")
        bindings = payload.get("bindings")
        expected_bindings: dict[str, Any]
        if component == "reader":
            expected_bindings = {"reproduction_manifest_sha256": reproduction_manifest_sha256}
        elif component == "prediction":
            _require(reader_output_sha256 is not None, "COMPONENT_CHAIN_INCOMPLETE",
                     "prediction cannot be checked before reader output")
            expected_bindings = {"reader_output_sha256": reader_output_sha256}
        else:
            _require(reader_output_sha256 is not None and prediction_output_sha256 is not None,
                     "COMPONENT_CHAIN_INCOMPLETE", "scoring cannot be checked before upstream outputs")
            expected_bindings = {
                "reader_output_sha256": reader_output_sha256,
                "prediction_output_sha256": prediction_output_sha256,
            }
        _require(bindings == expected_bindings, "COMPONENT_CHAIN_HASH_MISMATCH",
                 f"{component} input/output binding is not exact")
        _require(payload.get("output_report") == output_refs[component],
                 "OUTPUT_ARTIFACT_BINDING_MISMATCH",
                 f"{component} output_report differs from its output artifact")
        _validate_output(
            output_payloads[component], component=component,
            reproduction_host_id=reproduction_host_id, reproduction_root=reproduction_root,
        )
        result[component] = {
            "component": component,
            "physical_host_id": reproduction_host_id,
            "data_root": reproduction_root,
            "output_report": dict(output_refs[component]),
            "output_schema": output_payloads[component]["schema"],
            "output_sha256": output_refs[component]["sha256"],
            "bindings": dict(bindings),
        }
    return result


def _preflight_projection(
    role_refs: Mapping[str, Mapping[str, Any]], *, source_host: Mapping[str, str],
    reproduction_host: Mapping[str, str], data_roots: Mapping[str, Any],
    components: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "pass",
        "passed": True,
        "structural_preflight_passed": True,
        "diagnostic_only": True,
        "capability_minted": False,
        "formal_admission": False,
        "formal_training_count": 0,
        "qualification_credit": 0,
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "supporting_evidence": {role: dict(role_refs[role]) for role in ROLES},
        "assembly": {
            "source_host": dict(source_host),
            "reproduction_host": dict(reproduction_host),
            "data_roots": data_roots,
            "components": components,
            "distinct_physical_hosts": True,
            "distinct_data_roots": True,
            "reader_typed": True,
            "autonomous_prediction_typed": True,
            "scoring_typed": True,
        },
        "next_required": [
            "independent hash-bound root-review decision adapter",
            "core_campaign independent_reproduction gate verification",
        ],
        "errors": [],
    }


def _root_decision_projection(root_review: Mapping[str, Any]) -> dict[str, Any]:
    return {key: root_review[key] for key in ROOT_DECISION_FIELDS}


def _validate_root_review(payload: Mapping[str, Any]) -> dict[str, Any]:
    forbidden = sorted(set(payload).intersection(FORBIDDEN_TRUST_FIELDS))
    _require(not forbidden, "CALLER_TRUSTED_ROOT_REJECTED",
             f"caller self-asserted trusted-root fields are rejected: {forbidden}")
    _require_exact_fields(payload, ROOT_REVIEW_FIELDS, label="cross-host root review")
    _require(payload.get("schema") == ROOT_REVIEW_SCHEMA, "ROOT_REVIEW_SCHEMA_MISMATCH",
             "cross-host root-review schema is unsupported")
    _require(payload.get("registered_comparison_pass") is True
             and payload.get("two_terminal_reports_verified") is True
             and payload.get("all_eight_required_outputs_verified") is True,
             "ROOT_REVIEW_NOT_VERIFIED", "root review did not verify its diagnostic pair")
    _require(payload.get("diagnostic_only") is True
             and payload.get("formal_training_count") == 0
             and payload.get("full_core_reproduction_proven") is False,
             "ROOT_REVIEW_SCOPE_INVALID", "root review carries a formal/product claim")
    _validate_sha(payload.get("receipt_sha256"), code="ROOT_REVIEW_RECEIPT_HASH_INVALID",
                  label="root-review receipt hash")
    scope = payload.get("scope")
    expected_scope = {
        "all_particle_axis": True,
        "case_id": "F3_DEV_08_a0p953125",
        "diagnostic_only": True,
        "family": "F3",
        "formal_training_count": 0,
        "full_horizon": True,
        "particle_count": 34560,
        "scientific_qualification": False,
        "split": "validation",
        "trajectory_frames": 836,
        "transitions": 835,
    }
    _require(scope == expected_scope, "ROOT_REVIEW_SCOPE_INVALID",
             "root-review scope differs from the existing cross-host decision")
    headline = payload.get("headline")
    _require(isinstance(headline, Mapping) and headline.get("passed") is True
             and headline.get("physics_and_failure_categories_passed") is True,
             "ROOT_REVIEW_HEADLINE_INVALID", "root-review headline is not a passing diagnostic headline")
    decision = _root_decision_projection(payload)
    return {
        "decision": decision,
        "decision_sha256": _sha256_json(decision, label="root-review decision"),
    }


def _evidence_manifest(
    role_refs: Mapping[str, Mapping[str, Any]],
    manifest_refs: Mapping[str, Mapping[str, Any]],
    output_refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "core.reproduction.typed_evidence_manifest.v1",
        "categories": list(CATEGORIES),
        "roles": {
            role: {"category": ROLE_TO_CATEGORY[role], "artifact": dict(role_refs[role])}
            for role in ROLES
        },
        "manifest_artifacts": {name: dict(manifest_refs[name]) for name in (
            "source_manifest", "reproduction_manifest"
        )},
        "component_output_artifacts": {
            component: dict(output_refs[component]) for component in COMPONENTS
        },
    }


def _expected_binding_claim(
    *, evidence_manifest_sha256: str, preflight_sha256: str,
    root_review_artifact_sha256: str, root_review_decision_sha256: str,
    role_refs: Mapping[str, Mapping[str, Any]],
    manifest_refs: Mapping[str, Mapping[str, Any]],
    output_refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": BINDING_SCHEMA,
        "record_id": RECORD_ID,
        "input_origin": "synthetic_fixture",
        "typed_evidence_manifest_sha256": evidence_manifest_sha256,
        "preflight_sha256": preflight_sha256,
        "root_review_artifact_sha256": root_review_artifact_sha256,
        "root_review_decision_sha256": root_review_decision_sha256,
        "role_artifacts": {role: dict(role_refs[role]) for role in ROLES},
        "manifest_artifacts": {name: dict(manifest_refs[name]) for name in (
            "source_manifest", "reproduction_manifest"
        )},
        "component_output_artifacts": {
            component: dict(output_refs[component]) for component in COMPONENTS
        },
    }


def _fixture_artifact(path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = canonical_json_bytes(dict(payload), label=path)
    return {"path": path, "sha256": _sha256(raw), "bytes": len(raw), "raw": raw}


def synthetic_fixture() -> dict[str, Any]:
    """Return a deterministic, in-memory fixture used only by tests/reporting."""
    source_root = "/synthetic/core/source"
    reproduction_root = "/synthetic/core/reproduction"
    source_host_id = "physical-source-001"
    reproduction_host_id = "physical-reproduction-001"
    package_hash = "a" * 64

    source_host = _fixture_artifact("typed/source-host.json", {
        "schema": HOST_SCHEMA, "role": "source_host", "category": "host_pair",
        "passed": True, "hostname": "synthetic-source-host",
        "physical_host_id": source_host_id, "diagnostic_only": True, "formal": False,
        "full_product_reproduction": False, "input_origin": "synthetic_fixture",
    })
    reproduction_host = _fixture_artifact("typed/reproduction-host.json", {
        "schema": HOST_SCHEMA, "role": "reproduction_host", "category": "host_pair",
        "passed": True, "hostname": "synthetic-reproduction-host",
        "physical_host_id": reproduction_host_id, "diagnostic_only": True, "formal": False,
        "full_product_reproduction": False, "input_origin": "synthetic_fixture",
    })
    source_manifest = _fixture_artifact("manifests/source-package.json", {
        "schema": MANIFEST_SCHEMA, "data_root": source_root, "package_sha256": package_hash,
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "input_origin": "synthetic_fixture",
    })
    reproduction_manifest = _fixture_artifact("manifests/reproduction-package.json", {
        "schema": MANIFEST_SCHEMA, "data_root": reproduction_root,
        "package_sha256": package_hash, "diagnostic_only": True, "formal": False,
        "full_product_reproduction": False,
        "input_origin": "synthetic_fixture",
    })
    source_manifest_ref = _public_ref(source_manifest)
    reproduction_manifest_ref = _public_ref(reproduction_manifest)
    data_roots = _fixture_artifact("typed/data-roots.json", {
        "schema": ROOT_SCHEMA, "role": "data_roots", "category": "data_roots",
        "passed": True, "source_data_root": source_root,
        "reproduction_data_root": reproduction_root, "different_data_root": True,
        "source_manifest": source_manifest_ref, "reproduction_manifest": reproduction_manifest_ref,
        "source_manifest_sha256": source_manifest_ref["sha256"],
        "reproduction_manifest_sha256": reproduction_manifest_ref["sha256"],
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "input_origin": "synthetic_fixture",
    })

    reader_output = _fixture_artifact("outputs/reader.json", {
        "schema": "core.reader_reproduction.v1", "component": "reader", "passed": True,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "future_state_inputs": False, "input_origin": "synthetic_fixture",
    })
    reader_output_ref = _public_ref(reader_output)
    prediction_output = _fixture_artifact("outputs/prediction.json", {
        "schema": "core.model_reproduction.v1", "component": "prediction", "passed": True,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "autonomous": True, "full_horizon": True, "future_state_inputs": False,
        "predictor_future_state_inputs": False, "input_origin": "synthetic_fixture",
    })
    prediction_output_ref = _public_ref(prediction_output)
    scoring_output = _fixture_artifact("outputs/scoring.json", {
        "schema": "core.model_reproduction.score.v1", "component": "scoring", "passed": True,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "metrics": {"registered_cases": 1, "complete_fraction": 1.0, "missing_execution": 0},
        "cases": ["synthetic-case-0"], "predictor_future_state_inputs": False,
        "input_origin": "synthetic_fixture",
    })
    scoring_output_ref = _public_ref(scoring_output)

    reader = _fixture_artifact("typed/reader-evidence.json", {
        "schema": COMPONENT_SCHEMA, "role": "reader", "category": "reader",
        "component": "reader", "passed": True, "reader_reproduced": True,
        "prediction_reproduced": False, "scoring_reproduced": False,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "output_report": reader_output_ref,
        "bindings": {"reproduction_manifest_sha256": reproduction_manifest_ref["sha256"]},
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "input_origin": "synthetic_fixture",
    })
    prediction = _fixture_artifact("typed/prediction-evidence.json", {
        "schema": COMPONENT_SCHEMA, "role": "prediction", "category": "prediction",
        "component": "prediction", "passed": True, "reader_reproduced": False,
        "prediction_reproduced": True, "scoring_reproduced": False,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "output_report": prediction_output_ref,
        "bindings": {"reader_output_sha256": reader_output_ref["sha256"]},
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "input_origin": "synthetic_fixture",
    })
    scoring = _fixture_artifact("typed/scoring-evidence.json", {
        "schema": COMPONENT_SCHEMA, "role": "scoring", "category": "scoring",
        "component": "scoring", "passed": True, "reader_reproduced": False,
        "prediction_reproduced": False, "scoring_reproduced": True,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "output_report": scoring_output_ref,
        "bindings": {
            "reader_output_sha256": reader_output_ref["sha256"],
            "prediction_output_sha256": prediction_output_ref["sha256"],
        },
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "input_origin": "synthetic_fixture",
    })

    typed_evidence = {
        "source_host": source_host, "reproduction_host": reproduction_host,
        "data_roots": data_roots, "reader": reader, "prediction": prediction,
        "scoring": scoring,
    }
    role_refs = {role: _public_ref(typed_evidence[role]) for role in ROLES}
    manifest_artifacts = {
        "source_manifest": source_manifest, "reproduction_manifest": reproduction_manifest,
    }
    component_outputs = {
        "reader": reader_output, "prediction": prediction_output, "scoring": scoring_output,
    }

    source_host_projection = {
        "hostname": "synthetic-source-host", "physical_host_id": source_host_id,
    }
    reproduction_host_projection = {
        "hostname": "synthetic-reproduction-host", "physical_host_id": reproduction_host_id,
    }
    data_root_projection = {
        "source_data_root": source_root, "reproduction_data_root": reproduction_root,
        "different_data_root": True, "package_sha256": package_hash,
        "manifests": {
            "source_manifest": {"artifact": source_manifest_ref, "data_root": source_root,
                                "package_sha256": package_hash},
            "reproduction_manifest": {"artifact": reproduction_manifest_ref,
                                      "data_root": reproduction_root,
                                      "package_sha256": package_hash},
        },
    }
    component_projection = {
        component: {
            "component": component,
            "physical_host_id": reproduction_host_id,
            "data_root": reproduction_root,
            "output_report": _public_ref(component_outputs[component]),
            "output_schema": _parse_canonical_object(
                component_outputs[component]["raw"], label=f"{component} output"
            )["schema"],
            "output_sha256": component_outputs[component]["sha256"],
            "bindings": _parse_canonical_object(
                typed_evidence[component]["raw"], label=f"{component} evidence"
            )["bindings"],
        }
        for component in COMPONENTS
    }
    preflight = _fixture_artifact("adapter/update-300-preflight.json", _preflight_projection(
        role_refs, source_host=source_host_projection,
        reproduction_host=reproduction_host_projection, data_roots=data_root_projection,
        components=component_projection,
    ))

    root_review = _fixture_artifact("root-review/existing-cross-host-decision.json", {
        "schema": ROOT_REVIEW_SCHEMA,
        "registered_comparison_pass": True,
        "two_terminal_reports_verified": True,
        "all_eight_required_outputs_verified": True,
        "diagnostic_only": True,
        "formal_training_count": 0,
        "full_core_reproduction_proven": False,
        "receipt_sha256": _sha256(b"synthetic-cross-host-comparison-receipt"),
        "scope": {
            "all_particle_axis": True, "case_id": "F3_DEV_08_a0p953125",
            "diagnostic_only": True, "family": "F3", "formal_training_count": 0,
            "full_horizon": True, "particle_count": 34560,
            "scientific_qualification": False, "split": "validation",
            "trajectory_frames": 836, "transitions": 835,
        },
        "headline": {
            "absolute_score_difference": 0.0,
            "maximum_position_absolute_difference_m": 0.0,
            "maximum_velocity_absolute_difference_mps": 0.0,
            "passed": True,
            "physics_and_failure_categories_passed": True,
            "score_left_ada": 0.1,
            "score_right_h200": 0.1,
        },
    })
    root_payload = _parse_canonical_object(root_review["raw"], label="root review")
    root_decision = _root_decision_projection(root_payload)
    evidence_manifest = _evidence_manifest(role_refs, {
        name: _public_ref(manifest_artifacts[name]) for name in manifest_artifacts
    }, {name: _public_ref(component_outputs[name]) for name in component_outputs})
    evidence_manifest_sha256 = _sha256_json(evidence_manifest, label="typed evidence manifest")
    binding_claim_payload = _expected_binding_claim(
        evidence_manifest_sha256=evidence_manifest_sha256,
        preflight_sha256=preflight["sha256"],
        root_review_artifact_sha256=root_review["sha256"],
        root_review_decision_sha256=_sha256_json(root_decision, label="root review decision"),
        role_refs=role_refs,
        manifest_refs={name: _public_ref(manifest_artifacts[name]) for name in manifest_artifacts},
        output_refs={name: _public_ref(component_outputs[name]) for name in component_outputs},
    )
    binding_claim = _fixture_artifact("adapter/exact-binding-claim.json", binding_claim_payload)
    return {
        "typed_evidence": typed_evidence,
        "manifest_artifacts": manifest_artifacts,
        "component_outputs": component_outputs,
        "preflight": preflight,
        "root_review": root_review,
        "binding_claim": binding_claim,
    }


def bind_synthetic_typed_evidence_root_review(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Verify one synthetic fixture and return a non-authorizing binding result."""
    _require(isinstance(fixture, Mapping) and set(fixture) == FIXTURE_FIELDS,
             "FIXTURE_FIELDS_NOT_EXACT", "synthetic fixture fields are not exact")
    typed = fixture["typed_evidence"]
    _require(isinstance(typed, Mapping) and set(typed) == set(ROLES),
             "ROLE_SET_MISMATCH", "typed evidence must contain exactly the six artifact roles")
    manifests = fixture["manifest_artifacts"]
    outputs = fixture["component_outputs"]
    _require(isinstance(manifests, Mapping) and isinstance(outputs, Mapping),
             "FIXTURE_SECTION_INVALID", "nested artifact sections must be mappings")

    role_payloads: dict[str, dict[str, Any]] = {}
    role_refs: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for role in ROLES:
        payload, ref = _verify_artifact(typed[role], label=role)
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE",
                 f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
        role_payloads[role] = payload
        role_refs[role] = ref

    host_source = _validate_host(role_payloads["source_host"], role="source_host")
    host_reproduction = _validate_host(role_payloads["reproduction_host"], role="reproduction_host")
    _require(_host_key(host_source["hostname"]) != _host_key(host_reproduction["hostname"]),
             "SAME_HOST_RELOCATION_REJECTED", "source/reproduction hostnames are identical")
    _require(host_source["physical_host_id"] != host_reproduction["physical_host_id"],
             "SAME_HOST_RELOCATION_REJECTED", "source/reproduction physical host IDs are identical")

    manifest_payloads, manifest_refs = _validate_manifest_artifacts(manifests)
    for ref in manifest_refs.values():
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE",
                 f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
    data_roots = _validate_data_roots(
        role_payloads["data_roots"], manifest_payloads, manifest_refs,
    )

    output_payloads: dict[str, dict[str, Any]] = {}
    output_refs: dict[str, dict[str, Any]] = {}
    for component in COMPONENTS:
        payload, ref = _verify_artifact(outputs[component], label=f"{component} output")
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE",
                 f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
        output_payloads[component] = payload
        output_refs[component] = ref

    component_payloads = {component: role_payloads[component] for component in COMPONENTS}
    component_projection = _validate_components(
        component_payloads, output_payloads, output_refs,
        reproduction_host_id=host_reproduction["physical_host_id"],
        reproduction_root=data_roots["reproduction_data_root"],
        reproduction_manifest_sha256=manifest_refs["reproduction_manifest"]["sha256"],
        reader_output_sha256=output_refs["reader"]["sha256"],
        prediction_output_sha256=output_refs["prediction"]["sha256"],
    )

    preflight_payload, preflight_ref = _verify_artifact(
        fixture["preflight"], label="UPDATE-300 preflight"
    )
    _require(preflight_ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE",
             f"artifact path is reused: {preflight_ref['path']}")
    paths.add(preflight_ref["path"])
    expected_preflight = _preflight_projection(
        role_refs, source_host=host_source, reproduction_host=host_reproduction,
        data_roots=data_roots, components=component_projection,
    )
    _require(preflight_payload == expected_preflight, "PREFLIGHT_BINDING_MISMATCH",
             "UPDATE-300 preflight is not the exact projection of typed evidence")

    root_payload, root_ref = _verify_artifact(
        fixture["root_review"], label="existing cross-host root review"
    )
    _require(root_ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE",
             f"artifact path is reused: {root_ref['path']}")
    paths.add(root_ref["path"])
    root_info = _validate_root_review(root_payload)

    evidence_manifest = _evidence_manifest(role_refs, manifest_refs, output_refs)
    evidence_manifest_sha256 = _sha256_json(evidence_manifest, label="typed evidence manifest")
    expected_claim = _expected_binding_claim(
        evidence_manifest_sha256=evidence_manifest_sha256,
        preflight_sha256=preflight_ref["sha256"],
        root_review_artifact_sha256=root_ref["sha256"],
        root_review_decision_sha256=root_info["decision_sha256"],
        role_refs=role_refs, manifest_refs=manifest_refs, output_refs=output_refs,
    )
    claim_payload, claim_ref = _verify_artifact(
        fixture["binding_claim"], label="exact binding claim"
    )
    _require(claim_ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE",
             f"artifact path is reused: {claim_ref['path']}")
    _require(claim_payload == expected_claim, "EXACT_BINDING_CLAIM_MISMATCH",
             "caller binding claim does not exactly match recomputed canonical hashes")

    binding = {
        "canonical_encoding": "UTF-8 JSON sort_keys=true separators=(',', ':') allow_nan=false",
        "typed_evidence_manifest_sha256": evidence_manifest_sha256,
        "preflight_artifact": dict(preflight_ref),
        "preflight_sha256": preflight_ref["sha256"],
        "root_review_artifact": dict(root_ref),
        "root_review_artifact_sha256": root_ref["sha256"],
        "root_review_decision_sha256": root_info["decision_sha256"],
        "binding_claim_artifact": dict(claim_ref),
        "binding_claim_sha256": claim_ref["sha256"],
        "role_artifacts": {role: dict(role_refs[role]) for role in ROLES},
        "manifest_artifacts": {name: dict(manifest_refs[name]) for name in (
            "source_manifest", "reproduction_manifest"
        )},
        "component_output_artifacts": {
            component: dict(output_refs[component]) for component in COMPONENTS
        },
    }
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "diagnostic_only": True,
        "capability_minted": False,
        "formal_training_count": 0,
        "full_product_reproduction": False,
        "credit": 0,
        "qualification_credit": 0,
        "real_cross_host_reproduction": False,
        "cross_host_claim": False,
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "evidence_manifest": {
            "schema": evidence_manifest["schema"],
            "sha256": evidence_manifest_sha256,
            "category_count": len(CATEGORIES),
            "role_count": len(ROLES),
        },
        "root_review": {
            "decision_bound": True,
            "decision": root_info["decision"],
            "decision_sha256": root_info["decision_sha256"],
            "artifact": dict(root_ref),
            "trusted_root_authenticated": False,
            "caller_self_asserted_trusted_root_accepted": False,
        },
        "assembly": {
            "source_host": host_source,
            "reproduction_host": host_reproduction,
            "distinct_physical_hosts": True,
            "distinct_data_roots": True,
            "data_roots": data_roots,
            "components": component_projection,
        },
        "binding": binding,
        "non_authorizing_boundary": dict(NON_AUTHORIZING_BOUNDARY),
        "execution_constraints": {
            "read_only": True,
            "synthetic_in_memory_only": True,
            "production_files_read": False,
            "workload_started": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
        "interpretation": (
            "Exact structural/hash binding of synthetic typed evidence to an existing "
            "diagnostic cross-host root-review decision; this is not trusted-root "
            "authentication, real cross-host reproduction, full-product reproduction, "
            "formal admission, qualification, or credit."
        ),
    }


# Short aliases keep the sidecar convenient for focused contract tests without
# creating a second implementation or importing an old verifier.
bind_synthetic_fixture = bind_synthetic_typed_evidence_root_review
build_adapter = bind_synthetic_typed_evidence_root_review


def build_report() -> dict[str, Any]:
    result = bind_synthetic_typed_evidence_root_review(synthetic_fixture())
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": REPORT_STATUS,
        "adapter_schema": result["schema"],
        "adapter_status": result["status"],
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "typed_evidence_categories": result["typed_evidence_categories"],
        "typed_evidence_roles": result["typed_evidence_roles"],
        "evidence_manifest": result["evidence_manifest"],
        "root_review": result["root_review"],
        "assembly": result["assembly"],
        "binding": result["binding"],
        "non_authorizing_boundary": result["non_authorizing_boundary"],
        "execution_constraints": result["execution_constraints"],
        "rejection_contract": {
            "same_host_relocation": "reject",
            "missing_or_extra_role": "reject",
            "path_or_hash_mismatch": "reject",
            "diagnostic_evidence_claiming_formal": "reject",
            "caller_self_asserted_trusted_root": "reject",
        },
        "interpretation": result["interpretation"],
    }


def write_json_once(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    _require(not target.exists(), "IMMUTABLE_OUTPUT_EXISTS",
             f"refusing to overwrite diagnostic output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_report()
    write_json_once(args.output, report)
    print(json.dumps({
        "schema": report["schema"], "status": report["status"],
        "diagnostic_only": report["non_authorizing_boundary"]["diagnostic_only"],
        "capability_minted": report["non_authorizing_boundary"]["capability_minted"],
        "formal_training_count": report["non_authorizing_boundary"]["formal_training_count"],
        "full_product_reproduction": report["non_authorizing_boundary"]["full_product_reproduction"],
        "credit": report["non_authorizing_boundary"]["credit"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
