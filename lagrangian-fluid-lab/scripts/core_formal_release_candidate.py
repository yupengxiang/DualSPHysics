#!/usr/bin/env python3
"""Materialize a versioned, non-authorizing formal release candidate.

This is the boundary between an auditable source closure and a future formal
release.  It snapshots the current learning code hashes, runs the read-only
admission audit, and writes a candidate record that can only report
``formal_release=true`` when the admission audit and source-closure binding
are ready.  It observes campaign completion for diagnostics, but does not use
the post-training ``can_finalize`` gate to authorize formal training.  It
never edits a reader manifest, upgrades ``formal_release``, starts a training
job, or writes registry/ledger state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_formal_admission_audit import (
    FORMAL_JOB_COUNT,
    REQUIRED_CODE_FILES,
    SCHEMA as ADMISSION_SCHEMA,
    audit_admission,
    canonical_sha256,
    sha256_file,
)
from scripts.core_campaign import completion as campaign_completion


CLOSURE_SCHEMA = "core.formal_source_closure.v1"
CANDIDATE_SCHEMA = "core.formal_release_candidate.v1"
GENERATOR_VERSION = "core-formal-release-candidate-v4"
DATA_BLOCKERS = {
    "MANIFEST_CONTRACT_INVALID",
    "SPLIT_SHAPE_REQUIRED",
    "HARD_AUDIT_GAP",
    "STRUCTURAL_AUDIT_GAP",
    "STRUCTURAL_RECEIPT_BINDING_GAP",
    "AUDIT_BINDING_GAP",
}
CAMPAIGN_REGISTRY = Path("campaigns/core-v1/registry.json")
CAMPAIGN_CHECKS = (
    "three_t1_families",
    "two_macro_t2_families",
    "nine_formal_training_runs",
    "t1_denominator_complete",
    "material_denominator_complete",
    "independent_reproduction",
    "causal_lineage_contracts",
    "evidence_valid",
)
CAMPAIGN_COMPLETION_INTEGER_FIELDS = (
    "missing_t1_case_runs",
    "missing_material_case_runs",
    "missing_registered_material_case_runs",
    "missing_registered_t1_case_runs",
    "missing_target_t1_case_runs",
    "missing_target_material_case_runs",
    "unregistered_t1_case_runs",
    "unregistered_material_case_runs",
    "unregistered_t1_evidence_case_runs",
    "unregistered_material_evidence_case_runs",
    "required_t1_case_runs",
    "required_material_case_runs",
    "observed_t1_case_runs",
    "observed_material_case_runs",
    "minimum_t1_case_runs",
    "minimum_material_case_runs",
)
CAMPAIGN_COMPLETION_LIST_FIELDS = (
    "t1_families",
    "macro_t2_families",
    "training_runs",
    "expected_training_runs",
    "missing_training_runs",
)


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def _digest_self() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"immutable candidate output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                  ensure_ascii=False, allow_nan=False) + "\n",
                       encoding="utf-8")
    partial.replace(path)


def _registry_reference(path: Path, *, root: Path) -> dict[str, Any]:
    try:
        relative = _relative(path, root)
    except ValueError:
        relative = str(path)
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _validate_campaign_completion_status(status: Any) -> list[str]:
    """Validate the completion receipt before allowing it to affect release."""
    if not isinstance(status, Mapping):
        return ["completion result is not a JSON object"]
    errors: list[str] = []
    if status.get("schema") != "core.completion.v1":
        errors.append("completion schema is missing or unsupported")
    if not isinstance(status.get("can_finalize"), bool):
        errors.append("completion can_finalize must be boolean")
    checks = status.get("checks")
    if not isinstance(checks, Mapping):
        errors.append("completion checks must be an object")
    else:
        if set(checks) != set(CAMPAIGN_CHECKS):
            errors.append("completion checks do not match the fixed gate set")
        if any(type(value) is not bool for value in checks.values()):
            errors.append("completion check values must be boolean")
        if isinstance(status.get("can_finalize"), bool):
            expected = all(checks.get(name) is True for name in CAMPAIGN_CHECKS)
            if status["can_finalize"] is not expected:
                errors.append("completion can_finalize disagrees with its checks")
    for field in CAMPAIGN_COMPLETION_LIST_FIELDS:
        value = status.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ) or len(value) != len(set(value)):
            errors.append(f"completion {field} must be a unique string list")
    for field in CAMPAIGN_COMPLETION_INTEGER_FIELDS:
        value = status.get(field)
        if type(value) is not int or value < 0:
            errors.append(f"completion {field} must be a non-negative integer")
    issues = status.get("issues")
    if not isinstance(issues, list):
        errors.append("completion issues must be a list")
    return errors


def _invalid_campaign_observation(
    *, reference: Mapping[str, Any], bound: bool, error: str,
) -> dict[str, Any]:
    return {
        "bound": bound,
        "valid": False,
        "can_finalize": False,
        "registry": dict(reference),
        "checks": {},
        "t1_families": [],
        "macro_t2_families": [],
        "training_runs": [],
        "missing_t1_case_runs": None,
        "missing_material_case_runs": None,
        "issues": [{"registry": "completion", "reason": error}],
        "error": error,
    }


def _campaign_completion_observation(
    *, root: Path, registry: str | Path | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Read the central completion gate without mutating campaign state."""
    registry_path: Path | None = None
    if isinstance(registry, Mapping):
        try:
            payload: Mapping[str, Any] | None = dict(registry)
            reference = {
                "path": "<in-memory>",
                "sha256": canonical_sha256(payload),
                "bytes": len(json.dumps(
                    payload, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                ).encode("utf-8")),
            }
        except (TypeError, ValueError, OverflowError) as error:
            return _invalid_campaign_observation(
                reference={"path": "<in-memory>", "sha256": None, "bytes": None},
                bound=True,
                error=str(error),
            )
    else:
        registry_path = Path(registry).expanduser() if registry is not None else root / CAMPAIGN_REGISTRY
        if not registry_path.is_absolute():
            registry_path = root / registry_path
        registry_path = registry_path.resolve()
        reference = {"path": str(registry_path), "sha256": None, "bytes": None}
        try:
            if not registry_path.is_file():
                raise FileNotFoundError(registry_path)
            reference = _registry_reference(registry_path, root=root)
            loaded = json.loads(registry_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, Mapping):
                raise ValueError("campaign registry must be a JSON object")
            payload = dict(loaded)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            return _invalid_campaign_observation(
                reference=reference, bound=False, error=str(error),
            )

    try:
        status = campaign_completion(payload, root)
    except Exception as error:
        return _invalid_campaign_observation(
            reference=reference, bound=True, error=str(error),
        )
    validation_errors = _validate_campaign_completion_status(status)
    valid = not validation_errors
    if not valid:
        return _invalid_campaign_observation(
            reference=reference, bound=True,
            error="; ".join(validation_errors),
        ) | {
            "observed": status if isinstance(status, Mapping) else status,
        }
    return {
        "bound": True,
        "valid": valid,
        "can_finalize": status.get("can_finalize") is True,
        "registry": reference,
        "checks": dict(status.get("checks", {})) if isinstance(status, Mapping) else {},
        "t1_families": list(status.get("t1_families", ())) if isinstance(status, Mapping) else [],
        "macro_t2_families": list(status.get("macro_t2_families", ())) if isinstance(status, Mapping) else [],
        "training_runs": list(status.get("training_runs", ())) if isinstance(status, Mapping) else [],
        "missing_t1_case_runs": status.get("missing_t1_case_runs") if isinstance(status, Mapping) else None,
        "missing_material_case_runs": status.get("missing_material_case_runs") if isinstance(status, Mapping) else None,
        "issues": list(status.get("issues", ())) if isinstance(status, Mapping) else [],
    }


def _invalid_admission_observation(error: str) -> dict[str, Any]:
    return {
        "schema": ADMISSION_SCHEMA,
        "record_id": "invalid-admission-observation",
        "status": "blocked",
        "formal_admission": False,
        "formal_job_count": 0,
        "required_formal_job_count": FORMAL_JOB_COUNT,
        "blockers": [{
            "code": "ADMISSION_AUDIT_INVALID",
            "scope": "formal",
            "message": "the admission audit was missing, malformed, or raised an exception",
            "observed": error,
            "required": f"valid {ADMISSION_SCHEMA}",
        }],
        "manifests": [],
        "evidence": [],
        "family_summary": {},
        "production_denominator": {
            "failure_denominator_preserved": False,
        },
        "source_closure": {},
        "resource_profile": {},
        "resource_dryrun": {},
        "graph_probe": {},
        "execution_constraints": {
            "read_only": False,
            "formal_runs_started": None,
            "gpu_started": None,
            "solver_started": None,
            "submitted": None,
        },
        "admission_next_dependency": "repair the admission audit before considering formal release",
    }


def _validate_admission_observation(audit: Any) -> list[str]:
    """Validate the subset of the admission receipt used as a release gate."""
    if not isinstance(audit, Mapping):
        return ["admission audit is not a JSON object"]
    errors: list[str] = []
    if audit.get("schema") != ADMISSION_SCHEMA:
        errors.append("admission audit schema is missing or unsupported")
    if audit.get("status") not in {"ready", "blocked"}:
        errors.append("admission audit status is missing or unsupported")
    if not isinstance(audit.get("formal_admission"), bool):
        errors.append("admission formal_admission must be boolean")
    if type(audit.get("formal_job_count")) is not int or audit.get("formal_job_count") != 0:
        errors.append("admission formal_job_count must be zero")
    if (type(audit.get("required_formal_job_count")) is not int
            or audit.get("required_formal_job_count") != FORMAL_JOB_COUNT):
        errors.append("admission required_formal_job_count is not the fixed denominator")
    blockers = audit.get("blockers")
    if not isinstance(blockers, list):
        errors.append("admission blockers must be a list")
    else:
        seen_codes: set[str] = set()
        for index, blocker in enumerate(blockers):
            if not isinstance(blocker, Mapping):
                errors.append(f"admission blocker {index} is not an object")
                continue
            code = blocker.get("code")
            if not isinstance(code, str) or not code:
                errors.append(f"admission blocker {index} has no code")
            elif code in seen_codes:
                errors.append(f"admission blocker code is duplicated: {code}")
            else:
                seen_codes.add(code)
            if not isinstance(blocker.get("scope"), str) or not blocker.get("scope"):
                errors.append(f"admission blocker {index} has no scope")
            if not isinstance(blocker.get("message"), str) or not blocker.get("message"):
                errors.append(f"admission blocker {index} has no message")
        if audit.get("status") == "ready" and blockers:
            errors.append("ready admission contains blockers")
        if audit.get("status") == "blocked" and not blockers:
            errors.append("blocked admission has no blockers")
    if audit.get("status") == "ready" and audit.get("formal_admission") is not True:
        errors.append("ready admission is not formally admitted")
    if audit.get("status") == "blocked" and audit.get("formal_admission") is not False:
        errors.append("blocked admission is marked formally admitted")
    denominator = audit.get("production_denominator")
    if (not isinstance(denominator, Mapping)
            or denominator.get("failure_denominator_preserved") is not True):
        errors.append("admission production denominator is not failure-preserving")
    closure = audit.get("source_closure")
    if not isinstance(closure, Mapping):
        errors.append("admission source closure is missing")
    constraints = audit.get("execution_constraints")
    required_constraints = {
        "read_only": True,
        "formal_runs_started": 0,
        "gpu_started": False,
        "solver_started": False,
        "submitted": False,
        "central_registry_mutation": 0,
        "central_ledger_mutation": 0,
        "manifest_written": False,
        "formal_specs_written": False,
    }
    if not isinstance(constraints, Mapping):
        errors.append("admission execution constraints are missing")
    else:
        for key, expected in required_constraints.items():
            if constraints.get(key) != expected:
                errors.append(f"admission execution constraint {key} is not closed")
    return errors


def _source_closure_observation(
    source_closure: Mapping[str, Any], audit: Mapping[str, Any], *,
    root: Path, code_root: Path,
) -> dict[str, Any]:
    """Require a complete, current, and schema-valid source closure."""
    source = source_closure if isinstance(source_closure, Mapping) else {}
    audit_closure = audit.get("source_closure")
    audit_closure = audit_closure if isinstance(audit_closure, Mapping) else {}
    missing = source.get("missing_files")
    audit_missing = audit_closure.get("missing_files")
    declared_digest = source.get("closure_sha256")
    current_digest = audit_closure.get("current_closure_sha256")

    def closure_rows(value: Any) -> list[dict[str, Any]] | None:
        if not isinstance(value, list) or len(value) != len(REQUIRED_CODE_FILES):
            return None
        result: list[dict[str, Any]] = []
        for expected, row in zip(REQUIRED_CODE_FILES, value):
            if not isinstance(row, Mapping):
                return None
            if row.get("relative_path") != expected or not _valid_sha256(row.get("sha256")):
                return None
            if type(row.get("bytes")) is not int or row.get("bytes") < 0:
                return None
            result.append({
                "relative_path": expected,
                "sha256": row["sha256"],
                "bytes": row["bytes"],
            })
        return result

    declared_rows = closure_rows(source.get("files"))
    audit_rows = closure_rows(audit_closure.get("current_files"))
    current_rows: list[dict[str, Any]] | None = []
    try:
        for relative in REQUIRED_CODE_FILES:
            path = (code_root / relative).resolve()
            if not path.is_file():
                current_rows = None
                break
            current_rows.append({
                "relative_path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            })
    except (OSError, TypeError, ValueError):
        current_rows = None

    source_generator = source.get("generator")
    generator_ok = (
        isinstance(source_generator, Mapping)
        and source_generator.get("path") == _relative(Path(__file__), root)
        and _valid_sha256(source_generator.get("sha256"))
        and source_generator.get("sha256") == _digest_self()
    )
    computed_digest = (
        canonical_sha256([
            {"relative_path": row["relative_path"], "sha256": row["sha256"]}
            for row in declared_rows
        ])
        if declared_rows is not None else None
    )
    checks = {
        "closure_schema_valid": source.get("schema") == CLOSURE_SCHEMA,
        "closure_version_valid": source.get("closure_version") == GENERATOR_VERSION,
        "closure_hash_algorithm_valid": source.get("hash_algorithm") == "sha256",
        "closure_required_files_exact": source.get("required_files") == list(REQUIRED_CODE_FILES),
        "closure_complete": source.get("complete") is True,
        "closure_missing_files_empty": isinstance(missing, list) and not missing,
        "closure_file_rows_valid": declared_rows is not None,
        "closure_digest_valid": (
            _valid_sha256(declared_digest) and declared_digest == computed_digest
        ),
        "closure_generator_bound": generator_ok,
        "admission_closure_complete": (
            audit_closure.get("fresh_admission_closure_complete") is True
        ),
        "admission_required_files_exact": (
            audit_closure.get("required_files") == list(REQUIRED_CODE_FILES)
        ),
        "admission_missing_files_empty": isinstance(audit_missing, list) and not audit_missing,
        "admission_file_rows_match": (
            declared_rows is not None
            and declared_rows == audit_rows == current_rows
        ),
        "admission_digest_present": _valid_sha256(current_digest),
        "closure_digest_matches_admission": (
            _valid_sha256(declared_digest)
            and declared_digest == current_digest
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "declared_closure_sha256": declared_digest,
        "admission_current_closure_sha256": current_digest,
        "missing_files": list(missing) if isinstance(missing, list) else missing,
        "admission_missing_files": list(audit_missing) if isinstance(audit_missing, list) else audit_missing,
    }


def materialize_source_closure(*, root: Path, code_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in REQUIRED_CODE_FILES:
        path = (code_root / relative).resolve()
        if not path.is_file():
            missing.append(relative)
            continue
        files.append({
            "relative_path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    closure_sha256 = canonical_sha256([
        {"relative_path": item["relative_path"], "sha256": item["sha256"]}
        for item in files
    ])
    return {
        "schema": CLOSURE_SCHEMA,
        "closure_version": GENERATOR_VERSION,
        "hash_algorithm": "sha256",
        "required_files": list(REQUIRED_CODE_FILES),
        "files": files,
        "missing_files": missing,
        "closure_sha256": closure_sha256,
        "complete": not missing,
        "generator": {
            "path": _relative(Path(__file__), root),
            "sha256": _digest_self(),
        },
    }


def build_candidate(
    manifests: Sequence[str | Path | Mapping[str, Any]], *,
    evidence: Sequence[str | Path | Mapping[str, Any]],
    root: Path,
    code_root: Path,
    preprofile_index: str | Path | None,
    resource_profile: str | Path | None,
    resource_dryrun: str | Path | None,
    graph_probe: str | Path | None,
    capacity_evidence: str | Path | Mapping[str, Any] | None = None,
    source_closure: Mapping[str, Any],
    registry: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    code_root = Path(code_root).expanduser().resolve()
    try:
        raw_audit = audit_admission(
            manifests, data_root=root, evidence=evidence, code_root=code_root,
            preprofile_index=preprofile_index, resource_profile=resource_profile,
            resource_dryrun=resource_dryrun, graph_probe=graph_probe,
            capacity_evidence=capacity_evidence)
    except Exception as error:
        audit = _invalid_admission_observation(str(error))
        admission_contract_valid = False
    else:
        admission_errors = _validate_admission_observation(raw_audit)
        if admission_errors:
            audit = _invalid_admission_observation("; ".join(admission_errors))
            admission_contract_valid = False
        else:
            audit = dict(raw_audit)
            admission_contract_valid = True
    source_closure_payload = source_closure if isinstance(source_closure, Mapping) else {}
    blocker_codes = [item["code"] for item in audit["blockers"]]
    data_blocker_codes = sorted(set(blocker_codes) & DATA_BLOCKERS)
    source_closure_observation = _source_closure_observation(
        source_closure_payload, audit, root=root, code_root=code_root,
    )
    campaign = _campaign_completion_observation(root=root, registry=registry)
    if not source_closure_observation["passed"]:
        blocker_codes.append("SOURCE_CLOSURE_BINDING_GAP")
    if not admission_contract_valid:
        blocker_codes.append("ADMISSION_AUDIT_INVALID")
    if not campaign["valid"]:
        blocker_codes.append("CAMPAIGN_COMPLETION_INVALID")
    elif not campaign["can_finalize"]:
        blocker_codes.append("CAMPAIGN_COMPLETION_REQUIRED")
    blocker_codes = sorted(set(blocker_codes))
    data_blocker_codes = sorted(set(blocker_codes) & DATA_BLOCKERS)
    data_contract_ready = not data_blocker_codes and bool(
        source_closure_observation["passed"]
        and admission_contract_valid
        and audit["production_denominator"]["failure_denominator_preserved"]
    )
    formal_release = bool(
        admission_contract_valid
        and
        audit["status"] == "ready"
        and audit["formal_admission"] is True
        and not audit.get("blockers")
        and source_closure_observation["passed"]
        and campaign["valid"] is True
        and campaign["can_finalize"] is True
    )
    return {
        "schema": CANDIDATE_SCHEMA,
        "candidate_version": GENERATOR_VERSION,
        "record_id": "core-formal-release-candidate-f3-f4-v4-20260920",
        "status": "released" if formal_release else "blocked",
        "data_contract_ready": data_contract_ready,
        "formal_training_ready": formal_release,
        "formal_release": formal_release,
        "formal_release_requested": False,
        "formal_job_count": 0,
        "required_formal_job_count": audit["required_formal_job_count"],
        "diagnostic_runs_counted_as_formal": False,
        "admission_contract_valid": admission_contract_valid,
        "blocker_codes": blocker_codes,
        "data_blocker_codes": data_blocker_codes,
        "source_closure_contract": source_closure_observation,
        "campaign_completion": campaign,
        "campaign_completion_required_for_full_finalize": True,
        "source_closure": {
            "path": None,
            "sha256": None,
            "closure_sha256": source_closure_payload.get("closure_sha256"),
            "complete": source_closure_payload.get("complete"),
        },
        "manifest_bindings": audit["manifests"],
        "evidence_bindings": audit["evidence"],
        "admission_observation": {
            "family_summary": audit["family_summary"],
            "production_denominator": audit["production_denominator"],
            "resource_profile": audit["resource_profile"],
            "resource_dryrun": audit["resource_dryrun"],
            "graph_probe": audit["graph_probe"],
            "execution_constraints": audit["execution_constraints"],
        },
        "next_dependency": audit["admission_next_dependency"],
        "generator": {
            "path": _relative(Path(__file__), root),
            "sha256": _digest_self(),
        },
    }


def generate(
    manifests: Sequence[str | Path | Mapping[str, Any]], *,
    evidence: Sequence[str | Path | Mapping[str, Any]],
    data_root: str | Path,
    code_root: str | Path,
    output: str | Path,
    source_closure_output: str | Path,
    preprofile_index: str | Path | None = None,
    resource_profile: str | Path | None = None,
    resource_dryrun: str | Path | None = None,
    graph_probe: str | Path | None = None,
    capacity_evidence: str | Path | Mapping[str, Any] | None = None,
    registry: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    code = Path(code_root).expanduser().resolve()
    closure = materialize_source_closure(root=root, code_root=code)
    closure_path = Path(source_closure_output).expanduser().resolve()
    candidate_path = Path(output).expanduser().resolve()
    _immutable_json(closure_path, closure)
    candidate = build_candidate(
        manifests, evidence=evidence, root=root, code_root=code,
        preprofile_index=preprofile_index, resource_profile=resource_profile,
        resource_dryrun=resource_dryrun,
        graph_probe=graph_probe,
        capacity_evidence=capacity_evidence,
        registry=registry,
        source_closure=closure)
    candidate["source_closure"] = {
        "path": _relative(closure_path, root),
        "sha256": sha256_file(closure_path),
        "closure_sha256": closure["closure_sha256"],
        "complete": closure["complete"],
    }
    _immutable_json(candidate_path, candidate)
    return {
        "status": candidate["status"],
        "data_contract_ready": candidate["data_contract_ready"],
        "formal_training_ready": candidate["formal_training_ready"],
        "formal_release": candidate["formal_release"],
        "formal_job_count": candidate["formal_job_count"],
        "blocker_codes": candidate["blocker_codes"],
        "campaign_completion": candidate["campaign_completion"],
        "campaign_completion_required_for_full_finalize": candidate[
            "campaign_completion_required_for_full_finalize"],
        "source_closure": candidate["source_closure"],
        "output": _relative(candidate_path, root),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", required=True)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--preprofile-index", type=Path)
    parser.add_argument("--resource-profile", type=Path)
    parser.add_argument("--resource-dryrun", type=Path)
    parser.add_argument("--graph-probe", type=Path)
    parser.add_argument("--capacity-evidence", type=Path,
                        help="optional real 32000-update capacity adapter record")
    parser.add_argument("--registry", type=Path,
                        help="optional Core registry; defaults to campaigns/core-v1/registry.json")
    parser.add_argument("--source-closure-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = generate(
        args.manifest, evidence=args.evidence, data_root=args.data_root,
        code_root=args.code_root, output=args.output,
        source_closure_output=args.source_closure_output,
        preprofile_index=args.preprofile_index,
        resource_profile=args.resource_profile, resource_dryrun=args.resource_dryrun,
        graph_probe=args.graph_probe, capacity_evidence=args.capacity_evidence,
        registry=args.registry)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "released" else 2


if __name__ == "__main__":
    raise SystemExit(main())
