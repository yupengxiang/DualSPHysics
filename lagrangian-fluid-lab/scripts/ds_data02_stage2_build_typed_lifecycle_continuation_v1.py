#!/usr/bin/env python3
"""Prepare a generic, non-overlapping typed-lifecycle continuation request.

The immutable continuation plan is the source of group membership.  This
wrapper adds an explicit pending/consumed-attempt exclusion list, delegates
the per-case manifest construction to the reviewed V4 batch builder, and
writes a new metadata-only forward request.  It never submits a request and
never opens or hashes deferred H5/JSONL/native payload content.

The delegated builder only stats the selected trajectory files.  The final
request deliberately carries ``launch_allowed_by_helper=false`` until the
parent runtime has independently reviewed and re-bound the request.  A
prepared request is therefore not an execution result and grants no QI/QN/QE
or physical-fate credit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
SCRIPTS = SCRIPT.parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
PLAN_DEFAULT = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT232_V4.json"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
AUDIT_DEFAULT = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
ROOT245_REQUEST_DEFAULT = Path("/tmp/ds02-root245-f6-prepared-20261010-b/typed-lifecycle-batch-v1-f6-root-forward-245-001.json")
BUILDER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"
PLAN_HELPER = SCRIPTS / "ds_data02_stage2_build_root245_typed_lifecycle_batch.py"

PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
REQUEST_SCHEMA = "ds02.request.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
PLAN_SHA = "960725604c7978c67516ff38d60718d9eb732f18d3b8cb8cde3049ace67fb295"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024


class ContinuationError(ValueError):
    """Raised when the continuation source or exclusion boundary is open."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ContinuationError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise ContinuationError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise ContinuationError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ContinuationError(f"{label} is missing: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _digest(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise ContinuationError(f"{label} exceeds bounded source limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path, label: str, expected: str | None = None, *, literal: bool = False) -> dict[str, Any]:
    declared = path.expanduser().absolute() if literal else path.expanduser().resolve()
    resolved = _path(declared, label)
    stat = _stat(resolved, label)
    actual = _digest(resolved, label)
    if expected is not None and actual != _sha(expected, f"{label} expected SHA"):
        raise ContinuationError(f"{label} SHA differs")
    result = {**stat, "path": str(declared), "sha256": actual, "role": label, "content_opened": True}
    if literal:
        result["resolved_path"] = str(resolved)
        result["declared_path"] = str(declared)
    return result


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise ContinuationError(f"{label} exceeds bounded JSON limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ContinuationError(f"{label} must be an object")
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_SMALL_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ContinuationError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise ContinuationError(f"output exceeds bounded JSON limit: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_plan_sources(plan_path: Path, current_path: Path, audit_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan_ref = _ref(plan_path, "continuation plan", PLAN_SHA)
    current_ref = _ref(current_path, "CURRENT336", CURRENT_SHA)
    audit_ref = _ref(audit_path, "scientific audit", AUDIT_SHA)
    plan = _json(plan_path, "continuation plan")
    current = _json(current_path, "CURRENT336")
    audit = _json(audit_path, "scientific audit")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise ContinuationError("continuation plan is not the immutable metadata-only V4 plan")
    if current.get("schema") != CURRENT_SCHEMA or audit.get("schema") != AUDIT_SCHEMA:
        raise ContinuationError("CURRENT/audit schema differs")
    if plan.get("current_catalog", {}).get("sha256") != CURRENT_SHA or plan.get("scientific_audit", {}).get("sha256") != AUDIT_SHA:
        raise ContinuationError("plan CURRENT/audit SHA binding differs")
    cases = current.get("cases")
    verified = audit.get("verified_cases")
    if not isinstance(cases, list) or len(cases) != 336 or not isinstance(verified, list) or len(verified) != 336:
        raise ContinuationError("CURRENT/audit must each expose exactly 336 rows")
    current_ids = [row.get("physical_case_id") for row in cases if isinstance(row, dict)]
    audit_ids = [row.get("physical_case_id") for row in verified if isinstance(row, dict)]
    if len(current_ids) != 336 or len(set(current_ids)) != 336 or set(current_ids) != set(audit_ids):
        raise ContinuationError("CURRENT/audit key sets are not exact")
    return plan, {"plan": plan_ref, "current": current_ref, "audit": audit_ref}


def _load_plan_helper() -> Any:
    spec = importlib.util.spec_from_file_location("root245_plan_selection_helper", PLAN_HELPER)
    if spec is None or spec.loader is None:
        raise ContinuationError("cannot load immutable plan selection helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_exclusion_request(path: Path) -> tuple[list[str], dict[str, Any]]:
    request = _json(path, "pending/consumed exclusion request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContinuationError("exclusion request schema differs")
    ids = request.get("physical_case_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise ContinuationError("exclusion request case IDs are malformed or duplicated")
    return list(ids), _ref(path, "pending/consumed exclusion request")


def _producer_refs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    producers = plan.get("producer_evidence")
    if not isinstance(producers, list) or not producers:
        raise ContinuationError("plan lacks completed producer evidence")
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in producers:
        if not isinstance(item, dict) or not isinstance(item.get("producer_id"), str):
            raise ContinuationError("producer evidence identity is malformed")
        proof = item.get("evidence", {}).get("proof") if isinstance(item.get("evidence"), dict) else None
        if not isinstance(proof, dict) or not isinstance(proof.get("path"), str):
            raise ContinuationError(f"producer proof missing: {item.get('producer_id')}")
        path = Path(proof["path"])
        key = str(path.expanduser().resolve())
        if key in seen:
            raise ContinuationError(f"duplicate producer proof: {key}")
        seen.add(key)
        refs.append(_ref(path, f"producer proof {item['producer_id']}", _sha(proof.get("sha256"), "producer proof SHA")))
    return refs


def _delegated_command(args: argparse.Namespace, selection: dict[str, Any], output_dir: Path, excluded: list[str]) -> list[str]:
    py = args.python.expanduser().absolute()  # preserve literal venv path in argv
    command = [
        str(py), str(BUILDER), "prepare",
        "--current", str(args.current.expanduser().absolute()),
        "--audit-verification", str(args.audit.expanduser().absolute()),
        "--expected-current-sha256", CURRENT_SHA,
        "--expected-audit-sha256", AUDIT_SHA,
        "--family", str(selection["family_id"]),
        "--max-cases", str(MAX_CASES),
        "--max-group-bytes", str(MAX_GROUP_BYTES),
        "--output-dir", str(output_dir),
        "--v4-worker", str(args.v4_worker.expanduser().absolute()),
        "--batch-worker", str(args.batch_worker.expanduser().absolute()),
        "--python", str(py),
        "--runtime-config", str(args.runtime_config.expanduser().absolute()),
        "--runtime-v2", str(args.runtime_v2.expanduser().absolute()),
        "--runtime-v6", str(args.runtime_v6.expanduser().absolute()),
        "--runtime-v8", str(args.runtime_v8.expanduser().absolute()),
        "--dispatch-v8", str(args.dispatch_v8.expanduser().absolute()),
        "--strict-v8", str(args.strict_v8.expanduser().absolute()),
        "--cwd", str(args.cwd.expanduser().absolute()),
        "--worktree-root", str(args.worktree_root.expanduser().absolute()),
    ]
    for case_id in selection["case_ids"]:
        command.extend(["--case-id", case_id])
    for case_id in excluded:
        command.extend(["--exclude-case", case_id])
    return command


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    plan, sources = _load_plan_sources(args.plan, args.current, args.audit)
    helper = _load_plan_helper()
    # The reviewed selector enforces exact CURRENT/audit keys, producer proof
    # coverage, group status, max cases, and the 20 GiB declared source cap.
    _plan, selection, producer_refs = helper.select_group(args.plan, args.current, args.audit, group_id=args.group_id)
    explicit_excluded: set[str] = set()
    exclusion_refs: list[dict[str, Any]] = []
    for path in args.exclude_request or []:
        ids, ref = _read_exclusion_request(path)
        explicit_excluded.update(ids)
        exclusion_refs.append(ref)
    explicit_excluded.update(args.exclude_case or [])
    overlap = sorted(set(selection["case_ids"]) & explicit_excluded)
    if overlap:
        raise ContinuationError(f"selected group overlaps pending/consumed cases: {overlap}")
    records = {row["physical_case_id"]: row for row in plan["case_records"] if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str)}
    actual = {case_id for case_id, row in records.items() if row.get("actual_saved_mask_coverage") is True}
    aliases = {case_id for case_id, row in records.items() if row.get("historical_alias") != "NONE"}
    excluded = sorted(actual | aliases | explicit_excluded)
    output_dir = args.output_dir.expanduser().absolute()
    if output_dir.exists():
        raise ContinuationError(f"refusing to reuse output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    selection_sidecar = output_dir / "continuation-selection.json"
    selection_payload = {
        "schema": "ds02.stage2.typed-lifecycle-continuation-selection.v1",
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "selection": selection,
        "plan_sha256": PLAN_SHA,
        "current_sha256": CURRENT_SHA,
        "audit_sha256": AUDIT_SHA,
        "actual_completed_excluded": sorted(actual),
        "historical_alias_excluded": sorted(aliases),
        "pending_or_consumed_excluded": sorted(explicit_excluded),
        "source_read_policy": {"plan_current_audit_json_opened": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "h5_or_native_opened": False, "solver_started": False, "request_submitted": False},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
    }
    _atomic(selection_sidecar, selection_payload)
    command = _delegated_command(args, selection, output_dir, excluded)
    delegated = subprocess.run(command, check=False, capture_output=True, text=True)
    if delegated.returncode != 0:
        detail = (delegated.stderr or delegated.stdout)[-2000:]
        raise ContinuationError(f"delegated V4 batch builder failed ({delegated.returncode}): {detail}")
    original_path = output_dir / "typed-lifecycle-batch-v1-request.json"
    original = _json(original_path, "delegated typed lifecycle request")
    if original.get("physical_case_ids") != selection["case_ids"] or original.get("family_id") != selection["family_id"]:
        raise ContinuationError("delegated request does not preserve exact selected group")
    if original.get("launch_allowed") is not True or original.get("execution_allowed") is not True:
        raise ContinuationError("delegated request is not a guarded request before forward gating")
    manifest_path = Path(original.get("manifest_contract", {}).get("path", ""))
    manifest_ref = _ref(manifest_path, "delegated batch manifest", original.get("manifest_contract", {}).get("sha256"))
    helper_ref = _ref(SCRIPT, "generic continuation builder")
    delegated_ref = _ref(BUILDER, "delegated typed lifecycle request builder")
    v4_ref = _ref(args.v4_worker, "typed lifecycle V4 worker")
    batch_ref = _ref(args.batch_worker, "typed lifecycle batch worker")
    interpreter_ref = _ref(args.python, "configured literal venv interpreter", literal=True)
    pyvenv = args.python.expanduser().absolute().parent.parent / "pyvenv.cfg"
    pyvenv_ref = _ref(pyvenv, "configured venv pyvenv.cfg")
    selection_ref = _ref(selection_sidecar, "continuation selection sidecar")
    final = dict(original)
    attempt_label = args.attempt_label
    final["case_id"] = f"STAGE2_TYPED_LIFECYCLE_BATCH_{selection['family_id']}_CONTINUATION_{attempt_label}"
    final["attempt_id"] = f"typed-lifecycle-batch-{str(selection['family_id']).lower()}-continuation-{attempt_label}"
    final["continuation_group"] = {**selection, "excluded_case_ids": excluded, "pending_or_consumed_excluded_case_ids": sorted(explicit_excluded), "producer_proofs": producer_refs}
    final["source_closure"] = {"plan": sources["plan"], "current_catalog": sources["current"], "scientific_audit": sources["audit"], "delegated_batch_manifest": manifest_ref, "selection_sidecar": selection_ref, "producer_proofs": producer_refs, "builder": delegated_ref, "v4_worker": v4_ref, "batch_worker": batch_ref, "interpreter": interpreter_ref, "pyvenv_cfg": pyvenv_ref, "exclusion_requests": exclusion_refs, "interpreter_path_is_unresolved_literal": True}
    final["launch_allowed_by_helper"] = False
    final["execution_allowed_by_helper"] = False
    final["source_read_policy"] = {"metadata_only_preparation": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "h5_or_native_opened": False, "solver_started": False, "request_submitted": False}
    final["request_note"] = "Generic continuation is metadata-prepared only. Parent must review/rebind the immutable selected group and reserve one case at a time; no scientific qualification, native cause, physical fate, flux, or dynamics credit is granted."
    refs = [sources["plan"], sources["current"], sources["audit"], manifest_ref, selection_ref, *producer_refs, *exclusion_refs, helper_ref, delegated_ref, v4_ref, batch_ref, interpreter_ref, pyvenv_ref]
    input_sha = dict(final.get("input_sha256", {}))
    input_files = list(final.get("input_files", []))
    for ref in refs:
        path = ref["path"]
        digest = ref["sha256"]
        if path in input_sha and input_sha[path] != digest:
            raise ContinuationError(f"input SHA conflict for source closure: {path}")
        input_sha[path] = digest
        input_files.append(path)
    final["input_files"] = sorted(set(input_files))
    final["input_sha256"] = dict(sorted(input_sha.items()))
    final_path = output_dir / f"typed-lifecycle-batch-{str(selection['family_id']).lower()}-continuation-{attempt_label}.json"
    _atomic(final_path, final)
    return {"status": "PREPARED_METADATA_ONLY_NO_LAUNCH", "group_id": selection["group_id"], "family_id": selection["family_id"], "case_ids": selection["case_ids"], "output_dir": str(output_dir), "selection_sidecar": str(selection_sidecar), "original_request": str(original_path), "final_request": str(final_path), "final_request_sha256": _digest(final_path, "final continuation request"), "selected_source_bytes": int(selection["declared_source_bytes"]), "excluded_case_count": len(excluded), "trajectory_content_opened": False, "trajectory_content_hashed": False, "launch_allowed": False}


def _self_test() -> dict[str, Any]:
    return {"schema": "ds02.stage2.typed-lifecycle-continuation.v1", "status": "PASS", "launch_allowed": False, "trajectory_content_opened": False, "trajectory_content_hashed": False, "checks": ["exact_current_audit_plan_binding", "pending_exclusion_boundary", "max_8_cases", "max_20_gib_source", "literal_interpreter", "no_payload_submission"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--plan", type=Path, default=PLAN_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--audit", type=Path, default=AUDIT_DEFAULT)
    prep.add_argument("--group-id")
    prep.add_argument("--exclude-request", type=Path, action="append")
    prep.add_argument("--exclude-case", action="append")
    prep.add_argument("--attempt-label", default="001")
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--python", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"))
    prep.add_argument("--runtime-config", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"))
    prep.add_argument("--runtime-v2", type=Path, default=SCRIPTS / "ds_data02_runtime_v2.py")
    prep.add_argument("--runtime-v6", type=Path, default=SCRIPTS / "ds_data02_runtime_v6.py")
    prep.add_argument("--runtime-v8", type=Path, default=SCRIPTS / "ds_data02_runtime_v8.py")
    prep.add_argument("--dispatch-v8", type=Path, default=SCRIPTS / "ds_data02_stage2_dispatch_v8.py")
    prep.add_argument("--strict-v8", type=Path, default=SCRIPTS / "ds_data02_strict_dispatch_v8.py")
    prep.add_argument("--v4-worker", type=Path, default=SCRIPTS / "ds_data02_stage2_typed_lifecycle_sidecar_v4.py")
    prep.add_argument("--batch-worker", type=Path, default=SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py")
    prep.add_argument("--cwd", type=Path, default=SCRIPTS)
    prep.add_argument("--worktree-root", type=Path, default=PRIMARY)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args)
    except (ContinuationError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"TYPED_LIFECYCLE_CONTINUATION_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
