#!/usr/bin/env python3
"""Additive v14 launcher shim with the real terminal-accounting adapter.

The consumed v14 source calls a helper on its v13 module that does not exist;
the authoritative predicate lives on v12.  This wrapper leaves v14 bytes
untouched, binds itself as an extra immutable source, and invokes the real
v14 launcher after installing that explicit adapter.  The v14 process group,
strace, PDEATHSIG, signal cleanup, and sidecar implementation remain the
executed code; this shim does not bypass the launcher or its child.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
V14_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v14.py"
SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v14"
WRAPPER_ROLE = "parent_launcher_v15_accounting_adapter"


class LauncherV15Error(RuntimeError):
    pass


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_parent_launcher_v14_for_v15", path)
    if spec is None or spec.loader is None:
        raise LauncherV15Error(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V14 = _load(V14_PATH)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LauncherV15Error("JSON object required")
    return value


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V14.canonical_sha(value)


def _binding(path: Path, role: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise LauncherV15Error(f"wrapper binding is missing: {target}")
    stat = target.stat()
    return {"role": role, "path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(target),
            "source_kind": "static"}


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise LauncherV15Error(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def build_request(v14_request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    source = Path(v14_request_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    old = load_json(source)
    if old.get("schema") != V14.SCHEMA or old.get("status") != "READY_FOR_PARENT_GUARD":
        raise LauncherV15Error("source must be a ready v14 request")
    if old.get("sha256") != V14.canonical_sha(old):
        raise LauncherV15Error("source v14 canonical SHA differs")
    value = copy.deepcopy(old)
    bindings = [dict(item) for item in value.get("source_bindings", [])]
    bindings.append(_binding(Path(__file__), WRAPPER_ROLE))
    value["source_bindings"] = bindings
    value["input_files"] = [str(item["path"]) for item in bindings]
    value["input_sha256"] = {str(item["path"]): str(item["sha256"]) for item in bindings}
    value["execution"] = copy.deepcopy(value.get("execution", {}))
    value["execution"]["v15_accounting_adapter"] = str(Path(__file__).resolve())
    value["execution"]["parent_supervised"] = [str(value["execution"]["python"]), "-B",
                                                   str(Path(__file__).resolve()), "run",
                                                   "--request", "<request>",
                                                   "--parent-pid", "<supervisor_pid>"]
    value["forward_of"] = {"schema": V14.SCHEMA, "path": str(source),
                           "sha256": old["sha256"], "immutable": True,
                           "revision": "v14-terminal-accounting-adapter-v15"}
    value["limitations"] = list(value.get("limitations", [])) + [
        "v15 executes the immutable v14 launcher after binding the v12 terminal fee predicate explicitly.",
        "No scientific/HDF5/BI4/model/CFD credit is granted by this adapter.",
    ]
    value["sha256"] = V14.canonical_sha(value)
    _write_new(output, value)
    return value


def _install_accounting_adapter() -> None:
    predicate = getattr(V14.V13.V12, "_terminal_accounting_status", None)
    if not callable(predicate):
        raise LauncherV15Error("v12 terminal accounting predicate is unavailable")
    V14.V13._terminal_accounting_status = predicate


def run(request_path: Path | str, *, parent_pid: int) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != V14.SCHEMA:
        raise LauncherV15Error("v15 adapter accepts only the bound v14 schema")
    wrapper = next((item for item in request.get("source_bindings", [])
                    if isinstance(item, Mapping) and item.get("role") == WRAPPER_ROLE), None)
    if not isinstance(wrapper, Mapping):
        raise LauncherV15Error("v15 adapter source binding is missing")
    if Path(str(wrapper.get("path", ""))).expanduser().resolve() != Path(__file__).resolve():
        raise LauncherV15Error("v15 adapter path differs")
    if sha256_file(Path(__file__)) != str(wrapper.get("sha256")):
        raise LauncherV15Error("v15 adapter source SHA differs")
    _install_accounting_adapter()
    return V14.run(request_path, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v14-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v14_request, args.output)
            result = {"status": value["status"], "sha256": value["sha256"]}
        else:
            result = run(args.request, parent_pid=args.parent_pid)
    except (LauncherV15Error, V14.ParentLaunchError, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0 if str(result.get("status", "")).startswith("COMPLETED_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
