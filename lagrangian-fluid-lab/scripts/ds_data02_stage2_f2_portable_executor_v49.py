#!/usr/bin/env python3
"""Forward the V48 portable request onto the real root source closure.

V48's copied bundle was never reached: its overlay still contained fourteen
consumer-worktree paths while the V48 request's ``source_entries`` had already
been rebound to the root worktree.  V34 checks the overlay's original paths
against that exact request closure, so a byte-identical source at another path
was correctly rejected.  This forward builder repairs only that metadata
alias, using a unique ``(declared SHA-256, declared byte count)`` match in the
same immutable request.  It does not hash or open raw BI4/HDF5 payloads.

The actionable ``v2_worker`` entry is also rebound to the V3 scratch wrapper.
The immutable V2 worker remains in ``runtime_sources`` and is loaded by the
wrapper from the copied runtime.  Thus the source closure contains both the
scientific worker and the additive scratch policy, without changing a
consumed request or relying on a source worktree fallback.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
OVERLAY_SCHEMA = "ds02.stage2.f2-native-raw-portable-overlay.v5"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v49-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 8 * 1024 * 1024


class PortableV49Error(RuntimeError):
    """Raised when V49 cannot be safely rebound to the root closure."""


def _canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV49Error(f"{name} must be an absolute path")
    return Path(value).expanduser().resolve()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise PortableV49Error(f"{name} must be a lowercase SHA-256")
    return value


def _load_json(path: Path, name: str) -> dict[str, Any]:
    path = _path(str(path), name)
    stat = path.stat()
    if stat.st_size > MAX_METADATA_BYTES:
        raise PortableV49Error(f"{name} exceeds metadata-only size bound: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV49Error(f"cannot read {name}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV49Error(f"{name} must be a JSON object")
    return value


def _new_output(path: Path, name: str) -> Path:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise PortableV49Error(f"refusing existing {name}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_new(path: Path, value: Mapping[str, Any], name: str) -> Path:
    path = _new_output(path, name)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True)
        stream.write("\n")
    return path


def _stat_contract(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino),
        "st_mode": int(stat.st_mode), "st_nlink": int(stat.st_nlink),
        "st_uid": int(stat.st_uid), "st_gid": int(stat.st_gid),
        "st_size": int(stat.st_size), "st_mtime_ns": int(stat.st_mtime_ns),
        "mode_bits": int(stat.st_mode & 0o777),
    }


def _source_index(request: Mapping[str, Any]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    entries = request.get("source_entries")
    if not isinstance(entries, list) or not entries:
        raise PortableV49Error("V48 request.source_entries is missing")
    index: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for number, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise PortableV49Error(f"source_entries[{number}] is malformed")
        role = raw.get("role")
        path = _path(raw.get("path"), f"source_entries[{number}].path")
        expected = _sha(raw.get("sha256"), f"source_entries[{number}].sha256")
        try:
            size = int(raw.get("bytes", -1))
        except (TypeError, ValueError) as error:
            raise PortableV49Error(f"source_entries[{number}].bytes is invalid") from error
        if not isinstance(role, str) or not role or size < 0:
            raise PortableV49Error(f"source_entries[{number}] role/bytes is invalid")
        if not path.is_file():
            raise PortableV49Error(f"declared root source is missing: {path}")
        if path.stat().st_size != size:
            raise PortableV49Error(f"declared root source byte stat differs: {path}")
        index.setdefault((expected, size), []).append(dict(raw))
    return index


def _runtime_bindings(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate the small runtime closure without reading payload files."""
    values = request.get("runtime_sources")
    if values is None:
        return []
    if not isinstance(values, list):
        raise PortableV49Error("V48 runtime_sources must be a list")
    result: list[dict[str, Any]] = []
    for number, raw in enumerate(values):
        if not isinstance(raw, Mapping):
            raise PortableV49Error(f"runtime_sources[{number}] is malformed")
        path = _path(raw.get("path"), f"runtime_sources[{number}].path")
        digest = _sha(raw.get("sha256"), f"runtime_sources[{number}].sha256")
        try:
            size = int(raw.get("bytes", -1))
        except (TypeError, ValueError) as error:
            raise PortableV49Error(f"runtime_sources[{number}].bytes is invalid") from error
        if not path.is_file() or path.stat().st_size != size:
            raise PortableV49Error(f"runtime source stat differs: {path}")
        result.append({"role": str(raw.get("role", "")), "path": str(path),
                       "sha256": digest, "bytes": size,
                       "mode_bits": int(raw.get("mode_bits", path.stat().st_mode & 0o777))})
    return result


def _role_compatible(overlay_role: Any, source_role: Any, old_path: Path,
                     source_path: Path) -> bool:
    if str(overlay_role) == str(source_role):
        return True
    # V37 retained the frozen PartOut binding under the native reconciliation
    # role while the older V5 overlay called the same declared bytes a raw
    # auxiliary.  The filename and identity tuple must agree; this is the
    # only historical role alias accepted by V49.
    return (
        old_path.name == "PartOut_000.obi4" and source_path.name == old_path.name
        and str(source_role) == "v2:native_partout"
        and str(overlay_role) in {"raw_auxiliary:PartOut_000.obi4", "v2:native_partout"}
    )


def _replace_worker_source(request: dict[str, Any], overlay: dict[str, Any], worker: Path,
                           changed: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind the V4 wrapper as the overlay worker, retaining V2 runtime code."""
    worker = worker.expanduser().resolve()
    if not worker.is_file():
        raise PortableV49Error(f"scratch wrapper is missing: {worker}")
    worker_stat = _stat_contract(worker)
    worker_sha = _sha256_file(worker)
    source_entries = request["source_entries"]
    source_values = [x for x in source_entries if isinstance(x, Mapping) and x.get("role") == "v2_worker"]
    if len(source_values) != 1:
        raise PortableV49Error("V48 v2_worker source entry is not unique")
    source = source_values[0]
    old_path = str(source.get("path"))
    old_sha = source.get("sha256")
    old_bytes = int(source.get("bytes", -1))
    source.update({"path": str(worker), "sha256": worker_sha, "bytes": worker_stat["st_size"],
                   "mtime_ns": worker_stat["st_mtime_ns"]})
    for item in overlay.get("entries", []):
        if not isinstance(item, dict) or item.get("role") != "v2_worker":
            continue
        old_overlay_path = str(item.get("original_path"))
        item.update({
            "original_path": str(worker), "expected_sha256": worker_sha,
            "expected_bytes": worker_stat["st_size"],
            "original_mtime_ns": worker_stat["st_mtime_ns"],
            "source_mode_bits": worker_stat["mode_bits"],
            "target_mode_bits": worker_stat["mode_bits"],
            "source_stat_expected": worker_stat,
            "content_hash_status": "PENDING_PARENT_COPY",
        })
        item.pop("target_path", None)
        item.pop("target_bytes", None)
        item.pop("target_mtime_ns", None)
        item.pop("target_sha256", None)
        changed.append({"role": "v2_worker", "old_path": old_overlay_path,
                        "new_path": str(worker), "old_sha256": old_sha,
                        "new_sha256": worker_sha, "reason": "attempt-owned-scratch-wrapper"})
        break
    else:
        raise PortableV49Error("V48 overlay has no v2_worker entry")
    return {
        "previous_wrapper_path": old_path,
        "previous_wrapper_sha256": old_sha,
        "previous_wrapper_bytes": old_bytes,
        "new_wrapper_path": str(worker),
        "new_wrapper_sha256": worker_sha,
        "new_wrapper_bytes": int(worker_stat["st_size"]),
        "wrapper_byte_delta": int(worker_stat["st_size"]) - old_bytes,
    }


def build_forward(*, v48_request: Path | str, v48_overlay: Path | str | None,
                  scratch_worker: Path | str, output_request: Path | str,
                  output_overlay: Path | str, target_root: Path | str,
                  output_root: Path | str) -> dict[str, Any]:
    """Create an additive V49 executor request from V48 metadata."""
    request_path = _path(str(v48_request), "v48_request")
    request = _load_json(request_path, "v48_request")
    if request.get("schema") != V34_SCHEMA:
        raise PortableV49Error("V48 request schema differs")
    prior_forward = request.get("forward_v48")
    if not isinstance(prior_forward, Mapping) or prior_forward.get("schema") != "ds02.stage2.f2-portable-executor-v48-forward.v1":
        raise PortableV49Error("V48 request lacks the consumed V48 forward marker")
    if request.get("sha256") != _canonical_sha(request):
        raise PortableV49Error("V48 request canonical SHA differs")
    bound_overlay = request.get("v5_overlay_template")
    if v48_overlay is None:
        if not isinstance(bound_overlay, Mapping):
            raise PortableV49Error("V48 v5_overlay_template is missing")
        v48_overlay = bound_overlay.get("path")
    overlay_path = _path(str(v48_overlay), "v48_overlay")
    overlay = _load_json(overlay_path, "v48_overlay")
    if overlay.get("schema") != OVERLAY_SCHEMA:
        raise PortableV49Error("V48 overlay schema differs")
    prior_overlay_forward = overlay.get("forward_v48")
    if not isinstance(prior_overlay_forward, Mapping) or prior_overlay_forward.get("schema") != "ds02.stage2.f2-portable-executor-v48-forward.v1":
        raise PortableV49Error("V48 overlay lacks the consumed V48 forward marker")
    if overlay.get("sha256") != _canonical_sha(overlay):
        raise PortableV49Error("V48 overlay canonical SHA differs")
    if not isinstance(bound_overlay, Mapping):
        raise PortableV49Error("V48 request overlay binding is missing")
    if bound_overlay.get("sha256") != _sha256_file(overlay_path):
        raise PortableV49Error("V48 request does not bind the supplied overlay bytes")
    source_index = _source_index(request)
    runtime_bindings = _runtime_bindings(request)

    old_target = request.get("fresh_roots", {}).get("target_root") if isinstance(request.get("fresh_roots"), Mapping) else None
    old_output = request.get("fresh_roots", {}).get("output_root") if isinstance(request.get("fresh_roots"), Mapping) else None
    target = _path(str(target_root), "target_root")
    output = _path(str(output_root), "output_root")
    metadata_output_parent = _path(str(Path(output_request).expanduser().resolve().parent),
                                    "output_request parent")
    if target == output or target == metadata_output_parent or output == metadata_output_parent:
        raise PortableV49Error("V49 target/output roots are not distinct from metadata output")
    if old_target and target == _path(str(old_target), "old target_root"):
        raise PortableV49Error("V49 target reuses the consumed V48 target")
    if old_output and output == _path(str(old_output), "old output_root"):
        raise PortableV49Error("V49 output reuses the consumed V48 output")
    if target.exists() or output.exists():
        raise PortableV49Error("V49 target/output roots must be fresh")

    new_overlay = copy.deepcopy(overlay)
    new_request = copy.deepcopy(request)
    changed: list[dict[str, Any]] = []
    mapped_old_paths: list[str] = []
    mapped_new_paths: list[str] = []
    for number, raw in enumerate(new_overlay.get("entries", [])):
        if not isinstance(raw, dict):
            raise PortableV49Error(f"overlay.entries[{number}] is malformed")
        old = _path(raw.get("original_path"), f"overlay.entries[{number}].original_path")
        expected = _sha(raw.get("expected_sha256"), f"overlay.entries[{number}].expected_sha256")
        try:
            size = int(raw.get("expected_bytes", -1))
        except (TypeError, ValueError) as error:
            raise PortableV49Error(f"overlay.entries[{number}].expected_bytes is invalid") from error
        candidates = source_index.get((expected, size), [])
        compatible = [candidate for candidate in candidates
                      if _role_compatible(raw.get("role"), candidate.get("role"), old,
                                          _path(candidate.get("path"), "source match path"))]
        if len(compatible) != 1:
            raise PortableV49Error(
                f"overlay entry {raw.get('role')!r} has {len(compatible)} compatible source matches"
            )
        candidate = compatible[0]
        new = _path(candidate.get("path"), f"source match {raw.get('role')}")
        stat = _stat_contract(new)
        if stat["st_size"] != size:
            raise PortableV49Error(f"source match byte stat differs for {new}")
        raw["source_path_provenance"] = str(old)
        raw["original_path"] = str(new)
        raw["original_mtime_ns"] = stat["st_mtime_ns"]
        raw["source_mode_bits"] = stat["mode_bits"]
        raw["target_mode_bits"] = stat["mode_bits"]
        raw["source_stat_expected"] = stat
        raw["content_hash_status"] = "PENDING_PARENT_COPY"
        raw.pop("target_path", None)
        raw.pop("target_bytes", None)
        raw.pop("target_mtime_ns", None)
        raw.pop("target_sha256", None)
        mapped_old_paths.append(str(old))
        mapped_new_paths.append(str(new))
        if str(old) != str(new):
            changed.append({"role": raw.get("role"), "old_path": str(old),
                            "new_path": str(new), "sha256": expected,
                            "bytes": size, "reason": "request-closure-source-entry-match"})

    bundle = new_request.get("v5_bundle")
    if not isinstance(bundle, Mapping):
        raise PortableV49Error("V48 v5_bundle binding is missing")
    bundle_path = _path(bundle.get("path"), "v5_bundle.path")
    # This is metadata JSON, not payload.  Keep the overlay's nested bundle
    # provenance coherent with the root q used by V34.
    old_bundle_path = new_overlay.get("bundle", {}).get("path") if isinstance(new_overlay.get("bundle"), Mapping) else None
    if isinstance(new_overlay.get("bundle"), dict):
        new_overlay["bundle"]["provenance_path"] = old_bundle_path
        new_overlay["bundle"]["path"] = str(bundle_path)
        new_overlay["bundle"]["sha256"] = str(bundle.get("sha256"))
        new_overlay["bundle"]["canonical_sha256"] = str(bundle.get("canonical_sha256"))

    wrapper_binding = _replace_worker_source(
        new_request, new_overlay, _path(str(scratch_worker), "scratch_worker"), changed
    )
    preserved_v2: list[dict[str, Any]] = []
    for item in runtime_bindings:
        role = str(item.get("role", ""))
        path_name = Path(str(item.get("path", ""))).name
        if role in {"raw_worker_v2", "runtime/raw_worker_v2", "immutable_raw_worker_v2"} or path_name == "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py":
            preserved_v2.append({"collection": "runtime_sources", **item})
    for item in new_request.get("source_entries", []):
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role", ""))
        path_name = Path(str(item.get("path", ""))).name
        if role in {"raw_worker_v2", "runtime/raw_worker_v2", "immutable_raw_worker_v2"} or (
            path_name == "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py" and role != "v2_worker"
        ):
            preserved_v2.append({
                "collection": "source_entries", "role": role, "path": str(item.get("path")),
                "sha256": item.get("sha256"), "bytes": int(item.get("bytes", -1)),
            })
    declared_copy_items: dict[tuple[str, str, int], dict[str, Any]] = {}
    for collection, values in (("source_entries", new_request.get("source_entries", [])),
                               ("runtime_sources", runtime_bindings)):
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, Mapping):
                continue
            key = (str(item.get("path")), str(item.get("sha256")), int(item.get("bytes", -1)))
            declared_copy_items[key] = {"collection": collection, "path": key[0],
                                        "sha256": key[1], "bytes": key[2]}
    static_copy_bytes = sum(int(item["bytes"]) for item in declared_copy_items.values())
    new_overlay["target_root"] = str(target)
    new_overlay["forbidden_original_prefixes"] = sorted(set(mapped_new_paths))
    new_overlay["target_paths_are_new"] = True
    new_overlay["content_hash_verified"] = False
    new_overlay["status"] = "READY_FOR_V49_PARENT_COPY"
    new_overlay["forward_v49"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request_sha256": request["sha256"],
        "previous_overlay_file_sha256": _sha256_file(overlay_path),
        "source_match_key": "unique declared (expected_sha256, expected_bytes) within V48 source_entries",
        "changed_overlay_entries": len(changed),
        "changed_paths": changed,
        "bundle_path_rebound_to_request": True,
        "content_read_during_build": False,
        "payload_hashes_computed_during_build": False,
        "source_stat_only": True,
        "original_path_fallback": "FORBIDDEN",
        "decoder_scratch": {
            "wrapper_schema": "ds02.stage2.f2-native-raw-to-typed-label-scratch-wrapper.v4",
            "scope": "attempt-owned",
            "per_frame_directory": True,
            "cleanup_after_each_frame": True,
            "default_tmp_forbidden": True,
            "max_live_frame_directories": 1,
            "max_frame_scratch_bytes": 512 * 1024 * 1024,
            "decoder_timeout_seconds": 180.0,
            "byte_guard": "watchdog terminates only owned decoder process group; post-call stat closes polling race",
            "peak_measurement": "regular-file bytes and file count sampled every 0.02s plus post-call stat",
            "cleanup_failure": "terminal failure with per-frame evidence; no silent ignore_errors",
        },
        "wrapper_binding": wrapper_binding,
        "preserved_v2_runtime_bindings": preserved_v2,
        "runtime_static_copy_bytes": sum(int(item.get("bytes", 0)) for item in runtime_bindings),
        "deduplicated_declared_copy_item_count": len(declared_copy_items),
        "static_copy_bytes_after_rebind": static_copy_bytes,
        "content_read_during_build": False,
        "payload_hashes_computed_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    new_overlay["sha256"] = _canonical_sha(new_overlay)
    overlay_out = _write_new(Path(output_overlay), new_overlay, "V49 overlay")
    overlay_file_sha = _sha256_file(overlay_out)

    new_request["request_id"] = f"{request.get('request_id', 'f2-s1-portable-executor')}-v49"
    new_request["fresh_roots"] = {"target_root": str(target), "output_root": str(output)}
    new_request["v5_overlay_template"] = {
        "path": str(overlay_out), "sha256": overlay_file_sha,
        "canonical_sha256": new_overlay["sha256"], "forward_v49": True,
    }
    execution = copy.deepcopy(new_request.get("execution", {}))
    if not isinstance(execution, dict):
        execution = {}
    execution["decoder_scratch"] = copy.deepcopy(new_overlay["forward_v49"]["decoder_scratch"])
    execution["decoder_scratch"]["wrapper_path"] = str(_path(str(scratch_worker), "scratch_worker"))
    execution["original_path_fallback"] = "FORBIDDEN"
    new_request["execution"] = execution
    new_request["status"] = "READY_FOR_PARENT_STAGE2_GUARD_V49"
    new_request["forward_v49"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request_sha256": request["sha256"],
        "previous_overlay_file_sha256": _sha256_file(overlay_path),
        "overlay": {"path": str(overlay_out), "sha256": overlay_file_sha,
                     "canonical_sha256": new_overlay["sha256"]},
        "target_root": str(target), "output_root": str(output),
        "source_path_mapping_count": len(changed),
        "source_path_mapping": changed,
        "v2_scientific_worker_retained_in_runtime_role": "raw_worker_v2",
        "v4_scratch_wrapper_role": "v2_worker",
        "wrapper_binding": wrapper_binding,
        "preserved_v2_runtime_bindings": preserved_v2,
        "runtime_static_copy_bytes": sum(int(item.get("bytes", 0)) for item in runtime_bindings),
        "deduplicated_declared_copy_item_count": len(declared_copy_items),
        "static_copy_bytes_after_rebind": static_copy_bytes,
        "content_read_during_build": False,
        "payload_hashes_computed_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    new_request["limitations"] = list(new_request.get("limitations", [])) + [
        "V49 repairs actionable overlay paths by unique source-entry SHA/byte identity; historical paths remain provenance only.",
        "V49 keeps the immutable V2 scientific worker in its runtime role and uses an additive V4 scratch wrapper as v2_worker.",
        "The V4 wrapper bounds per-frame scratch bytes and decoder callback time, measures peak bytes, and fails on cleanup errors; parent OS strace remains required for C-level BI4/HDF5 access.",
    ]
    new_request["sha256"] = _canonical_sha(new_request)
    request_out = _write_new(Path(output_request), new_request, "V49 request")
    return {
        "schema": FORWARD_SCHEMA,
        "status": "READY_FOR_PARENT_V49_METADATA_GUARD",
        "request": str(request_out), "request_sha256": _sha256_file(request_out),
        "overlay": str(overlay_out), "overlay_sha256": overlay_file_sha,
        "source_path_mapping_count": len(changed), "overlay_entry_count": len(new_overlay["entries"]),
        "content_read": False, "payload_hashes_computed": False,
        "decoder_scratch": new_overlay["forward_v49"]["decoder_scratch"],
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v48-request", type=Path, required=True)
    parser.add_argument("--v48-overlay", type=Path)
    parser.add_argument("--scratch-worker", type=Path, required=True)
    parser.add_argument("--output-request", type=Path, required=True)
    parser.add_argument("--output-overlay", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build_forward(v48_request=args.v48_request, v48_overlay=args.v48_overlay,
                              scratch_worker=args.scratch_worker,
                              output_request=args.output_request, output_overlay=args.output_overlay,
                              target_root=args.target_root, output_root=args.output_root)
    except (OSError, PortableV49Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(value, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
