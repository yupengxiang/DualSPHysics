#!/usr/bin/env python3
"""ROOT241 guarded metadata runner for the all-336 effective-condition index.

V28 turns the V27 index into a real parent-consumable metadata request.  The
request contains one exact source closure for the CURRENT catalog, V25/V26/
V27 lineage, every case's owner/XML/conversion/receipt metadata, and the
declared trajectory placeholders.  It also binds fresh ROOT241 output,
product, supervisor and receipt paths plus the existing shared-ledger
resource contract.

The ``run`` phase is intentionally metadata-only: after the outer parent
reservation it validates the declared source closure (hashing bounded
metadata files and checking stat before/after), runs the existing V26
bounded metadata builder, then derives the V27 physical-union index.  H5,
BI4, raw arrays, JSONL and solver output are never opened.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V26_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_effective_conditions_v26.py"
V27_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_effective_conditions_v27.py"
V26_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v26"
V27_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v27"
REQUEST_SCHEMA = "ds02.stage2.effective-condition-metadata-parent-request.v28"
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_METADATA_HASH_BYTES = 8 * 1024 * 1024
PAYLOAD_ROLES = frozenset({"trajectory"})
ROLE_ORDER = (
    "manifest", "xmf", "conversion_report", "generated_xml", "owner_metadata",
    "gencase_receipt", "solver_receipt", "trajectory",
)


class EffectiveConditionV28Error(ValueError):
    """Invalid bounded metadata closure or unsafe ROOT241 request."""


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EffectiveConditionV28Error(f"cannot load runtime source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items()
                                     if key != "sha256"}).encode()).hexdigest()


def _sha(path: Path, *, maximum: int | None = None) -> str:
    if path.is_symlink() or not path.is_file():
        raise EffectiveConditionV28Error(f"expected regular file: {path}")
    if maximum is not None and path.stat().st_size > maximum:
        raise EffectiveConditionV28Error(f"bounded hash limit exceeded: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.exists():
        return {"exists": False}
    value = path.stat()
    return {
        "exists": True,
        "kind": "file" if path.is_file() else "directory",
        "bytes": int(value.st_size) if path.is_file() else None,
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _read_json(path: Path, maximum: int = MAX_INDEX_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise EffectiveConditionV28Error(f"invalid bounded JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EffectiveConditionV28Error(f"cannot read metadata JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise EffectiveConditionV28Error(f"metadata object required: {path}")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise EffectiveConditionV28Error(f"refusing to overwrite ROOT241 file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                    encoding="utf-8")


def _declared_sha(record: Mapping[str, Any]) -> str | None:
    for key in ("declared_sha256", "sha256", "recomputed_sha256", "file_sha256"):
        value = record.get(key)
        if isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value):
            return value
    return None


def _source_record(record: Mapping[str, Any] | None, *, role: str,
                   case_index: int) -> dict[str, Any] | None:
    if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
        return None
    raw_path = str(record["path"])
    if not raw_path:
        return {
            "logical_role": f"CURRENT_case_{case_index:03d}_{role}",
            "role": role, "case_index": case_index,
            "status": "DECLARATION_MISSING", "content_policy": "NO_PATH",
        }
    source = Path(raw_path).expanduser()
    declared_stat = record.get("stat") if isinstance(record.get("stat"), Mapping) else {"exists": False}
    declared_sha = _declared_sha(record)
    payload = role in PAYLOAD_ROLES or bool(record.get("payload_or_provenance"))
    return {
        "logical_role": f"CURRENT_case_{case_index:03d}_{role}",
        "role": role, "case_index": case_index, "path": str(source),
        "expected_sha256": declared_sha,
        "expected_stat": dict(declared_stat),
        "status": "DECLARED_DEFERRED_PAYLOAD" if payload else "DECLARED_METADATA_SOURCE",
        "content_policy": "STAT_ONLY_DEFERRED_PAYLOAD" if payload else "HASH_AFTER_RESERVATION_BOUNDED",
        "source_content_read_by_builder": False,
        "owner_sha_is_provenance_only": role == "owner_metadata",
    }


def _merge_source(table: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
    path = item.get("path")
    if not isinstance(path, str):
        # Keep missing declarations by logical role; they are explicit gaps,
        # not silently discarded inputs.
        table[item["logical_role"]] = item
        return
    previous = table.get(path)
    if previous is None:
        table[path] = item
        return
    if previous.get("expected_sha256") != item.get("expected_sha256"):
        raise EffectiveConditionV28Error(
            f"conflicting declared SHA for source path {path}: "
            f"{previous.get('expected_sha256')} vs {item.get('expected_sha256')}")
    if previous.get("expected_stat") != item.get("expected_stat"):
        raise EffectiveConditionV28Error(f"conflicting declared stat for source path {path}")
    roles = list(previous.setdefault("logical_roles", [previous["logical_role"]]))
    roles.append(item["logical_role"])
    previous["logical_roles"] = sorted(set(roles))
    previous["role_count"] = len(previous["logical_roles"])


def _load_v26_index(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if value.get("schema") != V26_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise EffectiveConditionV28Error("V26 index schema/SHA mismatch")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise EffectiveConditionV28Error("V26 index must contain 336 cases")
    return value


def _collect_source_closure(v26_index: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    index = _load_v26_index(v26_index)
    sources: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {role: 0 for role in ROLE_ORDER}
    for compact in index["cases"]:
        case_index = int(compact["current_index"])
        case_path = Path(str(compact["case_path"])).expanduser().resolve()
        case = _read_json(case_path, maximum=256 * 1024)
        if case.get("schema") != "ds02.stage2.effective-condition-case.v26":
            raise EffectiveConditionV28Error(f"unexpected V26 case detail schema: {case_path}")
        if case.get("sha256") != compact.get("case_sha256") or case.get("sha256") != canonical_sha(case):
            raise EffectiveConditionV28Error(f"V26 case detail SHA mismatch: {case_path}")
        case_record = {
            "logical_role": f"V26_case_detail_{case_index:03d}",
            "role": "v26_case_detail", "case_index": case_index,
            "path": str(case_path), "expected_sha256": _sha(case_path, maximum=256 * 1024),
            "expected_stat": _stat(case_path), "status": "DECLARED_METADATA_SOURCE",
            "content_policy": "HASH_AFTER_RESERVATION_BOUNDED",
            "source_content_read_by_builder": True,
        }
        _merge_source(sources, case_record)
        for role in ROLE_ORDER:
            item = _source_record(case.get("source_bindings", {}).get(role), role=role,
                                  case_index=case_index)
            if item is None:
                continue
            counts[role] += 1
            _merge_source(sources, item)

    _merge_source(sources, {
        "logical_role": "V26_effective_condition_index", "role": "v26_index",
        "path": str(v26_index), "expected_sha256": _sha(v26_index, maximum=MAX_INDEX_BYTES),
        "expected_stat": _stat(v26_index), "status": "DECLARED_METADATA_SOURCE",
        "content_policy": "HASH_AFTER_RESERVATION_BOUNDED",
        "source_content_read_by_builder": True,
    })

    current_catalog = index.get("current_catalog", {}).get("path")
    if isinstance(current_catalog, str):
        item = {
            "logical_role": "CURRENT336_catalog", "role": "current_catalog",
            "path": str(Path(current_catalog).expanduser().resolve()),
            "expected_sha256": index.get("current_catalog", {}).get("observed_file_sha256"),
            "expected_stat": _stat(Path(current_catalog).expanduser()),
            "status": "DECLARED_METADATA_SOURCE", "content_policy": "HASH_AFTER_RESERVATION_BOUNDED",
            "source_content_read_by_builder": False,
        }
        _merge_source(sources, item)
    v25_path = index.get("versioned_from", {}).get("v25_index_path")
    if isinstance(v25_path, str):
        path = Path(v25_path).expanduser()
        item = {
            "logical_role": "V25_source_index", "role": "v25_index",
            "path": str(path), "expected_sha256": index.get("versioned_from", {}).get("v25_index_sha256"),
            "expected_stat": _stat(path), "status": "DECLARED_METADATA_SOURCE",
            "content_policy": "HASH_AFTER_RESERVATION_BOUNDED",
            "expected_sha_kind": "canonical_json",
            "source_content_read_by_builder": False,
        }
        _merge_source(sources, item)
    for logical_role, path, role in (
        ("V26_builder_source", V26_SCRIPT, "runtime_source"),
        ("V27_builder_source", V27_SCRIPT, "runtime_source"),
        ("V28_builder_source", SCRIPT, "runtime_source"),
    ):
        _merge_source(sources, {
            "logical_role": logical_role, "role": role, "path": str(path),
            "expected_sha256": _sha(path), "expected_stat": _stat(path),
            "status": "DECLARED_RUNTIME_SOURCE", "content_policy": "HASH_AFTER_RESERVATION_BOUNDED",
            "source_content_read_by_builder": True,
        })
    ordered = sorted(sources.values(), key=lambda item: (str(item.get("path", "")), item["logical_role"]))
    return ordered, counts


def _fresh_namespace(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise EffectiveConditionV28Error(f"ROOT241 output is not a directory namespace: {path}")
    if path.exists() and any(path.iterdir()):
        raise EffectiveConditionV28Error(f"ROOT241 output namespace is not fresh: {path}")


def build_request(*, v26_index: Path | str, request_dir: Path | str,
                  output_root: Path | str, ledger_path: Path | str,
                  attempt_id: str = "ds02-effective-condition-all336-v28-root241-001",
                  external_filesystem: Path | str = "/var/tmp/ds02-stage2",
                  external_reservation_bytes: int = 256 * 1024 * 1024,
                  home_receipt_bytes: int = 16 * 1024 * 1024,
                  external_min_free_bytes: int = 20 * 1024**3,
                  home_free_floor_bytes: int = 500 * 1024**3,
                  allow_missing_parent: bool = False) -> dict[str, Any]:
    source_index = Path(v26_index).expanduser().resolve()
    request_root = Path(request_dir).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    _fresh_namespace(output)
    if request_root.exists() and any(request_root.iterdir()):
        raise EffectiveConditionV28Error(f"ROOT241 request namespace is not fresh: {request_root}")
    source_index_value = _load_v26_index(source_index)
    sources, counts = _collect_source_closure(source_index)
    request_root.mkdir(parents=True, exist_ok=True)
    metadata = request_root / "root241-source-closure-v28.json"
    request_path = request_root / "effective-condition-metadata-parent-request-v28.json"
    output_products = output / "products"
    output_v26 = output / "v26-metadata"
    output_v27 = output / "v27-physical-union"
    report = output / "root241-metadata-report-v28.json"
    receipt = output / "execution-receipt.json"
    supervisor = output / "supervisor"
    ledger = Path(ledger_path).expanduser().resolve()
    external_fs = Path(external_filesystem).expanduser().resolve()
    current_catalog_path = Path(str(source_index_value.get("current_catalog", {}).get("path", ""))).expanduser().resolve()
    v25_index_path = Path(str(source_index_value.get("versioned_from", {}).get("v25_index_path", ""))).expanduser().resolve()
    runtime = {
        "python": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        "script": str(SCRIPT), "v26_script": str(V26_SCRIPT), "v27_script": str(V27_SCRIPT),
        "stage2_root": str(source_index.parent.parent.parent),
        "current_catalog": str(current_catalog_path),
        "v25_index": str(v25_index_path),
    }
    closure = {
        "schema": "ds02.stage2.effective-condition-source-closure.v28",
        "attempt_id": attempt_id, "source_index": str(source_index),
        "source_index_sha256": _sha(source_index, maximum=MAX_INDEX_BYTES),
        "roles": sources, "role_counts": counts,
        "payload_policy": {"trajectory": "STAT_ONLY_DECLARED_SHA; NEVER_OPEN_CONTENT",
                           "hdf5": "FORBID", "bi4": "FORBID", "raw_arrays": "FORBID",
                           "jsonl": "FORBID", "solver_output": "FORBID"},
        "source_content_read_by_builder": False,
        "bounded_metadata_content_read_by_builder": True,
        "payload_content_read_by_builder": False,
    }
    closure["sha256"] = canonical_sha(closure)
    _write_new(metadata, closure)
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_ROOT241_METADATA_PARENT_GUARD",
        "request_id": attempt_id, "mode": "ALL336_V27_METADATA_ONLY",
        "execution": {
            **runtime,
            "command_template": [runtime["python"], "-B", "-I", "{copied_v28_entrypoint}", "run",
                                  "--request", "{request}", "--parent-pid", "{parent_pid}"],
            "cpu_threads": 1, "max_wall_seconds": 900, "memory_max_bytes": 512 * 1024**2,
            "parent_guard_required": True, "model_invoked": False, "cfd_invoked": False,
        },
        "runtime_closure": {
            "literal_python": runtime["python"],
            "roles": [
                {"role": "v28_entrypoint", "source_path": str(SCRIPT),
                 "target_relative_path": f"runtime/{SCRIPT.name}",
                 "source_sha256": _sha(SCRIPT), "source_stat": _stat(SCRIPT)},
                {"role": "v26_builder", "source_path": str(V26_SCRIPT),
                 "target_relative_path": f"runtime/{V26_SCRIPT.name}",
                 "source_sha256": _sha(V26_SCRIPT), "source_stat": _stat(V26_SCRIPT)},
                {"role": "v27_builder", "source_path": str(V27_SCRIPT),
                 "target_relative_path": f"runtime/{V27_SCRIPT.name}",
                 "source_sha256": _sha(V27_SCRIPT), "source_stat": _stat(V27_SCRIPT)},
            ],
            "original_worktree_fallback": "REJECT",
        },
        "parent_resource_binding": {
            "ledger_path": str(ledger), "same_parent_ledger": True,
            "ledger_reset": False, "attempt_id": attempt_id,
            "reservation_id": f"{attempt_id}::reservation",
            "charge_id": f"{attempt_id}::charge",
            "allow_missing_parent": bool(allow_missing_parent),
            "storage_policy": "home_free_floor", "cpu_threads": 1,
            "max_wall_seconds": 900,
        },
        "storage_scope": {
            "external_filesystem": str(external_fs),
            "external_output_root": str(output),
            "supervisor_output_root": str(supervisor),
            "home_receipt_path": str(receipt),
            "accessible_index_path": str(metadata),
            "parent_attempt_id": attempt_id,
            "source_copy_bytes": 0,
            "external_reservation_bytes": int(external_reservation_bytes),
            "home_receipt_bytes": int(home_receipt_bytes),
            "external_min_free_bytes": int(external_min_free_bytes),
            "home_free_floor_bytes": int(home_free_floor_bytes),
        },
        "source_closure": {
            "path": str(metadata), "sha256": closure["sha256"],
            "role_count": len(sources), "case_count": 336,
            "owner_xml_receipt_conversion_current_bound": True,
            "trajectory_content_deferred": True,
            "original_path_fallback": "REJECT",
            "bounded_metadata_content_read_by_worker": True,
            "payload_content_read_by_worker": False,
        },
        "outputs": {
            "root": str(output), "products": str(output_products),
            "v26_metadata": str(output_v26), "v27_physical_union": str(output_v27),
            "metadata_report": str(report), "execution_receipt": str(receipt),
            "supervisor_root": str(supervisor), "fresh_attempt_namespace": True,
        },
        "source_inputs": {
            "v26_index": {"path": str(source_index), "sha256": closure["source_index_sha256"]},
            "closure_manifest": {"path": str(metadata), "sha256": closure["sha256"]},
        },
        "read_policy": closure["payload_policy"] | {"original_path_fallback": "REJECT"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "model_invoked": False, "cfd_invoked": False,
    }
    request["execution"]["argv"] = list(request["execution"]["command_template"])
    request["sha256"] = canonical_sha(request)
    _write_new(request_path, request)
    return {"request": str(request_path), "request_sha256": request["sha256"],
            "closure": str(metadata), "closure_sha256": closure["sha256"],
            "role_count": len(sources), "role_counts": counts, "case_count": 336,
            "output_root": str(output), "qualification": request["qualification"]}


def _validate_stat(path: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    current = _stat(path)
    if expected.get("exists") is False:
        if current.get("exists"):
            raise EffectiveConditionV28Error(f"source appeared after declaration: {path}")
        return current
    for key in ("exists", "kind", "bytes", "mode_bits", "mtime_ns"):
        if current.get(key) != expected.get(key):
            raise EffectiveConditionV28Error(
                f"source stat changed for {path}: {key} {current.get(key)} != {expected.get(key)}")
    return current


def _validate_closure(closure: Mapping[str, Any]) -> dict[str, Any]:
    before: list[dict[str, Any]] = []
    for item in closure.get("roles", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            continue
        path = Path(str(item["path"])).expanduser()
        expected = item.get("expected_stat") if isinstance(item.get("expected_stat"), Mapping) else {}
        current = _validate_stat(path, expected)
        observed_sha = None
        if (item.get("content_policy") == "HASH_AFTER_RESERVATION_BOUNDED" and
                current.get("exists") and current.get("kind") == "file"):
            if int(current.get("bytes") or 0) <= MAX_METADATA_HASH_BYTES:
                if item.get("expected_sha_kind") == "canonical_json":
                    observed_sha = canonical_sha(_read_json(path, maximum=MAX_METADATA_HASH_BYTES))
                else:
                    observed_sha = _sha(path, maximum=MAX_METADATA_HASH_BYTES)
                expected_sha = item.get("expected_sha256")
                if isinstance(expected_sha, str) and observed_sha != expected_sha:
                    raise EffectiveConditionV28Error(f"source SHA changed after reservation: {path}")
        before.append({"path": str(path), "stat": current, "sha256": observed_sha,
                       "content_policy": item.get("content_policy")})
    return {"checked_roles": len(before), "entries": before}


def _validate_runtime_closure(request: Mapping[str, Any]) -> dict[str, Any]:
    runtime = request.get("runtime_closure")
    if not isinstance(runtime, Mapping) or not isinstance(runtime.get("roles"), list):
        raise EffectiveConditionV28Error("runtime_closure roles are required")
    checked: list[dict[str, Any]] = []
    for item in runtime["roles"]:
        if not isinstance(item, Mapping):
            raise EffectiveConditionV28Error("runtime closure role is not an object")
        target_relative = Path(str(item.get("target_relative_path", "")))
        if (target_relative.is_absolute() or len(target_relative.parts) != 2 or
                target_relative.parts[0] != "runtime" or ".." in target_relative.parts):
            raise EffectiveConditionV28Error("runtime target path is not a copied runtime sibling")
        target = SCRIPT.parent / target_relative.name
        expected_sha = item.get("source_sha256")
        if not target.is_file() or target.is_symlink():
            raise EffectiveConditionV28Error(f"copied runtime role is missing: {target}")
        observed_sha = _sha(target, maximum=MAX_METADATA_HASH_BYTES)
        if observed_sha != expected_sha:
            raise EffectiveConditionV28Error(f"copied runtime SHA differs: {target}")
        checked.append({"role": item.get("role"), "target": str(target), "sha256": observed_sha})
    return {"checked_roles": len(checked), "roles": checked}


def _load_request(path: Path) -> dict[str, Any]:
    request = _read_json(path, maximum=2 * MAX_INDEX_BYTES)
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise EffectiveConditionV28Error("ROOT241 request schema/SHA mismatch")
    return request


def run(*, request_path: Path | str, parent_pid: int) -> dict[str, Any]:
    request = _load_request(Path(request_path).expanduser().resolve())
    if parent_pid > 0:
        try:
            os.kill(parent_pid, 0)
        except OSError as error:
            raise EffectiveConditionV28Error(f"parent is not alive: {parent_pid}") from error
    output = Path(request["outputs"]["root"]).expanduser().resolve()
    _fresh_namespace(output)
    runtime_attestation = _validate_runtime_closure(request)
    closure_path = Path(request["source_closure"]["path"]).expanduser().resolve()
    closure = _read_json(closure_path, maximum=MAX_INDEX_BYTES)
    if closure.get("sha256") != request["source_closure"]["sha256"]:
        raise EffectiveConditionV28Error("source closure SHA differs from request")
    started = time.monotonic()
    pre = _validate_closure(closure)
    runtime_roles = {
        str(item["role"]): Path(str(item["target_relative_path"])).name
        for item in request["runtime_closure"]["roles"]
        if isinstance(item, Mapping)
    }
    v26_script = SCRIPT.parent / runtime_roles["v26_builder"]
    v27_script = SCRIPT.parent / runtime_roles["v27_builder"]
    v26 = _load(v26_script, "effective_conditions_v26_root241_runtime")
    v27 = _load(v27_script, "effective_conditions_v27_root241_runtime")
    v26_output = output / "v26-metadata"
    v27_output = output / "v27-physical-union"
    v26_result = v26.build(
        stage2_root=Path(request["execution"]["stage2_root"]),
        output_dir=v26_output,
        current_catalog=Path(request["execution"]["current_catalog"]),
        v25_index=Path(request["execution"]["v25_index"]),
    )
    v27_result = v27.build_from_index(v26_index=Path(v26_result["index"]), output_dir=v27_output,
                                      request_id=f"{request['request_id']}::v27")
    report = {
        "schema": "ds02.stage2.effective-condition-metadata-report.v28",
        "request_id": request["request_id"], "status": "COMPLETED_METADATA_ONLY",
        "runtime_closure": runtime_attestation,
        "source_pre": pre, "source_post": _validate_closure(closure),
        "v26": v26_result, "v27": v27_result,
        "elapsed_wall_seconds": time.monotonic() - started,
        "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False,
        "jsonl_opened": False, "solver_output_opened": False,
        "model_invoked": False, "cfd_invoked": False,
        "bounded_metadata_content_read": True, "payload_content_read": False,
    }
    report_path = Path(request["outputs"]["metadata_report"])
    _write_new(report_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v26-index", type=Path, required=True)
    build.add_argument("--request-dir", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--ledger-path", type=Path, required=True)
    build.add_argument("--attempt-id", default="ds02-effective-condition-all336-v28-root241-001")
    build.add_argument("--external-filesystem", type=Path, default=Path("/var/tmp/ds02-stage2"))
    build.add_argument("--external-reservation-bytes", type=int, default=256 * 1024 * 1024)
    build.add_argument("--home-receipt-bytes", type=int, default=16 * 1024 * 1024)
    build.add_argument("--external-min-free-bytes", type=int, default=20 * 1024**3)
    build.add_argument("--home-free-floor-bytes", type=int, default=500 * 1024**3)
    build.add_argument("--allow-missing-parent", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-request":
            result = build_request(v26_index=args.v26_index, request_dir=args.request_dir,
                                   output_root=args.output_root, ledger_path=args.ledger_path,
                                   attempt_id=args.attempt_id, external_filesystem=args.external_filesystem,
                                   external_reservation_bytes=args.external_reservation_bytes,
                                   home_receipt_bytes=args.home_receipt_bytes,
                                   external_min_free_bytes=args.external_min_free_bytes,
                                   home_free_floor_bytes=args.home_free_floor_bytes,
                                   allow_missing_parent=args.allow_missing_parent)
        else:
            result = run(request_path=args.request, parent_pid=args.parent_pid)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (EffectiveConditionV28Error, OSError, ValueError, KeyError) as error:
        print(f"effective conditions v28: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
