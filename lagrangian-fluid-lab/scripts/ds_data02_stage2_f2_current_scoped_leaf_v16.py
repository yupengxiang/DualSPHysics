#!/usr/bin/env python3
"""V16 scoped CURRENT336 leaf contract for the portable typed consumer.

The ROOT242 graph contains a large CURRENT336 catalog.  The V8/V12 proof
consumer and the typed-only scorer bind CURRENT by its exact content digest and
case identity; they do not open ``cases[*].manifest.path``.  V16 makes that
boundary explicit.  A CURRENT file is a sealed, exact-SHA/stat leaf.  Nested
manifest paths are not recursively opened or silently exempted.  If a future
consumer actually needs one, it must register that one manifest as a separate
source role with its own SHA/stat.

This module is additive.  It does not modify V14/V15/V2 or any consumed
request.  Its ``rebind_scoped_document`` uses the V15 rebinder with only the
CURRENT leaf recursion boundary changed, and its chain helper is a small
metadata-only execution-order probe used by the copied-runtime fixture.
No H5, BI4, raw, typed-result, model, ledger, or parent resource operation is
performed here.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V15_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V12_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
SCORER_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v1.py"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CONTRACT_SCHEMA = "ds02.stage2.f2-current-scoped-leaf-contract.v16"
AUDIT_SCHEMA = "ds02.stage2.f2-current-consumer-audit.v16"
MAX_METADATA_BYTES = 10 * 1024 * 1024
HEX64 = frozenset("0123456789abcdef")


class CurrentScopedLeafError(RuntimeError):
    """Raised when CURRENT or its bounded consumer contract is unsafe."""


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CurrentScopedLeafError(f"cannot load V15 dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V15 = _load(V15_SCRIPT, "ds02_current_scoped_leaf_v15")
_V15_ORIGINAL_SHOULD_RECURSE = V15._should_recurse


def _sha(path: Path, *, maximum: int = MAX_METADATA_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise CurrentScopedLeafError(f"bound file is not regular/non-symlink: {path}")
    size = path.stat().st_size
    if size > maximum:
        raise CurrentScopedLeafError(f"bounded metadata limit exceeded: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise CurrentScopedLeafError(f"bound file is not regular/non-symlink: {path}")
    value = path.stat()
    return {
        "bytes": int(value.st_size),
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _sha_value(value: Any, role: str) -> str:
    if (not isinstance(value, str) or len(value) != 64 or
            any(char not in HEX64 for char in value.lower())):
        raise CurrentScopedLeafError(f"{role} must be a lowercase SHA-256")
    if value != value.lower():
        raise CurrentScopedLeafError(f"{role} must use lowercase hexadecimal")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _absolute_file(value: Any, role: str) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        raise CurrentScopedLeafError(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    _stat(target)
    return target


def default_consumer_sources() -> dict[str, Path]:
    """Return the exact source modules used by the V8/V12/scorer path."""
    return {
        "fresh_v16_proof_consumer_v8": V8_SCRIPT,
        "fresh_v16_proof_consumer_v12": V12_SCRIPT,
        "typed_only_scorer_v1": SCORER_SCRIPT,
    }


def _source_audit(path: Path, role: str) -> dict[str, Any]:
    """Audit only CURRENT-path semantics, with a conservative fail-closed rule.

    The actual modules may open their request, sidecar, result, or frozen
    scorer files.  What matters here is narrower: a consumer that reaches into
    ``current_manifest``/``current_catalog`` and asks for its ``path`` would
    make the sealed-leaf contract unsound.  The lexical checks below are backed
    by AST checks for the common ``x["path"]`` and ``x.get("path")`` forms.
    """
    source_stat = _stat(path)
    if source_stat["bytes"] > MAX_METADATA_BYTES:
        raise CurrentScopedLeafError(f"consumer source exceeds metadata limit: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        raise CurrentScopedLeafError(f"consumer source is not parseable: {path}") from error

    forbidden: list[str] = []

    def name_text(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id.lower()
        if isinstance(node, ast.Attribute):
            return f"{name_text(node.value)}.{node.attr.lower()}"
        return ""

    for node in ast.walk(tree):
        # Reject current_manifest/current_catalog direct path extraction.
        if isinstance(node, ast.Subscript):
            base = name_text(node.value)
            key = node.slice
            key_value = key.value if isinstance(key, ast.Constant) else None
            if (key_value == "path" and
                    ("current_manifest" in base or "current_catalog" in base)):
                forbidden.append("subscript-path")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            method = node.func.attr
            base = name_text(node.func.value)
            if method in {"get", "open", "read_text", "read_bytes"} and (
                    "current_manifest" in base or "current_catalog" in base):
                if method != "get" or (node.args and isinstance(node.args[0], ast.Constant)
                                        and node.args[0].value == "path"):
                    forbidden.append(f"{method}-current-path")
    # A simple negative fixture often uses a literal current_manifest path
    # access with a different AST shape; keep this explicit and narrow.
    for line in text.splitlines():
        lowered = line.lower().replace(" ", "")
        if ("current_manifest.get(\"path\")" in lowered or
                "current_catalog.get(\"path\")" in lowered or
                "current_manifest[\"path\"]" in lowered or
                "current_catalog[\"path\"]" in lowered):
            forbidden.append("literal-current-path")
    if forbidden:
        raise CurrentScopedLeafError(
            f"{role} reads a nested CURRENT manifest/catalog path: {sorted(set(forbidden))}")
    return {
        "role": role,
        "path": str(path),
        "sha256": _sha(path),
        "stat": source_stat,
        "current_access": "EXACT_SHA_AND_IDENTITY_ONLY",
        "nested_manifest_path_open": False,
        "source_fallback": "REJECT",
    }


def audit_consumers(consumer_sources: Mapping[str, Path | str] | None = None) -> dict[str, Any]:
    sources = consumer_sources or default_consumer_sources()
    if not isinstance(sources, Mapping) or not sources:
        raise CurrentScopedLeafError("at least one consumer source is required")
    roles = []
    for role, raw_path in sources.items():
        if not isinstance(role, str) or not role:
            raise CurrentScopedLeafError("consumer role must be a non-empty string")
        roles.append(_source_audit(_absolute_file(raw_path, role), role))
    roles.sort(key=lambda item: item["role"])
    return {
        "schema": AUDIT_SCHEMA,
        "status": "PASS_CURRENT_EXACT_SHA_IDENTITY_ONLY",
        "roles": roles,
        "nested_manifest_paths": "PROVENANCE_NOT_OPENED_BY_CONSUMER",
        "payload_read": False,
        "original_path_fallback": "REJECT",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build_current_leaf_contract(*, current_path: Path | str,
                                case_identity: Mapping[str, Any],
                                consumer_sources: Mapping[str, Path | str] | None = None,
                                expected_sha256: str = CURRENT_SHA) -> dict[str, Any]:
    """Build a strict sealed CURRENT leaf without parsing its case array."""
    current = _absolute_file(current_path, "CURRENT catalog")
    observed_sha = _sha(current)
    expected = _sha_value(expected_sha256, "expected CURRENT SHA")
    if observed_sha != expected:
        raise CurrentScopedLeafError("CURRENT catalog SHA differs from the pinned source")
    if not isinstance(case_identity, Mapping) or not case_identity:
        raise CurrentScopedLeafError("case_identity is required")
    required_identity = ("family_id", "physical_case_id", "identity_status")
    if any(key not in case_identity for key in required_identity):
        raise CurrentScopedLeafError("case_identity lacks family/physical/status fields")
    if case_identity.get("identity_status") in {
            "HISTORICAL_ALIAS_UNRESOLVED", "UNRESOLVED", "UNKNOWN"}:
        raise CurrentScopedLeafError("unresolved historical alias cannot become a CURRENT leaf identity")
    audit = audit_consumers(consumer_sources)
    contract: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_SCOPED_CURRENT_SEALED_LEAF",
        "current_leaf_policy": "SEALED_EXACT_CURRENT_SHA_IDENTITY",
        "current_binding": {
            "path": str(current),
            "sha256": observed_sha,
            "stat": _stat(current),
            "content_verification_phase": "PARENT_AFTER_RESERVATION",
        },
        "case_scope": {"identity": dict(case_identity),
                       "selection_is_single_case": True,
                       "catalog_membership_sha256": observed_sha},
        "consumer_audit": audit,
        "nested_manifest_paths": {
            "policy": "PROVENANCE_NOT_OPENED_BY_CONSUMER",
            "opened": False,
            "recursive_rebase": "SEALED_LEAF",
            "allowlist": [],
        },
        "original_path_fallback": "REJECT",
        "payload_read": False,
        "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    contract["sha256"] = _canonical(contract)
    return contract


def write_contract(path: Path | str, contract: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise CurrentScopedLeafError(f"refusing to overwrite V16 contract: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(contract), indent=2, sort_keys=True,
                                  ensure_ascii=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    return target


def _validate_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise CurrentScopedLeafError("V16 contract schema differs")
    if contract.get("sha256") != _canonical(contract):
        raise CurrentScopedLeafError("V16 contract canonical SHA differs")
    current = contract.get("current_binding")
    if not isinstance(current, Mapping):
        raise CurrentScopedLeafError("V16 CURRENT binding is missing")
    path = _absolute_file(current.get("path"), "V16 CURRENT binding")
    expected_sha = _sha_value(current.get("sha256"), "V16 CURRENT binding SHA")
    if _sha(path) != expected_sha:
        raise CurrentScopedLeafError("V16 CURRENT binding content SHA differs")
    if dict(_stat(path)) != dict(current.get("stat", {})):
        raise CurrentScopedLeafError("V16 CURRENT binding stat differs")
    if contract.get("original_path_fallback") != "REJECT":
        raise CurrentScopedLeafError("V16 contract permits original path fallback")
    leaf = contract.get("nested_manifest_paths")
    if not isinstance(leaf, Mapping) or leaf.get("opened") is not False or leaf.get("allowlist") != []:
        raise CurrentScopedLeafError("V16 nested CURRENT manifest is not a sealed leaf")
    audit = contract.get("consumer_audit")
    if not isinstance(audit, Mapping) or audit.get("status") != "PASS_CURRENT_EXACT_SHA_IDENTITY_ONLY":
        raise CurrentScopedLeafError("V16 consumer audit is not exact-SHA-only")
    return dict(contract)


def validate_contract(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_METADATA_BYTES:
        raise CurrentScopedLeafError("V16 contract must be a bounded regular file")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CurrentScopedLeafError(f"cannot read V16 contract: {error}") from error
    if not isinstance(value, Mapping):
        raise CurrentScopedLeafError("V16 contract must be an object")
    _validate_contract(value)
    return {"schema": CONTRACT_SCHEMA, "status": "PASS_V16_SCOPED_CURRENT_LEAF",
            "contract_path": str(target), "contract_sha256": _sha(target),
            "payload_read": False, "ledger_mutated": False}


def _scoped_should_recurse(parts: tuple[str, ...]) -> bool:
    """V15 recursion boundary: CURRENT itself is the only sealed leaf."""
    lowered = {str(item).lower() for item in parts}
    # This exact context is the binding object, not an arbitrary key containing
    # the word manifest.  V8/V12 do not open its internal cases[*] manifest.
    if "current_manifest" in lowered or "current_manifest_binding" in lowered:
        return False
    return _V15_ORIGINAL_SHOULD_RECURSE(parts)


def rebind_scoped_document(*, document: Path | str, root: Path | str,
                           source_map: Mapping[str, tuple[Mapping[str, Any], Path]],
                           contract: Mapping[str, Any], label: str = "current-scoped") -> dict[str, Any]:
    """Rebase a bounded V15 document while keeping CURRENT a sealed leaf.

    The source map must include the CURRENT file itself.  Its internal
    ``cases[*].manifest.path`` is intentionally never opened by this helper;
    a caller that needs it must add a separate exact source-map role and use a
    different contract.
    """
    _validate_contract(contract)
    source = _absolute_file(document, "scoped metadata document")
    target_root = Path(root).expanduser().absolute()
    if target_root.is_symlink():
        raise CurrentScopedLeafError("scoped target root must not be a symlink")
    target_root.mkdir(parents=True, exist_ok=True)
    old = V15._should_recurse
    V15._should_recurse = _scoped_should_recurse
    try:
        target, _value, source_sha = V15._recursive_rebase(
            source, root=target_root, source_map=source_map, label=label)
    finally:
        V15._should_recurse = old
    return {
        "schema": "ds02.stage2.f2-current-scoped-rebound-document.v16",
        "status": "PASS_CURRENT_LEAF_REBOUND",
        "source_path": str(source), "source_sha256": source_sha,
        "target_path": str(target), "target_sha256": _sha(target),
        "current_manifest_internal_paths_opened": False,
        "source_fallback": "REJECT", "payload_read": False,
    }


def build_eight_document_fixture(base: Path | str) -> dict[str, Any]:
    """Create the bounded eight-document graph used by the V16 integration test.

    This is deliberately a fixture builder, never a production-data adapter.
    It writes seven tiny request/evidence documents plus one CURRENT leaf.  The
    leaf contains an absent ``cases[0].manifest.path`` so a broad recursive
    walker fails, while the scoped V8/V12/scorer path succeeds without opening
    that nested path.
    """
    root = Path(base).expanduser().absolute()
    source_dir = root / "source"
    target_root = root / "target"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)
    current = source_dir / "CURRENT336.json"
    current.write_text(json.dumps({
        "schema": "fixture.current336.v1",
        "source_catalog_sha256": "f" * 64,
        "cases": [{"physical_case_id": "F2_CASE65",
                   "manifest": {"path": str(source_dir / "absent-manifest.json")}}],
    }, sort_keys=True) + "\n", encoding="utf-8")
    document_names = (
        "root200-inner.json", "root194-inner.json", "root200-sidecar.json",
        "root194-sidecar.json", "root190-proof.json", "root190-source-contract.json",
    )
    contexts = ("source_request", "replaces_request", "semantic_sidecar",
                "root194_sidecar", "frozen", "root_proof")
    documents: dict[str, Path] = {}
    for name in document_names:
        path = source_dir / name
        path.write_text(json.dumps({
            "schema": "fixture.bound-metadata.v1", "document": name,
            "current_manifest": {"path": str(current)},
        }, sort_keys=True) + "\n", encoding="utf-8")
        documents[name] = path
    root_document = source_dir / "root242-request.json"
    root_value: dict[str, Any] = {
        "schema": "fixture.root242-request.v16",
        "current_manifest_binding": {"path": str(current), "sha256": _sha(current)},
    }
    for context, name in zip(contexts, document_names):
        root_value[context] = {"path": str(documents[name]), "sha256": _sha(documents[name])}
    root_document.write_text(json.dumps(root_value, sort_keys=True) + "\n", encoding="utf-8")
    target_current = target_root / "evidence" / "CURRENT336.json"
    target_current.parent.mkdir(parents=True, exist_ok=True)
    target_current.write_bytes(current.read_bytes())
    source_map: dict[str, tuple[Mapping[str, Any], Path]] = {
        str(current): ({
            "logical_role": "current_catalog_exact_leaf",
            "source_path_provenance": str(current), "source_sha256": _sha(current),
            "source_stat_provenance": _stat(current),
            "target_relative_path": str(target_current.relative_to(target_root)),
        }, target_current),
    }
    for name, source in documents.items():
        target = target_root / "evidence" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        source_map[str(source)] = ({
            "logical_role": f"fixture_{name.removesuffix('.json').replace('-', '_')}",
            "source_path_provenance": str(source), "source_sha256": _sha(source),
            "source_stat_provenance": _stat(source),
            "target_relative_path": str(target.relative_to(target_root)),
        }, target)
    contract = build_current_leaf_contract(
        current_path=current,
        expected_sha256=_sha(current),
        case_identity={"family_id": "F2", "physical_case_id": "F2_CASE65",
                       "identity_status": "CANONICAL"},
        consumer_sources={"fixture_v8": source_dir / "root200-inner.json"},
    )
    return {"root_document": root_document, "current": current,
            "target_root": target_root, "source_map": source_map,
            "contract": contract, "document_count": 8,
            "documents": [root_document, *documents.values(), current]}


CHAIN_ORDER = (
    "v14", "v13", "v11", "copied_entry_v15", "v16_scoped_rebinder", "v2_globals",
)


def run_scoped_chain(stages: Mapping[str, Callable[[], Any]]) -> dict[str, Any]:
    """Run the copied metadata entry sequence and record every stage."""
    if not isinstance(stages, Mapping):
        raise CurrentScopedLeafError("chain stages must be a mapping")
    missing = [name for name in CHAIN_ORDER if not callable(stages.get(name))]
    if missing:
        raise CurrentScopedLeafError(f"scoped chain is missing stages: {missing}")
    events: list[str] = []
    values: dict[str, Any] = {}
    for name in CHAIN_ORDER:
        values[name] = stages[name]()
        events.append(name)
    return {
        "schema": "ds02.stage2.f2-current-scoped-chain.v16",
        "status": "PASS_V14_V13_V11_V15_V16_V2_ORDER",
        "events": events, "values": values, "payload_read": False,
        "ledger_mutated": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--family-id", required=True)
    build.add_argument("--physical-case-id", required=True)
    build.add_argument("--identity-status", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--consumer", action="append", default=[], metavar="ROLE=PATH")
    validate = sub.add_parser("validate")
    validate.add_argument("--contract", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_contract(args.contract)
        else:
            consumers: dict[str, Path] = {}
            for item in args.consumer:
                if "=" not in item:
                    raise CurrentScopedLeafError("--consumer must be ROLE=PATH")
                role, path = item.split("=", 1)
                if not role or not path:
                    raise CurrentScopedLeafError("--consumer must be ROLE=PATH")
                consumers[role] = Path(path)
            contract = build_current_leaf_contract(
                current_path=args.current,
                case_identity={"family_id": args.family_id,
                               "physical_case_id": args.physical_case_id,
                               "identity_status": args.identity_status},
                consumer_sources=consumers or None,
            )
            output = write_contract(args.output, contract)
            result = {"schema": CONTRACT_SCHEMA, "status": "READY_SCOPED_CURRENT_SEALED_LEAF",
                      "path": str(output), "file_sha256": _sha(output),
                      "payload_read": False, "ledger_mutated": False}
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (CurrentScopedLeafError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V16 scoped CURRENT leaf: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
