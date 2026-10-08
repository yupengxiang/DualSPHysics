#!/usr/bin/env python3
"""Normalize the V46 cold parent to absolute, SHA-bound metadata paths.

V46's executor request inherited one relative ``v5_overlay_template.path``.
When the copied V45 process loaded its request from the relocated worktree,
the current working directory was already ``lagrangian-fluid-lab`` and the
relative value became a doubled path.  V47 creates two fresh immutable JSON
objects:

* a V45 executor request whose overlay path is the actual absolute source
  path, and
* a V46 parent request that points at that new executor request and fresh
  target/output/receipt namespaces.

Only path fields, fresh namespaces, and parent attempt identifiers change.
The overlay's canonical/content SHA, every source/runtime SHA/stat, and every
``target_relative_path`` remain bound.  This builder reads only bounded JSON
and source metadata.  It never reads H5, BI4, raw frames, or typed/label
payloads, and it does not own a ledger or reservation.
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
EXECUTOR_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-parent-v47-path-normalization.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class ParentV47Error(RuntimeError):
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


def _load_json(path: Path | str, role: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise ParentV47Error(f"{role} is not a regular file: {target}")
    if target.stat().st_size > max_bytes:
        raise ParentV47Error(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ParentV47Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ParentV47Error(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise ParentV47Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise ParentV47Error(f"{role} must be a lowercase SHA-256")
    return value


def _stat_record(path: Path) -> dict[str, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ParentV47Error(f"source is not a regular file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _repo_root_from_executor(value: Mapping[str, Any]) -> Path:
    # V46 stores ``executor_script`` at the parent level, while the bound V45
    # executor request only records the literal script in execution.command.
    # Resolve the latter from its own request, never from the process cwd.
    candidates: list[Path] = []
    binding = value.get("executor_script")
    if isinstance(binding, Mapping) and isinstance(binding.get("path"), str):
        candidates.append(Path(str(binding["path"])).expanduser())
    execution = value.get("execution")
    if isinstance(execution, Mapping):
        command = execution.get("command")
        if isinstance(command, list):
            candidates.extend(Path(str(item)).expanduser() for item in command
                              if isinstance(item, str) and item.endswith(".py"))
    runtime_sources = value.get("runtime_sources")
    if isinstance(runtime_sources, list):
        for row in runtime_sources:
            if isinstance(row, Mapping) and isinstance(row.get("path"), str):
                candidate = Path(str(row["path"])).expanduser()
                if candidate.suffix == ".py":
                    candidates.append(candidate)
    script = next((candidate for candidate in candidates if candidate.is_file()), None)
    if script is None:
        raise ParentV47Error("bound executor script is missing")
    # .../DualSPHysics/lagrangian-fluid-lab/scripts/<executor>.py
    return script.parent.parent.parent


def _resolve_bound_path(raw: Any, *, repo_root: Path, role: str) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw:
        raise ParentV47Error(f"{role} path is missing")
    original = raw
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    if candidate.is_symlink() or not candidate.is_file():
        raise ParentV47Error(f"{role} source is missing: {candidate}")
    return candidate, original


def _validate_overlay(overlay_path: Path, binding: Mapping[str, Any]) -> dict[str, Any]:
    declared_sha = _require_sha(binding.get("sha256"), "v5 overlay SHA")
    observed_sha = sha256_file(overlay_path)
    if observed_sha != declared_sha:
        raise ParentV47Error("v5 overlay content SHA differs from immutable binding")
    overlay = _load_json(overlay_path, "v5 overlay")
    if overlay.get("sha256") != canonical_sha(overlay):
        raise ParentV47Error("v5 overlay canonical SHA differs")
    canonical_declared = binding.get("canonical_sha256")
    if canonical_declared is not None and overlay.get("sha256") != canonical_declared:
        raise ParentV47Error("v5 overlay canonical binding differs")
    return overlay


def _target_relative_paths(value: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for section in ("source_entries", "runtime_sources"):
        entries = value.get(section, [])
        if not isinstance(entries, list):
            continue
        rows.extend(str(item.get("target_relative_path"))
                    for item in entries if isinstance(item, Mapping)
                    and "target_relative_path" in item)
    return rows


def _normalize_executor(*, base_parent: Mapping[str, Any], output: Path,
                        target_root: Path, output_root: Path) -> dict[str, Any]:
    binding = base_parent.get("executor_request")
    if not isinstance(binding, Mapping) or not isinstance(binding.get("path"), str):
        raise ParentV47Error("V46 executor_request binding is missing")
    old_path = Path(str(binding["path"])).expanduser()
    old_physical_sha = _require_sha(binding.get("sha256"), "V46 executor request SHA")
    if not old_path.is_file() or sha256_file(old_path) != old_physical_sha:
        raise ParentV47Error("V46 executor request physical SHA differs")
    old_executor = _load_json(old_path, "V45 executor request")
    if old_executor.get("schema") != EXECUTOR_SCHEMA:
        raise ParentV47Error("bound executor is not the V45/V34 request schema")
    if old_executor.get("sha256") != canonical_sha(old_executor):
        raise ParentV47Error("V45 executor canonical SHA differs")
    overlay_binding = old_executor.get("v5_overlay_template")
    if not isinstance(overlay_binding, Mapping):
        raise ParentV47Error("V45 v5_overlay_template binding is missing")
    repo_root = _repo_root_from_executor(old_executor)
    overlay_path, old_overlay_path = _resolve_bound_path(
        overlay_binding.get("path"), repo_root=repo_root, role="v5 overlay")
    _validate_overlay(overlay_path, overlay_binding)
    if target_root.exists() or output_root.exists() or target_root == output_root:
        raise ParentV47Error("V47 target/output roots must be fresh and distinct")
    value = copy.deepcopy(old_executor)
    before_relative = _target_relative_paths(value)
    value["v5_overlay_template"]["path"] = str(overlay_path)
    value["fresh_roots"] = {"target_root": str(target_root), "output_root": str(output_root)}
    value["request_id"] = str(value.get("request_id", "f2-s1-v45")) + "-v47"
    value["v47_path_normalization"] = {
        "schema": FORWARD_SCHEMA,
        "changed_fields": ["v5_overlay_template.path", "fresh_roots.target_root",
                           "fresh_roots.output_root", "request_id"],
        "old_overlay_path": old_overlay_path,
        "absolute_overlay_path": str(overlay_path),
        "overlay_sha256": overlay_binding["sha256"],
        "overlay_canonical_sha256": overlay_binding.get("canonical_sha256"),
        "source_stat_policy": "immutable source SHA verified; no payload stat/hash substitution",
        "target_relative_paths_unchanged": True,
        "payload_content_read": False,
        "qualification": dict(UNKNOWN),
    }
    if _target_relative_paths(value) != before_relative:
        raise ParentV47Error("V47 changed a target_relative_path")
    value["sha256"] = canonical_sha(value)
    _write_new(output, value)
    return {
        "value": value,
        "path": str(output),
        "physical_sha256": sha256_file(output),
        "canonical_sha256": value["sha256"],
        "old_path": str(old_path),
        "old_physical_sha256": old_physical_sha,
        "old_canonical_sha256": old_executor["sha256"],
        "overlay_path": str(overlay_path),
        "overlay_sha256": overlay_binding["sha256"],
    }


def _replace_exact(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_exact(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_exact(item, old, new) for item in value]
    if isinstance(value, str) and value == old:
        return new
    return value


def _refresh_parent_binding(parent: dict[str, Any], *, old_executor_path: str,
                            new_executor_path: Path, new_executor_physical_sha: str,
                            new_executor_canonical_sha: str, attempt_id: str,
                            home_receipt_path: Path, supervisor_output_root: Path) -> None:
    value = _replace_exact(parent, old_executor_path, str(new_executor_path))
    parent.clear()
    parent.update(value)
    top = parent.get("executor_request")
    if not isinstance(top, dict):
        raise ParentV47Error("parent executor_request disappeared during rebind")
    top["path"] = str(new_executor_path)
    top["sha256"] = new_executor_physical_sha
    for row in parent.get("static_bindings", []):
        if not isinstance(row, dict) or row.get("role") != "executor_v34_request":
            continue
        row.update({"path": str(new_executor_path), "sha256": new_executor_physical_sha,
                    **_stat_record(new_executor_path)})
    nested = parent.get("v41_forward", {}).get("executor_request")
    if isinstance(nested, dict):
        nested["path"] = str(new_executor_path)
        nested["sha256"] = new_executor_canonical_sha
    parent["attempt_id"] = attempt_id + "::f2-v47-parent"
    parent_resource = dict(parent.get("parent_resource_binding", {}))
    parent_resource.update({
        "attempt_id": attempt_id,
        "reservation_id": attempt_id + "::f2-v47-parent-reservation",
        "charge_id": attempt_id + "::f2-v47-parent-charge",
        "allow_missing_parent": True,
    })
    parent["parent_resource_binding"] = parent_resource
    accounting = dict(parent.get("accounting", {}))
    accounting.update({
        "attempt_id": attempt_id,
        "reservation_id": parent_resource["reservation_id"],
        "charge_id": parent_resource["charge_id"],
        "allow_missing_parent": True,
    })
    parent["accounting"] = accounting
    storage = dict(parent.get("storage_scope", {}))
    storage["home_receipt_path"] = str(home_receipt_path)
    storage["supervisor_output_root"] = str(supervisor_output_root)
    parent["storage_scope"] = storage
    execution = dict(parent.get("execution", {}))
    execution["trace_path"] = str(supervisor_output_root / "os-trace-v34")
    parent["execution"] = execution


def forward_parent(*, base_parent: Path | str, executor_output: Path | str,
                   parent_output: Path | str, target_root: Path | str,
                   output_root: Path | str, parent_attempt_id: str,
                   home_receipt_path: Path | str,
                   supervisor_output_root: Path | str) -> dict[str, Any]:
    base_path = Path(base_parent).expanduser()
    base = _load_json(base_path, "V46 parent request")
    if base.get("schema") != SCHEMA or base.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentV47Error("base parent is not a V3 ready request")
    if base.get("sha256") != canonical_sha(base):
        raise ParentV47Error("base V46 parent canonical SHA differs")
    if base.get("qualification") != UNKNOWN or base.get("model_invoked") is not False:
        raise ParentV47Error("base parent must remain DEVELOPMENT/UNKNOWN")
    executor_path = Path(executor_output).expanduser()
    parent_path = Path(parent_output).expanduser()
    target = Path(target_root).expanduser()
    products = Path(output_root).expanduser()
    receipt = Path(home_receipt_path).expanduser()
    supervisor = Path(supervisor_output_root).expanduser()
    for path, role in ((executor_path, "executor output"), (parent_path, "parent output")):
        if path.exists():
            raise ParentV47Error(f"refusing existing {role}: {path}")
    result = _normalize_executor(base_parent=base, output=executor_path,
                                 target_root=target, output_root=products)
    parent = copy.deepcopy(base)
    _refresh_parent_binding(
        parent, old_executor_path=result["old_path"], new_executor_path=executor_path,
        new_executor_physical_sha=result["physical_sha256"],
        new_executor_canonical_sha=result["canonical_sha256"], attempt_id=parent_attempt_id,
        home_receipt_path=receipt, supervisor_output_root=supervisor)
    parent["v47_forward"] = {
        "schema": FORWARD_SCHEMA,
        "base_parent_request": {"path": str(base_path), "sha256": sha256_file(base_path),
                                 "canonical_sha256": base["sha256"]},
        "old_executor_request": {"path": result["old_path"],
                                  "physical_sha256": result["old_physical_sha256"],
                                  "canonical_sha256": result["old_canonical_sha256"]},
        "new_executor_request": {"path": str(executor_path),
                                  "physical_sha256": result["physical_sha256"],
                                  "canonical_sha256": result["canonical_sha256"]},
        "overlay": {"path": result["overlay_path"], "sha256": result["overlay_sha256"]},
        "target_relative_paths_preserved": True,
        "source_hash_stat_contract": "preserved; only bound overlay path and fresh namespace metadata changed",
        "payload_content_read": False,
        "same_parent_ledger": True,
        "allow_missing_parent_scope": "fresh same-ledger attempt only; no fabricated ancestor",
        "qualification": dict(UNKNOWN),
    }
    # Add the builder as provenance if the base closure does not already carry
    # it.  The actual child executor remains V45; this is not an executable
    # wrapper substitution.
    roles = {row.get("role") for row in parent.get("static_bindings", []) if isinstance(row, Mapping)}
    if "parent_closure_builder_v47" not in roles:
        info = _stat_record(SCRIPT)
        parent.setdefault("static_bindings", []).append({
            "role": "parent_closure_builder_v47", "path": str(SCRIPT),
            **info, "sha256": sha256_file(SCRIPT), "immutable": True,
        })
    parent["status"] = "READY_FOR_PARENT_GUARD"
    parent["qualification"] = dict(UNKNOWN)
    parent["sha256"] = canonical_sha(parent)
    _write_new(parent_path, parent)
    return {
        "status": "READY_FOR_PARENT_GUARD_V47_PATH_NORMALIZATION",
        "executor_request": str(executor_path),
        "executor_physical_sha256": result["physical_sha256"],
        "executor_canonical_sha256": result["canonical_sha256"],
        "parent_request": str(parent_path),
        "parent_sha256": parent["sha256"],
        "static_binding_count": len(parent.get("static_bindings", [])),
        "overlay_path": result["overlay_path"],
        "raw_h5_bi4_result_payload_read": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-parent", type=Path, required=True)
    parser.add_argument("--executor-output", type=Path, required=True)
    parser.add_argument("--parent-output", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--parent-attempt-id", required=True)
    parser.add_argument("--home-receipt-path", type=Path, required=True)
    parser.add_argument("--supervisor-output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(forward_parent(
            base_parent=args.base_parent, executor_output=args.executor_output,
            parent_output=args.parent_output, target_root=args.target_root,
            output_root=args.output_root, parent_attempt_id=args.parent_attempt_id,
            home_receipt_path=args.home_receipt_path,
            supervisor_output_root=args.supervisor_output_root),
                         sort_keys=True, ensure_ascii=False))
    except (ParentV47Error, OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
