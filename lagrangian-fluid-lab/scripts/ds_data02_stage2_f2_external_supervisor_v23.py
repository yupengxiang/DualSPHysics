#!/usr/bin/env python3
"""Forward v22 with an explicit parent-I/O execution switch.

The consumed v22 entry validates the request and then calls ``V21.run``
without forwarding the ``io_slot_approved`` decision.  Consequently its
programmatic ``run`` API can only return ``READY_FOR_PARENT_IO_SLOT`` and
cannot execute the reserved path.  This additive v23 wrapper keeps the v22
25-second helper cleanup and source graph, but forwards the approval flag to
the immutable v21 accounting implementation.  It still owns no ledger and
does not relax any source, output, model, or HDF5 guard.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V22_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v22.py")
SPEC = importlib.util.spec_from_file_location("ds02_external_supervisor_v22_for_v23", V22_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - packaging failure
    raise RuntimeError(f"cannot import immutable v22 supervisor: {V22_PATH}")
V22 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V22)

SCHEMA = V22.SCHEMA
UNKNOWN = V22.UNKNOWN
V23Error = V22.V22Error
HELPER_CLEANUP_GRACE_SECONDS = float(V22.HELPER_CLEANUP_GRACE_SECONDS)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V22.canonical_sha(value)


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V23Error(f"JSON object required: {path}")
    return value


def _binding(path: Path, role: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise V23Error(f"v23 source binding is missing: {target}")
    stat = target.stat()
    return {"role": role, "path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(target),
            "source_kind": "static", "content_scope": "content_sha256"}


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise V23Error(f"refusing existing v23 request: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def build_request(v14_path: Path | str, output_path: Path | str, *,
                  output_root: Path | str, max_wall_seconds: float = 6000.0) -> dict[str, Any]:
    """Build a fresh v23 request from the immutable v22/v21 graph."""
    # V22's builder creates only this new output path; it never changes an
    # existing request.  We then seal the additive v23 binding in the same
    # newly-created file before exposing it to a parent guard.
    V22.build_request(v14_path, output_path, output_root=output_root,
                      max_wall_seconds=max_wall_seconds)
    output = Path(output_path).expanduser().resolve()
    request = load_json(output)
    bindings = list(request.get("static_bindings", []))
    bindings.append(_binding(SCRIPT, "external_supervisor_v23"))
    request["static_bindings"] = bindings
    request["forward_runtime"] = {
        "schema": "ds02.stage2.f2-external-supervisor-runtime.v23",
        "path": str(SCRIPT), "sha256": sha256_file(SCRIPT), "immutable": True,
        "forward_of": {"path": str(V22_PATH), "sha256": sha256_file(V22_PATH)},
        "io_slot_flag_forwarded": True,
        "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
        "cold_terminal_scope": "v21 child and v20 helper groups retain the v22 25 s grace",
    }
    execution = dict(request.get("execution", {}))
    execution["outer_entrypoint"] = str(SCRIPT)
    execution["outer_entrypoint_sha256"] = sha256_file(SCRIPT)
    execution["io_slot_approved_flag"] = "--io-slot-approved"
    execution["outer_command"] = ["<bound-supervisor-python>", str(SCRIPT), "run",
                                   "--request", "<v23-request>",
                                   "--io-slot-approved", "--parent-pid",
                                   "<supervising-parent-pid>"]
    request["execution"] = execution
    request["limitations"] = list(request.get("limitations", [])) + [
        "v23 fixes only the v22 programmatic execution switch; v22 request/source bytes remain immutable.",
        "Metadata validation occurs before the v21 entry timer; the parent must account for this small preflight phase.",
        "Local finalization and OS cleanup are reported separately when the parent deadline is exceeded.",
    ]
    request["sha256"] = canonical_sha(request)
    # This output was created by V22.build_request in this function; refuse
    # any pre-existing destination before replacing only that new file.
    output.unlink()
    _write_new(output, request)
    return request


def validate_request(request_path: Path | str, *, verify_content: bool = False) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != SCHEMA:
        raise V23Error("v23 accepts only the immutable v21 supervisor schema")
    forward = request.get("forward_runtime")
    if not isinstance(forward, Mapping) or forward.get("path") != str(SCRIPT):
        raise V23Error("v23 forward runtime binding is missing")
    if forward.get("sha256") != sha256_file(SCRIPT):
        raise V23Error("v23 forward runtime SHA differs")
    if float(forward.get("helper_cleanup_grace_seconds", 0.0) or 0.0) < HELPER_CLEANUP_GRACE_SECONDS:
        raise V23Error("v23 helper cleanup grace is less than 25 seconds")
    bindings = request.get("static_bindings")
    if not isinstance(bindings, list) or not any(
            isinstance(item, Mapping) and item.get("role") == "external_supervisor_v23"
            for item in bindings):
        raise V23Error("v23 static source binding is missing")
    # V21 validates the immutable v14 graph, output namespace, parent ledger,
    # policy, and source closure.  V22's forward path check is intentionally
    # not reused because the request now names this v23 source.
    return V22.V21._validate_request(request, verify_content=verify_content)


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    validate_request(request_file, verify_content=True)
    V22._install_forward_helpers()
    return V22.V21.run(request_file, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v14-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=6000.0)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--verify-content", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v14_request, args.output,
                                  output_root=args.output_root,
                                  max_wall_seconds=args.max_wall_seconds)
            result = {"status": value["status"], "sha256": value["sha256"],
                      "path": str(args.output.expanduser().resolve()),
                      "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS}
        elif args.command == "validate":
            value = validate_request(args.request, verify_content=args.verify_content)
            result = {"status": "VALIDATED_V23", "v14": str(value["v14_path"]),
                      "helper_cleanup_grace_seconds": value["child_cleanup_grace_seconds"]}
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid)
    except (V23Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0 if str(result.get("status", "")).startswith(("READY_", "VALIDATED_", "COMPLETED_")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
