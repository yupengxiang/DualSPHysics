#!/usr/bin/env python3
"""Forward task-split request builder with strict nested evidence binding.

The consumed v1 audit remains unchanged.  The v1 request builder assumed
``payload["output"]`` and ``payload["receipt"]`` were strings, while actual
independent proofs store each as ``{"path": ..., "sha256": ...}``.  This
forward entry point accepts both representations, checks the declared digest,
and binds the exact nested file into a v8-compatible multi-family ``infra``
request.  Its run command delegates to the v1 metadata-only audit, so no H5,
BI4, raw trajectory, solver, or model input is opened.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
_V1_PATH = SCRIPT.with_name("ds_data02_stage2_task_split_audit_v1.py")
_SPEC = importlib.util.spec_from_file_location("_ds02_task_split_v1_for_v2", _V1_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load {_V1_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)


REQUEST_SCHEMA = "ds02.stage2.task-equivalence-split-request.v2-forward-001"
RUNTIME_FAMILY_ID = "infra"
FAMILIES = [f"F{i}" for i in range(1, 8)]


def _nested_binding(value: Any, sibling_sha: Any, label: str) -> tuple[Path, str]:
    """Normalize a legacy string or proof ``{path, sha256}`` object."""
    declared_sha = value.get("sha256") if isinstance(value, dict) else sibling_sha
    raw_path = value.get("path") if isinstance(value, dict) else value
    path = _BASE.require_file(raw_path, label)
    actual_sha = _BASE.sha256_file(path)
    if declared_sha is not None:
        if not isinstance(declared_sha, str) or len(declared_sha) != 64:
            raise _BASE.TaskSplitError(f"{label} lacks a valid SHA256")
        if actual_sha != declared_sha:
            raise _BASE.TaskSplitError(f"{label} digest differs")
    return path, actual_sha


def _nested_sources(evidence_manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Collect nested output/receipt/reference files with producer hashes."""
    nested: list[dict[str, str]] = []
    for item in evidence_manifest.get("evidence", []):
        if not isinstance(item, dict):
            raise _BASE.TaskSplitError("evidence entry is not an object")
        evidence_id = item.get("evidence_id")
        evidence_path = _BASE.require_file(item.get("path"), f"evidence {evidence_id}")
        _, payload = _BASE.read_json(evidence_path, f"evidence {evidence_id}")
        kind = item.get("kind")
        names = ("output", "receipt") if kind == "all118_impact_v8" else (
            ("request", "receipt", "report", "converter_report")
            if kind == "f1_raw_to_typed_proof" else ()
        )
        for name in names:
            value = payload.get(name)
            sibling_sha = payload.get(f"{name}_sha256")
            # Missing optional F1 fields retain v1 semantics.  If either a
            # path or digest is present, however, bind and validate both.
            if value is None and sibling_sha is None:
                continue
            path, actual_sha = _nested_binding(
                value, sibling_sha, f"evidence {evidence_id} {name}"
            )
            nested.append({
                "evidence_id": str(evidence_id),
                "role": name,
                "path": str(path),
                "sha256": actual_sha,
            })
    return nested


def make_request(current_path: Path | str, lineage_path: Path | str,
                 source_manifest_path: Path | str, evidence_manifest_path: Path | str,
                 output: Path | str, worktree_root: Path | str,
                 runtime_paths: Iterable[Path | str] | None = None,
                 worker_root: Path | str | None = None) -> dict[str, Any]:
    """Prepare a strict metadata-only request without opening trajectory data."""
    current_path, current = _BASE.read_json(current_path, "CURRENT336")
    lineage_path, _ = _BASE.read_json(lineage_path, "lineage-v19")
    source_manifest_path, _ = _BASE.read_json(source_manifest_path, "v22 source access index")
    evidence_manifest_path, evidence_manifest = _BASE.read_json(
        evidence_manifest_path, "task evidence manifest"
    )
    _BASE._BASE._rows(current)
    runtime_root = Path(worktree_root).expanduser().resolve()
    script_root = Path(worker_root).expanduser().resolve() if worker_root is not None else runtime_root
    worker = script_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_task_split_audit_v2.py"
    v1_worker = script_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_task_split_audit_v1.py"
    v0_worker = script_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_equivalence_split_audit_v1.py"
    if runtime_paths is None:
        runtime_paths = [
            runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
            runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
            runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
            runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        ]
    runtime_paths = [Path(path).expanduser().resolve() for path in runtime_paths]
    nested = _nested_sources(evidence_manifest)
    paths: list[Path] = [
        worker, v1_worker, v0_worker, current_path, lineage_path,
        source_manifest_path, evidence_manifest_path, *runtime_paths,
    ]
    for item in evidence_manifest.get("evidence", []):
        paths.append(_BASE.require_file(item.get("path"), f"evidence {item.get('evidence_id')}"))
    paths.extend(Path(item["path"]) for item in nested)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if str(resolved) not in seen:
            unique.append(resolved)
            seen.add(str(resolved))
    missing = [str(path) for path in unique if not path.is_file()]
    hashes = {str(path): _BASE.sha256_file(path) for path in unique if path.is_file()}
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": REQUEST_SCHEMA,
        "attempt_id": "current336-task-equivalence-split-v2-forward-001",
        "case_id": "DS02_STAGE2_CURRENT336_TASK_SCOPED_ELIGIBILITY_V2",
        "family_id": RUNTIME_FAMILY_ID,
        "dataset_families": FAMILIES,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(runtime_root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(runtime_root),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker), "run", "--current", str(current_path), "--lineage", str(lineage_path),
            "--source-index", str(source_manifest_path), "--evidence-manifest", str(evidence_manifest_path),
            "--output", "{attempt_root}/current336-task-equivalence-split-v2.json",
        ],
        "input_files": [str(path) for path in unique],
        "input_sha256": hashes,
        "launch_allowed": not missing,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {
            "small_json_bytes_read": sum(path.stat().st_size for path in unique if path.is_file()),
            "original_trajectory_h5_bytes_read": 0,
            "part_bi4_bytes_read": 0,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
        "nested_evidence_bindings": nested,
        "claim_boundary": {
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
            "split_safe": "UNKNOWN", "recovery_safe": "UNKNOWN",
            "qualification_credit": "none",
        },
        "missing_guard_sources": missing,
        "request_note": (
            "Task-scoped metadata/native-cause/source-role eligibility only; v1 global "
            "unresolved exclusions are preserved. Nested proof objects are bound by exact "
            "path and SHA; no H5/BI4/raw trajectory content is opened."
        ),
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise _BASE.TaskSplitError(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def run(current_path: Path | str, lineage_path: Path | str,
        source_manifest_path: Path | str, evidence_manifest_path: Path | str,
        output: Path | str) -> dict[str, Any]:
    """Run the immutable v1 metadata audit under the forward request."""
    result = _BASE.audit(current_path, lineage_path, source_manifest_path, evidence_manifest_path)
    _BASE.write_json(result, output)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--current", type=Path, required=True)
    run_parser.add_argument("--lineage", type=Path, required=True)
    run_parser.add_argument("--source-index", type=Path, required=True)
    run_parser.add_argument("--evidence-manifest", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    req_parser = sub.add_parser("make-request")
    req_parser.add_argument("--current", type=Path, required=True)
    req_parser.add_argument("--lineage", type=Path, required=True)
    req_parser.add_argument("--source-index", type=Path, required=True)
    req_parser.add_argument("--evidence-manifest", type=Path, required=True)
    req_parser.add_argument("--output", type=Path, required=True)
    req_parser.add_argument("--worktree-root", type=Path, required=True)
    req_parser.add_argument("--worker-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.current, args.lineage, args.source_index, args.evidence_manifest, args.output)
    else:
        make_request(args.current, args.lineage, args.source_index, args.evidence_manifest,
                     args.output, args.worktree_root, worker_root=args.worker_root)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
