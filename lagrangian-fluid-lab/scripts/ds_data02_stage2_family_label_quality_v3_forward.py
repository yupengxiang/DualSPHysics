#!/usr/bin/env python3
"""Forward F1--F5 source-role quality request for completed label products.

The consumed v3 worker remains immutable.  This entry point reuses its strict
artifact validator and audit implementation, while making the request
identity and source closure accurate for a multi-family materialized-label
audit.  It never opens an original trajectory H5, BI4, or starts a solver.

The runtime family identity is ``infra`` because runtime v8 accepts one
dataset family or ``infra`` for a cross-family metadata/audit job.  The exact
families and physical cases remain explicit in ``dataset_families`` and
``entries``; ``infra`` does not grant any physical or split qualification.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
_V3_PATH = SCRIPT.with_name("ds_data02_stage2_family_label_quality_v3.py")
_SPEC = importlib.util.spec_from_file_location("_ds02_family_label_quality_v3_forward_base", _V3_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import failure is environment-specific
    raise RuntimeError(f"cannot load {_V3_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)


REQUEST_SCHEMA = "ds02.stage2.family-label-quality-request.v3-forward-001"
RUNTIME_FAMILY_ID = "infra"

sha256_file = _BASE.sha256_file
read_json = _BASE.read_json
require_file = _BASE.require_file


def make_manifest(entries: Iterable[dict[str, Any]], output: Path | str) -> dict[str, Any]:
    """Create a v3 manifest using the immutable v3 policy validator."""
    return _BASE.make_manifest(entries, output)


def _report_current_path(report_path: Path) -> Path:
    report = read_json(report_path, "family label report")[1]
    if report.get("schema") == _BASE._BASE.RECOVERY_REPORT_SCHEMA:
        contract = report.get("source_contract")
        current = contract.get("current", {}).get("path") if isinstance(contract, dict) else None
    else:
        source_join = report.get("source_join")
        bindings = source_join.get("source_bindings") if isinstance(source_join, dict) else None
        current = bindings.get("current_manifest", {}).get("path") if isinstance(bindings, dict) else None
    return require_file(current, f"CURRENT source binding for {report_path}")


def _request_identity(entries: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    """Return runtime-safe identity plus exact dataset family scope."""
    families = sorted({str(entry["family_id"]) for entry in entries})
    if not families:
        raise ValueError("quality request has no family entries")
    # Runtime v8 rejects values such as F1_F2_F3.  Keep the cross-family
    # scope explicit in metadata while using its supported infra namespace.
    runtime_family = families[0] if len(families) == 1 else RUNTIME_FAMILY_ID
    family_suffix = "_".join(families)
    return runtime_family, f"DS02_STAGE2_FAMILY_LABEL_QUALITY_V3_{family_suffix}", families


def _attempt_id(families: list[str]) -> str:
    """Make the attempt identity reflect the exact family scope."""
    return "family-label-quality-v3-" + "-".join(f.lower() for f in families) + "-forward-002"


def _source_inputs(runtime_root: Path, worker_root: Path | None = None) -> list[Path]:
    worker_root = runtime_root if worker_root is None else worker_root
    return [
        worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_v3_forward.py",
        worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_v3.py",
        worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_v2.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
    ]


def make_request(manifest_path: Path | str, output: Path | str,
                 worktree_root: Path | str,
                 worker_root: Path | str | None = None) -> dict[str, Any]:
    """Prepare a strict, source-bound CPU request without reading source H5s."""
    manifest_path, manifest = read_json(manifest_path, "family label quality v3 forward manifest")
    entries = _BASE._validate_manifest_payload(manifest, check_paths=True, verify_artifacts=False)
    root = Path(worktree_root).expanduser().resolve()
    script_root = Path(worker_root).expanduser().resolve() if worker_root is not None else root
    source_inputs = _source_inputs(root, script_root)
    for path in source_inputs:
        require_file(str(path), "quality v3 forward source")

    inputs: list[Path] = [manifest_path, *source_inputs]
    current_paths: set[Path] = set()
    producer_receipts: list[dict[str, str]] = []
    for entry in entries:
        report_path = Path(entry["report"]).resolve()
        labels_path = Path(entry["labels_h5"]).resolve()
        inputs.extend([report_path, labels_path])
        current_paths.add(_report_current_path(report_path))

        # A receipt is an optional additive manifest field.  When supplied,
        # bind it as an input; the immutable report/H5 identity checks remain
        # authoritative and this does not retrofit trust into old products.
        raw_entry = next(
            item for item in manifest["entries"]
            if item.get("entry_key", item.get("physical_case_id")) == entry["entry_key"]
        )
        receipt_raw = raw_entry.get("producer_receipt")
        if receipt_raw is not None:
            receipt = require_file(receipt_raw, f"producer receipt for {entry['entry_key']}")
            receipt_sha = sha256_file(receipt)
            declared_receipt_sha = raw_entry.get("producer_receipt_sha256")
            if declared_receipt_sha is not None and declared_receipt_sha != receipt_sha:
                raise ValueError(f"producer receipt digest differs: {receipt}")
            inputs.append(receipt)
            producer_receipts.append({
                "entry_key": entry["entry_key"],
                "path": str(receipt),
                "sha256": receipt_sha,
            })

    inputs.extend(sorted(current_paths))
    unique_inputs: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        resolved = Path(path).expanduser().resolve()
        if str(resolved) not in seen:
            unique_inputs.append(resolved)
            seen.add(str(resolved))

    input_hashes: dict[str, str] = {}
    label_paths = {Path(entry["labels_h5"]).resolve(): entry["labels_h5_sha256"] for entry in entries}
    for path in unique_inputs:
        if path in label_paths:
            expected = label_paths[path]
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError(f"label H5 lacks a producer digest: {path}")
            # The worker/guard rechecks the declared materialized H5 digest;
            # preparation deliberately avoids a second large-file hash pass.
            input_hashes[str(path)] = expected
        else:
            input_hashes[str(path)] = sha256_file(path)

    runtime_family, case_id, families = _request_identity(entries)
    worker = script_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_v3_forward.py"
    label_bytes = sum(Path(entry["labels_h5"]).stat().st_size for entry in entries)
    role_counts = {
        role: sum(entry["source_role"] == role for entry in entries)
        for role in sorted(_BASE.SOURCE_ROLES)
    }
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": REQUEST_SCHEMA,
        "attempt_id": _attempt_id(families),
        "case_id": case_id,
        "family_id": runtime_family,
        "dataset_families": families,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 128 * 1024 * 1024,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(root),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker), "run", "--manifest", str(manifest_path),
            "--output", "{attempt_root}/family-label-quality-v3-" + "-".join(f.lower() for f in families) + ".json",
        ],
        "input_files": [str(path) for path in unique_inputs],
        "input_sha256": input_hashes,
        "launch_allowed": True,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {
            "materialized_label_h5_bytes_read": label_bytes,
            "original_trajectory_h5_bytes_read": 0,
            "part_bi4_bytes_read": 0,
            "solver_started": False,
            "cfd_or_model_run": False,
            "h5_prepare_hash_deferred_to_guard": True,
        },
        "source_roles": role_counts,
        "entries": [
            {
                "entry_key": entry["entry_key"],
                "family_id": entry["family_id"],
                "physical_case_id": entry["physical_case_id"],
                "source_role": entry["source_role"],
                "split": entry["split"],
                "trajectory_sha256": entry["trajectory_sha256"],
                "report_sha256": entry["report_sha256"],
                "labels_h5_sha256": entry["labels_h5_sha256"],
            }
            for entry in entries
        ],
        "producer_receipts": producer_receipts,
        "claim_boundary": {
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "continuous_first_arrival": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
            "split_safe": "NOT_ASSESSED",
            "recovery_safe": "NOT_ASSESSED",
        },
        "request_note": (
            "Audit only completed materialized label H5 artifacts. Labels are saved-frame chord "
            "observations with first-passage brackets; continuous first arrival and hidden "
            "recrossings remain UNKNOWN. No original trajectory H5, BI4, solver, or model is read."
        ),
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def run(manifest_path: Path | str, output: Path | str) -> dict[str, Any]:
    """Delegate the actual materialized-label audit to consumed v3 semantics."""
    return _BASE._quality_run(manifest_path, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make_manifest_parser = sub.add_parser("make-manifest")
    make_manifest_parser.add_argument("--entries-json", type=Path, required=True)
    make_manifest_parser.add_argument("--output", type=Path, required=True)
    make_request_parser = sub.add_parser("make-request")
    make_request_parser.add_argument("--manifest", type=Path, required=True)
    make_request_parser.add_argument("--output", type=Path, required=True)
    make_request_parser.add_argument("--worktree-root", type=Path, required=True)
    make_request_parser.add_argument("--worker-root", type=Path)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "make-manifest":
        _, payload = read_json(args.entries_json, "entries JSON")
        raw_entries = payload.get("entries") if isinstance(payload, dict) else payload
        make_manifest(raw_entries, args.output)
    elif args.command == "make-request":
        make_request(args.manifest, args.output, args.worktree_root, args.worker_root)
    else:
        run(args.manifest, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
