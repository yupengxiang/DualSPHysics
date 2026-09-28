#!/usr/bin/env python3
"""Assemble and verify Core independent-reproduction evidence, read-only.

This is an additive diagnostic preflight for the evidence gap between the
historical cross-host/relocated receipts and the Core completion gate.  It
checks five typed evidence categories represented by six artifact roles:

* ``source_host`` and ``reproduction_host``;
* ``data_roots`` with two hash-bound package manifests;
* relocated ``reader``, autonomous ``prediction``, and ``scoring`` outputs.

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
    from scripts.core_campaign import _canonical_data_root, _component_output_passes
    from scripts.core_runtime import digest
except ModuleNotFoundError:  # pragma: no cover - direct copied-script fallback
    from core_campaign import _canonical_data_root, _component_output_passes
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
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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
    return candidate, {
        "path": relative.as_posix(),
        "sha256": digest(candidate),
        "bytes": candidate.stat().st_size,
    }


def _load_object(path: Path, *, role: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
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
    if "bytes" in reference:
        _require(type(reference["bytes"]) is int and reference["bytes"] >= 0,
                 "BYTES_INVALID", f"{role} reference byte count is invalid", role=role)
        _require(reference["bytes"] == observed["bytes"], "BYTES_MISMATCH",
                 f"{role} reference byte count does not match the artifact", role=role)
    return _load_object(resolved, role=role), observed


def _nonempty_string(value: Any, *, code: str, label: str, role: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), code,
             f"{label} must be a non-empty string", role=role)
    return value.strip()


def _validate_host(payload: Mapping[str, Any], *, role: str) -> dict[str, str]:
    _require(payload.get("schema") == HOST_SCHEMA, "HOST_SCHEMA_MISMATCH",
             f"{role} has an unsupported host-identity schema", role=role)
    _require(payload.get("passed") is True, "HOST_EVIDENCE_NOT_PASSED",
             f"{role} host evidence is not passed", role=role)
    hostname = _nonempty_string(payload.get("hostname"), code="HOSTNAME_MISSING",
                                label="hostname", role=role)
    physical_host_id = _nonempty_string(
        payload.get("physical_host_id"), code="PHYSICAL_HOST_ID_MISSING",
        label="physical_host_id", role=role,
    )
    return {"hostname": hostname, "physical_host_id": physical_host_id}


def _validate_package_manifest(reference: Any, expected_root: str, root: Path,
                               *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, observed = _load_reference(reference, root, role=role)
    _require(manifest.get("schema") == MANIFEST_SCHEMA, "MANIFEST_SCHEMA_MISMATCH",
             f"{role} package manifest has an unsupported schema", role=role)
    _require(_canonical_data_root(manifest.get("data_root")) == expected_root,
             "MANIFEST_ROOT_MISMATCH", f"{role} package manifest binds the wrong data root",
             role=role)
    _require(_valid_sha256(manifest.get("package_sha256")), "PACKAGE_HASH_INVALID",
             f"{role} package manifest has no valid package hash", role=role)
    return manifest, observed


def _validate_data_roots(payload: Mapping[str, Any], root: Path) -> dict[str, Any]:
    role = "data_roots"
    _require(payload.get("schema") == ROOT_SCHEMA, "DATA_ROOT_SCHEMA_MISMATCH",
             "data_roots has an unsupported schema", role=role)
    _require(payload.get("passed") is True, "DATA_ROOT_EVIDENCE_NOT_PASSED",
             "data_roots evidence is not passed", role=role)
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
        _require(declared_artifact_hash.lower() == observed["sha256"],
                 "MANIFEST_REFERENCE_HASH_MISMATCH",
                 f"{role}.{label}_sha256 does not match its reference", role=role)
        manifest_rows[label] = {
            "artifact": observed,
            "data_root": expected,
            "package_sha256": manifest["package_sha256"],
        }
    _require(
        manifest_rows["source_manifest"]["package_sha256"]
        == manifest_rows["reproduction_manifest"]["package_sha256"],
        "PACKAGE_IDENTITY_MISMATCH",
        "source and reproduction manifests bind different package hashes",
        role=role,
    )
    return {
        "source_data_root": source,
        "reproduction_data_root": reproduction,
        "different_data_root": True,
        "package_sha256": manifest_rows["source_manifest"]["package_sha256"],
        "manifests": manifest_rows,
    }


def _validate_component(payload: Mapping[str, Any], *, component: str,
                        reproduction_host_id: str, reproduction_root: str,
                        root: Path) -> dict[str, Any]:
    role = component
    claim = f"{component}_reproduced"
    _require(payload.get("schema") == COMPONENT_SCHEMA, "COMPONENT_SCHEMA_MISMATCH",
             f"{role} has an unsupported component schema", role=role)
    _require(payload.get("component") == component, "COMPONENT_ROLE_MISMATCH",
             f"{role} component identity is inconsistent", role=role)
    _require(payload.get("passed") is True and payload.get(claim) is True,
             "COMPONENT_EVIDENCE_NOT_PASSED", f"{role} component evidence is not passed",
             role=role)
    _require(payload.get("physical_host_id") == reproduction_host_id,
             "COMPONENT_HOST_MISMATCH", f"{role} is not bound to the reproduction host",
             role=role)
    _require(_canonical_data_root(payload.get("data_root")) == reproduction_root,
             "COMPONENT_ROOT_MISMATCH", f"{role} is not bound to the reproduction data root",
             role=role)
    _require(payload.get("diagnostic_only") is not True, "COMPONENT_IS_DIAGNOSTIC",
             f"{role} component explicitly remains diagnostic-only", role=role)
    if component == "prediction":
        _require(payload.get("autonomous") is True, "PREDICTION_NOT_AUTONOMOUS",
                 "prediction evidence does not assert autonomous prediction", role=role)
        _require(payload.get("full_horizon") is True, "PREDICTION_HORIZON_INCOMPLETE",
                 "prediction evidence does not close the full horizon", role=role)
        _require(payload.get("future_state_inputs") is False,
                 "PREDICTION_FUTURE_STATE_INPUT", "prediction evidence allows future-state inputs",
                 role=role)

    output_report, output_reference = _load_reference(
        payload.get("output_report"), root, role=f"{role}.output_report"
    )
    _require(_component_output_passes(component, output_report), "COMPONENT_OUTPUT_INVALID",
             f"{role} output report does not satisfy its typed output contract", role=role)
    return {
        "component": component,
        "physical_host_id": reproduction_host_id,
        "data_root": reproduction_root,
        "output_report": output_reference,
        "output_schema": output_report.get("schema"),
        "output_sha256": output_reference["sha256"],
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
        "capability_minted": False,
        "formal_admission": False,
        "formal_training_count": 0,
        "qualification_credit": 0,
        "data_root": normalized_root,
        "typed_evidence_categories": list(CATEGORIES),
        "typed_evidence_roles": list(ROLES),
        "supporting_evidence": {},
        "assembly": None,
        "errors": [],
        "execution_constraints": {
            "read_only": True,
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
        components = {
            component: _validate_component(
                payloads[component], component=component,
                reproduction_host_id=reproduction_host["physical_host_id"],
                reproduction_root=roots["reproduction_data_root"], root=root,
            )
            for component in COMPONENTS
        }

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
