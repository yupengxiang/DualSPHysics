#!/usr/bin/env python3
"""Build a root-dispatchable V10 typed-proof outer request.

This is an additive forward of the V9 ``ds02.request.v1`` wrapper.  It
changes only the V10 inner request/consumer, output namespace, and explicit
900-second argument.  Every inherited small input is hashed; no V16 result,
HDF5, BI4, or raw payload is opened by this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


SCHEMA = "ds02.request.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class OuterV10RequestError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise OuterV10RequestError(f"{role} is not a regular non-symlink file: {target}")
    return target


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OuterV10RequestError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise OuterV10RequestError(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise OuterV10RequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def build_request(*, source_request: Path | str, v10_request: Path | str,
                  v10_consumer: Path | str, output: Path | str,
                  case_id: str, attempt_id: str, worktree_root: Path | str,
                  output_name: str = "fresh-v16-proof-v10.json") -> dict[str, Any]:
    source_path, source = _json(source_request, "source V9 outer request")
    if source.get("schema") != SCHEMA or source.get("kind") != "cpu":
        raise OuterV10RequestError("source outer request must be ds02.request.v1 CPU")
    if not isinstance(case_id, str) or not case_id or not isinstance(attempt_id, str) or not attempt_id:
        raise OuterV10RequestError("case_id and attempt_id are required")
    inner_path = _file(v10_request, "V10 proof request")
    script_path = _file(v10_consumer, "V10 consumer script")
    inner = json.loads(inner_path.read_text(encoding="utf-8"))
    if not isinstance(inner, Mapping) or inner.get("schema") != "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8":
        raise OuterV10RequestError("V10 inner request is not V8-shaped")
    if not output_name or "/" in output_name or output_name in {".", ".."}:
        raise OuterV10RequestError("output_name must be a simple filename")
    command = [
        str(source["command"][0]), "-B", "-I", "-c",
        "import importlib.util,os,json;"
        f"s=importlib.util.spec_from_file_location(\"proofconsumer_v10\",{str(script_path)!r});"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        f"print(json.dumps(m.run({str(inner_path)!r},\"{{attempt_root}}/{output_name}\","
        "io_slot_approved=True,parent_pid=os.getppid(),max_wall_seconds=900.0)))",
    ]
    inherited = [str(x) for x in source.get("input_files", [])]
    files = [x for x in inherited if x not in {str(script_path), str(inner_path)}]
    files.extend([str(script_path), str(inner_path)])
    unique: list[str] = []
    seen: set[str] = set()
    for item in files:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    hashes: dict[str, str] = {}
    for item in unique:
        path = _file(item, "outer input")
        hashes[str(path)] = sha256_file(path)
    value: dict[str, Any] = {
        "schema": SCHEMA, "kind": source.get("kind", "cpu"),
        "cpu_task_kind": source.get("cpu_task_kind", "audit"), "family_id": "F2",
        "case_id": case_id, "attempt_id": attempt_id,
        "cwd": str(Path(str(source.get("cwd", script_path.parent))).expanduser().resolve()),
        "cpu_threads": 1, "max_wall_seconds": 900,
        "estimated_storage_bytes": int(source.get("estimated_storage_bytes", 4 * 1024 * 1024)),
        "command": command, "input_files": unique,
        "qualification": dict(UNKNOWN),
        "worktree_root": str(Path(worktree_root).expanduser().resolve()), "omp_threads": 1,
        "input_hashes": hashes, "input_sha256": dict(hashes),
        "root_forward_provenance": {
            "source_request": str(source_path), "source_request_sha256": sha256_file(source_path),
            "forward_fix": "V10 exact root051 mass-scope contract over immutable V8/V9 checks",
            "max_wall_argument": "900.0 passed explicitly to V10",
            "hdf5_or_bi4_read_by_builder": False, "model_invoked": False,
            "qualification": dict(UNKNOWN),
        },
    }
    target = _write_new(output, value)
    return {"schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "request": str(target),
            "case_id": case_id, "attempt_id": attempt_id, "input_count": len(unique),
            "request_source_sha256": sha256_file(source_path),
            "v10_request_sha256": sha256_file(inner_path), "v10_consumer_sha256": sha256_file(script_path),
            "max_wall_seconds": 900, "hdf5_or_bi4_content_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-request", type=Path, required=True)
    parser.add_argument("--v10-request", type=Path, required=True)
    parser.add_argument("--v10-consumer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--worktree-root", type=Path, required=True)
    parser.add_argument("--output-name", default="fresh-v16-proof-v10.json")
    args = parser.parse_args(argv)
    try:
        value = build_request(source_request=args.source_request, v10_request=args.v10_request,
                              v10_consumer=args.v10_consumer, output=args.output,
                              case_id=args.case_id, attempt_id=args.attempt_id,
                              worktree_root=args.worktree_root, output_name=args.output_name)
    except (OuterV10RequestError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"fresh V16 outer V10 request: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
