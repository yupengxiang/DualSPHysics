#!/usr/bin/env python3
"""Derive cache-rebound F3 decisions and scope metadata from a Root receipt.

This metadata-only binder runs after the Root-only copy worker and strict audit.
It preserves every original decision field and schema, replacing only paths
whose bytes were proven by the completed receipt.  Original provenance is kept
under ``source_absolute_path`` fields; this binder never hashes or decodes an
original H5/GIF/native artifact.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SCOPE = "F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1"


class DeriveError(RuntimeError):
    pass


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def rewrite_paths(value: Any, mapping: Mapping[str, Mapping[str, Any]], rewrites: list[dict[str, Any]]) -> Any:
    if isinstance(value, Mapping):
        result = {key: rewrite_paths(child, mapping, rewrites) for key, child in value.items()}
        path_value = value.get("path")
        sha_value = value.get("sha256")
        if isinstance(path_value, str) and isinstance(sha_value, str) and path_value in mapping:
            proof = mapping[path_value]
            if sha_value.lower() != str(proof["expected_sha256"]).lower():
                raise DeriveError(f"binding digest mismatch while rebinding {path_value}")
            result["path"] = str(proof["cache_absolute_path"])
            result["source_absolute_path"] = path_value
            result["source_sha256"] = sha_value
            result["cache_sha256"] = proof["cache_sha256_actual"]
            rewrites.append(
                {
                    "source_absolute_path": path_value,
                    "source_sha256": sha_value,
                    "cache_absolute_path": proof["cache_absolute_path"],
                    "cache_sha256": proof["cache_sha256_actual"],
                }
            )
        return result
    if isinstance(value, list):
        return [rewrite_paths(child, mapping, rewrites) for child in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-index", required=True)
    parser.add_argument("--scope-id", default=DEFAULT_SCOPE)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    try:
        candidate_path = Path(args.candidate_index).resolve()
        receipt_path = Path(args.receipt).resolve()
        candidate = load(candidate_path)
        receipt = load(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise DeriveError("cannot derive from a failed/incomplete replica receipt")
        if receipt.get("scope_id") != args.scope_id:
            raise DeriveError("receipt scope mismatch")
        selected = {}
        for artifact in receipt.get("artifacts", []):
            source = artifact.get("source_absolute_path")
            if artifact.get("selected_for_cache") and artifact.get("cache_actual") is True:
                if not isinstance(source, str) or not Path(str(artifact["cache_absolute_path"])).is_file():
                    raise DeriveError(f"receipt cache artifact is missing: {source}")
                selected[source] = {
                    "expected_sha256": artifact["expected_sha256"],
                    "cache_absolute_path": artifact["cache_absolute_path"],
                    "cache_sha256_actual": artifact["cache_sha256_actual"],
                }
        if not selected:
            raise DeriveError("receipt has no proven large artifact mapping")
        scopes = candidate.get("scopes", [])
        matches = [scope for scope in scopes if isinstance(scope, Mapping) and scope.get("scope_id") == args.scope_id]
        if len(matches) != 1:
            raise DeriveError("candidate-index scope is missing")
        original_scope = copy.deepcopy(matches[0])
        derived_scope = copy.deepcopy(original_scope)
        derived_dir = output_dir / "derived-decisions"
        derived_dir.mkdir(parents=True, exist_ok=True)
        derived_decision_refs: list[dict[str, Any]] = []
        observed = derived_scope.get("visual_evidence", {}).get("observed", [])
        original_observed = original_scope.get("visual_evidence", {}).get("observed", [])
        if len(observed) != len(original_observed):
            raise DeriveError("scope observed list changed while deriving")
        for index, original_entry in enumerate(original_observed):
            original_decision = Path(str(original_entry["decision"]["path"])).resolve()
            expected_decision_sha = str(original_entry["decision"]["sha256"]).lower()
            actual_decision_sha = sha256_file(original_decision)
            if actual_decision_sha != expected_decision_sha:
                raise DeriveError(f"case decision digest changed: {original_decision}")
            decision = load(original_decision)
            rewrites: list[dict[str, Any]] = []
            derived_decision = rewrite_paths(decision, selected, rewrites)
            derived_decision["derived_visual_replica"] = {
                "mode": "byte_identity_cache_rebound",
                "source_case_decision": {
                    "source_absolute_path": str(original_decision),
                    "source_sha256": actual_decision_sha,
                },
                "copy_receipt": {
                    "source_absolute_path": str(receipt_path),
                    "source_sha256": sha256_file(receipt_path),
                },
                "rewritten_large_artifact_bindings": rewrites,
                "independent_physical_case_count_increment": 0,
                "q_n": "not_granted",
                "production_approval": "none",
            }
            derived_path = derived_dir / f"{original_entry['case_id']}.json"
            atomic_json(derived_path, derived_decision)
            derived_sha = sha256_file(derived_path)
            derived_scope["visual_evidence"]["observed"][index] = rewrite_paths(derived_scope["visual_evidence"]["observed"][index], selected, [])
            derived_scope["visual_evidence"]["observed"][index]["decision"] = {
                "path": str(derived_path),
                "sha256": derived_sha,
                "source_absolute_path": str(original_decision),
                "source_sha256": actual_decision_sha,
            }
            derived_decision_refs.append(
                {
                    "case_id": original_entry["case_id"],
                    "source_absolute_path": str(original_decision),
                    "source_sha256": actual_decision_sha,
                    "derived_decision_absolute_path": str(derived_path),
                    "derived_decision_sha256": derived_sha,
                    "rewritten_large_artifact_count": len(rewrites),
                }
            )
        provenance = {
            "schema": "ds02.f3.visual-nvme-replica-opaque-provenance.v1",
            "scope_id": args.scope_id,
            "candidate_index": {
                "source_absolute_path": str(candidate_path),
                "source_sha256": sha256_file(candidate_path),
            },
            "copy_receipt": {
                "source_absolute_path": str(receipt_path),
                "source_sha256": sha256_file(receipt_path),
            },
            "derived_decisions": derived_decision_refs,
            "cache_root": receipt["cache_policy"]["root"],
            "byte_identity": "Only receipt-proven large artifact bindings were rebound; all source decision values and schemas are retained.",
            "independent_physical_case_count_increment": 0,
            "q_n": "not_granted",
            "production_approval": "none",
        }
        atomic_json(output_dir / "opaque-provenance.json", provenance)
        derived_scope["derived_visual_replica"] = {
            "mode": "byte_identity_cache_rebound",
            "source_scope_entry": {
                "source_absolute_path": str(candidate_path),
                "source_sha256": sha256_file(candidate_path),
                "scope_id": args.scope_id,
            },
            "copy_receipt": {
                "source_absolute_path": str(receipt_path),
                "source_sha256": sha256_file(receipt_path),
            },
            "decision_references": derived_decision_refs,
            "independent_physical_case_count_increment": 0,
            "q_n": "not_granted",
            "production_approval": "none",
        }
        atomic_json(output_dir / "derived-scope-entry.json", derived_scope)
        derived_candidate = copy.deepcopy(candidate)
        for index, scope in enumerate(derived_candidate.get("scopes", [])):
            if isinstance(scope, Mapping) and scope.get("scope_id") == args.scope_id:
                derived_candidate["scopes"][index] = derived_scope
                break
        derived_candidate["derived_visual_replica"] = {
            "mode": "byte_identity_cache_rebound",
            "source_candidate_index": {
                "source_absolute_path": str(candidate_path),
                "source_sha256": sha256_file(candidate_path),
            },
            "copy_receipt": {
                "source_absolute_path": str(receipt_path),
                "source_sha256": sha256_file(receipt_path),
            },
            "scope_id": args.scope_id,
            "independent_physical_case_count_increment": 0,
            "q_n": "not_granted",
            "production_approval": "none",
        }
        atomic_json(output_dir / "derived-candidate-index.json", derived_candidate)
        result = {
            "schema": "ds02.f3.visual-nvme-derived-scope-result.v1",
            "status": "completed",
            "scope_id": args.scope_id,
            "derived_scope_entry": str(output_dir / "derived-scope-entry.json"),
            "derived_candidate_index": str(output_dir / "derived-candidate-index.json"),
            "opaque_provenance": str(output_dir / "opaque-provenance.json"),
            "derived_decisions": derived_decision_refs,
            "source_files_modified": False,
            "raw_arrays_read": False,
            "h5_datasets_decoded": False,
            "independent_physical_case_count_increment": 0,
            "q_n": "not_granted",
            "production_approval": "none",
        }
        atomic_json(output_dir / "derive-result.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = {"schema": "ds02.f3.visual-nvme-derived-scope-result.v1", "status": "failed", "scope_id": args.scope_id, "failure": {"type": type(exc).__name__, "message": str(exc)}, "source_files_modified": False, "independent_physical_case_count_increment": 0, "q_n": "not_granted", "production_approval": "none"}
        atomic_json(output_dir / "derive-result.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
