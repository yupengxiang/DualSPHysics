#!/usr/bin/env python3
"""Assemble a bounded, diagnostic-only A8 local product/reproduction bridge.

The repository already owns the reader-bundle v2 builder/verifier, the Core
benchmark CLI, and the independent-reproduction runner.  This module is a
small product boundary around those assets: it consumes bounded JSON indexes
and historical diagnostic receipts, binds reader/rollout/score stages, and
emits a portable manifest plus a fail-closed reproduction receipt.

It deliberately does not open HDF5/NPZ/checkpoint assets, launch a reader or
model process, or write any scientific registry, ledger, denominator, gate,
completion snapshot, or PLAN file.  A future caller may use the manifest to
authorize a separate full bundle verification and runtime execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from collections.abc import Mapping

if __name__ == "__main__":
    sys.dont_write_bytecode = True

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

# Reuse the current package/manifest contracts instead of introducing a
# second reader-bundle verifier.  Importing these helpers is read-only; this
# bridge never calls verify_bundle() because the coarse package boundary is
# intentionally bounded and must not hash the large production assets.
from scripts.core_package import BUNDLE_SCHEMA, inspect_reader_manifests
from scripts.core_runtime import atomic_json, digest
from scripts.core_strict_json import read_bounded_json_object


MAX_BRIDGE_JSON_BYTES = 1_048_576
OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"

MANIFEST_SCHEMA = "core.product.local_package_manifest.v1"
REPORT_SCHEMA = "core.product.repro_bridge_report.v1"
RECEIPT_SCHEMA = "core.product.repro_receipt.v1"
DIAGNOSTIC_ROLLOUT_SCHEMA = "core.product.diagnostic_rollout.v1"
DIAGNOSTIC_SCORE_SCHEMA = "core.product.diagnostic_score.v1"

READER_REPORT_SCHEMAS = {
    "core.verification.v1",
    "local.f4.core_reader_smoke.stdout.v1",
}
ZERO_MUTATIONS = {
    "registry": 0,
    "ledger": 0,
    "denominator": 0,
    "gate": 0,
    "completion": 0,
    "plan": 0,
}
FALSE_CLAIMS = {
    "formal_training": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "full_product_reproduction": False,
    "credit": 0,
}

# ``core.verification.v1`` is an established reader-only receipt schema and
# its historical receipts predate the explicit diagnostic markers.  Preserve
# those legal receipts, but never allow an authority-shaped field that is
# present in a receipt to contradict the bridge's non-authorizing boundary.
# The projection below always emits these safe values regardless of whether
# the legacy input carried the corresponding fields.
READER_AUTHORITY_FIELDS = {
    "diagnostic_only": True,
    "formal_training": False,
    "full_product_reproduction": False,
    "qualification_credit": 0,
    "formal": False,
    "formal_admission": False,
    "formal_eligible": False,
    "qualification": False,
    "credit": 0,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "independent_reproduction": False,
    "cross_host_reproduction": False,
}


class BridgeContractError(ValueError):
    """Raised when a bounded bridge input cannot be safely bound."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_hex(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BridgeContractError(f"{label} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise BridgeContractError(f"{label} must be a SHA-256 hex digest") from error
    return value.lower()


def _relative_path(path: Path, root: Path, *, label: str) -> str:
    path = Path(path).resolve()
    root = Path(root).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise BridgeContractError(f"{label} must be inside lab_root") from error
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() in ("", "."):
        raise BridgeContractError(f"{label} is not a portable relative path")
    return relative.as_posix()


def _portable_json_ref(path: str | Path, lab_root: Path, *, label: str) -> tuple[dict, dict]:
    """Read one strict bounded JSON object and return public ref plus payload."""
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise BridgeContractError(f"{label} symlink is forbidden")
    safe = candidate.resolve()
    relative = _relative_path(safe, lab_root, label=label)
    try:
        payload, safe_path, raw_sha256 = read_bounded_json_object(
            safe, max_bytes=MAX_BRIDGE_JSON_BYTES, label=label
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise BridgeContractError(f"{label} cannot be read within bounded JSON boundary: {error}") from error
    if safe_path != safe:
        raise BridgeContractError(f"{label} path changed during bounded read")
    public = {
        "path": relative,
        "bytes": int(safe.stat().st_size),
        "sha256": raw_sha256,
        "schema": payload.get("schema"),
        "read_policy": "strict_bounded_json_only",
        "opened": True,
    }
    return public, payload


def _portable_file_ref(path: Path, lab_root: Path, *, label: str) -> dict:
    """Hash a small code file without accepting symlinks or path escapes."""
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise BridgeContractError(f"{label} symlink is forbidden")
    safe = candidate.resolve()
    relative = _relative_path(safe, lab_root, label=label)
    if safe.is_symlink() or not safe.is_file():
        raise BridgeContractError(f"{label} must be a regular non-symlink file")
    size = safe.stat().st_size
    if size > MAX_BRIDGE_JSON_BYTES:
        raise BridgeContractError(f"{label} exceeds the bounded code-file limit")
    return {
        "path": relative,
        "bytes": int(size),
        "sha256": digest(safe),
        "read_policy": "bounded_code_closure",
    }


def _require_ref_shape(value: object, *, label: str) -> None:
    if not isinstance(value, Mapping):
        raise BridgeContractError(f"{label} must be an object")
    _relative_path(Path(str(value.get("path", ""))), Path("/"), label=label)
    _sha256_hex(value.get("sha256"), label=f"{label}.sha256")
    bytes_value = value.get("bytes")
    if isinstance(bytes_value, bool) or not isinstance(bytes_value, int) or bytes_value < 0:
        raise BridgeContractError(f"{label}.bytes must be a non-negative integer")


def _bundle_index_projection(
    bundle_ref: Mapping[str, object], bundle_payload: Mapping[str, object],
    dataset_ref: Mapping[str, object], dataset_payload: Mapping[str, object],
) -> tuple[dict, list[str]]:
    blockers: list[str] = []
    schema = bundle_payload.get("schema")
    files = bundle_payload.get("files")
    if not isinstance(files, list):
        raise BridgeContractError("bundle.json files must be a list")
    seen: set[str] = set()
    malformed = 0
    for item in files:
        if not isinstance(item, Mapping):
            malformed += 1
            continue
        value = item.get("path")
        if not isinstance(value, str) or not value or value.startswith("/"):
            malformed += 1
            continue
        path = Path(value)
        if ".." in path.parts or path.as_posix() != value or value in seen:
            malformed += 1
            continue
        seen.add(value)
        try:
            _sha256_hex(item.get("sha256"), label=f"bundle artifact {value}.sha256")
        except BridgeContractError:
            malformed += 1
        bytes_value = item.get("bytes")
        if isinstance(bytes_value, bool) or not isinstance(bytes_value, int) or bytes_value < 0:
            malformed += 1
    if malformed:
        blockers.append(f"bundle_index_malformed_artifacts:{malformed}")
    if "dataset.json" not in seen:
        blockers.append("bundle_index_missing_dataset_json")
    if schema != BUNDLE_SCHEMA:
        blockers.append(f"legacy_or_unsupported_bundle_schema:{schema!r}:expected={BUNDLE_SCHEMA!r}")
    if dataset_payload.get("schema") != "core.dataset.v2":
        blockers.append(
            f"bundle_dataset_schema_not_compact:{dataset_payload.get('schema')!r}"
        )
    cases = dataset_payload.get("cases")
    if not isinstance(cases, list):
        blockers.append("bundle_dataset_cases_missing")
        case_count = None
    else:
        case_count = len(cases)
        declared = bundle_payload.get("case_count")
        if isinstance(declared, int) and declared != case_count:
            blockers.append(f"bundle_case_count_drift:{declared}!={case_count}")
    checkpoint_count = bundle_payload.get("checkpoint_count", 0)
    if isinstance(checkpoint_count, bool) or not isinstance(checkpoint_count, int) or checkpoint_count < 0:
        blockers.append("bundle_checkpoint_count_malformed")
    projection = {
        "schema": schema,
        "current_v2_schema": BUNDLE_SCHEMA,
        "v2_index_contract": schema == BUNDLE_SCHEMA and not malformed,
        "bundle_index": dict(bundle_ref),
        "dataset_manifest": dict(dataset_ref),
        "registered_artifact_count": len(seen),
        "case_count": case_count,
        "checkpoint_count": checkpoint_count,
        "full_artifact_integrity_verified": False,
        "large_asset_hashes_read": False,
        "verification_entrypoint": "scripts.core_package.verify_bundle",
        "verification_deferred_reason": (
            "coarse bridge reads bundle/dataset JSON only; production HDF5/NPZ/checkpoint "
            "artifacts are not opened or rehashed"
        ),
    }
    return projection, blockers


def _reader_report_projection(payload: Mapping[str, object], *, label: str) -> tuple[dict, list[str]]:
    blockers: list[str] = []
    schema = payload.get("schema")
    if schema not in READER_REPORT_SCHEMAS:
        blockers.append(f"{label}_schema_unsupported:{schema!r}")

    def check_authority_fields(value: Mapping[str, object], *, value_label: str) -> None:
        for field, expected in READER_AUTHORITY_FIELDS.items():
            actual = value.get(field)
            if field not in value:
                continue
            if isinstance(expected, bool):
                matches = type(actual) is bool and actual is expected
            elif type(expected) is int:
                matches = type(actual) is int and actual == expected
            else:  # pragma: no cover - the contract currently uses bool/int only.
                matches = actual == expected
            if not matches:
                blockers.append(
                    f"{value_label}_{field}_must_be_{expected!r}"
                )

    # Do not infer authorization from a reader's claim fields.  Legacy reader
    # receipts remain compatible when the markers are absent, while any
    # supplied marker must explicitly agree with the diagnostic-only contract.
    check_authority_fields(payload, value_label=label)
    passed = False
    if schema == "core.verification.v1":
        passed = payload.get("passed") is True
    elif schema == "local.f4.core_reader_smoke.stdout.v1":
        operation = payload.get("operation")
        result = payload.get("reader_result")
        source_hash = operation.get("source_hash_verification") if isinstance(operation, Mapping) else None
        if isinstance(result, Mapping):
            check_authority_fields(result, value_label=f"{label}_reader_result")
        passed = bool(
            isinstance(operation, Mapping)
            and isinstance(source_hash, Mapping)
            and source_hash.get("passed") == source_hash.get("total")
            and isinstance(source_hash.get("passed"), int)
            and isinstance(result, Mapping)
            and result.get("dataset_opened") is True
            and result.get("diagnostic_only") is True
            and result.get("qualification_credit") == 0
        )
        if not passed:
            blockers.append(f"{label}_smoke_contract_not_passed")
    if schema == "core.verification.v1" and not passed:
        blockers.append(f"{label}_verification_not_passed")
    projection = {
        "schema": schema,
        "passed": bool(passed and not blockers),
        "case_count": payload.get("case_count"),
        "diagnostic_only": True,
        "formal_training": False,
        "full_product_reproduction": False,
        "qualification_credit": 0,
        "source_payload_not_embedded": True,
    }
    return projection, blockers


def _f8_projection(ref: Mapping[str, object], payload: Mapping[str, object], *, label: str) -> tuple[dict, list[str]]:
    blockers: list[str] = []
    schema = payload.get("schema")
    status = payload.get("status")
    authorization = payload.get("authorization")
    if not isinstance(schema, str) or not schema.startswith("core.cfd.f8.r008"):
        blockers.append(f"{label}_schema_not_f8_r008:{schema!r}")
    if not isinstance(status, str) or not status.startswith("diagnostic_only"):
        blockers.append(f"{label}_status_not_diagnostic:{status!r}")
    if not isinstance(authorization, Mapping):
        blockers.append(f"{label}_authorization_missing")
    else:
        if authorization.get("diagnostic_only") is not True:
            blockers.append(f"{label}_diagnostic_marker_missing")
        if not (
            authorization.get("formal") is False
            or authorization.get("formal_admission") is False
        ):
            blockers.append(f"{label}_formal_marker_not_false")
        if authorization.get("qualification_credit") != 0:
            blockers.append(f"{label}_qualification_credit_not_zero")
    projection = {
        "schema": schema,
        "status": status,
        "diagnostic_only": True,
        "readiness_pass": bool(isinstance(authorization, Mapping) and authorization.get("readiness_pass") is True),
        "qualification_credit": 0,
        "artifact": dict(ref),
        "source_payload_not_embedded": True,
    }
    return projection, blockers


def _diagnostic_pair_projection(ref: Mapping[str, object], payload: Mapping[str, object]) -> tuple[dict, dict, list[str]]:
    blockers: list[str] = []
    if payload.get("schema") != "core.a8.cross_host_diagnostic_pair_audit.v1":
        blockers.append(f"diagnostic_pair_schema_unsupported:{payload.get('schema')!r}")
    evidence = payload.get("evidence")
    if not isinstance(evidence, Mapping):
        blockers.append("diagnostic_pair_evidence_missing")
        evidence = {}
    if evidence.get("diagnostic_only") is not True:
        blockers.append("diagnostic_pair_diagnostic_marker_missing")
    if evidence.get("qualification_credit") != 0:
        blockers.append("diagnostic_pair_qualification_credit_not_zero")
    if evidence.get("formal_training") is not False:
        blockers.append("diagnostic_pair_formal_training_marker_not_false")

    observed_hosts = payload.get("observed_hosts")
    normalized_hosts: list[str] = []
    host_identity_contract_passed = isinstance(observed_hosts, list) and len(observed_hosts) == 2
    if not host_identity_contract_passed:
        blockers.append("diagnostic_pair_requires_exactly_two_host_identities")
    elif any(type(host) is not str or not host.strip() for host in observed_hosts):
        host_identity_contract_passed = False
        blockers.append("diagnostic_pair_host_identity_malformed")
    else:
        normalized_hosts = [host.strip() for host in observed_hosts]
        if len(set(normalized_hosts)) != len(normalized_hosts):
            host_identity_contract_passed = False
            blockers.append("diagnostic_pair_host_identities_not_distinct")
    if payload.get("distinct_host_evidence") is not True:
        blockers.append("diagnostic_pair_distinct_host_evidence_missing")
    score = payload.get("score")
    if not isinstance(score, Mapping):
        blockers.append("diagnostic_pair_score_missing")
        score = {}
    score_cases = score.get("cases")
    if not isinstance(score_cases, Mapping) or not score_cases:
        blockers.append("diagnostic_pair_score_cases_missing")
        score_cases = {}
    trajectory = payload.get("trajectory")
    if not isinstance(trajectory, Mapping) or not trajectory:
        blockers.append("diagnostic_pair_trajectory_missing")
        trajectory = {}
    score_passed = score.get("passed") is True
    rollout_passed = payload.get("passed") is True and not blockers
    complete_cases = 0
    expected_frames: dict[str, int] = {}
    score_delta_max = 0.0
    for case_id, row in score_cases.items():
        if not isinstance(case_id, str) or not isinstance(row, Mapping):
            blockers.append("diagnostic_pair_score_case_malformed")
            continue
        if row.get("left_complete") is True and row.get("right_complete") is True:
            complete_cases += 1
        frames = row.get("expected_frames")
        if isinstance(frames, int) and not isinstance(frames, bool) and frames > 0:
            expected_frames[case_id] = frames
        delta = row.get("absolute_score_difference")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool):
            score_delta_max = max(score_delta_max, float(delta))
    rollout = {
        "schema": DIAGNOSTIC_ROLLOUT_SCHEMA,
        "passed": bool(rollout_passed),
        "source_schema": payload.get("schema"),
        "observed_hosts": normalized_hosts,
        "distinct_host_evidence": bool(
            host_identity_contract_passed and payload.get("distinct_host_evidence") is True
        ),
        "host_identity_contract_passed": host_identity_contract_passed,
        "case_count": len(score_cases),
        "complete_case_count": complete_cases,
        "expected_frames_by_case": expected_frames,
        "trajectory_receipts_passed": sum(
            1 for row in trajectory.values() if isinstance(row, Mapping) and row.get("passed") is True
        ),
        "historical_input": dict(ref),
        "model_started_by_bridge": False,
        "gpu_started_by_bridge": False,
        "future_state_inputs_claimed": False,
        "scientific_qualification": False,
    }
    score_projection = {
        "schema": DIAGNOSTIC_SCORE_SCHEMA,
        "passed": bool(score_passed and not blockers),
        "source_schema": payload.get("comparator_result_schema"),
        "case_count": len(score_cases),
        "complete_case_count": complete_cases,
        "maximum_absolute_score_difference": score_delta_max,
        "historical_input": dict(ref),
        "score_kind": "cross_host_diagnostic_agreement",
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "scientific_qualification": False,
    }
    return rollout, score_projection, blockers


def _code_closure(lab_root: Path) -> list[dict]:
    script_root = lab_root / "lagrangian-fluid-lab/scripts"
    names = (
        "core_package.py",
        "core_benchmark.py",
        "core_campaign.py",
        "core_independent_reproduction.py",
        "core_strict_json.py",
    )
    return [
        _portable_file_ref(script_root / name, lab_root, label=f"code closure {name}")
        for name in names
    ]


def assemble(
    *,
    lab_root: str | Path,
    bundle: str | Path,
    f3_manifest: str | Path,
    f4_manifest: str | Path,
    f3_reader_report: str | Path,
    f4_reader_report: str | Path,
    f8_reports: tuple[str | Path, ...],
    diagnostic_pair: str | Path,
    bundle_local_check: str | Path | None = None,
    manifest_output: str | Path | None = None,
    receipt_output: str | Path | None = None,
    report_output: str | Path | None = None,
) -> dict:
    """Assemble and optionally write the bounded local package products."""
    root = Path(lab_root).expanduser().resolve()
    blockers: list[str] = []

    bundle_root = Path(bundle).expanduser().resolve()
    bundle_index_ref, bundle_index = _portable_json_ref(bundle_root / "bundle.json", root, label="bundle.json")
    dataset_ref, dataset = _portable_json_ref(bundle_root / "dataset.json", root, label="bundle dataset.json")
    bundle_projection, bundle_blockers = _bundle_index_projection(
        bundle_index_ref, bundle_index, dataset_ref, dataset
    )
    blockers.extend(bundle_blockers)

    f3_ref, f3_payload = _portable_json_ref(f3_manifest, root, label="F3 reader manifest")
    f4_ref, f4_payload = _portable_json_ref(f4_manifest, root, label="F4 reader manifest")
    manifest_inspection = inspect_reader_manifests(
        [Path(f3_manifest).expanduser().resolve(), Path(f4_manifest).expanduser().resolve()],
        data_root=root / "lagrangian-fluid-lab",
        expected_families=("F3", "F4"),
        expected_cases_per_family=32,
        require_formal=False,
    )
    if not manifest_inspection.get("portable"):
        blockers.append("reader_manifest_preflight_not_portable")
    if not manifest_inspection.get("composable"):
        blockers.append("reader_manifest_preflight_not_composable")
    manifest_projection = {
        "schema": manifest_inspection.get("schema"),
        "passed": bool(manifest_inspection.get("portable") and manifest_inspection.get("composable")),
        "source_manifests": {"F3": f3_ref, "F4": f4_ref},
        "family_case_counts": manifest_inspection.get("family_case_counts"),
        "schema_versions": manifest_inspection.get("schema_versions"),
        "formal_release_observed": manifest_inspection.get("formal_release"),
        "formal_eligibility_claim": False,
        "hold_reasons": list(manifest_inspection.get("hold_reasons", [])),
        "trajectory_files_opened_by_bridge": False,
        "future_state_inputs": False,
    }
    # The current preflight helper exposes a metadata-only formal_eligible
    # field when require_formal=False.  Never carry that field into product
    # claims: this bridge is diagnostic-only and does not qualify a reader.
    if manifest_inspection.get("formal_eligible") is True:
        manifest_projection["formal_eligibility_suppressed_reason"] = (
            "metadata preflight eligibility is not a trusted reader/runtime gate"
        )

    f3_reader_ref, f3_reader_payload = _portable_json_ref(
        f3_reader_report, root, label="F3 reader receipt"
    )
    f4_reader_ref, f4_reader_payload = _portable_json_ref(
        f4_reader_report, root, label="F4 reader receipt"
    )
    f3_reader_projection, f3_reader_blockers = _reader_report_projection(
        f3_reader_payload, label="F3 reader"
    )
    f4_reader_projection, f4_reader_blockers = _reader_report_projection(
        f4_reader_payload, label="F4 reader"
    )
    blockers.extend(f3_reader_blockers + f4_reader_blockers)
    reader_projection = {
        "schema": "core.product.reader_stage.v1",
        "passed": bool(
            manifest_projection["passed"]
            and f3_reader_projection["passed"]
            and f4_reader_projection["passed"]
        ),
        "manifest_preflight": manifest_projection,
        "F3": {"artifact": f3_reader_ref, **f3_reader_projection},
        "F4": {"artifact": f4_reader_ref, **f4_reader_projection},
        "reader_invoked_by_bridge": False,
        "large_reader_assets_opened_by_bridge": False,
    }

    f8_projections = []
    for index, f8_path in enumerate(f8_reports, start=1):
        ref, payload = _portable_json_ref(f8_path, root, label=f"F8 bounded receipt {index}")
        projection, f8_blockers = _f8_projection(ref, payload, label=f"F8 receipt {index}")
        blockers.extend(f8_blockers)
        f8_projections.append(projection)
    if not f8_projections:
        blockers.append("no_f8_bounded_receipt")

    pair_ref, pair_payload = _portable_json_ref(
        diagnostic_pair, root, label="A8 diagnostic pair receipt"
    )
    rollout_projection, score_projection, pair_blockers = _diagnostic_pair_projection(
        pair_ref, pair_payload
    )
    blockers.extend(pair_blockers)

    local_check_projection = None
    if bundle_local_check is not None:
        local_check_ref, local_check_payload = _portable_json_ref(
            bundle_local_check, root, label="bundle local check"
        )
        local_check_projection = {
            "artifact": local_check_ref,
            "schema": local_check_payload.get("schema"),
            "full_package_verify_claim": local_check_payload.get("full_core_package_verify"),
            "reader_preflight_passed": bool(
                isinstance(local_check_payload.get("reader_preflight"), Mapping)
                and local_check_payload["reader_preflight"].get("passed") is True
            ),
            "source_payload_not_embedded": True,
        }

    code_closure = _code_closure(root)
    claims = dict(FALSE_CLAIMS)
    mutations = dict(ZERO_MUTATIONS)
    coarse_chain_passed = bool(
        manifest_projection["passed"]
        and reader_projection["passed"]
        and rollout_projection["passed"]
        and score_projection["passed"]
    )
    package_ready = bool(coarse_chain_passed and bundle_projection["v2_index_contract"])
    if not bundle_projection["v2_index_contract"]:
        blockers.append("portable_package_requires_current_reader_bundle_v2")
    blockers = sorted(set(blockers))

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "version": "a8-coarse-local-package-v1",
        "observed_at_utc": OBSERVED_AT_UTC,
        "package_role": "coarse_end_to_end_local_diagnostic",
        "portable_paths": True,
        "source_host": platform.node(),
        "entrypoints": {
            "reader": "scripts/core_benchmark.py verify",
            "bundle_verifier": "scripts/core_package.py --verify-bundle",
            "diagnostic_rollout": "scripts/core_product_repro_bridge_v1.py assemble",
            "score": "scripts/core_product_repro_bridge_v1.py assemble",
            "repro_receipt": "scripts/core_product_repro_bridge_v1.py validate",
        },
        "reuse_contract": {
            "reader_bundle_builder": "scripts.core_package.build_bundle",
            "reader_bundle_verifier": "scripts.core_package.verify_bundle",
            "reader_manifest_preflight": "scripts.core_package.inspect_reader_manifests",
            "benchmark_cli": "scripts.core_benchmark",
            "independent_reproduction_runner": "scripts.core_independent_reproduction",
            "campaign_status_reader": "scripts.core_campaign.completion",
            "bridge_does_not_call_campaign_mutators": True,
        },
        "bundle": bundle_projection,
        "source_assets": {
            "reader_manifests": {"F3": f3_ref, "F4": f4_ref},
            "reader_receipts": {"F3": f3_reader_ref, "F4": f4_reader_ref},
            "f8_bounded_receipts": f8_projections,
            "diagnostic_rollout_score": pair_ref,
            "bundle_local_check": local_check_projection,
        },
        "stages": {
            "manifest": manifest_projection,
            "reader": reader_projection,
            "diagnostic_rollout": rollout_projection,
            "score": score_projection,
        },
        "code_closure": code_closure,
        "coarse_chain_passed": coarse_chain_passed,
        "local_package_ready": package_ready,
        "claims": claims,
        "mutations": mutations,
        "diagnostic_only": True,
        "formal_admission": False,
        "qualification_credit": 0,
        "blockers": blockers,
        "read_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_BRIDGE_JSON_BYTES,
            "manifest_files_opened": True,
            "reader_receipt_files_opened": True,
            "bundle_dataset_opened": True,
            "hdf5_opened": False,
            "npz_opened": False,
            "checkpoint_opened": False,
            "trajectory_opened": False,
            "large_asset_hashes_read": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_started": False,
        },
        "interpretation": (
            "The bridge wires existing Core/F3/F4/F8 diagnostic assets into a portable "
            "metadata-first package contract. It does not execute a new rollout, "
            "mint a trusted capability, or alter scientific completion state."
        ),
    }

    manifest_path = Path(manifest_output).expanduser().resolve() if manifest_output else None
    if manifest_path is not None:
        atomic_json(manifest_path, manifest)
        if manifest_path.stat().st_size > MAX_BRIDGE_JSON_BYTES:
            raise BridgeContractError("generated package manifest exceeds bounded report limit")

    manifest_ref = None
    manifest_sha256 = None
    if manifest_path is not None:
        manifest_ref, _ = _portable_json_ref(manifest_path, root, label="generated package manifest")
        manifest_sha256 = manifest_ref["sha256"]
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "version": "a8-coarse-local-package-v1",
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": "diagnostic_only_local_package_ready" if package_ready else "diagnostic_only_local_package_blocked",
        "diagnostic_only": True,
        "package_manifest": manifest_ref,
        "package_manifest_sha256": manifest_sha256,
        "stages": {
            "manifest": {"passed": manifest_projection["passed"]},
            "reader": {"passed": reader_projection["passed"]},
            "cli": {"passed": True, "entrypoints_bound": True},
            "diagnostic_rollout": {"passed": rollout_projection["passed"]},
            "score": {"passed": score_projection["passed"]},
        },
        "coarse_chain_passed": coarse_chain_passed,
        "local_package_ready": package_ready,
        "claims": claims,
        "mutations": mutations,
        "formal_admission": False,
        "qualification_credit": 0,
        "cross_host_diagnostic_agreement": bool(rollout_projection["distinct_host_evidence"] and score_projection["passed"]),
        "cross_host_reproduction": False,
        "full_product_reproduction": False,
        "formal_training_runs_counted": 0,
        "blockers": blockers,
        "source_binding": {
            "bundle_index_sha256": bundle_ref_sha256(bundle_projection),
            "diagnostic_pair_sha256": pair_ref["sha256"],
            "code_closure_sha256": _canonical_hash(code_closure),
        },
        "interpretation": (
            "A ready result means only that the coarse metadata chain is assembled "
            "against the current v2 index contract. It never means Core completion, "
            "T1/T2 qualification, or trusted independent reproduction."
        ),
    }
    receipt_path = Path(receipt_output).expanduser().resolve() if receipt_output else None
    if receipt_path is not None:
        atomic_json(receipt_path, receipt)
        if receipt_path.stat().st_size > MAX_BRIDGE_JSON_BYTES:
            raise BridgeContractError("generated reproduction receipt exceeds bounded report limit")

    report = {
        "schema": REPORT_SCHEMA,
        "version": "a8-coarse-local-package-v1",
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": receipt["status"],
        "package_manifest": manifest_ref,
        "reproduction_receipt": (
            _portable_json_ref(receipt_path, root, label="generated reproduction receipt")[0]
            if receipt_path is not None else None
        ),
        "stages": manifest["stages"],
        "coarse_chain_passed": coarse_chain_passed,
        "local_package_ready": package_ready,
        "claims": claims,
        "mutations": mutations,
        "diagnostic_only": True,
        "formal_admission": False,
        "qualification_credit": 0,
        "blockers": blockers,
        "receipt_binding_sha256": _canonical_hash(receipt),
        "manifest_binding_sha256": manifest_sha256,
        "report_policy": "bounded_json_projection; no production artifact payloads embedded",
    }
    report_path = Path(report_output).expanduser().resolve() if report_output else None
    if report_path is not None:
        atomic_json(report_path, report)
        if report_path.stat().st_size > MAX_BRIDGE_JSON_BYTES:
            raise BridgeContractError("generated bridge report exceeds bounded report limit")
    return {"manifest": manifest, "receipt": receipt, "report": report}


def bundle_ref_sha256(bundle_projection: Mapping[str, object]) -> str:
    bundle_index = bundle_projection.get("bundle_index")
    if not isinstance(bundle_index, Mapping):
        raise BridgeContractError("bundle projection is missing bundle index reference")
    return str(bundle_index.get("sha256"))


def _validate_claims(value: Mapping[str, object], *, label: str) -> list[str]:
    errors: list[str] = []
    if value.get("diagnostic_only") is not True:
        errors.append(f"{label}.diagnostic_only must be true")
    claims = value.get("claims")
    if not isinstance(claims, Mapping):
        errors.append(f"{label}.claims missing")
    else:
        for key, expected in FALSE_CLAIMS.items():
            if claims.get(key) != expected:
                errors.append(f"{label}.claims.{key} must be {expected!r}")
    mutations = value.get("mutations")
    if not isinstance(mutations, Mapping):
        errors.append(f"{label}.mutations missing")
    else:
        for key, expected in ZERO_MUTATIONS.items():
            if mutations.get(key) != expected:
                errors.append(f"{label}.mutations.{key} must be {expected!r}")
    if value.get("formal_admission") is not False:
        errors.append(f"{label}.formal_admission must be false")
    if value.get("qualification_credit") != 0:
        errors.append(f"{label}.qualification_credit must be zero")
    return errors


def validate_outputs(
    *, manifest_path: str | Path, receipt_path: str | Path, report_path: str | Path, lab_root: str | Path
) -> list[str]:
    """Validate the bounded cross-file binding without opening large assets."""
    root = Path(lab_root).expanduser().resolve()
    errors: list[str] = []
    try:
        manifest_ref, manifest = _portable_json_ref(manifest_path, root, label="package manifest")
        receipt_ref, receipt = _portable_json_ref(receipt_path, root, label="reproduction receipt")
        report_ref, report = _portable_json_ref(report_path, root, label="bridge report")
    except BridgeContractError as error:
        return [str(error)]
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append("package manifest schema mismatch")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        errors.append("reproduction receipt schema mismatch")
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("bridge report schema mismatch")
    errors.extend(_validate_claims(manifest, label="manifest"))
    errors.extend(_validate_claims(receipt, label="receipt"))
    errors.extend(_validate_claims(report, label="report"))
    if receipt.get("package_manifest_sha256") != manifest_ref["sha256"]:
        errors.append("receipt package manifest hash mismatch")
    if report.get("manifest_binding_sha256") != manifest_ref["sha256"]:
        errors.append("report manifest hash mismatch")
    if report.get("reproduction_receipt", {}).get("sha256") != receipt_ref["sha256"]:
        errors.append("report reproduction receipt hash mismatch")
    if report.get("status") != receipt.get("status"):
        errors.append("report/receipt status mismatch")
    if report.get("coarse_chain_passed") != receipt.get("coarse_chain_passed"):
        errors.append("report/receipt coarse-chain mismatch")
    if report.get("local_package_ready") != receipt.get("local_package_ready"):
        errors.append("report/receipt package-ready mismatch")
    for value, label in ((manifest, "manifest"), (receipt, "receipt"), (report, "report")):
        if value.get("T1_numerical") is True or value.get("T2_macro") is True or value.get("T2_path") is True:
            errors.append(f"{label} contains a forbidden positive qualification field")
    return sorted(set(errors))


def _add_assemble_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--f3-manifest", type=Path, required=True)
    parser.add_argument("--f4-manifest", type=Path, required=True)
    parser.add_argument("--f3-reader-report", type=Path, required=True)
    parser.add_argument("--f4-reader-report", type=Path, required=True)
    parser.add_argument("--f8-report", type=Path, action="append", required=True)
    parser.add_argument("--diagnostic-pair", type=Path, required=True)
    parser.add_argument("--bundle-local-check", type=Path)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    assemble_parser = sub.add_parser("assemble", help="assemble bounded local package products")
    _add_assemble_arguments(assemble_parser)
    validate_parser = sub.add_parser("validate", help="validate an existing bounded product chain")
    validate_parser.add_argument("--lab-root", type=Path, required=True)
    validate_parser.add_argument("--manifest", type=Path, required=True)
    validate_parser.add_argument("--receipt", type=Path, required=True)
    validate_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "assemble":
            result = assemble(
                lab_root=args.lab_root,
                bundle=args.bundle,
                f3_manifest=args.f3_manifest,
                f4_manifest=args.f4_manifest,
                f3_reader_report=args.f3_reader_report,
                f4_reader_report=args.f4_reader_report,
                f8_reports=tuple(args.f8_report),
                diagnostic_pair=args.diagnostic_pair,
                bundle_local_check=args.bundle_local_check,
                manifest_output=args.manifest_output,
                receipt_output=args.receipt_output,
                report_output=args.report_output,
            )
            print(json.dumps({
                "schema": result["report"]["schema"],
                "status": result["report"]["status"],
                "coarse_chain_passed": result["report"]["coarse_chain_passed"],
                "local_package_ready": result["report"]["local_package_ready"],
                "blocker_count": len(result["report"]["blockers"]),
                "report": str(Path(args.report_output).resolve()),
            }, indent=2, sort_keys=True))
            return 0
        errors = validate_outputs(
            manifest_path=args.manifest,
            receipt_path=args.receipt,
            report_path=args.report,
            lab_root=args.lab_root,
        )
        result = {"schema": "core.product.repro_bridge_validation.v1", "passed": not errors, "errors": errors}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not errors else 1
    except (BridgeContractError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
