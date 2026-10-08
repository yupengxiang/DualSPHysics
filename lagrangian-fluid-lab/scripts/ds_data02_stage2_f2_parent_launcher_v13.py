#!/usr/bin/env python3
"""F2 parent launcher v13 with a source-bound virtualenv interpreter.

This is an additive forward of the consumed v12 launcher.  The execution
argv keeps the literal ``.venv/bin/python`` path; resolving that symlink to
``/usr/bin/python3.10`` is provenance only and is forbidden at launch because
the system NumPy/h5py pair has an ABI mismatch.  The executable, pyvenv.cfg,
and the installed NumPy/h5py RECORD+METADATA files are bound and reported.
The launcher remains DEVELOPMENT/UNKNOWN and never opens HDF5/BI4 itself.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
V12_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v12.py"
V13_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v13.py"
V12_SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v12"
SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v13"
REPORT_SCHEMA = "ds02.stage2.f2-parent-supervised-launch-report.v13"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
VENV_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv")
# Keep this spelling in every request and Popen argv.  ``resolve()`` is used
# only when recording the target identity, never to select the interpreter.
VENV_PYTHON = VENV_ROOT / "bin/python"
VENV_CFG = VENV_ROOT / "pyvenv.cfg"
VENV_DEPS = {
    "numpy_record": VENV_ROOT / "lib/python3.10/site-packages/numpy-2.2.6.dist-info/RECORD",
    "numpy_metadata": VENV_ROOT / "lib/python3.10/site-packages/numpy-2.2.6.dist-info/METADATA",
    "h5py_record": VENV_ROOT / "lib/python3.10/site-packages/h5py-3.16.0.dist-info/RECORD",
    "h5py_metadata": VENV_ROOT / "lib/python3.10/site-packages/h5py-3.16.0.dist-info/METADATA",
}


class ParentLaunchError(RuntimeError):
    pass


class ParentLaunchCancelled(ParentLaunchError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParentLaunchError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ParentLaunchError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ParentLaunchError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _load_v12_module():
    spec = importlib.util.spec_from_file_location("ds02_parent_launcher_v12_for_v13", V12_PATH)
    if spec is None or spec.loader is None:
        raise ParentLaunchError(f"cannot import v12 launcher: {V12_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V12 = _load_v12_module()


def _static_binding(role: str, path: Path | str, *, literal: bool = False) -> dict[str, Any]:
    spelling = Path(path).expanduser() if literal else Path(path).expanduser().resolve()
    resolved = spelling.resolve()
    if not resolved.is_file():
        raise ParentLaunchError(f"bound source is missing: {resolved}")
    stat = resolved.stat()
    return {"role": role, "path": str(spelling), "resolved_path": str(resolved),
            "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "sha256": sha256_file(resolved), "source_kind": "static"}


def _check_binding(item: Mapping[str, Any], *, verify_content: bool) -> dict[str, Any]:
    raw = Path(str(item.get("path", ""))).expanduser()
    resolved = raw.resolve()
    if not resolved.is_file():
        raise ParentLaunchError(f"bound source is missing: {resolved}")
    expected = str(item.get("sha256", ""))
    if len(expected) != 64 or any(c not in HEX64 for c in expected):
        raise ParentLaunchError(f"invalid source SHA for {item.get('role')}")
    stat = resolved.stat()
    if item.get("source_kind") != "parent":
        if item.get("bytes") is not None and int(item["bytes"]) != stat.st_size:
            raise ParentLaunchError(f"bound source byte stat differs: {resolved}")
        if item.get("mtime_ns") is not None and int(item["mtime_ns"]) != stat.st_mtime_ns:
            raise ParentLaunchError(f"bound source mtime differs: {resolved}")
        if verify_content and sha256_file(resolved) != expected:
            raise ParentLaunchError(f"bound source SHA differs: {resolved}")
    return {"role": str(item.get("role")), "path": str(raw),
            "resolved_path": str(resolved), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": expected,
            "source_kind": item.get("source_kind", "static")}


def _venv_contract() -> dict[str, Any]:
    if not VENV_PYTHON.is_file() or not VENV_CFG.is_file():
        raise ParentLaunchError("bound .venv interpreter or pyvenv.cfg is missing")
    target = VENV_PYTHON.resolve()
    return {
        "literal_path": str(VENV_PYTHON),
        "resolved_target_provenance": str(target),
        "binary_sha256": sha256_file(target),
        "pyvenv_cfg": _static_binding("venv_pyvenv_cfg", VENV_CFG),
        "dependencies": [_static_binding("venv_" + role, path)
                         for role, path in VENV_DEPS.items()],
        "resolution_policy": "resolve-for-provenance-only; literal-path-required-for-exec",
        "abi_scope": "venv numpy-2.2.6 + h5py-3.16.0; system python ABI is untrusted",
    }


def _new_trace_path(old: str) -> str:
    path = Path(old).expanduser().resolve()
    return str(path.with_name("os-open-trace-v13.json"))


def _new_sidecar_path(trace: str) -> str:
    path = Path(trace).expanduser().resolve()
    return str(path.with_name(path.stem + "-finalization-v13.json"))


def build_request(v12_request_path: Path | str, output_path: Path | str,
                  *, cleanup_grace_seconds: float = 5.0) -> dict[str, Any]:
    source = Path(v12_request_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise ParentLaunchError(f"refusing to overwrite output: {output}")
    old = load_json(source)
    if old.get("schema") != V12_SCHEMA or old.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("source must be a ready v12 request")
    if old.get("sha256") != canonical_sha(old):
        raise ParentLaunchError("source v12 canonical SHA differs")
    if cleanup_grace_seconds <= 0:
        raise ParentLaunchError("cleanup grace must be positive")
    venv = _venv_contract()
    bindings = copy.deepcopy(old.get("source_bindings", []))
    # Keep the v12 and v11 closure as immutable provenance, then add this
    # launcher and every interpreter/dependency artifact actually required.
    bindings.append(_static_binding("parent_launcher_v13", V13_PATH))
    bindings.append(_static_binding("v12_launch_request", source))
    bindings.append(_static_binding("venv_python_literal", VENV_PYTHON, literal=True))
    bindings.append(venv["pyvenv_cfg"])
    bindings.extend(venv["dependencies"])
    trace = dict(old.get("trace", {}))
    trace["path"] = _new_trace_path(str(trace["path"]))
    sidecar = _new_sidecar_path(trace["path"])
    request = copy.deepcopy(old)
    request.update({
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "forward_of": {"schema": V12_SCHEMA, "path": str(source),
                       "sha256": old["sha256"], "immutable": True,
                       "revision": "literal-venv-interpreter-and-ABI-closure-v13"},
        "v12_launch": {"path": str(source), "sha256": old["sha256"],
                       "file_sha256": sha256_file(source), "schema": V12_SCHEMA},
        "trace": trace,
        "source_bindings": bindings,
        "input_files": [str(item["path"]) for item in bindings],
        "input_sha256": {str(item["path"]): str(item["sha256"]) for item in bindings},
        "attempt_id": str(old.get("attempt_id", "")) + "-v13",
    })
    request["storage_scope"] = copy.deepcopy(request.get("storage_scope", {}))
    request["storage_scope"]["trace_path"] = trace["path"]
    request["storage_scope"]["finalization_sidecar"] = sidecar
    request["execution"] = copy.deepcopy(request.get("execution", {}))
    request["execution"].update({
        "python": str(VENV_PYTHON),
        "strace": str(old["execution"]["strace"]),
        "v12_launcher": str(old["execution"].get("v12_launcher", V12_PATH)),
        "v13_launcher": str(V13_PATH),
        "trace_finalization_sidecar": sidecar,
        "parent_supervised": [str(VENV_PYTHON), "-B", str(V13_PATH), "run",
                               "--request", "<request>", "--parent-pid", "<supervisor_pid>"],
        "interpreter_binding": venv,
        "literal_path_required": True,
        "resolved_path_must_not_be_launched": True,
        "cleanup_grace_seconds": float(cleanup_grace_seconds),
    })
    request["interpreter_binding"] = venv
    request["model_invoked"] = False
    request["cfd_invoked"] = False
    request["qualification"] = copy.deepcopy(UNKNOWN)
    request["limitations"] = list(request.get("limitations", [])) + [
        "v13 preserves the literal .venv/bin/python invocation; resolved target is provenance only.",
        "An actual replay must bind a new bridge attempt; the v12 forward request is immutable evidence.",
        "System interpreter NumPy/h5py ABI is not an accepted fallback.",
    ]
    request["sha256"] = canonical_sha(request)
    write_new(output, request)
    return request


def _load_bound_v11(request: Mapping[str, Any], *, verify_sources: bool) -> tuple[dict[str, Any], Any]:
    v11_path = Path(str(request.get("v11_launch", {}).get("path", ""))).expanduser().resolve()
    if not v11_path.is_file():
        raise ParentLaunchError("v11 launch request is missing from v13 closure")
    return V12._load_v11(v11_path, verify_sources=verify_sources)


def _validate_launch(request: Mapping[str, Any], *, verify_content: bool) -> tuple[dict[str, Any], Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("unsupported or non-ready v13 launch request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise ParentLaunchError("v13 launch must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ParentLaunchError("v13 launch cannot invoke model/CFD")
    if request.get("sha256") != canonical_sha(request):
        raise ParentLaunchError("v13 launch canonical SHA differs")
    bindings = request.get("source_bindings")
    if not isinstance(bindings, list):
        raise ParentLaunchError("v13 source closure is incomplete")
    by_role = {str(item.get("role")): item for item in bindings if isinstance(item, Mapping)}
    for role in ("parent_launcher_v13", "v12_launch_request", "venv_python_literal",
                 "venv_pyvenv_cfg", "venv_numpy_record", "venv_numpy_metadata",
                 "venv_h5py_record", "venv_h5py_metadata"):
        if role not in by_role:
            raise ParentLaunchError(f"v13 source closure lacks {role}")
    for item in bindings:
        if isinstance(item, Mapping):
            _check_binding(item, verify_content=verify_content)
    literal = str(request.get("execution", {}).get("python", ""))
    if literal != str(VENV_PYTHON):
        raise ParentLaunchError("execution.python must retain literal .venv path")
    contract = request.get("interpreter_binding")
    if not isinstance(contract, Mapping) or contract.get("literal_path") != str(VENV_PYTHON):
        raise ParentLaunchError("venv interpreter contract is missing")
    if str(contract.get("binary_sha256")) != sha256_file(VENV_PYTHON.resolve()):
        raise ParentLaunchError("venv interpreter binary SHA differs")
    old = load_json(Path(str(request["v12_launch"]["path"])))
    if old.get("schema") != V12_SCHEMA or old.get("sha256") != request["v12_launch"].get("sha256"):
        raise ParentLaunchError("v12 forward source binding differs")
    v11, module = _load_bound_v11(request, verify_sources=verify_content)
    return v11, module


def _set_parent_death_signal(parent_pid: int) -> None:
    if os.getppid() != int(parent_pid):
        raise ParentLaunchCancelled("supervising parent already exited")


def _write_sidecar(request: Mapping[str, Any], cleanup: Mapping[str, Any], trace: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(request["storage_scope"]["finalization_sidecar"])).expanduser().resolve()
    value: dict[str, Any] = {
        "schema": "ds02.stage2.f2-parent-trace-finalization.v13",
        "request_sha256": request.get("sha256"),
        "attempt_id": request.get("attempt_id"),
        "trace": dict(trace),
        "cleanup": dict(cleanup),
        "supplemental_charge_required": True,
        "interpreter": copy.deepcopy(request.get("interpreter_binding", {})),
        "model_invoked": False, "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
    }
    value["sha256"] = canonical_sha(value)
    V12.write_new(path, value)
    value["sidecar_path"] = str(path)
    value["sidecar_bytes"] = path.stat().st_size
    return value


def run(request_path: Path | str, *, parent_pid: int) -> dict[str, Any]:
    entry = time.monotonic()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    max_wall = int(request.get("parent_boundary", {}).get("max_wall_seconds", 0))
    cleanup_grace = float(request.get("execution", {}).get("cleanup_grace_seconds", 0))
    if max_wall <= 0 or cleanup_grace <= 0:
        raise ParentLaunchError("v13 max wall and cleanup grace must be positive")
    child: subprocess.Popen[str] | None = None
    stdout = stderr = ""
    error: str | None = None
    cleanup: dict[str, Any] = {"attempted": False}
    child_timed_out = False
    status = "FAILED_PARENT_SUPERVISED_LAUNCH"
    storage: dict[str, Any] | None = None
    try:
        v11, _module = _validate_launch(request, verify_content=True)
        storage = V12._storage_preflight(v11)
        trace_path = Path(str(request["trace"]["path"])).expanduser().resolve()
        sidecar_path = Path(str(request["storage_scope"]["finalization_sidecar"])).expanduser().resolve()
        if trace_path.exists() or sidecar_path.exists():
            raise ParentLaunchError("v13 trace or sidecar already exists")
        _set_parent_death_signal(parent_pid)
        # This is intentionally the un-resolved spelling from the request.
        python_literal = str(request["execution"]["python"])
        strace = str(Path(str(request["execution"]["strace"])).expanduser().resolve())
        bridge = str(Path(str(request["execution"]["bridge"])).expanduser().resolve())
        command = [strace, "-f", "-e", "trace=openat,openat2,creat,truncate,rename,unlink,statx",
                   "-o", str(trace_path), python_literal, "-B", bridge, "run",
                   "--request", str(v11["bridge_request"]["path"]), "--io-slot-approved"]
        child = subprocess.Popen(command, cwd=str(SCRIPT_DIR.parents[1]), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
        remaining = max(0.001, float(max_wall) - (time.monotonic() - entry))
        try:
            stdout, stderr = child.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            child_timed_out = True
            cleanup = V12._terminate_child_group_bounded(child, cleanup_grace)
            try:
                stdout, stderr = child.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", "child did not become reapable after bounded cleanup"
            error = "parent launcher wall deadline exceeded"
        if not child_timed_out and child.returncode == 0:
            status = "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN"
        elif not child_timed_out:
            status = "FAILED_PARENT_SUPERVISED_CHILD"
            error = error or f"bridge child returned {child.returncode}: {stderr[-1000:]}"
        else:
            status = "FAILED_PARENT_SUPERVISED_DEADLINE"
    except ParentLaunchCancelled as exc:
        error = str(exc); status = "FAILED_PARENT_SUPERVISED_CANCELLED"
        if child is not None:
            cleanup = V12._terminate_child_group_bounded(child, cleanup_grace)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"; status = "FAILED_PARENT_SUPERVISED_LAUNCH"
        if child is not None:
            cleanup = V12._terminate_child_group_bounded(child, cleanup_grace)
    trace = {"path": str(Path(str(request["trace"]["path"])).expanduser().resolve()),
             "exists": Path(str(request["trace"]["path"])).expanduser().is_file(),
             "bytes": Path(str(request["trace"]["path"])).expanduser().stat().st_size
             if Path(str(request["trace"]["path"])).expanduser().is_file() else 0}
    accounting = V12._terminal_accounting_status(request)
    sidecar = None
    try:
        sidecar = _write_sidecar(request, cleanup, trace)
    except BaseException as exc:
        status = "FAILED_PARENT_FINALIZATION"; error = error or f"sidecar: {type(exc).__name__}: {exc}"
    return {"schema": REPORT_SCHEMA, "status": status,
            "request": {"path": str(request_file), "sha256": request.get("sha256")},
            "child": {"returncode": child.returncode if child is not None else None,
                       "argv": command if 'command' in locals() else [],
                       "literal_python": request.get("execution", {}).get("python"),
                       "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]},
            "interpreter_binding": copy.deepcopy(request.get("interpreter_binding", {})),
            "storage_preflight": storage, "trace": trace,
            "terminal_accounting": accounting, "trace_finalization_sidecar": sidecar,
            "error": error, "model_invoked": False, "cfd_invoked": False,
            "qualification": copy.deepcopy(UNKNOWN), "development_only": True}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v12-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--cleanup-grace-seconds", type=float, default=5.0)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v12_request, args.output,
                                  cleanup_grace_seconds=args.cleanup_grace_seconds)
            result = {"status": value["status"], "sha256": value["sha256"]}; code = 0
        elif args.command == "preflight":
            request = load_json(args.request); _validate_launch(request, verify_content=True)
            result = {"status": "READY_FOR_PARENT_IO_SLOT", "request_sha256": request["sha256"],
                      "literal_python": request["execution"]["python"], "resolved_python_provenance": request["interpreter_binding"]["resolved_target_provenance"],
                      "ledger_mutated": False, "raw_opened": False, "hdf5_opened": False}; code = 0
        else:
            result = run(args.request, parent_pid=args.parent_pid)
            code = 0 if result["status"] == "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN" else 2
    except (ParentLaunchError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
