#!/usr/bin/env python3
"""Execute the guarded F2 portable copy/seal/raw-replay pipeline.

The v5 bundle, overlay, and storage plan are immutable inputs.  This forward
orchestrator supplies the missing parent operation: it rechecks the existing
DS-DATA-02 ledger lease and output filesystem, copies every overlay source into
a fresh target namespace, seals every copied byte, and invokes the v5 loader
with the explicit I/O-slot flag.  It never resets the ledger, moves/deletes an
old product, or falls back to an original source path after relocation.

The copy and native replay are parent-guard operations.  ``build-request``
and a run without ``--io-slot-approved`` are metadata/stat-only.  The current
v5 native worker leaves family labels/evaluator adaptation source-bound; the
report therefore records that evaluator status explicitly as pending unless a
compatible evaluator request is supplied by a future forward version.  No
scientific qualification is granted by this orchestrator.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import time
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-portable-orchestration-request.v6"
REPORT_SCHEMA = "ds02.stage2.f2-portable-orchestration-report.v6"
V5_REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-label-portable-request.v5"
V5_BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v5"
V5_OVERLAY_SCHEMA = "ds02.stage2.f2-native-raw-portable-overlay.v5"
V5_PLAN_SCHEMA = "ds02.stage2.f2-portable-storage-plan.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class OrchestrationV6Error(RuntimeError):
    """Raised when a v6 copy/replay contract is incomplete or unsafe."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise OrchestrationV6Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise OrchestrationV6Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise OrchestrationV6Error(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise OrchestrationV6Error(f"{name} must be a lowercase SHA-256")
    return value


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise OrchestrationV6Error(f"{role} is missing: {target}")
    return target


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OrchestrationV6Error(f"cannot import bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stat_binding(path: Path | str, expected_bytes: int | None = None,
                  expected_mtime_ns: int | None = None) -> dict[str, Any]:
    target = _require_file(path, "source")
    stat = target.stat()
    if expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise OrchestrationV6Error(f"source byte stat differs: {target}")
    if expected_mtime_ns is not None and int(expected_mtime_ns) != stat.st_mtime_ns:
        raise OrchestrationV6Error(f"source mtime stat differs: {target}")
    return {"path": str(target), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _disk_probe(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    probe_root = target if target.exists() else target.parent
    if not probe_root.exists() or not probe_root.is_dir():
        raise OrchestrationV6Error(f"output filesystem probe root is unavailable: {probe_root}")
    usage = shutil.disk_usage(probe_root)
    return {"path": str(probe_root), "free_bytes": int(usage.free),
            "total_bytes": int(usage.total), "used_bytes": int(usage.used)}


def _load_inputs(v5_request_path: Path, overlay_path: Path, plan_path: Path,
                 loader_path: Path | None = None) -> dict[str, Any]:
    request = load_json(v5_request_path)
    if request.get("schema") != V5_REQUEST_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise OrchestrationV6Error("v5 request is not an executable development request")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise OrchestrationV6Error("v5 request model/CFD scope is unsafe")
    if request.get("qualification") != UNKNOWN or request.get("sha256") != canonical_sha(request):
        raise OrchestrationV6Error("v5 request is noncanonical or qualification was promoted")
    bundle_ref = request.get("bundle")
    if not isinstance(bundle_ref, Mapping):
        raise OrchestrationV6Error("v5 bundle binding is missing")
    bundle_path = _require_file(bundle_ref.get("path", ""), "v5 bundle")
    bundle = load_json(bundle_path)
    if bundle.get("schema") != V5_BUNDLE_SCHEMA or bundle.get("sha256") != canonical_sha(bundle):
        raise OrchestrationV6Error("v5 bundle is noncanonical")
    if bundle.get("sha256") != bundle_ref.get("canonical_sha256"):
        raise OrchestrationV6Error("v5 request is bound to another bundle")
    overlay = load_json(overlay_path)
    if overlay.get("schema") != V5_OVERLAY_SCHEMA or overlay.get("sha256") != canonical_sha(overlay):
        raise OrchestrationV6Error("v5 overlay is noncanonical")
    if overlay.get("bundle", {}).get("canonical_sha256") != bundle.get("sha256"):
        raise OrchestrationV6Error("v5 overlay is bound to another bundle")
    if overlay.get("original_path_fallback") != "FORBIDDEN" or overlay.get("target_paths_are_new") is not True:
        raise OrchestrationV6Error("v5 overlay permits unsafe original-path reuse")
    entries = overlay.get("entries")
    if not isinstance(entries, list) or not entries:
        raise OrchestrationV6Error("v5 overlay entries are missing")
    target_root = Path(str(overlay.get("target_root", ""))).expanduser().resolve()
    if not str(target_root).startswith("/var/tmp/"):
        raise OrchestrationV6Error("portable source target must remain below /var/tmp")
    if target_root.exists():
        raise OrchestrationV6Error(f"portable source target root already exists: {target_root}")
    relatives: set[str] = set()
    for item in entries:
        if not isinstance(item, Mapping):
            raise OrchestrationV6Error("overlay entry is malformed")
        relative = str(item.get("bundle_relative_path", ""))
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise OrchestrationV6Error(f"unsafe overlay relative path: {relative!r}")
        if relative in relatives:
            raise OrchestrationV6Error(f"duplicate overlay relative path: {relative}")
        relatives.add(relative)
        original = Path(str(item.get("original_path", ""))).expanduser().resolve()
        destination = Path(str(item.get("target_path", ""))).expanduser().resolve()
        if not original.is_file() or not _under(destination, target_root) or destination == original:
            raise OrchestrationV6Error(f"unsafe or unavailable overlay source: {original}")
        if destination != (target_root / relative).resolve():
            raise OrchestrationV6Error(f"overlay target differs from relative mapping: {destination}")
        _require_sha(item.get("expected_sha256"), f"overlay {item.get('role')}.expected_sha256")
        expected_bytes = int(item.get("expected_bytes", -1))
        if expected_bytes < 0:
            raise OrchestrationV6Error(f"overlay byte binding is missing: {item.get('role')}")
        if original.stat().st_size != expected_bytes:
            raise OrchestrationV6Error(f"overlay source byte stat differs before dispatch: {original}")
    plan_file = _require_file(plan_path, "v5 storage plan")
    plan = load_json(plan_file)
    if plan.get("schema") != V5_PLAN_SCHEMA or plan.get("sha256") != canonical_sha(plan):
        raise OrchestrationV6Error("v5 storage plan is noncanonical")
    planner_path = next((Path(str(item["original_path"])).expanduser().resolve()
                         for item in bundle.get("source_bindings", [])
                         if isinstance(item, Mapping) and item.get("role") == "portable_storage_planner_v5"), None)
    if planner_path is None:
        raise OrchestrationV6Error("v5 storage planner binding is missing")
    planner = _load_module(planner_path, "_ds02_storage_v5_for_orchestrator")
    validation = planner.validate_plan(plan_file)
    if validation.get("status") != "PASS_PARENT_SEMANTIC_AND_HEADROOM_RECHECK":
        raise OrchestrationV6Error("v5 storage plan parent recheck did not pass")
    selected_root = Path(str(plan["storage_mapping"]["selected_storage_root"])).expanduser().resolve()
    if not _under(selected_root, Path("/var/tmp").resolve()):
        raise OrchestrationV6Error("selected output root is outside /var/tmp")
    if selected_root.exists():
        raise OrchestrationV6Error(f"selected output namespace already exists: {selected_root}")
    if loader_path is None:
        loader_path = next((Path(str(item["original_path"])).expanduser().resolve()
                            for item in bundle.get("source_bindings", [])
                            if isinstance(item, Mapping) and item.get("role") == "portable_loader_v5"), None)
    if loader_path is None or not loader_path.is_file():
        raise OrchestrationV6Error("v5 portable loader binding is missing")
    return {"request": request, "bundle": bundle, "bundle_path": bundle_path,
            "overlay": overlay, "overlay_path": overlay_path.resolve(),
            "plan": plan, "plan_path": plan_file, "planner": planner,
            "loader_path": loader_path, "entries": entries,
            "target_root": target_root, "selected_root": selected_root,
            "storage_validation": validation}


def _metadata_bindings(loaded: Mapping[str, Any], script_path: Path) -> list[dict[str, Any]]:
    request = loaded["request"]
    bundle = loaded["bundle"]
    plan = loaded["plan"]
    paths: list[tuple[str, Path, str]] = [
        ("v5_request", Path(str(loaded["request_path"])), "metadata"),
        ("v5_bundle", Path(str(loaded["bundle_path"])), "metadata"),
        ("v5_overlay", Path(str(loaded["overlay_path"])), "metadata"),
        ("v5_storage_plan", Path(str(loaded["plan_path"])), "metadata"),
        ("portable_orchestrator_v6", script_path, "runtime"),
        ("portable_loader_v5", loaded["loader_path"], "runtime"),
    ]
    planner_path = next(Path(str(item["original_path"])).expanduser().resolve()
                        for item in bundle["source_bindings"]
                        if item.get("role") == "portable_storage_planner_v5")
    evaluator_path = next(Path(str(item["original_path"])).expanduser().resolve()
                          for item in bundle["source_bindings"]
                          if item.get("role") == "no_model_evaluator_v1")
    paths.extend([("portable_storage_planner_v5", planner_path, "runtime"),
                  ("no_model_evaluator_v1", evaluator_path, "runtime")])
    parent = loaded["plan"]["parent_resource_binding"]
    paths.extend([("parent_resource_ledger", Path(str(parent["path"])).expanduser().resolve(), "parent"),
                  ("stage2_checkpoint", Path(str(parent["checkpoint_path"])).expanduser().resolve(), "parent")])
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for role, path, source_kind in paths:
        path = path.expanduser().resolve()
        if str(path) in seen:
            continue
        seen.add(str(path))
        stat = _stat_binding(path)
        result.append({"role": role, "path": str(path), "bytes": stat["bytes"],
                       "mtime_ns": stat["mtime_ns"], "sha256": sha256_file(path),
                       "source_kind": source_kind})
    # Keep the complete copy closure in the request.  The v5 bundle remains
    # the authority for each source hash; this list is not a second source of
    # identity and is checked again by seal_overlay before any raw read.
    for item in loaded["entries"]:
        path = Path(str(item["original_path"])).expanduser().resolve()
        result.append({"role": str(item["role"]), "path": str(path),
                       "bytes": int(item["expected_bytes"]),
                       "mtime_ns": int(path.stat().st_mtime_ns),
                       "sha256": str(item["expected_sha256"]),
                       "source_kind": "copy_source"})
    unique: dict[str, dict[str, Any]] = {}
    for item in result:
        previous = unique.get(item["path"])
        if previous is not None and previous["sha256"] != item["sha256"]:
            raise OrchestrationV6Error(f"conflicting v6 input SHA: {item['path']}")
        unique.setdefault(item["path"], item)
    return [unique[key] for key in sorted(unique)]


def build_request(v5_request_path: Path | str, overlay_path: Path | str,
                  storage_plan_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    v5_request_file = _require_file(v5_request_path, "v5 request")
    overlay_file = _require_file(overlay_path, "v5 overlay")
    plan_file = _require_file(storage_plan_path, "v5 storage plan")
    loaded = _load_inputs(v5_request_file, overlay_file, plan_file)
    loaded = dict(loaded)
    loaded.update({"request_path": v5_request_file})
    script_path = Path(__file__).resolve()
    inputs = _metadata_bindings(loaded, script_path)
    parent = loaded["plan"]["parent_resource_binding"]
    mapping = loaded["plan"]["storage_mapping"]
    source_copy_bytes = sum(int(item["expected_bytes"]) for item in loaded["entries"])
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "request_id": "f2-s1-portable-orchestration-v6-001",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "source_hashes_preverified_by_parent": False,
        "parent_resource_binding": parent,
        "storage_plan": {"path": str(plan_file), "sha256": sha256_file(plan_file),
                          "schema": V5_PLAN_SCHEMA},
        "v5_inputs": {
            "request": {"path": str(v5_request_file), "sha256": sha256_file(v5_request_file)},
            "bundle": {"path": str(loaded["bundle_path"]), "sha256": loaded["bundle"]["sha256"]},
            "overlay": {"path": str(overlay_file), "sha256": sha256_file(overlay_file)},
        },
        "input_files": [item["path"] for item in inputs],
        "input_hashes": {item["path"]: item["sha256"] for item in inputs},
        "source_bindings": inputs,
        "copy_contract": {
            "stage": "copy_all_overlay_entries_before_any_native_open",
            "entry_count": len(loaded["entries"]),
            "source_bytes_from_overlay": source_copy_bytes,
            "target_root": str(loaded["target_root"]),
            "target_root_must_be_absent_before_copy": True,
            "destination_files_must_be_absent": True,
            "shared_parent_directories": "mkdir(parents=True, exist_ok=True) after fresh target root; never overwrite files",
            "copy_method": "byte_copy_then_seal_sha256",
            "source_paths_are_provenance_only_after_seal": True,
            "original_path_fallback": "FORBIDDEN",
        },
        "execution": {
            "command": [sys.executable, "-B", str(script_path), "run", "--request", "<request>",
                         "--io-slot-approved"],
            "stages": ["parent_ledger_recheck", "copy", "seal", "raw_to_typed_and_labels",
                       "no_model_evaluator_contract", "receipt"],
            "loader_entrypoint": str(loaded["loader_path"]),
            "copy_before_raw_read": True,
            "seal_before_raw_read": True,
            "private_fresh_python_subprocess": True,
            "private_subprocess_bytecode": "-B and PYTHONDONTWRITEBYTECODE=1",
            "private_subprocess_sys_path": "relocated runtime/output plus explicit interpreter standard/dependency roots; inherited PYTHONPATH cleared",
            "module_file_closure_report": "required; any module outside relocated runtime/output or declared interpreter roots fails",
            "original_module_cache": "unavailable in fresh child interpreter",
            "raw_bi4_hdf5_read": "parent slot only",
            "os_open_audit_required": True,
            "python_audit_is_complementary": True,
            "model_invoked": False,
            "cfd_invoked": False,
            "output_dir": str(mapping["selected_storage_root"]),
            "accessible_index_path": str(mapping["accessible_index_path"]),
            "output_index_write": "new index only after successful run; no overwrite",
        },
        "evaluator_contract": {
            "entrypoint_role": "no_model_evaluator_v1",
            "model_invoked": False,
            "scope": "source-bound result adapter required after raw-to-typed/labels; no self-comparison credit",
            "status": "BOUND_CONTRACT_PENDING_COMPATIBLE_RAW_RESULT_ADAPTER",
            "binding_errors": "reject",
            "scientific_score_errors": "FAIL status with event/mass metrics",
            "qualification": copy_unknown(),
        },
        "resource_request": {
            "cpu_threads": int(loaded["plan"]["limits"]["cpu_threads"]),
            "max_wall_seconds": int(loaded["plan"]["limits"]["max_wall_seconds"]),
            "max_rss_observational_bytes": int(loaded["plan"]["limits"]["max_rss_observational_bytes"]),
            "source_copy_bytes": source_copy_bytes,
            "new_storage_reservation_bytes": int(loaded["plan"]["storage_budget"]["required_new_storage_bytes"]),
            "storage_filesystem": str(mapping["selected_storage_root"]),
            "parent_deadline_utc": parent["deadline_utc"],
            "parent_ledger_path": parent["path"],
            "same_parent_lease_required": True,
            "ledger_reset": False,
            "home_floor_preserved": True,
            "output_fs_guard": "live disk_usage immediately before copy and before loader",
        },
        "raw_to_label_scope": loaded["bundle"].get("raw_to_typed_to_label", {}),
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy_unknown(),
        "limitations": [
            "This request adds the executable copy/seal orchestration; it does not claim that the parent I/O slot has run.",
            "Native labels remain DEVELOPMENT and all QI/QN/QE UNKNOWN.",
            "The no-model evaluator is bound as a contract and refuses incompatible raw-worker result schemas.",
            "Parent OS strace/openat is required to credit absence of original HDF5/BI4 C opens.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return request


def copy_unknown() -> dict[str, str]:
    return dict(UNKNOWN)


def _validate_request(request: Mapping[str, Any], *, verify_metadata_content: bool = False) -> dict[str, Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise OrchestrationV6Error("unsupported or non-ready v6 request")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise OrchestrationV6Error("v6 request must remain model-free DEVELOPMENT")
    if request.get("qualification") != UNKNOWN or request.get("sha256") != canonical_sha(request):
        raise OrchestrationV6Error("v6 request canonical SHA or qualification differs")
    for item in request.get("source_bindings", []):
        if not isinstance(item, Mapping):
            raise OrchestrationV6Error("v6 source binding is malformed")
        # The parent ledger is intentionally mutable within the same lease:
        # v5's semantic validator rechecks campaign/deadline/limits and
        # accepts a changed ledger content SHA.  Its old stat is provenance,
        # not a reason to reject an otherwise unchanged parent reservation.
        mutable_parent = item.get("source_kind") == "parent"
        stat = _stat_binding(item.get("path"), None if mutable_parent else item.get("bytes"),
                             None if mutable_parent else item.get("mtime_ns"))
        digest = _require_sha(item.get("sha256"), f"v6 input {item.get('role')}.sha256")
        if verify_metadata_content and item.get("source_kind") != "copy_source" and sha256_file(stat["path"]) != digest:
            raise OrchestrationV6Error(f"v6 metadata source SHA differs: {stat['path']}")
    execution = request.get("execution")
    if not isinstance(execution, Mapping) or execution.get("copy_before_raw_read") is not True or execution.get("seal_before_raw_read") is not True:
        raise OrchestrationV6Error("v6 copy/seal ordering contract is missing")
    contract = request.get("copy_contract")
    if not isinstance(contract, Mapping) or contract.get("original_path_fallback") != "FORBIDDEN":
        raise OrchestrationV6Error("v6 copy contract allows original fallback")
    return {"sources": len(request["source_bindings"]),
            "source_bytes": sum(int(item["bytes"]) for item in request["source_bindings"]),
            "copy_entries": int(contract["entry_count"])}


def _copy_overlay_entries(overlay: Mapping[str, Any]) -> dict[str, Any]:
    target_root = Path(str(overlay["target_root"])).expanduser().resolve()
    if target_root.exists():
        raise OrchestrationV6Error(f"copy target root already exists; refusing reuse: {target_root}")
    target_root.mkdir(parents=True, exist_ok=False)
    copied = 0
    total = 0
    started = time.monotonic()
    for item in overlay["entries"]:
        source = _require_file(item["original_path"], str(item.get("role", "source")))
        destination = Path(str(item["target_path"])).expanduser().resolve()
        if destination.exists() or not _under(destination, target_root):
            raise OrchestrationV6Error(f"copy destination is reused or unsafe: {destination}")
        if destination != (target_root / str(item["bundle_relative_path"])).resolve():
            raise OrchestrationV6Error(f"copy destination does not match overlay: {destination}")
        if source.stat().st_size != int(item["expected_bytes"]):
            raise OrchestrationV6Error(f"source size changed before copy: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied += 1
        total += int(destination.stat().st_size)
    return {"status": "COPIED_PENDING_SHA_SEAL", "entry_count": copied,
            "bytes": total, "elapsed_seconds": time.monotonic() - started,
            "target_root": str(target_root)}


def _write_bundle_copy(bundle: Mapping[str, Any], target_root: Path) -> Path:
    runtime = target_root / "runtime" / "portable"
    runtime.mkdir(parents=True, exist_ok=True)
    destination = runtime / "f2-s1-native-raw-to-label-bundle-v5.json"
    write_new(destination, bundle)
    return destination


def _private_loader_program() -> str:
    """Return the fresh-interpreter program used for the relocated loader.

    The v5 loader predates the portable orchestration boundary and imports its
    compare worker in-process.  Calling it in this process would leave the
    parent interpreter's module cache and ``sys.path`` in scope.  The program
    below is deliberately self-contained: the parent passes only target
    paths, the child resets ``sys.path`` before loading the relocated loader,
    and the child reports every imported module file.  The installed Python
    standard/dependency roots are explicit runtime dependencies; the original
    data/worktree roots are never added to the path.
    """
    return r'''import importlib.util
import json
import os
from pathlib import Path
import sys
import sysconfig
import traceback

runtime = Path(sys.argv[1]).resolve()
loader_path = Path(sys.argv[2]).resolve()
bundle_path = Path(sys.argv[3]).resolve()
sealed_path = Path(sys.argv[4]).resolve()
output_path = Path(sys.argv[5]).resolve()
result_path = Path(sys.argv[6]).resolve()

paths = [runtime, runtime / "portable", runtime / "relocated-runtime"]
config = sysconfig.get_paths()
for key in ("stdlib", "platstdlib", "purelib", "platlib"):
    value = config.get(key)
    if value:
        paths.append(Path(value).resolve())
sys.path[:] = list(dict.fromkeys(str(path) for path in paths if path.exists()))

def module_files():
    result = {}
    for name, value in sorted(sys.modules.items()):
        filename = getattr(value, "__file__", None)
        if isinstance(filename, str):
            try:
                result[name] = str(Path(filename).resolve())
            except OSError:
                result[name] = filename
    return result

def emit(payload):
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")

module = None
payload = {
    "schema": "ds02.stage2.f2-private-loader-subprocess.v1",
    "fresh_interpreter": True,
    "python_executable": sys.executable,
    "sys_path": list(sys.path),
    "loader_path": str(loader_path),
    "module_files": {},
    "original_path_fallback": "FORBIDDEN",
}
try:
    if not loader_path.is_file():
        raise RuntimeError("relocated loader is missing: " + str(loader_path))
    spec = importlib.util.spec_from_file_location("_ds02_relocated_portable_loader_v5", loader_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load relocated loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload["loader_module_file"] = str(Path(module.__file__).resolve())
    if Path(payload["loader_module_file"]) != loader_path:
        raise RuntimeError("loader module was not loaded from relocated target")
    result = module.run_portable(bundle_path, sealed_path, output_path,
                                 io_slot_approved=True, rehash_after_copy=True)
    payload["result"] = result
    payload["status"] = "PRIVATE_SUBPROCESS_COMPLETE"
except BaseException as error:
    payload["status"] = "PRIVATE_SUBPROCESS_FAILED"
    payload["error"] = f"{type(error).__name__}: {error}"
    payload["traceback"] = traceback.format_exc()
finally:
    payload["module_files"] = module_files()
    # A module outside the relocated runtime/output or explicitly declared
    # interpreter roots is evidence that the relocation was not closed.  In
    # particular this rejects both the original data tree and the original
    # worktree, even when a source module happens to have the same basename.
    allowed_module_roots = [runtime, output_path, output_path.parent]
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        value = config.get(key)
        if value:
            allowed_module_roots.append(Path(value).resolve())
    forbidden = []
    for name, filename in payload["module_files"].items():
        path = Path(filename)
        if not any(path == root or root in path.parents for root in allowed_module_roots):
            forbidden.append({"module": name, "path": filename})
    payload["forbidden_module_files"] = forbidden
    if forbidden and payload.get("status") == "PRIVATE_SUBPROCESS_COMPLETE":
        payload["status"] = "PRIVATE_SUBPROCESS_MODULE_CLOSURE_FAILED"
        payload["error"] = "module closure reached an original data source"
    emit(payload)
if payload.get("status") != "PRIVATE_SUBPROCESS_COMPLETE":
    raise SystemExit(3)
'''


def _run_private_loader(loader_target: Path, bundle_copy: Path, sealed_path: Path,
                        output_dir: Path, runtime_root: Path) -> dict[str, Any]:
    """Run the relocated v5 loader in a clean child interpreter.

    ``-B`` avoids bytecode writes into the copied bundle.  The child receives
    only relocated runtime paths plus the interpreter's declared standard and
    dependency roots.  It writes a new JSON receipt inside the new output
    namespace, so a failed child cannot be mistaken for a successful loader
    result printed to stdout.
    """
    result_path = output_dir / "private-loader-subprocess-v1.json"
    if result_path.exists():
        raise OrchestrationV6Error(f"private subprocess receipt already exists: {result_path}")
    command = [
        sys.executable, "-B", "-c", _private_loader_program(),
        str(runtime_root), str(loader_target), str(bundle_copy), str(sealed_path),
        str(output_dir), str(result_path),
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    # The child resets sys.path itself.  Clearing PYTHONPATH prevents an
    # inherited worktree path from becoming an implicit fallback before that
    # reset occurs.
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(command, cwd=str(runtime_root), env=env,
                               check=False, capture_output=True, text=True)
    if not result_path.is_file():
        raise OrchestrationV6Error(
            "private loader emitted no receipt: "
            f"returncode={completed.returncode}, stderr={completed.stderr[-2000:]}"
        )
    receipt = load_json(result_path)
    receipt["command"] = command[:2] + ["<private-loader-program>"] + command[4:]
    receipt["returncode"] = int(completed.returncode)
    receipt["stdout"] = completed.stdout[-4000:]
    receipt["stderr"] = completed.stderr[-4000:]
    if completed.returncode != 0 or receipt.get("status") != "PRIVATE_SUBPROCESS_COMPLETE":
        raise OrchestrationV6Error(
            f"private relocated loader failed: {receipt.get('error', receipt.get('status'))}"
        )
    return receipt


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        verify_metadata_content: bool = False) -> dict[str, Any]:
    request_file = _require_file(request_path, "v6 request")
    request = load_json(request_file)
    _validate_request(request, verify_metadata_content=verify_metadata_content)
    if not io_slot_approved:
        return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
                "execution_boundary": {"copy_started": False, "seal_started": False,
                                        "raw_opened": False, "hdf5_opened": False,
                                        "model_invoked": False, "cfd_invoked": False},
                "qualification": copy_unknown()}
    v5 = request["v5_inputs"]
    loaded = _load_inputs(Path(v5["request"]["path"]), Path(v5["overlay"]["path"]),
                          Path(request["storage_plan"]["path"]),
                          loader_path=Path(request["execution"]["loader_entrypoint"]))
    target_root = loaded["target_root"]
    selected_root = loaded["selected_root"]
    output_report_path = selected_root.parent / "orchestration-v6-report.json"
    if output_report_path.exists():
        raise OrchestrationV6Error(f"orchestration report already exists: {output_report_path}")
    fs_before = _disk_probe(selected_root.parent)
    required = int(loaded["plan"]["storage_budget"]["required_new_storage_bytes"])
    if fs_before["free_bytes"] < required:
        raise OrchestrationV6Error("output filesystem no longer satisfies storage reservation")
    copy_result = _copy_overlay_entries(loaded["overlay"])
    # Store the sealed sidecar below the fresh target root.  It is itself a
    # new product and is included in the final receipt; source entries remain
    # immutable and are never overwritten.
    sealed_path = target_root / "sealed-overlay-v6.json"
    loader = _load_module(loaded["loader_path"], "_ds02_portable_loader_v5_for_v6")
    seal_result = loader.seal_overlay(loaded["overlay_path"], sealed_path)
    bundle_copy = _write_bundle_copy(loaded["bundle"], target_root)
    fs_after_copy = _disk_probe(selected_root.parent)
    if fs_after_copy["free_bytes"] < required:
        raise OrchestrationV6Error("output filesystem reservation failed after source copy")
    loader_target = next((Path(str(item["target_path"])).expanduser().resolve()
                          for item in loaded["entries"]
                          if item.get("role") == "portable_loader_v5"), None)
    if loader_target is None or not loader_target.is_file():
        raise OrchestrationV6Error("relocated portable loader target is missing")
    loader_result = _run_private_loader(loader_target, bundle_copy, sealed_path,
                                        selected_root, target_root / "runtime")
    nested_result = loader_result.get("result", {})
    nested_status = nested_result.get("status") if isinstance(nested_result, Mapping) else None
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_RAW_REPLAY_DEVELOPMENT_UNKNOWN" if isinstance(nested_status, str) and nested_status.startswith("COMPLETE") else "RAW_REPLAY_RETURNED",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "parent_resource": {"ledger_path": loaded["plan"]["parent_resource_binding"]["path"],
                             "deadline_utc": loaded["plan"]["parent_resource_binding"]["deadline_utc"],
                             "lease_preserved": True, "ledger_reset": False},
        "filesystem": {"before": fs_before, "after_copy": fs_after_copy,
                        "required_new_storage_bytes": required,
                        "accessible_index_path": loaded["plan"]["storage_mapping"]["accessible_index_path"],
                        "large_output_root": str(selected_root)},
        "stages": {
            "copy": copy_result,
            "seal": seal_result,
            "raw_to_typed_loader": loader_result,
            "no_model_evaluator": {"status": "PENDING_COMPATIBLE_RAW_RESULT_ADAPTER",
                                    "model_invoked": False,
                                    "qualification": copy_unknown()},
        },
        "bundle_copy": str(bundle_copy),
        "sealed_overlay": str(sealed_path),
        "private_subprocess": {
            "fresh_interpreter": loader_result.get("fresh_interpreter") is True,
            "bytecode_disabled": True,
            "sys_path": loader_result.get("sys_path", []),
            "module_files": loader_result.get("module_files", {}),
            "forbidden_module_files": loader_result.get("forbidden_module_files", []),
            "receipt": str(selected_root / "private-loader-subprocess-v1.json"),
        },
        "original_path_fallback": "FORBIDDEN",
        "os_open_audit_required": True,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy_unknown(),
        "limitations": [
            "Parent OS strace/openat must independently verify no original HDF5/BI4 C opens.",
            "The private Python module closure is reported and rejects original source/worktree modules; it cannot observe native C HDF5/BI4 opens.",
            "Native worker labels are development evidence; no QI/QN/QE credit is awarded.",
            "No-model evaluator contract is bound but cannot score the v5 native result until a result-schema adapter is supplied.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    write_new(output_report_path, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v5-request", type=Path, required=True)
    build.add_argument("--overlay", type=Path, required=True)
    build.add_argument("--storage-plan", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--verify-metadata-content", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v5_request, args.overlay, args.storage_plan, args.output)
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        verify_metadata_content=args.verify_metadata_content)
    except (OrchestrationV6Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": value.get("schema", SCHEMA), "status": value.get("status"),
                      "qualification": value.get("qualification", UNKNOWN)}, sort_keys=True,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
