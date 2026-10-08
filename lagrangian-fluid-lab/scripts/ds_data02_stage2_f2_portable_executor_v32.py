#!/usr/bin/env python3
"""Execute the source-bound F2 portable raw-to-label chain in a new namespace.

The v31 files are immutable provenance and contract files.  They do not make
the v25 runner consume the v29 path map.  This forward entry point is the
actionable boundary that was missing:

``copy -> seal -> private raw/typed/label worker -> private evaluator``.

Every data and code role is copied to a fresh target root, every copied byte
is SHA-256 checked before a native open, and all requests used after the copy
are generated from the copied paths.  Original paths remain provenance only.
The native worker is launched in a closed ``python -B -I`` subprocess; the
evaluator is a second closed subprocess.  Both are optional only at the
explicitly declared stage boundary: without a fresh independent proof the
evaluator returns ``PENDING_FRESH_INDEPENDENT_PROOF`` and the executor cannot
claim a complete chain.

This module owns no resource ledger.  The caller must launch it as a child of
the shared stage2 guard with the request's reservation and
``--io-slot-approved``.  It does not read HDF5/BI4 in preflight mode.
Qualification is always UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
REQUEST_SCHEMA = "ds02.stage2.f2-portable-executor-request.v32"
REPORT_SCHEMA = "ds02.stage2.f2-portable-executor-report.v32"
OVERLAY_SCHEMA = "ds02.stage2.f2-portable-executor-overlay.v32"
ERROR_PREFIX = "portable v32: "


class PortableExecutorError(RuntimeError):
    """An immutable-source, relocation, or stage-boundary error."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=_json_default).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableExecutorError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise PortableExecutorError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise PortableExecutorError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")
    return target


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise PortableExecutorError(f"{name} must be a lowercase SHA-256")
    return value


def _safe_rel(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PortableExecutorError(f"{name} must be a relative POSIX path")
    rel = PurePosixPath(value)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise PortableExecutorError(f"unsafe relative path in {name}: {value!r}")
    return str(rel)


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PortableExecutorError(f"{role} is missing: {target}")
    return target


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _new_child(path: Path, root: Path, name: str) -> Path:
    target = path.expanduser().resolve()
    root = root.expanduser().resolve()
    if target.exists():
        raise PortableExecutorError(f"{name} destination already exists: {target}")
    if not _within(target, root) or target == root:
        raise PortableExecutorError(f"{name} must be a fresh child of {root}: {target}")
    return target


def _v31_binding(request: Mapping[str, Any], key: str) -> tuple[Path, str]:
    item = request.get(key)
    if not isinstance(item, Mapping):
        raise PortableExecutorError(f"request.{key} binding is missing")
    path = _require_file(item.get("path"), key)
    expected = _sha(item.get("sha256"), f"request.{key}.sha256")
    actual = sha256_file(path)
    if actual != expected:
        raise PortableExecutorError(f"{key} SHA differs from request")
    return path, expected


def _load_request(path: Path | str) -> dict[str, Any]:
    request_path = _require_file(path, "v32 request")
    request = load_json(request_path)
    if request.get("schema") != REQUEST_SCHEMA:
        raise PortableExecutorError(f"request schema differs: {request.get('schema')!r}")
    if request.get("sha256") != canonical_sha(request):
        raise PortableExecutorError("request canonical SHA differs")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise PortableExecutorError("request must be model-free DEVELOPMENT")
    if request.get("cfd_invoked") is not False or request.get("qualification") != UNKNOWN:
        raise PortableExecutorError("request must keep CFD false and QI/QN/QE UNKNOWN")
    execution = request.get("execution")
    if not isinstance(execution, Mapping) or execution.get("original_path_fallback") != "FORBIDDEN":
        raise PortableExecutorError("request does not forbid original-path fallback")
    return request


def _validate_source_entries(request: Mapping[str, Any], *, verify_content: bool) -> list[dict[str, Any]]:
    entries = request.get("source_entries")
    if not isinstance(entries, list) or not entries:
        raise PortableExecutorError("source_entries are required")
    checked: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    seen_paths: set[str] = set()
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise PortableExecutorError(f"source_entries[{index}] is malformed")
        role = raw.get("role")
        if not isinstance(role, str) or not role:
            raise PortableExecutorError(f"source_entries[{index}] role is missing")
        if role in seen_roles and role != "raw_frame_input":
            raise PortableExecutorError(f"duplicate source role: {role}")
        seen_roles.add(role)
        path = _require_file(raw.get("path"), role)
        path_string = str(path)
        if path_string in seen_paths:
            raise PortableExecutorError(f"duplicate source path: {path}")
        seen_paths.add(path_string)
        expected = _sha(raw.get("sha256"), f"source_entries[{index}].sha256")
        stat = path.stat()
        expected_bytes = int(raw.get("bytes", -1))
        if stat.st_size != expected_bytes:
            raise PortableExecutorError(f"source byte stat differs for {role}")
        item = dict(raw)
        item.update({"role": role, "path": path_string, "bytes": int(stat.st_size),
                     "mtime_ns": int(stat.st_mtime_ns), "sha256": expected})
        if verify_content and sha256_file(path) != expected:
            raise PortableExecutorError(f"source SHA differs for {role}")
        checked.append(item)
    return checked


def _copy_one(source: Path, target: Path, expected_sha: str, expected_bytes: int) -> dict[str, Any]:
    if target.exists():
        raise PortableExecutorError(f"refusing existing copied target: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    stat = target.stat()
    if stat.st_size != expected_bytes or sha256_file(target) != expected_sha:
        raise PortableExecutorError(f"copied target content differs: {target}")
    return {"path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": expected_sha}


def _runtime_copy(request: Mapping[str, Any], target_root: Path, runtime_root: Path) -> list[dict[str, Any]]:
    sources = request.get("runtime_sources")
    if not isinstance(sources, list) or not sources:
        raise PortableExecutorError("runtime_sources are required")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in sources:
        if not isinstance(raw, Mapping):
            raise PortableExecutorError("runtime source is malformed")
        role = str(raw.get("role", ""))
        rel = _safe_rel(raw.get("target_relative_path"), f"runtime {role}.target_relative_path")
        if rel in seen:
            raise PortableExecutorError(f"duplicate runtime target: {rel}")
        seen.add(rel)
        source = _require_file(raw.get("path"), role)
        expected = _sha(raw.get("sha256"), f"runtime {role}.sha256")
        expected_bytes = int(raw.get("bytes", -1))
        if source.stat().st_size != expected_bytes or sha256_file(source) != expected:
            raise PortableExecutorError(f"runtime source changed: {role}")
        target = (runtime_root / rel).resolve()
        if not _within(target, target_root):
            raise PortableExecutorError(f"runtime target escapes target root: {target}")
        copied = _copy_one(source, target, expected, expected_bytes)
        copied.update({"role": role, "source_path_provenance": str(source),
                       "target_relative_path": rel})
        # A venv executable is commonly a symlink whose resolved binary is a
        # system interpreter.  Preserve the invocation path in the binding;
        # resolving it would silently select the ABI-incompatible system
        # interpreter and lose the venv site-packages.
        if role == "python_executable" and isinstance(raw.get("invocation_path"), str):
            copied["invocation_path"] = raw["invocation_path"]
        results.append(copied)
    return results


def _overlay_from_template(template: Mapping[str, Any], target_root: Path) -> dict[str, Any]:
    if template.get("schema") != "ds02.stage2.f2-native-raw-portable-overlay.v5":
        raise PortableExecutorError("v5 overlay template schema differs")
    entries = template.get("entries")
    if not isinstance(entries, list) or not entries:
        raise PortableExecutorError("v5 overlay entries are missing")
    result = copy.deepcopy(dict(template))
    result["schema"] = OVERLAY_SCHEMA
    result["derived_from_overlay_sha256"] = template.get("sha256")
    result["target_root"] = str(target_root)
    result["content_hash_verified"] = False
    result["status"] = "READY_FOR_COPY"
    result["original_path_fallback"] = "FORBIDDEN"
    target_paths: set[str] = set()
    for item in result["entries"]:
        rel = _safe_rel(item.get("bundle_relative_path"), "overlay.bundle_relative_path")
        target = (target_root / rel).resolve()
        if not _within(target, target_root) or str(target) in target_paths:
            raise PortableExecutorError(f"unsafe or duplicate overlay target: {target}")
        target_paths.add(str(target))
        item["target_path"] = str(target)
        item.pop("target_bytes", None)
        item.pop("target_mtime_ns", None)
        item.pop("target_sha256", None)
        item["content_hash_status"] = "PENDING_PARENT_COPY"
    result["forbidden_original_prefixes"] = sorted({
        str(Path(item["original_path"]).expanduser().resolve())
        for item in result["entries"]
    })
    result["target_paths_are_new"] = True
    result["sha256"] = canonical_sha(result)
    return result


def _overlay_entry(overlay: Mapping[str, Any], role: str) -> dict[str, Any]:
    values = [dict(item) for item in overlay.get("entries", [])
              if isinstance(item, Mapping) and item.get("role") == role]
    if len(values) != 1:
        raise PortableExecutorError(f"overlay role is not unique: {role}")
    return values[0]


def _load_target_loader(runtime: Mapping[str, Any], name: str) -> Any:
    item = next((x for x in runtime.values() if x.get("role") == name), None)
    if not isinstance(item, Mapping):
        raise PortableExecutorError(f"runtime role is missing: {name}")
    path = Path(str(item["path"])).resolve()
    spec = importlib.util.spec_from_file_location(f"_ds02_bound_{name}", path)
    if spec is None or spec.loader is None:
        raise PortableExecutorError(f"cannot load copied runtime role: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_aliases(loader: Any, overlay: Mapping[str, Any], output_dir: Path) -> tuple[Path, dict[str, Path]]:
    # The relocation implementation is the already tested v5 loader, but it
    # is loaded from the copied runtime above.  No source worktree module is
    # imported for this stage.
    aliases_dir = output_dir / "relocated-runtime"
    if aliases_dir.exists():
        raise PortableExecutorError(f"refusing existing alias directory: {aliases_dir}")
    v4_path, aliases = loader._prepare_relocated_requests(overlay, output_dir)
    return v4_path, {str(key): Path(value).resolve() for key, value in aliases.items()}


def _private_audit(python: Path, runtime_root: Path, roles: Sequence[str], output: Path) -> dict[str, Any]:
    code = (
        "import importlib.util,json,sys,pathlib; "
        "root=pathlib.Path(sys.argv[1]).resolve(); roles=json.loads(sys.argv[2]); out={}; "
        "\nfor role,path in roles.items(): "
        " spec=importlib.util.spec_from_file_location('_audit_'+role,path); "
        " m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
        " actual=pathlib.Path(m.__file__).resolve(); "
        " out[role]={'module_file':str(actual),'under_runtime':root==actual or root in actual.parents}; "
        "\nassert all(v['under_runtime'] for v in out.values()),out; print(json.dumps(out,sort_keys=True))"
    )
    payload = json.dumps(dict(roles), sort_keys=True)
    proc = subprocess.run([str(python), "-B", "-I", "-c", code, str(runtime_root), payload],
                          check=False, capture_output=True, text=True,
                          env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"})
    if proc.returncode != 0:
        raise PortableExecutorError(f"private runtime module audit failed: {proc.stderr.strip()}")
    value = json.loads(proc.stdout.strip())
    write_new(output, {"schema": "ds02.stage2.f2-private-runtime-audit.v1",
                       "status": "PASS_CLOSED_RUNTIME_MODULE_FILES",
                       "fresh_interpreter": True, "modules": value,
                       "original_path_fallback": "FORBIDDEN"})
    return value


def _child_group_terminate(proc: subprocess.Popen[str], grace: float = 25.0) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def _run_private_worker(python: Path, worker: Path, request: Path, output: Path,
                        *, deadline: float | None) -> tuple[int, str, str]:
    command = [str(python), "-B", "-I", str(worker), "run", "--request", str(request),
               "--output-dir", str(output), "--io-slot-approved", "--run-labels"]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    proc = subprocess.Popen(command, start_new_session=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    try:
        stdout, stderr = proc.communicate(timeout=None if deadline is None else max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _child_group_terminate(proc)
        stdout, stderr = proc.communicate()
        return 124, stdout, stderr + "\nprivate worker deadline exceeded"
    return int(proc.returncode), stdout, stderr


def _rewrite_evaluator_request(source: Mapping[str, Any], *, result: Path, frozen: Path,
                               proof: Path, raw_report: Path, runtime: Mapping[str, Any],
                               output: Path) -> dict[str, Any]:
    request = copy.deepcopy(dict(source))
    if request.get("schema") != "ds02.stage2.f2-no-model-evaluator-request.v4":
        raise PortableExecutorError("evaluator source request must be v4")
    bindings = {"v16_label_result": result, "frozen_v15_request": frozen,
                "independent_raw_proof": proof, "raw_to_label_report": raw_report}
    items = request.get("input_files")
    if not isinstance(items, list):
        raise PortableExecutorError("evaluator input_files are missing")
    seen: set[str] = set()
    rewritten: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            raise PortableExecutorError("evaluator input binding is malformed")
        item = dict(raw)
        role = str(item.get("role", ""))
        if role in bindings:
            if role in seen:
                raise PortableExecutorError(f"duplicate evaluator role: {role}")
            target = _require_file(bindings[role], role)
            item["path"] = str(target)
            item["bytes"] = int(target.stat().st_size)
            item["mtime_ns"] = int(target.stat().st_mtime_ns)
            item["sha256"] = sha256_file(target)
            seen.add(role)
        rewritten.append(item)
    if set(bindings) != seen:
        raise PortableExecutorError(f"evaluator roles not rebound: {sorted(set(bindings)-seen)}")
    request["input_files"] = rewritten
    for key, role in (("result", "v16_label_result"), ("frozen_request", "frozen_v15_request"),
                      ("independent_proof", "independent_raw_proof"),
                      ("raw_to_label_report", "raw_to_label_report")):
        binding = request.get(key)
        if not isinstance(binding, Mapping):
            raise PortableExecutorError(f"evaluator.{key} binding is missing")
        binding = dict(binding)
        binding["path"] = str(bindings[role].resolve())
        binding["sha256"] = sha256_file(bindings[role])
        request[key] = binding
    evaluator_role = next((x for x in runtime.values() if x.get("role") == "evaluator_v4"), None)
    if not isinstance(evaluator_role, Mapping):
        raise PortableExecutorError("copied evaluator_v4 runtime role is missing")
    command = list(request.get("execution", {}).get("command", []))
    if len(command) < 2:
        raise PortableExecutorError("evaluator command is malformed")
    python_binding = runtime["python_executable"]
    command[0] = str(python_binding.get("invocation_path", python_binding["path"]))
    command[1] = str(evaluator_role["path"])
    request["execution"] = dict(request.get("execution", {}), command=command,
                                 fresh_result_required=True, original_path_fallback="FORBIDDEN")
    request["portable_executor"] = {"schema": REQUEST_SCHEMA,
                                     "fresh_result_sha256": sha256_file(result),
                                     "fresh_raw_report_sha256": sha256_file(raw_report),
                                     "copied_runtime_root": str(Path(evaluator_role["path"]).parent),
                                     "original_path_fallback": "FORBIDDEN"}
    request["sha256"] = canonical_sha(request)
    write_new(output, request)
    return request


def _run_private_evaluator(python: Path, evaluator: Path, request: Path, output: Path,
                          *, deadline: float | None) -> tuple[int, str, str]:
    command = [str(python), "-B", "-I", str(evaluator), "run", "--request", str(request),
               "--output", str(output)]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    proc = subprocess.Popen(command, start_new_session=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    try:
        stdout, stderr = proc.communicate(timeout=None if deadline is None else max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _child_group_terminate(proc)
        stdout, stderr = proc.communicate()
        return 124, stdout, stderr + "\nprivate evaluator deadline exceeded"
    return int(proc.returncode), stdout, stderr


def build_request(*, v31_request: Path | str, v31_contract: Path | str,
                  bundle: Path | str, overlay: Path | str, evaluator: Path | str,
                  output: Path | str, contract_output: Path | str | None = None,
                  target_root: Path | str | None = None, output_root: Path | str | None = None) -> dict[str, Any]:
    """Build the executable v32 request without reading raw/HDF5 content."""
    v31_path = _require_file(v31_request, "v31 request")
    contract_path = _require_file(v31_contract, "v31 contract")
    bundle_path = _require_file(bundle, "v5 bundle")
    overlay_path = _require_file(overlay, "v5 overlay")
    evaluator_path = _require_file(evaluator, "v4 evaluator request")
    v31 = load_json(v31_path)
    contract = load_json(contract_path)
    bundle_value = load_json(bundle_path)
    overlay_value = load_json(overlay_path)
    evaluator_value = load_json(evaluator_path)
    if contract.get("sha256") != canonical_sha(contract):
        raise PortableExecutorError("v31 contract canonical SHA differs")
    if bundle_value.get("schema") != "ds02.stage2.f2-native-raw-to-label-bundle.v5":
        raise PortableExecutorError("v5 bundle schema differs")
    if bundle_value.get("sha256") != canonical_sha(bundle_value):
        raise PortableExecutorError("v5 bundle canonical SHA differs")
    if overlay_value.get("sha256") != canonical_sha(overlay_value):
        raise PortableExecutorError("v5 overlay canonical SHA differs")
    if evaluator_value.get("schema") != "ds02.stage2.f2-no-model-evaluator-request.v4":
        raise PortableExecutorError("evaluator v4 request schema differs")
    checked = []
    for item in overlay_value.get("entries", []):
        if not isinstance(item, Mapping):
            raise PortableExecutorError("v5 overlay entry is malformed")
        source = _require_file(item.get("original_path"), str(item.get("role")))
        expected = _sha(item.get("expected_sha256"), f"overlay {item.get('role')}.expected_sha256")
        size = int(item.get("expected_bytes", -1))
        if source.stat().st_size != size:
            raise PortableExecutorError(f"overlay source byte stat differs: {source}")
        checked.append({"role": str(item.get("role")), "path": str(source),
                        "target_relative_path": _safe_rel(item.get("bundle_relative_path"), "bundle_relative_path"),
                        "bytes": size, "mtime_ns": int(source.stat().st_mtime_ns), "sha256": expected})
    troot = Path(target_root or contract.get("v29_bundle", {}).get("path_map", {}).get("fresh_target_root", ""))
    oroot = Path(output_root or contract.get("v29_bundle", {}).get("path_map", {}).get("fresh_output_root", ""))
    if not str(troot) or not str(oroot):
        raise PortableExecutorError("fresh target/output roots are required")
    troot = troot.expanduser().resolve(); oroot = oroot.expanduser().resolve()
    if troot == oroot:
        raise PortableExecutorError("target and output roots must be distinct")
    # The executor never uses the frozen V25 destination as an actionable root.
    frozen_roots = {str(contract.get("v29_bundle", {}).get("path_map", {}).get(k, ""))
                    for k in ("frozen_target_root", "frozen_v25_output_root")}
    if str(troot) in frozen_roots or str(oroot) in frozen_roots:
        raise PortableExecutorError("fresh roots collide with frozen V25 roots")
    runtime_specs: list[dict[str, Any]] = []
    inherited_command = v31.get("execution", {}).get("portable_full_chain_command", [])
    inherited_python = Path(inherited_command[0]) if isinstance(inherited_command, list) and inherited_command else None
    venv_python = inherited_python if inherited_python is not None and inherited_python.is_file() else (
        SCRIPT_DIR.parent / ".venv" / "bin" / "python"
    )
    if not venv_python.is_file():
        # Keep an explicit invocation path whenever this checkout does not
        # carry its own venv.  ``sys.executable`` may already be resolved to
        # /usr/bin/python3.10 even when the caller entered through a venv
        # symlink, so it is only the last fallback.
        venv_python = Path(sys.executable)
    runtime_files = [
        ("executor_v32", SCRIPT, "runtime/executor/ds_data02_stage2_f2_portable_executor_v32.py"),
        ("portable_loader_v5", SCRIPT_DIR / "ds_data02_stage2_f2_raw_portable_v5.py", "runtime/portable/ds_data02_stage2_f2_raw_portable_v5.py"),
        ("raw_worker_v2", SCRIPT_DIR / "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py", "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"),
        ("evaluator_v4", SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v4.py", "runtime/evaluator/ds_data02_stage2_f2_no_model_evaluator_v4.py"),
        ("evaluator_v3", SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v3.py", "runtime/evaluator/ds_data02_stage2_f2_no_model_evaluator_v3.py"),
        ("evaluator_v2", SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v2.py", "runtime/evaluator/ds_data02_stage2_f2_no_model_evaluator_v2.py"),
        ("evaluator_v4_source_request", evaluator_path, "runtime/evaluator/frozen-evaluator-v4-source-request.json"),
        ("operator_v14", SCRIPT_DIR / "ds_data02_stage2_f2_replay_v14.py", "runtime/evaluator/ds_data02_stage2_f2_replay_v14.py"),
        ("operator_v15", SCRIPT_DIR / "ds_data02_stage2_f2_replay_v15.py", "runtime/evaluator/ds_data02_stage2_f2_replay_v15.py"),
        ("operator_v16", SCRIPT_DIR / "ds_data02_stage2_f2_flux_v16.py", "runtime/evaluator/ds_data02_stage2_f2_flux_v16.py"),
        ("python_executable", venv_python, "runtime/python/.venv-python"),
    ]
    for role, path, relative in runtime_files:
        invocation_path = Path(path)
        path = _require_file(path, role)
        item = {"role": role,
                # Keep the venv symlink as the invocation path; content
                # verification follows it, but the request must not replace
                # it with the ABI-incompatible resolved system binary.
                "path": str(invocation_path) if role == "python_executable" else str(path),
                "target_relative_path": relative,
                              "bytes": int(path.stat().st_size), "mtime_ns": int(path.stat().st_mtime_ns),
                              "sha256": sha256_file(path)}
        if role == "python_executable":
            item["invocation_path"] = str(invocation_path)
        runtime_specs.append(item)
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-portable-executor-v32-035",
        "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "case_id": v31.get("case_id"), "family_id": v31.get("family_id"),
        "v31_request": {"path": str(v31_path), "sha256": sha256_file(v31_path)},
        "v31_contract": {"path": str(contract_path), "sha256": sha256_file(contract_path),
                         "canonical_sha256": contract.get("sha256")},
        "v5_bundle": {"path": str(bundle_path), "sha256": sha256_file(bundle_path),
                       "canonical_sha256": bundle_value.get("sha256")},
        "v5_overlay_template": {"path": str(overlay_path), "sha256": sha256_file(overlay_path),
                                 "canonical_sha256": overlay_value.get("sha256")},
        "evaluator_v4_source_request": {"path": str(evaluator_path), "sha256": sha256_file(evaluator_path)},
        "fresh_roots": {"target_root": str(troot), "output_root": str(oroot)},
        "source_entries": checked,
        "runtime_sources": runtime_specs,
        "execution": {
            "command": [str(Path(sys.executable)), "-B", "-I", str(SCRIPT), "run",
                         "--request", "<this-request>", "--io-slot-approved", "--parent-pid", "<parent-pid>",
                         "--max-wall-seconds", "6000"],
            "evaluator_command": [str(Path(sys.executable)), "-B", "-I", str(SCRIPT), "evaluate",
                                  "--request", "<this-request>", "--evaluator-proof", "<fresh-proof>",
                                  "--parent-pid", "<parent-pid>"],
            "stages": ["copy_overlay", "seal_overlay", "private_raw_to_typed_to_label",
                       "private_sdk_module_audit", "private_no_model_evaluator"],
            "fresh_subprocess": True, "bytecode": "-B", "isolated_python": "-I",
            "original_path_fallback": "FORBIDDEN", "os_open_audit_required": True,
            "parent_owns_ledger": True, "hdf5_or_bi4_read": "only after parent --io-slot-approved",
        },
        "parent_resource_binding": copy.deepcopy(v31.get("parent_resource_binding", {})),
        "storage_scope": copy.deepcopy(v31.get("storage_scope", {})),
        "raw_opened": False, "hdf5_opened": False, "model_invoked": False,
        "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "fresh_result_required": True,
        "evaluator_policy": {
            "independent_proof_required": True,
            "old_v16_result_substitution": "FORBIDDEN",
            "pending_status_without_fresh_proof": "PENDING_FRESH_INDEPENDENT_PROOF",
        },
        "limitations": [
            "The parent shared stage2 guard must reserve and charge copy, raw worker, evaluator, and OS trace bytes.",
            "The copied typed reference HDF5 is a comparison/provenance input; raw BI4 reconstruction remains required.",
            "No QI/QN/QE credit is granted; a fresh independent proof is required before evaluator PASS.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output, request)
    if contract_output is not None:
        contract_value = {
            "schema": "ds02.stage2.f2-portable-executor-contract.v1",
            "role": "DEVELOPMENT", "status": "EXECUTABLE_PARENT_GUARDED_UNKNOWN",
            "request": {"path": str(Path(output).expanduser().resolve()), "sha256": request["sha256"]},
            "stages": request["execution"]["stages"],
            "fresh_roots": request["fresh_roots"],
            "source_entry_count": len(checked), "runtime_source_count": len(runtime_specs),
            "copy_entry_bytes": sum(item["bytes"] for item in checked),
            "original_path_fallback": "FORBIDDEN", "model_invoked": False, "cfd_invoked": False,
            "qualification": dict(UNKNOWN),
        }
        contract_value["sha256"] = canonical_sha(contract_value)
        write_new(contract_output, contract_value)
    return {"path": str(Path(output).expanduser().resolve()), "sha256": request["sha256"],
            "source_entry_count": len(checked), "runtime_source_count": len(runtime_specs),
            "copy_entry_bytes": sum(item["bytes"] for item in checked)}


def preflight(request_path: Path | str, output: Path | str) -> dict[str, Any]:
    request = _load_request(request_path)
    sources = _validate_source_entries(request, verify_content=False)
    runtime = request.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableExecutorError("runtime_sources are missing")
    for item in runtime:
        if not isinstance(item, Mapping):
            raise PortableExecutorError("runtime source is malformed")
        _require_file(item.get("path"), str(item.get("role")))
        _sha(item.get("sha256"), f"runtime {item.get('role')}.sha256")
    result = {
        "schema": "ds02.stage2.f2-portable-executor-preflight.v1",
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "request": {"path": str(Path(request_path).expanduser().resolve()), "sha256": sha256_file(request_path)},
        "source_entry_count": len(sources), "runtime_source_count": len(runtime),
        "content_hash_read": False, "hdf5_or_bi4_read": False,
        "copy_required": True, "seal_required": True,
        "original_path_fallback": "FORBIDDEN", "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
    }
    result["sha256"] = canonical_sha(result)
    write_new(output, result)
    return result


def run(request_path: Path | str, *, io_slot_approved: bool, parent_pid: int | None = None,
        evaluator_proof: Path | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    request = _load_request(request_path)
    if not io_slot_approved:
        raise PortableExecutorError("run requires --io-slot-approved from the parent guard")
    if parent_pid is not None and (parent_pid <= 1 or not Path(f"/proc/{parent_pid}").exists()):
        raise PortableExecutorError("parent guard process is not alive")
    started = time.monotonic()
    deadline = started + max_wall_seconds if max_wall_seconds else None
    sources = _validate_source_entries(request, verify_content=True)
    target_root = Path(request["fresh_roots"]["target_root"]).expanduser().resolve()
    output_root = Path(request["fresh_roots"]["output_root"]).expanduser().resolve()
    # Both roots are deliberately created only after all metadata validation.
    # Existing roots/products are never reused.
    if target_root.exists() or output_root.exists():
        raise PortableExecutorError("fresh target/output root already exists")
    target_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    target_root.mkdir()
    output_root.mkdir()
    copy_records: list[dict[str, Any]] = []
    overlay_template = load_json(request["v5_overlay_template"]["path"])
    overlay = _overlay_from_template(overlay_template, target_root)
    by_path = {str(Path(item["path"]).expanduser().resolve()): item for item in sources}
    for item in overlay["entries"]:
        source = Path(item["original_path"]).expanduser().resolve()
        source_item = by_path.get(str(source))
        if source_item is None:
            raise PortableExecutorError(f"overlay source missing from request closure: {source}")
        copy_records.append(_copy_one(source, Path(item["target_path"]),
                                      item["expected_sha256"], int(item["expected_bytes"])))
    runtime_root = target_root / "runtime"
    runtime_records = _runtime_copy(request, target_root, runtime_root)
    # Seal again from the newly materialized overlay; the loader's canonical
    # SHA is a fresh sidecar and does not mutate the v5 template.
    sealed_entries = []
    for item in overlay["entries"]:
        target = Path(item["target_path"])
        stat = target.stat()
        actual = sha256_file(target)
        if int(stat.st_size) != int(item["expected_bytes"]) or actual != item["expected_sha256"]:
            raise PortableExecutorError(f"post-copy seal differs: {target}")
        value = dict(item)
        value.update({"target_bytes": int(stat.st_size), "target_mtime_ns": int(stat.st_mtime_ns),
                      "target_sha256": actual, "content_hash_status": "VERIFIED_AFTER_COPY"})
        sealed_entries.append(value)
    overlay["entries"] = sealed_entries
    overlay["status"] = "CONTENT_SHA_VERIFIED_AFTER_COPY; READY_FOR_NATIVE_OPEN"
    overlay["content_hash_verified"] = True
    overlay["copy_hash_receipt"] = {"entry_count": len(sealed_entries),
                                     "total_bytes": sum(int(x["expected_bytes"]) for x in sealed_entries),
                                     "runtime_entry_count": len(runtime_records),
                                     "original_mtime_is_provenance_only": True}
    overlay["sha256"] = canonical_sha(overlay)
    sealed_path = write_new(output_root / "sealed-overlay-v32.json", overlay)
    loader = _load_target_loader({item["role"]: item for item in runtime_records}, "portable_loader_v5")
    # The copied loader expects the overlay's bundle canonical SHA.  The
    # overlay template is still the immutable v5 bundle graph; only target
    # paths and seal metadata are new.
    v4_path, aliases = _prepare_aliases(loader, overlay, output_root)
    base_path = aliases["base"]
    worker_item = next((x for x in overlay["entries"] if x.get("role") == "v2_worker"), None)
    if worker_item is None:
        raise PortableExecutorError("overlay lacks v2_worker")
    worker_path = Path(worker_item["target_path"]).resolve()
    python_item = next(x for x in runtime_records if x["role"] == "python_executable")
    python_path = Path(python_item.get("invocation_path", python_item["source_path_provenance"])).expanduser()
    _require_file(python_path, "bound venv Python executable")
    # Runtime python is copied as a provenance role but executing the copied
    # binary itself is wrong for a venv (it lacks its sibling layout).  The
    # bound executable path is invoked; its SHA is checked above and -I clears
    # inherited module paths.  The copied runtime role remains part of the
    # closure/audit.
    runtime_module_paths = {
        "portable_loader_v5": str(next(x for x in runtime_records if x["role"] == "portable_loader_v5")["path"]),
        "raw_worker_v2": str(next(x for x in runtime_records if x["role"] == "raw_worker_v2")["path"]),
        "evaluator_v4": str(next(x for x in runtime_records if x["role"] == "evaluator_v4")["path"]),
    }
    audit_path = output_root / "private-runtime-audit-v32.json"
    _private_audit(python_path, runtime_root, ["portable_loader_v5", "raw_worker_v2", "evaluator_v4"], audit_path)
    native_output = output_root / "native-raw-to-label-v32"
    if native_output.exists():
        raise PortableExecutorError(f"native output already exists: {native_output}")
    worker_deadline = deadline
    return_code, stdout, stderr = _run_private_worker(
        python_path, worker_path, base_path, native_output, deadline=worker_deadline)
    (output_root / "native-worker.stdout.log").write_text(stdout, encoding="utf-8")
    (output_root / "native-worker.stderr.log").write_text(stderr, encoding="utf-8")
    if return_code != 0:
        raise PortableExecutorError(f"private raw-to-label worker failed with {return_code}: {stderr[-1000:]}")
    worker_report_path = native_output / "raw-to-typed-to-label-report-v2.json"
    if not worker_report_path.is_file():
        raise PortableExecutorError("private worker did not produce raw-to-typed-to-label report")
    worker_report = load_json(worker_report_path)
    if worker_report.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2":
        raise PortableExecutorError("private worker report schema differs")
    evaluator_status = "PENDING_FRESH_INDEPENDENT_PROOF"
    evaluator_report_path: Path | None = None
    if evaluator_proof is not None:
        proof = _require_file(evaluator_proof, "fresh independent proof")
        result_binding = worker_report.get("typed_to_label", {}).get("v16_forward", {})
        result_value = result_binding.get("result") if isinstance(result_binding, Mapping) else None
        if not isinstance(result_value, str) or not Path(result_value).is_file():
            raise PortableExecutorError("worker report has no v16 result for evaluator")
        result_path = Path(result_value).resolve()
        frozen_path = aliases["v15"]
        evaluator_source_item = next(x for x in runtime_records if x["role"] == "evaluator_v4_source_request")
        evaluator_source = load_json(evaluator_source_item["path"])
        evaluator_request_path = output_root / "evaluator-v4-relocated-request.json"
        evaluator_request = _rewrite_evaluator_request(
            evaluator_source, result=result_path, frozen=frozen_path, proof=proof,
            raw_report=worker_report_path, runtime={**{x["role"]: x for x in runtime_records},
                                                   "python_executable": python_item},
            output=evaluator_request_path)
        evaluator_item = next(x for x in runtime_records if x["role"] == "evaluator_v4")
        evaluator_report_path = output_root / "no-model-evaluator-v4.json"
        code, out, err = _run_private_evaluator(
            python_path, Path(evaluator_item["path"]), evaluator_request, evaluator_report_path,
            deadline=deadline)
        (output_root / "evaluator.stdout.log").write_text(out, encoding="utf-8")
        (output_root / "evaluator.stderr.log").write_text(err, encoding="utf-8")
        if code != 0:
            raise PortableExecutorError(f"private evaluator failed with {code}: {err[-1000:]}")
        evaluator_status = "PASS_DEVELOPMENT_RAW_TYPED_LABEL_OPERATOR_TRIAL_V4"
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_RAW_TYPED_LABEL_PENDING_EVALUATOR_PROOF" if evaluator_status.startswith("PENDING")
                  else "COMPLETE_RAW_TYPED_LABEL_EVALUATOR_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(Path(request_path).expanduser().resolve()), "sha256": sha256_file(request_path)},
        "fresh_roots": {"target_root": str(target_root), "output_root": str(output_root)},
        "stages": {
            "copy_overlay": {"status": "COMPLETE", "entry_count": len(copy_records),
                              "bytes": sum(int(x["bytes"]) for x in copy_records)},
            "seal_overlay": {"status": "COMPLETE", "path": str(sealed_path), "sha256": sha256_file(sealed_path)},
            "private_runtime": {"status": "COMPLETE", "audit": str(audit_path),
                                 "module_files": runtime_module_paths},
            "raw_to_typed_to_label": {"status": worker_report.get("status"),
                                       "report": str(worker_report_path),
                                       "report_sha256": sha256_file(worker_report_path),
                                       "request": str(base_path)},
            "no_model_evaluator_v4": {"status": evaluator_status,
                                       "report": None if evaluator_report_path is None else str(evaluator_report_path)},
        },
        "raw_opened": True, "hdf5_opened": True,
        "model_invoked": False, "cfd_invoked": False,
        "original_path_fallback": "FORBIDDEN", "os_open_audit_required": True,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "The independent proof is not synthesized by this executor; without one evaluator remains pending.",
            "Parent OS strace/openat is required to cover HDF5/BI4 C-level opens; Python module closure is checked here.",
            "This remains DEVELOPMENT with QI/QN/QE UNKNOWN.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    report_path = write_new(output_root / "portable-executor-report-v32.json", report)
    return {"status": report["status"], "report": str(report_path), "sha256": report["sha256"],
            "evaluator_status": evaluator_status, "output_root": str(output_root)}


def evaluate_existing(request_path: Path | str, *, evaluator_proof: Path,
                      parent_pid: int | None = None, max_wall_seconds: float | None = 300.0) -> dict[str, Any]:
    """Run only the private JSON evaluator after a completed raw worker.

    This is the post-worker handoff used when the independent proof is
    produced by the parent guard after the raw/typed/label stage.  It reads
    no HDF5/BI4 and refuses to consult the original evaluator request or
    original runtime once the copied bundle exists.
    """
    request = _load_request(request_path)
    if parent_pid is not None and (parent_pid <= 1 or not Path(f"/proc/{parent_pid}").exists()):
        raise PortableExecutorError("parent guard process is not alive")
    proof = _require_file(evaluator_proof, "fresh independent proof")
    output_root = Path(request["fresh_roots"]["output_root"]).expanduser().resolve()
    target_root = Path(request["fresh_roots"]["target_root"]).expanduser().resolve()
    if not output_root.is_dir() or not target_root.is_dir():
        raise PortableExecutorError("completed fresh executor roots are missing")
    executor_report_path = output_root / "portable-executor-report-v32.json"
    if not executor_report_path.is_file():
        raise PortableExecutorError("raw executor report is missing")
    executor_report = load_json(executor_report_path)
    if executor_report.get("original_path_fallback") != "FORBIDDEN":
        raise PortableExecutorError("raw executor report permits original-path fallback")
    raw_item = executor_report.get("stages", {}).get("raw_to_typed_to_label", {})
    raw_report_path = Path(str(raw_item.get("report", ""))).expanduser().resolve()
    raw_report_path = _require_file(raw_report_path, "fresh raw-to-label report")
    raw_report = load_json(raw_report_path)
    result_value = raw_report.get("typed_to_label", {}).get("v16_forward", {})
    result_value = result_value.get("result") if isinstance(result_value, Mapping) else None
    if not isinstance(result_value, str):
        raise PortableExecutorError("fresh raw-to-label report has no v16 result")
    result_path = _require_file(result_value, "fresh v16 result")
    frozen_path = _require_file(output_root / "relocated-runtime" / "f2-s1-replay-request-v15-relocated.json",
                                "fresh relocated frozen v15 request")
    runtime_records: list[dict[str, Any]] = []
    runtime_root = target_root / "runtime"
    for raw in request.get("runtime_sources", []):
        if not isinstance(raw, Mapping):
            raise PortableExecutorError("runtime source is malformed")
        role = str(raw.get("role", ""))
        target = (target_root / _safe_rel(raw.get("target_relative_path"), f"runtime {role}")).resolve()
        target = _require_file(target, role)
        expected = _sha(raw.get("sha256"), f"runtime {role}.sha256")
        if sha256_file(target) != expected:
            raise PortableExecutorError(f"copied runtime changed: {role}")
        item = dict(raw)
        item["path"] = str(target)
        item["source_path_provenance"] = str(raw.get("path"))
        runtime_records.append(item)
    evaluator_source_item = next((x for x in runtime_records if x.get("role") == "evaluator_v4_source_request"), None)
    if not isinstance(evaluator_source_item, Mapping):
        raise PortableExecutorError("copied evaluator source request is missing")
    evaluator_source = load_json(evaluator_source_item["path"])
    evaluator_request_path = output_root / "evaluator-v4-relocated-request-forward.json"
    evaluator_request = _rewrite_evaluator_request(
        evaluator_source, result=result_path, frozen=frozen_path, proof=proof,
        raw_report=raw_report_path, runtime={x["role"]: x for x in runtime_records},
        output=evaluator_request_path)
    evaluator_item = next((x for x in runtime_records if x.get("role") == "evaluator_v4"), None)
    python_item = next((x for x in runtime_records if x.get("role") == "python_executable"), None)
    if not isinstance(evaluator_item, Mapping) or not isinstance(python_item, Mapping):
        raise PortableExecutorError("copied evaluator/python roles are missing")
    python_path = Path(str(python_item.get("invocation_path", python_item.get("source_path_provenance")))).expanduser()
    evaluator_report_path = output_root / "no-model-evaluator-v4-forward.json"
    code, stdout, stderr = _run_private_evaluator(
        python_path, Path(str(evaluator_item["path"])), evaluator_request,
        evaluator_report_path, deadline=(time.monotonic() + max_wall_seconds if max_wall_seconds else None))
    (output_root / "evaluator-forward.stdout.log").write_text(stdout, encoding="utf-8")
    (output_root / "evaluator-forward.stderr.log").write_text(stderr, encoding="utf-8")
    if code != 0:
        raise PortableExecutorError(f"private evaluator failed with {code}: {stderr[-1000:]}")
    report = {
        "schema": "ds02.stage2.f2-portable-evaluator-forward-report.v1",
        "status": "PASS_DEVELOPMENT_RAW_TYPED_LABEL_OPERATOR_TRIAL_V4",
        "request": {"path": str(Path(request_path).expanduser().resolve()), "sha256": sha256_file(request_path)},
        "fresh_executor_report": {"path": str(executor_report_path), "sha256": sha256_file(executor_report_path)},
        "fresh_result": {"path": str(result_path), "sha256": sha256_file(result_path)},
        "fresh_raw_report": {"path": str(raw_report_path), "sha256": sha256_file(raw_report_path)},
        "independent_proof": {"path": str(proof), "sha256": sha256_file(proof)},
        "evaluator_request": {"path": str(evaluator_request_path), "sha256": sha256_file(evaluator_request_path)},
        "evaluator_report": {"path": str(evaluator_report_path), "sha256": sha256_file(evaluator_report_path)},
        "hdf5_or_bi4_content_read": False, "model_invoked": False, "cfd_invoked": False,
        "original_path_fallback": "FORBIDDEN", "qualification": dict(UNKNOWN),
    }
    report["sha256"] = canonical_sha(report)
    report_path = write_new(output_root / "portable-evaluator-forward-report-v32.json", report)
    return {"status": report["status"], "report": str(report_path), "sha256": report["sha256"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v31-request", type=Path, required=True)
    build.add_argument("--v31-contract", type=Path, required=True)
    build.add_argument("--bundle", type=Path, required=True)
    build.add_argument("--overlay", type=Path, required=True)
    build.add_argument("--evaluator", type=Path, required=True)
    build.add_argument("--target-root", type=Path)
    build.add_argument("--output-root", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--contract-output", type=Path)
    prep = sub.add_parser("preflight")
    prep.add_argument("--request", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--evaluator-proof", type=Path)
    run_parser.add_argument("--max-wall-seconds", type=float)
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--request", type=Path, required=True)
    evaluate_parser.add_argument("--evaluator-proof", type=Path, required=True)
    evaluate_parser.add_argument("--parent-pid", type=int)
    evaluate_parser.add_argument("--max-wall-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(v31_request=args.v31_request, v31_contract=args.v31_contract,
                                  bundle=args.bundle, overlay=args.overlay, evaluator=args.evaluator,
                                  output=args.output, contract_output=args.contract_output,
                                  target_root=args.target_root, output_root=args.output_root)
        elif args.command == "preflight":
            value = preflight(args.request, args.output)
        elif args.command == "run":
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                        max_wall_seconds=args.max_wall_seconds)
        else:
            value = evaluate_existing(args.request, evaluator_proof=args.evaluator_proof,
                                      parent_pid=args.parent_pid,
                                      max_wall_seconds=args.max_wall_seconds)
    except (PortableExecutorError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(ERROR_PREFIX + str(error), file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
