#!/usr/bin/env python3
"""Verify a synthetic-only Core independent-reproduction assembly envelope.

This is the narrow envelope layer between two existing contracts:

* ``core_independent_reproduction_preflight.py`` (UPDATE-300) verifies
  path-backed typed evidence; and
* ``core_independent_reproduction_root_review_adapter_v1.py`` (UPDATE-311)
  binds synthetic evidence to an existing diagnostic root-review decision.

This verifier deliberately does neither job.  It consumes only a bounded
in-memory *projection* of already typed evidence: portable artifact
descriptors plus the host, root, output, and binding projections needed to
assemble lineage.  It does not re-read or re-parse artifact bytes, does not
consume a preflight/root-review result, and does not accept a caller-supplied
envelope digest.  It validates the assembly relationships and derives a
canonical envelope hash from them.

The result is a structural, recomputable identity only.  It is not a trust
root, execution capability, product-reproduction claim, qualification result,
or credit.  The module has no production-data, subprocess, workload, solver,
worker, GPU, queue, registry, ledger, gate, or completion API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


INPUT_SCHEMA = "core.reproduction.independent_evidence_assembly_projection.v1"
SCHEMA = "core.reproduction.independent_evidence_assembly_envelope.v1"
REPORT_SCHEMA = "core.reproduction.independent_evidence_assembly_report.v1"
RECORD_ID = "core-independent-reproduction-evidence-assembly-v1"
REPORT_ID = "core-independent-reproduction-evidence-assembly-report-v1"
STATUS = "synthetic_only_independent_reproduction_assembly_verified"
REPORT_STATUS = "synthetic_only_non_authorizing_independent_reproduction_assembly"

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

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")

PROJECTION_FIELDS = frozenset({
    "schema",
    "input_origin",
    "typed_evidence_categories",
    "typed_evidence_roles",
    "role_artifacts",
    "host_pair",
    "data_roots",
    "components",
    "component_outputs",
})
ROLE_ARTIFACT_FIELDS = frozenset({"category", "artifact"})
ARTIFACT_REF_FIELDS = frozenset({"path", "sha256", "bytes"})
HOST_FIELDS = frozenset({
    "hostname",
    "physical_host_id",
    "passed",
    "diagnostic_only",
    "formal",
    "full_product_reproduction",
})
HOST_PAIR_FIELDS = frozenset({"source_host", "reproduction_host"})
ROOT_FIELDS = frozenset({
    "source_data_root",
    "reproduction_data_root",
    "different_data_root",
    "package_sha256",
    "manifests",
})
MANIFEST_FIELDS = frozenset({"artifact", "data_root", "package_sha256"})
COMPONENT_FIELDS = frozenset({
    "component",
    "physical_host_id",
    "data_root",
    "passed",
    "reproduced",
    "output_report",
    "bindings",
    "diagnostic_only",
    "formal",
    "full_product_reproduction",
})
OUTPUT_COMMON_FIELDS = frozenset({
    "artifact",
    "schema",
    "component",
    "passed",
    "physical_host_id",
    "data_root",
    "diagnostic_only",
    "formal",
    "full_product_reproduction",
})
OUTPUT_FIELDS = {
    "reader": OUTPUT_COMMON_FIELDS | frozenset({"future_state_inputs"}),
    "prediction": OUTPUT_COMMON_FIELDS | frozenset({
        "autonomous",
        "full_horizon",
        "future_state_inputs",
        "predictor_future_state_inputs",
    }),
    "scoring": OUTPUT_COMMON_FIELDS | frozenset({
        "metrics",
        "cases",
        "predictor_future_state_inputs",
    }),
}
OUTPUT_SCHEMAS = {
    "reader": "core.reader_reproduction.v1",
    "prediction": "core.model_reproduction.v1",
    "scoring": "core.model_reproduction.score.v1",
}

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
    """Encode values with the exact representation used by the envelope hash."""
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


def _require_exact(value: Any, expected: frozenset[str], *, label: str) -> None:
    _require(isinstance(value, Mapping), "PROJECTION_OBJECT_REQUIRED", f"{label} must be an object")
    _require(set(value) == expected, "PROJECTION_FIELDS_NOT_EXACT", f"{label} fields are not exact")


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
    _require(
        all(part not in ("", ".", "..") for part in value.split("/")),
        "PATH_NOT_PORTABLE",
        f"{label} path contains an escaping component",
    )
    return value


def _artifact_ref(value: Any, *, label: str) -> dict[str, Any]:
    _require_exact(value, ARTIFACT_REF_FIELDS, label=label)
    path = _portable_path(value.get("path"), label=label)
    declared_sha = _valid_sha(value.get("sha256"), code="ARTIFACT_HASH_INVALID", label=f"{label}.sha256")
    declared_bytes = value.get("bytes")
    _require(
        type(declared_bytes) is int and declared_bytes > 0,
        "ARTIFACT_BYTES_INVALID",
        f"{label}.bytes must be a positive integer",
    )
    return {"path": path, "sha256": declared_sha, "bytes": declared_bytes}


def _diagnostic_projection(value: Mapping[str, Any], *, label: str) -> None:
    _require(value.get("passed") is True, "EVIDENCE_NOT_PASSED", f"{label} is not passed")
    _require(value.get("diagnostic_only") is True, "DIAGNOSTIC_MARKER_MISSING", f"{label} is not diagnostic-only")
    _require(
        value.get("formal") is False and value.get("full_product_reproduction") is False,
        "DIAGNOSTIC_FORMAL_CONFLICT",
        f"{label} claims formal or full-product evidence",
    )


def _canonical_root(value: Any, *, label: str) -> str:
    _require(
        type(value) is str and value.startswith("/") and "\\" not in value,
        "DATA_ROOT_INVALID",
        f"{label} is not an absolute POSIX root",
    )
    parts = value.split("/")
    _require(".." not in parts, "DATA_ROOT_INVALID", f"{label} contains '..'")
    normalized = posixpath.normpath(value)
    _require(normalized.startswith("/") and normalized != ".", "DATA_ROOT_INVALID", f"{label} is invalid")
    return normalized


def _host_projection(value: Any, *, label: str) -> dict[str, str]:
    _require_exact(value, HOST_FIELDS, label=label)
    _diagnostic_projection(value, label=label)
    hostname = value.get("hostname")
    physical_host_id = value.get("physical_host_id")
    _require(type(hostname) is str and bool(hostname.strip()), "HOSTNAME_MISSING", f"{label}.hostname is missing")
    _require(
        type(physical_host_id) is str and bool(physical_host_id.strip()),
        "PHYSICAL_HOST_ID_MISSING",
        f"{label}.physical_host_id is missing",
    )
    return {"hostname": hostname.strip(), "physical_host_id": physical_host_id.strip()}


def _host_key(value: str) -> str:
    return value.rstrip(".").casefold()


def _manifest_projections(value: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    _require(
        isinstance(value, Mapping) and set(value) == {"source_manifest", "reproduction_manifest"},
        "MANIFEST_ROLE_SET_MISMATCH",
        "exactly source_manifest and reproduction_manifest are required",
    )
    result: dict[str, Any] = {}
    refs: dict[str, dict[str, Any]] = {}
    for name in ("source_manifest", "reproduction_manifest"):
        row = value[name]
        _require_exact(row, MANIFEST_FIELDS, label=name)
        ref = _artifact_ref(row.get("artifact"), label=f"{name}.artifact")
        root = _canonical_root(row.get("data_root"), label=f"{name}.data_root")
        package_sha256 = _valid_sha(
            row.get("package_sha256"), code="PACKAGE_HASH_INVALID", label=f"{name}.package_sha256"
        )
        result[name] = {
            "artifact": ref,
            "data_root": root,
            "package_sha256": package_sha256,
        }
        refs[name] = ref
    _require(
        result["source_manifest"]["package_sha256"] == result["reproduction_manifest"]["package_sha256"],
        "PACKAGE_IDENTITY_MISMATCH",
        "source/reproduction package hashes differ",
    )
    return result, refs


def _root_projection(
    value: Any,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    _require_exact(value, ROOT_FIELDS, label="data_roots")
    source = _canonical_root(value.get("source_data_root"), label="source_data_root")
    reproduction = _canonical_root(value.get("reproduction_data_root"), label="reproduction_data_root")
    _require(source != reproduction, "DATA_ROOTS_NOT_DISTINCT", "source/reproduction roots are identical")
    _require(value.get("different_data_root") is True, "DATA_ROOT_DISTINCT_MARKER_MISSING", "distinct-root marker is false")
    package_sha256 = _valid_sha(value.get("package_sha256"), code="PACKAGE_HASH_INVALID", label="data_roots.package_sha256")
    manifests, manifest_refs = _manifest_projections(value.get("manifests"))
    for name, expected_root in (("source_manifest", source), ("reproduction_manifest", reproduction)):
        _require(
            manifests[name]["data_root"] == expected_root,
            "MANIFEST_ROOT_MISMATCH",
            f"{name} does not bind its declared data root",
        )
        _require(
            manifests[name]["package_sha256"] == package_sha256,
            "PACKAGE_IDENTITY_MISMATCH",
            f"{name} package hash differs from data_roots",
        )
    normalized = {
        "source_data_root": source,
        "reproduction_data_root": reproduction,
        "different_data_root": True,
        "package_sha256": package_sha256,
        "manifests": manifests,
    }
    return normalized, manifest_refs, manifests


def _output_projection(
    value: Any,
    *,
    component: str,
    reproduction_host_id: str,
    reproduction_root: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_exact(value, OUTPUT_FIELDS[component], label=f"{component} output")
    _require(value.get("schema") == OUTPUT_SCHEMAS[component], "OUTPUT_SCHEMA_MISMATCH", f"{component} schema is unsupported")
    _require(value.get("component") == component, "COMPONENT_ROLE_MISMATCH", f"{component} output component is inconsistent")
    _diagnostic_projection(value, label=f"{component} output")
    _require(
        value.get("physical_host_id") == reproduction_host_id
        and _canonical_root(value.get("data_root"), label=f"{component}.data_root") == reproduction_root,
        "OUTPUT_HOST_ROOT_MISMATCH",
        f"{component} output is not bound to reproduction host/root",
    )
    if component == "reader":
        _require(value.get("future_state_inputs") is False, "READER_FUTURE_STATE_INPUT", "reader permits future-state inputs")
    elif component == "prediction":
        _require(
            value.get("autonomous") is True
            and value.get("full_horizon") is True
            and value.get("future_state_inputs") is False
            and value.get("predictor_future_state_inputs") is False,
            "PREDICTION_CONTRACT_INCOMPLETE",
            "prediction is not autonomous/full-horizon or permits future-state inputs",
        )
    else:
        _require(value.get("predictor_future_state_inputs") is False, "SCORING_FUTURE_STATE_INPUT", "scoring permits future-state inputs")
        _require(
            value.get("metrics") == {"registered_cases": 1, "complete_fraction": 1.0, "missing_execution": 0}
            and value.get("cases") == ["synthetic-case-0"],
            "SCORING_CONTRACT_INCOMPLETE",
            "scoring denominator is not the exact synthetic denominator",
        )
    return dict(value), _artifact_ref(value.get("artifact"), label=f"{component} output artifact")


def _component_projections(
    value: Any,
    *,
    role_refs: Mapping[str, Mapping[str, Any]],
    output_payloads: Mapping[str, Mapping[str, Any]],
    output_refs: Mapping[str, Mapping[str, Any]],
    reproduction_host_id: str,
    reproduction_root: str,
    reproduction_manifest_sha256: str,
) -> dict[str, dict[str, Any]]:
    _require(
        isinstance(value, Mapping) and set(value) == set(COMPONENTS),
        "COMPONENT_SET_MISMATCH",
        "components must contain exactly reader, prediction, and scoring",
    )
    result: dict[str, dict[str, Any]] = {}
    for component in COMPONENTS:
        row = value[component]
        _require_exact(row, COMPONENT_FIELDS, label=component)
        _require(
            row.get("component") == component and row.get("reproduced") is True,
            "COMPONENT_ROLE_MISMATCH",
            f"{component} component identity/reproduced marker is inconsistent",
        )
        _diagnostic_projection(row, label=component)
        _require(
            row.get("physical_host_id") == reproduction_host_id
            and _canonical_root(row.get("data_root"), label=f"{component}.data_root") == reproduction_root,
            "COMPONENT_HOST_ROOT_MISMATCH",
            f"{component} is not bound to reproduction host/root",
        )
        _require(
            row.get("output_report") == output_refs[component],
            "OUTPUT_ARTIFACT_BINDING_MISMATCH",
            f"{component} output_report differs from its output projection",
        )
        if component == "reader":
            expected_bindings = {"reproduction_manifest_sha256": reproduction_manifest_sha256}
        elif component == "prediction":
            expected_bindings = {"reader_output_sha256": output_refs["reader"]["sha256"]}
        else:
            expected_bindings = {
                "reader_output_sha256": output_refs["reader"]["sha256"],
                "prediction_output_sha256": output_refs["prediction"]["sha256"],
            }
        _require(row.get("bindings") == expected_bindings, "COMPONENT_CHAIN_HASH_MISMATCH", f"{component} bindings are not exact")
        result[component] = {
            "component": component,
            "evidence_artifact": dict(role_refs[component]),
            "output_artifact": dict(output_refs[component]),
            "output_schema": output_payloads[component]["schema"],
            "bindings": dict(expected_bindings),
        }
    return result


def _build_envelope(
    *,
    role_refs: Mapping[str, Mapping[str, Any]],
    roots: Mapping[str, Any],
    hosts: Mapping[str, Mapping[str, str]],
    components: Mapping[str, Mapping[str, Any]],
    output_refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    manifests = roots["manifests"]
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "version": 1,
        "input_origin": "synthetic_fixture",
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "role_artifacts": {
            role: {"category": ROLE_TO_CATEGORY[role], "artifact": dict(role_refs[role])}
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
                    "artifact": dict(manifests[name]["artifact"]),
                    "data_root": manifests[name]["data_root"],
                    "package_sha256": manifests[name]["package_sha256"],
                }
                for name in ("source_manifest", "reproduction_manifest")
            },
        },
        "reader_prediction_scoring_chain": {
            "reader_output_sha256": output_refs["reader"]["sha256"],
            "prediction_input_reader_output_sha256": components["prediction"]["bindings"]["reader_output_sha256"],
            "scoring_input_reader_output_sha256": components["scoring"]["bindings"]["reader_output_sha256"],
            "prediction_output_sha256": output_refs["prediction"]["sha256"],
            "scoring_input_prediction_output_sha256": components["scoring"]["bindings"]["prediction_output_sha256"],
            "scoring_output_sha256": output_refs["scoring"]["sha256"],
            "chain_complete": True,
        },
        "components": {component: dict(components[component]) for component in COMPONENTS},
        "manifest_artifacts": {
            name: dict(manifests[name]["artifact"])
            for name in ("source_manifest", "reproduction_manifest")
        },
        "component_output_artifacts": {
            component: dict(output_refs[component]) for component in COMPONENTS
        },
    }


def recompute_envelope_sha256(envelope: Mapping[str, Any]) -> str:
    """Recompute the exact digest published beside an assembly envelope."""
    _require(isinstance(envelope, Mapping), "ENVELOPE_INVALID", "envelope must be an object")
    _require(envelope.get("schema") == SCHEMA, "ENVELOPE_SCHEMA_MISMATCH", "envelope schema is unsupported")
    return _sha256(canonical_json_bytes(dict(envelope), label="assembly envelope"))


def verify_assembly_projection(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Verify only assembly relationships in a synthetic evidence projection."""
    _require_exact(projection, PROJECTION_FIELDS, label="assembly projection")
    _require(projection.get("schema") == INPUT_SCHEMA, "PROJECTION_SCHEMA_MISMATCH", "assembly projection schema is unsupported")
    _require(projection.get("input_origin") == "synthetic_fixture", "NON_SYNTHETIC_INPUT", "projection is not synthetic_fixture")
    _require(projection.get("typed_evidence_categories") == list(CATEGORIES), "CATEGORY_SET_MISMATCH", "typed evidence categories are not exact")
    _require(projection.get("typed_evidence_roles") == list(ROLES), "ROLE_SET_MISMATCH", "typed evidence roles are not exact")

    role_rows = projection.get("role_artifacts")
    _require(isinstance(role_rows, Mapping) and set(role_rows) == set(ROLES), "ROLE_SET_MISMATCH", "role artifacts are not exact")
    role_refs: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for role in ROLES:
        row = role_rows[role]
        _require_exact(row, ROLE_ARTIFACT_FIELDS, label=role)
        _require(row.get("category") == ROLE_TO_CATEGORY[role], "ROLE_CATEGORY_MISMATCH", f"{role} category is inconsistent")
        ref = _artifact_ref(row.get("artifact"), label=f"{role}.artifact")
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE", f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
        role_refs[role] = ref

    host_pair = projection.get("host_pair")
    _require_exact(host_pair, HOST_PAIR_FIELDS, label="host_pair")
    source_host = _host_projection(host_pair["source_host"], label="source_host")
    reproduction_host = _host_projection(host_pair["reproduction_host"], label="reproduction_host")
    _require(
        _host_key(source_host["hostname"]) != _host_key(reproduction_host["hostname"])
        and source_host["physical_host_id"] != reproduction_host["physical_host_id"],
        "SAME_HOST_RELOCATION_REJECTED",
        "source/reproduction hosts are not distinct",
    )

    roots, manifest_refs, _ = _root_projection(projection.get("data_roots"))
    for ref in manifest_refs.values():
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE", f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])

    output_rows = projection.get("component_outputs")
    _require(isinstance(output_rows, Mapping) and set(output_rows) == set(COMPONENTS), "COMPONENT_SET_MISMATCH", "component outputs are not exact")
    output_payloads: dict[str, dict[str, Any]] = {}
    output_refs: dict[str, dict[str, Any]] = {}
    for component in COMPONENTS:
        payload, ref = _output_projection(
            output_rows[component],
            component=component,
            reproduction_host_id=reproduction_host["physical_host_id"],
            reproduction_root=roots["reproduction_data_root"],
        )
        _require(ref["path"] not in paths, "ARTIFACT_PATH_DUPLICATE", f"artifact path is reused: {ref['path']}")
        paths.add(ref["path"])
        output_payloads[component] = payload
        output_refs[component] = ref

    components = _component_projections(
        projection.get("components"),
        role_refs=role_refs,
        output_payloads=output_payloads,
        output_refs=output_refs,
        reproduction_host_id=reproduction_host["physical_host_id"],
        reproduction_root=roots["reproduction_data_root"],
        reproduction_manifest_sha256=manifest_refs["reproduction_manifest"]["sha256"],
    )
    envelope = _build_envelope(
        role_refs=role_refs,
        roots=roots,
        hosts={"source_host": source_host, "reproduction_host": reproduction_host},
        components=components,
        output_refs=output_refs,
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
            "synthetic_projection_only": True,
            "raw_artifacts_read": False,
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
            "artifact_bytes_reverified": False,
        },
        "interpretation": (
            "Deterministic structural assembly of a synthetic typed-evidence "
            "projection only. The envelope hash is recomputable lineage metadata; "
            "it is not a trusted root, formal/product reproduction, admission, "
            "qualification, or credit claim."
        ),
    }


def verify_synthetic_assembly(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility-named entry point for the synthetic projection verifier."""
    return verify_assembly_projection(projection)


def _ref(path: str, sha256: str, bytes_count: int) -> dict[str, Any]:
    return {"path": path, "sha256": sha256, "bytes": bytes_count}


def synthetic_projection() -> dict[str, Any]:
    """Return a deterministic projection with no filesystem dependency."""
    source_root = "/synthetic/core/source"
    reproduction_root = "/synthetic/core/reproduction"
    source_host_id = "physical-source-assembly-001"
    reproduction_host_id = "physical-reproduction-assembly-001"
    package_sha256 = "b" * 64
    role_refs = {
        "source_host": _ref("typed/source-host.json", "1" * 64, 288),
        "reproduction_host": _ref("typed/reproduction-host.json", "2" * 64, 306),
        "data_roots": _ref("typed/data-roots.json", "3" * 64, 832),
        "reader": _ref("typed/reader-evidence.json", "4" * 64, 639),
        "prediction": _ref("typed/prediction-evidence.json", "5" * 64, 647),
        "scoring": _ref("typed/scoring-evidence.json", "6" * 64, 729),
    }
    manifest_refs = {
        "source_manifest": _ref("manifests/source-package.json", "7" * 64, 278),
        "reproduction_manifest": _ref("manifests/reproduction-package.json", "8" * 64, 284),
    }
    output_refs = {
        "reader": _ref("outputs/reader.json", "9" * 64, 300),
        "prediction": _ref("outputs/prediction.json", "a" * 64, 379),
        "scoring": _ref("outputs/scoring.json", "c" * 64, 424),
    }
    diagnostic = {
        "passed": True,
        "diagnostic_only": True,
        "formal": False,
        "full_product_reproduction": False,
    }
    return {
        "schema": INPUT_SCHEMA,
        "input_origin": "synthetic_fixture",
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "role_artifacts": {
            role: {"category": ROLE_TO_CATEGORY[role], "artifact": ref}
            for role, ref in role_refs.items()
        },
        "host_pair": {
            "source_host": {
                **diagnostic,
                "hostname": "synthetic-source-host",
                "physical_host_id": source_host_id,
            },
            "reproduction_host": {
                **diagnostic,
                "hostname": "synthetic-reproduction-host",
                "physical_host_id": reproduction_host_id,
            },
        },
        "data_roots": {
            "source_data_root": source_root,
            "reproduction_data_root": reproduction_root,
            "different_data_root": True,
            "package_sha256": package_sha256,
            "manifests": {
                "source_manifest": {
                    "artifact": manifest_refs["source_manifest"],
                    "data_root": source_root,
                    "package_sha256": package_sha256,
                },
                "reproduction_manifest": {
                    "artifact": manifest_refs["reproduction_manifest"],
                    "data_root": reproduction_root,
                    "package_sha256": package_sha256,
                },
            },
        },
        "component_outputs": {
            "reader": {
                **diagnostic,
                "artifact": output_refs["reader"],
                "schema": OUTPUT_SCHEMAS["reader"],
                "component": "reader",
                "physical_host_id": reproduction_host_id,
                "data_root": reproduction_root,
                "future_state_inputs": False,
            },
            "prediction": {
                **diagnostic,
                "artifact": output_refs["prediction"],
                "schema": OUTPUT_SCHEMAS["prediction"],
                "component": "prediction",
                "physical_host_id": reproduction_host_id,
                "data_root": reproduction_root,
                "autonomous": True,
                "full_horizon": True,
                "future_state_inputs": False,
                "predictor_future_state_inputs": False,
            },
            "scoring": {
                **diagnostic,
                "artifact": output_refs["scoring"],
                "schema": OUTPUT_SCHEMAS["scoring"],
                "component": "scoring",
                "physical_host_id": reproduction_host_id,
                "data_root": reproduction_root,
                "metrics": {"registered_cases": 1, "complete_fraction": 1.0, "missing_execution": 0},
                "cases": ["synthetic-case-0"],
                "predictor_future_state_inputs": False,
            },
        },
        "components": {
            "reader": {
                **diagnostic,
                "component": "reader",
                "physical_host_id": reproduction_host_id,
                "data_root": reproduction_root,
                "reproduced": True,
                "output_report": output_refs["reader"],
                "bindings": {"reproduction_manifest_sha256": manifest_refs["reproduction_manifest"]["sha256"]},
            },
            "prediction": {
                **diagnostic,
                "component": "prediction",
                "physical_host_id": reproduction_host_id,
                "data_root": reproduction_root,
                "reproduced": True,
                "output_report": output_refs["prediction"],
                "bindings": {"reader_output_sha256": output_refs["reader"]["sha256"]},
            },
            "scoring": {
                **diagnostic,
                "component": "scoring",
                "physical_host_id": reproduction_host_id,
                "data_root": reproduction_root,
                "reproduced": True,
                "output_report": output_refs["scoring"],
                "bindings": {
                    "reader_output_sha256": output_refs["reader"]["sha256"],
                    "prediction_output_sha256": output_refs["prediction"]["sha256"],
                },
            },
        },
    }


def build_report() -> dict[str, Any]:
    result = verify_assembly_projection(synthetic_projection())
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
            "missing_or_extra_role_or_category": "reject",
            "same_host_relocation": "reject",
            "same_data_root_after_canonicalization": "reject",
            "artifact_descriptor_path_hash_bytes_mismatch": "reject",
            "reader_prediction_scoring_hash_rebind": "reject",
            "diagnostic_projection_claiming_formal_product": "reject",
            "caller_supplied_envelope_digest": "not_consumed",
            "raw_artifact_or_production_bundle": "not_consumed",
            "root_review_or_capability_claim": "not_consumed",
        },
        "interpretation": result["interpretation"],
    }


def write_json_once(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write a new report without replacing an existing receipt."""
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
