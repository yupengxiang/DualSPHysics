#!/usr/bin/env python3
"""Verify a synthetic-only Core independent-reproduction assembly envelope.

This module is the narrow envelope layer between two existing contracts:

* ``core_independent_reproduction_preflight.py`` (UPDATE-300) verifies
  path-backed typed evidence; and
* ``core_independent_reproduction_root_review_adapter_v1.py`` (UPDATE-311)
  binds synthetic evidence to an existing diagnostic root-review decision.

This verifier does neither of those jobs.  It accepts only bounded, in-memory
canonical JSON artifacts and constructs a deterministic envelope containing
the five typed evidence categories, six role artifacts, source/reproduction
host identity, distinct data roots, and the reader -> prediction -> scoring
hash lineage.  It deliberately has no root-review input or filesystem input.
The envelope digest is a reproducible structural identity, not a trust root,
execution capability, product-reproduction claim, or qualification result.

The public verifier is intentionally strict about the assembly boundary.  It
does not read a production bundle, invoke a reader/model/scorer, start a
workload/solver/worker/GPU/queue, or mutate registry/ledger/gate/completion
state.  A successful result is always diagnostic-only and has zero credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "core.reproduction.independent_evidence_assembly_envelope.v1"
REPORT_SCHEMA = "core.reproduction.independent_evidence_assembly_report.v1"
RECORD_ID = "core-independent-reproduction-evidence-assembly-v1"
REPORT_ID = "core-independent-reproduction-evidence-assembly-report-v1"
STATUS = "synthetic_only_independent_reproduction_assembly_verified"
REPORT_STATUS = "synthetic_only_non_authorizing_independent_reproduction_assembly"

HOST_SCHEMA = "core.reproduction.host_identity.v1"
ROOT_SCHEMA = "core.reproduction.data_roots.v1"
MANIFEST_SCHEMA = "core.reproduction.package_manifest.v1"
COMPONENT_SCHEMA = "core.reproduction.component.v1"

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

ARTIFACT_FIELDS = frozenset({"path", "sha256", "bytes", "raw"})
FIXTURE_FIELDS = frozenset({
    "typed_evidence", "manifest_artifacts", "component_outputs",
})

NON_AUTHORIZING_BOUNDARY = {
    "diagnostic_only": True,
    "capability_minted": False,
    "full_product_reproduction": False,
    "formal_admission": False,
    "formal_training_count": 0,
    "credit": 0,
    "qualification_credit": 0,
    "cross_host_claim": False,
    "real_cross_host_reproduction": False,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
}


class EvidenceAssemblyError(ValueError):
    """A fail-closed synthetic assembly contract failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise EvidenceAssemblyError(code, message)


def canonical_json_bytes(value: Any, *, label: str = "value") -> bytes:
    """Return the one canonical JSON encoding used for all envelope hashes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise EvidenceAssemblyError(
            "NON_CANONICAL_JSON", f"{label} is not canonical JSON serializable"
        ) from error


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _parse_canonical_object(raw: Any, *, label: str) -> dict[str, Any]:
    _require(
        type(raw) is bytes and 0 < len(raw) <= MAX_ARTIFACT_BYTES,
        "ARTIFACT_BYTES_INVALID",
        f"{label} raw bytes are outside the bounded synthetic contract",
    )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise EvidenceAssemblyError(
            "INVALID_CANONICAL_JSON", f"{label} is not valid canonical JSON"
        ) from error
    _require(type(value) is dict, "JSON_OBJECT_REQUIRED", f"{label} must be a JSON object")
    _require(
        canonical_json_bytes(value, label=label) == raw,
        "NON_CANONICAL_JSON",
        f"{label} bytes are not the exact canonical encoding",
    )
    return value


def _valid_sha(value: Any, *, code: str, label: str) -> str:
    _require(
        type(value) is str and SHA256_RE.fullmatch(value) is not None,
        code,
        f"{label} is not a lowercase SHA-256",
    )
    return value


def _portable_path(value: Any, *, label: str) -> str:
    _require(type(value) is str and bool(value), "PATH_INVALID", f"{label} path is missing")
    _require(
        "\\" not in value and not value.startswith("/") and DRIVE_PATH_RE.match(value) is None,
        "PATH_NOT_PORTABLE",
        f"{label} path is not portable",
    )
    parts = value.split("/")
    _require(
        all(part not in ("", ".", "..") for part in parts),
        "PATH_NOT_PORTABLE",
        f"{label} path contains an escaping component",
    )
    return value


def _public_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("path", "sha256", "bytes")}


def _verify_artifact(row: Any, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(
        isinstance(row, Mapping) and set(row) == ARTIFACT_FIELDS,
        "ARTIFACT_FIELDS_NOT_EXACT",
        f"{label} artifact fields are not exact",
    )
    path = _portable_path(row.get("path"), label=label)
    raw = row.get("raw")
    _require(
        type(raw) is bytes and 0 < len(raw) <= MAX_ARTIFACT_BYTES,
        "ARTIFACT_BYTES_INVALID",
        f"{label} raw bytes are outside the bounded synthetic contract",
    )
    declared_bytes = row.get("bytes")
    _require(
        type(declared_bytes) is int and declared_bytes >= 0,
        "ARTIFACT_BYTES_INVALID",
        f"{label} declared byte count is invalid",
    )
    _require(
        declared_bytes == len(raw),
        "ARTIFACT_BYTES_MISMATCH",
        f"{label} declared byte count does not match raw bytes",
    )
    declared_sha = _valid_sha(
        row.get("sha256"), code="ARTIFACT_HASH_INVALID", label=f"{label} artifact hash"
    )
    _require(
        declared_sha == _sha256(raw),
        "ARTIFACT_HASH_MISMATCH",
        f"{label} declared hash does not match raw bytes",
    )
    payload = _parse_canonical_object(raw, label=label)
    return payload, _public_ref(row)


def _require_exact_fields(payload: Mapping[str, Any], expected: frozenset[str], *, label: str) -> None:
    _require(set(payload) == expected, "PAYLOAD_FIELDS_NOT_EXACT", f"{label} fields are not exact")


def _validate_non_formal(payload: Mapping[str, Any], *, label: str) -> None:
    _require(
        payload.get("diagnostic_only") is True,
        "DIAGNOSTIC_MARKER_MISSING",
        f"{label} is not diagnostic-only",
    )
    _require(
        payload.get("formal") is False
        and payload.get("full_product_reproduction") is False,
        "DIAGNOSTIC_FORMAL_CONFLICT",
        f"{label} attempts to present diagnostic evidence as formal/product evidence",
    )
    _require(
        payload.get("input_origin") == "synthetic_fixture",
        "NON_SYNTHETIC_INPUT",
        f"{label} is not marked synthetic_fixture",
    )


def _canonical_data_root(value: Any, *, label: str) -> str:
    _require(
        type(value) is str and value.startswith("/") and "\\" not in value,
        "DATA_ROOT_INVALID",
        f"{label} is not an absolute POSIX root",
    )
    parts = value.split("/")
    _require(".." not in parts, "DATA_ROOT_INVALID", f"{label} contains '..'")
    normalized = posixpath.normpath(value)
    _require(
        normalized.startswith("/") and normalized != ".",
        "DATA_ROOT_INVALID",
        f"{label} cannot be canonicalized",
    )
    return normalized


def _host_key(value: str) -> str:
    return value.rstrip(".").casefold()


def _validate_host(payload: Mapping[str, Any], *, role: str) -> dict[str, str]:
    _require_exact_fields(payload, HOST_FIELDS, label=role)
    _require(payload.get("schema") == HOST_SCHEMA, "HOST_SCHEMA_MISMATCH", f"{role} schema is unsupported")
    _require(
        payload.get("role") == role and payload.get("category") == "host_pair",
        "ROLE_BINDING_MISMATCH",
        f"{role} role/category binding is inconsistent",
    )
    _require(payload.get("passed") is True, "HOST_EVIDENCE_NOT_PASSED", f"{role} is not passed")
    _validate_non_formal(payload, label=role)
    hostname = payload.get("hostname")
    physical_host_id = payload.get("physical_host_id")
    _require(
        type(hostname) is str and bool(hostname.strip()),
        "HOSTNAME_MISSING",
        f"{role} hostname is missing",
    )
    _require(
        type(physical_host_id) is str and bool(physical_host_id.strip()),
        "PHYSICAL_HOST_ID_MISSING",
        f"{role} physical host id is missing",
    )
    return {"hostname": hostname.strip(), "physical_host_id": physical_host_id.strip()}


def _validate_manifest_artifacts(
    rows: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    expected = {"source_manifest", "reproduction_manifest"}
    _require(
        set(rows) == expected,
        "MANIFEST_ROLE_SET_MISMATCH",
        "exactly source_manifest and reproduction_manifest are required",
    )
    payloads: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    for name in ("source_manifest", "reproduction_manifest"):
        payload, ref = _verify_artifact(rows[name], label=name)
        _require_exact_fields(payload, MANIFEST_FIELDS, label=name)
        _require(payload.get("schema") == MANIFEST_SCHEMA, "MANIFEST_SCHEMA_MISMATCH", f"{name} schema is unsupported")
        _validate_non_formal(payload, label=name)
        _valid_sha(payload.get("package_sha256"), code="PACKAGE_HASH_INVALID", label=f"{name} package hash")
        payloads[name] = payload
        refs[name] = ref
    _require(
        payloads["source_manifest"]["package_sha256"]
        == payloads["reproduction_manifest"]["package_sha256"],
        "PACKAGE_IDENTITY_MISMATCH",
        "source/reproduction package hashes differ",
    )
    return payloads, refs


def _validate_data_roots(
    payload: Mapping[str, Any],
    manifest_payloads: Mapping[str, Mapping[str, Any]],
    manifest_refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    _require_exact_fields(payload, DATA_ROOT_FIELDS, label="data_roots")
    _require(payload.get("schema") == ROOT_SCHEMA, "DATA_ROOT_SCHEMA_MISMATCH", "data_roots schema is unsupported")
    _require(
        payload.get("role") == "data_roots" and payload.get("category") == "data_roots",
        "ROLE_BINDING_MISMATCH",
        "data_roots role/category binding is inconsistent",
    )
    _require(
        payload.get("passed") is True and payload.get("different_data_root") is True,
        "DATA_ROOT_EVIDENCE_NOT_PASSED",
        "data_roots does not pass its distinct-root marker",
    )
    _validate_non_formal(payload, label="data_roots")
    source = _canonical_data_root(payload.get("source_data_root"), label="source_data_root")
    reproduction = _canonical_data_root(
        payload.get("reproduction_data_root"), label="reproduction_data_root"
    )
    _require(source != reproduction, "DATA_ROOTS_NOT_DISTINCT", "source/reproduction roots are identical")

    for name, expected_root in (("source_manifest", source), ("reproduction_manifest", reproduction)):
        _require(
            _canonical_data_root(manifest_payloads[name].get("data_root"), label=f"{name}.data_root")
            == expected_root,
            "MANIFEST_ROOT_MISMATCH",
            f"{name} does not bind its declared data root",
        )
        _require(
            payload.get(name) == manifest_refs[name],
            "NESTED_ARTIFACT_BINDING_MISMATCH",
            f"data_roots {name} reference differs from its artifact",
        )
        _require(
            payload.get(f"{name}_sha256") == manifest_refs[name]["sha256"],
            "NESTED_ARTIFACT_BINDING_MISMATCH",
            f"data_roots {name}_sha256 differs from its manifest artifact",
        )
    return {
        "source_data_root": source,
        "reproduction_data_root": reproduction,
        "different_data_root": True,
        "package_sha256": manifest_payloads["source_manifest"]["package_sha256"],
        "manifests": {
            name: {
                "artifact": dict(manifest_refs[name]),
                "data_root": expected_root,
                "package_sha256": manifest_payloads[name]["package_sha256"],
            }
            for name, expected_root in (("source_manifest", source), ("reproduction_manifest", reproduction))
        },
    }


def _output_fields(component: str) -> frozenset[str]:
    if component == "reader":
        return READER_OUTPUT_FIELDS
    if component == "prediction":
        return PREDICTION_OUTPUT_FIELDS
    return SCORING_OUTPUT_FIELDS


def _validate_output(
    payload: Mapping[str, Any],
    *,
    component: str,
    reproduction_host_id: str,
    reproduction_root: str,
) -> dict[str, Any]:
    _require_exact_fields(payload, _output_fields(component), label=f"{component} output")
    expected_schema = {
        "reader": "core.reader_reproduction.v1",
        "prediction": "core.model_reproduction.v1",
        "scoring": "core.model_reproduction.score.v1",
    }[component]
    _require(
        payload.get("schema") == expected_schema and payload.get("component") == component,
        "OUTPUT_SCHEMA_MISMATCH",
        f"{component} output schema/component is unsupported",
    )
    _require(payload.get("passed") is True, "OUTPUT_NOT_PASSED", f"{component} output is not passed")
    _require(
        payload.get("physical_host_id") == reproduction_host_id
        and _canonical_data_root(payload.get("data_root"), label=f"{component}.data_root")
        == reproduction_root,
        "OUTPUT_HOST_ROOT_MISMATCH",
        f"{component} output is not bound to the reproduction host/root",
    )
    _validate_non_formal(payload, label=f"{component} output")
    if component == "reader":
        _require(
            payload.get("future_state_inputs") is False,
            "READER_FUTURE_STATE_INPUT",
            "reader output permits future-state inputs",
        )
    elif component == "prediction":
        _require(
            payload.get("autonomous") is True and payload.get("full_horizon") is True,
            "PREDICTION_CONTRACT_INCOMPLETE",
            "prediction output is not autonomous/full-horizon",
        )
        _require(
            payload.get("future_state_inputs") is False
            and payload.get("predictor_future_state_inputs") is False,
            "PREDICTION_FUTURE_STATE_INPUT",
            "prediction output permits future-state inputs",
        )
    else:
        _require(
            payload.get("predictor_future_state_inputs") is False,
            "SCORING_FUTURE_STATE_INPUT",
            "scoring output permits future-state inputs",
        )
        _require(
            payload.get("metrics")
            == {"registered_cases": 1, "complete_fraction": 1.0, "missing_execution": 0}
            and payload.get("cases") == ["synthetic-case-0"],
            "SCORING_CONTRACT_INCOMPLETE",
            "scoring output denominator is not the exact synthetic denominator",
        )
    return {"schema": payload["schema"], "component": component}


def _validate_components(
    role_payloads: Mapping[str, Mapping[str, Any]],
    output_payloads: Mapping[str, Mapping[str, Any]],
    output_refs: Mapping[str, Mapping[str, Any]],
    *,
    reproduction_host_id: str,
    reproduction_root: str,
    reproduction_manifest_sha256: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    output_sha256 = {component: output_refs[component]["sha256"] for component in COMPONENTS}
    for component in COMPONENTS:
        payload = role_payloads[component]
        _require_exact_fields(payload, COMPONENT_FIELDS, label=component)
        _require(
            payload.get("schema") == COMPONENT_SCHEMA
            and payload.get("role") == component
            and payload.get("category") == component
            and payload.get("component") == component,
            "ROLE_BINDING_MISMATCH",
            f"{component} evidence role/category is inconsistent",
        )
        _require(
            payload.get("passed") is True and payload.get(f"{component}_reproduced") is True,
            "COMPONENT_EVIDENCE_NOT_PASSED",
            f"{component} typed evidence is not passed",
        )
        _validate_non_formal(payload, label=component)
        _require(
            payload.get("physical_host_id") == reproduction_host_id
            and _canonical_data_root(payload.get("data_root"), label=f"{component}.data_root")
            == reproduction_root,
            "COMPONENT_HOST_ROOT_MISMATCH",
            f"{component} evidence is not bound to the reproduction host/root",
        )
        bindings = payload.get("bindings")
        if component == "reader":
            expected_bindings = {"reproduction_manifest_sha256": reproduction_manifest_sha256}
        elif component == "prediction":
            expected_bindings = {"reader_output_sha256": output_sha256["reader"]}
        else:
            expected_bindings = {
                "reader_output_sha256": output_sha256["reader"],
                "prediction_output_sha256": output_sha256["prediction"],
            }
        _require(
            bindings == expected_bindings,
            "COMPONENT_CHAIN_HASH_MISMATCH",
            f"{component} input/output binding is not exact",
        )
        _require(
            payload.get("output_report") == output_refs[component],
            "OUTPUT_ARTIFACT_BINDING_MISMATCH",
            f"{component} output_report differs from its output artifact",
        )
        _validate_output(
            output_payloads[component],
            component=component,
            reproduction_host_id=reproduction_host_id,
            reproduction_root=reproduction_root,
        )
        result[component] = {
            "evidence_artifact": None,
            "output_artifact": dict(output_refs[component]),
            "output_schema": output_payloads[component]["schema"],
            "bindings": dict(bindings),
        }
    return result


def _assembly_envelope(
    *,
    role_refs: Mapping[str, Mapping[str, Any]],
    manifest_refs: Mapping[str, Mapping[str, Any]],
    output_refs: Mapping[str, Mapping[str, Any]],
    hosts: Mapping[str, Mapping[str, str]],
    roots: Mapping[str, Any],
    components: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build only from verified projections; no caller-supplied digest is used."""
    component_chain = {
        component: {
            "evidence_artifact": dict(role_refs[component]),
            "output_artifact": dict(output_refs[component]),
            "output_schema": components[component]["output_schema"],
            "bindings": dict(components[component]["bindings"]),
        }
        for component in COMPONENTS
    }
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "version": 1,
        "input_origin": "synthetic_fixture",
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "role_artifacts": {
            role: {
                "category": ROLE_TO_CATEGORY[role],
                "artifact": dict(role_refs[role]),
            }
            for role in ROLES
        },
        "host_pair": {
            "source_host": dict(hosts["source_host"]),
            "reproduction_host": dict(hosts["reproduction_host"]),
            "distinct_hostnames": True,
            "distinct_physical_hosts": True,
        },
        "data_roots": {
            "source_data_root": roots["source_data_root"],
            "reproduction_data_root": roots["reproduction_data_root"],
            "different_data_root": True,
            "distinct_data_roots": True,
            "package_sha256": roots["package_sha256"],
            "manifest_artifacts": {
                name: {
                    "artifact": dict(manifest_refs[name]),
                    "data_root": roots["manifests"][name]["data_root"],
                    "package_sha256": roots["manifests"][name]["package_sha256"],
                }
                for name in ("source_manifest", "reproduction_manifest")
            },
        },
        "reader_prediction_scoring_chain": {
            "reader_output_sha256": output_refs["reader"]["sha256"],
            "prediction_input_reader_output_sha256": components["prediction"]["bindings"][
                "reader_output_sha256"
            ],
            "scoring_input_reader_output_sha256": components["scoring"]["bindings"][
                "reader_output_sha256"
            ],
            "prediction_output_sha256": output_refs["prediction"]["sha256"],
            "scoring_input_prediction_output_sha256": components["scoring"]["bindings"][
                "prediction_output_sha256"
            ],
            "scoring_output_sha256": output_refs["scoring"]["sha256"],
            "chain_complete": True,
        },
        "components": component_chain,
        "manifest_artifacts": {
            name: dict(manifest_refs[name])
            for name in ("source_manifest", "reproduction_manifest")
        },
        "component_output_artifacts": {
            component: dict(output_refs[component]) for component in COMPONENTS
        },
    }


def recompute_envelope_sha256(envelope: Mapping[str, Any]) -> str:
    """Recompute the exact digest published beside an assembly envelope."""
    _require(isinstance(envelope, Mapping), "ENVELOPE_INVALID", "envelope must be a mapping")
    _require(envelope.get("schema") == SCHEMA, "ENVELOPE_SCHEMA_MISMATCH", "envelope schema is unsupported")
    return _sha256(canonical_json_bytes(dict(envelope), label="assembly envelope"))


def verify_synthetic_assembly(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Verify one in-memory typed-evidence set and return its envelope.

    This function deliberately has no path or subprocess API.  It verifies the
    narrow assembly boundary and derives every output digest itself; it does
    not accept a caller-supplied envelope hash, root-review decision, or
    capability claim.
    """
    _require(
        isinstance(fixture, Mapping) and set(fixture) == FIXTURE_FIELDS,
        "FIXTURE_FIELDS_NOT_EXACT",
        "assembly input fields are not exact",
    )
    typed = fixture["typed_evidence"]
    manifests = fixture["manifest_artifacts"]
    outputs = fixture["component_outputs"]
    _require(
        isinstance(typed, Mapping) and set(typed) == set(ROLES),
        "ROLE_SET_MISMATCH",
        "typed evidence must contain exactly the six artifact roles",
    )
    _require(
        isinstance(manifests, Mapping) and set(manifests) == {"source_manifest", "reproduction_manifest"},
        "MANIFEST_ROLE_SET_MISMATCH",
        "manifest artifacts must contain exactly two package manifests",
    )
    _require(
        isinstance(outputs, Mapping) and set(outputs) == set(COMPONENTS),
        "COMPONENT_SET_MISMATCH",
        "component outputs must contain exactly reader, prediction, and scoring",
    )

    paths: set[str] = set()
    role_payloads: dict[str, dict[str, Any]] = {}
    role_refs: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        payload, ref = _verify_artifact(typed[role], label=role)
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE", f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
        role_payloads[role] = payload
        role_refs[role] = ref

    source_host = _validate_host(role_payloads["source_host"], role="source_host")
    reproduction_host = _validate_host(role_payloads["reproduction_host"], role="reproduction_host")
    _require(
        _host_key(source_host["hostname"]) != _host_key(reproduction_host["hostname"])
        and source_host["physical_host_id"] != reproduction_host["physical_host_id"],
        "SAME_HOST_RELOCATION_REJECTED",
        "source/reproduction hosts are not distinct",
    )

    manifest_payloads, manifest_refs = _validate_manifest_artifacts(manifests)
    for ref in manifest_refs.values():
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE", f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
    roots = _validate_data_roots(role_payloads["data_roots"], manifest_payloads, manifest_refs)

    output_payloads: dict[str, dict[str, Any]] = {}
    output_refs: dict[str, dict[str, Any]] = {}
    for component in COMPONENTS:
        payload, ref = _verify_artifact(outputs[component], label=f"{component} output")
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE", f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
        output_payloads[component] = payload
        output_refs[component] = ref

    components = _validate_components(
        {component: role_payloads[component] for component in COMPONENTS},
        output_payloads,
        output_refs,
        reproduction_host_id=reproduction_host["physical_host_id"],
        reproduction_root=roots["reproduction_data_root"],
        reproduction_manifest_sha256=manifest_refs["reproduction_manifest"]["sha256"],
    )
    for component in COMPONENTS:
        components[component]["evidence_artifact"] = dict(role_refs[component])

    envelope = _assembly_envelope(
        role_refs=role_refs,
        manifest_refs=manifest_refs,
        output_refs=output_refs,
        hosts={"source_host": source_host, "reproduction_host": reproduction_host},
        roots=roots,
        components=components,
    )
    envelope_sha256 = recompute_envelope_sha256(envelope)
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "diagnostic_only": True,
        "capability_minted": False,
        "full_product_reproduction": False,
        "credit": 0,
        "qualification_credit": 0,
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "assembly_envelope": envelope,
        "assembly_envelope_sha256": envelope_sha256,
        "envelope_hash_recomputed": recompute_envelope_sha256(envelope) == envelope_sha256,
        "non_authorizing_boundary": dict(NON_AUTHORIZING_BOUNDARY),
        "execution_constraints": {
            "read_only": True,
            "synthetic_in_memory_only": True,
            "production_bundle_read": False,
            "workload_started": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "upstream_boundary": {
            "update_300_preflight_consumed": False,
            "update_311_root_review_consumed": False,
            "root_review_authenticated": False,
            "capability_consumer_present": False,
        },
        "interpretation": (
            "Deterministic structural assembly of synthetic typed evidence only. "
            "The envelope hash is recomputable lineage metadata; it is not a "
            "trusted root, formal/product reproduction, admission, qualification, "
            "or credit claim."
        ),
    }


def _fixture_artifact(path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = canonical_json_bytes(dict(payload), label=path)
    return {"path": path, "sha256": _sha256(raw), "bytes": len(raw), "raw": raw}


def synthetic_fixture() -> dict[str, Any]:
    """Return a deterministic fixture with no filesystem dependencies."""
    source_root = "/synthetic/core/source"
    reproduction_root = "/synthetic/core/reproduction"
    source_host_id = "physical-source-assembly-001"
    reproduction_host_id = "physical-reproduction-assembly-001"
    package_hash = "b" * 64

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
        "full_product_reproduction": False, "input_origin": "synthetic_fixture",
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
    prediction_output = _fixture_artifact("outputs/prediction.json", {
        "schema": "core.model_reproduction.v1", "component": "prediction", "passed": True,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "autonomous": True, "full_horizon": True, "future_state_inputs": False,
        "predictor_future_state_inputs": False, "input_origin": "synthetic_fixture",
    })
    scoring_output = _fixture_artifact("outputs/scoring.json", {
        "schema": "core.model_reproduction.score.v1", "component": "scoring", "passed": True,
        "physical_host_id": reproduction_host_id, "data_root": reproduction_root,
        "diagnostic_only": True, "formal": False, "full_product_reproduction": False,
        "metrics": {"registered_cases": 1, "complete_fraction": 1.0, "missing_execution": 0},
        "cases": ["synthetic-case-0"], "predictor_future_state_inputs": False,
        "input_origin": "synthetic_fixture",
    })
    reader_output_ref = _public_ref(reader_output)
    prediction_output_ref = _public_ref(prediction_output)
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
    return {
        "typed_evidence": {
            "source_host": source_host,
            "reproduction_host": reproduction_host,
            "data_roots": data_roots,
            "reader": reader,
            "prediction": prediction,
            "scoring": scoring,
        },
        "manifest_artifacts": {
            "source_manifest": source_manifest,
            "reproduction_manifest": reproduction_manifest,
        },
        "component_outputs": {
            "reader": reader_output,
            "prediction": prediction_output,
            "scoring": scoring_output,
        },
    }


def build_report() -> dict[str, Any]:
    result = verify_synthetic_assembly(synthetic_fixture())
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": REPORT_STATUS,
        "verifier_schema": result["schema"],
        "verifier_status": result["status"],
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "typed_evidence_categories": result["typed_evidence_categories"],
        "typed_evidence_roles": result["typed_evidence_roles"],
        "assembly_envelope": result["assembly_envelope"],
        "assembly_envelope_sha256": result["assembly_envelope_sha256"],
        "envelope_hash_recomputed": result["envelope_hash_recomputed"],
        "non_authorizing_boundary": result["non_authorizing_boundary"],
        "execution_constraints": result["execution_constraints"],
        "upstream_boundary": result["upstream_boundary"],
        "rejection_contract": {
            "missing_or_extra_role": "reject",
            "missing_or_extra_category": "reject",
            "same_host_relocation": "reject",
            "same_data_root_after_canonicalization": "reject",
            "artifact_path_or_hash_or_bytes_mismatch": "reject",
            "reader_prediction_scoring_hash_rebind": "reject",
            "noncanonical_json_or_duplicate_keys": "reject",
            "diagnostic_evidence_claiming_formal_product": "reject",
            "caller_supplied_envelope_digest": "not_consumed",
            "root_review_or_capability_claim": "not_consumed",
        },
        "interpretation": result["interpretation"],
    }


def write_json_once(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write a new report without ever replacing an existing receipt."""
    target = Path(path).expanduser().resolve()
    _require(not target.exists(), "IMMUTABLE_OUTPUT_EXISTS", f"refusing to overwrite output: {target}")
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
        "schema": report["schema"],
        "status": report["status"],
        "assembly_envelope_sha256": report["assembly_envelope_sha256"],
        "diagnostic_only": report["non_authorizing_boundary"]["diagnostic_only"],
        "capability_minted": report["non_authorizing_boundary"]["capability_minted"],
        "full_product_reproduction": report["non_authorizing_boundary"]["full_product_reproduction"],
        "credit": report["non_authorizing_boundary"]["credit"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
