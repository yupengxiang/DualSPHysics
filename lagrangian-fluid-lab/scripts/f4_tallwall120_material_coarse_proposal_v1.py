#!/usr/bin/env python3
"""Prepare a fail-closed, source-bound F4 DEV_07 material proposal.

This module is a static planner.  It reads bounded JSON metadata and code
files, but never opens a trajectory HDF5, starts a solver/worker/native
process, requests a GPU/queue slot, or mutates campaign state.  The proposal
therefore records an exact future argv contract without pretending that a
material trace or material labels already exist.

The existing ``f4_tallwall120_material.py`` tracer remains the planned
execution implementation.  This planner deliberately keeps its source
binding separate from the older qualification-cell proposal and refuses to
turn a collection-manifest path alias into an accepted source identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from scripts.core_contract import contract_hash
from scripts.core_dataset import known_inputs_from_dict


SCHEMA = "core.material.f4.tallwall120.coarse_proposal.v1"
LAB_ROOT = Path(__file__).resolve().parents[1]

TARGET: dict[str, Any] = {
    "family": "F4",
    "case_id": "F4_resting_pool_laminar_tallwall120_x_v1_DEV_07",
    "physical_case_id": "F4_resting_pool_laminar_tallwall120_x_v1_DEV_07",
    "lineage_group_id": "F4_resting_pool_laminar_tallwall120_x_v1_DEV_07",
    "source_hdf5": "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5",
    "source_sha256": "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae",
    "source_bytes": 2067911708,
    "frames": 218,
    "transitions": 217,
    "particle_count": 217485,
    "time_start_s": 0.0,
    "time_end_s": 4.340002980805959,
    "split": "train",
    "recipe_id": "F4_mdbc_laminar_nu1e6_tallwall120_v1",
    "scope_id": "F4_resting_pool_laminar_tallwall120_x_v1",
}

COLLECTION_MANIFEST = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
SOURCE_ARCHIVE = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/archive.json"
)
SOURCE_RESULT = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/result.json"
)
SOURCE_AUDIT = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/audit.json"
)

EXPECTED_COLLECTION_MANIFEST_SHA256 = (
    "808fe201c4df28f2be9b48a514f338689c38bcb96db0b0c0590946b79fb9ad09"
)
EXPECTED_SOURCE_ARCHIVE_SHA256 = (
    "49412fb74e488628ccb0fa15ce0aa808c1e723fb8821196e79b646a3121513e5"
)
EXPECTED_SOURCE_RESULT_SHA256 = (
    "2a5196951147f2d640384b471aab876568b4f795588de222bc1ad1b1a1788b5c"
)
EXPECTED_SOURCE_AUDIT_SHA256 = (
    "e55dcd6fa2b4a8415bb998a3a8160fb84165cc041983217942a73f659b1cfa28"
)
EXPECTED_KNOWN_INPUTS_SHA256 = (
    "7d3c28ae71e165ecb679545c78a9d7c2fc087593d41157a7fd0a214e97c14724"
)
# The collection JSON contains a declaration, but the trusted Core reader
# smoke/admission evidence still reports this path as non-formal.  A manifest
# flag is never allowed to promote the trusted reader gate.
TRUSTED_READER_FORMAL_ELIGIBLE = False

CODE_BINDINGS = {
    "scripts/core_material.py": "shared material provider, gates, and F4 seed primitives",
    "scripts/f4_tallwall120_material.py": "planned F4 tall-wall material tracer",
    "scripts/f4_tallwall120_material_diagnosis.py": "planned read-only support diagnosis",
    "scripts/core_contract.py": "Core KnownInputs contract implementation",
    "scripts/core_dataset.py": "Core known-input reconstruction and hash boundary",
    "scripts/core_cfd_dataset.py": "CFD-to-Core manifest adapter",
    "scripts/f3_material_neighbors.py": "visible-support backend used by baseline24",
    "scripts/passive_tracers.py": "finite-wall and swept-segment primitives",
    "scripts/f4_tallwall120_material_coarse_proposal_v1.py": "this static fail-closed proposal planner",
}

DEFAULT_OUTPUT_NAMESPACE = (
    "campaigns/core-v1/material/proposals/"
    "f4-tallwall120-production-dev-07/coarse-baseline24-s2-r001-source-6ae8ca70"
)

PARAMETER_CONTRACT: dict[str, Any] = {
    # This is the prepared DEV_07 source geometry parameter, not the old
    # center-q=0.5 qualification proposal.
    "q": 0.23437500000000008,
    "drop_left_x_m": 0.3015625,
    "dp_m": 0.0075,
    "seeds": 512,
    "substeps": 2,
    "neighbour_variant": "baseline24",
    "neighbour_backend": "f3_ckdtree_visible_shepard_distance_v1",
    "neighbours": 24,
    "regularization_m": 0.004,
    "maximum_support_distance_m": 0.03,
    "unknown_gate_fraction_max": 0.01,
    "stop_after_frame": 217,
    "native_frame_count": 218,
    "native_transition_count": 217,
    "native_window_s": 4.340002980805959,
    "extension_window_s": 8.68,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative POSIX path")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"{field} must not be absolute or contain dot segments")
    if "" in path.parts:
        raise ValueError(f"{field} contains an empty path segment")
    return "/".join(path.parts)


def _resolve(root: Path, relative: str, *, field: str) -> Path:
    relative = _safe_relative(relative, field=field)
    candidate = (Path(root).resolve() / relative).resolve()
    root = Path(root).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{field} escapes lab root") from error
    return candidate


def _read_json(path: Path, *, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > max_bytes:
        raise ValueError(f"JSON metadata is too large: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _ref(root: Path, relative: str, role: str, *, expected_sha256: str | None = None) -> dict[str, Any]:
    path = _resolve(root, relative, field=f"{role}.path")
    if not path.is_file():
        return {
            "path": relative,
            "role": role,
            "exists": False,
            "sha256": None,
            "expected_sha256": expected_sha256,
            "sha256_match": False if expected_sha256 else None,
        }
    observed = sha256_file(path)
    return {
        "path": relative,
        "role": role,
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": observed,
        "expected_sha256": expected_sha256,
        "sha256_match": observed == expected_sha256 if expected_sha256 else None,
    }


def _check(name: str, passed: bool, reason: str, **details: Any) -> dict[str, Any]:
    result = {"check": name, "passed": bool(passed), "reason": reason}
    result.update(details)
    return result


def _case_row(collection: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    reader = collection.get("reader_manifest")
    if not isinstance(reader, Mapping):
        reader = collection
    rows = reader.get("cases")
    if not isinstance(rows, list):
        raise ValueError("collection manifest has no cases list")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == case_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one collection row for {case_id}, got {len(matches)}")
    return dict(matches[0])


def _known_input_contract(
    row: Mapping[str, Any], *, expected_sha256: str = EXPECTED_KNOWN_INPUTS_SHA256
) -> dict[str, Any]:
    payload = row.get("known_inputs")
    declared = row.get("known_inputs_sha256")
    if not isinstance(payload, Mapping):
        return {
            "representation": "not_inline",
            "declared_sha256": declared,
            "computed_sha256": None,
            "contract_valid": False,
            "error": "known_inputs_ref/asset reconstruction is not admitted by this static proposal",
        }
    try:
        known = known_inputs_from_dict(dict(payload))
        computed = contract_hash(known)
        return {
            "representation": "inline_core_inputs_v1",
            "contract_version": payload.get("contract_version"),
            "declared_sha256": declared,
            "computed_sha256": computed,
            "expected_sha256": expected_sha256,
            "contract_valid": bool(
                computed == declared == expected_sha256
            ),
            "coordinate_frame": payload.get("coordinate_frame"),
            "contains_future_or_reference_state": False,
        }
    except (KeyError, TypeError, ValueError) as error:
        return {
            "representation": "inline_core_inputs_v1",
            "declared_sha256": declared,
            "computed_sha256": None,
            "expected_sha256": expected_sha256,
            "contract_valid": False,
            "contains_future_or_reference_state": None,
            "error": f"{type(error).__name__}: {error}",
        }


def _prepared_contract(root: Path, row: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    provenance = row.get("provenance")
    prepared = provenance.get("prepared") if isinstance(provenance, Mapping) else None
    if not isinstance(prepared, Mapping) or not isinstance(prepared.get("path"), str):
        return {"available": False, "parameter_match": False, "reason": "prepared ref is absent"}
    relative = _safe_relative(prepared["path"], field="prepared.path")
    path = _resolve(root, relative, field="prepared.path")
    if not path.is_file():
        return {"available": False, "parameter_match": False, "path": relative}
    payload = _read_json(path)
    config = payload.get("config")
    parameter = config.get("parameter") if isinstance(config, Mapping) else None
    if not isinstance(parameter, Mapping):
        return {"available": False, "parameter_match": False, "path": relative, "reason": "config.parameter absent"}
    q = float(parameter.get("q"))
    drop_left = float(parameter.get("value"))
    expected_q = float(PARAMETER_CONTRACT["q"])
    expected_drop = float(PARAMETER_CONTRACT["drop_left_x_m"])
    observed_sha = sha256_file(path)
    declared_sha = prepared.get("sha256")
    return {
        "available": True,
        "path": relative,
        "declared_sha256": declared_sha,
        "observed_sha256": observed_sha,
        "declared_sha256_match": declared_sha == observed_sha if declared_sha else None,
        "q": q,
        "drop_left_x_m": drop_left,
        "parameter_match": bool(abs(q - expected_q) <= 1e-15 and abs(drop_left - expected_drop) <= 1e-15),
        "case_id": config.get("case_id"),
        "recipe_id": config.get("recipe_id"),
        "scope_id": config.get("scope_id"),
        "qualification_inherited": bool(config.get("qualification_inheritance", True)),
    }


def _archive_output(archive: Mapping[str, Any], relative: str) -> dict[str, Any] | None:
    for row in archive.get("outputs", []):
        if isinstance(row, Mapping) and row.get("path") == relative:
            return dict(row)
    return None


def _code_snapshot(root: Path, code_paths: Mapping[str, str]) -> dict[str, Any]:
    bindings = []
    for relative, role in sorted(code_paths.items()):
        reference = _ref(root, relative, role)
        bindings.append(reference)
    if not all(item["exists"] for item in bindings):
        snapshot_hash = None
    else:
        snapshot_hash = hashlib.sha256(_canonical([
            {"path": item["path"], "sha256": item["sha256"]} for item in bindings
        ])).hexdigest()
    return {
        "bindings": bindings,
        "code_snapshot_sha256": snapshot_hash,
        "hash_semantics": "sha256(canonical sorted path+file-sha256 list)",
    }


def _argv_contract(target: Mapping[str, Any], namespace: str) -> dict[str, Any]:
    source = "{lab_root}/" + str(target["source_hdf5"])
    output = "{fresh_output_namespace}/product/tallwall120_material.h5"
    diagnosis = "{fresh_output_namespace}/product/tallwall120_material_diagnosis.json"
    q = format(float(PARAMETER_CONTRACT["q"]), ".17g")
    dp = str(PARAMETER_CONTRACT["dp_m"])
    return {
        "placeholder_semantics": {
            "lab_root": "absolute checkout root supplied by the authorized runner",
            "fresh_output_namespace": namespace,
        },
        "material_trace": [
            "{lab_root}/.venv/bin/python",
            "{lab_root}/scripts/f4_tallwall120_material.py",
            "--source", source,
            "--output", output,
            "--q", q,
            "--dp-m", dp,
            "--seeds", str(PARAMETER_CONTRACT["seeds"]),
            "--substeps", str(PARAMETER_CONTRACT["substeps"]),
            "--neighbour-variant", str(PARAMETER_CONTRACT["neighbour_variant"]),
            "--stop-after", str(PARAMETER_CONTRACT["stop_after_frame"]),
        ],
        "diagnosis": [
            "{lab_root}/.venv/bin/python",
            "{lab_root}/scripts/f4_tallwall120_material_diagnosis.py",
            "--source", source,
            "--trace", output,
            "--output", diagnosis,
            "--q", q,
            "--dp-m", dp,
            "--substeps", str(PARAMETER_CONTRACT["substeps"]),
        ],
        "execution_order": ["material_trace", "diagnosis"],
        "forbidden_argv_mutations": [
            "do not replace source path or source SHA",
            "do not change q, dp_m, seeds, substeps, neighbour variant, or stop-after",
            "do not add --resume to an existing namespace",
            "do not add a threshold-relaxing or imputation option",
        ],
    }


def build_proposal(
    lab_root: str | Path = LAB_ROOT,
    *,
    target: Mapping[str, Any] | None = None,
    collection_manifest: str = COLLECTION_MANIFEST,
    source_archive: str = SOURCE_ARCHIVE,
    source_result: str = SOURCE_RESULT,
    source_audit: str = SOURCE_AUDIT,
    expected_collection_sha256: str | None = EXPECTED_COLLECTION_MANIFEST_SHA256,
    expected_archive_sha256: str | None = EXPECTED_SOURCE_ARCHIVE_SHA256,
    expected_result_sha256: str | None = EXPECTED_SOURCE_RESULT_SHA256,
    expected_audit_sha256: str | None = EXPECTED_SOURCE_AUDIT_SHA256,
    expected_known_inputs_sha256: str = EXPECTED_KNOWN_INPUTS_SHA256,
    fresh_output_namespace: str = DEFAULT_OUTPUT_NAMESPACE,
    code_paths: Mapping[str, str] | None = None,
    created_at_utc: str = "2026-09-28T00:00:00Z",
) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    target = dict(TARGET if target is None else target)
    namespace = _safe_relative(fresh_output_namespace, field="fresh_output_namespace")
    code_paths = dict(CODE_BINDINGS if code_paths is None else code_paths)

    collection_path = _resolve(root, collection_manifest, field="collection_manifest")
    collection = _read_json(collection_path)
    collection_sha = sha256_file(collection_path)
    row = _case_row(collection, str(target["case_id"]))
    known_contract = _known_input_contract(row, expected_sha256=expected_known_inputs_sha256)
    prepared = _prepared_contract(root, row, target)

    archive_path = _resolve(root, source_archive, field="source_archive")
    archive = _read_json(archive_path)
    archive_ref = _ref(root, source_archive, "source archive", expected_sha256=expected_archive_sha256)
    result_ref = _ref(root, source_result, "source result", expected_sha256=expected_result_sha256)
    audit_ref = _ref(root, source_audit, "source audit", expected_sha256=expected_audit_sha256)
    result = _read_json(_resolve(root, source_result, field="source_result"))
    audit = _read_json(_resolve(root, source_audit, field="source_audit"))

    source_path = _resolve(root, str(target["source_hdf5"]), field="source_hdf5")
    archive_trajectory = _archive_output(archive, "product/trajectory.h5")
    source_metadata = {
        "path": target["source_hdf5"],
        "sha256": target["source_sha256"],
        "exists": source_path.is_file(),
        "bytes": source_path.stat().st_size if source_path.is_file() else None,
        "byte_size_match_archive": bool(
            source_path.is_file() and archive_trajectory
            and source_path.stat().st_size == archive_trajectory.get("bytes") == target.get("source_bytes")
        ),
        "content_hash_rehashed_by_planner": False,
        "content_hash_recheck_required_before_runtime": True,
    }

    collection_reader = collection.get("reader_manifest")
    if not isinstance(collection_reader, Mapping):
        collection_reader = collection
    manifest_declared_formal_eligible = bool(
        collection_reader.get("formal_eligible", collection.get("formal_eligible", False))
    )
    reader_formal_eligible = TRUSTED_READER_FORMAL_ELIGIBLE
    declared_hdf5 = row.get("hdf5")
    row_sha = row.get("sha256")
    identity_checks = {
        "case_id": row.get("case_id") == target["case_id"],
        "physical_case_id": row.get("physical_case_id") == target["physical_case_id"],
        "lineage_group_id": row.get("lineage_group_id") == target["lineage_group_id"],
        "family": row.get("family") == target["family"],
        "split": row.get("split") == target["split"],
        "source_sha256": row_sha == target["source_sha256"],
        "known_inputs_sha256": row.get("known_inputs_sha256") == expected_known_inputs_sha256,
    }

    source_archive_checks = {
        "schema": archive.get("schema") == "core.verified_archive.v1",
        "execution_status": archive.get("execution_status") == "succeeded",
        "job_id": archive.get("job_id") == "f4-tallwall120-production-dev-07",
        "trajectory_output_present": archive_trajectory is not None,
        "trajectory_output_sha256": bool(archive_trajectory and archive_trajectory.get("sha256") == target["source_sha256"]),
        "trajectory_output_bytes": bool(archive_trajectory and archive_trajectory.get("bytes") == target.get("source_bytes")),
    }
    result_checks = {
        "schema": result.get("schema") == "core.cfd.v1",
        "case_id": result.get("case_id") == target["case_id"],
        "conversion_sha256": result.get("conversion", {}).get("sha256") == target["source_sha256"],
        "frame_count": result.get("conversion", {}).get("frames") == target["frames"],
        "particle_count": result.get("conversion", {}).get("particle_count") == target["particle_count"],
        "hard_integrity_pass": result.get("hard_integrity_pass") is True,
        "source_mass_gate_pass": result.get("source_mass_gate_pass") is True,
        "qualified": result.get("qualified") is False,
        "qualification_claim_none": result.get("qualification_claim") == "none; one case cannot establish range/temporal/reference qualification",
    }
    audit_checks = {
        "schema": audit.get("schema") == "core.cfd.v1",
        "case_id": audit.get("case_id") == target["case_id"],
        "hard_integrity_pass": audit.get("hard_integrity_pass") is True,
        "source_mass_gate_pass": audit.get("source_mass_gate_pass") is True,
        "qualified": audit.get("qualified") is False,
    }

    checks = [
        _check("collection_manifest_sha256", collection_sha == expected_collection_sha256, "collection manifest bytes are fixed", observed=collection_sha, expected=expected_collection_sha256),
        _check("collection_case_identity", all(identity_checks.values()), "collection row identity and source digest must match", details=identity_checks),
        _check("collection_source_path_exact", declared_hdf5 == target["source_hdf5"], "the Core collection row must declare the exact v2 source path", declared=declared_hdf5, expected=target["source_hdf5"]),
        _check("known_inputs_contract", bool(known_contract.get("contract_valid")), "known_inputs must reconstruct through Core inputs.v1 and reproduce the declared hash", details=known_contract),
        _check("prepared_parameter_contract", bool(prepared.get("available") and prepared.get("parameter_match") and prepared.get("declared_sha256_match", True)), "prepared DEV_07 q and drop-left parameter must bind the proposal", details=prepared),
        _check("source_path_exists", bool(source_metadata["exists"]), "target HDF5 must exist at the exact relative path", details=source_metadata),
        _check("source_archive_binding", all(source_archive_checks.values()), "v2 archive manifest must bind the exact trajectory output", details=source_archive_checks),
        _check("source_result_binding", all(result_checks.values()), "result metadata must bind the complete native source without qualification inheritance", details=result_checks),
        _check("source_audit_binding", all(audit_checks.values()), "audit metadata must bind hard integrity/mass checks without qualification", details=audit_checks),
        _check("code_files_present", all(item["exists"] for item in _code_snapshot(root, code_paths)["bindings"]), "all planned implementation files must be hashable",),
        _check("fresh_namespace_absent", not (_resolve(root, namespace, field="fresh_output_namespace").exists()), "planned output namespace must not already exist", namespace=namespace),
    ]
    code_snapshot = _code_snapshot(root, code_paths)
    blockers = [
        "collection_manifest_path_alias_must_be_replaced_or_root_explicitly_rebind_it"
        if not checks[2]["passed"] else None,
        "fresh_root_review_and_material_definition_admission_missing",
        "fresh_resource_admission_and_runtime_authorization_missing",
        "one_shot_authorization_must_remain_unconsumed_and_cannot_be_used_by_this_proposal",
        "material_trace_and_diagnosis_do_not_exist_in_this_proposal",
        "4.340002980805959_s_source_cannot_prove_the_registered_8.68_s_extension_if_right_censored",
        "reader_formal_eligible_is_false_and_no_material_labels_or_T2_credit_may_be_inferred",
    ]
    blockers.extend(
        f"failed_static_check:{item['check']}" for item in checks if not item["passed"]
    )
    blockers = list(dict.fromkeys(item for item in blockers if item))

    output_paths = {
        "namespace": namespace,
        "material_h5": f"{namespace}/product/tallwall120_material.h5",
        "material_result_json": f"{namespace}/product/tallwall120_material.json",
        "diagnosis_json": f"{namespace}/product/tallwall120_material_diagnosis.json",
        "checkpoint_manifest": f"{namespace}/product/tallwall120_material.h5.checkpoint.json",
        "checkpoint_generations": f"{namespace}/product/tallwall120_material.h5.checkpoints/",
        "log": f"{namespace}/logs/material-trace.log",
        "namespace_policy": {
            "must_be_absent_before_admission": True,
            "overwrite_allowed": False,
            "resume_allowed": False,
            "reuse_historical_trace": False,
            "historical_trace_paths_are_not_inputs": [
                "/tmp/f4-dev07-material-baseline24-20260928.h5",
                "campaigns/core-v1/runtime/attempts/core-f4-tallwall120-material-cadence-native004-s2-canary-v1/",
            ],
        },
    }

    return {
        "schema": SCHEMA,
        "created_at_utc": created_at_utc,
        "status": "blocked_fail_closed",
        "proposal_only": True,
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification": {
            "T1": False,
            "T2": False,
            "credit": 0,
            "qualification_credit": 0,
            "material_labels_created": False,
            "material_labels_source": "not_generated",
            "registry_mutation": 0,
            "completion_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
        "target": target,
        "source": {
            "hdf5": source_metadata,
            "archive_manifest": archive_ref,
            "result": result_ref,
            "audit": audit_ref,
            "collection_manifest": {
                "path": collection_manifest,
                "sha256": collection_sha,
                "expected_sha256": expected_collection_sha256,
                "sha256_match": collection_sha == expected_collection_sha256,
                "declared_case_hdf5": declared_hdf5,
                "declared_case_sha256": row_sha,
                "exact_path_match": declared_hdf5 == target["source_hdf5"],
                "reader_formal_eligible": reader_formal_eligible,
                "manifest_declared_formal_eligible": manifest_declared_formal_eligible,
                "manifest_flag_does_not_override_trusted_reader": True,
            },
            "archive_output_binding": archive_trajectory,
            "case_row": {
                "case_id": row.get("case_id"),
                "physical_case_id": row.get("physical_case_id"),
                "lineage_group_id": row.get("lineage_group_id"),
                "split": row.get("split"),
                "family": row.get("family"),
                "source_sha256": row_sha,
                "known_inputs_sha256": row.get("known_inputs_sha256"),
            },
            "known_inputs_contract": known_contract,
            "prepared_contract": prepared,
            "native_shape_contract": {
                "frames": target["frames"],
                "transitions": target["transitions"],
                "time_start_s": target["time_start_s"],
                "time_end_s": target["time_end_s"],
                "particle_count": target["particle_count"],
                "hdf5_reopened_by_planner": False,
            },
        },
        "code_contract": code_snapshot,
        "parameter_contract": PARAMETER_CONTRACT,
        "argv_contract": _argv_contract(target, namespace),
        "planned_output_namespace": output_paths,
        "admission": {
            "admission_status": "blocked_fail_closed",
            "static_checks": checks,
            "reader_formal_eligible": reader_formal_eligible,
            "required_before_any_runtime": [
                "exact target HDF5 content hash rechecked from a read-only descriptor immediately before launch",
                "collection/source manifest path and SHA reconciliation accepted by a fresh root review",
                "fresh material definition and source-bound recipe admission",
                "fresh resource admission and output namespace reservation",
                "explicit runtime authorization for exactly the argv contract recorded here",
                "full 217-transition material trace and read-only diagnosis receipt",
                "event-window completion or an explicitly authorized native extension; no right-censor imputation",
            ],
            "blocking_reasons": blockers,
            "one_shot_authorization": {
                "consumed": False,
                "consumption_allowed_by_this_proposal": False,
                "note": "This proposal does not read, reserve, or consume an authorization token.",
            },
        },
        "execution_controls": {
            "static_only": True,
            "solver_started": False,
            "worker_started": False,
            "native_started": False,
            "gencase_started": False,
            "gpu_started": False,
            "queue_mutation": False,
            "source_mutation": False,
            "production_artifact_mutation": False,
            "plan_mutation": False,
        },
        "scientific_boundary": {
            "baseline24_is_planned_not_executed": True,
            "native_source_labels_are_not_material_labels": True,
            "no_material_trace_claim": True,
            "no_T2_credit_claim": True,
            "existing_dev07_negative_diagnostic_not_promoted": True,
        },
    }


def write_proposal(proposal: Mapping[str, Any], output: str | Path) -> Path:
    """Write only the caller-selected proposal JSON, never campaign state."""
    path = Path(output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(proposal, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fresh-output-namespace", default=DEFAULT_OUTPUT_NAMESPACE)
    args = parser.parse_args(argv)
    proposal = build_proposal(args.lab_root, fresh_output_namespace=args.fresh_output_namespace)
    write_proposal(proposal, args.output)
    print(json.dumps({
        "output": str(Path(args.output).resolve()),
        "schema": proposal["schema"],
        "status": proposal["status"],
        "proposal_only": proposal["proposal_only"],
        "formal_eligible": proposal["formal_eligible"],
        "credit": proposal["qualification"]["credit"],
        "blocking_reasons": len(proposal["admission"]["blocking_reasons"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
