#!/usr/bin/env python3
"""Forward a V45 parent request with its missing direct runtime closure.

The V45 parent request was metadata-valid, but its ``static_bindings`` stopped
at the V6 wrapper and the V45 executor.  The V6 wrapper imports the shared V2
runtime, while the closed command invokes the project virtual-environment
interpreter.  V46 is a parent-request overlay that records those two direct
edges and the V45 -> V41 -> V43 -> V38 -> V34 code edges.  It does not run the
executor and it does not read or hash H5, BI4, raw frames, or result payloads.

The overlay keeps the literal interpreter path in ``argv[0]``.  A symlink may
be stat'ed and hashed for provenance, but it is never replaced with
``Path.resolve()``: doing that would select the system NumPy/h5py ABI.  The
base V45 request remains immutable; the output is a new canonical parent
request and is still DEVELOPMENT/UNKNOWN.  The parent V3 guard remains the
only ledger owner.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-parent-v46-static-closure.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
VENV_SUFFIX = "/lagrangian-fluid-lab/.venv/bin/python"


class ParentV46Error(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise ParentV46Error(f"{role} is not a regular file: {target}")
    if target.stat().st_size > 32 * 1024 * 1024:
        raise ParentV46Error(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ParentV46Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ParentV46Error(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise ParentV46Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise ParentV46Error(f"{role} must be a lowercase SHA-256")
    return value


def _path_from_item(item: Mapping[str, Any], role: str) -> Path:
    path = item.get("path")
    if not isinstance(path, str) or not path:
        raise ParentV46Error(f"{role} path is missing")
    target = Path(path).expanduser()
    if not target.is_file():
        raise ParentV46Error(f"{role} is missing: {target}")
    return target


def _binding(path: Path | str, role: str, *, literal_invocation: bool = False) -> dict[str, Any]:
    """Record one small code/interpreter source without rewriting its path."""
    target = Path(path).expanduser()
    if target.is_symlink() and not literal_invocation:
        raise ParentV46Error(f"{role} must be a non-symlink source file: {target}")
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ParentV46Error(f"{role} is not a regular file: {target}")
    item: dict[str, Any] = {
        "role": role,
        "path": str(target),
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "sha256": sha256_file(target),
        "immutable": True,
    }
    if literal_invocation:
        item.update({
            "path_semantics": "literal_argv0_preserved;stat_follows_approved_venv_symlink",
            "invocation_path": str(target),
            "resolved_path_provenance": str(target.resolve()),
            "abi_environment": "lagrangian-fluid-lab/.venv",
        })
    return item


def _roles(bindings: list[Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in bindings:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("role"), str):
            raise ParentV46Error("static binding is malformed")
        role = str(raw["role"])
        if role in result:
            raise ParentV46Error(f"duplicate static binding role: {role}")
        result[role] = raw
    return result


def _assert_base(value: Mapping[str, Any], base_path: Path) -> None:
    if value.get("schema") != SCHEMA:
        raise ParentV46Error("base request schema differs")
    if value.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentV46Error("base request is not parent-guard ready")
    if value.get("role") != "DEVELOPMENT" or value.get("qualification") != UNKNOWN:
        raise ParentV46Error("base request must remain DEVELOPMENT/UNKNOWN")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise ParentV46Error("base request must keep model/CFD false")
    if value.get("sha256") != canonical_sha(value):
        raise ParentV46Error("base request canonical SHA differs")
    bindings = value.get("static_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ParentV46Error("base static_bindings are missing")
    roles = _roles(bindings)
    for required in ("parent_executor_v3", "shared_v21_accounting", "shared_runtime_v6",
                     "executor_v34", "executor_v34_request", "os_strace"):
        if required not in roles:
            raise ParentV46Error(f"base static binding is missing: {required}")
    executor = value.get("executor_script")
    command = value.get("execution", {}).get("closed_executor_command", [])
    if not isinstance(executor, Mapping) or not isinstance(command, list) or not command:
        raise ParentV46Error("base executor/closed command is missing")
    if not isinstance(command[0], str) or not command[0].endswith(VENV_SUFFIX):
        raise ParentV46Error("base closed command does not use the approved literal venv")
    if str(executor.get("path", "")) != str(roles["executor_v34"].get("path", "")):
        raise ParentV46Error("base executor script and executor binding differ")
    # The base request itself is small metadata.  This also prevents an
    # accidental payload path from being treated as a source-closure input.
    if base_path.stat().st_size > 32 * 1024 * 1024:
        raise ParentV46Error("base request exceeds metadata bound")


def _existing_or_add(bindings: list[dict[str, Any]], item: dict[str, Any]) -> str:
    role = str(item["role"])
    existing = [row for row in bindings if row.get("role") == role]
    if len(existing) > 1:
        raise ParentV46Error(f"duplicate static binding role: {role}")
    if existing:
        row = existing[0]
        if row.get("path") != item.get("path") or row.get("sha256") != item.get("sha256"):
            raise ParentV46Error(f"existing binding differs for {role}")
        return "existing"
    bindings.append(item)
    return "added"


def _source_dir(value: Mapping[str, Any]) -> Path:
    executor = value.get("executor_script")
    if not isinstance(executor, Mapping):
        raise ParentV46Error("executor_script is missing")
    path = _path_from_item(executor, "executor script")
    return path.parent


def _append_direct_closure(value: dict[str, Any]) -> list[dict[str, Any]]:
    raw_bindings = value.get("static_bindings")
    if not isinstance(raw_bindings, list):
        raise ParentV46Error("static_bindings are missing")
    # Work on dict copies: caller's loaded JSON remains the base snapshot until
    # the final canonical output is written.
    bindings = [dict(row) for row in raw_bindings]
    source_dir = _source_dir(value)
    parent_roles = _roles(bindings)
    additions: list[tuple[str, Path, bool]] = [
        ("runtime_v2", source_dir / "ds_data02_runtime_v2.py", False),
        ("executor_v45", Path(str(value["executor_script"]["path"])), False),
        ("executor_v41_compat", source_dir / "ds_data02_stage2_f2_portable_executor_v41.py", False),
        ("executor_v43_builder", source_dir / "ds_data02_stage2_f2_portable_executor_v43.py", False),
        ("executor_v38_compat", source_dir / "ds_data02_stage2_f2_portable_executor_v38.py", False),
        ("executor_v34_compat", source_dir / "ds_data02_stage2_f2_portable_executor_v34.py", False),
        ("parent_closure_builder_v46", SCRIPT, False),
    ]
    # Use the exact argv[0] from the frozen command.  It is intentionally not
    # resolved, even if it is a symlink to /usr/bin/python3.10.
    command = value["execution"]["closed_executor_command"]
    additions.append(("python_executable", Path(str(command[0])), True))
    results: list[dict[str, Any]] = []
    for role, path, literal in additions:
        item = _binding(path, role, literal_invocation=literal)
        action = _existing_or_add(bindings, item)
        results.append({"role": role, "path": str(path), "action": action,
                        "sha256": item["sha256"], "literal_invocation": literal})
    # The direct imported modules are the actionable closure.  Existing V21,
    # V6, parent V3 and V34-request roles remain unchanged and are recorded in
    # the marker for an offline reviewer.
    value["static_bindings"] = bindings
    value["v46_static_closure"] = {
        "schema": FORWARD_SCHEMA,
        "source_dir": str(source_dir),
        "direct_import_roles": [
            "parent_executor_v3", "shared_v21_accounting", "shared_runtime_v6",
            "runtime_v2", "executor_v45", "executor_v41_compat",
            "executor_v43_builder", "executor_v38_compat", "executor_v34_compat",
            "executor_v34_request", "os_strace", "python_executable",
        ],
        "added_or_verified": results,
        "literal_python_invocation": str(command[0]),
        "resolved_python_provenance": str(Path(str(command[0])).expanduser().resolve()),
        "source_read_scope": "small code/request metadata only; no H5/BI4/raw/result payload",
        "parent_ledger_owner": "parent_executor_v3; no new ledger/reservation owner",
        "scientific_scope": "DEVELOPMENT; QI/QN/QE UNKNOWN",
    }
    return results


def forward_parent(*, base_request: Path | str, output: Path | str,
                   parent_attempt_id: str | None = None) -> dict[str, Any]:
    base_path = Path(base_request).expanduser()
    value = _load_json(base_path, "base V45 parent request")
    _assert_base(value, base_path)
    output_path = Path(output).expanduser()
    if output_path.exists():
        raise ParentV46Error(f"refusing existing output: {output_path}")
    original_attempt = str(value.get("attempt_id", ""))
    if not original_attempt:
        raise ParentV46Error("base attempt_id is missing")
    new_attempt = str(parent_attempt_id or (original_attempt + "-v46"))
    if not new_attempt or new_attempt == original_attempt:
        raise ParentV46Error("V46 requires a fresh parent attempt id")
    result = copy.deepcopy(value)
    # A fresh parent attempt is mandatory, but all science/source identities,
    # roots, and frozen raw-tree declarations stay inherited and auditable.
    result["attempt_id"] = new_attempt + "::f2-v46-parent"
    parent = dict(result.get("parent_resource_binding", {}))
    accounting = dict(result.get("accounting", {}))
    for section in (parent, accounting):
        if "attempt_id" in section:
            section["attempt_id"] = new_attempt
        if "reservation_id" in section:
            section["reservation_id"] = new_attempt + "::f2-v46-parent-reservation"
        if "charge_id" in section:
            section["charge_id"] = new_attempt + "::f2-v46-parent-charge"
    parent["attempt_id"] = new_attempt
    parent["reservation_id"] = new_attempt + "::f2-v46-parent-reservation"
    parent["charge_id"] = new_attempt + "::f2-v46-parent-charge"
    parent["allow_missing_parent"] = True
    accounting["attempt_id"] = new_attempt
    accounting["reservation_id"] = parent["reservation_id"]
    accounting["charge_id"] = parent["charge_id"]
    accounting["allow_missing_parent"] = True
    result["parent_resource_binding"] = parent
    result["accounting"] = accounting
    _append_direct_closure(result)
    # Keep the V3 wire-level status.  The immutable parent runner rejects
    # unknown status strings before inspecting the additive V46 marker.
    result["status"] = "READY_FOR_PARENT_GUARD"
    result["forward_v46"] = {
        "schema": FORWARD_SCHEMA,
        "base_parent_request": {"path": str(base_path), "sha256": sha256_file(base_path)},
        "base_canonical_sha256": value["sha256"],
        "fresh_parent_attempt": new_attempt,
        "allow_missing_parent_scope": "new same-ledger attempt only; no fabricated ancestor/charge",
        "payload_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    result["qualification"] = dict(UNKNOWN)
    result["sha256"] = canonical_sha(result)
    _write_new(output_path, result)
    return {
        "status": "READY_FOR_PARENT_GUARD_V46_STATIC_CLOSURE",
        "request": str(output_path),
        "request_sha256": result["sha256"],
        "base_parent_sha256": value["sha256"],
        "parent_attempt_id": new_attempt,
        "static_binding_count": len(result["static_bindings"]),
        "added_or_verified": result["v46_static_closure"]["added_or_verified"],
        "h5_bi4_raw_result_payload_read": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent-attempt-id")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(forward_parent(base_request=args.base_request,
                                        output=args.output,
                                        parent_attempt_id=args.parent_attempt_id),
                         sort_keys=True, ensure_ascii=False))
    except (ParentV46Error, OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
