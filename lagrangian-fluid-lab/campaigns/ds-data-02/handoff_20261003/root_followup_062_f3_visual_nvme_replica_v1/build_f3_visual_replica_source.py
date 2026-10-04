#!/usr/bin/env python3
"""Build the disabled Root113 F3 visual-replica source package.

This builder reads only the candidate index and small case-decision JSON.  It
uses stat metadata to identify eligible artifacts and never hashes or reads an
H5/GIF/native blob.  Root runs the replica worker later.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
INFRA_ROOT = HERE.parents[4]
INFRA_LAB = INFRA_ROOT / "lagrangian-fluid-lab"
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION_ROOT / "lagrangian-fluid-lab"
CAMPAIGN = INTEGRATION_LAB / "campaigns/ds-data-02"
CANDIDATE_INDEX = CAMPAIGN / "handoff_20261003/root_stage1_f3_first24_actual_production_scope_113/candidate-index.json"
GOAL = CAMPAIGN / "GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
STRICT = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
SCOPE_ID = "F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1"
CACHE_ROOT = Path("/tmp/ds02-visual-evidence-cache")
RECEIPT = CACHE_ROOT / "receipts/F3_STAGE1_FIRST24_AY0250_AY0750.replica-receipt.json"
MIN_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_CACHE_BYTES = 24 * 1024**3
MIN_FREE_BYTES = 100 * 1024**3
LARGE_SUFFIXES = {".h5", ".hdf5", ".gif", ".bi4", ".bin", ".dat", ".raw", ".blob", ".vtk", ".vtu"}
MAX_JSON_BYTES = 64 * 1024 * 1024


class BuildError(ValueError):
    pass


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read JSON source: {path}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise BuildError(f"missing source file: {path}")
    return {"source_absolute_path": str(path), "source_sha256": sha256_file(path)}


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_pairs(value: Any, trail: str = "") -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            pairs.append((str(value["path"]), str(value["sha256"]), trail or "/"))
        for key, child in value.items():
            pairs.extend(collect_pairs(child, f"{trail}/{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            pairs.extend(collect_pairs(child, f"{trail}/{index}"))
    return pairs


def discover(scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    observed = scope.get("visual_evidence", {}).get("observed", [])
    records: dict[tuple[str, str], dict[str, Any]] = {}
    queue: list[tuple[Path, str, str]] = []
    visited: set[Path] = set()

    def add(path_value: str, expected: str, trail: str, case_id: str, kind: str) -> None:
        path = Path(path_value).resolve()
        if not path.is_absolute() or not path.exists() or not path.is_file():
            raise BuildError(f"source binding missing: {path}")
        key = (str(path), expected.lower())
        record = records.setdefault(key, {"source_absolute_path": str(path), "expected_sha256": expected.lower(), "binding_locations": [], "case_ids": [], "source_kinds": []})
        record["binding_locations"].append(trail)
        if case_id not in record["case_ids"]:
            record["case_ids"].append(case_id)
        if kind not in record["source_kinds"]:
            record["source_kinds"].append(kind)
        if path.suffix.lower() == ".json" and path not in visited:
            if path.stat().st_size > MAX_JSON_BYTES:
                raise BuildError(f"metadata JSON exceeds safe limit: {path}")
            queue.append((path, case_id, kind))

    for entry in observed:
        case_id = str(entry["case_id"])
        for name in ("decision", "integrity_report", "full_saved_animation"):
            reference = entry[name]
            add(str(reference["path"]), str(reference["sha256"]), f"/visual_evidence/observed/{case_id}/{name}", case_id, f"scope.{name}")
    while queue:
        path, case_id, kind = queue.pop()
        if path in visited:
            continue
        visited.add(path)
        document = load(path)
        for path_value, expected, trail in collect_pairs(document):
            add(path_value, expected, f"{path}{trail}", case_id, f"nested:{kind}")
    return list(records.values())


def main() -> None:
    candidate = load(CANDIDATE_INDEX)
    scopes = candidate.get("scopes", [])
    matches = [scope for scope in scopes if isinstance(scope, Mapping) and scope.get("scope_id") == SCOPE_ID]
    if len(matches) != 1:
        raise BuildError(f"candidate-index must contain exactly one {SCOPE_ID}")
    scope = matches[0]
    observed = scope.get("visual_evidence", {}).get("observed", [])
    if len(observed) != 3:
        raise BuildError("Root113 F3 scope must retain exactly three observed entries")
    records = discover(scope)
    artifacts = []
    for record in records:
        source = Path(record["source_absolute_path"])
        size = int(source.stat().st_size)
        suffix = source.suffix.lower()
        selected = suffix in LARGE_SUFFIXES and size >= MIN_ARTIFACT_BYTES
        artifacts.append(
            {
                "source_absolute_path": record["source_absolute_path"],
                "expected_sha256": record["expected_sha256"],
                "source_size_bytes": size,
                "source_suffix": suffix,
                "selected_for_cache": selected,
                "selection_reason": "large_visual_artifact" if selected else ("below_64MiB_threshold" if suffix in LARGE_SUFFIXES else "suffix_not_H5_GIF_or_native_blob"),
                "cache_absolute_path": None,
                "cache_sha256_actual": None,
                "cache_actual": False,
                "copy_status": "not_run",
                "binding_locations": record["binding_locations"],
                "case_ids": record["case_ids"],
                "source_kinds": record["source_kinds"],
            }
        )
    cases = []
    for entry in observed:
        decision = load(Path(str(entry["decision"]["path"])))
        cases.append(
            {
                "case_id": entry["case_id"],
                "status": entry["status"],
                "decision": {
                    "source_absolute_path": str(Path(str(entry["decision"]["path"])).resolve()),
                    "expected_sha256": entry["decision"]["sha256"],
                },
                "physical_case_id": decision.get("physical_case_id"),
                "physical_condition_sha256": decision.get("physical_condition_sha256"),
                "frames": decision.get("frames"),
                "numerical_precision_status": decision.get("numerical_precision_status"),
                "q_n": decision.get("q_n"),
            }
        )
    plan = {
        "schema": "ds02.f3.visual-nvme-replica-plan.v1",
        "status": "source_only_not_run",
        "family_id": "F3",
        "scope_id": SCOPE_ID,
        "candidate_index": binding(CANDIDATE_INDEX),
        "observed_cases": cases,
        "artifact_discovery": {
            "recursive_case_decision_bindings": True,
            "source_paths_are_opaque": "source_absolute_path",
            "large_artifact_threshold_bytes": MIN_ARTIFACT_BYTES,
            "h5_gif_native_blob_suffixes": sorted(LARGE_SUFFIXES),
            "arrays_read": False,
            "h5_datasets_decoded": False,
        },
        "cache_policy": {
            "root": str(CACHE_ROOT),
            "min_artifact_bytes": MIN_ARTIFACT_BYTES,
            "max_cache_bytes": MAX_CACHE_BYTES,
            "min_free_bytes": MIN_FREE_BYTES,
            "existing_cache_must_rehash": True,
            "source_stat_before_after_must_match": True,
            "atomic_publish_after_digest_match_only": True,
        },
        "artifacts": artifacts,
        "copy_receipt": {
            "source_absolute_path": str(RECEIPT),
            "status": "not_generated",
            "cache_actual": False,
            "sha256": None,
        },
        "independent_physical_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
        "source_files_modified": False,
    }
    save(HERE / "replica-plan.json", plan)
    replica_command = {
        "schema": "ds02.f3.visual-nvme-replica-command.v1",
        "launch_owner": "Root only",
        "launch_allowed": False,
        "command": [
            "/usr/bin/python3.10",
            str((HERE / "replicate_visual_evidence.py").resolve()),
            "--candidate-index",
            str(CANDIDATE_INDEX.resolve()),
            "--scope-id",
            SCOPE_ID,
            "--cache-root",
            str(CACHE_ROOT),
            "--receipt",
            str(RECEIPT),
        ],
        "source_only": True,
        "execution_allowed": False,
        "independent_physical_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
    }
    save(HERE / "replica-command.json", replica_command)
    input_paths = [
        Path("/usr/bin/python3.10"),
        HERE / "replicate_visual_evidence.py",
        HERE / "audit_visual_replica.py",
        HERE / "derive_visual_scope.py",
        HERE / "replica-plan.json",
        CANDIDATE_INDEX,
        GOAL,
        STRICT,
        RUNTIME,
    ]
    # Bind the actual Root visual-decision JSON inputs explicitly in the
    # disabled audit request; no large artifact is hashed by this builder.
    input_paths.extend(Path(str(entry["decision"]["path"])) for entry in observed)
    input_paths = [path.resolve() for path in input_paths]
    input_files = [str(path) for path in input_paths]
    input_sha256 = {str(path): sha256_file(path) for path in input_paths}
    audit_request = {
        "schema": "ds02.runner.request.v2",
        "family_id": "F3",
        "case_id": "F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_REPLICA",
        "attempt_id": "root-stage1-f3-visual-nvme-replica-strict-cpu-audit-062-pending",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "model_profile": "gpt-5.6-luna/max",
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": 134217728,
        "cwd": str(INFRA_LAB),
        "worktree_root": str(INFRA_ROOT),
        "command": [
            "/usr/bin/python3.10",
            str((HERE / "audit_visual_replica.py").resolve()),
            "--receipt",
            str(RECEIPT),
            "--candidate-index",
            str(CANDIDATE_INDEX.resolve()),
            "--scope-id",
            SCOPE_ID,
            "--output",
            "{attempt_root}/strict-cpu-audit.json",
        ],
        "input_files": input_files,
        "input_sha256": input_sha256,
        "input_hashes": dict(input_sha256),
        "future_input_files": [str(RECEIPT)],
        "future_input_sha256": None,
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "source_immutability": True,
        "launch_owner": "Root only after the byte-copy receipt is completed and reviewed",
        "production_approval": "none",
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "numerical_precision_status": "not_accepted",
        "request_status": "disabled_pending_root_visual_replica_receipt",
        "scope_source": binding(CANDIDATE_INDEX),
        "worker_contract": {
            "rechecks_cache_digest_on_NVMe": True,
            "does_not_read_original_H5_dataset": True,
            "does_not_decode_arrays": True,
            "does_not_modify_originals": True,
            "requires_free_floor_bytes": MIN_FREE_BYTES,
            "requires_peak_cache_limit_bytes": MAX_CACHE_BYTES,
        },
        "required_output_contract": {
            "schema": "ds02.f3.visual-nvme-replica-strict-cpu-audit.v1",
            "status": "completed",
            "returncode": 0,
            "independent_physical_case_count_increment": 0,
            "raw_arrays_read": False,
            "derived_decisions_published": False,
        },
    }
    request_path = HERE / "requests/F3_STAGE1_FIRST24_VISUAL_REPLICA_STRICT_CPU_AUDIT_REQUEST.json"
    save(request_path, audit_request)
    readme = HERE / "README.md"
    readme.write_text(
        """# F3 Root113 visual NVMe replica source handoff (fresh062)

This package prepares a Root-only byte-preserving replica workflow for the
three observed entries in `F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1`. The
worker recursively discovers `path`/`sha256` bindings inside the original case
decision JSON, records opaque originals as `source_absolute_path`, and selects
only H5/GIF/native blob files at least 64 MiB. It streams each selected source
once into `/tmp/ds02-visual-evidence-cache/SHA.ext`, verifies the frozen digest while
copying, checks source stat before/after, rehashes existing cache files, and
publishes with an atomic rename. It enforces a 24 GiB cache peak and 100 GiB
free-space floor.

The package has performed no byte copy, H5 hash, decode, solver run, GPU run,
or source mutation. `replicate_visual_evidence.py` must be run only by Root.
The disabled CPU audit request then rehashes the NVMe copies without opening
the original H5 datasets. `derive_visual_scope.py` can run only after a
completed receipt and creates schema-preserving derived decisions plus a
derived scope/candidate index; it changes only proven cache paths and keeps
all physical IDs, observed results, precision labels, and case counts intact.
""",
        encoding="utf-8",
    )
    manifest = {
        "schema": "ds02.f3.visual-nvme-replica-source-handoff.v1",
        "handoff_id": "root_followup_062_f3_visual_nvme_replica_v1",
        "family_id": "F3",
        "scope_id": SCOPE_ID,
        "status": "source_only_worker_and_disabled_audit_request",
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "byte_copy_performed": False,
        "large_artifact_hash_performed": False,
        "arrays_read": False,
        "h5_datasets_decoded": False,
        "source_files_modified": False,
        "independent_physical_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
        "candidate_index": binding(CANDIDATE_INDEX),
        "plan": binding(HERE / "replica-plan.json"),
        "replica_worker": binding(HERE / "replicate_visual_evidence.py"),
        "strict_audit_worker": binding(HERE / "audit_visual_replica.py"),
        "derived_scope_binder": binding(HERE / "derive_visual_scope.py"),
        "replica_command": binding(HERE / "replica-command.json"),
        "strict_audit_request": binding(request_path),
        "cache_policy": plan["cache_policy"],
        "observed_case_ids": [entry["case_id"] for entry in cases],
        "next_step": "Root runs replica command, reviews completed receipt, enables strict CPU audit, then runs metadata binder.",
        "builder": binding(HERE / "build_f3_visual_replica_source.py"),
    }
    save(HERE / "manifest.json", manifest)
    print(json.dumps({"package": str(HERE), "observed_cases": len(cases), "artifact_bindings": len(artifacts), "eligible_large_artifacts": sum(1 for row in artifacts if row["selected_for_cache"]), "status": manifest["status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
