#!/usr/bin/env python3
"""Materialize a versioned, non-authorizing formal release candidate.

This is the boundary between an auditable source closure and a future formal
release.  It snapshots the current learning code hashes, runs the read-only
admission audit, and writes a candidate record that can only report
``formal_release=true`` when the audit itself is ready.  It never edits a
reader manifest, upgrades ``formal_release``, starts a training job, or writes
registry/ledger state.
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
) -> dict[str, Any]:
    audit = audit_admission(
        manifests, data_root=root, evidence=evidence, code_root=code_root,
        preprofile_index=preprofile_index, resource_profile=resource_profile,
        resource_dryrun=resource_dryrun, graph_probe=graph_probe,
        capacity_evidence=capacity_evidence)
    blocker_codes = [item["code"] for item in audit["blockers"]]
    data_blocker_codes = sorted(set(blocker_codes) & DATA_BLOCKERS)
    data_contract_ready = not data_blocker_codes and bool(
        source_closure.get("complete")
        and audit["production_denominator"]["failure_denominator_preserved"]
    )
    formal_release = bool(audit["status"] == "ready" and audit["formal_admission"])
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
        "source_closure": {
            "path": None,
            "sha256": None,
            "closure_sha256": source_closure.get("closure_sha256"),
            "complete": source_closure.get("complete"),
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
        graph_probe=args.graph_probe, capacity_evidence=args.capacity_evidence)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "released" else 2


if __name__ == "__main__":
    raise SystemExit(main())
