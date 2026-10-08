#!/usr/bin/env python3
"""V44 forward runtime for the relocated F2 producer.

V43 made SHA-verified small-file stat migration possible, but its refreshed
top-level ``mtime_ns``/``mode_bits`` could leave the nested V36 permission
contract (``source_stat_expected``/``source_mode_bits``) stale.  V44 carries
that migration through every nested contract and binds a new executor source.

The V41 runtime also passed a remaining *duration* to a callee that treated it
as an absolute monotonic deadline, subtracting the clock twice.  V44 wraps the
immutable V41 runtime at the process boundary and converts that duration back
to one absolute deadline.  It additionally patches the bound V34 copy hook to
preserve source mode bits, so executable decoder files remain executable in
the private bundle.  No H5, BI4, raw frame, or result payload is read by the
metadata builder.  Scientific status remains DEVELOPMENT/UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V41_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v41.py"
V43_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v43.py"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
V44_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v44-forward.v1"
V44_DEADLINE_SCHEMA = "ds02.stage2.f2-portable-executor-v44-deadline.v1"


class PortableV44Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PortableV44Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V41 = _load(V41_SCRIPT, "ds02_bound_f2_portable_executor_v41_for_v44")
V43 = _load(V43_SCRIPT, "ds02_bound_f2_portable_executor_v43_for_v44")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V41.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    return V41.sha256_file(path)


def _load_json(path: Path | str, role: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > max_bytes:
        raise PortableV44Error(f"{role} is missing, symlinked, or too large: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV44Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV44Error(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise PortableV44Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _stat_record(path: Path) -> dict[str, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise PortableV44Error(f"bound source is not a regular file: {path}")
    return {
        "st_dev": int(info.st_dev), "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode), "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink), "st_uid": int(info.st_uid),
        "st_gid": int(info.st_gid), "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns), "st_ctime_ns": int(info.st_ctime_ns),
    }


def _payload_role(role: str) -> bool:
    # Keep the V43 scientific-payload classification.  ``raw_converter`` and
    # other ``raw_*`` names are source-code roles and remain eligible for the
    # small SHA-verified stat migration; only raw frame/auxiliary data and the
    # explicitly protected V43 payload roles are stat-strict.
    return V43._payload_role(role) or role in {
        "native_partout", "native_reconciliation", "native_reconciliation_receipt",
    }


def _small_migration(item: Mapping[str, Any], *, role: str) -> bool:
    path = Path(str(item.get("path", ""))).expanduser()
    try:
        size = int(path.stat().st_size)
    except OSError:
        return False
    return (not _payload_role(role) and size <= V43.SMALL_REFRESH_MAX_BYTES
            and isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64)


def _synchronize_nested_stat_contract(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Refresh all stat mirrors after a small binding's full SHA succeeds.

    ``source_stat_expected`` is an execution contract, so leaving the old
    inode/ctime/mtime there would make the later V36 checker reject a valid
    relocated source even though the top-level stat was refreshed.  The old
    record is retained as provenance; the actual current record is the one
    used by downstream mode/stat validation.
    """
    refreshes: list[dict[str, Any]] = []
    for section in ("source_entries", "runtime_sources"):
        rows = value.get(section)
        if not isinstance(rows, list):
            continue
        for index, raw in enumerate(rows):
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role", f"{section}[{index}]"))
            expected = raw.get("source_stat_expected")
            if not isinstance(expected, Mapping):
                continue
            source = Path(str(raw.get("path", ""))).expanduser()
            actual = _stat_record(source)
            relevant = ("st_dev", "st_ino", "st_mode", "mode_bits", "st_nlink",
                        "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")
            differs = any(int(expected.get(key, -1)) != int(actual[key]) for key in relevant)
            top_differs = any(
                key in raw and int(raw[key]) != int(actual[nested])
                for key, nested in (("bytes", "st_size"), ("mtime_ns", "st_mtime_ns"),
                                    ("mode_bits", "mode_bits"),
                                    ("source_mode_bits", "mode_bits")))
            if not (differs or top_differs):
                continue
            if not _small_migration(raw, role=role):
                raise PortableV44Error(
                    f"{role} nested source stat differs for a protected/non-small binding")
            if sha256_file(source) != str(raw["sha256"]):
                raise PortableV44Error(f"{role} content SHA differs during stat migration")
            old = copy.deepcopy(dict(expected))
            raw.setdefault("source_stat_provenance", old)
            raw["source_stat_expected"] = dict(actual)
            raw["source_mode_bits"] = int(actual["mode_bits"])
            raw["bytes"] = int(actual["st_size"])
            raw["mtime_ns"] = int(actual["st_mtime_ns"])
            raw["mode_bits"] = int(actual["mode_bits"])
            refreshes.append({
                "section": section, "index": index, "role": role,
                "path": str(source), "content_sha_verified": True,
                "nested_stat_before": old, "nested_stat_after": dict(actual),
                "source_stat_provenance_retained": True,
            })
    # ``source_contract_binding`` is also consumed downstream, but older
    # forward builders kept only its top-level byte/mtime/mode mirrors while
    # refreshing the corresponding runtime-source row.  Keep both views
    # synchronized after the same small SHA check.  This is still metadata
    # migration: protected payloads are rejected and the old stat remains
    # provenance.
    contract = value.get("source_contract_binding")
    if isinstance(contract, dict) and isinstance(contract.get("path"), str):
        role = str(contract.get("role", "source_contract_binding"))
        source = Path(str(contract["path"])).expanduser()
        actual = _stat_record(source)
        differs = any(
            key in contract and int(contract[key]) != int(actual[nested])
            for key, nested in (("bytes", "st_size"), ("mtime_ns", "st_mtime_ns"),
                                ("mode_bits", "mode_bits"))
        )
        if differs:
            if not _small_migration(contract, role=role):
                raise PortableV44Error(
                    "source_contract_binding stat differs for a protected/non-small binding")
            if sha256_file(source) != str(contract["sha256"]):
                raise PortableV44Error("source_contract_binding content SHA differs during stat migration")
            old = {key: contract.get(key) for key in ("bytes", "mtime_ns", "mode_bits")
                   if key in contract}
            contract.setdefault("source_stat_provenance", old)
            contract.update({"bytes": int(actual["st_size"]),
                             "mtime_ns": int(actual["st_mtime_ns"]),
                             "mode_bits": int(actual["mode_bits"])})
            refreshes.append({
                "section": "source_contract_binding", "index": None, "role": role,
                "path": str(source), "content_sha_verified": True,
                "nested_stat_before": old,
                "nested_stat_after": {key: actual[key] for key in
                                       ("st_size", "st_mtime_ns", "mode_bits")},
                "source_stat_provenance_retained": True,
            })
    return refreshes


def _copy_one_preserving_mode(source: Path, target: Path,
                              expected_sha: str, expected_bytes: int) -> dict[str, Any]:
    """V34-compatible copy hook that retains executable mode and inode proof."""
    if target.exists():
        raise PortableV44Error(f"refusing existing copied target: {target}")
    source = Path(source).expanduser()
    target = Path(target).expanduser()
    source_pre = _stat_record(source)
    if source_pre["st_size"] != int(expected_bytes):
        raise PortableV44Error(f"source byte stat differs: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    os.chmod(target, stat.S_IMODE(source_pre["st_mode"]))
    target_stat = _stat_record(target)
    if (target_stat["st_dev"], target_stat["st_ino"]) == (source_pre["st_dev"], source_pre["st_ino"]):
        raise PortableV44Error(f"copied target inode is not distinct: {target}")
    if target_stat["mode_bits"] != source_pre["mode_bits"]:
        raise PortableV44Error(f"copied target mode differs: {target}")
    target_sha = sha256_file(target)
    if target_stat["st_size"] != int(expected_bytes) or target_sha != expected_sha:
        raise PortableV44Error(f"copied target content differs: {target}")
    return {"path": str(target), "bytes": int(target_stat["st_size"]),
            "mtime_ns": int(target_stat["st_mtime_ns"]), "mode_bits": int(target_stat["mode_bits"]),
            "sha256": target_sha, "source_mode_bits": int(source_pre["mode_bits"]),
            "target_inode_distinct": True, "required_executable": bool(source_pre["mode_bits"] & 0o111)}


def _load_mode_bound_v34() -> Any:
    """Load the actual V34 module and replace only its global copy primitive."""
    original_loader = V41.V38._load_v34
    module = original_loader()
    module._copy_one = _copy_one_preserving_mode
    return module


def _run_evaluator_with_one_deadline(*args: Any, deadline: float | None, **kwargs: Any) -> Any:
    """Adapter for V41's remaining-duration argument.

    V41's caller computes ``remaining = absolute_deadline - now``.  Its
    callee subtracts ``time.monotonic()`` again.  Reconstructing one absolute
    deadline here makes the immutable callee perform exactly one subtraction.
    """
    absolute = None if deadline is None else time.monotonic() + max(0.0, float(deadline))
    return _ORIGINAL_EVALUATOR(*args, deadline=absolute, **kwargs)


_ORIGINAL_EVALUATOR: Any = None


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Run V41 with the mode-preserving copy and one-deadline adapter."""
    global _ORIGINAL_EVALUATOR
    original_loader = V41.V38._load_v34
    original_evaluator = V41._run_evaluator_with_bootstrap
    _ORIGINAL_EVALUATOR = original_evaluator
    V41.V38._load_v34 = _load_mode_bound_v34
    V41._run_evaluator_with_bootstrap = _run_evaluator_with_one_deadline
    try:
        return V41.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        V41.V38._load_v34 = original_loader
        V41._run_evaluator_with_bootstrap = original_evaluator
        _ORIGINAL_EVALUATOR = None


def _rebind_v43(value: dict[str, Any], *, output: Path,
                target_root: Path, output_root: Path,
                parent_attempt_id: str) -> dict[str, Any]:
    refreshes = _synchronize_nested_stat_contract(value)
    command = list(value.get("execution", {}).get("command", []))
    matches = [i for i, item in enumerate(command)
               if isinstance(item, str) and item.endswith("ds_data02_stage2_f2_portable_executor_v41.py")]
    if len(matches) != 1:
        raise PortableV44Error("V43 command has no unique V41 executor operand")
    command[matches[0]] = str(SCRIPT)
    execution = dict(value.get("execution", {}))
    execution["command"] = command
    execution["deadline_contract"] = {
        "schema": V44_DEADLINE_SCHEMA,
        "caller_argument": "remaining_duration_seconds",
        "callee_interpretation": "absolute_monotonic_deadline_after_adapter",
        "subtractions": 1,
    }
    value["execution"] = execution
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV44Error("V43 runtime_sources are missing")
    found = 0
    for item in runtime:
        if not isinstance(item, dict) or item.get("role") != "executor_v41":
            continue
        old = {key: item.get(key) for key in ("path", "bytes", "mtime_ns", "mode_bits", "sha256",
                                               "source_stat_expected", "source_mode_bits")}
        info = _stat_record(SCRIPT)
        item.setdefault("source_stat_provenance", old.get("source_stat_expected"))
        item.update({"path": str(SCRIPT), "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v44.py",
                     "bytes": info["st_size"], "mtime_ns": info["st_mtime_ns"],
                     "mode_bits": info["mode_bits"], "sha256": sha256_file(SCRIPT),
                     "source_stat_expected": info, "source_mode_bits": info["mode_bits"],
                     "compatibility_role": "executor_v41"})
        found += 1
    if found != 1:
        raise PortableV44Error("V43 executor_v41 runtime role is not unique")
    roots = {"target_root": str(target_root), "output_root": str(output_root)}
    value["fresh_roots"] = roots
    parent = dict(value.get("parent_resource_binding", {}))
    parent.update({"attempt_id": parent_attempt_id, "allow_missing_parent": True,
                   "reservation_id": parent_attempt_id + "::v44-reservation",
                   "supplemental_charge_id": parent_attempt_id + "::v44-charge"})
    value["parent_resource_binding"] = parent
    value["request_id"] = str(value.get("request_id", "f2-s1-v43")) + "-v44"
    value["forward_v44"] = {
        "schema": V44_FORWARD_SCHEMA,
        "previous_request_sha256": value.get("sha256"),
        "wrapper": {"path": str(SCRIPT), "sha256": sha256_file(SCRIPT)},
        "nested_stat_refreshes": refreshes,
        "nested_stat_policy": "small_sha_verified_code_json_only; payload_reject",
        "mode_copy_policy": "preserve_source_mode_and_distinct_target_inode",
        "deadline_policy": "one_absolute_monotonic_subtraction",
        "old_v41_request_reuse": "FORBIDDEN",
        "hdf5_bi4_raw_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    value["qualification"] = dict(UNKNOWN)
    value["sha256"] = canonical_sha(value)
    _write_new(output, value)
    return value


def build_from_v43(*, base_request: Path | str, output: Path | str,
                   target_root: Path | str, output_root: Path | str,
                   parent_attempt_id: str) -> dict[str, Any]:
    """Make a fresh V44 request from a V43 request without payload reads."""
    base = _load_json(base_request, "V43 executor request")
    if base.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise PortableV44Error("V43 base schema differs")
    if base.get("sha256") != canonical_sha(base):
        raise PortableV44Error("V43 base canonical SHA differs")
    if not isinstance(base.get("forward_v43"), Mapping):
        raise PortableV44Error("V43 forward marker is missing")
    target = Path(target_root).expanduser().resolve()
    product = Path(output_root).expanduser().resolve()
    if target.exists() or product.exists() or target == product:
        raise PortableV44Error("V44 target/output roots must be fresh and distinct")
    value = copy.deepcopy(base)
    rebound = _rebind_v43(value, output=Path(output).expanduser(),
                           target_root=target, output_root=product,
                           parent_attempt_id=parent_attempt_id)
    return {"status": "READY_FOR_PARENT_V44_METADATA_ONLY",
            "request": str(Path(output).expanduser()),
            "request_sha256": rebound["sha256"],
            "nested_stat_refresh_count": len(rebound["forward_v44"]["nested_stat_refreshes"]),
            "raw_h5_sha_during_build": False, "qualification": dict(UNKNOWN)}


def build_parent(*, executor_request: Path | str, output: Path | str,
                 external_filesystem: Path | str, ledger_path: Path | str,
                 parent_attempt_id: str, max_wall_seconds: float,
                 home_receipt_path: Path | str, supervisor_output_root: Path | str,
                 home_path: Path | str = "/home/jade", home_min_free_bytes: int | None = None,
                 external_bytes: int | None = None, home_receipt_bytes: int = 65536,
                 allow_missing_parent: bool = True) -> dict[str, Any]:
    old_script = V41.SCRIPT
    try:
        V41.SCRIPT = SCRIPT
        return V41.build_parent(executor_request=executor_request, output=output,
                                external_filesystem=external_filesystem, ledger_path=ledger_path,
                                parent_attempt_id=parent_attempt_id, max_wall_seconds=max_wall_seconds,
                                home_receipt_path=home_receipt_path,
                                supervisor_output_root=supervisor_output_root, home_path=home_path,
                                home_min_free_bytes=home_min_free_bytes, external_bytes=external_bytes,
                                home_receipt_bytes=home_receipt_bytes,
                                allow_missing_parent=allow_missing_parent)
    finally:
        V41.SCRIPT = old_script


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    forward = sub.add_parser("build-from-v43")
    forward.add_argument("--base-request", type=Path, required=True)
    forward.add_argument("--output", type=Path, required=True)
    forward.add_argument("--target-root", type=Path, required=True)
    forward.add_argument("--output-root", type=Path, required=True)
    forward.add_argument("--parent-attempt-id", required=True)
    parent = sub.add_parser("build-parent")
    parent.add_argument("--executor-request", type=Path, required=True)
    parent.add_argument("--output", type=Path, required=True)
    parent.add_argument("--external-filesystem", type=Path, required=True)
    parent.add_argument("--ledger-path", type=Path, required=True)
    parent.add_argument("--parent-attempt-id", required=True)
    parent.add_argument("--max-wall-seconds", type=float, required=True)
    parent.add_argument("--home-receipt-path", type=Path, required=True)
    parent.add_argument("--supervisor-output-root", type=Path, required=True)
    parent.add_argument("--home-path", type=Path, default=Path("/home/jade"))
    parent.add_argument("--home-min-free-bytes", type=int)
    parent.add_argument("--external-bytes", type=int)
    parent.add_argument("--home-receipt-bytes", type=int, default=65536)
    parent.add_argument("--allow-missing-parent", action=argparse.BooleanOptionalAction, default=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--evaluator-proof", type=Path)
    run_parser.add_argument("--max-wall-seconds", type=float)
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
    pre.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-from-v43":
            result = build_from_v43(base_request=args.base_request, output=args.output,
                                     target_root=args.target_root, output_root=args.output_root,
                                     parent_attempt_id=args.parent_attempt_id)
        elif args.command == "build-parent":
            result = build_parent(executor_request=args.executor_request, output=args.output,
                                  external_filesystem=args.external_filesystem,
                                  ledger_path=args.ledger_path,
                                  parent_attempt_id=args.parent_attempt_id,
                                  max_wall_seconds=args.max_wall_seconds,
                                  home_receipt_path=args.home_receipt_path,
                                  supervisor_output_root=args.supervisor_output_root,
                                  home_path=args.home_path,
                                  home_min_free_bytes=args.home_min_free_bytes,
                                  external_bytes=args.external_bytes,
                                  home_receipt_bytes=args.home_receipt_bytes,
                                  allow_missing_parent=args.allow_missing_parent)
        elif args.command == "preflight":
            result = V41.preflight(args.request, args.output)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV44Error, V41.PortableV41Error, V41.V38.PortableV38Error,
            V41.V40.ColdProducerV40Error, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"f2 portable executor v44: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
