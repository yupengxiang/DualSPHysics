#!/usr/bin/env python3
"""Assemble and verify Core independent-reproduction evidence, read-only.

This is an additive diagnostic preflight for the evidence gap between the
historical cross-host/relocated receipts and the Core completion gate.  It
checks five typed evidence categories represented by six artifact roles:

* ``source_host`` and ``reproduction_host``;
* ``data_roots`` with two hash-bound package manifests;
* relocated ``reader``, autonomous ``prediction``, and ``scoring`` outputs.

Each role uses an exact field contract.  The component reports additionally
bind the reproduction manifest and the reader -> prediction -> scoring output
hash chain.  Only bounded JSON/hash artifacts are consumed; no HDF5, model
checkpoint, solver, worker, GPU, or queue is opened or started.

The preflight is deliberately not a completion-gate adapter.  A successful
result means only that the five artifacts can be assembled and their local
typed contracts are internally consistent.  It never writes registry,
ledger, denominator, gate, or capability state, and it always reports
``capability_minted=false`` and zero qualification credit.  The final
``core_campaign.py`` verifier still requires a trusted root review and the
non-diagnostic full-product claims.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from scripts.core_campaign import _canonical_data_root
    from scripts.core_runtime import digest
except ModuleNotFoundError:  # pragma: no cover - direct copied-script fallback
    from core_campaign import _canonical_data_root
    from core_runtime import digest


SCHEMA = "core.reproduction.independent_preflight.v1"
HOST_SCHEMA = "core.reproduction.host_identity.v1"
ROOT_SCHEMA = "core.reproduction.data_roots.v1"
MANIFEST_SCHEMA = "core.reproduction.package_manifest.v1"
COMPONENT_SCHEMA = "core.reproduction.component.v1"
ROLES = (
    "source_host",
    "reproduction_host",
    "data_roots",
    "reader",
    "prediction",
    "scoring",
)
COMPONENTS = ("reader", "prediction", "scoring")
CATEGORIES = ("host_pair", "data_roots", "reader", "prediction", "scoring")
ROLE_TO_CATEGORY = {
    "source_host": "host_pair",
    "reproduction_host": "host_pair",
    "data_roots": "data_roots",
    "reader": "reader",
    "prediction": "prediction",
    "scoring": "scoring",
}
INPUT_ORIGINS = ("historical_receipt_projection", "synthetic_fixture")
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_FIELDS = frozenset({"path", "sha256", "bytes"})
HOST_FIELDS = frozenset({
    "schema", "role", "category", "passed", "hostname", "physical_host_id",
    "diagnostic_only", "formal", "full_product_reproduction", "input_origin",
})
ROOT_FIELDS = frozenset({
    "schema", "role", "category", "passed", "source_data_root",
    "reproduction_data_root", "different_data_root", "package_sha256",
    "source_manifest", "reproduction_manifest", "source_manifest_sha256",
    "reproduction_manifest_sha256", "diagnostic_only", "formal",
    "full_product_reproduction", "input_origin",
})
MANIFEST_FIELDS = frozenset({
    "schema", "passed", "data_root", "package_sha256", "package_artifact",
    "diagnostic_only", "formal", "full_product_reproduction", "input_origin",
})
COMPONENT_FIELDS = frozenset({
    "schema", "role", "category", "component", "passed",
    "reader_reproduced", "prediction_reproduced", "scoring_reproduced",
    "physical_host_id", "data_root", "output_report", "bindings",
    "diagnostic_only", "formal", "full_product_reproduction", "input_origin",
})
OUTPUT_COMMON_FIELDS = frozenset({
    "schema", "component", "passed", "physical_host_id", "data_root",
    "diagnostic_only", "formal", "full_product_reproduction", "input_origin",
    "source_artifact",
})
OUTPUT_FIELDS = {
    "reader": OUTPUT_COMMON_FIELDS | frozenset({"future_state_inputs"}),
    "prediction": OUTPUT_COMMON_FIELDS | frozenset({
        "autonomous", "full_horizon", "future_state_inputs",
        "predictor_future_state_inputs",
    }),
    "scoring": OUTPUT_COMMON_FIELDS | frozenset({
        "metrics", "cases", "predictor_future_state_inputs",
    }),
}
OUTPUT_SCHEMAS = {
    "reader": "core.reader_reproduction.v1",
    "prediction": "core.model_reproduction.v1",
    "scoring": "core.model_reproduction.score.v1",
}


class PreflightError(ValueError):
    """A structural evidence failure with a stable diagnostic code."""

    def __init__(self, code: str, message: str, *, role: str | None = None):
        super().__init__(message)
        self.code = code
        self.role = role


def _require(condition: bool, code: str, message: str, *, role: str | None = None) -> None:
    if not condition:
        raise PreflightError(code, message, role=role)


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _require_exact_fields(payload: Any, fields: frozenset[str], *, role: str) -> None:
    _require(isinstance(payload, Mapping), "JSON_OBJECT_REQUIRED",
             f"{role} must contain a JSON object", role=role)
    _require(set(payload) == set(fields), "TYPED_FIELDS_NOT_EXACT",
             f"{role} fields are not the exact typed contract", role=role)


def _validate_diagnostic_markers(payload: Mapping[str, Any], *, role: str) -> None:
    _require(payload.get("passed") is True, "EVIDENCE_NOT_PASSED",
             f"{role} evidence is not passed", role=role)
    _require(payload.get("diagnostic_only") is True, "DIAGNOSTIC_MARKER_MISSING",
             f"{role} is not explicitly diagnostic-only", role=role)
    _require(payload.get("formal") is False,
             "FORMAL_MARKER_CONFLICT", f"{role} claims formal evidence", role=role)
    _require(payload.get("full_product_reproduction") is False,
             "PRODUCT_MARKER_CONFLICT",
             f"{role} claims full-product reproduction", role=role)
    _require(payload.get("input_origin") in INPUT_ORIGINS,
             "INPUT_ORIGIN_INVALID", f"{role} has an unsupported input origin", role=role)


def _portable_file(path: Any, root: Path, *, role: str) -> tuple[Path, dict[str, Any]]:
    _require(isinstance(path, (str, Path)), "ARTIFACT_PATH_INVALID",
             f"{role} artifact path is missing", role=role)
    candidate = Path(path).expanduser().resolve()
    root = root.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise PreflightError(
            "NON_PORTABLE_PATH",
            f"{role} artifact is outside the supplied data root",
            role=role,
        ) from error
    _require(candidate.is_file(), "ARTIFACT_MISSING",
             f"{role} artifact is not a file: {candidate}", role=role)
    byte_count = candidate.stat().st_size
    _require(0 < byte_count <= MAX_ARTIFACT_BYTES, "ARTIFACT_SIZE_OUT_OF_BOUNDS",
             f"{role} artifact exceeds the bounded JSON/hash input limit", role=role)
    return candidate, {
        "path": relative.as_posix(),
        "sha256": digest(candidate),
        "bytes": byte_count,
    }


def _load_object(path: Path, *, role: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON object key: {key}")
                result[key] = value
            return result

        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise PreflightError("INVALID_JSON", f"{role} is not valid finite JSON", role=role) from error
    _require(isinstance(payload, dict), "JSON_OBJECT_REQUIRED",
             f"{role} must contain a JSON object", role=role)
    return payload


def _load_direct(path: Any, root: Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved, reference = _portable_file(path, root, role=role)
    return _load_object(resolved, role=role), reference


def _load_reference(reference: Any, root: Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(isinstance(reference, Mapping), "EVIDENCE_REFERENCE_MISSING",
             f"{role} reference is missing", role=role)
    _require_exact_fields(reference, ARTIFACT_FIELDS, role=f"{role} reference")
    relative = reference.get("path")
    _require(
        isinstance(relative, str)
        and relative
        and "\\" not in relative
        and not relative.startswith("/")
        and not re.fullmatch(r"[A-Za-z]:[\\/].*", relative)
        and not Path(relative).is_absolute()
        and ".." not in Path(relative).parts,
             "NON_PORTABLE_PATH", f"{role} reference path is not portable", role=role)
    resolved, observed = _portable_file(root / relative, root, role=role)
    declared_sha = reference.get("sha256")
    _require(_valid_sha256(declared_sha), "HASH_INVALID",
             f"{role} reference does not contain a SHA-256 hash", role=role)
    _require(declared_sha.lower() == observed["sha256"], "HASH_MISMATCH",
             f"{role} reference hash does not match the artifact", role=role)
    _require(type(reference["bytes"]) is int and reference["bytes"] > 0,
             "BYTES_INVALID", f"{role} reference byte count is invalid", role=role)
    _require(reference["bytes"] == observed["bytes"], "BYTES_MISMATCH",
             f"{role} reference byte count does not match the artifact", role=role)
    return _load_object(resolved, role=role), observed


def _nonempty_string(value: Any, *, code: str, label: str, role: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), code,
             f"{label} must be a non-empty string", role=role)
    return value.strip()


def _validate_host(payload: Mapping[str, Any], *, role: str) -> dict[str, str]:
    _require_exact_fields(payload, HOST_FIELDS, role=role)
    _require(payload.get("schema") == HOST_SCHEMA, "HOST_SCHEMA_MISMATCH",
             f"{role} has an unsupported host-identity schema", role=role)
    _require(payload.get("role") == role, "ROLE_IDENTITY_MISMATCH",
             f"{role} role identity is inconsistent", role=role)
    _require(payload.get("category") == ROLE_TO_CATEGORY[role], "CATEGORY_IDENTITY_MISMATCH",
             f"{role} category identity is inconsistent", role=role)
    _validate_diagnostic_markers(payload, role=role)
    hostname = _nonempty_string(payload.get("hostname"), code="HOSTNAME_MISSING",
                                label="hostname", role=role)
    physical_host_id = _nonempty_string(
        payload.get("physical_host_id"), code="PHYSICAL_HOST_ID_MISSING",
        label="physical_host_id", role=role,
    )
    return {
        "hostname": hostname,
        "physical_host_id": physical_host_id,
        "input_origin": payload["input_origin"],
    }


def _validate_package_manifest(reference: Any, expected_root: str, root: Path,
                               *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, observed = _load_reference(reference, root, role=role)
    _require_exact_fields(manifest, MANIFEST_FIELDS, role=role)
    _require(manifest.get("schema") == MANIFEST_SCHEMA, "MANIFEST_SCHEMA_MISMATCH",
             f"{role} package manifest has an unsupported schema", role=role)
    _validate_diagnostic_markers(manifest, role=role)
    _require(_canonical_data_root(manifest.get("data_root")) == expected_root,
             "MANIFEST_ROOT_MISMATCH", f"{role} package manifest binds the wrong data root",
             role=role)
    _require(_valid_sha256(manifest.get("package_sha256")), "PACKAGE_HASH_INVALID",
             f"{role} package manifest has no valid package hash", role=role)
    _, package_artifact = _load_reference(
        manifest.get("package_artifact"), root, role=f"{role}.package_artifact"
    )
    _require(package_artifact["sha256"] == manifest["package_sha256"],
             "PACKAGE_ARTIFACT_HASH_MISMATCH",
             f"{role} package artifact is not the declared package identity", role=role)
    return {**manifest, "package_artifact_observed": package_artifact}, observed


def _validate_data_roots(payload: Mapping[str, Any], root: Path) -> dict[str, Any]:
    role = "data_roots"
    _require_exact_fields(payload, ROOT_FIELDS, role=role)
    _require(payload.get("schema") == ROOT_SCHEMA, "DATA_ROOT_SCHEMA_MISMATCH",
             "data_roots has an unsupported schema", role=role)
    _require(payload.get("role") == role, "ROLE_IDENTITY_MISMATCH",
             "data_roots role identity is inconsistent", role=role)
    _require(payload.get("category") == ROLE_TO_CATEGORY[role], "CATEGORY_IDENTITY_MISMATCH",
             "data_roots category identity is inconsistent", role=role)
    _validate_diagnostic_markers(payload, role=role)
    source = _canonical_data_root(payload.get("source_data_root"))
    reproduction = _canonical_data_root(payload.get("reproduction_data_root"))
    _require(source is not None and reproduction is not None, "DATA_ROOT_INVALID",
             "both data roots must be absolute POSIX roots", role=role)
    _require(source != reproduction, "DATA_ROOTS_NOT_DISTINCT",
             "source and reproduction data roots are canonically identical", role=role)
    _require(payload.get("different_data_root") is True, "DATA_ROOT_DISTINCT_MARKER_MISSING",
             "data_roots does not assert distinct roots", role=role)

    manifest_rows: dict[str, Any] = {}
    for label, expected in (("source_manifest", source), ("reproduction_manifest", reproduction)):
        manifest, observed = _validate_package_manifest(
            payload.get(label), expected, root, role=f"{role}.{label}"
        )
        declared_artifact_hash = payload.get(f"{label}_sha256")
        _require(_valid_sha256(declared_artifact_hash), "MANIFEST_REFERENCE_HASH_INVALID",
                 f"{role}.{label}_sha256 is not a valid hash", role=role)
        _require(declared_artifact_hash == observed["sha256"],
                 "MANIFEST_REFERENCE_HASH_MISMATCH",
                 f"{role}.{label}_sha256 does not match its reference", role=role)
        manifest_rows[label] = {
            "artifact": observed,
            "data_root": expected,
            "package_sha256": manifest["package_sha256"],
            "package_artifact": manifest["package_artifact_observed"],
        }
    _require(
        manifest_rows["source_manifest"]["package_sha256"]
        == manifest_rows["reproduction_manifest"]["package_sha256"],
        "PACKAGE_IDENTITY_MISMATCH",
        "source and reproduction manifests bind different package hashes",
        role=role,
    )
    _require(
        payload["package_sha256"] == manifest_rows["source_manifest"]["package_sha256"],
        "PACKAGE_IDENTITY_MISMATCH",
        "data_roots.package_sha256 does not match the package manifests",
        role=role,
    )
    return {
        "source_data_root": source,
        "reproduction_data_root": reproduction,
        "different_data_root": True,
        "package_sha256": manifest_rows["source_manifest"]["package_sha256"],
        "manifests": manifest_rows,
    }


def _validate_output_report(payload: Mapping[str, Any], *, component: str,
                            reproduction_host_id: str, reproduction_root: str,
                            root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    role = component
    _require_exact_fields(payload, OUTPUT_FIELDS[component], role=f"{role}.output_report")
    _require(payload.get("schema") == OUTPUT_SCHEMAS[component], "OUTPUT_SCHEMA_MISMATCH",
             f"{role} output report has an unsupported schema", role=role)
    _require(payload.get("component") == component, "COMPONENT_ROLE_MISMATCH",
             f"{role} output component identity is inconsistent", role=role)
    _validate_diagnostic_markers(payload, role=f"{role}.output_report")
    _require(payload.get("physical_host_id") == reproduction_host_id,
             "OUTPUT_HOST_MISMATCH", f"{role} output is not bound to the reproduction host",
             role=role)
    _require(_canonical_data_root(payload.get("data_root")) == reproduction_root,
             "OUTPUT_ROOT_MISMATCH", f"{role} output is not bound to the reproduction data root",
             role=role)
    _, source_artifact = _load_reference(
        payload.get("source_artifact"), root, role=f"{role}.source_artifact"
    )
    if component == "reader":
        _require(payload.get("future_state_inputs") is False,
                 "READER_FUTURE_STATE_INPUT",
                 "reader output permits future-state inputs", role=role)
    if component == "prediction":
        _require(payload.get("autonomous") is True, "PREDICTION_NOT_AUTONOMOUS",
                 "prediction output does not assert autonomous prediction", role=role)
        _require(payload.get("full_horizon") is True, "PREDICTION_HORIZON_INCOMPLETE",
                 "prediction output does not close the full horizon", role=role)
        _require(payload.get("future_state_inputs") is False
                 and payload.get("predictor_future_state_inputs") is False,
                 "PREDICTION_FUTURE_STATE_INPUT",
                 "prediction output permits future-state inputs",
                 role=role)
    if component == "scoring":
        _require(payload.get("predictor_future_state_inputs") is False,
                 "SCORING_FUTURE_STATE_INPUT",
                 "scoring output permits future-state inputs", role=role)
        metrics = payload.get("metrics")
        _require(
            isinstance(metrics, Mapping)
            and type(metrics.get("registered_cases")) is int
            and metrics["registered_cases"] > 0
            and metrics.get("complete_fraction") == 1.0
            and metrics.get("missing_execution") == 0,
            "SCORING_CONTRACT_INCOMPLETE",
            "scoring output does not close its registered denominator",
            role=role,
        )
        cases = payload.get("cases")
        _require(
            isinstance(cases, list) and bool(cases)
            and all(isinstance(case, str) and bool(case.strip()) for case in cases),
            "SCORING_CASES_INVALID",
            "scoring output has no typed case list",
            role=role,
        )
    return dict(payload), source_artifact


def _validate_component(payload: Mapping[str, Any], *, component: str,
                        reproduction_host_id: str, reproduction_root: str,
                        reproduction_manifest_sha256: str,
                        reader_output_sha256: str | None,
                        prediction_output_sha256: str | None,
                        root: Path) -> dict[str, Any]:
    role = component
    claim = f"{component}_reproduced"
    _require_exact_fields(payload, COMPONENT_FIELDS, role=role)
    _require(payload.get("schema") == COMPONENT_SCHEMA, "COMPONENT_SCHEMA_MISMATCH",
             f"{role} has an unsupported component schema", role=role)
    _require(payload.get("role") == role, "ROLE_IDENTITY_MISMATCH",
             f"{role} role identity is inconsistent", role=role)
    _require(payload.get("category") == ROLE_TO_CATEGORY[role], "CATEGORY_IDENTITY_MISMATCH",
             f"{role} category identity is inconsistent", role=role)
    _require(payload.get("component") == component, "COMPONENT_ROLE_MISMATCH",
             f"{role} component identity is inconsistent", role=role)
    _require(payload.get(claim) is True, "COMPONENT_EVIDENCE_NOT_PASSED",
             f"{role} component evidence is not passed", role=role)
    _require(
        all(payload.get(f"{other}_reproduced") is (other == component)
            for other in COMPONENTS),
        "COMPONENT_CLAIM_SET_INVALID",
        f"{role} component claim set is not exact",
        role=role,
    )
    _validate_diagnostic_markers(payload, role=role)
    _require(payload.get("physical_host_id") == reproduction_host_id,
             "COMPONENT_HOST_MISMATCH", f"{role} is not bound to the reproduction host",
             role=role)
    _require(_canonical_data_root(payload.get("data_root")) == reproduction_root,
             "COMPONENT_ROOT_MISMATCH", f"{role} is not bound to the reproduction data root",
             role=role)

    output_report, output_source_artifact = _load_reference(
        payload.get("output_report"), root, role=f"{role}.output_report"
    )
    output_payload, source_artifact = _validate_output_report(
        output_report,
        component=component,
        reproduction_host_id=reproduction_host_id,
        reproduction_root=reproduction_root,
        root=root,
    )
    _require(output_source_artifact["sha256"] == payload["output_report"]["sha256"],
             "OUTPUT_REFERENCE_HASH_MISMATCH",
             f"{role} output reference was not observed consistently", role=role)
    expected_bindings: dict[str, str]
    if component == "reader":
        expected_bindings = {
            "reproduction_manifest_sha256": reproduction_manifest_sha256,
            "source_artifact_sha256": source_artifact["sha256"],
        }
    elif component == "prediction":
        _require(reader_output_sha256 is not None, "COMPONENT_CHAIN_INCOMPLETE",
                 "prediction has no reader output to bind", role=role)
        expected_bindings = {
            "reader_output_sha256": reader_output_sha256,
            "source_artifact_sha256": source_artifact["sha256"],
        }
    else:
        _require(reader_output_sha256 is not None and prediction_output_sha256 is not None,
                 "COMPONENT_CHAIN_INCOMPLETE",
                 "scoring has no reader/prediction outputs to bind", role=role)
        expected_bindings = {
            "reader_output_sha256": reader_output_sha256,
            "prediction_output_sha256": prediction_output_sha256,
            "source_artifact_sha256": source_artifact["sha256"],
        }
    _require(payload.get("bindings") == expected_bindings,
             "COMPONENT_CHAIN_HASH_MISMATCH",
             f"{role} bindings do not close the typed evidence chain", role=role)
    return {
        "component": component,
        "physical_host_id": reproduction_host_id,
        "data_root": reproduction_root,
        "output_report": output_source_artifact,
        "output_schema": output_payload["schema"],
        "output_sha256": output_source_artifact["sha256"],
        "source_artifact": source_artifact,
        "source_artifact_sha256": source_artifact["sha256"],
        "bindings": expected_bindings,
    }


def _base_report(data_root: Any) -> dict[str, Any]:
    try:
        normalized_root = str(Path(data_root).expanduser().resolve())
    except (OSError, TypeError, ValueError):
        normalized_root = str(data_root)
    return {
        "schema": SCHEMA,
        "status": "blocked",
        "passed": False,
        "structural_preflight_passed": False,
        "diagnostic_only": True,
        "independent_reproduction": False,
        "capability_minted": False,
        "full_product_reproduction": False,
        "cross_host_claim": False,
        "formal_admission": False,
        "formal_training_admission": False,
        "formal_training_count": 0,
        "credit": 0,
        "qualification_credit": 0,
        "data_root": normalized_root,
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "supporting_evidence": {},
        "assembly": None,
        "errors": [],
        "execution_constraints": {
            "read_only": True,
            "bounded_json_hash_inputs": True,
            "workload_started": False,
            "gpu_started": False,
            "solver_started": False,
            "worker_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
        "interpretation": (
            "Structural typed-evidence preflight only; a pass is not an independent "
            "reproduction capability, formal admission, qualification, or credit."
        ),
    }


def build_preflight(*, data_root: str | Path,
                    evidence_paths: Mapping[str, str | Path]) -> dict[str, Any]:
    """Build a diagnostic report from five existing typed evidence artifacts.

    The function performs no external execution and never mutates campaign
    state.  Invalid or incomplete input is returned as a blocked report so a
    caller can safely persist the diagnostic result without catching a gate
    exception or treating a partial structure as capability evidence.
    """
    report = _base_report(data_root)
    try:
        root = Path(data_root).expanduser().resolve()
        _require(root.is_dir(), "DATA_ROOT_MISSING", f"data root is not a directory: {root}")
        _require(set(evidence_paths) == set(ROLES), "EVIDENCE_ROLE_SET_MISMATCH",
                 f"exactly these typed roles are required: {', '.join(ROLES)}")

        payloads: dict[str, dict[str, Any]] = {}
        references: dict[str, dict[str, Any]] = {}
        for role in ROLES:
            payloads[role], references[role] = _load_direct(
                evidence_paths[role], root, role=role
            )

        source_host = _validate_host(payloads["source_host"], role="source_host")
        reproduction_host = _validate_host(
            payloads["reproduction_host"], role="reproduction_host"
        )
        _require(
            source_host["hostname"].rstrip(".").casefold()
            != reproduction_host["hostname"].rstrip(".").casefold(),
            "HOSTNAMES_NOT_DISTINCT",
            "source and reproduction hostnames are canonically identical",
        )
        _require(source_host["physical_host_id"] != reproduction_host["physical_host_id"],
                 "PHYSICAL_HOSTS_NOT_DISTINCT",
                 "source and reproduction evidence bind the same physical host identity")

        roots = _validate_data_roots(payloads["data_roots"], root)
        components: dict[str, dict[str, Any]] = {}
        for component in COMPONENTS:
            components[component] = _validate_component(
                payloads[component], component=component,
                reproduction_host_id=reproduction_host["physical_host_id"],
                reproduction_root=roots["reproduction_data_root"],
                reproduction_manifest_sha256=roots["manifests"]["reproduction_manifest"]["artifact"]["sha256"],
                reader_output_sha256=components.get("reader", {}).get("output_sha256"),
                prediction_output_sha256=components.get("prediction", {}).get("output_sha256"),
                root=root,
            )

        report.update({
            "status": "pass",
            "passed": True,
            "structural_preflight_passed": True,
            "supporting_evidence": references,
            "assembly": {
                "source_host": source_host,
                "reproduction_host": reproduction_host,
                "data_roots": roots,
                "components": components,
                "distinct_physical_hosts": True,
                "distinct_data_roots": True,
                "reader_typed": True,
                "autonomous_prediction_typed": True,
                "scoring_typed": True,
                "typed_chain": {
                    "reader_output_sha256": components["reader"]["output_sha256"],
                    "prediction_input_reader_output_sha256": components["prediction"]["bindings"]["reader_output_sha256"],
                    "prediction_output_sha256": components["prediction"]["output_sha256"],
                    "scoring_input_reader_output_sha256": components["scoring"]["bindings"]["reader_output_sha256"],
                    "scoring_input_prediction_output_sha256": components["scoring"]["bindings"]["prediction_output_sha256"],
                    "scoring_output_sha256": components["scoring"]["output_sha256"],
                    "chain_complete": True,
                },
            },
            "next_required": [
                "trusted independent root review bound to this evidence assembly",
                "core_campaign independent_reproduction gate verification",
            ],
        })
    except PreflightError as error:
        report["errors"] = [{
            "code": error.code,
            "role": error.role,
            "message": str(error),
        }]
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        report["errors"] = [{
            "code": "PREFLIGHT_INPUT_ERROR",
            "role": None,
            "message": f"{type(error).__name__}: {error}",
        }]
    return report


def write_json_once(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write only a new diagnostic artifact; never overwrite an existing one."""
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite preflight output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-host", type=Path, required=True)
    parser.add_argument("--reproduction-host", type=Path, required=True)
    parser.add_argument("--data-roots", type=Path, required=True)
    parser.add_argument("--reader", type=Path, required=True)
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--scoring", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_preflight(
        data_root=args.data_root,
        evidence_paths={
            "source_host": args.source_host,
            "reproduction_host": args.reproduction_host,
            "data_roots": args.data_roots,
            "reader": args.reader,
            "prediction": args.prediction,
            "scoring": args.scoring,
        },
    )
    write_json_once(args.output, report)
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "structural_preflight_passed": report["structural_preflight_passed"],
        "capability_minted": report["capability_minted"],
    }, sort_keys=True))
    return 0 if report["structural_preflight_passed"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
