#!/usr/bin/env python3
"""V57 forward for the ROOT145 copied-worker recovery boundary.

V56's run hook called the V55 globals after replacing them, so the real
V55/V54 boundary recursed.  V57 captures those immutable callables before
installing its wrappers.  It also has a bounded, code-only import smoke for
the plain worker's lazy converter/v14/v15/v16 graph.

The build command reads only bounded JSON/code metadata.  It never reads or
hashes BI4, HDF5, or result payloads.  Parent receipt and returned report are
separate lineage inputs; a synthetic merged report is rejected.
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
from typing import Any, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
V56_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v56.py"
V57_SCHEMA = "ds02.stage2.f2-portable-executor-v57-forward.v1"
RECOVERY_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-request.v57"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
WORKER_NAME = "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
PINNED_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
IMPORT_TIMEOUT_SECONDS = 60.0
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class PortableV57Error(RuntimeError):
    pass


def _load_v56() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_v56_for_v57", V56_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV57Error(f"cannot load V56: {V56_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V56 = _load_v56()
V55 = V56.V55
CORE = V56.CORE

# Capture before any hook is installed.  Calling V55 attributes after
# replacing them is the recursion that V56 accidentally introduced.
_ORIGINAL_V55_ALIAS = V55._materialize_aliases_in_worker_parent
_ORIGINAL_V55_IMPORT = V55._import_four_modules
_ACTIVE_REQUEST: Mapping[str, Any] | None = None


def _sha(path: Path, *, max_bytes: int | None = None) -> str:
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise PortableV57Error(f"bounded file exceeds limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return V56.canonical_sha(value)


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV57Error(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str, *, limit: int | None = None) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PortableV57Error(f"{role} is not a regular non-symlink file: {target}")
    maximum = CORE.MAX_JSON_BYTES if limit is None else int(limit)
    if target.stat().st_size > maximum:
        raise PortableV57Error(f"{role} exceeds bounded metadata size")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV57Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV57Error(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PortableV57Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return target


def _base_request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = V56._request_v55(path)
    if value.get("schema") != V34_SCHEMA:
        raise PortableV57Error("base request is not V34")
    return target, value


def _fresh(path: Path | str, role: str) -> Path:
    target = _absolute(str(path), role)
    if target.exists() or target.is_symlink():
        raise PortableV57Error(f"{role} must be a fresh namespace: {target}")
    return target


def _fixed_command(command: Any, target: Path) -> list[str]:
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise PortableV57Error("base execution command is malformed")
    positions = [i for i, item in enumerate(command)
                 if item.endswith("ds_data02_stage2_f2_portable_executor_v56.py")]
    if len(positions) != 1:
        raise PortableV57Error("base command has no unique V56 executor")
    result = list(command)
    result[positions[0]] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v57.py")
    return result


def _replace_executor(runtime: list[Any], target: Path) -> None:
    kept = [row for row in runtime
            if not (isinstance(row, Mapping) and row.get("role") == "executor_v56")]
    info = SCRIPT.stat()
    kept.append({
        "role": "executor_v57",
        "path": str(SCRIPT),
        "resolved_source_path": str(SCRIPT),
        "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v57.py",
        "target_path": str(
            target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v57.py"),
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "source_mode_bits": int(stat.S_IMODE(info.st_mode)),
        "sha256": _sha(SCRIPT),
        "required_executable": False,
        "source_path_fallback": "FORBIDDEN",
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
    })
    runtime[:] = kept


def build_recovery(*, base_request: Path | str, output_request: Path | str,
                   target_root: Path | str, output_root: Path | str,
                   prior_parent_receipt: Path | str,
                   prior_returned_report: Path | str,
                   graph_report: Path | str | None = None,
                   reused_bundle_root: Path | str | None = None) -> dict[str, Any]:
    """Build a new V34-compatible recovery request from small metadata."""
    source_path, _ = _base_request(base_request)
    receipt_path, receipt = _json(prior_parent_receipt, "previous parent receipt")
    returned_path, returned = _json(prior_returned_report, "previous returned report")
    if receipt_path == returned_path:
        raise PortableV57Error("parent receipt and returned report must be separate files")
    request = receipt.get("request")
    request_sha = request.get("sha256") if isinstance(request, Mapping) else None
    returned_sha = returned.get("request_sha256")
    if not isinstance(request_sha, str) or len(request_sha) != 64:
        raise PortableV57Error("parent receipt lacks request.sha256")
    if returned_sha != request_sha:
        raise PortableV57Error("returned report is not bound to receipt request")
    charge = returned.get("charge")
    if not isinstance(charge, Mapping) or not charge.get("ledger_mutated"):
        raise PortableV57Error("returned report lacks independent ledger mutation")

    target = _fresh(target_root, "target_root")
    product = _fresh(output_root, "output_root")
    if target == product:
        raise PortableV57Error("target and output roots must be distinct")

    # V56 is used as a metadata rebasing function only.  The intermediate
    # request is private to this build and is never a scientific artifact.
    with tempfile.TemporaryDirectory(prefix="ds02-v57-metadata-") as temp:
        intermediate = Path(temp) / "v56-request.json"
        V56.build_forward(v55_request=source_path, output_request=intermediate,
                          target_root=target, output_root=product)
        value = json.loads(intermediate.read_text(encoding="utf-8"))

    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV57Error("rebased request has no runtime_sources")
    _replace_executor(runtime, target)
    execution = value.get("execution")
    if not isinstance(execution, dict):
        raise PortableV57Error("rebased request has no execution object")
    execution["command"] = _fixed_command(execution.get("command"), target)
    execution["executor_script_target_path"] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v57.py")
    execution["runtime_target_root"] = str(target / "runtime")
    execution["actual_cli_contract"] = {
        "argv0": PINNED_PYTHON,
        "executor": "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v57.py",
        "subcommand": "run",
        "required_flags": ["--request", "--io-slot-approved", "--parent-pid",
                           "--max-wall-seconds"],
        "literal_venv_path_preserved": True,
        "resolve_argv0_forbidden": True,
    }

    attempt = "f2-s1-root145-v57-recovery-20261009-001"
    parent = value.get("parent_resource_binding")
    if not isinstance(parent, dict):
        raise PortableV57Error("parent_resource_binding is missing")
    parent.update({
        "attempt_id": attempt,
        "reservation_id": attempt + "::reservation",
        "supplemental_charge_id": attempt + "::charge",
        "allow_missing_parent": True,
        "same_parent_ledger": True,
        "ledger_reset": False,
    })
    scope = value.get("storage_scope")
    if not isinstance(scope, dict):
        raise PortableV57Error("storage_scope is missing")
    scope.update({
        "parent_attempt_id": attempt,
        "external_output_root": str(product),
        "supervisor_output_root": str(product.parent / "supervisor"),
        "source_copy_bytes": 0,
        "new_namespace_absent_before_run": True,
        "reused_source_copy_bytes_not_recharged": True,
        "payload_content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
    })
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    value["request_id"] = attempt
    value["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    value["raw_opened"] = False
    value["hdf5_opened"] = False
    value["model_invoked"] = False
    value["cfd_invoked"] = False
    value["qualification"] = dict(UNKNOWN)

    old_namespace = Path(
        "/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V55_RELOCATED_COLD_20261009")
    reused = _absolute(str(reused_bundle_root or (old_namespace / "bundle-target")),
                       "reused_bundle_root")
    graph_meta = None
    if graph_report is not None:
        graph_path, graph_value = _json(graph_report, "V56 graph report")
        graph_meta = {"path": str(graph_path),
                      "sha256": _sha(graph_path, max_bytes=CORE.MAX_JSON_BYTES),
                      "status": graph_value.get("status")}

    value["forward_v57"] = {
        "schema": V57_SCHEMA,
        "previous_request": {
            "path": str(source_path),
            "sha256": _sha(source_path, max_bytes=CORE.MAX_JSON_BYTES),
        },
        "previous_v55_parent_receipt": {
            "path": str(receipt_path),
            "sha256": _sha(receipt_path, max_bytes=CORE.MAX_JSON_BYTES),
        },
        "previous_v55_returned_report": {
            "path": str(returned_path),
            "sha256": _sha(returned_path, max_bytes=CORE.MAX_JSON_BYTES),
        },
        "previous_request_sha256": request_sha,
        "graph_report": graph_meta,
        "recovery_namespace": {
            "target_root": str(target), "output_root": str(product),
            "attempt_id": attempt,
        },
        "reused_immutable_copy": {
            "bundle_root": str(reused),
            "read_only_source_role": "explicit_existing_root145_copied_source",
            "new_copy_forbidden": True,
            "source_path_fallback": "FORBIDDEN",
            "content_verification": "AFTER_ATOMIC_PARENT_RESERVATION",
            "raw_root_layout": (
                "PARENT_MUST_BIND_EXACT_RAW_DATA_ROOT; the ROOT145 bundle root "
                "also contains code/metadata and must not silently be treated as raw root"),
        },
        "parent_receipt_returned_report_split": {
            "parent_receipt_role": "request/path/execution/accounting pending at receipt write",
            "returned_report_role": "request_sha256/report_path/charge.ledger_mutated after terminal accounting",
            "join_keys": ["request_sha256", "attempt_id", "charge_id",
                          "ledger_path", "output_namespace"],
            "synthetic_combined_report_forbidden": True,
            "new_parent_receipt_path": str(
                product.parent / "supervisor" / "f2-s1-root145-v57-parent-receipt.json"),
            "new_returned_report_path": str(
                product.parent / "supervisor" / "f2-s1-root145-v57-returned-report.json"),
            "status": "PENDING_PARENT_EXECUTION",
        },
        "dependency_inventory": {
            "status": "SOURCE_ONLY_PENDING_GRAPH_AND_PARENT_GUARD",
            "plain_worker_lookup": "wrapper._worker_path() -> target/runtime/native/WORKER_NAME",
            "plain_worker_parent": "target/runtime/runtime/native source plus target/runtime/native compatibility copy",
            "overlay_alias_parent": "target/sources; four sibling aliases stay here",
            "lazy_import_graph": ["raw_converter", "v14_operator",
                                  "v15_operator", "v16_operator"],
            "top_level_libraries": ["h5py", "numpy"],
            "pinned_interpreter": PINNED_PYTHON,
            "partvtk": {
                "worker_call": {"partvtk": None, "run_partvtk": False},
                "executable_consumed": False,
                "initial_csv_and_stats": "evidence-only source roles",
                "native_decoder": "native_bi4_decoder executable is separate",
            },
            "source_path_fallback": "FORBIDDEN",
        },
        "fresh_cold_credit": False,
        "qualification": dict(UNKNOWN),
    }
    value["sha256"] = _canonical(value)
    out = _write_new(output_request, value)
    return {
        "schema": RECOVERY_SCHEMA,
        "status": value["status"],
        "request": str(out),
        "request_sha256": _sha(out, max_bytes=CORE.MAX_JSON_BYTES),
        "payload_read": False,
        "fresh_cold_credit": False,
        "qualification": dict(UNKNOWN),
        "prior_parent_receipt": str(receipt_path),
        "prior_returned_report": str(returned_path),
    }


def _copy_small(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise PortableV57Error(f"scratch target already exists: {target}")
    shutil.copyfile(source, target)
    os.chmod(target, stat.S_IMODE(source.stat().st_mode))


def smoke_plain_worker_graph(python: Path | str, request: Mapping[str, Any],
                             records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Import V4, its plain worker, and all lazy operator modules.

    The subprocess gets code paths only.  It never receives a request or a
    data-root path and therefore cannot open BI4/HDF5/result data.
    """
    if not records or not isinstance(records[0].get("worker_parent"), str):
        raise PortableV57Error("worker-parent aliases are missing")
    worker_parent = Path(str(records[0]["worker_parent"])).expanduser().resolve()
    wrapper = V56._wrapper(request, worker_parent)
    compatibility = V56._ACTIVE_COMPATIBILITY
    if not isinstance(compatibility, Mapping):
        raise PortableV57Error("compatibility target is not materialized")
    python_path = Path(python).expanduser()
    if not python_path.is_file():
        raise PortableV57Error(f"pinned Python is missing: {python_path}")
    bundle_root = worker_parent.parent
    scratch_parent = bundle_root / "scratch-v57-lazy-import"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lazy-", dir=str(scratch_parent)) as temp:
        scratch = Path(temp)
        alias_args = []
        for row in records:
            source = Path(str(row["alias_path"])).expanduser().resolve()
            target = scratch / str(row["canonical_module"])
            _copy_small(source, target)
            alias_args.append(str(target))
        code = r'''
import importlib.util, json, pathlib, sys
wrapper = pathlib.Path(sys.argv[1]).resolve()
plain_expected = pathlib.Path(sys.argv[2]).resolve()
aliases = [pathlib.Path(x).resolve() for x in sys.argv[3:]]
scratch = aliases[0].parent
sys.path.insert(0, str(scratch))
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("no loader for " + str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
wrapper_mod = load(wrapper, "_ds02_v57_wrapper")
plain = wrapper_mod._load_worker()
if pathlib.Path(plain.__file__).resolve() != plain_expected:
    raise RuntimeError("plain worker path mismatch")
loaded = []
for path in aliases:
    loaded.append(str(pathlib.Path(load(path, path.stem).__file__).resolve()))
for index, path in enumerate(aliases):
    plain._load_module(path, "_ds02_v57_lazy_%d" % index)
print(json.dumps({"wrapper": str(wrapper),
                  "plain_worker": str(pathlib.Path(plain.__file__).resolve()),
                  "lazy_modules": loaded}, sort_keys=True))
'''
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME"}}
        try:
            proc = subprocess.run(
                [str(python_path), "-B", "-I", "-c", code,
                 str(wrapper), str(compatibility["target_path"]), *alias_args],
                capture_output=True, text=True, check=False, env=env,
                timeout=IMPORT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise PortableV57Error("plain-worker lazy import graph timed out") from error
        if proc.returncode != 0:
            raise PortableV57Error(
                f"plain-worker lazy import graph failed: {proc.stderr[-1600:]}")
        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise PortableV57Error("plain-worker lazy import graph returned no JSON") from error
    return {
        "status": "PASS_COPIED_PLAIN_WORKER_LAZY_IMPORT_GRAPH",
        "payload_read": False,
        "timeout_seconds": IMPORT_TIMEOUT_SECONDS,
        "original_path_fallback": "FORBIDDEN",
        **result,
    }


def inventory_code_graph(*, wrapper: Path | str, plain_worker: Path | str,
                         aliases: Mapping[str, Path | str],
                         decoder: Path | str,
                         bundle_root: Path | str) -> dict[str, Any]:
    """Source-only dependency inventory for an actual copied namespace."""
    root = _absolute(str(bundle_root), "bundle_root").resolve()
    wrapper_path = V56._regular(wrapper, "V4 wrapper").resolve()
    plain_path = V56._regular(plain_worker, "plain worker").resolve()
    decoder_path = V56._regular(decoder, "native BI4 decoder").resolve()
    for path, role in ((wrapper_path, "V4 wrapper"), (plain_path, "plain worker"),
                       (decoder_path, "native BI4 decoder")):
        try:
            path.relative_to(root)
        except ValueError as error:
            raise PortableV57Error(f"{role} escapes copied bundle") from error
    expected_aliases = {"raw_converter", "v14_operator", "v15_operator", "v16_operator"}
    if set(aliases) != expected_aliases:
        raise PortableV57Error("inventory requires exactly four sibling aliases")
    alias_rows = []
    for role in sorted(expected_aliases):
        path = V56._regular(aliases[role], f"alias {role}").resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise PortableV57Error(f"alias {role} escapes copied bundle") from error
        alias_rows.append({"role": role, "path": str(path),
                           "sha256": _sha(path, max_bytes=1_000_000),
                           "bytes": int(path.stat().st_size),
                           "parent": str(path.parent)})
    wrapper_text = wrapper_path.read_text(encoding="utf-8")
    plain_text = plain_path.read_text(encoding="utf-8")
    decoder_mode = stat.S_IMODE(decoder_path.stat().st_mode)
    if not (decoder_mode & 0o111):
        raise PortableV57Error("native BI4 decoder is not executable")
    required = {
        "wrapper_worker_path_contract": "runtime" in wrapper_text and "native" in wrapper_text and "WORKER_NAME" in wrapper_text,
        "wrapper_load_worker": "def _load_worker" in wrapper_text,
        "plain_load_module": "def _load_module" in plain_text,
        "plain_h5py_import": "import h5py" in plain_text,
        "plain_numpy_import": "import numpy as np" in plain_text,
        "plain_v15_lazy_role": '"v15_operator"' in plain_text,
        "plain_v16_lazy_role": '"v16_operator"' in plain_text,
        "partvtk_disabled_in_label_worker": "partvtk=None" in plain_text and "run_partvtk=False" in plain_text,
    }
    if not all(required.values()):
        raise PortableV57Error("plain-worker dependency contract is incomplete")
    return {
        "schema": "ds02.stage2.f2-copied-dependency-inventory-v57.v1",
        "status": "PASS_SOURCE_ONLY_COPIED_DEPENDENCY_INVENTORY",
        "bundle_root": str(root),
        "v4_wrapper": {"path": str(wrapper_path), "sha256": _sha(wrapper_path, max_bytes=1_000_000),
                       "lookup": "target/runtime/native/" + WORKER_NAME},
        "plain_worker": {"path": str(plain_path), "sha256": _sha(plain_path, max_bytes=1_000_000),
                         "parent": str(plain_path.parent), "lazy_load_graph": True},
        "four_overlay_sibling_aliases": alias_rows,
        "native_decoder": {"path": str(decoder_path), "sha256": _sha(decoder_path, max_bytes=1_000_000),
                           "mode_bits": decoder_mode, "required_executable": True},
        "libraries": {
            "top_level_python_imports": ["h5py", "numpy"],
            "abi_source": "pinned literal venv argv0; do not resolve symlink to system Python",
            "standalone_environment": False,
        },
        "partvtk": {
            "worker_partvtk_argument": None,
            "worker_run_partvtk": False,
            "partvtk_executable_opened_by_this_worker": False,
            "initial_csv_and_initial_stats": "precomputed evidence roles only",
            "scientific_partvtk_crosscheck": "not credited by this native label worker",
        },
        "required_contract_checks": required,
        "source_path_fallback": "FORBIDDEN",
        "payload_read": False,
        "qualification": dict(UNKNOWN),
    }


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Run V55/V54 with V57's non-recursive hooks."""
    global _ACTIVE_REQUEST
    _, request = V56._request_v55(request_path)
    marker = request.get("forward_v57")
    if not isinstance(marker, Mapping) or marker.get("schema") != V57_SCHEMA:
        raise PortableV57Error("V57 forward marker is missing")
    _ACTIVE_REQUEST = request

    def aliases(bindings: Mapping[str, Mapping[str, Any]], worker_dir: Path | str):
        records = _ORIGINAL_V55_ALIAS(bindings, worker_dir)
        V56._materialize_worker_compatibility(request, worker_dir)
        return records

    def imports(python: Path | str, records: Sequence[Mapping[str, Any]]):
        result = _ORIGINAL_V55_IMPORT(python, records)
        result["worker_path_smoke"] = V56._smoke_worker(python, request, records)
        result["plain_worker_lazy_import_graph"] = smoke_plain_worker_graph(
            python, request, records)
        return result

    previous_alias = V55._materialize_aliases_in_worker_parent
    previous_import = V55._import_four_modules
    V55._materialize_aliases_in_worker_parent = aliases
    V55._import_four_modules = imports
    try:
        return V55.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        V55._materialize_aliases_in_worker_parent = previous_alias
        V55._import_four_modules = previous_import
        # V57 calls the V55 boundary directly rather than V56.run.  Clear
        # V56's compatibility singleton as V56.run would, so a failed or
        # repeated parent attempt cannot inherit a prior copied target.
        if hasattr(V56, "_ACTIVE_REQUEST"):
            V56._ACTIVE_REQUEST = None
        if hasattr(V56, "_ACTIVE_COMPATIBILITY"):
            V56._ACTIVE_COMPATIBILITY = None
        _ACTIVE_REQUEST = None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-recovery")
    build.add_argument("--base-request", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--prior-parent-receipt", type=Path, required=True)
    build.add_argument("--prior-returned-report", type=Path, required=True)
    build.add_argument("--graph-report", type=Path)
    build.add_argument("--reused-bundle-root", type=Path)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--evaluator-proof", type=Path)
    run_parser.add_argument("--max-wall-seconds", type=float)
    inv = sub.add_parser("inventory")
    inv.add_argument("--bundle-root", type=Path, required=True)
    inv.add_argument("--wrapper", type=Path, required=True)
    inv.add_argument("--plain-worker", type=Path, required=True)
    inv.add_argument("--decoder", type=Path, required=True)
    inv.add_argument("--alias", action="append", required=True,
                     help="role=absolute-path; repeat for raw_converter,v14_operator,v15_operator,v16_operator")
    inv.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-recovery":
            result = build_recovery(
                base_request=args.base_request, output_request=args.output_request,
                target_root=args.target_root, output_root=args.output_root,
                prior_parent_receipt=args.prior_parent_receipt,
                prior_returned_report=args.prior_returned_report,
                graph_report=args.graph_report,
                reused_bundle_root=args.reused_bundle_root)
        elif args.command == "inventory":
            aliases = {}
            for value in args.alias:
                role, separator, path = value.partition("=")
                if not separator:
                    raise PortableV57Error("alias must be role=absolute-path")
                aliases[role] = path
            result = inventory_code_graph(
                wrapper=args.wrapper, plain_worker=args.plain_worker,
                aliases=aliases, decoder=args.decoder, bundle_root=args.bundle_root)
            _write_new(args.output, result)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV57Error, V56.PortableV56Error, V55.PortableV55Error,
            V55.V54.PortableV54Error, V55.V54.V53.PortableV53Error,
            V55.V54.V53.V52.PortableV52Error,
            V55.V54.V53.V52.V51.PortableV51Error,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v57: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
