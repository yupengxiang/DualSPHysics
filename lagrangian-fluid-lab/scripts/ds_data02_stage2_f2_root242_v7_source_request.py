#!/usr/bin/env python3
"""Build the ROOT242 V7 source-only parent handoff.

This builder consumes the byte-frozen ROOT230 V5 request and copy manifest and
emits a *new* V7 metadata contract plus its ds02.request.v1 parent wrapper. It
does not run the V7 executor, reserve the ledger, copy a source, or read a
deferred H5/BI4/native/result payload. The parent owns those operations after
its atomic reservation.

The important distinction in this file is between a path which is merely
provenance and a path that a later V2/V8/V12/scorer stage will open. Reports,
receipts, solver logs, XMF and nested historical sidecars are actionable when
they occur in a consumer graph: they need a declared SHA/stat and a copied
target. Only the explicitly declared parent resource ledger is administrative
and mutable. A historical frozen ledger remains a sealed input when a
consumer reads its content.

The resulting wrapper is a source handoff, not portable or scientific credit.
It records an OS-open trace and old-root poison check that the supervised
parent must perform after the attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat as statmod
import sys
from typing import Any, Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
MAX_METADATA_BYTES = 10 * 1024 * 1024
HEX64 = frozenset("0123456789abcdef")
FULL_STAT = ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
DECLARED_STAT = ("bytes", "mode_bits", "mtime_ns")
REQUEST_SCHEMA = "ds02.request.v1"
CONTRACT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-parent-request.v1"
HANDOFF_SCHEMA = "ds02.stage2.f2-root242-v7-source-binding.v1"

# These are annotations, not a blanket exemption for a file named report or
# receipt.  The V7 executor has the same narrow policy; keeping it local makes
# the source-only builder independently auditable.
PROVENANCE_CONTEXTS = frozenset({
    "original_roots", "source_provenance", "provenance", "old_absolute_paths",
    "source_path_provenance", "argv0_provenance", "resolved_provenance",
    "git_at_launch",
})
REFERENCE_ONLY_CONTEXTS = frozenset({
    # These rows document an older graph's candidate input list.  They are
    # not the current V2/V12/scorer input edge; a row without a content SHA is
    # retained as provenance and cannot authorize a source open.
    "metadata_graph_reference_rows",
})
ADMIN_REFERENCE_CONTEXTS = frozenset({
    # Resource leases are mutable parent bookkeeping.  They are joined to
    # the one shared ledger by the outer guard and are never scientific copy
    # inputs; a historical lease path therefore remains an administrative
    # reference rather than an unsealed source edge.
    "lease", "leases", "gpu_lease", "resource_lease", "parent_resource_lease",
    "actual_progress", "live_queue_progress", "ledger", "live_ledger",
    "parent_resource_ledger", "resource_ledger",
})
GENERATED_CONTEXTS = frozenset({
    "trace", "trace_path", "expected_artifacts", "home_receipt",
    "finalization_sidecar", "scratch", "decoder_scratch", "filesystem_headroom",
    "delete_files", "removed_from_successor_request", "future_outputs",
})
DATASET_POINTER_CONTEXTS = frozenset({
    "dataset_discovery", "dataset_paths", "hdf5_datasets", "hdf5_dataset",
    "field_paths", "array_paths", "dataset_pointer",
})
DIRECTORY_KEYS = frozenset({
    "root", "target_root", "output_root", "runtime_root", "runtime_target_root",
    "fresh_output_root", "fresh_output_namespace", "fresh_proof_namespace",
    "proof_namespace", "bundle_target", "target_product_root", "target_runtime_root",
    "target_evidence_root", "namespace_root", "proof_output_root_binding",
    "output_root_rebind", "source_root", "raw_root", "data_root", "bundle_root",
    "products", "root_source_provenance_directories", "endpoint_visual_acceptance_scope",
    "directory_references", "nvme_staging", "excluded_prior_packages",
})
SHA_KEYS = (
    # Failure reports sometimes preserve both the producer's expected digest
    # (``declared``) and the observed file digest (``actual``).  The current
    # bounded source identity is the observed value; the mismatch remains in
    # the parent metadata and is never silently turned into a PASS.
    "actual_sha256", "actual", "current_file_sha256", "historical_input_sha256",
    "file_sha256", "sha256", "sha", "expected_sha256", "registered_sha256",
    "source_sha256", "producer_sha256", "content_sha256", "report_sha256",
    "receipt_sha256", "proof_sha256", "contract_sha256", "manifest_sha256",
    "physical_sha256", "producer_declared_sha256", "recomputed_sha256",
    "sha256_producer_attested", "producer_attested_sha256", "sha256_at_integration",
)


class Root242SourceError(RuntimeError):
    """A strict source-only ROOT242 closure or request error."""


def _fail(message: str) -> None:
    raise Root242SourceError(message)


def _abs(value: Any, role: str, *, allow_symlink: bool = False) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        _fail(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink() and not allow_symlink:
        _fail(f"{role} may not be a symlink: {path}")
    return path


def _safe_rel(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{role} target path is missing")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        _fail(f"{role} target path escapes the copied root: {value}")
    return path.as_posix()


def _full_stat(path: Path, role: str, *, allow_symlink: bool = False) -> dict[str, int]:
    if path.is_symlink() and not allow_symlink:
        _fail(f"{role} is a symlink")
    try:
        value = path.stat()
    except OSError as error:
        _fail(f"cannot stat {role}: {error}")
    if not statmod.S_ISREG(value.st_mode) and not path.is_dir():
        _fail(f"{role} is not a regular file/directory: {path}")
    return {
        "bytes": int(value.st_size), "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
    }


def _sha_file(path: Path, role: str, *, maximum: int = MAX_METADATA_BYTES) -> str:
    value = _full_stat(path, role)
    if value["bytes"] > maximum:
        _fail(f"{role} is larger than the metadata-only hash limit: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        _fail(f"cannot hash {role}: {error}")
    return digest.hexdigest()


def _json(path: Path, role: str) -> dict[str, Any]:
    value = _full_stat(path, role)
    if value["bytes"] > MAX_METADATA_BYTES:
        _fail(f"{role} is larger than the bounded JSON limit: {path}")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read {role}: {error}")
    if not isinstance(result, dict):
        _fail(f"{role} must contain a JSON object")
    return result


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _declared_sha(value: Mapping[str, Any]) -> str | None:
    for key in SHA_KEYS:
        candidate = value.get(key)
        if (isinstance(candidate, str) and len(candidate) == 64
                and set(candidate) <= HEX64):
            return candidate
    return None


def _declared_stat(value: Mapping[str, Any]) -> dict[str, int] | None:
    for key in ("source_stat_expected", "source_stat", "stat", "expected_stat"):
        candidate = value.get(key)
        if isinstance(candidate, Mapping):
            result = {}
            for field in FULL_STAT:
                raw = candidate.get(field)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    break
                result[field] = int(raw)
            if all(field in result for field in DECLARED_STAT):
                return result
    inline = {}
    for field in FULL_STAT:
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        inline[field] = int(raw)
    return inline if all(field in inline for field in DECLARED_STAT) else None


def _pointer(parts: Sequence[str]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1")
                   for part in parts)


def _in_context(parts: Sequence[str], contexts: Iterable[str]) -> bool:
    expected = {str(item).lower() for item in contexts}
    return any(str(item).lower() in expected for item in parts)


def _is_generated(parts: Sequence[str], parent: Mapping[str, Any]) -> bool:
    lowered = {str(item).lower() for item in parts}
    role = str(parent.get("role", "")).lower()
    source_kind = str(parent.get("source_kind", "")).lower()
    # Decoder cleanup/scratch paths are attempt-owned directory anchors.  Do
    # not treat a generic ``cleanup`` field as generated; it must be nested
    # under the decoder/scratch context.
    return (bool(lowered & GENERATED_CONTEXTS) or role in {
        "parent_os_open_trace", "generated_output", "generated_trace",
    } or source_kind in {"generated_output", "runtime_trace", "parent_output"}
            or ("cleanup" in lowered and ("decoder" in lowered or "scratch" in lowered)))


def _is_dataset_pointer(parts: Sequence[str]) -> bool:
    return bool({str(item).lower() for item in parts} & DATASET_POINTER_CONTEXTS)


def _is_admin_ledger_edge(parent: Mapping[str, Any], path_value: str) -> bool:
    """Recognize the mutable shared ledger without treating it as a source."""
    if Path(path_value).name != "resource-ledger.json":
        return False
    role = str(parent.get("role", "")).lower()
    return bool(
        parent.get("ledger_sha_may_change_within_same_parent_lease") is True
        or parent.get("live_ledger") is True
        or "parent_resource_ledger" in role
        or parent.get("schema") == "ds02.resource-ledger.v1"
    )


def _is_explicit_unknown(parent: Mapping[str, Any], parts: Sequence[str]) -> bool:
    lower = {str(item).lower() for item in parts}
    note = str(parent.get("sha256_source", "")).lower()
    path_name = Path(str(parent.get("path", ""))).name.lower()
    return (
        parent.get("exists") is False
        and any("observation" in item or "diagnostic" in item for item in lower)
    ) or (
        _declared_sha(parent) is None
        and any(token in note for token in ("not_registered", "not_read", "not_consumed"))
    ) or (
        str(parent.get("status", "")).upper() in {"WAIT", "UNKNOWN", "UNRESOLVED", "PENDING"}
        # An explicit unresolved status is itself the producer's declaration
        # that this path is not an input for the current attempt.  If either
        # flag is present and true, fail closed; absent flags remain an
        # explicit WAIT record rather than an implicit report/receipt waiver.
        and parent.get("scientific_input") is not True
        and parent.get("actionable") is not True
    ) or (
        # Some producer plans retain an intentionally disabled optional XMF
        # request as a path-only record.  Its basename is the explicit state
        # marker; do not generalize this to arbitrary missing path records.
        "xmf_request" in lower and "disabled" in path_name
    ) or (
        # An official worker may have consumed this native leaf while the
        # producer intentionally withheld a payload digest.  Retain the
        # unresolved evidence; it cannot become a source-copy role here.
        parent.get("not_a_measured_payload_digest") is True
        and "registered official" in str(parent.get("provenance", "")).lower()
    ) or (
        parent.get("bounded_prefix_only") is True
        and "not_computed" in str(parent.get("hash_policy", "")).lower()
    ) or (
        # Future-input plans may intentionally carry a large scientific leaf
        # without a digest because the guarded producer has not yet opened it.
        # Keep that leaf as an unresolved deferred edge; do not hash it in the
        # metadata builder and do not let it authorize a portable run.
        parent.get("producer_only") is True
        and "future_input_files" in lower
        and _declared_sha(parent) is None
        and any(token in str(parent.get("role", "")).lower()
                for token in ("payload", "initial", "trajectory", "native"))
    ) or (
        # An attempt-results entry can be a retained, unpublished partial H5
        # from a failed job.  Its metadata explicitly says that the payload
        # was never read/hashed and has no runnable reference.  Preserve the
        # forensic edge as unresolved instead of turning a failed partial
        # file into a source-copy role.
        "attempt_results" in lower
        and str(parent.get(
            "actual_failed_status",
            (parent.get("original_file_stat") or {}).get("actual_failed_status", "")
            if isinstance(parent.get("original_file_stat"), Mapping) else ""
        )).lower() == "failed"
        and (
            parent.get("scientific_payload_contents_read_or_hashed") is False
            or (isinstance(parent.get("original_file_stat"), Mapping)
                and parent["original_file_stat"].get(
                    "scientific_payload_contents_read_or_hashed") is False)
        )
        and str(parent.get(
            "absence_of_successful_published_H5_and_conversion_report",
            (parent.get("original_file_stat") or {}).get(
                "absence_of_successful_published_H5_and_conversion_report", ""
            ) if isinstance(parent.get("original_file_stat"), Mapping) else ""
        )).lower() == "true"
        and str(parent.get("path", "")).lower().endswith((".h5.partial", ".partial"))
    ) or (
        # A planned native-solver receipt may be represented only by its
        # future path (no status, return code, or digest).  It is an
        # unresolved plan edge, never a completed solver input.
        "native_solver" in lower
        and str(parent.get("path", "")).lower().endswith("execution-receipt.json")
        and _declared_sha(parent) is None
        and parent.get("returncode") is None
        and parent.get("status") is None
    )


def _is_directory_anchor(parent: Mapping[str, Any], parts: Sequence[str], path: Path) -> bool:
    """Admit only explicit consumed namespace/output directory bindings."""
    if not path.is_dir():
        return False
    lower_parts = {str(item).lower() for item in parts}
    declared_kind = str(parent.get("kind", parent.get("role", ""))).lower()
    return bool(lower_parts & DIRECTORY_KEYS) or any(
        token in declared_kind
        for token in ("directory", "namespace", "output_root", "bundle_root")
    )


def _is_registered_environment_symlink(parent: Mapping[str, Any],
                                       parts: Sequence[str], path: Path) -> bool:
    """Allow only the explicit interpreter provenance exception.

    A producer receipt can record a literal venv interpreter as a symlink and
    separately record the resolved system binary.  That is an environment
    binding, not a scientific source to copy.  Any other symlink remains a
    hard failure, including symlinks in reports, source data, and outputs.
    """
    if not path.is_symlink():
        return False
    source_kind = str(parent.get("source_kind", "")).lower()
    return (
        path.name in {"python", "python3", "python3.10"}
        and "terminal_producer_receipt" in source_kind
        and parent.get("source_did_not_read_or_hash_binary") is True
        and isinstance(parent.get("resolved_receipt_path"), str)
        and _in_context(parts, ("registered_tool_attestations", "python"))
    )


def _is_bounded_unbound_metadata(parent: Mapping[str, Any], path: Path,
                                 parts: Sequence[str] = ()) -> bool:
    """Identify a narrow producer-declared small metadata contract.

    A few historical QA records describe a JSON contract but omit its digest.
    We may bind the current bounded file by hashing it once, but only when the
    record explicitly says this is the pre-solver metadata-only stage and
    explicitly excludes native frame/receipt inputs.  Missing SHA on reports,
    receipts, solver inputs, or payloads still fails closed.
    """
    bounded_file = (
        path.is_file() and not path.is_symlink()
        and path.stat().st_size <= MAX_METADATA_BYTES
    )
    bounded_json = bounded_file and path.suffix.lower() == ".json"
    # The F4 terminal-chain graph contains small render/receipt/manifest JSON
    # files whose producer records are only ``{"path": ...}``.  These are
    # real consumer-side metadata inputs, so they must be sealed here rather
    # than treated as a generic report/receipt exemption.  The exact
    # terminal-chain context, JSON suffix, and 10 MiB bound keep this narrow;
    # the builder hashes each bounded file once and emits that digest as the
    # source binding.  A larger payload or a path outside this context still
    # fails closed when its producer omitted a SHA.
    if (bounded_json
            and "terminal_chain" in {str(item).lower() for item in parts}):
        return True
    if (bounded_json and path.name == "execution-receipt.json"
            and "native_solver" in {str(item).lower() for item in parts}):
        return True
    # A native-producer plan may deliberately omit a digest for its small
    # ``Run.out`` log while marking the row ``producer_only``.  It is still a
    # sealed input if this graph carries it forward.  Hash only this exact
    # basename/role combination; arbitrary solver logs remain fail-closed.
    if (bounded_file and path.name == "Run.out"
            and parent.get("producer_only") is True
            and str(parent.get("role", "")).lower() == "native_solver_log"):
        return True
    return bounded_json and (
        (parent.get("pre_solver_gencase_basic") is True
         and parent.get("requires_native_frame0") is False
         and parent.get("requires_native_receipt") is False)
        or ("qualification_request_summaries" in {str(item).lower() for item in parts}
            and parent.get("solver_output_exact_path_present") is False)
    )


def _classify(item: Mapping[str, Any], *, active_ledger: bool = False) -> str:
    source = Path(str(item.get("source_path_provenance", "")))
    role = str(item.get("logical_role", "")).lower()
    kind = str(item.get("source_kind", "")).lower()
    if active_ledger:
        return "admin_live_ledger_reference"
    if source.name == "resource-ledger.json":
        return "historical_ledger_snapshot"
    if bool(item.get("deferred_content")) or bool(item.get("placeholder_only")):
        return "deferred_payload"
    if ("report" in role or "receipt" in role or "checkpoint" in role
            or "proof" in role or "log" in role or source.name.lower().endswith((
                "report.json", "receipt.json", "proof.json", "checkpoint.json", ".log"))):
        return "sealed_report_or_receipt"
    if kind.startswith("runtime") or kind == "external_environment":
        return "sealed_runtime_source"
    if kind in {"bounded_nested_metadata", "bounded_evidence", "bounded_source", "frozen_source"}:
        return "sealed_metadata_source"
    return "sealed_source"


def _manifest_item_map(artifacts: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in artifacts:
        if not isinstance(raw, Mapping):
            _fail("manifest artifact is not an object")
        source = raw.get("source_path_provenance")
        if not isinstance(source, str) or not source.startswith("/"):
            _fail("manifest artifact source_path_provenance is not absolute")
        item = dict(raw)
        item["source_path_provenance"] = str(Path(source).expanduser())
        item["target_relative_path"] = _safe_rel(item.get("target_relative_path"), "manifest artifact")
        sha = item.get("source_sha256")
        if not isinstance(sha, str) or len(sha) != 64 or not set(sha) <= HEX64:
            _fail(f"manifest artifact has no declared source SHA: {source}")
        stat = item.get("source_stat_provenance")
        if not isinstance(stat, Mapping) or not all(
                field in stat and isinstance(stat[field], (int, float))
                and not isinstance(stat[field], bool) for field in DECLARED_STAT):
            _fail(f"manifest artifact has no source stat contract: {source}")
        key = os.path.abspath(source)
        if key in result and result[key].get("source_sha256") != sha:
            _fail(f"manifest gives conflicting SHA for {source}")
        result[key] = item
    return result


def _make_entry(item: Mapping[str, Any], classification: str,
                pointer: str | None = None) -> dict[str, Any]:
    source = str(item["source_path_provenance"])
    stat = dict(item.get("source_stat_provenance") or {})
    result = {
        "logical_role": item.get("logical_role"),
        "classification": classification,
        "source_path_provenance": source,
        "source_sha256": item.get("source_sha256"),
        "source_stat_provenance": stat,
        "target_relative_path": item.get("target_relative_path"),
        "deferred_content": bool(item.get("deferred_content")),
        "content_read_by_v5_manifest": bool(item.get("content_read_by_manifest")),
        "source_sha_basis": item.get("source_sha256_basis", "DECLARED_SOURCE_SHA"),
    }
    if pointer is not None:
        result["nested_consumption_pointer"] = pointer
    return result


class _Closure:
    def __init__(self, artifacts: Sequence[Mapping[str, Any]], root_old: Path):
        self.items = _manifest_item_map(artifacts)
        self.root_old = root_old
        self.discovered: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.alias_by_target: dict[str, str] = {}
        # A nested consumer graph can mention the same absolute source more
        # than once.  One occurrence may carry the producer SHA while another
        # carries only the path (for example CURRENT336's case_xmf leaf).  A
        # missing local annotation is safe to join only when an *exact same
        # absolute source path* was already bound by the frozen manifest or a
        # bounded metadata record.  Never infer by basename/latest-file.
        self.known_sha_by_source: dict[str, str] = {
            key: str(item["source_sha256"])
            for key, item in self.items.items()
            if isinstance(item.get("source_sha256"), str)
        }
        self.sha_candidates_by_source: dict[str, set[str]] = {
            key: {str(item["source_sha256"])}
            for key, item in self.items.items()
            if isinstance(item.get("source_sha256"), str)
        }
        self.sha_conflicts: list[dict[str, Any]] = []
        self.known_stat_by_source: dict[str, dict[str, int]] = {
            key: dict(item["source_stat_provenance"])
            for key, item in self.items.items()
            if isinstance(item.get("source_stat_provenance"), Mapping)
        }
        self.queue = [Path(key) for key, item in self.items.items()
                      if not item.get("deferred_content")
                      and str(item.get("source_path_provenance", "")).lower().endswith(".json")]
        self.seen: set[str] = set()

    def _index_metadata_file(self, path: Path) -> None:
        """Index exact path/SHA joins from one bounded JSON source.

        This is metadata-only and deliberately does not follow newly found
        paths.  The normal walk still decides whether each path is actionable,
        generated, or provenance-only; this index only prevents a duplicated
        record from losing an already declared identity.
        """
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
            return
        value = _json(path, f"ROOT242 SHA index {path}")

        def visit(node: Any, parts: tuple[str, ...] = ()) -> None:
            if isinstance(node, Mapping):
                path_value = node.get("path")
                if (isinstance(path_value, str) and path_value.startswith("/")
                        and not _in_context(
                            parts,
                            PROVENANCE_CONTEXTS | REFERENCE_ONLY_CONTEXTS
                            | ADMIN_REFERENCE_CONTEXTS)):
                    key = os.path.abspath(path_value)
                    if _is_admin_ledger_edge(node, path_value):
                        return
                    sha = _declared_sha(node)
                    if sha is not None:
                        previous = self.known_sha_by_source.get(key)
                        if previous is not None and previous != sha:
                            candidates = self.sha_candidates_by_source.setdefault(key, {previous})
                            candidates.add(sha)
                            path_obj = Path(key)
                            if (not path_obj.is_file() or path_obj.is_symlink()
                                    or path_obj.stat().st_size > MAX_METADATA_BYTES):
                                _fail(f"conflicting exact-path SHA without bounded source proof for {path_value}")
                            observed = _sha_file(path_obj, f"conflicting exact-path source {path_value}")
                            if observed not in candidates:
                                _fail(f"conflicting exact-path SHA does not match current source for {path_value}")
                            self.sha_conflicts.append({
                                "source_path": key, "declared_sha256": sha,
                                "previous_sha256": previous, "observed_sha256": observed,
                                "resolution": "CURRENT_BOUNDED_SOURCE_MATCHES_DECLARED_CANDIDATE",
                            })
                            self.known_sha_by_source[key] = observed
                        else:
                            self.known_sha_by_source[key] = sha
                            self.sha_candidates_by_source.setdefault(key, {sha}).add(sha)
                    stat = _declared_stat(node)
                    if stat is not None:
                        previous_stat = self.known_stat_by_source.get(key)
                        if previous_stat is not None:
                            # Bytes and mode are content/permission identity.
                            # Timestamps can legitimately differ between a
                            # producer receipt snapshot and the later copied
                            # target; retain the first (manifest) contract and
                            # keep the nested observation as provenance.  A
                            # timestamp difference must never be used to
                            # replace a source SHA or to authorize fallback.
                            for field in ("bytes", "mode_bits"):
                                if field in previous_stat and previous_stat[field] != stat[field]:
                                    _fail(f"conflicting exact-path content stat in metadata index for {path_value}")
                        if previous_stat is None:
                            self.known_stat_by_source[key] = dict(stat)
                for key, child in node.items():
                    visit(child, parts + (str(key),))
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    visit(child, parts + (str(index),))

        visit(value)

    @property
    def all_items(self) -> dict[str, dict[str, Any]]:
        result = dict(self.items)
        result.update(self.discovered)
        return result

    def _active_ledger(self, item: Mapping[str, Any]) -> bool:
        source = Path(str(item.get("source_path_provenance", "")))
        pointer = str(item.get("nested_discovery_pointer", "")).lower()
        role = str(item.get("logical_role", "")).lower()
        return source.name == "resource-ledger.json" and (
            bool(item.get("mutable_source")) or bool(item.get("live_ledger"))
            or "parent_resource_ledger" in role or "live_ledger" in role
            or pointer == "/ledger/path"
        )

    def _add_discovered(self, source: Path, parent: Mapping[str, Any], pointer: str) -> dict[str, Any]:
        key = os.path.abspath(str(source))
        declared_original = parent.get("original_path_provenance")
        if isinstance(declared_original, str) and declared_original.startswith("/"):
            origin_key = os.path.abspath(declared_original)
            previous_alias = self.alias_by_target.get(key)
            if previous_alias is not None and previous_alias != origin_key:
                _fail(f"relocated target has conflicting source aliases at {pointer}: {source}")
            self.alias_by_target[key] = origin_key
        existing = self.all_items.get(key)
        if existing is not None:
            self.edges.append({"pointer": pointer, "source_path": key,
                               "source_sha256": existing.get("source_sha256"),
                               "classification": _classify(existing, active_ledger=self._active_ledger(existing))})
            return existing
        path = Path(source)
        if _is_registered_environment_symlink(parent, pointer.strip("/").split("/"), path):
            stat = _full_stat(path, f"registered interpreter provenance {pointer}", allow_symlink=True)
            sha = _declared_sha(parent) or self.known_sha_by_source.get(key)
            entry = {"source_path_provenance": key,
                     "logical_role": "registered_interpreter_provenance",
                     "source_sha256": sha,
                     "source_stat_provenance": stat,
                     "target_relative_path": None,
                     "deferred_content": True,
                     "placeholder_only": True,
                     "source_kind": "external_environment_symlink_provenance"}
            self.discovered[key] = entry
            self.edges.append({"pointer": pointer, "source_path": key,
                               "source_sha256": sha,
                               "classification": "registered_environment_symlink_provenance",
                               "resolved_path_provenance": parent.get("resolved_receipt_path")})
            return entry
        # A copied request may retain an old target path while explicitly
        # carrying the source path used to create it.  If the target is
        # absent, bind the exact declared original source and retain the
        # target as an alias edge.  This is a closed source-to-target mapping,
        # never a search/fallback to a basename or latest artifact.
        original = declared_original
        if not isinstance(original, str) or not original.startswith("/"):
            original = self.alias_by_target.get(key)
        if (not path.exists() and isinstance(original, str) and original.startswith("/")):
            origin_key = os.path.abspath(original)
            origin_sha = self.known_sha_by_source.get(origin_key)
            declared_sha = _declared_sha(parent)
            if origin_sha is not None and declared_sha is not None and origin_sha != declared_sha:
                _fail(f"relocated target/source SHA differs at {pointer}: {source}")
            sha = declared_sha or origin_sha
            if sha is not None:
                origin_path = Path(origin_key)
                origin_stat = self.known_stat_by_source.get(origin_key)
                if origin_stat is None and origin_path.exists():
                    origin_stat = _full_stat(origin_path, f"relocated source {pointer}")
                if origin_stat is None:
                    origin_stat = _declared_stat(parent)
                if origin_stat is not None:
                    existing_origin = self.all_items.get(origin_key)
                    if existing_origin is not None:
                        self.edges.append({"pointer": pointer, "source_path": key,
                                           "source_binding_path": origin_key,
                                           "source_sha256": sha,
                                           "classification": "relocated_target_alias"})
                        return existing_origin
                    target = f"evidence/recursive/{sha[:16]}-{origin_path.name or 'source'}"
                    item = {
                        "source_path_provenance": origin_key,
                        "logical_role": f"recursive_v7_{sha[:16]}",
                        "source_sha256": sha,
                        "source_stat_provenance": dict(origin_stat),
                        "target_relative_path": target,
                        "deferred_content": bool(origin_path.suffix.lower() in {
                            ".h5", ".hdf5", ".bi4", ".obi4", ".out"
                        } or origin_stat.get("bytes", 0) > MAX_METADATA_BYTES),
                        "placeholder_only": bool(origin_path.suffix.lower() in {
                            ".h5", ".hdf5", ".bi4", ".obi4", ".out"
                        } or origin_stat.get("bytes", 0) > MAX_METADATA_BYTES),
                        "source_kind": "relocated_source_alias",
                    }
                    self.discovered[origin_key] = item
                    self.edges.append({"pointer": pointer, "source_path": key,
                                       "source_binding_path": origin_key,
                                       "source_sha256": sha,
                                       "classification": "relocated_target_alias"})
                    return item
        # A consumed output/namespace directory has no content SHA, but the
        # copied V2 graph still needs a target-local alias.  Keep its stat and
        # relationship explicit; do not exempt arbitrary directory paths.
        if _is_directory_anchor(parent, pointer.strip("/").split("/"), path):
            stat = _full_stat(path, f"nested directory {pointer}")
            entry = {"source_path_provenance": key, "logical_role": "nested_directory_anchor",
                     "source_sha256": None, "source_stat_provenance": stat,
                     "target_relative_path": None, "deferred_content": True,
                     "placeholder_only": True, "source_kind": "directory_anchor"}
            self.discovered[key] = entry
            self.edges.append({"pointer": pointer, "source_path": key,
                               "classification": "directory_anchor",
                               "source_stat_provenance": stat})
            return entry
        sha = _declared_sha(parent)
        computed_metadata_sha = False
        if sha is None and _is_bounded_unbound_metadata(
                parent, path, pointer.strip("/").split("/")):
            sha = _sha_file(path, f"bounded metadata-only source {pointer}")
            computed_metadata_sha = True
        if sha is None:
            # Exact-path identity join across duplicated nested records.  This
            # remains strict: the source must have been independently bound by
            # the frozen manifest or another bounded JSON record.
            sha = self.known_sha_by_source.get(key)
        # A few historical conversion records retain an unavailable worktree
        # path but carry the same explicit decoder digest as a source already
        # sealed earlier in this graph.  Bind that edge by the declared
        # content identity, never by basename or ``latest`` discovery.  The
        # candidate must already be present in this closure and its source
        # must exist; otherwise the missing path remains a hard failure.
        if sha is not None and not path.exists():
            candidates = []
            for candidate_key, candidate in self.all_items.items():
                if candidate_key == key or candidate.get("source_sha256") != sha:
                    continue
                candidate_path = Path(candidate_key)
                if candidate_path.exists() and not candidate_path.is_symlink():
                    candidate_stat = candidate.get("source_stat_provenance")
                    if isinstance(candidate_stat, Mapping):
                        candidates.append((candidate_key, candidate, dict(candidate_stat)))
            if candidates:
                # Multiple copies are acceptable only when they describe the
                # same bounded identity.  Pick the stable lexical source and
                # retain every provenance edge; no path search is performed.
                candidates.sort(key=lambda item: item[0])
                candidate_key, candidate, candidate_stat = candidates[0]
                self.edges.append({
                    "pointer": pointer,
                    "source_path": key,
                    "source_binding_path": candidate_key,
                    "source_sha256": sha,
                    "classification": "declared_sha_alias_missing_source",
                })
                self.alias_by_target[key] = candidate_key
                return candidate
        if sha is None:
            if _is_explicit_unknown(parent, pointer.split("/")) or _is_generated(pointer.split("/"), parent):
                entry = {"source_path_provenance": key, "logical_role": "unresolved_or_generated_observation",
                         "source_sha256": None, "source_stat_provenance": None,
                         "target_relative_path": None, "deferred_content": True,
                         "placeholder_only": True, "source_kind": "observation"}
                self.discovered[key] = entry
                self.edges.append({"pointer": pointer, "source_path": key,
                                   "classification": "generated_or_explicit_unknown"})
                return entry
            _fail(f"actionable nested path has no declared SHA at {pointer}: {source}")
        if not path.exists():
            declared_stat = _declared_stat(parent) or self.known_stat_by_source.get(key)
            if declared_stat is None:
                _fail(f"missing deferred source has no stat contract at {pointer}: {source}")
            stat = declared_stat
            is_dir = False
        else:
            is_dir = path.is_dir()
            stat = _full_stat(path, f"nested source {pointer}")
            if path.is_symlink():
                _fail(f"nested source is a symlink at {pointer}: {source}")
        if is_dir:
            # V2 needs directory anchors to be target-local, but they are not
            # scientific source bytes.  Preserve the relationship explicitly.
            entry = {"source_path_provenance": key, "logical_role": "nested_directory_anchor",
                     "source_sha256": sha, "source_stat_provenance": stat,
                     "target_relative_path": None, "deferred_content": True,
                     "placeholder_only": True, "source_kind": "directory_anchor"}
            self.discovered[key] = entry
            self.edges.append({"pointer": pointer, "source_path": key,
                               "source_sha256": sha, "classification": "directory_anchor"})
            return entry
        name = path.name if path.name else "source"
        target = f"evidence/recursive/{sha[:16]}-{name}"
        item = {"source_path_provenance": key, "logical_role": f"recursive_v7_{sha[:16]}",
                "source_sha256": sha, "source_stat_provenance": stat,
                "target_relative_path": target,
                "deferred_content": bool(path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".out"}
                                      or stat.get("bytes", 0) > MAX_METADATA_BYTES),
                "placeholder_only": bool(path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".out"}
                                      or stat.get("bytes", 0) > MAX_METADATA_BYTES),
                "source_kind": "deferred_source_placeholder"}
        if computed_metadata_sha:
            item["source_sha256_basis"] = "BUILDER_BOUNDED_METADATA_HASH"
        self.discovered[key] = item
        self.edges.append({"pointer": pointer, "source_path": key, "source_sha256": sha,
                           "classification": _classify(item)})
        if (not item["deferred_content"] and path.suffix.lower() == ".json"
                and stat.get("bytes", 0) <= MAX_METADATA_BYTES):
            self.queue.append(path)
        return item

    def walk(self) -> None:
        while self.queue:
            path = self.queue.pop(0)
            key = os.path.abspath(str(path))
            if key in self.seen:
                continue
            self.seen.add(key)
            item = self.all_items.get(key)
            if item is None or item.get("deferred_content"):
                continue
            if not path.is_file() or path.is_symlink():
                _fail(f"bounded metadata source is not a regular file: {path}")
            if path.stat().st_size > MAX_METADATA_BYTES:
                continue
            self._index_metadata_file(path)
            value = _json(path, f"ROOT242 bounded metadata {path}")
            self._walk_value(value, ())

    def _walk_value(self, value: Any, parts: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                text = str(key)
                if text == "path" and isinstance(child, str) and child.startswith("/"):
                    pointer = _pointer(parts + (text,))
                    if _is_dataset_pointer(parts):
                        self.edges.append({"pointer": pointer, "source_path": child,
                                           "classification": "dataset_pointer_not_filesystem_path"})
                    elif _in_context(parts, REFERENCE_ONLY_CONTEXTS):
                        self.edges.append({"pointer": pointer, "source_path": child,
                                           "classification": "reference_only_not_opened"})
                    elif _in_context(parts, ADMIN_REFERENCE_CONTEXTS):
                        self.edges.append({"pointer": pointer, "source_path": child,
                                           "classification": "administrative_lease_reference_not_opened"})
                    elif _is_admin_ledger_edge(value, child):
                        self.edges.append({"pointer": pointer, "source_path": child,
                                           "classification": "administrative_live_ledger_reference_not_opened"})
                    elif _in_context(parts, PROVENANCE_CONTEXTS):
                        self.edges.append({"pointer": pointer, "source_path": child,
                                           "classification": "provenance_only_not_opened"})
                    elif _is_generated(parts, value):
                        self.edges.append({"pointer": pointer, "source_path": child,
                                           "classification": "generated_output_anchor"})
                    else:
                        self._add_discovered(Path(child).expanduser(), value, pointer)
                else:
                    self._walk_value(child, parts + (text,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._walk_value(child, parts + (str(index),))

    def report(self) -> tuple[list[dict[str, Any]], dict[str, int], str]:
        entries = []
        counts: dict[str, int] = {}
        for key, item in sorted(self.all_items.items()):
            classification = _classify(item, active_ledger=self._active_ledger(item))
            entry = _make_entry(item, classification)
            entries.append(entry)
            counts[classification] = counts.get(classification, 0) + 1
        edge_sha = hashlib.sha256(json.dumps(self.edges, sort_keys=True,
                                              separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        return entries, counts, edge_sha


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = _json(path, "ROOT230 V5 copy manifest")
    if manifest.get("schema") != "ds02.stage2.f2-typed-only-portable-dependency-manifest.v1":
        _fail("base manifest is not ROOT230 V5 typed-only manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        _fail("base manifest has no artifacts")
    declared = manifest.get("sha256")
    if not isinstance(declared, str) or len(declared) != 64 or set(declared) - HEX64:
        _fail("base manifest has no canonical SHA")
    return manifest


def _load_contract(path: Path) -> dict[str, Any]:
    contract = _json(path, "ROOT230 V5 metadata contract")
    if contract.get("schema") != CONTRACT_SCHEMA:
        _fail("base metadata contract schema differs")
    if contract.get("status") not in {"READY_FOR_PARENT_STAGE2_GUARD", "READY_FOR_PARENT_GUARD"}:
        _fail("base metadata contract is not a parent-ready ROOT213 contract")
    if contract.get("source_content_read_by_builder") is not False:
        _fail("base metadata contract has an open source-content boundary")
    return contract


def _load_outer(path: Path) -> dict[str, Any]:
    request = _json(path, "ROOT230 V5 parent wrapper")
    if request.get("schema") != REQUEST_SCHEMA:
        _fail("base parent wrapper schema differs")
    return request


def _stat_binding(path: Path, role: str, *, allow_symlink: bool = False) -> dict[str, Any]:
    return {"path": str(path), "file_sha256": _sha_file(path, role),
            "stat": _full_stat(path, role, allow_symlink=allow_symlink)}


def _literal_interpreter() -> dict[str, Any]:
    # Keep argv[0] literal.  The resolved binary is provenance only; using it
    # as argv[0] loses the venv ABI and reproduces the system h5py/numpy error.
    invocation = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
    cfg = invocation.parent.parent / "pyvenv.cfg"
    if not invocation.is_symlink() and not invocation.is_file():
        _fail(f"literal project interpreter is unavailable: {invocation}")
    if not cfg.is_file():
        _fail(f"literal project pyvenv.cfg is unavailable: {cfg}")
    resolved = invocation.resolve()
    result = {
        "invocation_path": str(invocation), "argv0_literal": True,
        "do_not_resolve_argv0": True, "resolved_path_provenance": str(resolved),
        "resolved_binary_sha256": _sha_file(resolved, "resolved interpreter binary",
                                             maximum=64 * 1024 * 1024),
        "pyvenv_cfg": _stat_binding(cfg, "project pyvenv.cfg"),
    }
    return result


def _set_nested(value: Any, replacements: Mapping[str, str], parts: tuple[str, ...] = ()) -> Any:
    """Rebase only fresh namespace anchors in a contract clone.

    Source paths and historical provenance remain byte/path evidence.  This
    helper intentionally changes no arbitrary nested source path.
    """
    if isinstance(value, Mapping):
        result = {}
        for key, child in value.items():
            text = str(key)
            if isinstance(child, str) and child.startswith("/") and text in replacements:
                result[key] = replacements[text]
            else:
                result[key] = _set_nested(child, replacements, parts + (text,))
        return result
    if isinstance(value, list):
        return [_set_nested(child, replacements, parts + (str(i),))
                for i, child in enumerate(value)]
    return value


def _output_forbidden(path: Path, old_paths: Iterable[str]) -> None:
    if path.exists() or path.is_symlink():
        _fail(f"fresh ROOT242 namespace already exists: {path}")
    text = str(path)
    for old in old_paths:
        if old and old in text:
            _fail(f"fresh ROOT242 namespace reuses an old target namespace: {path}")


def build_request(*, base_contract: Path | str, base_request: Path | str,
                  manifest: Path | str, output_contract: Path | str,
                  output_request: Path | str, fresh_root: Path | str,
                  home_receipt: Path | str, case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str) -> dict[str, Any]:
    contract_path = _abs(str(base_contract), "base ROOT213 contract")
    outer_path = _abs(str(base_request), "base ROOT230 parent wrapper")
    manifest_path = _abs(str(manifest), "ROOT230 V5 manifest")
    out_contract = _abs(str(output_contract), "ROOT242 metadata contract output")
    out_request = _abs(str(output_request), "ROOT242 parent request output")
    if out_contract.exists() or out_request.exists():
        _fail("ROOT242 outputs already exist; refusing overwrite")
    contract = _load_contract(contract_path)
    outer = _load_outer(outer_path)
    frozen_manifest = _load_manifest(manifest_path)
    root = _abs(str(fresh_root), "ROOT242 external fresh root")
    receipt = _abs(str(home_receipt), "ROOT242 Home receipt")
    old_namespaces = {
        "ROOT230", "ROOT213_PORTABLE_TYPED", "STAGE2_F2_ROOT213_PORTABLE_TYPED_PARENT",
    }
    _output_forbidden(root, old_namespaces)
    _output_forbidden(receipt, old_namespaces)
    if not case_id or "ROOT242" not in case_id:
        _fail("case_id must identify ROOT242")
    if not attempt_id or "root-forward-242-001" not in attempt_id:
        _fail("attempt_id must retain root-forward-242-001")

    closure = _Closure(frozen_manifest["artifacts"], manifest_path.parent)
    closure.walk()
    entries, class_counts, edge_sha = closure.report()
    all_items = closure.all_items
    active_ledger_keys = {
        key for key, item in all_items.items() if closure._active_ledger(item)
    }
    unique = {key: item for key, item in all_items.items()
              if item.get("source_sha256") and item.get("source_stat_provenance")
              and key not in active_ledger_keys and item.get("target_relative_path")}
    logical_bytes = sum(int(item["source_stat_provenance"].get("bytes", 0))
                        for item in unique.values())
    deferred_bytes = sum(int(item["source_stat_provenance"].get("bytes", 0))
                         for item in unique.values() if item.get("deferred_content"))
    metadata_bytes = logical_bytes - deferred_bytes
    report_roles = sum(1 for key, item in unique.items()
                       if _classify(item, active_ledger=key in active_ledger_keys)
                       == "sealed_report_or_receipt")
    if report_roles == 0:
        _fail("source closure has no sealed report/receipt roles")
    if not any(_classify(item, active_ledger=key in active_ledger_keys)
               == "historical_ledger_snapshot" for key, item in unique.items()):
        # The current ROOT230 graph may not have an archived ledger.  Record
        # the negative explicitly; an active ledger is still never copied.
        historical_ledger_status = "ABSENT_NO_HISTORICAL_LEDGER_ROLE"
    else:
        historical_ledger_status = "SEALED_CONTENT_ROLE_PRESENT"

    primary_root = _abs(str(primary_scripts_root), "primary scripts root")
    primary_scripts = primary_root / "lagrangian-fluid-lab" / "scripts"
    executor = primary_scripts / "ds_data02_stage2_f2_root213_portable_typed_executor_v7.py"
    runtime = primary_scripts / "ds_data02_stage2_f2_typed_only_portable_rebind_v7.py"
    v2 = primary_scripts / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
    runtime_v6 = primary_scripts / "ds_data02_runtime_v6.py"
    for path, label in ((executor, "primary V7 executor"), (runtime, "primary V7 runtime"),
                        (v2, "primary V2 runtime"), (runtime_v6, "primary runtime_v6")):
        if not path.is_file() or path.is_symlink():
            _fail(f"{label} is not a regular primary source: {path}")

    interpreter = _literal_interpreter()
    # The custom ROOT213 contract is cloned only for its immutable source
    # evidence.  Rebase contract metadata/output anchors and the strict V7
    # interface; do not rewrite arbitrary nested historical input paths.
    new_contract = json.loads(json.dumps(contract))
    new_contract["case_id"] = case_id
    new_contract["attempt_id"] = attempt_id
    new_contract["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    new_contract["portable_cold_replay_credit"] = "NOT_CLAIMED"
    new_contract["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    new_contract["quality"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    new_contract["ledger_mutated"] = False
    new_contract["source_content_read_by_builder"] = False
    relocation = dict(new_contract.get("relocation") or {})
    relocation.update({
        "fresh_output_root": str(root), "target_runtime_root": str(root / "runtime"),
        "target_evidence_root": str(root / "evidence"),
        "target_product_root": str(root / "products"),
        "target_home_receipt_path": str(receipt),
        "source_provenance_only": True, "original_absolute_path_fallback": "REJECT",
        "symlink_targets": "REJECT", "source_inode_mtime_equivalence": "NOT_CLAIMED",
    })
    new_contract["relocation"] = relocation
    runtime_closure = dict(new_contract.get("runtime_closure") or {})
    runtime_closure.update({
        "schema": "ds02.stage2.f2-root242-v7-runtime-closure.v1",
        "import_mode": "PRIVATE_COPIED_RUNTIME_EXPLICIT_BOOTSTRAP",
        "original_worktree_fallback": "REJECT",
        "literal_interpreter": interpreter,
        "preferred_entrypoint": str(executor),
        "roles": [
            {"role": "v7_executor", **_stat_binding(executor, "primary V7 executor")},
            {"role": "v7_rebind_runtime", **_stat_binding(runtime, "primary V7 runtime")},
            {"role": "v2_rebind_runtime", **_stat_binding(v2, "primary V2 runtime")},
            {"role": "runtime_v6_import", **_stat_binding(runtime_v6, "primary runtime_v6")},
        ],
    })
    new_contract["runtime_closure"] = runtime_closure
    new_contract["root242_source_binding"] = {
        "schema": HANDOFF_SCHEMA, "manifest_schema": frozen_manifest["schema"],
        "manifest_path": str(manifest_path), "manifest_file_sha256": _sha_file(manifest_path, "V5 manifest"),
        "manifest_declared_canonical_sha256": frozen_manifest["sha256"],
        "manifest_artifact_count": len(frozen_manifest["artifacts"]),
        "recursive_discovery_count": len(closure.discovered),
        "recursive_edge_count": len(closure.edges), "recursive_edges_sha256": edge_sha,
        "exact_path_sha_conflict_count": len(closure.sha_conflicts),
        "exact_path_sha_conflicts_sha256": hashlib.sha256(json.dumps(
            closure.sha_conflicts, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True).encode("utf-8")).hexdigest(),
        "role_counts": class_counts,
        "input_closure": {
            "report_receipt_policy": "ACTIONABLE_IF_CONSUMED; SEALED_SHA_STAT_AND_TARGET_COPY_REQUIRED",
            "nested_request_policy": "RECURSE_ALL_ACTIONABLE_JSON_EDGES",
            "historical_provenance_policy": "PROVENANCE_ONLY_ONLY_WHEN_NOT_CONSUMED",
            "historical_ledger_policy": historical_ledger_status,
            "active_ledger_policy": "ADMIN_REFERENCE_ONLY; OUTER_PARENT_MUTATES_ONE_SHARED_LEDGER",
            "unknown_or_missing_sha": "REJECT_UNLESS_EXPLICIT_GENERATED_OR_UNKNOWN_OBSERVATION",
            "original_path_fallback": "REJECT",
        },
        "roles": entries,
    }
    new_contract["v2_interface"] = {
        "schema": "ds02.stage2.f2-root242-v7-interface.v1",
        "source_script": str(executor), "source_script_sha256": _sha_file(executor, "V7 executor"),
        "v7_runtime_script": str(runtime), "v7_runtime_sha256": _sha_file(runtime, "V7 runtime"),
        "v2_script": str(v2), "v2_script_sha256": _sha_file(v2, "V2 runtime"),
        "literal_python": interpreter["invocation_path"],
        "pyvenv_cfg": interpreter["pyvenv_cfg"]["path"],
        "command_template": [interpreter["invocation_path"], "-B", "-I", "-c",
                              "import os,sys,json;sys.path.insert(0,sys.argv[1]);from ds_data02_stage2_f2_root213_portable_typed_executor_v7 import run;r=run(request_path=sys.argv[2],output_root=sys.argv[3],parent_pid=os.getppid(),max_wall_seconds=900);print(json.dumps(r,sort_keys=True))",
                              str(primary_scripts), str(out_contract), str(root)],
        "parent_reservation_before_source_hash_or_payload_read": True,
        "max_wall_seconds": 900, "cpu_threads": 1, "max_memory_bytes": 16 * 1024**3,
        "no_h5_bi4_native_read_by_source_builder": True,
        "typed_only_result_read_after_reservation_bytes": next(
            (int(item["source_stat_provenance"].get("bytes", 0)) for key, item in unique.items()
             if "v16_result" in str(item.get("logical_role", ""))), 0),
    }
    new_contract["sha256"] = _canonical(new_contract)
    # The inner contract is itself one of the outer request's static inputs,
    # but it does not exist until this build completes.  Compute the exact
    # bytes that will be written so the outer input binding can be assembled
    # without trying to stat a not-yet-created file.
    contract_text = json.dumps(new_contract, indent=2, sort_keys=True,
                               ensure_ascii=True, allow_nan=False) + "\n"
    contract_file_sha256 = hashlib.sha256(contract_text.encode("utf-8")).hexdigest()

    # Outer parent wrapper.  It is deliberately a fresh ds02.request.v1
    # wrapper; the inner custom contract is the file passed to V7 after the
    # parent reservation.  The source paths are declared from the frozen V5
    # manifest and are not copied/read at this stage.
    new_outer = json.loads(json.dumps(outer))
    new_outer.update({
        "case_id": case_id, "attempt_id": attempt_id,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900,
        "max_memory_bytes": 16 * 1024**3,
        "estimated_storage_bytes": 12 * 1024**3,
        "estimated_hdf5_read_bytes": 0,
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_result_JSON_read_bytes": int(new_contract["v2_interface"]["typed_only_result_read_after_reservation_bytes"]),
        "estimated_deferred_read_bytes": int(new_contract["v2_interface"]["typed_only_result_read_after_reservation_bytes"]),
        "cwd": str(primary_root / "lagrangian-fluid-lab"),
        "worktree_root": str(primary_root),
        "launch_allowed": True, "execution_allowed": True,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "command": new_contract["v2_interface"]["command_template"],
        "root213_metadata_contract": {"path": str(out_contract), "sha256": new_contract["sha256"]},
        "storage_scope": {
            "external_filesystem": str(root), "external_reservation_bytes": 12 * 1024**3,
            "home_receipt_path": str(receipt), "home_reservation_bytes": 4 * 1024**3,
            "home_receipt_reserved_bytes": 512 * 1024**2,
            "source_logical_bytes_excluding_active_ledger": logical_bytes,
            "deferred_source_logical_bytes": deferred_bytes,
            "bounded_metadata_and_runtime_bytes": metadata_bytes,
            "parent_atomic_same_ledger_reservation": True,
            "parent_ledger_owner": "OUTER_PARENT_ONLY",
            "source_manifest_apparent_bytes": logical_bytes,
            "sparse_placeholders_accounted_by_logical_st_size": True,
        },
        "scope": {
            "no_raw_H5_BI4_read_by_builder": True,
            "model_invoked": False, "cfd_invoked": False,
            "original_path_fallback": "REJECT",
            "cold_replay_credit": "NOT_CLAIMED",
            "source_only_probe_is_not_reserved_execution_or_result_credit": True,
        },
        "interpreter_binding": interpreter,
        "root242_v7_source_binding": {
            "path": str(out_contract), "sha256": new_contract["sha256"],
            "manifest_path": str(manifest_path),
            "manifest_file_sha256": _sha_file(manifest_path, "V5 manifest"),
            "manifest_declared_canonical_sha256": frozen_manifest["sha256"],
            "role_counts": class_counts, "recursive_edges_sha256": edge_sha,
            "metadata_only_builder": True, "parent_after_reservation_copy_and_trace": True,
            "exact_path_sha_conflict_count": len(closure.sha_conflicts),
        },
        "root_forward_provenance": {
            "source_request": str(outer_path), "source_request_sha256": _sha_file(outer_path, "V5 wrapper"),
            "source_manifest": str(manifest_path), "source_manifest_sha256": _sha_file(manifest_path, "V5 manifest"),
            "source_contract": str(contract_path), "source_contract_sha256": _sha_file(contract_path, "V5 contract"),
            "actual_launch_git_receipt_required": True,
            "os_open_trace_required": True,
            "old_root_poison_check_required": True,
            "H5_BI4_read_by_builder": False, "large_existing_result_JSON_rehashed_by_builder": False,
            "scientific_qualification": "UNKNOWN",
        },
    })
    # Parent input closure follows the frozen manifest.  The live parent
    # ledger is intentionally absent from this scientific copy list; its
    # pre-reservation SHA/stat is retained in the binding as admin evidence.
    input_files: list[str] = []
    input_sha: dict[str, str] = {}
    deferred_records: list[dict[str, Any]] = []
    for key, item in sorted(unique.items()):
        source = str(item["source_path_provenance"])
        if key in active_ledger_keys:
            continue
        input_files.append(source)
        input_sha[source] = str(item["source_sha256"])
        if item.get("deferred_content"):
            source_stat = dict(item.get("source_stat_provenance") or {})
            deferred_records.append({
                "path": source, "role": item.get("logical_role"),
                "bytes": int(source_stat.get("bytes", 0)), "sha256": item["source_sha256"],
                **{field: source_stat[field] for field in FULL_STAT if field in source_stat},
                "stat_only_placeholder": True,
                "content_read_after_reservation": source.endswith("v16-reconstructed-label-result-v2.json"),
            })
    input_files.extend([str(out_contract), str(manifest_path), str(executor), str(runtime), str(v2), str(runtime_v6)])
    for source in (str(out_contract), str(manifest_path), str(executor), str(runtime), str(v2), str(runtime_v6)):
        target = Path(source)
        input_sha[source] = (
            contract_file_sha256 if source == str(out_contract)
            else _sha_file(target, f"source binding {source}")
        )
    new_outer["input_files"] = input_files
    new_outer["input_sha256"] = input_sha
    new_outer["deferred_input_records"] = deferred_records
    new_outer["deferred_input_files"] = [entry["path"] for entry in deferred_records]
    new_outer["deferred_input_sha256"] = {entry["path"]: entry["sha256"] for entry in deferred_records}
    # Keep the large role table in the sealed inner contract.  The outer
    # parent request carries an exact pointer/digest and a deterministic
    # summary instead of duplicating several megabytes of role rows.
    roles_digest = hashlib.sha256(json.dumps(
        entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()
    new_outer["source_only_expected_copy_roles"] = {
        "contract_path": str(out_contract),
        "contract_sha256": new_contract["sha256"],
        "role_count": len(entries),
        "roles_sha256": roles_digest,
        "manifest_artifact_count": len(frozen_manifest["artifacts"]),
        "metadata_only_builder": True,
    }
    new_outer["sha256"] = _canonical(new_outer)

    out_contract.parent.mkdir(parents=True, exist_ok=True)
    out_request.parent.mkdir(parents=True, exist_ok=True)
    if out_contract.exists() or out_request.exists():
        _fail("ROOT242 output appeared during build; refusing overwrite")
    out_contract.write_text(contract_text, encoding="utf-8")
    out_request.write_text(json.dumps(new_outer, indent=2, sort_keys=True,
                                      ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return {
        "schema": HANDOFF_SCHEMA, "status": "READY_FOR_PARENT_STAGE2_GUARD_V7_SOURCE_ONLY",
        "contract": {"path": str(out_contract), "file_sha256": _sha_file(out_contract, "ROOT242 contract")},
        "request": {"path": str(out_request), "file_sha256": _sha_file(out_request, "ROOT242 request"),
                    "canonical_sha256": new_outer["sha256"]},
        "manifest": {"path": str(manifest_path), "file_sha256": _sha_file(manifest_path, "V5 manifest"),
                      "declared_canonical_sha256": frozen_manifest["sha256"],
                      "artifact_count": len(frozen_manifest["artifacts"])},
            "recursive": {"discovered_count": len(closure.discovered), "edge_count": len(closure.edges),
                       "edges_sha256": edge_sha, "role_counts": class_counts,
                       "exact_path_sha_conflict_count": len(closure.sha_conflicts),
                       "exact_path_sha_conflicts_sha256": hashlib.sha256(json.dumps(
                           closure.sha_conflicts, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()},
        "storage": {"logical_source_bytes": logical_bytes, "deferred_source_bytes": deferred_bytes,
                     "metadata_bytes": metadata_bytes, "external_reservation_bytes": 12 * 1024**3,
                     "home_reservation_bytes": 4 * 1024**3, "home_receipt_bytes": 512 * 1024**2},
        "payload_read": False, "ledger_mutated": False, "launch_performed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("base-contract", "base-request", "manifest", "output-contract",
                 "output-request", "fresh-root", "home-receipt", "primary-scripts-root"):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--contract", type=Path, required=True)
    return parser


def validate(*, request: Path | str, contract: Path | str) -> dict[str, Any]:
    request_path = _abs(str(request), "ROOT242 request")
    contract_path = _abs(str(contract), "ROOT242 contract")
    outer = _load_outer(request_path)
    inner = _load_contract(contract_path)
    if outer.get("schema") != REQUEST_SCHEMA:
        _fail("ROOT242 request schema differs")
    if outer.get("root213_metadata_contract", {}).get("path") != str(contract_path):
        _fail("ROOT242 request does not bind the exact contract path")
    if outer.get("root213_metadata_contract", {}).get("sha256") != inner.get("sha256"):
        _fail("ROOT242 request/contract SHA binding differs")
    if outer.get("sha256") != _canonical(outer):
        _fail("ROOT242 request canonical SHA differs")
    if inner.get("schema") != CONTRACT_SCHEMA or inner.get("sha256") != _canonical(inner):
        _fail("ROOT242 contract schema/canonical SHA differs")
    if inner.get("source_content_read_by_builder") is not False:
        _fail("ROOT242 contract source-content boundary is open")
    interface = inner.get("v2_interface")
    if not isinstance(interface, Mapping) or interface.get("parent_reservation_before_source_hash_or_payload_read") is not True:
        _fail("ROOT242 contract lacks parent reservation boundary")
    closure = inner.get("root242_source_binding")
    if not isinstance(closure, Mapping) or closure.get("input_closure", {}).get("original_path_fallback") != "REJECT":
        _fail("ROOT242 source closure is not strict")
    scope = outer.get("scope")
    if not isinstance(scope, Mapping) or scope.get("original_path_fallback") != "REJECT":
        _fail("ROOT242 outer scope permits original fallback")
    return {"schema": HANDOFF_SCHEMA, "status": "ROOT242_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": _sha_file(request_path, "ROOT242 request"),
                        "canonical_sha256": outer["sha256"]},
            "contract": {"path": str(contract_path), "file_sha256": _sha_file(contract_path, "ROOT242 contract"),
                         "canonical_sha256": inner["sha256"]},
            "payload_read": False, "ledger_mutated": False, "launch_performed": False,
            "os_open_trace_required": True, "old_root_poison_check_required": True}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(base_contract=args.base_contract, base_request=args.base_request,
                                  manifest=args.manifest, output_contract=args.output_contract,
                                  output_request=args.output_request, fresh_root=args.fresh_root,
                                  home_receipt=args.home_receipt, case_id=args.case_id,
                                  attempt_id=args.attempt_id, primary_scripts_root=args.primary_scripts_root)
        else:
            value = validate(request=args.request, contract=args.contract)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242SourceError, OSError, ValueError, KeyError) as error:
        print(f"ROOT242 V7 source request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
