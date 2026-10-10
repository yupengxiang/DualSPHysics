#!/usr/bin/env python3
"""Parent-owned canonical CURRENT row-65 raw-to-typed executor.

The canonical65 phase request is intentionally content-pending.  This
additive entry point turns it into a runnable CPU request for the existing V10
parent runtime.  V10 performs the single parent-ledger reservation before it
hashes ``input_files``.  Its child then records the raw-tree and source
envelopes, fills the native v2 request, and invokes the checked-in native
converter/typed validator.  The child writes a small summary; the detailed
worker report remains an attempt-owned file and is joined by the verifier.

The builder only stats bounded metadata and source code.  ``run`` is the
resource-owning entry point and must be started by the parent with
``--parent-pid``.  It never grants scientific qualification and it never
changes the consumed phase request.  The historical row-78 identity is
rejected in every executable binding.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
PHASE_SCHEMA = "ds02.stage2.f2-canonical65-raw-to-typed-phase.v1"
WORKER_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
RUNTIME_REQUEST_SCHEMA = "ds02.stage2.f2-canonical65-v10-parent-request.v1"
SUMMARY_SCHEMA = "ds02.stage2.f2-canonical65-worker-summary.v1"
VERIFY_SCHEMA = "ds02.stage2.f2-canonical65-execution-verification.v1"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CANONICAL_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
HISTORICAL_ALIAS_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PENDING = "PENDING_PARENT_GUARD_CONTENT_SHA256"
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
HEX = frozenset("0123456789abcdef")

RUNTIME_V10_DEFAULT = SCRIPT_DIR / "ds_data02_runtime_v10_git_bound.py"
WORKER_DEFAULT = SCRIPT_DIR / "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
VERIFIER = SCRIPT_DIR / "ds_data02_stage2_f2_canonical65_raw_to_typed_verify_v1.py"


class Canonical65Error(RuntimeError):
    """The canonical65 parent or child contract is not safe to execute."""


def _canonical(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items()
                 if key not in {"sha256", "file_sha256", "canonical_sha256",
                                "phase_request_canonical_sha256",
                                "worker_materialized_request_sha256"}}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _sha(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise Canonical65Error(f"bound file is not a regular non-symlink file: {target}")
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise Canonical65Error(f"file exceeds metadata bound: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = target.lstat()
    except OSError as error:
        raise Canonical65Error(f"{role} cannot be stat'ed: {target}: {error}") from error
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
        raise Canonical65Error(f"{role} must be a regular non-symlink file: {target}")
    return {"role": role, "path": str(target), "st_dev": int(value.st_dev),
            "st_ino": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "mode_bits": int(stat.S_IMODE(value.st_mode))}


def _load_json(path: Path | str, role: str, *, limit: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    target = Path(path).expanduser()
    before = _stat(target, role)
    if before["bytes"] > limit:
        raise Canonical65Error(f"{role} exceeds bounded JSON limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Canonical65Error(f"{role} is invalid JSON: {target}: {error}") from error
    after = _stat(target, role)
    if before != after:
        raise Canonical65Error(f"{role} changed while being read: {target}")
    if not isinstance(value, dict):
        raise Canonical65Error(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise Canonical65Error(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                          allow_nan=False, default=str) + "\n").encode("utf-8")
    with target.open("xb") as stream:
        stream.write(encoded)
    return target


def _require_sha(value: Any, role: str, *, allow_pending: bool = False) -> str | None:
    if allow_pending and value in {None, "", PENDING}:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX for ch in value):
        raise Canonical65Error(f"{role} must be a lowercase SHA-256")
    return value


def _reject_old_paths(value: Any, *, key: str = "") -> None:
    """Reject old row-78 paths in actionable fields, retaining provenance text."""
    if isinstance(value, str):
        # A rejection marker is an explicit guard predicate, not an
        # actionable path.  Keep the historical identifier in that marker so
        # an independent verifier can prove that the alias was rejected.
        if "provenance" in key or "original_path" in key or "historical_alias_rejected" in key:
            return
        forbidden = (HISTORICAL_ALIAS_ID, "ROOT242", "root242", "RX056", "ROT090",
                     "f2-s1-native-raw-to-typed-label-request-v2-001")
        if any(token in value for token in forbidden):
            raise Canonical65Error(f"historical row-78 path leaked into {key or 'binding'}: {value}")
    elif isinstance(value, Mapping):
        for name, item in value.items():
            _reject_old_paths(item, key=str(name))
    elif isinstance(value, list):
        for item in value:
            _reject_old_paths(item, key=key)


def _phase_body_digest(request: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(request))
    body.pop("phase_request_canonical_sha256", None)
    return _canonical(body)


def _phase(path: Path | str) -> dict[str, Any]:
    request = _load_json(path, "canonical65 phase request")
    if request.get("phase_request_schema") != PHASE_SCHEMA:
        raise Canonical65Error("phase request is not canonical65 v1")
    if request.get("schema") != WORKER_SCHEMA:
        raise Canonical65Error("canonical65 phase worker schema differs")
    if request.get("status") != "PENDING_PARENT_GUARD_CONTENT_SHA256":
        raise Canonical65Error("canonical65 phase must remain content-pending")
    if request.get("phase_request_canonical_sha256") != _phase_body_digest(request):
        raise Canonical65Error("canonical65 phase canonical digest differs")
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or identity.get("current_case_index") != 65 or \
            identity.get("physical_case_id") != CANONICAL_ID or \
            identity.get("identity_status") != "CANONICAL_CURRENT_SAVED_MASK":
        raise Canonical65Error("canonical65 phase identity is not exact CURRENT row 65")
    if request.get("current_binding", {}).get("sha256") != CURRENT_SHA:
        raise Canonical65Error("canonical65 CURRENT binding differs")
    raw = request.get("raw_binding")
    if not isinstance(raw, Mapping) or raw.get("expected_raw_tree_sha256") != PENDING:
        raise Canonical65Error("canonical65 raw tree is not parent-deferred")
    if request.get("source_hashes_preverified_by_parent") is not False:
        raise Canonical65Error("canonical65 source hashes must be parent-deferred")
    if request.get("worker_ready") is not False or request.get("launch_allowed") is not False:
        raise Canonical65Error("phase request cannot claim runnable status")
    if request.get("qualification") != UNKNOWN:
        raise Canonical65Error("canonical65 phase must remain UNKNOWN")
    raw_root = Path(str(raw.get("data_root", ""))).expanduser()
    if not raw_root.is_dir() or raw_root.is_symlink():
        raise Canonical65Error(f"canonical65 raw root is missing: {raw_root}")
    entries = sorted(raw_root.rglob("*"))
    files = [item for item in entries if item.is_file()]
    if any(item.is_symlink() for item in entries):
        raise Canonical65Error("canonical65 raw tree contains a symlink")
    if len(files) != int(raw.get("expected_file_count", 405)):
        raise Canonical65Error(f"canonical65 raw file count differs: {len(files)}")
    frames = [item for item in files if item.parent == raw_root and item.name.startswith("Part_") and item.suffix == ".bi4"]
    if len(frames) != int(raw.get("frame_count", 401)) or \
            [int(item.stem.split("_")[-1]) for item in frames] != list(range(len(frames))):
        raise Canonical65Error("canonical65 raw frame scope is not contiguous 401 top-level frames")
    source_files = request.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise Canonical65Error("canonical65 source_files closure is missing")
    required = {"current_catalog", "generated_xml", "motion_dat", "gencase_receipt",
                "solver_receipt", "owner_metadata", "initial_csv", "conversion_report",
                "native_partout", "native_runparts"}
    seen_roles: set[str] = set()
    for item in source_files:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise Canonical65Error("canonical65 source binding is malformed")
        role = str(item["role"])
        if role in seen_roles:
            raise Canonical65Error(f"duplicate canonical65 source role: {role}")
        seen_roles.add(role)
        path_value = item.get("path")
        if not isinstance(path_value, str) or not Path(path_value).is_absolute():
            raise Canonical65Error(f"canonical65 source path is not absolute: {role}")
        _stat(path_value, role)
    if not required.issubset(seen_roles):
        raise Canonical65Error("canonical65 native worker source closure is incomplete")
    modules = request.get("modules")
    if not isinstance(modules, Mapping) or not {"raw_converter", "v14_operator", "v15_operator", "v16_operator", "worker"}.issubset(modules):
        raise Canonical65Error("canonical65 code module closure is incomplete")
    for role, item in modules.items():
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise Canonical65Error(f"canonical65 module binding is malformed: {role}")
        _stat(item["path"], f"module:{role}")
        _require_sha(item.get("sha256"), f"module:{role}.sha256")
    decoder = request.get("decoder")
    if not isinstance(decoder, Mapping) or not isinstance(decoder.get("path"), str):
        raise Canonical65Error("canonical65 decoder binding is missing")
    decoder_path = Path(str(decoder["path"])).expanduser()
    decoder_stat = _stat(decoder_path, "decoder")
    if not (decoder_stat["mode_bits"] & stat.S_IXUSR):
        raise Canonical65Error("canonical65 decoder is not executable")
    _require_sha(decoder.get("sha256"), "decoder.sha256")
    _reject_old_paths(request)
    return request


def _closure_paths(phase: Mapping[str, Any], *, runtime_v10: Path, worker: Path) -> tuple[list[Path], dict[str, list[str]]]:
    """Return all V10 input paths and their logical roles, stat-only."""
    values: list[tuple[str, Path]] = []
    def add(role: str, path: Path | str) -> None:
        target = Path(path).expanduser()
        _stat(target, role)
        values.append((role, target))

    add("phase_request", Path(str(phase["_phase_path"])))
    add("canonical65_executor", SCRIPT)
    add("canonical65_verifier", VERIFIER)
    add("native_worker", worker)
    add("runtime_v10", runtime_v10)
    # Runtime-v10's actual closure is explicit and must be part of the same
    # V10 input hash set.  This also makes a source drift fail before launch.
    runtime_names = (
        "ds_data02_runtime_v9_git_bound.py", "ds_data02_runtime_v8.py",
        "ds_data02_runtime_v6.py", "ds_data02_runtime_v2.py",
        "ds_data02_git_launch_state_v1.py", "ds_data02_git_launch_state_v2.py",
        "ds_data02_git_launch_state_v3.py",
    )
    for name in runtime_names:
        add(f"runtime_closure:{name}", SCRIPT_DIR / name)
    for role, item in phase.get("modules", {}).items():
        add(f"module:{role}", Path(str(item["path"])))
    add("decoder", Path(str(phase["decoder"]["path"])))
    source_roles: dict[str, list[str]] = {}
    for item in phase.get("source_files", []):
        path = Path(str(item["path"])).expanduser()
        role = str(item["role"])
        add(f"source:{role}", path)
        source_roles.setdefault(str(path), []).append(role)
    raw_root = Path(str(phase["raw_binding"]["data_root"])).expanduser()
    for item in sorted(raw_root.rglob("*")):
        if item.is_file():
            add(f"raw:{item.relative_to(raw_root).as_posix()}", item)
    unique: list[Path] = []
    roles_by_path: dict[str, list[str]] = {}
    for role, path in values:
        key = str(path)
        roles_by_path.setdefault(key, []).append(role)
        if path not in unique:
            unique.append(path)
    return unique, roles_by_path


def build_request(*, phase_request: Path | str, output: Path | str,
                  repo_root: Path | str, data_root: Path | str,
                  runtime_v10: Path | str = RUNTIME_V10_DEFAULT,
                  worker: Path | str = WORKER_DEFAULT,
                  attempt_id: str = "canonical65-raw-to-typed-v1") -> dict[str, Any]:
    phase_path = Path(phase_request).expanduser().resolve()
    phase = _phase(phase_path)
    phase["_phase_path"] = str(phase_path)
    runtime_path = Path(runtime_v10).expanduser().resolve()
    worker_path = Path(worker).expanduser().resolve()
    _stat(runtime_path, "runtime v10")
    _stat(worker_path, "native worker")
    repo = Path(repo_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if not repo.is_dir() or not data.is_dir():
        raise Canonical65Error("repo_root and data_root must be existing directories")
    if not isinstance(attempt_id, str) or not attempt_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in attempt_id):
        raise Canonical65Error("attempt_id contains unsafe characters")
    output_path = Path(output).expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        raise Canonical65Error(f"refusing existing request output: {output_path}")
    input_files, roles_by_path = _closure_paths(phase, runtime_v10=runtime_path, worker=worker_path)
    raw_bytes = sum(int(item.stat().st_size) for item in Path(str(phase["raw_binding"]["data_root"])).expanduser().rglob("*") if item.is_file())
    resource = phase.get("resource_request", {})
    typed_estimate = int(resource.get("typed_output_estimate_bytes", 1_191_366_281) or 0)
    output_estimate = typed_estimate + 512 * 1024 * 1024 + 128 * 1024 * 1024 + 64 * 1024 * 1024
    request: dict[str, Any] = {
        "schema": RUNTIME_REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_id": CANONICAL_ID,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "max_wall_seconds": float(resource.get("max_wall_seconds", 3600) or 3600),
        "estimated_storage_bytes": int(output_estimate),
        "raw_hash_read_bytes_stat_estimate": int(raw_bytes),
        "raw_frame_count": 401,
        "raw_file_count": 405,
        "command": [PYTHON, "-B", "-I", str(SCRIPT), "run-child",
                     "--phase-request", str(phase_path), "--output-dir",
                     "{attempt_root}/canonical65-raw-to-typed"],
        "cwd": str(SCRIPT_DIR.parent),
        "worktree_root": str(repo),
        "data_root_binding": {"path": str(data), "policy": "PARENT_OUTPUT_ROOT_EXACT"},
        "input_files": [str(path) for path in input_files],
        "input_roles": roles_by_path,
        "interpreter_binding": {"literal_path": PYTHON, "policy": "LITERAL_PINNED_VENV"},
        "phase_binding": {"path": str(phase_path), "file_sha256": _sha(phase_path, max_bytes=MAX_METADATA_BYTES),
                           "canonical_sha256": phase["phase_request_canonical_sha256"],
                           "schema": PHASE_SCHEMA, "immutable": True},
        "current_binding": {"case_index": 65, "physical_case_id": CANONICAL_ID,
                             "sha256": CURRENT_SHA, "historical_alias_rejected": HISTORICAL_ALIAS_ID},
        "native_worker_binding": {"path": str(worker_path), "sha256": _sha(worker_path, max_bytes=MAX_METADATA_BYTES),
                                   "schema": WORKER_SCHEMA, "entrypoint": "run", "run_labels": False},
        "verifier_binding": {"path": str(VERIFIER), "sha256": _sha(VERIFIER, max_bytes=MAX_METADATA_BYTES),
                              "schema": VERIFY_SCHEMA, "entrypoint": "verify", "payload_read": "bounded_report_only"},
        "parent_guard": {
            "runtime": "ds_data02_runtime_v10_git_bound",
            "reservation_before_input_content_hash": True,
            "source_hash_phase": "V10_AFTER_PARENT_RESERVATION_AND_CHILD_MATERIALIZATION",
            "raw_tree_pre_post_required": True, "source_file_pre_post_required": True,
            "typed_identity_validation": "native_worker_after_conversion",
            "no_original_path_fallback": True, "same_parent_ledger": True,
            "parent_pid_required": True,
        },
        "execution": {
            "child_action": "canonical65_materialize_then_native_worker",
            "output_root_template": "{attempt_root}/canonical65-raw-to-typed",
            "bounded_summary": True, "worker_report_is_attempt_owned": True,
            "run_labels": False, "run_evaluator": False,
            "model_invoked": False, "cfd_invoked": False,
            "source_fallback": "REJECT", "threads": 1,
        },
        "scientific_scope": {
            "identity_key": "(Zone,Idp)", "expected_cohort_count": 21114,
            "expected_frames": 401, "saved_mask_status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
            "mass_denominator_kg": 21.114001002861187,
            "source_quality": "ROOT206 saved-mask proof + native typed validation",
            "qualification": dict(UNKNOWN), "scientific_credit": "NONE_UNTIL_INDEPENDENT_VERIFIER",
        },
        "qualification": dict(UNKNOWN), "model_invoked": False, "cfd_invoked": False,
        "scientific_credit": "NONE", "ledger_mutated": False,
    }
    _reject_old_paths(request)
    request["canonical_sha256"] = _canonical(request)
    _write_new(output_path, request)
    return {"schema": RUNTIME_REQUEST_SCHEMA, "status": request["status"],
            "request": {"path": str(output_path), "file_sha256": _sha(output_path)},
            "canonical_sha256": request["canonical_sha256"], "input_file_count": len(input_files),
            "raw_hash_read_bytes_stat_estimate": raw_bytes, "estimated_storage_bytes": output_estimate,
            "worker_ready": True, "launch_allowed": True, "raw_payload_read": False,
            "ledger_mutated": False, "qualification": dict(UNKNOWN)}


def _stable_hash(path: Path, role: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    before = _stat(path, role)
    digest = _sha(path)
    after = _stat(path, role)
    if before != after:
        raise Canonical65Error(f"{role} changed while being hashed: {path}")
    return digest, before, after


def _load_bound_module(path: Path, name: str) -> Any:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Canonical65Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _raw_manifest(phase: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw = phase["raw_binding"]
    root = Path(str(raw["data_root"])).expanduser()
    converter_path = Path(str(phase["modules"]["raw_converter"]["path"])).expanduser()
    converter_expected = _require_sha(phase["modules"]["raw_converter"].get("sha256"), "raw_converter.sha256")
    if _sha(converter_path) != converter_expected:
        raise Canonical65Error("raw converter code SHA differs before materialization")
    converter = _load_bound_module(converter_path, "_ds02_canonical65_bound_converter")
    before_entries = [_stat(item, f"raw:{item.relative_to(root).as_posix()}")
                      for item in sorted(root.rglob("*")) if item.is_file()]
    manifest = converter.raw_tree_manifest(root)
    after_entries = [_stat(item, f"raw:{item.relative_to(root).as_posix()}")
                     for item in sorted(root.rglob("*")) if item.is_file()]
    if len(before_entries) != len(after_entries) or before_entries != after_entries:
        raise Canonical65Error("raw tree stat envelope changed during parent hash")
    if int(manifest.get("file_count", -1)) != 405 or len(manifest.get("files", [])) != 405:
        raise Canonical65Error("raw converter manifest does not contain the exact 405-file scope")
    frames = [item for item in manifest["files"] if Path(str(item["path"])).parent == Path(".") and str(item["path"]).startswith("Part_") and str(item["path"]).endswith(".bi4")]
    if len(frames) != 401:
        raise Canonical65Error("raw converter manifest does not contain 401 frames")
    return manifest, {"before": before_entries, "after": after_entries}, {"path": str(converter_path), "sha256": converter_expected}


def materialize_worker_request(phase_path: Path | str, output_dir: Path | str) -> tuple[Path, dict[str, Any]]:
    phase = _phase(phase_path)
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, Any]] = []
    source_by_role: dict[str, str] = {}
    for item in phase["source_files"]:
        path = Path(str(item["path"])).expanduser()
        digest, before, after = _stable_hash(path, str(item["role"]))
        source_by_role[str(item["role"])] = digest
        source_rows.append({"role": str(item["role"]), "path": str(path), "sha256": digest,
                            "content_hash_status": "VERIFIED_AFTER_PARENT_RESERVATION",
                            "pre_stat": before, "post_stat": after,
                            "content_verification_phase": "AFTER_V10_RESERVATION"})
    raw_manifest, raw_stat, converter_binding = _raw_manifest(phase)
    derived = copy.deepcopy(phase)
    derived.pop("phase_request_canonical_sha256", None)
    derived["schema"] = WORKER_SCHEMA
    derived["status"] = "READY_FOR_PARENT_GUARD"
    derived["source_hashes_preverified_by_parent"] = True
    derived["source_files"] = source_rows
    derived["raw_binding"]["expected_raw_tree_sha256"] = raw_manifest["tree_sha256"]
    derived["raw_binding"]["content_hash_status"] = "VERIFIED_AFTER_PARENT_RESERVATION"
    derived["raw_binding"]["pre_stat_envelope"] = raw_stat["before"]
    derived["raw_binding"]["post_stat_envelope"] = raw_stat["after"]
    manifest_by_path = {str(item["path"]): item for item in raw_manifest["files"]}
    for frame in derived["raw_binding"]["frames"]:
        name = Path(str(frame["path"])).name
        observed = manifest_by_path.get(name)
        if not isinstance(observed, Mapping):
            raise Canonical65Error(f"raw frame is absent from converter manifest: {name}")
        frame["sha256"] = observed["sha256"]
        frame["content_hash_status"] = "VERIFIED_AFTER_PARENT_RESERVATION"
        frame["pre_post_stat"] = next((row for row in raw_stat["before"] if Path(str(row["path"])).name == name), None)
    for role, digest in source_by_role.items():
        if role in {"current_catalog", "generated_xml", "motion_dat", "gencase_receipt", "solver_receipt", "owner_metadata", "initial_csv", "conversion_report", "native_partout", "native_runparts"}:
            pass
    derived["decoder"]["sha256"] = _sha(Path(str(derived["decoder"]["path"])))
    derived["parent_materialization"] = {
        "schema": "ds02.stage2.f2-canonical65-parent-content-materialization.v1",
        "reservation_runtime": "ds_data02_runtime_v10_git_bound",
        "reservation_before_content_hash": True,
        "raw_tree": {"tree_sha256": raw_manifest["tree_sha256"], "file_count": 405,
                     "frame_count": 401, "pre_post_stat_equal": raw_stat["before"] == raw_stat["after"]},
        "source_files": source_rows,
        "raw_converter": converter_binding,
        "original_path_fallback": "FORBIDDEN",
    }
    derived["request_id"] = str(derived.get("request_id", "")) + "-materialized"
    derived["worker_materialized_request_sha256"] = _canonical(derived)
    request_path = output / "canonical65-worker-request-ready.json"
    _write_new(request_path, derived)
    return request_path, {"raw_manifest": raw_manifest, "raw_stat": raw_stat, "source_rows": source_rows}


def _worker_summary(report: Mapping[str, Any], report_path: Path, request_path: Path,
                    output_dir: Path, materialization: Mapping[str, Any]) -> dict[str, Any]:
    typed = report.get("typed_output")
    if not isinstance(typed, Mapping):
        raise Canonical65Error("native worker report has no typed_output contract")
    typed_path = Path(str(typed.get("path", ""))).expanduser().resolve()
    if not typed_path.is_file() or typed_path.is_symlink() or not str(typed_path).startswith(str(output_dir.resolve()) + os.sep):
        raise Canonical65Error("native worker typed output escaped attempt output")
    validation = typed.get("validation")
    if not isinstance(validation, Mapping) or validation.get("status") != "PASS_TYPED_IDENTITY_LIFECYCLE_DEVELOPMENT":
        raise Canonical65Error("native worker identity/lifecycle validation did not pass")
    raw = report.get("raw_to_typed", {}).get("raw_evidence")
    if not isinstance(raw, Mapping) or raw.get("frame_count") != 401 or raw.get("file_count") != 405 or \
            raw.get("before_tree_sha256") != raw.get("after_tree_sha256"):
        raise Canonical65Error("native worker raw pre/post evidence is incomplete")
    summary = {
        "schema": SUMMARY_SCHEMA, "status": "COMPLETE_CANONICAL65_RAW_TO_TYPED_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(request_path), "sha256": _sha(request_path)},
        "worker_report": {"path": str(report_path), "sha256": _sha(report_path, max_bytes=MAX_REPORT_BYTES),
                           "schema": report.get("schema"), "status": report.get("status")},
        "raw_tree": {"before_sha256": raw.get("before_tree_sha256"), "after_sha256": raw.get("after_tree_sha256"),
                      "expected_sha256": raw.get("expected_raw_tree_sha256"), "file_count": raw.get("file_count"),
                      "frame_count": raw.get("frame_count"), "pre_post_equal": raw.get("before_tree_sha256") == raw.get("after_tree_sha256")},
        "typed_output": {"path": str(typed_path), "bytes": int(typed.get("bytes", -1)),
                          "sha256": str(typed.get("sha256")), "validation_status": validation.get("status"),
                          "identity_key": validation.get("identity_key"),
                          "cohort": validation.get("fluid_cohort"), "time": validation.get("time")},
        "source_quality": {"raw_hash_after_reservation": True, "source_pre_post_stat": True,
                           "saved_mask": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY", "identity": "(Zone,Idp)",
                           "current_sha256": CURRENT_SHA},
        "qualification": dict(UNKNOWN), "scientific_credit": "NONE",
        "materialization": {"raw_file_count": 405, "raw_frame_count": 401,
                             "source_count": len(materialization.get("source_rows", [])),
                             "reservation_runtime": "ds_data02_runtime_v10_git_bound"},
    }
    summary["sha256"] = _canonical(summary)
    return summary


def run_child(*, phase_request: Path | str, output_dir: Path | str) -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise Canonical65Error(f"refusing non-empty canonical65 child output: {output}")
    output.mkdir(parents=True, exist_ok=False)
    request_path, materialization = materialize_worker_request(phase_request, output)
    phase = _phase(phase_request)
    worker_path = Path(str(phase["modules"]["worker"]["path"])).expanduser().resolve()
    if _sha(worker_path) != str(phase["modules"]["worker"]["sha256"]):
        raise Canonical65Error("native worker source SHA differs")
    worker = _load_bound_module(worker_path, "_ds02_canonical65_native_worker")
    native_output = output / "native-worker"
    report = worker.run(request_path, native_output, io_slot_approved=True, run_labels=False,
                        run_evaluator=False, predictions_path=None)
    report_path = native_output / "raw-to-typed-to-label-report-v2.json"
    if not report_path.is_file():
        raise Canonical65Error("native worker report is missing")
    summary = _worker_summary(report, report_path, request_path, output, materialization)
    summary_path = output / "canonical65-worker-summary-v1.json"
    _write_new(summary_path, summary)
    return {"schema": SUMMARY_SCHEMA, "status": summary["status"],
            "summary_path": str(summary_path), "summary_file_sha256": _sha(summary_path),
            "report_path": str(report_path), "report_file_sha256": _sha(report_path, max_bytes=MAX_REPORT_BYTES),
            "typed_output_path": summary["typed_output"]["path"],
            "typed_output_bytes": summary["typed_output"]["bytes"],
            "typed_output_sha256": summary["typed_output"]["sha256"],
            "raw_tree_before_sha256": summary["raw_tree"]["before_sha256"],
            "raw_tree_after_sha256": summary["raw_tree"]["after_sha256"],
            "raw_opened": True, "hdf5_opened": True, "qualification": dict(UNKNOWN)}


def verify(*, runtime_request: Path | str, runtime_receipt: Path | str,
           summary_path: Path | str, output: Path | str) -> dict[str, Any]:
    request_path = Path(runtime_request).expanduser().resolve()
    request = _load_json(request_path, "canonical65 runtime request")
    receipt = _load_json(runtime_receipt, "V10 execution receipt", limit=MAX_REPORT_BYTES)
    summary = _load_json(summary_path, "canonical65 worker summary", limit=MAX_METADATA_BYTES)
    if request.get("schema") != RUNTIME_REQUEST_SCHEMA or request.get("canonical_sha256") != _canonical(request):
        raise Canonical65Error("canonical65 runtime request schema/SHA differs")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed":
        raise Canonical65Error("V10 receipt is not a completed execution receipt")
    if receipt.get("request_sha256") != _sha(request_path):
        raise Canonical65Error("V10 receipt request SHA differs")
    input_paths = {str(path) for path in request.get("input_files", [])}
    launch_hashes = receipt.get("input_hashes_at_launch")
    after_hashes = receipt.get("input_hashes_after_run")
    if not isinstance(launch_hashes, Mapping) or not isinstance(after_hashes, Mapping) or \
            set(launch_hashes) != input_paths or set(after_hashes) != input_paths:
        raise Canonical65Error("V10 receipt does not cover the complete canonical65 input closure")
    if any(not isinstance(value, str) or len(value) != 64 for value in launch_hashes.values()) or \
            any(not isinstance(value, str) or len(value) != 64 for value in after_hashes.values()):
        raise Canonical65Error("V10 input closure contains an invalid content SHA")
    verifier_binding = request.get("verifier_binding")
    if not isinstance(verifier_binding, Mapping) or verifier_binding.get("schema") != VERIFY_SCHEMA:
        raise Canonical65Error("canonical65 verifier binding is missing")
    verifier_path = Path(str(verifier_binding.get("path", ""))).expanduser().resolve()
    if verifier_path != VERIFIER or not verifier_path.is_file() or verifier_path.is_symlink():
        raise Canonical65Error("canonical65 verifier path is not the bound source")
    if verifier_binding.get("sha256") != _sha(verifier_path, max_bytes=MAX_METADATA_BYTES):
        raise Canonical65Error("canonical65 verifier source SHA differs")
    worker_binding = request.get("native_worker_binding")
    if not isinstance(worker_binding, Mapping):
        raise Canonical65Error("canonical65 native worker binding is missing")
    worker_path = Path(str(worker_binding.get("path", ""))).expanduser().resolve()
    if not worker_path.is_file() or worker_path.is_symlink() or \
            worker_binding.get("sha256") != _sha(worker_path, max_bytes=MAX_METADATA_BYTES):
        raise Canonical65Error("canonical65 native worker source SHA differs")
    phase_binding = request.get("phase_binding")
    if not isinstance(phase_binding, Mapping):
        raise Canonical65Error("canonical65 phase binding is missing")
    phase_path = Path(str(phase_binding.get("path", ""))).expanduser().resolve()
    if not phase_path.is_file() or phase_path.is_symlink() or \
            phase_binding.get("file_sha256") != _sha(phase_path, max_bytes=MAX_METADATA_BYTES):
        raise Canonical65Error("canonical65 phase source SHA differs")
    phase = _phase(phase_path)
    if phase_binding.get("canonical_sha256") != phase.get("phase_request_canonical_sha256"):
        raise Canonical65Error("canonical65 phase canonical binding differs")
    if summary.get("schema") != SUMMARY_SCHEMA or summary.get("status") != "COMPLETE_CANONICAL65_RAW_TO_TYPED_DEVELOPMENT_UNKNOWN":
        raise Canonical65Error("canonical65 worker summary is not complete")
    if summary.get("sha256") != _canonical(summary):
        raise Canonical65Error("canonical65 worker summary SHA differs")
    summary_request = summary.get("request", {})
    child_request = Path(str(summary_request.get("path", ""))).expanduser().resolve()
    if not child_request.is_file() or summary_request.get("sha256") != _sha(child_request):
        raise Canonical65Error("materialized worker request is not bound")
    worker_request = _load_json(child_request, "materialized worker request")
    if worker_request.get("schema") != WORKER_SCHEMA or worker_request.get("status") != "READY_FOR_PARENT_GUARD":
        raise Canonical65Error("materialized worker request ABI differs")
    identity = worker_request.get("case_identity", {})
    if identity.get("current_case_index") != 65 or identity.get("physical_case_id") != CANONICAL_ID:
        raise Canonical65Error("materialized worker is not canonical row 65")
    if worker_request.get("current_binding", {}).get("sha256") != CURRENT_SHA:
        raise Canonical65Error("materialized worker CURRENT SHA differs")
    if worker_request.get("worker_materialized_request_sha256") != _canonical(worker_request):
        raise Canonical65Error("materialized worker request canonical SHA differs")
    phase_request_id = phase.get("request_id")
    if not isinstance(phase_request_id, str) or not str(worker_request.get("request_id", "")).startswith(phase_request_id):
        raise Canonical65Error("materialized worker is not derived from the bound phase request")
    if worker_request.get("source_hashes_preverified_by_parent") is not True:
        raise Canonical65Error("materialized worker does not bind parent hashes")
    _reject_old_paths(worker_request)
    source_files = worker_request.get("source_files")
    if not isinstance(source_files, list) or any(
            not isinstance(item, Mapping) or _require_sha(item.get("sha256"), "source SHA") is None
            for item in source_files):
        raise Canonical65Error("materialized source closure has pending SHA")
    raw = summary.get("raw_tree", {})
    if raw.get("file_count") != 405 or raw.get("frame_count") != 401 or \
            raw.get("before_sha256") != raw.get("after_sha256") or \
            raw.get("before_sha256") != raw.get("expected_sha256"):
        raise Canonical65Error("raw tree pre/post evidence is not closed")
    report_info = summary.get("worker_report", {})
    report_path = Path(str(report_info.get("path", ""))).expanduser().resolve()
    if not report_path.is_file() or report_path.is_symlink() or report_info.get("sha256") != _sha(report_path, max_bytes=MAX_REPORT_BYTES):
        raise Canonical65Error("worker report file SHA is not bound")
    report = _load_json(report_path, "native worker report", limit=MAX_REPORT_BYTES)
    if report.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2" or report.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise Canonical65Error("native worker report status/schema is not complete")
    validation = report.get("typed_output", {}).get("validation", {})
    if validation.get("status") != "PASS_TYPED_IDENTITY_LIFECYCLE_DEVELOPMENT":
        raise Canonical65Error("typed identity/lifecycle validation is not PASS")
    if validation.get("source_current", {}).get("case_index") != 65 or validation.get("source_current", {}).get("sha256") != CURRENT_SHA:
        raise Canonical65Error("typed validation CURRENT binding differs")
    cohort = validation.get("fluid_cohort", {})
    if cohort.get("count") != 21114 or cohort.get("identity_sha256") != "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70":
        raise Canonical65Error("typed cohort identity does not match canonical65 contract")
    time_contract = validation.get("time", {})
    if time_contract.get("frame_count") != 401 or time_contract.get("strictly_increasing") is not True:
        raise Canonical65Error("typed saved-mask timeline is not closed")
    typed = summary.get("typed_output", {})
    typed_path = Path(str(typed.get("path", ""))).expanduser().resolve()
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    data_root_binding = request.get("data_root_binding")
    if not isinstance(data_root_binding, Mapping) or \
            output_root != Path(str(data_root_binding.get("path", ""))).expanduser().resolve() / "families" / "F2" / CANONICAL_ID / request["attempt_id"]:
        raise Canonical65Error("V10 output root is not the bound canonical65 data root/attempt")
    if output_root not in child_request.parents:
        raise Canonical65Error("materialized worker request escaped the V10 attempt root")
    if not typed_path.is_file() or typed_path.is_symlink() or output_root not in typed_path.parents:
        raise Canonical65Error("typed output is outside the V10 attempt root")
    if int(typed.get("bytes", -1)) != typed_path.stat().st_size:
        raise Canonical65Error("typed output stat differs from child summary")
    result = {
        "schema": VERIFY_SCHEMA, "status": "VERIFIED_CANONICAL65_RAW_TO_TYPED_DEVELOPMENT_UNKNOWN",
        "runtime_request": {"path": str(request_path), "file_sha256": _sha(request_path),
                             "canonical_sha256": request["canonical_sha256"]},
        "v10_receipt": {"path": str(Path(runtime_receipt).expanduser().resolve()),
                        "file_sha256": _sha(runtime_receipt, max_bytes=MAX_REPORT_BYTES),
                        "status": receipt.get("status"), "request_sha256": receipt.get("request_sha256"),
                        "input_hashes_at_launch_count": len(receipt.get("input_hashes_at_launch", {})),
                        "input_hashes_after_run_equal": receipt.get("input_hashes_at_launch") == receipt.get("input_hashes_after_run")},
        "worker_summary": {"path": str(Path(summary_path).expanduser().resolve()), "file_sha256": _sha(summary_path),
                           "report_path": str(report_path), "report_file_sha256": report_info.get("sha256")},
        "case_identity": {"current_index": 65, "physical_case_id": CANONICAL_ID,
                          "current_sha256": CURRENT_SHA, "historical_alias_rejected": HISTORICAL_ALIAS_ID},
        "raw_tree": dict(raw), "typed_output": dict(typed),
        "identity_validation": {"status": validation["status"], "cohort": dict(cohort), "time": dict(time_contract)},
        "scientific_credit": "NONE", "qualification": dict(UNKNOWN),
        "original_path_fallback": "FORBIDDEN", "model_invoked": False, "cfd_invoked": False,
    }
    result["sha256"] = _canonical(result)
    _write_new(output, result)
    return {"schema": VERIFY_SCHEMA, "status": result["status"], "output": str(Path(output).expanduser().resolve()),
            "output_sha256": _sha(output), "qualification": dict(UNKNOWN)}


def run_parent(*, request: Path | str, data_root: Path | str, parent_pid: int,
               runtime_v10: Path | str = RUNTIME_V10_DEFAULT) -> dict[str, Any]:
    if parent_pid <= 1 or os.getppid() != int(parent_pid):
        raise Canonical65Error("canonical65 V10 run requires its direct supervising parent PID")
    runtime_path = Path(runtime_v10).expanduser().resolve()
    bound_request = _load_json(request, "canonical65 runtime request")
    bound_data_root = bound_request.get("data_root_binding", {}).get("path")
    if not isinstance(bound_data_root, str) or Path(data_root).expanduser().resolve() != Path(bound_data_root).expanduser().resolve():
        raise Canonical65Error("run data_root differs from the bound canonical65 output root")
    runtime = _load_bound_module(runtime_path, "_ds02_canonical65_runtime_v10")
    result = runtime.run_request(Path(request).expanduser().resolve(), data_root=Path(data_root).expanduser().resolve(),
                                 parent_pid=int(parent_pid))
    output_root = result.get("output_root")
    if result.get("status") == "completed" and isinstance(output_root, str):
        attempt_root = Path(output_root).expanduser().resolve()
        summary_path = attempt_root / "canonical65-raw-to-typed" / "canonical65-worker-summary-v1.json"
        receipt_path = attempt_root / "execution-receipt.json"
        verification_path = attempt_root / "canonical65-raw-to-typed" / "canonical65-execution-verification-v1.json"
        verification = verify(runtime_request=request, runtime_receipt=receipt_path,
                              summary_path=summary_path, output=verification_path)
        result["canonical65_verification"] = verification
    result["worker_ready"] = result.get("status") == "completed"
    result["launch_allowed"] = result.get("status") == "completed"
    result["qualification"] = dict(UNKNOWN)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--phase-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--data-root", type=Path, required=True)
    build.add_argument("--runtime-v10", type=Path, default=RUNTIME_V10_DEFAULT)
    build.add_argument("--worker", type=Path, default=WORKER_DEFAULT)
    build.add_argument("--attempt-id", default="canonical65-raw-to-typed-v1")
    child = sub.add_parser("run-child")
    child.add_argument("--phase-request", type=Path, required=True)
    child.add_argument("--output-dir", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--data-root", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    run.add_argument("--runtime-v10", type=Path, default=RUNTIME_V10_DEFAULT)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--runtime-request", type=Path, required=True)
    verify_parser.add_argument("--runtime-receipt", type=Path, required=True)
    verify_parser.add_argument("--summary", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            result = build_request(phase_request=args.phase_request, output=args.output,
                                   repo_root=args.repo_root, data_root=args.data_root,
                                   runtime_v10=args.runtime_v10, worker=args.worker,
                                   attempt_id=args.attempt_id)
        elif args.command == "run-child":
            result = run_child(phase_request=args.phase_request, output_dir=args.output_dir)
        elif args.command == "verify":
            result = verify(runtime_request=args.runtime_request, runtime_receipt=args.runtime_receipt,
                            summary_path=args.summary, output=args.output)
        else:
            result = run_parent(request=args.request, data_root=args.data_root,
                                parent_pid=args.parent_pid, runtime_v10=args.runtime_v10)
    except (Canonical65Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": RUNTIME_REQUEST_SCHEMA, "status": "REJECTED", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
