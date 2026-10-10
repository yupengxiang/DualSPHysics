#!/usr/bin/env python3
"""ROOT242 V14 metadata-only recursive source preflight.

V13 found the output-slot marker only after the copied worker had already
started.  The producer request also contains consumed administrative evidence
under ``v66_parent_binding``; those paths are actionable inputs and must be
sealed like any other report or receipt.  This module performs the complete
small-JSON graph walk before a parent copies anything, adds explicit roles for
all discovered actionable files, and then invokes the real V2 request
rewriter on every bounded request/contract document.

This is a source preflight.  It does not reserve resources, copy deferred
payloads, open HDF5/BI4/JSONL data, mutate a ledger, or launch a worker.
Deferred scientific files are represented by stat/declared-SHA roles and are
left for the parent after reservation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V13_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v13.py"
if not V13_SCRIPT.is_file():
    raise RuntimeError(f"V13 dependency is unavailable: {V13_SCRIPT}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V13 = _load(V13_SCRIPT, "ds02_root242_v13_for_v14_preflight")
V11 = V13.V11
V2 = V13.V2
V5_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v5.py"
V5 = _load(V5_SCRIPT, "ds02_root242_v5_for_v14_preflight")


REQUEST_SCHEMA = "ds02.stage2.f2-root242-v14-recursive-source-preflight.v1"
MAX_METADATA_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTS = 512
MAX_REFERENCES = 20_000
MAX_ROLE_COUNT = 2_000

PROVENANCE_KEYS = set(V2.PROVENANCE_KEYS)
DIRECTORY_KEYS = {
    "root", "target_root", "output_root", "runtime_root", "runtime_target_root",
    "fresh_output_root", "fresh_output_namespace", "fresh_proof_namespace",
    "proof_namespace",
}
DEFERRED_SUFFIXES = {
    ".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".vtk", ".vtu", ".pvtu",
    ".jsonl", ".csv", ".dat", ".bin", ".raw",
}
# Match the consumed V5 recursive runtime's graph boundary exactly.  A
# request/sidecar/current-manifest path is a nested metadata document; reports,
# receipts and terminal evidence are leaf inputs whose bytes are sealed but
# whose contents are not recursively interpreted by V5.
RECURSIVE_CONTEXTS = frozenset({
    "historical_provenance", "source_metadata_provenance", "source_metadata",
    "v12_forward", "semantic_sidecar", "source_request", "replaces_request",
    "frozen", "profile_rebind", "root194_sidecar",
})
LEAF_CONTEXTS = frozenset({
    "producer_nested_report", "producer_report", "worker_summary", "execution_receipt",
    "completed_receipt", "parent_report", "root_proof", "terminal_evidence", "terminal_delta",
})


class Root242V14Error(RuntimeError):
    pass


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root242V14Error(f"{role} must be an absolute path")
    return Path(value)


def _safe_relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise Root242V14Error(f"{role} target-relative path is missing")
    path = Path(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise Root242V14Error(f"{role} target path is unsafe: {value}")
    return path.as_posix()


def _pointer(parts: Sequence[str]) -> str:
    return "".join("/" + str(item).replace("~", "~0").replace("/", "~1")
                   for item in parts)


def _provenance_context(parts: Sequence[str]) -> bool:
    return any(str(part).lower() in PROVENANCE_KEYS for part in parts)


def _stat(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise Root242V14Error(f"source role must be a regular non-symlink file: {path}")
    value = path.stat()
    return {
        "bytes": int(value.st_size),
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _safe_stat(path: Path) -> dict[str, int] | None:
    try:
        return _stat(path)
    except (OSError, Root242V14Error):
        return None


def _sha_small(path: Path) -> str:
    stat = _stat(path)
    if stat["bytes"] > MAX_METADATA_BYTES:
        raise Root242V14Error(f"metadata hash limit exceeded: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    stat = _stat(path)
    if stat["bytes"] > MAX_METADATA_BYTES:
        raise Root242V14Error(f"{label} exceeds metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root242V14Error(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise Root242V14Error(f"{label} must be a JSON object")
    return value


def _follow_json(parts: Sequence[str], path: Path) -> bool:
    if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
        return False
    try:
        if path.stat().st_size > MAX_METADATA_BYTES:
            return False
    except OSError:
        return False
    lowered = {str(item).lower() for item in parts}
    if lowered & LEAF_CONTEXTS:
        return False
    return bool(lowered & RECURSIVE_CONTEXTS)


def _path_expected_hash(container: Any) -> str | None:
    if not isinstance(container, Mapping):
        return None
    for key in ("file_sha256", "source_sha256", "expected_sha256", "sha256"):
        value = container.get(key)
        if isinstance(value, str) and len(value) == 64 and set(value.lower()) <= set("0123456789abcdef"):
            return value
    return None


def _walk_paths(value: Any, parts: tuple[str, ...] = (),
                container: Any = None) -> Iterable[dict[str, Any]]:
    """Yield exactly the path nodes V2 treats as actionable plus directories."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            next_parts = parts + (key_text,)
            if isinstance(child, str) and child.startswith("/"):
                if key_text.lower() == "path":
                    synthetic_directory = (
                        not _provenance_context(parts)
                        and _directory_rebind_v14(parts, Path("/__v14_target__")) is not None
                    )
                    yield {
                        "pointer": _pointer(next_parts),
                        "path": child,
                        "actionable": not _provenance_context(parts),
                        "directory": synthetic_directory,
                        "expected_sha256": _path_expected_hash(value),
                    }
                elif key_text.lower() in DIRECTORY_KEYS:
                    # V2 only synthesizes directories outside provenance
                    # contexts.  Keep these records so the manifest proves
                    # which exact directory tuple was handled.
                    yield {
                        "pointer": _pointer(next_parts),
                        "path": child,
                        "actionable": not _provenance_context(parts),
                        "directory": True,
                        "expected_sha256": None,
                    }
            yield from _walk_paths(child, next_parts, value)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_paths(child, parts + (str(index),), value)


def _directory_rebind_v14(parts: tuple[str, ...], root: Path) -> Path | None:
    # V13's exact output marker is retained; all other directory behavior is
    # explicit generated-output rules are handled here, then the consumed V5
    # implementation is consulted.  These rules are target namespaces, not
    # provenance exemptions: a copied request can only point at the fresh
    # attempt root produced by one of them.
    if tuple(str(item) for item in parts) == ("v12_forward", "output_root_rebind_v14"):
        return root / "products"
    lower = [str(item).lower() for item in parts]
    if "decoder_scratch" in lower and "cleanup" in lower:
        return root / "runtime" / "scratch"
    if any(item in {"trace", "expected_artifacts", "home_receipt", "finalization_sidecar"}
           for item in lower):
        return root / "runtime" / "generated"
    if "filesystem_headroom" in lower:
        label = next((item for item in reversed(lower)
                      if item in {"home", "external", "nvme", "scratch"}), "policy")
        return root / "runtime" / "filesystem-headroom" / label
    if "source_bindings" in lower or "source_binding" in lower:
        label = re.sub(r"[^A-Za-z0-9_.-]+", "_", lower[-1])
        return root / "evidence" / "source-bindings" / (label or "binding")
    return V5._directory_rebind_v5(parts, root)


def _role_source(role: Mapping[str, Any]) -> str | None:
    value = role.get("source_path_provenance")
    return value if isinstance(value, str) and value.startswith("/") else None


def _make_discovered_role(path: Path, *, index: int, expected_sha256: str | None,
                          hash_content: bool) -> dict[str, Any]:
    observed = _safe_stat(path)
    if observed is None:
        raise Root242V14Error(f"discovered source is missing or not regular: {path}")
    suffix = path.suffix.lower()
    deferred = suffix in DEFERRED_SUFFIXES or observed["bytes"] > MAX_METADATA_BYTES
    source_sha = expected_sha256
    if not deferred and source_sha is None and hash_content:
        source_sha = _sha_small(path)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.name).strip("_") or "source"
    path_digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    return {
        "logical_role": f"v14_discovered_{index:04d}_{path_digest}",
        "classification": "deferred_payload" if deferred else "sealed_metadata_source",
        "source_path_provenance": str(path),
        "source_sha256": source_sha,
        "source_sha_basis": "DECLARED_ADJACENT_SHA" if expected_sha256 else (
            "V14_BOUNDED_METADATA_HASH" if not deferred and hash_content
            else "PARENT_AFTER_RESERVATION"),
        "source_stat_provenance": observed,
        "target_relative_path": f"evidence/v14-discovered/{path_digest}-{stem}",
        "deferred_content": deferred,
        "content_verification_phase": "PARENT_AFTER_RESERVATION" if deferred else "REBOUND_METADATA",
        "discovered_by": "ROOT242_V14_RECURSIVE_SOURCE_PREFLIGHT",
    }


def _role_maps(roles: Sequence[Mapping[str, Any]], root: Path) -> tuple[
        dict[str, tuple[Mapping[str, Any], Path]], dict[str, Mapping[str, Any]]]:
    by_source: dict[str, tuple[Mapping[str, Any], Path]] = {}
    by_role: dict[str, Mapping[str, Any]] = {}
    targets: set[str] = set()
    for role in roles:
        if not isinstance(role, Mapping):
            raise Root242V14Error("source role table contains a non-object")
        source = _role_source(role)
        logical = role.get("logical_role")
        target_rel = _safe_relative(role.get("target_relative_path"), f"{logical}.target")
        if source is None or not isinstance(logical, str) or not logical:
            raise Root242V14Error("source role lacks logical/source provenance")
        if logical in by_role or target_rel in targets:
            raise Root242V14Error(f"duplicate source role/target: {logical}/{target_rel}")
        by_role[logical] = role
        targets.add(target_rel)
        by_source.setdefault(os.path.abspath(source), (role, root / target_rel))
    return by_source, by_role


def _source_inner(contract: Mapping[str, Any]) -> Path:
    source_name, path = V13._source_inner(contract)
    del source_name
    return path


def _load_actual_outer(request_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    outer, contract, contract_path = V11._outer(request_path)
    inner_path = _source_inner(contract)
    return outer, contract, contract_path, inner_path


def _discover_documents(start: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Walk request/contract/sidecar JSON without following scientific payloads."""
    queue: list[tuple[Path, tuple[str, ...] | None]] = [(start, None)]
    seen: set[str] = set()
    documents: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    while queue:
        path, parent_pointer = queue.pop(0)
        absolute = os.path.abspath(str(path))
        if absolute in seen:
            continue
        if len(documents) >= MAX_DOCUMENTS:
            errors.append({"kind": "document_limit", "path": absolute})
            break
        seen.add(absolute)
        try:
            value = _read_json(path, "recursive metadata document")
        except Root242V14Error as error:
            errors.append({"kind": "document_read_error", "path": absolute, "error": str(error)})
            continue
        document = {
            "source_path": absolute,
            "parent_pointer": _pointer(parent_pointer or ()),
            "bytes": _stat(path)["bytes"],
            "source_sha256": _sha_small(path),
            "followed": True,
        }
        documents.append(document)
        for item in _walk_paths(value):
            if len(refs) >= MAX_REFERENCES:
                errors.append({"kind": "reference_limit", "path": absolute})
                break
            item = dict(item)
            item["document_path"] = absolute
            refs.append(item)
            if not item["actionable"] or item["directory"]:
                continue
            candidate = Path(item["path"])
            if _follow_json(tuple(item["pointer"].strip("/").split("/")) if item["pointer"] else (), candidate):
                if candidate.exists() and candidate.is_file():
                    queue.append((candidate, tuple(item["pointer"].strip("/").split("/"))))
    return documents, refs, errors


def _expanded_roles(roles: Sequence[Mapping[str, Any]], refs: Sequence[Mapping[str, Any]],
                    root: Path) -> tuple[list[Mapping[str, Any]], dict[str, tuple[Mapping[str, Any], Path]], list[dict[str, Any]]]:
    source_map, by_role = _role_maps(roles, root)
    expanded: list[Mapping[str, Any]] = list(roles)
    missing: list[dict[str, Any]] = []
    seen_discovered: set[str] = set()
    next_index = 0
    for ref in refs:
        if not ref.get("actionable") or ref.get("directory"):
            continue
        if len(expanded) >= MAX_ROLE_COUNT:
            missing.append({
                "kind": "source_role_limit",
                "limit": MAX_ROLE_COUNT,
                "pointer": ref.get("pointer"),
                "path": ref.get("path"),
            })
            break
        path = Path(str(ref["path"]))
        source = os.path.abspath(str(path))
        if source in source_map:
            continue
        if path.name == "resource-ledger.json":
            missing.append({
                "kind": "live_ledger_requires_frozen_snapshot",
                "pointer": ref.get("pointer"), "path": str(path),
                "document_path": ref.get("document_path"),
            })
            continue
        if source in seen_discovered:
            continue
        seen_discovered.add(source)
        context = {str(part).lower() for part in str(ref.get("pointer", "")).split("/")}
        # Only the two newly discovered terminal evidence files are hashed in
        # this source-only phase.  Code, XML, CSV, and copied native members
        # get stat/declared-SHA records and remain parent-after-reservation;
        # no incidental payload bytes are read merely to make a role.
        hash_content = (
            path.suffix.lower() == ".json"
            and ("terminal_delta" in context or "terminal_evidence" in context)
        )
        try:
            role = _make_discovered_role(path, index=next_index,
                                         expected_sha256=ref.get("expected_sha256"),
                                         hash_content=hash_content)
        except Root242V14Error as error:
            missing.append({
                "kind": "unbound_or_missing_actionable_path",
                "pointer": ref.get("pointer"), "path": str(path),
                "document_path": ref.get("document_path"), "error": str(error),
            })
            continue
        next_index += 1
        logical = str(role["logical_role"])
        target_rel = str(role["target_relative_path"])
        expanded.append(role)
        by_role[logical] = role
        source_map[source] = (role, root / target_rel)
    return expanded, source_map, missing


def _rewrite_documents(documents: Sequence[Mapping[str, Any]], *, root: Path,
                       source_map: Mapping[str, tuple[Mapping[str, Any], Path]]) -> tuple[
                           dict[str, Any], list[dict[str, Any]], list[dict[str, Any]],
                           list[dict[str, Any]]]:
    rewritten: list[dict[str, Any]] = []
    all_bindings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    old_directory = V2._directory_rebind
    V2._directory_rebind = _directory_rebind_v14
    try:
        for document in documents:
            path = Path(str(document["source_path"]))
            value = _read_json(path, "rewrite source document")
            bindings: list[dict[str, Any]] = []
            try:
                rebased = V2._rewrite_request(
                    value, root=root, source_map=source_map, role_by_target={},
                    bindings=bindings, parts=(),
                )
            except Exception as error:  # report the complete preflight, never fallback
                errors.append({"kind": "v2_rewrite_error", "document_path": str(path),
                               "error": str(error)})
                continue
            all_bindings.extend([{**item, "document_path": str(path)} for item in bindings])
            body = json.dumps(rebased, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False)
            rewritten.append({
                "source_path": str(path),
                "source_sha256": document["source_sha256"],
                "rebased_canonical_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "actionable_binding_count": sum(1 for item in bindings if item.get("actionable")),
                "provenance_binding_count": sum(1 for item in bindings if not item.get("actionable")),
                "rebased": rebased,
            })
    finally:
        V2._directory_rebind = old_directory
    root_doc = rewritten[0]["rebased"] if rewritten else None
    return root_doc, rewritten, all_bindings, errors


def preflight_inner(*, inner_path: Path, roles: Sequence[Mapping[str, Any]],
                    target_root: Path) -> dict[str, Any]:
    """Run the full source-only V14 preflight over an inner request graph."""
    if target_root.exists() and (target_root.is_symlink() or any(target_root.iterdir())):
        raise Root242V14Error(f"refusing non-empty target root: {target_root}")
    documents, refs, graph_errors = _discover_documents(inner_path)
    expanded, source_map, unbound = _expanded_roles(roles, refs, target_root)
    root_rebased, rewritten, bindings, rewrite_errors = _rewrite_documents(
        documents, root=target_root, source_map=source_map,
    ) if not graph_errors and not unbound else (None, [], [], [])
    action_refs = [item for item in refs if item.get("actionable") and not item.get("directory")]
    synthetic_refs = [item for item in refs if item.get("actionable") and item.get("directory")]
    status = "READY_FOR_PARENT_GUARD_METADATA_ONLY"
    if graph_errors or unbound or rewrite_errors:
        status = "REJECTED_RECURSIVE_ACTIONABLE_CLOSURE"
    role_rows: list[dict[str, Any]] = []
    for role in expanded:
        row = {
            "logical_role": role.get("logical_role"),
            "classification": role.get("classification", "source_role"),
            "source_path_provenance": role.get("source_path_provenance"),
            "source_sha256": role.get("source_sha256"),
            "source_stat_provenance": dict(role.get("source_stat_provenance", {})),
            "target_relative_path": role.get("target_relative_path"),
            "deferred_content": bool(role.get("deferred_content")),
            "content_verification_phase": role.get("content_verification_phase"),
        }
        role_rows.append(row)
    return {
        "schema": REQUEST_SCHEMA,
        "status": status,
        "target_root": str(target_root),
        "source_inner_request": {
            "path": str(inner_path),
            "file_sha256": _sha_small(inner_path),
            "stat": _stat(inner_path),
        },
        "documents": rewritten,
        "document_count": len(documents),
        "recursive_reference_count": len(refs),
        "actionable_reference_count": len(action_refs),
        "synthetic_directory_count": len(synthetic_refs),
        "role_count": len(role_rows),
        "base_role_count": len(roles),
        "discovered_role_count": len(role_rows) - len(roles),
        "roles": role_rows,
        "nested_actionable_bindings": bindings,
        "rewrite": {
            "v2_rewrite_invoked": bool(rewritten),
            "root_rebased_request": root_rebased,
            "documents": [
                {
                    "source_path": item["source_path"],
                    "source_sha256": item["source_sha256"],
                    "rebased_canonical_sha256": item["rebased_canonical_sha256"],
                    "actionable_binding_count": item["actionable_binding_count"],
                    "provenance_binding_count": item["provenance_binding_count"],
                }
                for item in rewritten
            ],
            "errors": rewrite_errors,
        },
        "unbound_actionable_paths": unbound,
        "graph_errors": graph_errors,
        "policy": {
            "original_path_fallback": "REJECT",
            "reports_receipts_terminal_evidence_are_actionable": True,
            "live_resource_ledger": "REQUIRES_FROZEN_SNAPSHOT",
            "payload_content_read_by_builder": False,
            "hdf5_bi4_jsonl_content_read_by_builder": False,
            "ledger_mutated": False,
            "portable_cold_replay_credit": "NOT_CLAIMED",
        },
    }


def preflight_actual(*, request_path: Path, target_root: Path) -> dict[str, Any]:
    outer, contract, contract_path, inner_path = _load_actual_outer(request_path)
    del outer
    binding = contract.get("root242_source_binding")
    if not isinstance(binding, Mapping) or not isinstance(binding.get("roles"), list):
        raise Root242V14Error("complete ROOT242 source role table is missing")
    result = preflight_inner(inner_path=inner_path, roles=binding["roles"], target_root=target_root)
    result["source_contract"] = {
        "path": str(contract_path),
        "file_sha256": _sha_small(contract_path),
        "role_table_sha256": hashlib.sha256(json.dumps(
            binding["roles"], sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")).hexdigest(),
    }
    result["request_path"] = str(request_path)
    result["request_file_sha256"] = _sha_small(request_path)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True,
                        help="ROOT242 outer request; no parent reservation is performed")
    parser.add_argument("--target-root", type=Path, required=True,
                        help="fresh future target namespace; it is not populated")
    parser.add_argument("--output", type=Path, required=True,
                        help="metadata-only V14 report path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = preflight_actual(
            request_path=args.request.expanduser().absolute(),
            target_root=args.target_root.expanduser().absolute(),
        )
        output = args.output.expanduser().absolute()
        if output.exists() or output.is_symlink():
            raise Root242V14Error(f"refusing existing V14 report: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True,
                                     ensure_ascii=True, allow_nan=False) + "\n",
                          encoding="utf-8")
        print(json.dumps({
            "schema": result["schema"], "status": result["status"],
            "output": str(output), "role_count": result["role_count"],
            "document_count": result["document_count"],
            "unbound_count": len(result["unbound_actionable_paths"]),
            "rewrite_error_count": len(result["rewrite"]["errors"]),
            "payload_read": False,
        }, sort_keys=True))
        return 0 if result["status"] == "READY_FOR_PARENT_GUARD_METADATA_ONLY" else 2
    except (Root242V14Error, V13.Root242V13ExecutorError,
            V11.Root242V11ExecutorError, V2.PortableRebindV2Error,
            V11.V9.V1.PortableRebindError, OSError, TypeError, ValueError,
            json.JSONDecodeError) as error:
        print(f"ROOT242 V14 preflight: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
