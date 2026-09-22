#!/usr/bin/env python3
"""Run a read-only, relocatable Core reader/model/evaluation reproduction.

The runner deliberately materialises a second data root without copying the
large source assets: JSON/code/checkpoint metadata are copied and the HDF5 and
NPZ assets are hash-checked and hard-linked by ``core_relocate``.  The model
entrypoint is then executed from the relocated bundle with ``device=cpu``.
F3's privileged saved-state oracle and the F4 compact reader check are kept as
separate receipts; neither is treated as a learned-model result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_benchmark import verify_dataset
from scripts.core_dataset import validate_manifest, sha256_file
from scripts.core_relocate import relocate
from scripts.core_runtime import atomic_json, digest


SCHEMA = "core.independent_reproduction.run.v1"
DATASET_SCHEMA = "core.dataset.v2"
READER_SCHEMA = "core.reader_reproduction.v1"
MODEL_REPRODUCTION_SCHEMA = "core.model_reproduction.v1"
LARGE_ASSET_SUFFIXES = {".h5", ".npz"}
DEFAULT_CASE = "F3_DEV_08_a0p953125"
DEFAULT_F4_CASE = "F4_resting_pool_laminar_tallwall120_x_v1_DEV_04"

# These are intentionally outside the relocation bundle and are fingerprinted
# before/after the run to make the no-registry/no-ledger mutation claim
# checkable in the resulting receipt.
PROTECTED_STATE_RELATIVE = (
    "campaigns/core-v1/registry.json",
    "campaigns/core-v1/queue.sqlite3",
    "campaigns/core-v1/runtime/queue.sqlite3",
    "campaigns/l1-qualification/RESOURCE-LEDGER.json",
    "campaigns/l2-multifamily/ledger.json",
)


def _canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _portable_path(root, value, *, label, require_file=False):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} is not a portable relative path: {value}")
    root = Path(root).resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes data root: {value}") from error
    if require_file and not target.is_file():
        raise FileNotFoundError(target)
    return path.as_posix(), target


def _copy_metadata_root(bundle, metadata_root):
    """Copy only bundle metadata so relocation must resolve data externally."""
    bundle = Path(bundle).resolve()
    metadata_root = Path(metadata_root).resolve()
    if metadata_root.exists():
        raise FileExistsError(metadata_root)
    index = json.loads((bundle / "bundle.json").read_text())
    metadata_root.mkdir(parents=True)
    shutil.copy2(bundle / "bundle.json", metadata_root / "bundle.json")
    copied, omitted = [], []
    for item in index.get("files", []):
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"bundle path escapes root: {relative}")
        source = (bundle / relative).resolve()
        source.relative_to(bundle)
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.suffix.lower() in LARGE_ASSET_SUFFIXES:
            omitted.append({"path": relative.as_posix(), "bytes": source.stat().st_size})
            continue
        target = metadata_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append({"path": relative.as_posix(), "bytes": source.stat().st_size})
    return {"copied_metadata": copied, "omitted_external_assets": omitted}


def _state_fingerprints(root):
    root = Path(root).resolve()
    rows = []
    for relative in PROTECTED_STATE_RELATIVE:
        path = root / relative
        rows.append({
            "path": relative,
            "present": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "sha256": digest(path) if path.is_file() else None,
        })
    return rows


def _code_closure(root, names):
    root = Path(root).resolve()
    rows = []
    for name in names:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        rows.append({"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)})
    return {"files": rows, "closure_sha256": _canonical_hash(
        [{"path": row["path"], "sha256": row["sha256"]} for row in rows]
    )}


def audit_manifest(manifest_path, data_root, *, label, verify_assets=True,
                   selected_case=None, verify_selected_trajectory=False):
    """Audit compact relative paths and hashed input assets without training."""
    manifest_path = Path(manifest_path).resolve()
    data_root = Path(data_root).resolve()
    payload = json.loads(manifest_path.read_text())
    validate_manifest(payload)
    if payload.get("schema") != DATASET_SCHEMA:
        raise ValueError(f"{label} must use {DATASET_SCHEMA}")
    rows = payload["cases"]
    asset_rows = {}
    trajectory_rows = []
    for row in rows:
        _portable_path(data_root, row["hdf5"], label=f"{label}.hdf5")
        for key in ("geometry", "control"):
            reference = row["known_inputs_ref"][key]
            relative, path = _portable_path(
                data_root, reference["path"], label=f"{label}.{key}", require_file=verify_assets
            )
            asset_rows[relative] = {
                "path": relative,
                "sha256": reference["sha256"],
                "bytes": path.stat().st_size if path.is_file() else None,
                "verified": False,
            }
            if verify_assets:
                observed = sha256_file(path)
                if observed != reference["sha256"]:
                    raise ValueError(f"{label} input asset hash mismatch: {relative}")
                asset_rows[relative]["verified"] = True
        if selected_case is not None and row["case_id"] == selected_case:
            relative, path = _portable_path(
                data_root, row["hdf5"], label=f"{label}.selected_hdf5", require_file=True
            )
            trajectory = {
                "case_id": selected_case,
                "path": relative,
                "bytes_declared": row.get("bytes"),
                "bytes_observed": path.stat().st_size,
                "sha256_declared": row["sha256"],
                "sha256_observed": None,
                "verified": False,
            }
            if row.get("bytes") is not None and path.stat().st_size != row["bytes"]:
                raise ValueError(f"{label} selected HDF5 byte mismatch")
            if verify_selected_trajectory:
                trajectory["sha256_observed"] = sha256_file(path)
                if trajectory["sha256_observed"] != row["sha256"]:
                    raise ValueError(f"{label} selected HDF5 hash mismatch")
                trajectory["verified"] = True
            trajectory_rows.append(trajectory)
    if selected_case is not None and len(trajectory_rows) != 1:
        raise ValueError(f"{label} selected case is not registered: {selected_case}")
    return {
        "schema": "core.independent_reproduction.manifest_audit.v1",
        "label": label,
        "manifest": str(manifest_path),
        "manifest_sha256": digest(manifest_path),
        "data_root": str(data_root),
        "dataset_id": payload.get("dataset_id"),
        "dataset_schema": payload.get("schema"),
        "formal_release": bool(payload.get("formal_release", False)),
        "case_count": len(rows),
        "families": sorted({row["family"] for row in rows}),
        "splits": {split: sum(row["split"] == split for row in rows)
                   for split in sorted({row["split"] for row in rows})},
        "relative_paths": True,
        "future_state_inputs": False,
        "future_state_inputs_basis": "compact known_inputs_ref contains only declared causal control/geometry assets",
        "input_assets": sorted(asset_rows.values(), key=lambda row: row["path"]),
        "selected_trajectory": trajectory_rows[0] if trajectory_rows else None,
        "scientific_status": "source_manifest_and_reader_contract_only",
        "qualification_inferred": False,
    }


def _run(command, *, cwd, output_path, error_path, env):
    started = time.monotonic()
    with Path(output_path).open("w") as stdout, Path(error_path).open("w") as stderr:
        process = subprocess.run(command, cwd=str(cwd), env=env, stdout=stdout, stderr=stderr)
    return {
        "command": [str(value) for value in command],
        "cwd": str(cwd),
        "exit_code": int(process.returncode),
        "wall_seconds": float(time.monotonic() - started),
        "stdout": {"path": str(output_path), "sha256": digest(output_path), "bytes": Path(output_path).stat().st_size},
        "stderr": {"path": str(error_path), "sha256": digest(error_path), "bytes": Path(error_path).stat().st_size},
    }


def _relocation_identity(source_root, destination, relocation):
    index = json.loads((Path(source_root) / "bundle.json").read_text())
    large = []
    for item in index["files"]:
        relative = Path(item["path"])
        if relative.suffix.lower() not in LARGE_ASSET_SUFFIXES:
            continue
        source = Path(source_root) / relative
        target = Path(destination) / relative
        large.append({
            "path": relative.as_posix(),
            "bytes": int(source.stat().st_size),
            "source_sha256": digest(source),
            "destination_sha256": digest(target),
            "same_inode": source.stat().st_ino == target.stat().st_ino,
        })
    return {
        "source_data_root": str(Path(source_root).resolve()),
        "relocated_data_root": str(Path(destination).resolve()),
        "different_data_root": Path(source_root).resolve() != Path(destination).resolve(),
        "bundle_sha256_source": digest(Path(source_root) / "bundle.json"),
        "bundle_sha256_relocated": digest(Path(destination) / "bundle.json"),
        "large_asset_count": len(large),
        "large_assets_same_inode": sum(row["same_inode"] for row in large),
        "large_assets_hash_match": all(row["source_sha256"] == row["destination_sha256"] for row in large),
        "all_large_assets_hardlinked": bool(large) and all(row["same_inode"] for row in large),
        "assets": large,
        "relocation_receipt": relocation,
    }


def _independent_reproduction_gates(*, protected_unchanged, reader_run,
                                    f3_reader, f4_reader, model_run, model_report):
    """Apply the fail-closed gates used by the independent-run receipt.

    A child process can leave a syntactically valid report behind even when it
    exits non-zero. Likewise, a model report may describe a full horizon while
    its top-level ``passed`` flag is false (for example, source verification
    failed). Neither state is sufficient evidence for an independent
    reproduction, so the aggregator requires the process status, schema, and
    report-level pass contract together.
    """
    f3_passed = (
        isinstance(reader_run, dict)
        and reader_run.get("exit_code") == 0
        and isinstance(f3_reader, dict)
        and f3_reader.get("schema") == READER_SCHEMA
        and f3_reader.get("passed") is True
    )
    f4_passed = (
        isinstance(f4_reader, dict)
        and f4_reader.get("schema") == "core.verification.v1"
        and f4_reader.get("passed") is True
    )
    model_passed = (
        isinstance(model_run, dict)
        and model_run.get("exit_code") == 0
        and isinstance(model_report, dict)
        and model_report.get("schema") == MODEL_REPRODUCTION_SCHEMA
        and model_report.get("passed") is True
        and model_report.get("full_horizon_reproduction") is True
        and model_report.get("predictor_future_state_inputs") is False
    )
    read_only_contract_passed = bool(protected_unchanged and f3_passed and f4_passed)
    return {
        "f3_reader_passed": f3_passed,
        "f4_reader_passed": f4_passed,
        "model_passed": model_passed,
        "read_only_contract_passed": read_only_contract_passed,
        "independent_reproduction_evidence": bool(read_only_contract_passed and model_passed),
    }


def run(args):
    bundle = Path(args.bundle).resolve()
    output_root = Path(args.output_dir).resolve()
    relocated_root = Path(args.relocated_root).resolve()
    lab_root = Path(args.lab_root).resolve()
    if not (bundle / "bundle.json").is_file():
        raise ValueError("bundle must contain bundle.json")
    if output_root == bundle or output_root.is_relative_to(bundle):
        raise ValueError("output directory must be outside immutable source bundle")
    if relocated_root == bundle or relocated_root.is_relative_to(bundle):
        raise ValueError("relocated data root must be outside immutable source bundle")
    if output_root == relocated_root or output_root.is_relative_to(relocated_root):
        raise ValueError("output directory must be outside relocated data root")
    if relocated_root.exists() and not args.reuse_relocated_root:
        raise FileExistsError(f"refusing to overwrite relocated root: {relocated_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    protected_before = _state_fingerprints(lab_root)
    run_started = time.monotonic()
    metadata_receipt = None
    relocation_receipt = None
    if relocated_root.exists():
        # A prior run may have completed the expensive immutable relocation and
        # failed before the child interpreter started (for example because a
        # caller resolved a venv symlink to the system Python).  Reuse is
        # permitted only through an explicit flag and still rechecks the
        # bundle in the child reader/model entrypoints below.
        metadata_receipt = {"reused_existing_relocated_root": True}
        relocation_receipt = {"schema": "core.bundle_relocation.v1", "passed": True,
                              "destination": str(relocated_root), "reused_existing": True}
    else:
        with tempfile.TemporaryDirectory(prefix="core-independent-metadata-") as metadata_name:
            metadata_receipt = _copy_metadata_root(bundle, Path(metadata_name) / "metadata")
            relocation_receipt = relocate(Path(metadata_name) / "metadata", bundle, relocated_root)
    relocation_identity = _relocation_identity(bundle, relocated_root, relocation_receipt)

    reader_output = output_root / "f3-reader-verification.json"
    reader_stdout = output_root / "f3-reader.stdout.log"
    reader_stderr = output_root / "f3-reader.stderr.log"
    model_root = (Path(args.model_output_dir).resolve()
                  if args.model_output_dir else output_root / "model-reproduction")
    if model_root == relocated_root or model_root.is_relative_to(relocated_root):
        raise ValueError("model output directory must be outside relocated data root")
    if model_root == bundle or model_root.is_relative_to(bundle):
        raise ValueError("model output directory must be outside immutable source bundle")
    model_root.mkdir(parents=True, exist_ok=True)
    model_output = model_root / "reproduction.json"
    model_stdout = output_root / "model.stdout.log"
    model_stderr = output_root / "model.stderr.log"
    # Preserve a virtualenv launcher symlink.  Resolving it would silently
    # switch the child to /usr/bin/python and can pair incompatible system
    # h5py/numpy wheels, invalidating the portability test.
    runner_python = (Path(args.python).absolute()
                     if args.python else Path(sys.executable).absolute())
    bundled_script = relocated_root / "code/scripts/core_benchmark.py"
    env = dict(os.environ)
    env.update({
        "CUDA_VISIBLE_DEVICES": "",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        "PYTHONHASHSEED": "0",
        "OMP_NUM_THREADS": str(args.threads),
        "MKL_NUM_THREADS": str(args.threads),
        "OPENBLAS_NUM_THREADS": str(args.threads),
        "VECLIB_MAXIMUM_THREADS": str(args.threads),
        "NUMEXPR_NUM_THREADS": str(args.threads),
    })
    reader_run = _run(
        [runner_python, bundled_script, "verify", "--manifest", "dataset.json", "--data-root", ".",
         "--case-id", args.case_id, "--full-scan", "--output", reader_output],
        cwd=relocated_root, output_path=reader_stdout, error_path=reader_stderr, env=env,
    )
    if not reader_output.is_file():
        raise RuntimeError("relocated F3 reader did not produce a receipt")
    f3_reader = json.loads(reader_output.read_text())

    f3_manifest_audit = audit_manifest(
        relocated_root / "dataset.json", relocated_root, label="F3_v2", verify_assets=True,
        selected_case=args.case_id, verify_selected_trajectory=True,
    )
    f4_manifest_audit = audit_manifest(
        args.f4_manifest, args.f4_data_root, label="F4_compact_v2", verify_assets=True,
        selected_case=args.f4_case_id, verify_selected_trajectory=False,
    )
    f4_reader_started = time.monotonic()
    f4_reader = verify_dataset(
        args.f4_manifest, args.f4_data_root, case_ids=[args.f4_case_id], full_scan=True,
    )
    f4_reader["reader_wall_seconds_in_runner"] = float(time.monotonic() - f4_reader_started)
    f4_reader["oracle_role"] = "privileged_reference_integrity_check_only"
    f4_reader["learned_model_result"] = False
    f4_reader_path = output_root / "f4-compact-reader-verification.json"
    atomic_json(f4_reader_path, f4_reader)

    model_command = [
        runner_python, bundled_script, "reproduce", "--manifest", "dataset.json", "--data-root", ".",
        "--checkpoint", "models/checkpoint-000.pt", "--case-id", args.case_id,
        "--source-host", args.source_host, "--device", "cpu", "--output-dir", model_root,
        "--output", model_output,
    ]
    if args.paired_report:
        model_command.extend(["--paired-report", Path(args.paired_report).resolve()])
    model_run = _run(
        model_command, cwd=relocated_root, output_path=model_stdout, error_path=model_stderr, env=env,
    )
    if not model_output.is_file():
        raise RuntimeError("relocated CPU model reproduction did not produce a report")
    model_report = json.loads(model_output.read_text())
    model_report["runner_observed_device"] = "cpu"
    model_report["runner_cuda_visible_devices"] = env["CUDA_VISIBLE_DEVICES"]
    atomic_json(model_output, model_report)
    # Keep a small versioned snapshot beside the receipt while leaving the
    # large trajectory in the explicitly supplied model output directory.
    model_report_snapshot = output_root / "model-reproduction-report.json"
    shutil.copy2(model_output, model_report_snapshot)
    score_snapshot = None
    score_path = model_root / "scores.json"
    if score_path.is_file():
        score_snapshot = output_root / "model-reproduction-scores.json"
        shutil.copy2(score_path, score_snapshot)

    protected_after = _state_fingerprints(lab_root)
    protected_unchanged = protected_before == protected_after
    gate_checks = _independent_reproduction_gates(
        protected_unchanged=protected_unchanged,
        reader_run=reader_run,
        f3_reader=f3_reader,
        f4_reader=f4_reader,
        model_run=model_run,
        model_report=model_report,
    )
    receipt = {
        "schema": SCHEMA,
        "version": "a8-independent-relocated-v1",
        "status": "independent_relocated_model_run",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": platform.node(),
        "python": str(runner_python),
        "scope": {
            "independent_data_root": True,
            "independence_mode": "same_host_relocated_data_root_with_external_hash_bound_assets",
            "cross_host_claim": False,
            "training_started": False,
            "solver_started": False,
            "gpu_started": False,
            "registry_mutated": False,
            "ledger_mutated": False,
            "scientific_qualification": False,
            "formal_training_count": 0,
        },
        "source": {
            "bundle": str(bundle),
            "bundle_sha256": digest(bundle / "bundle.json"),
            "a8_index": str(Path(args.a8_index).resolve()),
            "a8_index_sha256": digest(args.a8_index),
            "a8_manifest_binding_root_review": str(Path(args.a8_manifest_root_review).resolve()),
            "a8_manifest_binding_root_review_sha256": digest(args.a8_manifest_root_review),
            "a8_reproduction_root_review": str(Path(args.a8_reproduction_root_review).resolve()),
            "a8_reproduction_root_review_sha256": digest(args.a8_reproduction_root_review),
        },
        "relocation": {"metadata": metadata_receipt, **relocation_identity},
        "manifests": {"f3": f3_manifest_audit, "f4": f4_manifest_audit},
        "reader": {
            "f3": {"run": reader_run, "receipt": str(reader_output), "receipt_sha256": digest(reader_output),
                   "passed": gate_checks["f3_reader_passed"], "oracle_role": "privileged_reference_integrity_check_only",
                   "learned_model_result": False},
            "f4": {"receipt": str(f4_reader_path), "receipt_sha256": digest(f4_reader_path),
                   "passed": gate_checks["f4_reader_passed"], "oracle_role": f4_reader["oracle_role"],
                   "learned_model_result": False},
        },
        "model": {
            "run": model_run,
            "report": str(model_output),
            "report_sha256": digest(model_output),
            "report_snapshot": str(model_report_snapshot),
            "report_snapshot_sha256": digest(model_report_snapshot),
            "score_snapshot": str(score_snapshot) if score_snapshot else None,
            "score_snapshot_sha256": digest(score_snapshot) if score_snapshot else None,
            "passed": gate_checks["model_passed"],
            "full_horizon_reproduction": bool(model_report.get("full_horizon_reproduction")),
            "full_product_reproduction": bool(model_report.get("full_product_reproduction")),
            "cross_host_reproduction": bool(model_report.get("cross_host_reproduction")),
            "predictor_future_state_inputs": model_report.get("predictor_future_state_inputs"),
            "future_reference_state_used_by_oracle": model_report.get("future_reference_state_used_by_oracle"),
            "scientific_status": model_report.get("scientific_status"),
            "resource": model_report.get("resource"),
            "model_kind": model_report.get("model_kind"),
            "checkpoint_sha256": model_report.get("checkpoint_sha256"),
            "manifest_sha256": model_report.get("manifest_sha256"),
            "bundle_sha256": model_report.get("bundle_sha256"),
            "case_ids": model_report.get("case_ids"),
        },
        "protected_state": {
            "before": protected_before,
            "after": protected_after,
            "unchanged": protected_unchanged,
        },
        "result": {
            **gate_checks,
            "core_gate_status": "blocked_for_full_product_release; diagnostic_model_reproduction_only",
            "blockers": [
                "The checkpoint is an engineering/preprofile artifact and no scientific qualification is inferred.",
                "The reader oracle uses future saved state as a privileged reference for integrity/scoring only.",
                "The relocated run is independent by data_root but is same-host; cross-host claim remains separate.",
            ],
        },
        "code": {
            "runner": _code_closure(Path(__file__).resolve().parent, ["core_independent_reproduction.py", "core_relocate.py"]),
            "bundle_entrypoint": model_report.get("code"),
        },
        "wall_seconds": float(time.monotonic() - run_started),
    }
    receipt_path = output_root / "independent-reproduction-receipt.json"
    atomic_json(receipt_path, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--relocated-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-output-dir", type=Path,
                        help="external directory for the large model trajectory and score artifacts")
    parser.add_argument("--reuse-relocated-root", action="store_true",
                        help="reuse a previously completed immutable relocation after a pre-model failure")
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--f4-manifest", type=Path, required=True)
    parser.add_argument("--f4-data-root", type=Path, required=True)
    parser.add_argument("--case-id", default=DEFAULT_CASE)
    parser.add_argument("--f4-case-id", default=DEFAULT_F4_CASE)
    parser.add_argument("--source-host", default="a8-prior-h200-model-report")
    parser.add_argument("--paired-report", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--a8-index", type=Path, required=True)
    parser.add_argument("--a8-manifest-root-review", type=Path, required=True)
    parser.add_argument("--a8-reproduction-root-review", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args)
    print(json.dumps({
        "schema": result["schema"], "status": result["status"],
        "independent_reproduction_evidence": result["result"]["independent_reproduction_evidence"],
        "core_gate_status": result["result"]["core_gate_status"],
        "receipt": str(Path(args.output_dir).resolve() / "independent-reproduction-receipt.json"),
    }, indent=2))
    return 0 if result["result"]["independent_reproduction_evidence"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
