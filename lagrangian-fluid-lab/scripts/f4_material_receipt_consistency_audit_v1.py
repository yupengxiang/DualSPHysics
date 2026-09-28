#!/usr/bin/env python3
"""Fail-closed consistency audit for the F4 Tallwall120 material receipts.

This audit is deliberately limited to small JSON/Python files and filesystem
metadata.  It never opens, hashes, or otherwise reads trajectory HDF5 content;
it also does not authorize or start any worker, solver, GPU, queue, or runtime
job.  The audit binds the current coarse planner output to the already
committed proposal receipt without rewriting that historical receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

# Keep both ``python -m scripts...`` and the documented direct script path
# usable without changing the planner's import contract.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f4_tallwall120_material_coarse_proposal_v1 as planner


SCHEMA = "core.material.f4.tallwall120.receipt_consistency_audit.v1"
LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"
)

COARSE_RECEIPT = Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
READER_RECEIPT = Path("reports/F4-TALLWALL120-CORE-READER-SMOKE-2026-09-28.json")
DEV07_DIAGNOSTIC = Path(
    "reports/F4-TALLWALL120-DEV07-MATERIAL-BASELINE24-DIAGNOSTIC-2026-09-28.json"
)
COLLECTION_MANIFEST = Path(planner.COLLECTION_MANIFEST)
PLANNER_SCRIPT = Path("scripts/f4_tallwall120_material_coarse_proposal_v1.py")
MAX_SMALL_FILE_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = {".h5", ".hdf5"}


def _resolve(root: Path, relative: Path | str) -> Path:
    path = Path(relative)
    return path if path.is_absolute() else root / path


def _sha256_small(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_SMALL_FILE_BYTES:
        raise ValueError(f"refusing to hash oversized non-HDF5 input: {path} ({size} bytes)")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(root: Path, relative: Path | str) -> dict[str, Any]:
    path = _resolve(root, relative)
    if path.suffix.lower() in HDF5_SUFFIXES:
        raise ValueError(f"HDF5 is outside the JSON-only audit boundary: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_SMALL_FILE_BYTES:
        raise ValueError(f"JSON input exceeds audit bound: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _small_ref(root: Path, relative: Path | str, role: str) -> dict[str, Any]:
    path = _resolve(root, relative)
    if path.suffix.lower() in HDF5_SUFFIXES:
        raise ValueError(f"HDF5 cannot be a small receipt input: {path}")
    exists = path.is_file()
    result: dict[str, Any] = {
        "role": role,
        "path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
        "exists": exists,
    }
    if exists:
        result["bytes"] = path.stat().st_size
        result["sha256"] = _sha256_small(path)
    else:
        result["bytes"] = None
        result["sha256"] = None
    return result


def _check(
    name: str,
    passed: bool,
    reason: str,
    *,
    observed: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }


def _static_map(proposal: Mapping[str, Any]) -> dict[str, bool]:
    return {
        item["check"]: bool(item["passed"])
        for item in proposal["admission"]["static_checks"]
    }


def _static_details(proposal: Mapping[str, Any], name: str) -> dict[str, Any]:
    for item in proposal["admission"]["static_checks"]:
        if item["check"] == name:
            return dict(item.get("details", {}))
    return {}


def _normalise_code_contract(contract: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = contract.get("bindings", contract.get("files", []))
    return sorted(
        [
            {"path": str(row["path"]), "sha256": str(row["sha256"])}
            for row in rows
        ],
        key=lambda row: (row["path"], row["sha256"]),
    )


def _normalise_argv_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(contract)
    # The committed receipt predates the planner's explicit placeholder
    # metadata; namespace projection below binds the same values separately.
    result.pop("placeholder_semantics", None)
    if "forbidden_argv_mutations" in result:
        result["forbidden_mutations"] = result.pop("forbidden_argv_mutations")
    result["forbidden_mutations"] = [
        _normalise_mutation(value) for value in result.get("forbidden_mutations", [])
    ]
    return result


def _normalise_mutation(value: str) -> str:
    """Collapse wording-only differences in the historical argv receipt."""

    lowered = value.lower()
    if "source path" in lowered or "source sha" in lowered:
        return "source_identity_immutable"
    if "q," in lowered or "dp_m" in lowered or "neighbour" in lowered:
        return "material_parameters_immutable"
    if "resume" in lowered or "overwrite" in lowered or "namespace" in lowered:
        return "fresh_namespace_no_resume_or_overwrite"
    if "threshold" in lowered or "imputation" in lowered or "right-censored" in lowered:
        return "no_threshold_relaxation_or_imputation"
    return value


_STATIC_CHECK_ALIASES = {
    "code_files_present": "code_files_present_and_hashed",
    "source_path_exists": "source_path_exists_and_size_matches_archive",
}


def _normalise_static_map(proposal_or_receipt: Mapping[str, Any]) -> dict[str, bool]:
    if isinstance(proposal_or_receipt["admission"]["static_checks"], list):
        raw = _static_map(proposal_or_receipt)
    else:
        raw = {
            key: bool(value)
            for key, value in proposal_or_receipt["admission"]["static_checks"].items()
        }
    return {_STATIC_CHECK_ALIASES.get(key, key): value for key, value in raw.items()}


def _normalise_blocker(blocker: str) -> str:
    if blocker in {
        "reader_formal_eligible_is_false_and_no_material_labels_or_T2_credit_may_be_inferred",
        "trusted_reader_formal_eligible_is_false_and_manifest_declaration_cannot_override_it",
    }:
        return "trusted_reader_formal_eligible_is_false_and_manifest_declaration_cannot_override_it"
    return blocker


def _normalise_namespace_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(contract.get("namespace_policy", {}))
    return {
        "namespace": contract.get("namespace"),
        "must_be_absent_before_admission": contract.get(
            "must_be_absent_before_admission", policy.get("must_be_absent_before_admission")
        ),
        "overwrite_allowed": contract.get("overwrite_allowed", policy.get("overwrite_allowed")),
        "resume_allowed": contract.get("resume_allowed", policy.get("resume_allowed")),
        "historical_trace_reuse": contract.get(
            "historical_trace_reuse", policy.get("reuse_historical_trace")
        ),
        "historical_paths_not_inputs": contract.get(
            "historical_paths_not_inputs",
            policy.get("historical_trace_paths_are_not_inputs"),
        ),
    }


def _direct_source_projection(root: Path, proposal: Mapping[str, Any]) -> dict[str, Any]:
    source = proposal["source"]
    archive_ref = source["archive_manifest"]
    result_ref = source["result"]
    audit_ref = source["audit"]
    archive = _read_json(root, archive_ref["path"])
    result = _read_json(root, result_ref["path"])
    audit = _read_json(root, audit_ref["path"])
    archive_target = next(
        (
            output
            for output in archive.get("outputs", [])
            if output.get("path") == "product/trajectory.h5"
        ),
        {},
    )
    archive_target_repo_path = (
        Path(archive_ref["path"]).parent / archive_target.get("path", "")
    ).as_posix()
    direct = {
        "path": archive_ref["path"],
        "sha256": archive_ref["sha256"],
        "schema": archive.get("schema"),
        "execution_status": archive.get("execution_status"),
        "trajectory_output": {
            "path": archive_target.get("path"),
            "bytes": archive_target.get("bytes"),
            "sha256": archive_target.get("sha256"),
        },
        "exact_target_binding": bool(
            archive_target_repo_path == proposal["target"]["source_hdf5"]
            and archive_target.get("sha256") == proposal["target"]["source_sha256"]
        ),
    }
    collection = source["collection_manifest"]
    collection_projection = {
        "path": collection["path"],
        "sha256": collection["sha256"],
        "case_row_source_sha256": collection["declared_case_sha256"],
        "case_row_declared_hdf5": collection["declared_case_hdf5"],
        "requested_hdf5": proposal["target"]["source_hdf5"],
        "exact_path_match": collection["exact_path_match"],
        "manifest_declared_formal_eligible": collection["manifest_declared_formal_eligible"],
        "trusted_reader_formal_eligible": collection["reader_formal_eligible"],
        "manifest_flag_does_not_override_trusted_reader": collection[
            "manifest_flag_does_not_override_trusted_reader"
        ],
    }
    source_result_projection = {
        "path": result_ref["path"],
        "sha256": result_ref["sha256"],
        "hard_integrity_pass": result.get("hard_integrity_pass"),
        "source_mass_gate_pass": result.get("source_mass_gate_pass"),
        "qualified": result.get("qualified"),
        "qualification_claim": result.get("qualification_claim"),
    }
    source_audit_projection = {
        "path": audit_ref["path"],
        "sha256": audit_ref["sha256"],
        "hard_integrity_pass": audit.get("hard_integrity_pass"),
        "source_mass_gate_pass": audit.get("source_mass_gate_pass"),
        "qualified": audit.get("qualified"),
    }
    hdf5 = source["hdf5"]
    native_shape = source["native_shape_contract"]
    hdf5_projection = {
        "exists_and_size_matches_archive": hdf5["byte_size_match_archive"],
        "content_hash_rehashed_by_planner": hdf5["content_hash_rehashed_by_planner"],
        "declared_source_sha256_fixed": bool(
            hdf5["sha256"] == proposal["target"]["source_sha256"]
        ),
        "content_hash_recheck_required_before_any_runtime": hdf5[
            "content_hash_recheck_required_before_runtime"
        ],
        "hdf5_reopened_by_planner": native_shape["hdf5_reopened_by_planner"],
    }
    return {
        "direct_source_manifest": direct,
        "core_collection_manifest": collection_projection,
        "source_result": source_result_projection,
        "source_audit": source_audit_projection,
        "hdf5_planner_boundary": hdf5_projection,
    }


def _known_inputs_projection(proposal: Mapping[str, Any]) -> dict[str, Any]:
    source = proposal["source"]
    contract = source["known_inputs_contract"]
    row = source["case_row"]
    return {
        "contract_version": contract["contract_version"],
        "representation": contract["representation"],
        "declared_sha256": contract["declared_sha256"],
        "reconstructed_sha256": contract["computed_sha256"],
        "contract_valid": contract["contract_valid"],
        "contains_future_or_reference_state": contract["contains_future_or_reference_state"],
        "coordinate_frame": contract["coordinate_frame"],
        "source_row_identity": {
            "case_id": row["case_id"],
            "physical_case_id": row["physical_case_id"],
            "lineage_group_id": row["lineage_group_id"],
            "family": row["family"],
            "split": row["split"],
        },
    }


def _prepared_projection(proposal: Mapping[str, Any]) -> dict[str, Any]:
    prepared = proposal["source"]["prepared_contract"]
    params = proposal["parameter_contract"]
    return {
        "path": prepared["path"],
        "sha256": prepared["declared_sha256"],
        "q": prepared["q"],
        "drop_left_x_m": prepared["drop_left_x_m"],
        "dp_m": params["dp_m"],
        "qualification_inherited": prepared["qualification_inherited"],
        "parameter_match": prepared["parameter_match"],
    }


def _receipt_source_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    source = receipt["source_manifest_contract"]
    return {
        "direct_source_manifest": dict(source["direct_source_manifest"]),
        "core_collection_manifest": dict(source["core_collection_manifest"]),
        "source_result": dict(source["source_result"]),
        "source_audit": dict(source["source_audit"]),
        "hdf5_planner_boundary": dict(source["hdf5_planner_boundary"]),
    }


def _hdf5_metadata(root: Path, proposal: Mapping[str, Any]) -> dict[str, Any]:
    relative = proposal["target"]["source_hdf5"]
    path = _resolve(root, relative)
    metadata: dict[str, Any] = {
        "path": relative,
        "exists": path.is_file(),
        "content_read": False,
        "content_hash_recomputed": False,
        "declared_sha256": proposal["target"]["source_sha256"],
    }
    if path.exists():
        metadata["bytes"] = path.stat().st_size
    else:
        metadata["bytes"] = None
    return metadata


def _path_family(observed: str, expected: str) -> str:
    if "archives-v1/" in observed and "archives-v2/" in expected:
        return "archives-v1_vs_archives-v2"
    if "archives-v2/" in observed and "archives-v1/" in expected:
        return "archives-v2_vs_archives-v1"
    return "other_path_mismatch"


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> dict[str, Any]:
    """Build a deterministic, fail-closed report without reading HDF5 content."""

    root = Path(lab_root).resolve()
    proposal = planner.build_proposal(root)
    receipt = _read_json(root, COARSE_RECEIPT)
    reader = _read_json(root, READER_RECEIPT)
    diagnostic = _read_json(root, DEV07_DIAGNOSTIC)
    collection_path = _resolve(root, COLLECTION_MANIFEST)
    current_collection_sha = _sha256_small(collection_path)

    checks: list[dict[str, Any]] = []
    add = checks.append

    proposal_source_projection = _direct_source_projection(root, proposal)
    receipt_source_projection = _receipt_source_projection(receipt)
    receipt_source_match = proposal_source_projection == receipt_source_projection
    add(
        _check(
            "planner_source_projection_matches_committed_receipt",
            receipt_source_match,
            "compare semantic source projection; HDF5 content is not part of this comparison",
            observed=proposal_source_projection,
            expected=receipt_source_projection,
        )
    )

    add(
        _check(
            "planner_schema_and_status_match_committed_receipt",
            proposal["schema"] == receipt["schema"]
            and proposal["status"] == receipt["status"]
            and proposal["proposal_only"] == receipt["proposal_only"]
            and proposal["diagnostic_only"] == receipt["diagnostic_only"]
            and proposal["formal_eligible"] == receipt["formal_eligible"],
            "current build_proposal identity/status is bound to the historical receipt",
            observed={
                "schema": proposal["schema"],
                "status": proposal["status"],
                "proposal_only": proposal["proposal_only"],
                "diagnostic_only": proposal["diagnostic_only"],
                "formal_eligible": proposal["formal_eligible"],
            },
            expected={
                "schema": receipt["schema"],
                "status": receipt["status"],
                "proposal_only": receipt["proposal_only"],
                "diagnostic_only": receipt["diagnostic_only"],
                "formal_eligible": receipt["formal_eligible"],
            },
        )
    )
    add(
        _check(
            "planner_target_matches_committed_receipt",
            proposal["target"] == receipt["target"],
            "target and DEV_07 source identity remain exact",
            observed=proposal["target"],
            expected=receipt["target"],
        )
    )
    add(
        _check(
            "planner_known_inputs_matches_committed_receipt",
            _known_inputs_projection(proposal) == receipt["known_inputs_contract"],
            "known-input contract is compared by declared and reconstructed SHA",
            observed=_known_inputs_projection(proposal),
            expected=receipt["known_inputs_contract"],
        )
    )
    add(
        _check(
            "planner_prepared_parameters_matches_committed_receipt",
            _prepared_projection(proposal) == receipt["prepared_parameter_contract"],
            "prepared parameter receipt remains bound to the same static values",
            observed=_prepared_projection(proposal),
            expected=receipt["prepared_parameter_contract"],
        )
    )
    add(
        _check(
            "planner_parameter_contract_matches_committed_receipt",
            proposal["parameter_contract"] == receipt["parameter_contract"],
            "full static material parameter contract remains bound",
            observed=proposal["parameter_contract"],
            expected=receipt["parameter_contract"],
        )
    )

    current_code = _normalise_code_contract(proposal["code_contract"])
    receipt_code = _normalise_code_contract(receipt["code_contract"])
    add(
        _check(
            "planner_code_snapshot_matches_committed_receipt",
            proposal["code_contract"]["code_snapshot_sha256"]
            == receipt["code_contract"]["code_snapshot_sha256"],
            "planner code snapshot SHA is unchanged",
            observed=proposal["code_contract"]["code_snapshot_sha256"],
            expected=receipt["code_contract"]["code_snapshot_sha256"],
        )
    )
    add(
        _check(
            "planner_code_file_sha_projection_matches_committed_receipt",
            current_code == receipt_code,
            "compare path/SHA bindings while tolerating historical role wording",
            observed=current_code,
            expected=receipt_code,
        )
    )

    current_argv = _normalise_argv_contract(proposal["argv_contract"])
    receipt_argv = _normalise_argv_contract(receipt["argv_contract"])
    add(
        _check(
            "planner_argv_contract_matches_committed_receipt",
            current_argv == receipt_argv,
            "argv contract is normalized only for the historical key name",
            observed=current_argv,
            expected=receipt_argv,
        )
    )
    current_namespace = _normalise_namespace_contract(proposal["planned_output_namespace"])
    receipt_namespace = _normalise_namespace_contract(receipt["planned_output_namespace"])
    add(
        _check(
            "planner_namespace_contract_matches_committed_receipt",
            current_namespace == receipt_namespace,
            "fresh namespace and historical-trace reuse policy remain bound",
            observed=current_namespace,
            expected=receipt_namespace,
        )
    )

    current_static = _normalise_static_map(proposal)
    receipt_static = _normalise_static_map(receipt)
    add(
        _check(
            "planner_static_checks_match_committed_receipt",
            current_static == receipt_static,
            "static admission check map matches the committed normalized receipt",
            observed=current_static,
            expected=receipt_static,
        )
    )
    current_core_blockers = [
        _normalise_blocker(blocker)
        for blocker in proposal["admission"]["blocking_reasons"]
        if not blocker.startswith("failed_static_check:")
    ]
    receipt_blockers = [
        _normalise_blocker(blocker) for blocker in receipt["admission"]["blocking_reasons"]
    ]
    add(
        _check(
            "planner_core_blockers_match_committed_receipt",
            current_core_blockers == receipt_blockers,
            "core blockers match after separating a current derived static-check detail",
            observed=current_core_blockers,
            expected=receipt_blockers,
        )
    )
    add(
        _check(
            "planner_blocker_projection_exact",
            proposal["admission"]["blocking_reasons"] == receipt_blockers,
            "exact blocker list detects receipt representation drift without rewriting it",
            observed=proposal["admission"]["blocking_reasons"],
            expected=receipt_blockers,
        )
    )
    add(
        _check(
            "planner_qualification_boundary_matches_committed_receipt",
            proposal["qualification"] == receipt["qualification"],
            "T1/T2, credit, and mutation boundary remain identical",
            observed=proposal["qualification"],
            expected=receipt["qualification"],
        )
    )
    add(
        _check(
            "planner_execution_boundary_matches_committed_receipt",
            proposal["execution_controls"] == receipt["execution_controls"],
            "static-only execution boundary remains identical",
            observed=proposal["execution_controls"],
            expected=receipt["execution_controls"],
        )
    )
    add(
        _check(
            "planner_scientific_boundary_matches_committed_receipt",
            proposal["scientific_boundary"] == receipt["scientific_boundary"],
            "no material trace, T2, or formal promotion is inferred",
            observed=proposal["scientific_boundary"],
            expected=receipt["scientific_boundary"],
        )
    )
    raw_shape_match = set(proposal) == set(receipt)
    add(
        _check(
            "planner_raw_report_shape_matches_committed_receipt",
            raw_shape_match,
            "raw top-level shape is checked separately from the normalized projection",
            observed=sorted(proposal),
            expected=sorted(receipt),
        )
    )

    reader_manifest_path = reader.get("manifest")
    reader_manifest_sha = reader.get("manifest_sha256")
    add(
        _check(
            "collection_manifest_current_sha_matches_planner",
            current_collection_sha == proposal["source"]["collection_manifest"]["sha256"],
            "current collection manifest file is bound to build_proposal",
            observed=current_collection_sha,
            expected=proposal["source"]["collection_manifest"]["sha256"],
        )
    )
    add(
        _check(
            "reader_smoke_manifest_path_matches_current",
            reader_manifest_path == COLLECTION_MANIFEST.as_posix(),
            "reader smoke receipt points at the current collection manifest path",
            observed=reader_manifest_path,
            expected=COLLECTION_MANIFEST.as_posix(),
        )
    )
    add(
        _check(
            "reader_smoke_manifest_sha_matches_current",
            reader_manifest_sha == current_collection_sha,
            "reader smoke receipt must be rejected when its recorded manifest SHA is stale",
            observed=reader_manifest_sha,
            expected=current_collection_sha,
        )
    )
    add(
        _check(
            "reader_smoke_formal_gate_remains_closed",
            reader.get("reader_result", {}).get("reader_formal_eligible") is False,
            "reader smoke cannot promote a case to formal material eligibility",
            observed=reader.get("reader_result", {}).get("reader_formal_eligible"),
            expected=False,
        )
    )

    collection_projection = proposal_source_projection["core_collection_manifest"]
    declared_hdf5 = collection_projection["case_row_declared_hdf5"]
    target_hdf5 = proposal["target"]["source_hdf5"]
    version_mismatch = _path_family(declared_hdf5, target_hdf5)
    add(
        _check(
            "archives_v1_v2_path_exact",
            declared_hdf5 == target_hdf5,
            "collection row and target path must be exact before runtime admission",
            observed=declared_hdf5,
            expected=target_hdf5,
        )
    )
    add(
        _check(
            "archives_v1_v2_mismatch_is_explicit",
            version_mismatch == "archives-v1_vs_archives-v2",
            "the path alias is classified explicitly rather than silently reconciled",
            observed=version_mismatch,
            expected="archives-v1_vs_archives-v2",
        )
    )
    add(
        _check(
            "archives_source_sha_remains_target_bound",
            collection_projection["case_row_source_sha256"]
            == proposal["target"]["source_sha256"],
            "archives path mismatch does not erase the independent source SHA binding",
            observed=collection_projection["case_row_source_sha256"],
            expected=proposal["target"]["source_sha256"],
        )
    )

    diagnostic_source = diagnostic.get("source", {})
    diagnostic_trace = diagnostic.get("trace", {})
    diagnostic_binding = diagnostic_trace.get("binding", {})
    diagnostic_decision = diagnostic.get("decision", {})
    diagnostic_sha_values = [
        diagnostic_source.get("before", {}).get("sha256"),
        diagnostic_source.get("after", {}).get("sha256"),
        diagnostic_binding.get("result_source_sha256"),
        diagnostic_binding.get("hdf5_attribute_source_sha256"),
    ]
    diagnostic_sha_match = bool(diagnostic_sha_values) and all(
        value == proposal["target"]["source_sha256"] for value in diagnostic_sha_values
    )
    add(
        _check(
            "dev07_diagnostic_source_path_matches_target",
            diagnostic_source.get("repo_relative_path") == proposal["target"]["source_hdf5"],
            "DEV_07 diagnostic receipt is bound to the target v2 source path",
            observed=diagnostic_source.get("repo_relative_path"),
            expected=proposal["target"]["source_hdf5"],
        )
    )
    add(
        _check(
            "dev07_diagnostic_source_sha_matches_target",
            diagnostic_sha_match
            and diagnostic_source.get("before_after_match") is True,
            "all diagnostic source bindings agree with the target SHA and unchanged-source check",
            observed={
                "sha_values": diagnostic_sha_values,
                "before_after_match": diagnostic_source.get("before_after_match"),
            },
            expected={
                "sha256": proposal["target"]["source_sha256"],
                "before_after_match": True,
            },
        )
    )
    diagnostic_negative = (
        diagnostic.get("status") == "completed_diagnostic_only"
        and diagnostic.get("diagnostic_only") is True
        and diagnostic_decision.get("formal_admission") is False
        and diagnostic_decision.get("T1") is False
        and diagnostic_decision.get("T2") is False
        and diagnostic_decision.get("credit") == 0
        and diagnostic_trace.get("event_window_complete") is False
        and diagnostic_trace.get("event_window_status") == "right_censored_or_unresolved"
        and diagnostic_trace.get("unknown_gate_pass") is False
        and diagnostic_trace.get("unknown_fraction_max") == 1.0
        and diagnostic_trace.get("common_reliable_path_coverage") == 0.0
    )
    add(
        _check(
            "dev07_diagnostic_negative_boundary_is_preserved",
            diagnostic_negative,
            "diagnostic-negative evidence cannot be promoted to T2 or credit",
            observed={
                "status": diagnostic.get("status"),
                "formal_admission": diagnostic_decision.get("formal_admission"),
                "T1": diagnostic_decision.get("T1"),
                "T2": diagnostic_decision.get("T2"),
                "credit": diagnostic_decision.get("credit"),
                "event_window_complete": diagnostic_trace.get("event_window_complete"),
                "event_window_status": diagnostic_trace.get("event_window_status"),
                "unknown_fraction_max": diagnostic_trace.get("unknown_fraction_max"),
                "common_reliable_path_coverage": diagnostic_trace.get(
                    "common_reliable_path_coverage"
                ),
            },
            expected={
                "status": "completed_diagnostic_only",
                "formal_admission": False,
                "T1": False,
                "T2": False,
                "credit": 0,
                "event_window_complete": False,
                "event_window_status": "right_censored_or_unresolved",
                "unknown_fraction_max": 1.0,
                "common_reliable_path_coverage": 0.0,
            },
        )
    )

    planner_hdf5_boundary = proposal_source_projection["hdf5_planner_boundary"]
    hdf5_boundary_preserved = (
        planner_hdf5_boundary["content_hash_rehashed_by_planner"] is False
        and planner_hdf5_boundary["hdf5_reopened_by_planner"] is False
        and planner_hdf5_boundary["content_hash_recheck_required_before_any_runtime"] is True
    )
    add(
        _check(
            "hdf5_content_boundary_is_preserved",
            hdf5_boundary_preserved,
            "planner and audit use metadata only; content recheck remains a future runtime gate",
            observed=planner_hdf5_boundary,
            expected={
                "content_hash_rehashed_by_planner": False,
                "hdf5_reopened_by_planner": False,
                "content_hash_recheck_required_before_any_runtime": True,
            },
        )
    )

    failed_checks = [item["check"] for item in checks if not item["passed"]]
    findings: list[dict[str, Any]] = []
    if not raw_shape_match or not receipt_source_match:
        findings.append(
            {
                "finding": "committed_proposal_receipt_projection_drift",
                "severity": "blocking",
                "detail": (
                    "the committed receipt is a normalized historical projection; "
                    "it is not overwritten to match the current raw build_proposal shape"
                ),
            }
        )
    if proposal["admission"]["blocking_reasons"] != receipt_blockers:
        findings.append(
            {
                "finding": "committed_proposal_receipt_omits_current_derived_blocker",
                "severity": "blocking",
                "detail": "current build_proposal includes failed_static_check:collection_source_path_exact",
            }
        )
    if reader_manifest_sha != current_collection_sha:
        findings.append(
            {
                "finding": "reader_smoke_receipt_manifest_sha_stale",
                "severity": "blocking",
                "detail": "reader smoke receipt SHA does not bind the current collection manifest bytes",
                "current_sha256": current_collection_sha,
                "receipt_sha256": reader_manifest_sha,
            }
        )
    if declared_hdf5 != target_hdf5:
        findings.append(
            {
                "finding": "collection_manifest_archives_v1_vs_target_archives_v2_mismatch",
                "severity": "blocking",
                "detail": "DEV_07 collection row still declares archives-v1 while proposal target is archives-v2",
                "collection_path": declared_hdf5,
                "target_path": target_hdf5,
            }
        )
    if diagnostic_negative:
        findings.append(
            {
                "finding": "dev07_diagnostic_negative_not_qualifying",
                "severity": "boundary",
                "detail": "DEV_07 diagnostic is target-bound but right-censored, unknown-gated, and non-qualifying",
            }
        )
    if reader.get("reader_result", {}).get("reader_formal_eligible") is False:
        findings.append(
            {
                "finding": "trusted_reader_formal_gate_closed",
                "severity": "boundary",
                "detail": "manifest formal declaration cannot override the trusted reader gate",
            }
        )

    input_refs = [
        _small_ref(root, COARSE_RECEIPT, "committed_coarse_proposal_receipt"),
        _small_ref(root, READER_RECEIPT, "reader_smoke_receipt"),
        _small_ref(root, DEV07_DIAGNOSTIC, "DEV_07_diagnostic_receipt"),
        _small_ref(root, COLLECTION_MANIFEST, "current_collection_manifest"),
        _small_ref(root, PLANNER_SCRIPT, "current_coarse_planner_source"),
    ]
    semantic_receipt_checks = [
        item
        for item in checks
        if item["check"].startswith("planner_")
        and item["check"]
        not in {
            "planner_blocker_projection_exact",
            "planner_raw_report_shape_matches_committed_receipt",
        }
    ]
    semantic_projection_match = all(item["passed"] for item in semantic_receipt_checks)

    return {
        "schema": SCHEMA,
        "observed_at_utc": observed_at_utc,
        "status": "blocked_fail_closed",
        "audit_only": True,
        "diagnostic_only": True,
        "formal_eligible": False,
        "scope": {
            "family": "F4",
            "case": "Tallwall120",
            "case_id": proposal["target"]["case_id"],
            "proposal_scope": proposal["target"]["scope_id"],
            "target_hdf5": proposal["target"]["source_hdf5"],
            "target_hdf5_sha256": proposal["target"]["source_sha256"],
        },
        "input_boundary": {
            "json_only": True,
            "file_metadata_only": True,
            "hdf5_opened": False,
            "hdf5_content_read": False,
            "hdf5_hash_recomputed": False,
            "production_hdf5_mutated": False,
            "worker_solver_gpu_queue_started": False,
        },
        "inputs": {
            "small_files": input_refs,
            "hdf5_metadata": _hdf5_metadata(root, proposal),
        },
        "planner_binding": {
            "module": PLANNER_SCRIPT.as_posix(),
            "build_proposal_status": proposal["status"],
            "build_proposal_formal_eligible": proposal["formal_eligible"],
            "committed_receipt": COARSE_RECEIPT.as_posix(),
            "semantic_projection_match": semantic_projection_match,
            "raw_top_level_shape_match": raw_shape_match,
            "derived_blocker_projection_match": proposal["admission"]["blocking_reasons"]
            == receipt_blockers,
            "historical_receipt_overwritten": False,
        },
        "collection_manifest_binding": {
            "path": COLLECTION_MANIFEST.as_posix(),
            "current_sha256": current_collection_sha,
            "planner_sha256": proposal["source"]["collection_manifest"]["sha256"],
            "reader_smoke_recorded_sha256": reader_manifest_sha,
            "reader_smoke_path": reader_manifest_path,
            "manifest_declared_formal_eligible": collection_projection[
                "manifest_declared_formal_eligible"
            ],
            "trusted_reader_formal_eligible": collection_projection[
                "trusted_reader_formal_eligible"
            ],
        },
        "reader_smoke_binding": {
            "receipt": READER_RECEIPT.as_posix(),
            "manifest_path_matches_current": reader_manifest_path == COLLECTION_MANIFEST.as_posix(),
            "manifest_sha_matches_current": reader_manifest_sha == current_collection_sha,
            "reader_formal_eligible": reader.get("reader_result", {}).get(
                "reader_formal_eligible"
            ),
            "dataset_opened": reader.get("reader_result", {}).get("dataset_opened"),
            "execution_complete_cases": reader.get("execution", {}).get(
                "execution_complete_cases"
            ),
        },
        "archives_path_binding": {
            "collection_case_declared_hdf5": declared_hdf5,
            "proposal_target_hdf5": target_hdf5,
            "mismatch_class": version_mismatch,
            "exact_path_match": declared_hdf5 == target_hdf5,
            "source_sha256_match": collection_projection["case_row_source_sha256"]
            == proposal["target"]["source_sha256"],
        },
        "dev07_diagnostic_binding": {
            "receipt": DEV07_DIAGNOSTIC.as_posix(),
            "source_path_matches_target": diagnostic_source.get("repo_relative_path")
            == proposal["target"]["source_hdf5"],
            "source_sha256_matches_target": diagnostic_sha_match,
            "before_after_match": diagnostic_source.get("before_after_match"),
            "status": diagnostic.get("status"),
            "event_window_complete": diagnostic_trace.get("event_window_complete"),
            "event_window_status": diagnostic_trace.get("event_window_status"),
            "unknown_fraction_max": diagnostic_trace.get("unknown_fraction_max"),
            "common_reliable_path_coverage": diagnostic_trace.get(
                "common_reliable_path_coverage"
            ),
            "unknown_gate_pass": diagnostic_trace.get("unknown_gate_pass"),
            "formal_admission": diagnostic_decision.get("formal_admission"),
            "T1": diagnostic_decision.get("T1"),
            "T2": diagnostic_decision.get("T2"),
            "credit": diagnostic_decision.get("credit"),
            "promote": False,
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "findings": findings,
        "qualification": {
            "T1": False,
            "T2": False,
            "T2_macro": False,
            "T2_path": False,
            "credit": 0,
            "qualification_credit": 0,
            "material_labels_created": False,
            "registry_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "gate_mutations": 0,
            "completion_mutations": 0,
        },
        "execution_controls": {
            "static_only": True,
            "worker_started": False,
            "solver_started": False,
            "native_runtime_started": False,
            "gencase_started": False,
            "gpu_requested": False,
            "queue_submitted": False,
            "scheduler_authorization": False,
            "root_authorization": False,
            "production_hdf5_opened": False,
            "production_hdf5_content_read": False,
            "production_hdf5_hash_recomputed": False,
            "registry_mutation": False,
            "ledger_mutation": False,
            "denominator_mutation": False,
            "gate_mutation": False,
            "completion_mutation": False,
        },
        "scientific_boundary": {
            "material_trace_created": False,
            "material_trace_admitted": False,
            "trusted_reader_formal_eligible": False,
            "T2_inferred": False,
            "credit_inferred": 0,
            "diagnostic_negative_promoted": False,
            "reader_smoke_manifest_drift_blocks_promotion": reader_manifest_sha
            != current_collection_sha,
            "archives_path_mismatch_blocks_promotion": declared_hdf5 != target_hdf5,
            "remaining_authorization_required": [
                "current_collection_row_rebound_to_archives-v2",
                "fresh_root_review_and_material_definition_admission",
                "fresh_resource_admission_and_runtime_authorization",
                "trusted_reader_formal_eligibility",
                "complete_reliable_material_trace_and_event_window",
            ],
        },
    }


def write_report(
    output: Path | str = DEFAULT_REPORT,
    *,
    lab_root: Path | str = LAB_ROOT,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> Path:
    output_path = Path(output)
    report = build_report(lab_root, observed_at_utc=observed_at_utc)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--observed-at-utc", default=DEFAULT_OBSERVED_AT_UTC)
    args = parser.parse_args()
    path = write_report(
        args.output,
        lab_root=args.lab_root,
        observed_at_utc=args.observed_at_utc,
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": report["status"],
                "failed_checks": len(report["failed_checks"]),
                "findings": len(report["findings"]),
                "output": str(path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
