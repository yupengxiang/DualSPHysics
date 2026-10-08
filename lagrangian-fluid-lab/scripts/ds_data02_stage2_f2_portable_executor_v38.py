#!/usr/bin/env python3
"""V38 forward executor for the F2 private Python import closure.

V37 completed the raw-tree copy and typed reconstruction, but its label phase
failed because relocated V15 was named with a numeric source prefix while its
source imports the canonical V14 module name.  Python isolated mode also omits
the script directory from sys.path.

V38 creates canonical V14/V15/V16 aliases inside the copied target, verifies
their bytes, and runs the worker through a private -B -I bootstrap that inserts
only the copied worker directory.  It also provides a metadata-only transitive
import preflight.  V34/V37 files and receipts are immutable; this module owns
no ledger and gives no scientific qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V34_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v34.py"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v38-forward.v1"
IMPORT_SCHEMA = "ds02.stage2.f2-private-transitive-import.v1"
BOUND_V34_SHA256 = "506477a0feb24a9e6b58af82499bf242f37a3cd768bc39cd6dbaa73d1dead989"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
CANONICAL_MODULE_NAMES = {
    "v14_operator": "ds_data02_stage2_f2_replay_v14.py",
    "v15_operator": "ds_data02_stage2_f2_replay_v15.py",
    "v16_operator": "ds_data02_stage2_f2_flux_v16.py",
}


class PortableV38Error(RuntimeError):
    """The V38 copied import closure is unsafe or incomplete."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    # V38 calls this only for JSON/Python/runtime files, never raw/HDF5/BI4.
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV38Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV38Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise PortableV38Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise PortableV38Error(f"{name} must be a lowercase SHA-256")
    return value


def _require_file(path: Path | str, role: str) -> Path:
    # Keep literal venv invocation paths.  Resolving them can select the
    # system interpreter and reproduce the known NumPy/h5py ABI failure.
    target = Path(path).expanduser()
    if not target.is_file():
        raise PortableV38Error(f"{role} is missing: {target}")
    return target


def _load_request(path: Path | str) -> dict[str, Any]:
    request_path = _require_file(path, "V38 request")
    request = load_json(request_path)
    if request.get("schema") != V34_SCHEMA:
        raise PortableV38Error(f"V38 request must retain V34 schema: {request.get('schema')!r}")
    if request.get("sha256") != canonical_sha(request):
        raise PortableV38Error("V38 request canonical SHA differs")
    forward = request.get("forward_v38")
    if not isinstance(forward, Mapping) or forward.get("schema") != FORWARD_SCHEMA:
        raise PortableV38Error("V38 forward marker is missing")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise PortableV38Error("V38 request must remain model-free DEVELOPMENT")
    if request.get("cfd_invoked") is not False or request.get("qualification") != UNKNOWN:
        raise PortableV38Error("V38 request must keep CFD false and QI/QN/QE UNKNOWN")
    expected = _require_sha(forward.get("wrapper_sha256"), "forward_v38.wrapper_sha256")
    if expected != sha256_file(SCRIPT):
        raise PortableV38Error("V38 wrapper source SHA differs from request binding")
    return request


def _module_bindings(base_request: Path | str) -> dict[str, dict[str, Any]]:
    base = load_json(base_request)
    modules = base.get("modules")
    if not isinstance(modules, Mapping):
        raise PortableV38Error("relocated worker request has no modules closure")
    result: dict[str, dict[str, Any]] = {}
    for role, filename in CANONICAL_MODULE_NAMES.items():
        raw = modules.get(role)
        if not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str):
            raise PortableV38Error(f"relocated worker module binding is missing: {role}")
        path = _require_file(raw["path"], role)
        expected = _require_sha(raw.get("sha256"), f"modules.{role}.sha256")
        if sha256_file(path) != expected:
            raise PortableV38Error(f"copied module SHA differs: {role}")
        result[role] = {
            "role": role, "module": filename, "canonical_module": filename,
            "path": str(path),
            "sha256": expected, "bytes": int(path.stat().st_size),
            "mode_bits": int(stat.S_IMODE(path.stat().st_mode)),
        }
    return result


def _materialize_aliases(bindings: Mapping[str, Mapping[str, Any]],
                         worker_dir: Path | str) -> list[dict[str, Any]]:
    """Create canonical aliases beside copied modules, never overwrite."""
    target_dir = Path(worker_dir).expanduser()
    if not target_dir.is_dir():
        raise PortableV38Error(f"copied worker directory is missing: {target_dir}")
    records: list[dict[str, Any]] = []
    source_dirs: set[str] = set()
    for role, canonical_name in CANONICAL_MODULE_NAMES.items():
        item = bindings.get(role)
        if not isinstance(item, Mapping):
            raise PortableV38Error(f"module binding is missing: {role}")
        source = _require_file(item.get("path", ""), role)
        try:
            source.relative_to(target_dir)
        except ValueError as error:
            raise PortableV38Error(
                f"module {role} is outside copied worker directory: {source}") from error
        source_dirs.add(str(source.parent))
        expected = _require_sha(item.get("sha256"), f"modules.{role}.sha256")
        if sha256_file(source) != expected:
            raise PortableV38Error(f"module {role} changed before aliasing")
        alias = target_dir / canonical_name
        state = "ALREADY_CANONICAL"
        if alias.exists():
            if not alias.is_file() or sha256_file(alias) != expected:
                raise PortableV38Error(f"existing canonical alias differs: {alias}")
            if alias.resolve() != source.resolve():
                state = "EXISTING_VERIFIED_ALIAS"
        else:
            shutil.copyfile(source, alias)
            os.chmod(alias, stat.S_IMODE(source.stat().st_mode))
            if sha256_file(alias) != expected:
                raise PortableV38Error(f"new canonical alias SHA differs: {alias}")
            state = "CREATED_FROM_COPIED_SOURCE"
        alias_stat = alias.stat()
        if alias_stat.st_size != int(item.get("bytes", alias_stat.st_size)):
            raise PortableV38Error(f"canonical alias byte stat differs: {alias}")
        records.append({
            "role": role, "canonical_module": canonical_name,
            "copied_source_path": str(source), "alias_path": str(alias),
            "sha256": expected, "bytes": int(alias_stat.st_size),
            "mode_bits": int(stat.S_IMODE(alias_stat.st_mode)),
            "inode_distinct": bool(alias.resolve() != source.resolve()),
            "state": state,
        })
    if len(source_dirs) != 1:
        raise PortableV38Error("V14/V15/V16 modules are not co-located")
    return records


def _import_subprocess(python: Path | str,
                       records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Import V14 then V15 and V16 in an isolated source-only process."""
    python_path = _require_file(python, "bound venv Python")
    if len(records) != len(CANONICAL_MODULE_NAMES):
        raise PortableV38Error("all V14/V15/V16 aliases are required")
    with tempfile.TemporaryDirectory(prefix="ds02-v38-import-") as temporary:
        root = Path(temporary)
        for item in records:
            role = str(item["role"])
            source = _require_file(item.get("alias_path", ""), f"alias {role}")
            target = root / str(item["canonical_module"])
            shutil.copyfile(source, target)
            os.chmod(target, stat.S_IMODE(source.stat().st_mode))
            expected = _require_sha(item.get("sha256"), f"alias {role}.sha256")
            if sha256_file(target) != expected:
                raise PortableV38Error(f"temporary import source SHA differs: {role}")
        code = r'''
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("no loader for " + str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
v14 = load(root / "ds_data02_stage2_f2_replay_v14.py", "ds_data02_stage2_f2_replay_v14")
v15 = load(root / "ds_data02_stage2_f2_replay_v15.py", "_ds02_v38_v15")
v16 = load(root / "ds_data02_stage2_f2_flux_v16.py", "_ds02_v38_v16")
print(json.dumps({"v14": str(pathlib.Path(v14.__file__).resolve()),
                  "v15": str(pathlib.Path(v15.__file__).resolve()),
                  "v16": str(pathlib.Path(v16.__file__).resolve()),
                  "sys_path0": str(root)}, sort_keys=True))
'''
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME"}}
        proc = subprocess.run(
            [str(python_path), "-B", "-I", "-c", code, str(root)],
            capture_output=True, text=True, check=False, env=env)
        if proc.returncode != 0:
            raise PortableV38Error(
                f"private transitive import failed: {proc.stderr.strip()}")
        try:
            loaded = json.loads(proc.stdout.strip())
        except json.JSONDecodeError as error:
            raise PortableV38Error(
                f"private import returned malformed JSON: {proc.stdout!r}") from error
        if not isinstance(loaded, dict):
            raise PortableV38Error("private import result is not an object")
        return {"loaded": loaded, "temporary_source_only": True,
                "python_invocation": str(python_path)}


def preflight_imports(*, base_request: Path | str, python: Path | str,
                      output: Path | str) -> dict[str, Any]:
    """Preflight only copied JSON/Python closure; never opens payload data."""
    base_path = _require_file(base_request, "relocated worker request")
    bindings = _module_bindings(base_path)
    if len({str(Path(item["path"]).parent) for item in bindings.values()}) != 1:
        raise PortableV38Error("module closure is not co-located")
    records = []
    for item in bindings.values():
        value = dict(item)
        value["alias_path"] = value["path"]
        records.append(value)
    imported = _import_subprocess(python, records)
    result: dict[str, Any] = {
        "schema": IMPORT_SCHEMA,
        "status": "PASS_PRIVATE_TRANSITIVE_IMPORT_V38",
        "role": "DEVELOPMENT",
        "base_request": {"path": str(base_path), "sha256": sha256_file(base_path)},
        "modules": records,
        "import": imported,
        "import_order": ["v14_operator", "v15_operator", "v16_operator"],
        "target_only_path_policy": "bound copied Python modules; no original fallback",
        "payload_read": False, "hdf5_or_bi4_read": False,
        "raw_tree_read": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
    }
    result["sha256"] = canonical_sha(result)
    write_new(output, result)
    return result


def _load_v34() -> Any:
    if sha256_file(V34_SCRIPT) != BOUND_V34_SHA256:
        raise PortableV38Error("immutable V34 executor SHA differs from V38 binding")
    spec = importlib.util.spec_from_file_location("ds02_bound_f2_executor_v34_v38", V34_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV38Error("cannot load immutable V34 executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_worker_with_bootstrap(v34: Any, python: Path, worker: Path,
                               request: Path, output: Path,
                               *, deadline: float | None) -> tuple[int, str, str]:
    # -I omits the script directory; the inline bootstrap inserts only this
    # copied directory before executing the worker as __main__.
    code = (
        "import runpy,sys; script=sys.argv[1]; sys.argv=sys.argv[1:]; "
        "sys.path.insert(0, __import__('pathlib').Path(script).parent.as_posix()); "
        "runpy.run_path(script, run_name='__main__')"
    )
    command = [str(python), "-B", "-I", "-c", code, str(worker), "run",
               "--request", str(request), "--output-dir", str(output),
               "--io-slot-approved", "--run-labels"]
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}
    proc = subprocess.Popen(command, start_new_session=False,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    try:
        stdout, stderr = proc.communicate(
            timeout=None if deadline is None else max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        v34._child_group_terminate(proc)
        stdout, stderr = proc.communicate()
        return 124, stdout, stderr + "\nprivate worker deadline exceeded"
    return int(proc.returncode), stdout, stderr


def _v38_worker_hook(v34: Any):
    original = v34._run_private_worker

    def wrapped(python: Path, worker: Path, request: Path, output: Path,
                *, deadline: float | None):
        bindings = _module_bindings(request)
        aliases = _materialize_aliases(bindings, worker.parent)
        imported = _import_subprocess(python, aliases)
        closure = {
            "schema": IMPORT_SCHEMA,
            "status": "PASS_COPIED_TARGET_TRANSITIVE_IMPORT_V38",
            "base_request": {"path": str(request), "sha256": sha256_file(request)},
            "worker": {"path": str(worker), "sha256": sha256_file(worker)},
            "aliases": aliases, "import": imported,
            "payload_read": False, "hdf5_or_bi4_read": False,
            "original_path_fallback": "FORBIDDEN",
            "qualification": dict(UNKNOWN),
        }
        write_new(output.parent / "private-import-closure-v38.json", closure)
        return _run_worker_with_bootstrap(v34, python, worker, request, output,
                                          deadline=deadline)

    return wrapped, original


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    _load_request(request_path)
    v34 = _load_v34()
    wrapped, original = _v38_worker_hook(v34)
    v34._run_private_worker = wrapped
    try:
        return v34.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        v34._run_private_worker = original


def build_forward(*, v37_request: Path | str, output: Path | str,
                  target_root: Path | str, output_root: Path | str) -> dict[str, Any]:
    """Create a fresh V38 request from V37 metadata; no payload reads."""
    previous_path = _require_file(v37_request, "V37 request")
    previous = load_json(previous_path)
    if previous.get("schema") != V34_SCHEMA or previous.get("sha256") != canonical_sha(previous):
        raise PortableV38Error("V37 request schema/SHA differs")
    if not isinstance(previous.get("forward_v37"), Mapping):
        raise PortableV38Error("V37 forward marker is missing")
    target = Path(target_root).expanduser()
    output_dir = Path(output_root).expanduser()
    if target.exists() or output_dir.exists():
        raise PortableV38Error("V38 target/output roots must be fresh")
    old_roots = previous.get("fresh_roots", {})
    if str(target) in {str(old_roots.get("target_root", "")),
                       str(old_roots.get("output_root", ""))}:
        raise PortableV38Error("V38 cannot reuse a consumed V37 root")
    runtime_sources = previous.get("runtime_sources")
    if not isinstance(runtime_sources, list):
        raise PortableV38Error("V37 runtime_sources are missing")
    if any(isinstance(item, Mapping) and item.get("role") == "executor_v38"
           for item in runtime_sources):
        raise PortableV38Error("executor_v38 is already bound")
    python_item = next((item for item in runtime_sources
                        if isinstance(item, Mapping) and item.get("role") == "python_executable"), None)
    if not isinstance(python_item, Mapping):
        raise PortableV38Error("python_executable binding is missing")
    invocation = python_item.get("invocation_path", python_item.get("path"))
    python_path = _require_file(str(invocation), "python executable invocation")
    wrapper = {
        "role": "executor_v38", "path": str(SCRIPT),
        "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v38.py",
        "bytes": int(SCRIPT.stat().st_size), "mtime_ns": int(SCRIPT.stat().st_mtime_ns),
        "sha256": sha256_file(SCRIPT), "invocation_path": str(SCRIPT),
    }
    request = dict(previous)
    request["request_id"] = str(previous.get("request_id", "f2-s1-v37")) + "-v38"
    request["fresh_roots"] = {"target_root": str(target), "output_root": str(output_dir)}
    request["runtime_sources"] = [*runtime_sources, wrapper]
    execution = dict(request.get("execution", {}))
    command = list(execution.get("command", []))
    if command:
        command[0] = str(python_path)
        if len(command) >= 3:
            command[2] = str(SCRIPT)
        execution["command"] = command
    execution["private_transitive_import_preflight"] = True
    execution["bootstrap_inserts_only_copied_worker_dir"] = True
    execution["original_path_fallback"] = "FORBIDDEN"
    request["execution"] = execution
    request["forward_v38"] = {
        "schema": FORWARD_SCHEMA,
        "compatibility_envelope": V34_SCHEMA,
        "previous_request": {"path": str(previous_path), "sha256": sha256_file(previous_path)},
        "wrapper_path": str(SCRIPT), "wrapper_sha256": sha256_file(SCRIPT),
        "canonical_aliases": dict(CANONICAL_MODULE_NAMES),
        "import_order": ["v14_operator", "v15_operator", "v16_operator"],
        "bootstrap": "-B -I plus explicit copied worker directory only",
        "payload_read_during_build": False,
        "hdf5_or_bi4_read_during_build": False,
        "raw_tree_read_during_build": False,
        "original_path_fallback": "FORBIDDEN",
        "qualification": dict(UNKNOWN),
    }
    request["status"] = "READY_FOR_PARENT_V38_IMPORT_CLOSURE_GUARD"
    request["raw_opened"] = False
    request["hdf5_opened"] = False
    request["model_invoked"] = False
    request["cfd_invoked"] = False
    request["qualification"] = dict(UNKNOWN)
    request["sha256"] = canonical_sha(request)
    out = write_new(output, request)
    return {"status": request["status"], "request": str(out),
            "sha256": request["sha256"], "wrapper_sha256": wrapper["sha256"],
            "payload_read": False, "hdf5_or_bi4_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v37-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    pre = sub.add_parser("preflight-imports")
    pre.add_argument("--base-request", type=Path, required=True)
    pre.add_argument("--python", type=Path, required=True)
    pre.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--evaluator-proof", type=Path)
    run_parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            result = build_forward(v37_request=args.v37_request, output=args.output,
                                   target_root=args.target_root, output_root=args.output_root)
        elif args.command == "preflight-imports":
            result = preflight_imports(base_request=args.base_request, python=args.python,
                                       output=args.output)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV38Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v38: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
