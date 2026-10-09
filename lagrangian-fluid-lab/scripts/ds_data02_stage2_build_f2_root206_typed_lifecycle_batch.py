#!/usr/bin/env python3
"""Prepare the first non-overlapping F2 lifecycle batch after ROOT203.

This helper is deliberately a preparation tool.  It validates the immutable
post-ROOT203 continuation plan and completed producer proofs, then delegates
manifest/request construction to the existing bounded batch request builder.
It never starts a worker, reserves a lease, opens HDF5/native payloads, or
changes a consumed request.  The parent agent may review the generated request
and perform the guarded launch separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
REQUEST_SCHEMA = "ds02.request.v1"
EXPECTED_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024


class Root206PreparationError(ValueError):
    """Raised when the immutable continuation edge is not closed."""


def _sha256(path: Path, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    path = path.expanduser().resolve()
    stat = path.stat()
    if stat.st_size > max_bytes:
        raise Root206PreparationError(f"bounded source exceeds {max_bytes} bytes: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".jsonl", ".vtk"}:
        raise Root206PreparationError(f"{label} is deferred payload content: {path}")
    try:
        if path.stat().st_size > MAX_SMALL_BYTES:
            raise Root206PreparationError(f"{label} exceeds bounded size: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Root206PreparationError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Root206PreparationError(f"{label} must be an object")
    return value


def _small_ref(path: Path, role: str, *, preserve_spelling: bool = False) -> dict[str, Any]:
    # The configured venv entry point is a symlink.  Keep its literal path in
    # the request so the worker does not silently switch to /usr/bin/python.
    path = path.expanduser().absolute() if preserve_spelling else path.expanduser().resolve()
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "content_opened": True,
    }


def _proof_ids(proof: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    if isinstance(proof.get("physical_case_id"), str):
        ids.add(proof["physical_case_id"])
    for item in proof.get("case_verifications", []) if isinstance(proof.get("case_verifications"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("physical_case_id"), str):
            ids.add(item["physical_case_id"])
    return ids


def _proof_completed(proof: dict[str, Any]) -> bool:
    status = str(proof.get("status", ""))
    return bool(
        proof.get("guarded_receipt_status") == "completed"
        and proof.get("parent_reservation_released") is True
        and "FAIL" not in status.upper()
        and "REJECT" not in status.upper()
    )


def select_group(plan_path: Path, proof_paths: Iterable[Path], *, group_id: str = "F2-typed-lifecycle-continuation-000") -> dict[str, Any]:
    """Select one exact plan group and reject overlap with terminal proofs."""
    plan = _json(plan_path, "ROOT203 continuation plan")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise Root206PreparationError("continuation plan is not the immutable prepared V4 plan")
    current = plan.get("current_catalog")
    if not isinstance(current, dict) or current.get("sha256") != EXPECTED_CURRENT_SHA:
        raise Root206PreparationError("continuation plan does not bind expected CURRENT336 SHA")
    groups = plan.get("groups")
    if not isinstance(groups, list):
        raise Root206PreparationError("continuation plan groups are missing")
    selected = next((value for value in groups if isinstance(value, dict) and value.get("group_id") == group_id), None)
    if selected is None:
        raise Root206PreparationError(f"continuation group is absent: {group_id}")
    case_ids = selected.get("case_ids")
    if selected.get("family_id") != "F2" or not isinstance(case_ids, list) or len(case_ids) != 8 or len(set(case_ids)) != 8:
        raise Root206PreparationError("ROOT206 group must contain eight unique F2 physical cases")
    if selected.get("status") != "UNSCHEDULED_METADATA_ONLY" or selected.get("request_created") is not False:
        raise Root206PreparationError("ROOT206 group is already scheduled or has a request")
    if selected.get("within_metadata_bounds") is not True or int(selected.get("declared_source_bytes", 0)) > MAX_GROUP_BYTES:
        raise Root206PreparationError("ROOT206 group exceeds source bounds")
    completed: set[str] = set()
    for proof_path in proof_paths:
        proof = _json(proof_path, f"producer proof {proof_path}")
        if _proof_completed(proof):
            completed.update(_proof_ids(proof))
    overlap = set(case_ids) & completed
    if overlap:
        raise Root206PreparationError(f"ROOT206 overlaps an actual completed physical case: {sorted(overlap)}")
    return {
        "group_id": group_id,
        "family_id": "F2",
        "case_ids": list(case_ids),
        "case_count": len(case_ids),
        "declared_source_bytes": int(selected.get("declared_source_bytes", 0)),
        "plan_status": selected.get("status"),
        "non_overlap_with_completed_proofs": True,
    }


def _default_stage2_root() -> Path:
    return SCRIPT.parents[1] / "campaigns" / "ds-data-02" / "stage2"


def _command(args: argparse.Namespace, group: dict[str, Any], output_dir: Path) -> list[str]:
    script_dir = SCRIPT.parent
    py = args.python.expanduser().absolute()
    cmd = [
        str(py),
        str((script_dir / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py").resolve()),
        "prepare",
        "--current", str(args.current.expanduser().resolve()),
        "--audit-verification", str(args.audit.expanduser().resolve()),
        "--expected-current-sha256", EXPECTED_CURRENT_SHA,
        "--expected-audit-sha256", EXPECTED_AUDIT_SHA,
        "--family", "F2",
        "--max-cases", str(MAX_CASES),
        "--max-group-bytes", str(MAX_GROUP_BYTES),
        "--output-dir", str(output_dir),
        "--v4-worker", str((script_dir / "ds_data02_stage2_typed_lifecycle_sidecar_v4.py").resolve()),
        "--batch-worker", str((script_dir / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py").resolve()),
        "--python", str(py),
        "--runtime-config", str(args.runtime_config.expanduser().resolve()),
        "--runtime-v2", str((script_dir / "ds_data02_runtime_v2.py").resolve()),
        "--runtime-v6", str((script_dir / "ds_data02_runtime_v6.py").resolve()),
        "--runtime-v8", str((script_dir / "ds_data02_runtime_v8.py").resolve()),
        "--dispatch-v8", str((script_dir / "ds_data02_stage2_dispatch_v8.py").resolve()),
        "--strict-v8", str((script_dir / "ds_data02_strict_dispatch_v8.py").resolve()),
        "--cwd", str(script_dir.resolve()),
        "--worktree-root", str(args.worktree_root.expanduser().resolve()),
    ]
    for case_id in group["case_ids"]:
        cmd.extend(["--case-id", case_id])
    return cmd


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    script_dir = SCRIPT.parent
    proof_paths = [args.root192_proof, args.root193_proof, args.root198_proof, args.root201_proof, args.root203_proof, args.root205_proof]
    group = select_group(args.plan, proof_paths, group_id=args.group_id)
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise Root206PreparationError(f"refusing to reuse an existing immutable output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    cmd = _command(args, group, output_dir)
    # This invokes only the request builder.  The builder stats deferred H5
    # paths and writes manifests; it does not submit a runner job.
    subprocess.run(cmd, check=True)
    original = output_dir / "typed-lifecycle-batch-v1-request.json"
    request = _json(original, "generated ROOT206 batch request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("physical_case_ids") != group["case_ids"]:
        raise Root206PreparationError("generated batch request does not preserve selected case set")
    plan_ref = _small_ref(args.plan, "ROOT203 continuation plan")
    proof_refs = [_small_ref(path, f"completed producer proof {path.name}") for path in proof_paths]
    final = dict(request)
    final["case_id"] = "STAGE2_TYPED_LIFECYCLE_BATCH_F2_ROOT206"
    final["attempt_id"] = "typed-lifecycle-batch-f2-root-206-001"
    final["continuation_group"] = {
        **group,
        "plan": plan_ref,
        "completed_producer_proofs": proof_refs,
        "typed_identity_count_is_not_case_count": True,
        "source_only_preparation": True,
    }
    final["request_note"] = "ROOT206 metadata-prepared non-overlapping F2 group after ROOT192/193/198/201/203; one-case-at-a-time typed lifecycle diagnostic only; parent review and shared guard required."
    final["launch_allowed"] = True
    final["execution_allowed"] = True
    final["launch_owner"] = "root"
    # Preserve the builder's own input closure and append only bounded plan /
    # proof metadata.  No deferred H5 path is hashed or read here.
    helper_ref = _small_ref(SCRIPT, "ROOT206 helper")
    builder_ref = _small_ref(script_dir / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py", "typed lifecycle batch request builder")
    interpreter_ref = _small_ref(args.python, "configured literal venv interpreter", preserve_spelling=True)
    pyvenv_path = args.python.expanduser().absolute().parent.parent / "pyvenv.cfg"
    if not pyvenv_path.is_file():
        raise Root206PreparationError(f"configured interpreter environment metadata is missing: {pyvenv_path}")
    pyvenv_ref = _small_ref(pyvenv_path, "configured venv pyvenv.cfg")
    final["source_closure"] = {
        "helper": helper_ref,
        "delegated_request_builder": builder_ref,
        "interpreter": interpreter_ref,
        "pyvenv_cfg": pyvenv_ref,
        "interpreter_path_is_unresolved_literal": True,
    }
    input_files = list(final.get("input_files", []))
    input_sha = dict(final.get("input_sha256", {}))
    for ref in [plan_ref, *proof_refs, helper_ref, builder_ref, interpreter_ref, pyvenv_ref]:
        if ref["path"] not in input_sha:
            input_files.append(ref["path"])
            input_sha[ref["path"]] = ref["sha256"]
    final["input_files"] = sorted(input_files)
    final["input_sha256"] = dict(sorted(input_sha.items()))
    final_path = output_dir / "typed-lifecycle-batch-v1-f2-root-forward-206-001.json"
    if final_path.exists():
        raise Root206PreparationError(f"refusing to overwrite final request: {final_path}")
    raw = json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with final_path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "group_id": group["group_id"],
        "case_ids": group["case_ids"],
        "output_dir": str(output_dir),
        "original_builder_request": str(original),
        "final_request": str(final_path),
        "final_request_sha256": hashlib.sha256(raw).hexdigest(),
        "launch_allowed_by_helper": False,
        "deferred_h5_opened": False,
        "solver_started": False,
    }


def _parser() -> argparse.ArgumentParser:
    stage2 = _default_stage2_root()
    scripts = SCRIPT.parent
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    p = sub.add_parser("prepare")
    p.add_argument("--plan", type=Path, default=stage2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT203_V4.json")
    p.add_argument("--current", type=Path, default=stage2 / "CURRENT336.json")
    p.add_argument("--audit", type=Path, default=stage2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json")
    p.add_argument("--root192-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_V4_ACTUAL_SINGLE_CASE_ROOT_VERIFICATION_192.json")
    p.add_argument("--root193-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_193.json")
    p.add_argument("--root198-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_198.json")
    p.add_argument("--root201-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_201.json")
    p.add_argument("--root203-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_203.json")
    p.add_argument("--root205-proof", type=Path, default=stage2 / "checkpoints/F2_TYPED_NATIVE_FIRST_MISSING_V4_ACTUAL_ROOT_VERIFICATION_205.json")
    p.add_argument("--group-id", default="F2-typed-lifecycle-continuation-000")
    p.add_argument("--output-dir", type=Path, default=stage2 / "requests/typed-lifecycle-batch-v1-f2-root-prepared-206-001")
    p.add_argument("--python", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"))
    p.add_argument("--runtime-config", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"))
    p.add_argument("--worktree-root", type=Path, default=SCRIPT.parents[2])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "self-test":
        # Exercise the selector and command constructor against a tiny fixture;
        # an unconditional PASS here would not catch path/environment drift.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="root206-self-test-") as directory:
            root = Path(directory)
            case_ids = [f"F2_FIXTURE_{index:02d}" for index in range(8)]
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps({
                "schema": PLAN_SCHEMA,
                "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
                "current_catalog": {"sha256": EXPECTED_CURRENT_SHA},
                "groups": [{
                    "group_id": "F2-typed-lifecycle-continuation-000",
                    "family_id": "F2",
                    "case_ids": case_ids,
                    "status": "UNSCHEDULED_METADATA_ONLY",
                    "request_created": False,
                    "declared_source_bytes": 8,
                    "within_metadata_bounds": True,
                }],
            }), encoding="utf-8")
            proof_path = root / "proof.json"
            proof_path.write_text(json.dumps({
                "status": "VERIFIED_TEST",
                "guarded_receipt_status": "completed",
                "parent_reservation_released": True,
                "case_verifications": [{"physical_case_id": "F2_OTHER_FIXTURE"}],
            }), encoding="utf-8")
            selected = select_group(plan_path, [proof_path])
            if selected["case_count"] != 8 or not selected["non_overlap_with_completed_proofs"]:
                raise SystemExit("Root206PreparationError: self-test selection failed")
            args_for_command = argparse.Namespace(
                current=root / "CURRENT336.json",
                audit=root / "audit.json",
                python=Path("/literal/venv/bin/python"),
                runtime_config=Path("/literal/DsphConfig.xml"),
                worktree_root=root,
            )
            command = _command(args_for_command, selected, root / "out")
            if command[0] != "/literal/venv/bin/python" or "run" in command[:4] or command.count("--case-id") != 8:
                raise SystemExit("Root206PreparationError: self-test command contract failed")
        print(json.dumps({"schema": "ds02.stage2.root206-helper.v1", "status": "PASS", "launch_allowed": False, "payload_opened": False, "checks": ["select_group", "source_only_command"]}, sort_keys=True))
        return 0
    try:
        print(json.dumps(prepare(args), sort_keys=True))
    except (Root206PreparationError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Root206PreparationError: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
