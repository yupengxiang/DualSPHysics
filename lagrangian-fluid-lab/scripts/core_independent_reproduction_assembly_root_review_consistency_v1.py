#!/usr/bin/env python3
"""Bind the Core assembly V1 result to the UPDATE-311 root-review result.

This is a narrow, synthetic-only composition layer.  The two upstream
verifiers remain responsible for their own evidence semantics:

* ``core_independent_reproduction_evidence_assembly_v1.py`` validates the
  assembly projection and derives the assembly envelope digest; and
* ``core_independent_reproduction_root_review_adapter_v1.py`` validates the
  typed-evidence/root-review fixture and derives the root-review bindings.

This module consumes only bounded, canonical, in-memory *result projections*
from those verifiers.  It does not read their reports or raw artifacts and it
does not reimplement either verifier.  It checks that the host pair,
data-roots/manifests, role artifacts, component outputs, reader -> prediction
-> scoring chain, and UPDATE-311 root-review decision all refer to the same
synthetic evidence projection.

The composition is intentionally non-authorizing.  It cannot authenticate a
root review, mint a capability, prove real cross-host reproduction, or change
any campaign state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import core_independent_reproduction_evidence_assembly_v1 as assembly
from scripts import core_independent_reproduction_root_review_adapter_v1 as root_review


INPUT_SCHEMA = "core.reproduction.independent_assembly_root_review_consistency_projection.v1"
SCHEMA = "core.reproduction.independent_assembly_root_review_consistency.v1"
REPORT_SCHEMA = "core.reproduction.independent_assembly_root_review_consistency_report.v1"
RECORD_ID = "core-independent-reproduction-assembly-root-review-consistency-v1"
REPORT_ID = "core-independent-reproduction-assembly-root-review-consistency-report-v1"
STATUS = "synthetic_only_assembly_root_review_consistent_non_authorizing"
REPORT_STATUS = "synthetic_only_non_authorizing_assembly_root_review_consistency"
BINDING_SCHEMA = "core.reproduction.assembly_root_review_consistency_binding.v1"

MAX_PROJECTION_BYTES = 512 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

PROJECTION_FIELDS = frozenset({
    "schema", "input_origin", "assembly_result", "root_review_result",
})
ASSEMBLY_RESULT_FIELDS = frozenset({
    "assembly_envelope", "assembly_envelope_sha256", "capability_minted",
    "credit", "diagnostic_only", "envelope_hash_recomputed",
    "execution_constraints", "full_product_reproduction", "input_origin",
    "interpretation", "non_authorizing_boundary", "qualification_credit",
    "record_id", "schema", "status", "synthetic_only",
    "typed_evidence_categories", "typed_evidence_roles", "upstream_boundary",
})
ROOT_RESULT_FIELDS = frozenset({
    "assembly", "binding", "capability_minted", "credit", "cross_host_claim",
    "diagnostic_only", "evidence_manifest", "execution_constraints",
    "formal_training_count", "full_product_reproduction", "input_origin",
    "interpretation", "non_authorizing_boundary", "qualification_credit",
    "real_cross_host_reproduction", "record_id", "root_review", "schema",
    "status", "synthetic_only", "typed_evidence_categories",
    "typed_evidence_roles",
})

ENVELOPE_FIELDS = frozenset({
    "component_output_artifacts", "components", "data_roots", "host_pair",
    "input_origin", "manifest_artifacts", "reader_prediction_scoring_chain",
    "record_id", "role_artifacts", "schema", "typed_evidence_categories",
    "typed_evidence_roles", "version",
})
ENVELOPE_HOST_PAIR_FIELDS = frozenset({
    "source_host", "reproduction_host", "distinct_hostnames",
    "distinct_physical_hosts",
})
ENVELOPE_HOST_FIELDS = frozenset({"hostname", "physical_host_id"})
ENVELOPE_DATA_ROOT_FIELDS = frozenset({
    "source_data_root", "reproduction_data_root", "different_data_root",
    "distinct_data_roots", "package_sha256", "manifest_artifacts",
})
ENVELOPE_COMPONENT_FIELDS = frozenset({
    "component", "evidence_artifact", "output_artifact", "output_schema",
    "bindings",
})
CHAIN_FIELDS = frozenset({
    "reader_output_sha256", "prediction_input_reader_output_sha256",
    "scoring_input_reader_output_sha256", "prediction_output_sha256",
    "scoring_input_prediction_output_sha256", "scoring_output_sha256",
    "chain_complete",
})
COMPONENT_BINDING_FIELDS = {
    "reader": frozenset({"reproduction_manifest_sha256"}),
    "prediction": frozenset({"reader_output_sha256"}),
    "scoring": frozenset({"reader_output_sha256", "prediction_output_sha256"}),
}

ROOT_ASSEMBLY_FIELDS = frozenset({
    "components", "data_roots", "distinct_data_roots",
    "distinct_physical_hosts", "reproduction_host", "source_host",
})
ROOT_HOST_FIELDS = frozenset({"hostname", "physical_host_id"})
ROOT_DATA_ROOT_FIELDS = frozenset({
    "source_data_root", "reproduction_data_root", "different_data_root",
    "package_sha256", "manifests",
})
ROOT_COMPONENT_FIELDS = frozenset({
    "component", "physical_host_id", "data_root", "output_report",
    "output_schema", "output_sha256", "bindings",
})
ROOT_REVIEW_FIELDS = frozenset({
    "artifact", "decision", "decision_sha256",
    "decision_bound", "trusted_root_authenticated",
    "caller_self_asserted_trusted_root_accepted",
})
ROOT_DECISION_FIELDS = frozenset({
    "all_eight_required_outputs_verified", "diagnostic_only",
    "formal_training_count", "full_core_reproduction_proven",
    "registered_comparison_pass", "schema", "scope",
    "two_terminal_reports_verified",
})
ROOT_SCOPE_FIELDS = frozenset({
    "all_particle_axis", "case_id", "diagnostic_only", "family",
    "formal_training_count", "full_horizon", "particle_count",
    "scientific_qualification", "split", "trajectory_frames", "transitions",
})
ROOT_BINDING_FIELDS = frozenset({
    "binding_claim_artifact", "binding_claim_sha256", "canonical_encoding",
    "component_output_artifacts", "manifest_artifacts", "preflight_artifact",
    "preflight_sha256", "role_artifacts", "root_review_artifact",
    "root_review_artifact_sha256", "root_review_decision_sha256",
    "typed_evidence_manifest_sha256",
})
EVIDENCE_MANIFEST_FIELDS = frozenset({
    "category_count", "role_count", "schema", "sha256",
})

NON_AUTHORIZING_BOUNDARY = {
    "diagnostic_only": True,
    "capability_minted": False,
    "full_product_reproduction": False,
    "formal_admission": False,
    "formal_training_count": 0,
    "root_review_authenticated": False,
    "real_cross_host_reproduction": False,
    "cross_host_claim": False,
    "credit": 0,
    "qualification_credit": 0,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
}

EXECUTION_CONSTRAINTS = {
    "read_only": True,
    "synthetic_in_memory_only": True,
    "production_artifacts_read": False,
    "raw_artifacts_read": False,
    "workload_started": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_mutation": 0,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
}

UPSTREAM_BOUNDARY = {
    "assembly_v1_result_projection_consumed": True,
    "update_311_root_review_result_projection_consumed": True,
    "root_review_authenticated": False,
    "capability_consumer_present": False,
    "production_artifact_read": False,
    "raw_artifacts_read": False,
}


class AssemblyRootReviewConsistencyError(ValueError):
    """A bounded projection or cross-contract binding failed closed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise AssemblyRootReviewConsistencyError(code, message)


def canonical_json_bytes(value: Any, *, label: str = "value") -> bytes:
    """Encode the exact canonical JSON representation used by this bridge."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise AssemblyRootReviewConsistencyError(
            "NON_CANONICAL_JSON", f"{label} is not canonical JSON serializable"
        ) from error


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(value: Any, *, label: str) -> str:
    return _sha256(canonical_json_bytes(value, label=label))


def _exact(value: Any, expected: frozenset[str], *, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "OBJECT_REQUIRED", f"{label} must be an object")
    _require(set(value) == expected, "FIELDS_NOT_EXACT", f"{label} fields are not exact")
    return value


def _sha256_text(value: Any, *, label: str) -> str:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             "SHA256_INVALID", f"{label} is not a lowercase SHA-256")
    return value


def _artifact_ref(value: Any, *, label: str) -> dict[str, Any]:
    row = _exact(value, frozenset({"path", "sha256", "bytes"}), label=label)
    _require(type(row["path"]) is str and bool(row["path"])
             and "\\" not in row["path"] and ".." not in row["path"].split("/"),
             "ARTIFACT_PATH_INVALID", f"{label}.path is not portable")
    _sha256_text(row["sha256"], label=f"{label}.sha256")
    _require(type(row["bytes"]) is int and row["bytes"] > 0,
             "ARTIFACT_BYTES_INVALID", f"{label}.bytes must be positive")
    return dict(row)


def _artifact_map(value: Any, names: Sequence[str], *, label: str) -> dict[str, dict[str, Any]]:
    row = _exact(value, frozenset(names), label=label)
    return {name: _artifact_ref(row[name], label=f"{label}.{name}") for name in names}


def _bounded_projection(value: Any, *, label: str) -> bytes:
    raw = canonical_json_bytes(value, label=label)
    _require(len(raw) <= MAX_PROJECTION_BYTES, "PROJECTION_TOO_LARGE",
             f"{label} exceeds the bounded projection size")
    return raw


def _validate_envelope(envelope: Any) -> Mapping[str, Any]:
    envelope = _exact(envelope, ENVELOPE_FIELDS, label="assembly envelope")
    _require(envelope["schema"] == assembly.SCHEMA,
             "ASSEMBLY_SCHEMA_MISMATCH", "assembly envelope schema is unsupported")
    _require(envelope["input_origin"] == "synthetic_fixture",
             "ASSEMBLY_ORIGIN_INVALID", "assembly envelope is not synthetic_fixture")
    _require(envelope["typed_evidence_categories"] == list(assembly.CATEGORIES),
             "ASSEMBLY_CATEGORY_MISMATCH", "assembly categories are not exact")
    _require(envelope["typed_evidence_roles"] == list(assembly.ROLES),
             "ASSEMBLY_ROLE_MISMATCH", "assembly roles are not exact")

    role_rows = _exact(envelope["role_artifacts"], frozenset(assembly.ROLES),
                       label="assembly role artifacts")
    for role in assembly.ROLES:
        row = _exact(role_rows[role], frozenset({"category", "artifact"}),
                     label=f"assembly role {role}")
        _require(row["category"] == assembly.ROLE_TO_CATEGORY[role],
                 "ROLE_CATEGORY_MISMATCH", f"assembly role {role} category differs")
        _artifact_ref(row["artifact"], label=f"assembly role {role}.artifact")

    host_pair = _exact(envelope["host_pair"], ENVELOPE_HOST_PAIR_FIELDS,
                       label="assembly host pair")
    for role in ("source_host", "reproduction_host"):
        host = _exact(host_pair[role], ENVELOPE_HOST_FIELDS,
                      label=f"assembly {role}")
        _require(type(host["hostname"]) is str and type(host["physical_host_id"]) is str,
                 "HOST_ID_INVALID", f"assembly {role} identity is invalid")
    _require(host_pair["distinct_hostnames"] is True
             and host_pair["distinct_physical_hosts"] is True,
             "HOST_DISTINCTNESS_MISSING", "assembly host distinctness is not true")

    roots = _exact(envelope["data_roots"], ENVELOPE_DATA_ROOT_FIELDS,
                   label="assembly data roots")
    _require(type(roots["source_data_root"]) is str
             and type(roots["reproduction_data_root"]) is str
             and roots["different_data_root"] is True
             and roots["distinct_data_roots"] is True,
             "DATA_ROOT_CONTRACT_INVALID", "assembly data-root contract is not closed")
    _sha256_text(roots["package_sha256"], label="assembly package_sha256")
    root_manifest_rows = _exact(
        roots["manifest_artifacts"],
        frozenset({"source_manifest", "reproduction_manifest"}),
        label="assembly manifest artifacts",
    )
    for name in ("source_manifest", "reproduction_manifest"):
        manifest = _exact(
            root_manifest_rows[name],
            frozenset({"artifact", "data_root", "package_sha256"}),
            label=f"assembly manifest descriptor {name}",
        )
        _artifact_ref(manifest["artifact"], label=f"assembly manifest {name}.artifact")
        _require(type(manifest["data_root"]) is str,
                 "MANIFEST_ROOT_INVALID", f"assembly manifest {name}.data_root is invalid")
        _sha256_text(manifest["package_sha256"],
                     label=f"assembly manifest {name}.package_sha256")
    manifest_rows = _exact(envelope["manifest_artifacts"],
                           frozenset({"source_manifest", "reproduction_manifest"}),
                           label="assembly manifest artifact index")
    for name in ("source_manifest", "reproduction_manifest"):
        _artifact_ref(manifest_rows[name], label=f"assembly manifest {name}")

    output_rows = _exact(envelope["component_output_artifacts"],
                         frozenset(assembly.COMPONENTS),
                         label="assembly component output artifacts")
    for component in assembly.COMPONENTS:
        _artifact_ref(output_rows[component], label=f"assembly output {component}")

    component_rows = _exact(envelope["components"], frozenset(assembly.COMPONENTS),
                            label="assembly component envelope")
    for component in assembly.COMPONENTS:
        row = _exact(component_rows[component], ENVELOPE_COMPONENT_FIELDS,
                     label=f"assembly component {component}")
        _require(row["component"] == component,
                 "COMPONENT_IDENTITY_MISMATCH", f"assembly component {component} differs")
        _artifact_ref(row["evidence_artifact"], label=f"assembly {component}.evidence_artifact")
        _artifact_ref(row["output_artifact"], label=f"assembly {component}.output_artifact")
        _require(type(row["output_schema"]) is str,
                 "OUTPUT_SCHEMA_INVALID", f"assembly {component} output schema is invalid")
        bindings = _exact(row["bindings"], COMPONENT_BINDING_FIELDS[component],
                          label=f"assembly {component}.bindings")
        for field in COMPONENT_BINDING_FIELDS[component]:
            _sha256_text(bindings[field], label=f"assembly {component}.bindings.{field}")

    chain = _exact(envelope["reader_prediction_scoring_chain"], CHAIN_FIELDS,
                   label="assembly reader/prediction/scoring chain")
    for field in CHAIN_FIELDS - {"chain_complete"}:
        _sha256_text(chain[field], label=f"assembly chain {field}")
    _require(chain["chain_complete"] is True,
             "CHAIN_INCOMPLETE", "assembly reader/prediction/scoring chain is incomplete")
    return envelope


def _validate_assembly_result(value: Any) -> Mapping[str, Any]:
    result = _exact(value, ASSEMBLY_RESULT_FIELDS, label="assembly result projection")
    _require(result["schema"] == assembly.SCHEMA and result["status"] == assembly.STATUS,
             "ASSEMBLY_RESULT_STATUS_INVALID", "assembly result is not the verified V1 result")
    _require(result["synthetic_only"] is True and result["input_origin"] == "synthetic_fixture",
             "ASSEMBLY_RESULT_ORIGIN_INVALID", "assembly result is not synthetic-only")
    _require(result["diagnostic_only"] is True
             and result["capability_minted"] is False
             and result["full_product_reproduction"] is False
             and result["credit"] == 0
             and result["qualification_credit"] == 0,
             "ASSEMBLY_RESULT_AUTHORITY_INVALID", "assembly result crosses its fixed boundary")
    _require(result["typed_evidence_categories"] == list(assembly.CATEGORIES)
             and result["typed_evidence_roles"] == list(assembly.ROLES),
             "ASSEMBLY_RESULT_TYPES_INVALID", "assembly result categories/roles are not exact")
    _require(result["non_authorizing_boundary"] == assembly.NON_AUTHORIZING_BOUNDARY,
             "ASSEMBLY_BOUNDARY_DRIFT", "assembly result non-authorizing boundary drifted")
    _require(result["execution_constraints"] == {
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
    }, "ASSEMBLY_EXECUTION_BOUNDARY_DRIFT", "assembly execution boundary drifted")
    _require(result["upstream_boundary"] == {
        "update_300_preflight_consumed": False,
        "update_311_root_review_consumed": False,
        "root_review_authenticated": False,
        "capability_consumer_present": False,
        "artifact_bytes_reverified": False,
    }, "ASSEMBLY_UPSTREAM_BOUNDARY_DRIFT", "assembly upstream boundary drifted")
    _validate_envelope(result["assembly_envelope"])
    _sha256_text(result["assembly_envelope_sha256"], label="assembly envelope digest")
    _require(assembly.recompute_envelope_sha256(result["assembly_envelope"])
             == result["assembly_envelope_sha256"]
             and result["envelope_hash_recomputed"] is True,
             "ASSEMBLY_ENVELOPE_HASH_MISMATCH", "assembly envelope digest is not recomputable")
    return result


def _validate_root_assembly(value: Any) -> Mapping[str, Any]:
    result = _exact(value, ROOT_ASSEMBLY_FIELDS, label="root-review assembly projection")
    for role in ("source_host", "reproduction_host"):
        host = _exact(result[role], ROOT_HOST_FIELDS,
                      label=f"root-review {role}")
        _require(type(host["hostname"]) is str and type(host["physical_host_id"]) is str,
                 "ROOT_HOST_ID_INVALID", f"root-review {role} identity is invalid")
    _require(result["distinct_physical_hosts"] is True
             and result["distinct_data_roots"] is True,
             "ROOT_DISTINCTNESS_MISSING", "root-review distinctness is not true")

    roots = _exact(result["data_roots"], ROOT_DATA_ROOT_FIELDS,
                   label="root-review data roots")
    _require(roots["different_data_root"] is True,
             "ROOT_DATA_ROOT_MARKER_MISSING", "root-review data-root marker is false")
    _sha256_text(roots["package_sha256"], label="root-review package_sha256")
    manifests = _exact(roots["manifests"],
                       frozenset({"source_manifest", "reproduction_manifest"}),
                       label="root-review manifests")
    for name in ("source_manifest", "reproduction_manifest"):
        row = _exact(manifests[name], frozenset({"artifact", "data_root", "package_sha256"}),
                     label=f"root-review {name}")
        _artifact_ref(row["artifact"], label=f"root-review {name}.artifact")
        _sha256_text(row["package_sha256"], label=f"root-review {name}.package_sha256")

    components = _exact(result["components"], frozenset(assembly.COMPONENTS),
                        label="root-review components")
    for component in assembly.COMPONENTS:
        row = _exact(components[component], ROOT_COMPONENT_FIELDS,
                     label=f"root-review component {component}")
        _require(row["component"] == component,
                 "ROOT_COMPONENT_IDENTITY_MISMATCH", f"root-review component {component} differs")
        _artifact_ref(row["output_report"], label=f"root-review {component}.output_report")
        _require(type(row["output_schema"]) is str and bool(row["output_schema"]),
                 "ROOT_OUTPUT_SCHEMA_INVALID", f"root-review {component} output schema is invalid")
        _sha256_text(row["output_sha256"], label=f"root-review {component}.output_sha256")
        bindings = _exact(row["bindings"], COMPONENT_BINDING_FIELDS[component],
                          label=f"root-review {component}.bindings")
        for field in COMPONENT_BINDING_FIELDS[component]:
            _sha256_text(bindings[field], label=f"root-review {component}.bindings.{field}")
    return result


def _validate_root_result(value: Any) -> Mapping[str, Any]:
    result = _exact(value, ROOT_RESULT_FIELDS, label="root-review result projection")
    _require(result["schema"] == root_review.SCHEMA
             and result["status"] == root_review.STATUS,
             "ROOT_RESULT_STATUS_INVALID", "root-review result is not the verified UPDATE-311 result")
    _require(result["synthetic_only"] is True and result["input_origin"] == "synthetic_fixture",
             "ROOT_RESULT_ORIGIN_INVALID", "root-review result is not synthetic-only")
    _require(result["diagnostic_only"] is True
             and result["capability_minted"] is False
             and result["full_product_reproduction"] is False
             and result["credit"] == 0
             and result["qualification_credit"] == 0
             and result["formal_training_count"] == 0
             and result["cross_host_claim"] is False
             and result["real_cross_host_reproduction"] is False,
             "ROOT_RESULT_AUTHORITY_INVALID", "root-review result crosses its fixed boundary")
    _require(result["typed_evidence_categories"] == list(assembly.CATEGORIES)
             and result["typed_evidence_roles"] == list(assembly.ROLES),
             "ROOT_RESULT_TYPES_INVALID", "root-review categories/roles are not exact")
    _require(result["non_authorizing_boundary"] == root_review.NON_AUTHORIZING_BOUNDARY,
             "ROOT_BOUNDARY_DRIFT", "root-review result non-authorizing boundary drifted")
    _require(result["execution_constraints"] == {
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
    }, "ROOT_EXECUTION_BOUNDARY_DRIFT", "root-review execution boundary drifted")
    _validate_root_assembly(result["assembly"])

    evidence_manifest = _exact(result["evidence_manifest"], EVIDENCE_MANIFEST_FIELDS,
                               label="root-review evidence manifest")
    _require(evidence_manifest["schema"] == "core.reproduction.typed_evidence_manifest.v1"
             and evidence_manifest["category_count"] == len(assembly.CATEGORIES)
             and evidence_manifest["role_count"] == len(assembly.ROLES),
             "EVIDENCE_MANIFEST_INVALID", "root-review evidence manifest is not exact")
    _sha256_text(evidence_manifest["sha256"], label="root-review evidence manifest sha256")

    root_projection = _exact(result["root_review"], ROOT_REVIEW_FIELDS,
                             label="root-review decision projection")
    _require(root_projection["decision_bound"] is True,
             "ROOT_DECISION_NOT_BOUND", "root-review decision is not marked bound")
    _artifact_ref(root_projection["artifact"], label="root-review decision artifact")
    _require(root_projection["trusted_root_authenticated"] is False
             and root_projection["caller_self_asserted_trusted_root_accepted"] is False,
             "ROOT_TRUST_BOUNDARY_DRIFT", "root-review projection claims authenticated trust")
    decision = _exact(root_projection["decision"], ROOT_DECISION_FIELDS,
                      label="root-review decision")
    _require(decision["schema"] == root_review.ROOT_REVIEW_SCHEMA
             and decision["diagnostic_only"] is True
             and decision["formal_training_count"] == 0
             and decision["full_core_reproduction_proven"] is False,
             "ROOT_DECISION_BOUNDARY_DRIFT", "root-review decision crosses its boundary")
    _exact(decision["scope"], ROOT_SCOPE_FIELDS, label="root-review decision scope")
    _sha256_text(root_projection["decision_sha256"], label="root-review decision sha256")
    _require(_sha256_json(decision, label="root-review decision")
             == root_projection["decision_sha256"],
             "ROOT_DECISION_HASH_MISMATCH", "root-review decision digest is not recomputable")

    binding = _exact(result["binding"], ROOT_BINDING_FIELDS,
                     label="root-review binding")
    for key in (
        "binding_claim_artifact", "preflight_artifact", "root_review_artifact",
    ):
        _artifact_ref(binding[key], label=f"root-review binding.{key}")
    for key in (
        "binding_claim_sha256", "preflight_sha256", "root_review_artifact_sha256",
        "root_review_decision_sha256", "typed_evidence_manifest_sha256",
    ):
        _sha256_text(binding[key], label=f"root-review binding.{key}")
    _require(binding["root_review_decision_sha256"] == root_projection["decision_sha256"],
             "ROOT_BINDING_DECISION_MISMATCH", "root-review binding uses another decision digest")
    _artifact_map(binding["role_artifacts"], assembly.ROLES,
                  label="root-review role artifacts")
    _artifact_map(binding["manifest_artifacts"],
                  ("source_manifest", "reproduction_manifest"),
                  label="root-review manifest artifacts")
    _artifact_map(binding["component_output_artifacts"], assembly.COMPONENTS,
                  label="root-review component output artifacts")
    _require(binding["typed_evidence_manifest_sha256"] == evidence_manifest["sha256"],
             "ROOT_BINDING_MANIFEST_MISMATCH", "root-review binding uses another evidence manifest")
    return result


def _cross_bind(assembly_result: Mapping[str, Any],
                root_result: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    envelope = assembly_result["assembly_envelope"]
    root_assembly = root_result["assembly"]
    root_binding = root_result["binding"]
    root_projection = root_result["root_review"]

    _require(assembly_result["typed_evidence_categories"]
             == root_result["typed_evidence_categories"]
             and assembly_result["typed_evidence_roles"]
             == root_result["typed_evidence_roles"],
             "CROSS_TYPE_SET_MISMATCH", "assembly and root-review categories/roles differ")

    expected_roles = {
        role: {
            "category": assembly.ROLE_TO_CATEGORY[role],
            "artifact": dict(root_binding["role_artifacts"][role]),
        }
        for role in assembly.ROLES
    }
    _require(envelope["role_artifacts"] == expected_roles,
             "CROSS_ROLE_ARTIFACT_MISMATCH", "assembly role artifacts differ from UPDATE-311")

    expected_host_pair = {
        "source_host": dict(root_assembly["source_host"]),
        "reproduction_host": dict(root_assembly["reproduction_host"]),
        "distinct_hostnames": True,
        "distinct_physical_hosts": root_assembly["distinct_physical_hosts"],
    }
    _require(envelope["host_pair"] == expected_host_pair,
             "CROSS_HOST_MISMATCH", "assembly host pair differs from UPDATE-311")

    root_data_roots = root_assembly["data_roots"]
    _require(envelope["data_roots"]["source_data_root"] == root_data_roots["source_data_root"]
             and envelope["data_roots"]["reproduction_data_root"] == root_data_roots["reproduction_data_root"]
             and envelope["data_roots"]["different_data_root"] == root_data_roots["different_data_root"]
             and envelope["data_roots"]["distinct_data_roots"] == root_assembly["distinct_data_roots"]
             and envelope["data_roots"]["package_sha256"] == root_data_roots["package_sha256"]
             and envelope["data_roots"]["manifest_artifacts"] == root_data_roots["manifests"]
             and envelope["manifest_artifacts"] == root_binding["manifest_artifacts"],
             "CROSS_DATA_ROOT_MISMATCH", "assembly data roots/manifests differ from UPDATE-311")

    _require(envelope["component_output_artifacts"]
             == root_binding["component_output_artifacts"],
             "CROSS_OUTPUT_ARTIFACT_MISMATCH",
             "assembly component outputs differ from UPDATE-311")
    expected_components: dict[str, dict[str, Any]] = {}
    for component in assembly.COMPONENTS:
        root_component = root_assembly["components"][component]
        expected_components[component] = {
            "component": component,
            "evidence_artifact": dict(root_binding["role_artifacts"][component]),
            "output_artifact": dict(root_binding["component_output_artifacts"][component]),
            "output_schema": root_component["output_schema"],
            "bindings": dict(root_component["bindings"]),
        }
    _require(envelope["components"] == expected_components,
             "CROSS_COMPONENT_MISMATCH", "assembly components differ from UPDATE-311")

    reader = root_assembly["components"]["reader"]
    prediction = root_assembly["components"]["prediction"]
    scoring = root_assembly["components"]["scoring"]
    expected_chain = {
        "reader_output_sha256": reader["output_sha256"],
        "prediction_input_reader_output_sha256": prediction["bindings"]["reader_output_sha256"],
        "scoring_input_reader_output_sha256": scoring["bindings"]["reader_output_sha256"],
        "prediction_output_sha256": prediction["output_sha256"],
        "scoring_input_prediction_output_sha256": scoring["bindings"]["prediction_output_sha256"],
        "scoring_output_sha256": scoring["output_sha256"],
        "chain_complete": True,
    }
    _require(envelope["reader_prediction_scoring_chain"] == expected_chain,
             "CROSS_CHAIN_MISMATCH", "reader/prediction/scoring chain differs from UPDATE-311")

    _require(root_binding["root_review_artifact"] == root_projection["artifact"],
             "CROSS_ROOT_ARTIFACT_MISMATCH", "root-review artifact binding is inconsistent")
    _require(root_binding["root_review_artifact_sha256"] == root_projection["artifact"]["sha256"],
             "CROSS_ROOT_ARTIFACT_HASH_MISMATCH", "root-review artifact digest is inconsistent")
    _require(root_binding["root_review_decision_sha256"] == root_projection["decision_sha256"],
             "CROSS_ROOT_DECISION_HASH_MISMATCH", "root-review decision digest is inconsistent")
    _require(
        root_binding["manifest_artifacts"] == {
            name: dict(root_data_roots["manifests"][name]["artifact"])
            for name in ("source_manifest", "reproduction_manifest")
        },
        "CROSS_ROOT_MANIFEST_MISMATCH",
        "UPDATE-311 manifest binding is inconsistent with its assembly projection",
    )
    _require(
        root_binding["component_output_artifacts"] == {
            component: dict(root_assembly["components"][component]["output_report"])
            for component in assembly.COMPONENTS
        },
        "CROSS_ROOT_OUTPUT_MISMATCH",
        "UPDATE-311 component output binding is inconsistent with its assembly projection",
    )

    cross_binding = {
        "schema": BINDING_SCHEMA,
        "input_origin": "synthetic_fixture",
        "assembly_envelope_sha256": assembly_result["assembly_envelope_sha256"],
        "root_review_artifact_sha256": root_binding["root_review_artifact_sha256"],
        "root_review_decision_sha256": root_binding["root_review_decision_sha256"],
        "typed_evidence_manifest_sha256": root_binding["typed_evidence_manifest_sha256"],
        "role_artifacts": expected_roles,
        "manifest_artifacts": dict(root_binding["manifest_artifacts"]),
        "component_output_artifacts": dict(root_binding["component_output_artifacts"]),
        "reader_prediction_scoring_chain": expected_chain,
        "consistent": True,
    }
    return cross_binding, _sha256_json(cross_binding, label="cross-contract binding")


def verify_consistency_projection(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Verify two already-produced result projections and their cross-bindings."""
    _bounded_projection(projection, label="consistency projection")
    _exact(projection, PROJECTION_FIELDS, label="consistency projection")
    _require(projection["schema"] == INPUT_SCHEMA,
             "PROJECTION_SCHEMA_MISMATCH", "consistency projection schema is unsupported")
    _require(projection["input_origin"] == "synthetic_fixture",
             "NON_SYNTHETIC_INPUT", "consistency projection is not synthetic_fixture")
    _bounded_projection(projection["assembly_result"], label="assembly result projection")
    _bounded_projection(projection["root_review_result"], label="root-review result projection")

    assembly_result = _validate_assembly_result(projection["assembly_result"])
    root_result = _validate_root_result(projection["root_review_result"])
    cross_binding, cross_binding_sha256 = _cross_bind(assembly_result, root_result)
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
        "formal_training_count": 0,
        "typed_evidence_categories": list(assembly.CATEGORIES),
        "typed_evidence_roles": list(assembly.ROLES),
        "assembly": {
            "schema": assembly_result["schema"],
            "status": assembly_result["status"],
            "envelope": assembly_result["assembly_envelope"],
            "envelope_sha256": assembly_result["assembly_envelope_sha256"],
        },
        "root_review": {
            "adapter_schema": root_result["schema"],
            "adapter_status": root_result["status"],
            "artifact": root_result["root_review"]["artifact"],
            "decision": root_result["root_review"]["decision"],
            "decision_sha256": root_result["root_review"]["decision_sha256"],
            "trusted_root_authenticated": False,
            "caller_self_asserted_trusted_root_accepted": False,
        },
        "cross_binding": cross_binding,
        "cross_binding_sha256": cross_binding_sha256,
        "non_authorizing_boundary": dict(NON_AUTHORIZING_BOUNDARY),
        "execution_constraints": dict(EXECUTION_CONSTRAINTS),
        "upstream_boundary": dict(UPSTREAM_BOUNDARY),
        "rejection_contract": {
            "assembly_envelope_hash_drift": "reject",
            "assembly_root_or_host_drift": "reject",
            "manifest_or_role_artifact_drift": "reject",
            "reader_prediction_scoring_chain_drift": "reject",
            "root_review_artifact_or_decision_drift": "reject",
            "formal_or_full_product_claim": "reject",
            "noncanonical_or_oversized_projection": "reject",
            "production_artifact_or_path_read": "not consumed",
            "caller_supplied_capability_or_trust": "not consumed",
        },
        "interpretation": (
            "Exact cross-contract consistency of two synthetic result projections; "
            "the binding digest is lineage metadata only and is not trusted-root "
            "authentication, real cross-host reproduction, formal admission, "
            "qualification, or credit."
        ),
    }


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row["raw"]
    _require(type(raw) is bytes, "SYNTHETIC_RAW_TYPE_INVALID", "synthetic fixture raw bytes are not bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssemblyRootReviewConsistencyError(
            "SYNTHETIC_RAW_INVALID", "synthetic fixture raw bytes are not JSON"
        ) from error
    _require(isinstance(value, dict), "SYNTHETIC_RAW_OBJECT_REQUIRED", "synthetic raw payload is not an object")
    return value


def _assembly_projection_from_root_fixture(
    root_fixture: Mapping[str, Any],
    root_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one consistent synthetic assembly input from UPDATE-311 output."""
    root_assembly = root_result["assembly"]
    binding = root_result["binding"]
    host_rows = {
        role: _payload(root_fixture["typed_evidence"][role])
        for role in ("source_host", "reproduction_host")
    }
    role_artifacts = {
        role: {
            "category": assembly.ROLE_TO_CATEGORY[role],
            "artifact": dict(binding["role_artifacts"][role]),
        }
        for role in assembly.ROLES
    }
    manifests = {
        name: {
            "artifact": dict(binding["manifest_artifacts"][name]),
            "data_root": root_assembly["data_roots"]["manifests"][name]["data_root"],
            "package_sha256": root_assembly["data_roots"]["manifests"][name]["package_sha256"],
        }
        for name in ("source_manifest", "reproduction_manifest")
    }
    component_outputs: dict[str, dict[str, Any]] = {}
    components: dict[str, dict[str, Any]] = {}
    for component in assembly.COMPONENTS:
        payload = _payload(root_fixture["component_outputs"][component])
        output = {
            "artifact": dict(binding["component_output_artifacts"][component]),
            "schema": payload["schema"],
            "component": payload["component"],
            "passed": payload["passed"],
            "physical_host_id": payload["physical_host_id"],
            "data_root": payload["data_root"],
            "diagnostic_only": payload["diagnostic_only"],
            "formal": payload["formal"],
            "full_product_reproduction": payload["full_product_reproduction"],
        }
        if component == "reader":
            output["future_state_inputs"] = payload["future_state_inputs"]
        elif component == "prediction":
            output.update({
                "autonomous": payload["autonomous"],
                "full_horizon": payload["full_horizon"],
                "future_state_inputs": payload["future_state_inputs"],
                "predictor_future_state_inputs": payload["predictor_future_state_inputs"],
            })
        else:
            output.update({
                "metrics": payload["metrics"],
                "cases": payload["cases"],
                "predictor_future_state_inputs": payload["predictor_future_state_inputs"],
            })
        component_outputs[component] = output
        root_component = root_assembly["components"][component]
        components[component] = {
            "component": component,
            "physical_host_id": root_component["physical_host_id"],
            "data_root": root_component["data_root"],
            "passed": payload["passed"],
            "reproduced": True,
            "output_report": dict(root_component["output_report"]),
            "bindings": dict(root_component["bindings"]),
            "diagnostic_only": payload["diagnostic_only"],
            "formal": payload["formal"],
            "full_product_reproduction": payload["full_product_reproduction"],
        }
    return {
        "schema": assembly.INPUT_SCHEMA,
        "input_origin": "synthetic_fixture",
        "typed_evidence_categories": list(assembly.CATEGORIES),
        "typed_evidence_roles": list(assembly.ROLES),
        "role_artifacts": role_artifacts,
        "host_pair": {
            "source_host": {
                "passed": host_rows["source_host"]["passed"],
                "diagnostic_only": host_rows["source_host"]["diagnostic_only"],
                "formal": host_rows["source_host"]["formal"],
                "full_product_reproduction": host_rows["source_host"]["full_product_reproduction"],
                "hostname": host_rows["source_host"]["hostname"],
                "physical_host_id": host_rows["source_host"]["physical_host_id"],
            },
            "reproduction_host": {
                "passed": host_rows["reproduction_host"]["passed"],
                "diagnostic_only": host_rows["reproduction_host"]["diagnostic_only"],
                "formal": host_rows["reproduction_host"]["formal"],
                "full_product_reproduction": host_rows["reproduction_host"]["full_product_reproduction"],
                "hostname": host_rows["reproduction_host"]["hostname"],
                "physical_host_id": host_rows["reproduction_host"]["physical_host_id"],
            },
        },
        "data_roots": {
            "source_data_root": root_assembly["data_roots"]["source_data_root"],
            "reproduction_data_root": root_assembly["data_roots"]["reproduction_data_root"],
            "different_data_root": root_assembly["data_roots"]["different_data_root"],
            "package_sha256": root_assembly["data_roots"]["package_sha256"],
            "manifests": manifests,
        },
        "component_outputs": component_outputs,
        "components": components,
    }


def synthetic_projection() -> dict[str, Any]:
    """Return a deterministic, filesystem-independent consistency projection."""
    root_fixture = root_review.synthetic_fixture()
    root_result = root_review.bind_synthetic_typed_evidence_root_review(root_fixture)
    assembly_projection = _assembly_projection_from_root_fixture(root_fixture, root_result)
    assembly_result = assembly.verify_assembly_projection(assembly_projection)
    return {
        "schema": INPUT_SCHEMA,
        "input_origin": "synthetic_fixture",
        "assembly_result": assembly_result,
        "root_review_result": root_result,
    }


def build_report() -> dict[str, Any]:
    """Build the deterministic machine report from the synthetic projection."""
    result = verify_consistency_projection(synthetic_projection())
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
        "assembly": result["assembly"],
        "root_review": result["root_review"],
        "cross_binding": result["cross_binding"],
        "cross_binding_sha256": result["cross_binding_sha256"],
        "non_authorizing_boundary": result["non_authorizing_boundary"],
        "execution_constraints": result["execution_constraints"],
        "upstream_boundary": result["upstream_boundary"],
        "rejection_contract": result["rejection_contract"],
        "interpretation": result["interpretation"],
    }


def write_json_once(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write a new report without replacing an existing receipt."""
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
        "schema": report["schema"],
        "status": report["status"],
        "cross_binding_sha256": report["cross_binding_sha256"],
        "diagnostic_only": report["non_authorizing_boundary"]["diagnostic_only"],
        "capability_minted": report["non_authorizing_boundary"]["capability_minted"],
        "full_product_reproduction": report["non_authorizing_boundary"]["full_product_reproduction"],
        "credit": report["non_authorizing_boundary"]["credit"],
    }, sort_keys=True))
    return 0


__all__ = [
    "BINDING_SCHEMA", "EXECUTION_CONSTRAINTS", "INPUT_SCHEMA", "MAX_PROJECTION_BYTES",
    "NON_AUTHORIZING_BOUNDARY", "REPORT_SCHEMA", "REPORT_STATUS", "SCHEMA", "STATUS",
    "AssemblyRootReviewConsistencyError", "build_report", "canonical_json_bytes",
    "synthetic_projection", "verify_consistency_projection", "write_json_once",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
