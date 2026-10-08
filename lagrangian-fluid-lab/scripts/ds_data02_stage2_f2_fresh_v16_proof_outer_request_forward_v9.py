#!/usr/bin/env python3
"""Build the guarded ``ds02.request.v1`` wrapper for proof-consumer V9.

This is a metadata-only forwarder from the failed V8 outer request.  It
changes only the imported consumer, V9 request, output namespace/name, and
the missing explicit ``max_wall_seconds`` argument.  Every inherited input is
re-hashed and every new input must be a regular file.  It never reads the
V16 result payload and never starts the proof worker.
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


class OuterV9RequestError(RuntimeError):
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
        raise OuterV9RequestError(f"{role} is not a regular non-symlink file: {target}")
    return target


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OuterV9RequestError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise OuterV9RequestError(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise OuterV9RequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def build_request(*, source_request: Path | str, v9_request: Path | str,
                  v9_consumer: Path | str, output: Path | str,
                  case_id: str, attempt_id: str, worktree_root: Path | str,
                  output_name: str = "fresh-v16-proof-v9.json") -> dict[str, Any]:
    source_path, source = _json(source_request, "source outer request")
    if source.get("schema") != SCHEMA or source.get("kind") != "cpu":
        raise OuterV9RequestError("source outer request must be ds02.request.v1 CPU")
    if not isinstance(case_id, str) or not case_id or not isinstance(attempt_id, str) or not attempt_id:
        raise OuterV9RequestError("case_id and attempt_id are required")
    v9_path = _file(v9_request, "V9 proof request")
    v9_script = _file(v9_consumer, "V9 consumer script")
    if not output_name or "/" in output_name or output_name in {".", ".."}:
        raise OuterV9RequestError("output_name must be a simple filename")
    command = [
        str(source["command"][0]), "-B", "-I", "-c",
        "import importlib.util,os,json;"
        f"s=importlib.util.spec_from_file_location(\"proofconsumer_v9\",{str(v9_script)!r});"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        f"print(json.dumps(m.run({str(v9_path)!r},\"{{attempt_root}}/{output_name}\","
        "io_slot_approved=True,parent_pid=os.getppid(),max_wall_seconds=900.0)))",
    ]
    inherited = [str(x) for x in source.get("input_files", [])]
    # Keep old V8 as an explicit immutable dependency: V9 delegates all
    # contract checks to that source.  Remove no inherited evidence.
    files = [x for x in inherited if x != str(v9_script) and x != str(v9_path)]
    files.extend([str(v9_script), str(v9_path)])
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
        "cwd": str(Path(str(source.get("cwd", Path(v9_script).parent))).expanduser().resolve()),
        "cpu_threads": 1, "max_wall_seconds": 900,
        "estimated_storage_bytes": int(source.get("estimated_storage_bytes", 4 * 1024 * 1024)),
        "command": command, "input_files": unique,
        "qualification": dict(UNKNOWN),
        "worktree_root": str(Path(worktree_root).expanduser().resolve()), "omp_threads": 1,
        "input_hashes": hashes, "input_sha256": dict(hashes),
        "root_forward_provenance": {
            "source_request": str(source_path), "source_request_sha256": sha256_file(source_path),
            "forward_fix": "V9 explicit producer-derived typed-input provenance; undeclared absolute paths remain fatal",
            "max_wall_argument": "900.0 passed explicitly to V9 after V8 omission",
            "hdf5_or_bi4_read_by_builder": False, "model_invoked": False,
            "qualification": dict(UNKNOWN),
        },
    }
    target = _write_new(output, value)
    return {"schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "request": str(target),
            "case_id": case_id, "attempt_id": attempt_id,
            "input_count": len(unique), "request_source_sha256": sha256_file(source_path),
            "v9_request_sha256": sha256_file(v9_path), "v9_consumer_sha256": sha256_file(v9_script),
            "max_wall_seconds": 900, "hdf5_or_bi4_content_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-request", type=Path, required=True)
    parser.add_argument("--v9-request", type=Path, required=True)
    parser.add_argument("--v9-consumer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--worktree-root", type=Path, required=True)
    parser.add_argument("--output-name", default="fresh-v16-proof-v9.json")
    args = parser.parse_args(argv)
    try:
        value = build_request(source_request=args.source_request, v9_request=args.v9_request,
                              v9_consumer=args.v9_consumer, output=args.output,
                              case_id=args.case_id, attempt_id=args.attempt_id,
                              worktree_root=args.worktree_root, output_name=args.output_name)
    except (OuterV9RequestError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"fresh V16 outer V9 request: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
