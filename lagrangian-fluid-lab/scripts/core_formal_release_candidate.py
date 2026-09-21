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
    REQUIRED_CODE_FILES,
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


def _campaign_completion_observation(
    *, root: Path, registry: str | Path | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Read the central completion gate without mutating campaign state."""
    registry_path: Path | None = None
    if isinstance(registry, Mapping):
        payload: Mapping[str, Any] | None = dict(registry)
        reference = {
            "path": "<in-memory>",
            "sha256": canonical_sha256(payload),
            "bytes": len(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")),
        }
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
            return {
                "bound": False,
                "valid": False,
                "can_finalize": False,
                "registry": reference,
                "error": str(error),
            }

    try:
        status = campaign_completion(payload, root)
    except (OSError, TypeError, ValueError, KeyError) as error:
        return {
            "bound": True,
            "valid": False,
            "can_finalize": False,
            "registry": reference,
            "error": str(error),
        }
    valid = bool(
        isinstance(status, Mapping)
        and status.get("schema") == "core.completion.v1"
        and isinstance(status.get("can_finalize"), bool)
        and isinstance(status.get("checks"), Mapping)
    )
    return {
        "bound": True,
        "valid": valid,
        "can_finalize": bool(status.get("can_finalize")) if valid else False,
        "registry": reference,
        "checks": dict(status.get("checks", {})) if isinstance(status, Mapping) else {},
        "t1_families": list(status.get("t1_families", ())) if isinstance(status, Mapping) else [],
        "macro_t2_families": list(status.get("macro_t2_families", ())) if isinstance(status, Mapping) else [],
        "training_runs": list(status.get("training_runs", ())) if isinstance(status, Mapping) else [],
        "missing_t1_case_runs": status.get("missing_t1_case_runs") if isinstance(status, Mapping) else None,
        "missing_material_case_runs": status.get("missing_material_case_runs") if isinstance(status, Mapping) else None,
        "issues": list(status.get("issues", ())) if isinstance(status, Mapping) else [],
    }


def _source_closure_observation(
    source_closure: Mapping[str, Any], audit: Mapping[str, Any],
) -> dict[str, Any]:
    """Require the generated closure and admission audit to bind one digest."""
    if not isinstance(source_closure, Mapping):
        source_closure = {}
    audit_closure = audit.get("source_closure")
    audit_closure = audit_closure if isinstance(audit_closure, Mapping) else {}
    missing = source_closure.get("missing_files")
    audit_missing = audit_closure.get("missing_files")
    declared_digest = source_closure.get("closure_sha256")
    current_digest = audit_closure.get("current_closure_sha256")
    checks = {
        "closure_complete": source_closure.get("complete") is True,
        "closure_missing_files_empty": isinstance(missing, list) and not missing,
        "admission_closure_complete": (
            audit_closure.get("fresh_admission_closure_complete") is True
        ),
        "admission_missing_files_empty": isinstance(audit_missing, list) and not audit_missing,
        "closure_digest_present": isinstance(declared_digest, str) and bool(declared_digest),
        "admission_digest_present": isinstance(current_digest, str) and bool(current_digest),
        "closure_digest_matches_admission": (
            isinstance(declared_digest, str)
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
    audit = audit_admission(
        manifests, data_root=root, evidence=evidence, code_root=code_root,
        preprofile_index=preprofile_index, resource_profile=resource_profile,
        resource_dryrun=resource_dryrun, graph_probe=graph_probe,
        capacity_evidence=capacity_evidence)
    source_closure_payload = source_closure if isinstance(source_closure, Mapping) else {}
    blocker_codes = [item["code"] for item in audit["blockers"]]
    data_blocker_codes = sorted(set(blocker_codes) & DATA_BLOCKERS)
    source_closure_observation = _source_closure_observation(source_closure_payload, audit)
    campaign = _campaign_completion_observation(root=root, registry=registry)
    if not source_closure_observation["passed"]:
        blocker_codes.append("SOURCE_CLOSURE_BINDING_GAP")
    blocker_codes = sorted(set(blocker_codes))
    data_blocker_codes = sorted(set(blocker_codes) & DATA_BLOCKERS)
    data_contract_ready = not data_blocker_codes and bool(
        source_closure_observation["passed"]
        and audit["production_denominator"]["failure_denominator_preserved"]
    )
    formal_release = bool(
        audit["status"] == "ready"
        and audit["formal_admission"] is True
        and not audit.get("blockers")
        and source_closure_observation["passed"]
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
