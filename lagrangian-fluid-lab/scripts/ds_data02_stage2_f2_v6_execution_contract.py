#!/usr/bin/env python3
"""Build a source-bound execution contract for the v6 F2 bridge.

This file is a command/dependency manifest, not a launcher.  It gives the
parent process the exact metadata preflight and approved-I/O argv while making
the cancellation boundary explicit: the bridge owns the nested ledger
reservation and artifact accounting, whereas the shared parent supervisor
owns hard wall time, process-group cancellation, and the OS open trace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-v6-portable-execution-contract.v1"
BRIDGE_SCHEMAS = {
    "ds02.stage2.f2-portable-ledger-bridge-request.v9",
    "ds02.stage2.f2-portable-ledger-bridge-request.v10",
}
V6_ROLES = {
    "shared_dispatch_v6",
    "shared_strict_dispatch_v6",
    "shared_runtime_v6",
    "shared_runtime_v2",
}
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class ContractError(ValueError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ContractError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _file_ref(item: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(item.get("path"))).expanduser().resolve()
    if not path.is_file():
        raise ContractError(f"bound input is missing: {path}")
    stat = path.stat()
    mutable_parent = item.get("source_kind") == "parent"
    expected_bytes = item.get("bytes")
    expected_mtime = item.get("mtime_ns")
    if not mutable_parent and expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise ContractError(f"bound input byte stat differs: {path}")
    if not mutable_parent and expected_mtime is not None and int(expected_mtime) != stat.st_mtime_ns:
        raise ContractError(f"bound input mtime stat differs: {path}")
    expected_sha = item.get("sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ContractError(f"bound input lacks SHA: {path}")
    role = str(item.get("role", ""))
    # Small code/contract sources are verified now.  Large copy sources retain
    # the request's expected SHA and are intentionally post-hashed only after
    # the parent reservation, so this builder never opens H5/BI4/CSV payloads.
    large_copy = item.get("content_scope") == "v7_target_seal_for_copy_source"
    actual = sha256_file(path) if not large_copy and not mutable_parent else None
    if actual is not None and actual != expected_sha:
        raise ContractError(f"bound input SHA differs: {path}")
    return {"role": role, "path": str(path), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": expected_sha,
            "sha_verification": "MUTABLE_PARENT_SEMANTIC_RECHECK" if mutable_parent else
            "PARENT_POSTHASH_REQUIRED" if large_copy else "BUILDER_VERIFIED",
            "content_scope": item.get("content_scope", "static_metadata_or_code")}


def build(request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    if request.get("schema") not in BRIDGE_SCHEMAS:
        raise ContractError("request is not a supported v9/v10 bridge schema")
    if request.get("sha256") != canonical_sha(request):
        raise ContractError("bridge request canonical SHA differs")
    guards = request.get("guard_bindings")
    if not isinstance(guards, list) or {item.get("role") for item in guards} != V6_ROLES:
        raise ContractError("v6 guard closure is incomplete")
    sources = request.get("source_bindings")
    if not isinstance(sources, list) or not sources:
        raise ContractError("bridge source_bindings are required")
    refs = [_file_ref(item) for item in sources]
    bridge = next((item for item in refs if item["role"].startswith("portable_ledger_bridge_")), None)
    if bridge is None:
        raise ContractError("forward v6 bridge source is not bound")
    python = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
    bridge_path = bridge["path"]
    request_arg = str(request_file)
    max_wall = int(request["reservation"]["max_wall_seconds"])
    trace_path = str(Path(request["external_storage_scope"]["filesystem"]).expanduser().resolve().parent /
                     f"os-open-trace-{request['attempt_id']}.log")
    preflight = [python, "-B", bridge_path, "run", "--request", request_arg]
    approved = [python, "-B", bridge_path, "run", "--request", request_arg, "--io-slot-approved"]
    traced = ["strace", "-ff", "-e", "trace=openat,openat2,creat,truncate,rename,unlink,statx",
              "-o", trace_path, *approved]
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "request": {"path": str(request_file), "sha256": request["sha256"],
                     "attempt_id": request["attempt_id"], "schema": request["schema"]},
        "qualification": dict(UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
        "commands": {
            "metadata_preflight": preflight,
            "approved_io_child": approved,
            "approved_io_os_trace": traced,
            "metadata_preflight_scope": "stat/hash/closure only; no H5/BI4 read and no ledger mutation",
        },
        "dependencies": {
            "shared_v6_guard_roles": [
                {"role": item["role"], "path": item["path"], "sha256": item["sha256"]}
                for item in refs if item["role"] in V6_ROLES
            ],
            "bridge": bridge,
            "source_binding_count": len(refs),
            "all_declared_input_roles": sorted(item["role"] for item in refs),
            "nested_v7_and_loader_closure": "inherited exactly from bridge source_bindings; no original-path fallback",
            "h5_bi4_csv_content": "parent I/O slot only; builder does not open these payloads",
        },
        "parent_boundary": {
            "hard_wall_seconds": max_wall,
            "hard_wall_owner": "bridge entry-to-finalization timer plus shared parent process-group supervisor",
            "cpu_storage_ledger_owner": "v6 bridge reservation/charge under the existing parent ledger lock",
            "cancellation": {
                "normal": "parent supervisor sends SIGTERM to the bridge process group, then SIGKILL after its grace period",
                "supervisor_death": "dispatch_v6 --parent-pid uses PR_SET_PDEATHSIG=SIGTERM when that entry is selected",
                "nested_loader": "inherits the bridge process group and is terminated with it",
                "bridge_inner_timeout": True,
                "bridge_timer_scope": "SIGALRM spans source validation, reservation, copy/seal, nested loader, source posthash, and artifact accounting; disabled only before terminal receipt/charge",
            },
            "no_nested_runtime_reservation": True,
            "reason": "the v9 bridge itself registers and charges its attempt; wrapping it in another ledger-owning v6 run would double-charge the parent",
            "os_trace_owner": "parent supervisor; Python audit is complementary and cannot see native C HDF5/BI4 opens",
        },
        "resource_request": {
            "cpu_threads": int(request["reservation"]["cpu_threads"]),
            "cpu_core_seconds": int(request["reservation"]["cpu_core_seconds"]),
            "max_wall_seconds": max_wall,
            "external_product_reserved_bytes": int(request["reservation"]["external_product_reserved_bytes"]),
            "home_receipt_reserved_bytes": int(request["reservation"]["home_receipt_reserved_bytes"]),
            "new_storage_bytes": int(request["reservation"]["new_storage_bytes"]),
            "rss": "observational getrusage only; no RLIMIT_AS claim",
        },
        "limitations": [
            "The contract is a parent-ready command/dependency manifest, not a replay receipt.",
            "The v10 bridge provides an inner timer and child-group cleanup, but a direct un-supervised invocation is still not an acceptable parent run because the parent owns cancellation, reservation lease, and native-open tracing.",
            "All QI/QN/QE remain UNKNOWN and no metadata preflight grants raw-to-label credit.",
        ],
    }
    value["sha256"] = canonical_sha(value)
    write_new(output_path, value)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build(args.request, args.output)
    except (ContractError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                      "input_count": value["dependencies"]["source_binding_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
