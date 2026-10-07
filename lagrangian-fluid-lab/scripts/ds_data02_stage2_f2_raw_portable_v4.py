#!/usr/bin/env python3
"""Executable relocation loader for the immutable F2 raw-to-label v3 bundle.

The v3 bundle and its native-v4 evidence remain byte-frozen.  This forward
loader adds the missing executable relocation boundary:

* source roles are copied by a parent guard into a new root;
* every target is content-hashed before an I/O grant;
* CURRENT gets an explicit path-overlay alias so its producer HDF5 binding
  remains exact after relocation;
* all nested v2/v15/v4 actionable paths are rewritten to target paths;
* a Python audit hook rejects source-path fallback, while the request still
  requires a parent OS-level openat/strace trace for HDF5/BI4 C opens.

No command here copies HDF5/BI4 data implicitly.  ``seal-overlay`` and
``run`` are parent-slot operations and refuse an unsealed overlay.  All
outputs are new paths; an existing destination or prior product is rejected.
Qualification remains UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
V3_BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v3"
V4_BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v4"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-label-portable-request.v4"
OVERLAY_SCHEMA = "ds02.stage2.f2-native-raw-portable-overlay.v4"
PREFLIGHT_SCHEMA = "ds02.stage2.f2-native-raw-portable-preflight.v4"
RUN_REPORT_SCHEMA = "ds02.stage2.f2-native-raw-portable-run-report.v4"
HEX64 = set("0123456789abcdef")
PROVENANCE_KEYS = {"original_path", "original_uri", "producer_path", "source_path_provenance"}
PATH_KEYS = {
    "path", "data_root", "raw_root", "trajectory_path", "reference_path",
    "output_root", "worker", "script", "module", "python", "command",
}


class PortableV4Error(RuntimeError):
    """Raised for unsafe relocation, source mismatch, or output reuse."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=_json_default).encode()).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV4Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV4Error(f"JSON object required: {path}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise PortableV4Error(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise PortableV4Error(f"{name} must be a lowercase SHA-256")
    return value


def _safe_relative(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PortableV4Error(f"{name} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PortableV4Error(f"{name} is unsafe: {value!r}")
    return str(path)


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PortableV4Error(f"{role} is missing: {target}")
    return target


def _validate_bundle(bundle: Mapping[str, Any], *, allow_v3: bool = True) -> dict[str, Any]:
    expected_schemas = {V4_BUNDLE_SCHEMA}
    if allow_v3:
        expected_schemas.add(V3_BUNDLE_SCHEMA)
    if bundle.get("schema") not in expected_schemas:
        raise PortableV4Error(f"unsupported raw bundle schema: {bundle.get('schema')!r}")
    if bundle.get("sha256") != canonical_sha(bundle):
        raise PortableV4Error("bundle canonical SHA differs")
    if bundle.get("role") != "DEVELOPMENT" or bundle.get("qualification") != UNKNOWN:
        raise PortableV4Error("bundle must remain development/UNKNOWN")
    bindings = bundle.get("source_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise PortableV4Error("bundle source_bindings are required")
    roles: set[str] = set()
    relatives: set[str] = set()
    for index, item in enumerate(bindings):
        if not isinstance(item, Mapping):
            raise PortableV4Error(f"source binding {index} is malformed")
        role = str(item.get("role", ""))
        if not role or (role in roles and role != "raw_frame_input"):
            raise PortableV4Error(f"source role is missing or duplicated: {role!r}")
        roles.add(role)
        relative = _safe_relative(item.get("bundle_relative_path"), f"source_bindings[{index}].bundle_relative_path")
        if relative in relatives:
            raise PortableV4Error(f"bundle relative path is duplicated: {relative}")
        relatives.add(relative)
        original = item.get("original_path")
        if not isinstance(original, str) or not Path(original).is_absolute():
            raise PortableV4Error(f"source_bindings[{index}].original_path must be absolute")
        _require_sha(item.get("content_sha256"), f"source_bindings[{index}].content_sha256")
        if item.get("replay_actionable") is not True and role in {"v4_request", "immutable_base_v2_request", "reference_typed_hdf5", "raw_frame_input"}:
            raise PortableV4Error(f"actionable source role is not marked replay_actionable: {role}")
    if not roles.intersection({"reference_typed_hdf5"}):
        raise PortableV4Error("bundle lacks the typed reference HDF5 binding")
    return {"bindings": bindings, "roles": roles, "relatives": relatives}


def _record_new_source(path: Path, role: str, relative: str) -> dict[str, Any]:
    path = _require_file(path, role)
    stat = path.stat()
    return {
        "role": role,
        "original_path": str(path),
        "bundle_relative_path": _safe_relative(relative, f"{role}.bundle_relative_path"),
        "bytes": int(stat.st_size),
        "original_mtime_ns": int(stat.st_mtime_ns),
        "content_sha256": sha256_file(path),
        "content_hash_status": "CONTENT_SHA_BOUND_IN_FORWARD_SOURCE",
        "replay_actionable": True,
    }


def build_bundle(parent_bundle_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    parent_path = _require_file(parent_bundle_path, "v3 bundle")
    parent = load_json(parent_path)
    _validate_bundle(parent, allow_v3=False if parent.get("schema") == V4_BUNDLE_SCHEMA else True)
    if parent.get("schema") != V3_BUNDLE_SCHEMA:
        raise PortableV4Error("forward bundle builder requires the immutable v3 bundle")
    bundle = copy.deepcopy(parent)
    bundle["schema"] = V4_BUNDLE_SCHEMA
    bundle["derived_from_v3_bundle_sha256"] = parent["sha256"]
    loader = _record_new_source(SCRIPT_DIR / Path(__file__).name,
                                "portable_loader_v4",
                                "runtime/portable/ds_data02_stage2_f2_raw_portable_v4.py")
    evaluator = _record_new_source(SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v1.py",
                                   "no_model_evaluator_v1",
                                   "runtime/portable/ds_data02_stage2_f2_no_model_evaluator_v1.py")
    roles = {str(item.get("role")) for item in bundle["source_bindings"]}
    if roles.intersection({loader["role"], evaluator["role"]}):
        raise PortableV4Error("forward runtime role already exists in parent bundle")
    bundle["source_bindings"].extend([loader, evaluator])
    portable = dict(bundle.get("portable_overlay", {}))
    portable.update({
        "runtime_source_roles": [loader["role"], evaluator["role"]],
        "relocation_loader": "portable_loader_v4",
        "relocation_aliases_current_catalog": True,
        "nested_actionable_path_rewrite": "all exact paths and raw data-root prefixes in v2/v15/v4 requests",
        "python_open_audit": "enabled in loader; parent OS trace still required for HDF5/BI4 C opens",
        "content_hash_seal": "all target roles must be SHA-256 verified before run",
        "original_path_fallback": "FORBIDDEN",
    })
    bundle["portable_overlay"] = portable
    replay = dict(bundle.get("replay_contract", {}))
    replay.update({
        "portable_entrypoint": "portable_loader_v4 run",
        "relocated_current_alias": "required; preserves original catalog SHA as provenance and records alias SHA",
        "source_runtime_closure": "v3 bindings plus portable_loader_v4 and no_model_evaluator_v1",
        "no_original_path_read": True,
    })
    bundle["replay_contract"] = replay
    bundle["status"] = "READY_FOR_PARENT_PORTABLE_GUARD; V3_NATIVE_TERMINAL_VERIFIED; V4_EXECUTABLE_RELOCATION; DEVELOPMENT_UNKNOWN"
    resource_request = dict(bundle.get("resource_request", {}))
    resource_request.update({
        "portable_loader_runtime_bytes": int(loader["bytes"] + evaluator["bytes"]),
        "portable_postcopy_rehash_required": True,
        "portable_python_audit": "records Python open/open_code; parent strace covers C-level HDF5/BI4 opens",
    })
    bundle["resource_request"] = resource_request
    bundle["sha256"] = canonical_sha(bundle)
    write_new(output_path, bundle)
    return {"path": str(Path(output_path).expanduser().resolve()),
            "sha256": bundle["sha256"], "source_count": len(bundle["source_bindings"]),
            "derived_from_v3": parent["sha256"]}


def build_request(bundle_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    bundle_file = _require_file(bundle_path, "v4 bundle")
    bundle = load_json(bundle_file)
    checked = _validate_bundle(bundle, allow_v3=False)
    if bundle.get("schema") != V4_BUNDLE_SCHEMA:
        raise PortableV4Error("portable v4 request must bind the executable v4 bundle")
    inputs: list[str] = [str(bundle_file)]
    hashes: dict[str, str] = {str(bundle_file): sha256_file(bundle_file)}
    for item in checked["bindings"]:
        path = str(item["original_path"])
        inputs.append(path)
        hashes[path] = item["content_sha256"]
    # Keep input order unique; this is a source closure declaration, not a
    # request to read all inputs before the parent grants the slot.
    unique_inputs = list(dict.fromkeys(inputs))
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-native-raw-to-label-portable-v4-001",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "bundle": {"path": str(bundle_file), "sha256": sha256_file(bundle_file),
                   "canonical_sha256": bundle["sha256"]},
        "input_files": unique_inputs,
        "input_hashes": hashes,
        "loader": {"role": "portable_loader_v4",
                   "path": next(item["original_path"] for item in checked["bindings"] if item["role"] == "portable_loader_v4"),
                   "original_path_fallback": "FORBIDDEN"},
        "execution": {
            "command": [sys.executable, "<portable_loader_v4>", "run", "--bundle", "<relocated-bundle>",
                         "--overlay", "<sealed-overlay>", "--output-dir", "<new-attempt-dir>",
                         "--io-slot-approved", "--rehash-after-copy"],
            "copy_before_run": True,
            "overlay_seal_required": True,
            "rehash_after_copy": True,
            "os_open_audit_required": True,
            "python_audit_scope": "Python open/open_code only; C HDF5/BI4 requires parent strace/openat",
            "original_path_fallback": False,
            "hdf5_or_bi4_read": "parent slot only",
            "no_model_or_cfd": True,
        },
        "overlay_contract": {
            "schema": OVERLAY_SCHEMA,
            "target_paths_are_new": True,
            "every_actionable_role_rebound": True,
            "current_catalog_alias_required": True,
            "content_hash_status": "PARENT_COPY_AND_SEAL_REQUIRED",
        },
        "resource_request": bundle.get("resource_request", {}),
        "case_scope": bundle.get("case_scope", {}),
        "raw_to_label": bundle.get("raw_to_typed_to_label", {}),
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "limitations": [
            "v3 native evidence is immutable parent evidence; this request has not copied or rerun the raw source.",
            "The relocated CURRENT alias changes only its producer path and records original/current alias hashes separately.",
            "Raw-to-label replay remains DEVELOPMENT and all QI/QN/QE UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return {"path": str(Path(output_path).expanduser().resolve()), "sha256": request["sha256"],
            "input_count": len(unique_inputs)}


def _load_overlay(path: Path | str) -> dict[str, Any]:
    overlay = load_json(path)
    if overlay.get("schema") != OVERLAY_SCHEMA:
        raise PortableV4Error("unsupported overlay schema")
    if overlay.get("sha256") != canonical_sha(overlay):
        raise PortableV4Error("overlay canonical SHA differs")
    if overlay.get("original_path_fallback") != "FORBIDDEN":
        raise PortableV4Error("overlay original_path_fallback must be FORBIDDEN")
    entries = overlay.get("entries")
    if not isinstance(entries, list) or not entries:
        raise PortableV4Error("overlay entries are required")
    return overlay


def build_overlay(bundle_path: Path | str, target_root: Path | str, output_path: Path | str) -> dict[str, Any]:
    bundle_file = _require_file(bundle_path, "v4 bundle")
    bundle = load_json(bundle_file)
    checked = _validate_bundle(bundle, allow_v3=False)
    target = Path(target_root).expanduser().resolve()
    if target == bundle_file.parent or target == Path(__file__).resolve().parent:
        raise PortableV4Error("overlay target root cannot be the source/runtime root")
    if target.exists() and not target.is_dir():
        raise PortableV4Error("overlay target root exists but is not a directory")
    entries: list[dict[str, Any]] = []
    target_paths: set[str] = set()
    original_paths: set[str] = set()
    raw_roots: set[str] = set()
    for item in checked["bindings"]:
        original = Path(str(item["original_path"])).expanduser().resolve()
        if not original.is_file():
            raise PortableV4Error(f"source binding is unavailable: {original}")
        relative = _safe_relative(item["bundle_relative_path"], f"{item['role']}.bundle_relative_path")
        destination = (target / relative).resolve()
        if destination == original or not str(destination).startswith(str(target) + os.sep):
            raise PortableV4Error(f"unsafe target mapping for {item['role']}")
        if str(destination) in target_paths or str(original) in original_paths:
            raise PortableV4Error("duplicate overlay path")
        target_paths.add(str(destination))
        original_paths.add(str(original))
        if item["role"] == "raw_frame_input":
            raw_roots.add(str(original.parent))
        entries.append({
            "role": item["role"],
            "bundle_relative_path": relative,
            "original_path": str(original),
            "target_path": str(destination),
            "expected_sha256": item["content_sha256"],
            "expected_bytes": int(item["bytes"]),
            "original_mtime_ns": int(item["original_mtime_ns"]),
            "content_hash_status": "PENDING_PARENT_COPY",
        })
    forbidden = sorted(original_paths | raw_roots)
    overlay: dict[str, Any] = {
        "schema": OVERLAY_SCHEMA,
        "status": "READY_FOR_PARENT_COPY",
        "role": "DEVELOPMENT",
        "qualification": UNKNOWN,
        "bundle": {"path": str(bundle_file), "sha256": sha256_file(bundle_file),
                   "canonical_sha256": bundle["sha256"]},
        "target_root": str(target),
        "entries": entries,
        "target_paths_are_new": True,
        "content_hash_verified": False,
        "original_path_fallback": "FORBIDDEN",
        "original_paths_are_provenance_only": True,
        "forbidden_original_prefixes": forbidden,
        "runtime_allowed_roots": [str(Path(sys.prefix).resolve()), "/usr", "/lib", "/lib64", "/dev", "/proc"],
        "hdf5_bi4_c_open_audit": "parent OS strace/openat required; Python audit hook is complementary",
        "current_catalog_alias_role": "v2:current_catalog",
        "current_catalog_alias_required": True,
        "source_hash_seal": "seal-overlay must verify every expected_sha256 before run",
    }
    overlay["sha256"] = canonical_sha(overlay)
    write_new(output_path, overlay)
    return {"path": str(Path(output_path).expanduser().resolve()), "status": overlay["status"],
            "entry_count": len(entries), "target_root": str(target)}


def preflight_overlay(overlay_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    overlay = _load_overlay(overlay_path)
    target = Path(overlay["target_root"]).expanduser().resolve()
    missing: list[str] = []
    stat_mismatches: list[str] = []
    seen: set[str] = set()
    for item in overlay["entries"]:
        destination = Path(item["target_path"]).expanduser().resolve()
        if str(destination) in seen or not str(destination).startswith(str(target) + os.sep):
            raise PortableV4Error("overlay target paths are duplicated or outside target root")
        seen.add(str(destination))
        for forbidden in overlay.get("forbidden_original_prefixes", []):
            old = Path(forbidden).expanduser().resolve()
            try:
                destination.relative_to(old)
            except ValueError:
                continue
            raise PortableV4Error("overlay target root overlaps forbidden original source prefix")
        if not destination.is_file():
            missing.append(str(destination))
            continue
        stat = destination.stat()
        if stat.st_size != int(item["expected_bytes"]):
            stat_mismatches.append(str(destination))
    if stat_mismatches:
        raise PortableV4Error(f"target byte stats differ: {stat_mismatches[:3]}")
    if missing:
        status = "READY_FOR_PARENT_COPY"
    elif overlay.get("content_hash_verified") is True:
        status = "READY_FOR_IO_SLOT"
    else:
        status = "PENDING_PARENT_CONTENT_HASH_SEAL"
    report = {
        "schema": PREFLIGHT_SCHEMA,
        "status": status,
        "overlay_path": str(Path(overlay_path).expanduser().resolve()),
        "target_root": str(target),
        "entry_count": len(overlay["entries"]),
        "missing_count": len(missing),
        "missing_targets": missing,
        "content_hash_verified": overlay.get("content_hash_verified") is True,
        "hdf5_or_bi4_read": False,
        "original_path_fallback": "FORBIDDEN",
        "qualification": UNKNOWN,
        "model_invoked": False,
    }
    report["sha256"] = canonical_sha(report)
    write_new(output_path, report)
    return report


def seal_overlay(overlay_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    """Hash every copied target and create a new sealed overlay."""
    overlay = _load_overlay(overlay_path)
    started = time.monotonic()
    sealed = copy.deepcopy(overlay)
    total = 0
    for item in sealed["entries"]:
        target = _require_file(item["target_path"], str(item["role"]))
        stat = target.stat()
        if stat.st_size != int(item["expected_bytes"]):
            raise PortableV4Error(f"copied target byte size differs: {target}")
        actual = sha256_file(target)
        if actual != item["expected_sha256"]:
            raise PortableV4Error(f"copied target SHA differs: {target}")
        item["target_bytes"] = int(stat.st_size)
        item["target_mtime_ns"] = int(stat.st_mtime_ns)
        item["target_sha256"] = actual
        item["content_hash_status"] = "VERIFIED_AFTER_COPY"
        total += int(stat.st_size)
    sealed["status"] = "CONTENT_SHA_VERIFIED_AFTER_COPY; READY_FOR_IO_SLOT"
    sealed["content_hash_verified"] = True
    sealed["copy_hash_receipt"] = {
        "entry_count": len(sealed["entries"]), "total_bytes": total,
        "elapsed_seconds": time.monotonic() - started,
        "content_sha256_verified": True,
        "original_mtime_is_provenance_only": True,
    }
    sealed["sha256"] = canonical_sha(sealed)
    write_new(output_path, sealed)
    return {"path": str(Path(output_path).expanduser().resolve()), "status": sealed["status"],
            "entry_count": len(sealed["entries"]), "total_bytes": total,
            "sha256": sealed["sha256"]}


def _path_maps(overlay: Mapping[str, Any]) -> tuple[dict[str, str], list[tuple[str, str]]]:
    exact: dict[str, str] = {}
    prefixes: list[tuple[str, str]] = []
    for item in overlay["entries"]:
        old = str(Path(item["original_path"]).expanduser().resolve())
        new = str(Path(item["target_path"]).expanduser().resolve())
        exact[old] = new
    raw = [item for item in overlay["entries"] if item.get("role") == "raw_frame_input"]
    if raw:
        old_root = str(Path(raw[0]["original_path"]).parent.resolve())
        new_root = str(Path(raw[0]["target_path"]).parent.resolve())
        prefixes.append((old_root, new_root))
    return exact, sorted(prefixes, key=lambda pair: len(pair[0]), reverse=True)


def _replace_path(value: str, exact: Mapping[str, str], prefixes: Sequence[tuple[str, str]]) -> str:
    candidate = str(Path(value).expanduser().resolve()) if value.startswith("/") else value
    if candidate in exact:
        return exact[candidate]
    for old, new in prefixes:
        if candidate == old:
            return new
        if candidate.startswith(old + os.sep):
            return new + candidate[len(old):]
    return value


def _rewrite(value: Any, exact: Mapping[str, str], prefixes: Sequence[tuple[str, str]], *, key: str | None = None) -> Any:
    if isinstance(value, Mapping):
        return {str(name): (item if str(name) in PROVENANCE_KEYS else
                            _rewrite(item, exact, prefixes, key=str(name)))
                for name, item in value.items()}
    if isinstance(value, list):
        return [_rewrite(item, exact, prefixes, key=key) for item in value]
    if isinstance(value, str):
        replaced = _replace_path(value, exact, prefixes)
        if replaced != value:
            return replaced
        # Command strings can contain an exact path as one token.  Replace
        # only known path tokens; provenance strings remain untouched above.
        for old, new in sorted(exact.items(), key=lambda pair: len(pair[0]), reverse=True):
            if old in value and (key in PATH_KEYS or key == "command"):
                value = value.replace(old, new)
        for old, new in prefixes:
            if old in value and (key in PATH_KEYS or key == "command"):
                value = value.replace(old, new)
        return value
    return value


def _entry_by_role(overlay: Mapping[str, Any], role: str) -> dict[str, Any]:
    values = [item for item in overlay["entries"] if item.get("role") == role]
    if len(values) != 1:
        raise PortableV4Error(f"overlay role is not unique: {role}")
    return dict(values[0])


def _write_alias(path: Path, value: Mapping[str, Any]) -> tuple[Path, str]:
    write_new(path, value)
    return path, sha256_file(path)


def _prepare_relocated_requests(overlay: Mapping[str, Any], output_dir: Path) -> tuple[Path, dict[str, Any]]:
    exact, prefixes = _path_maps(overlay)
    v4_source = Path(_entry_by_role(overlay, "v4_request")["target_path"])
    base_source = Path(_entry_by_role(overlay, "immutable_base_v2_request")["target_path"])
    current_source = Path(_entry_by_role(overlay, "v2:current_catalog")["target_path"])
    reference_target = Path(_entry_by_role(overlay, "reference_typed_hdf5")["target_path"])
    v15_entry = _entry_by_role(overlay, "v2:v15_replay_request")
    v15_source = Path(v15_entry["target_path"])
    current = load_json(current_source)
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) <= 78 or not isinstance(cases[78], Mapping):
        raise PortableV4Error("copied CURRENT case row is malformed")
    current_alias = copy.deepcopy(current)
    current_alias["cases"][78]["trajectory"] = dict(current_alias["cases"][78].get("trajectory", {}))
    current_alias["cases"][78]["trajectory"]["path"] = str(reference_target.resolve())
    alias_dir = output_dir / "relocated-runtime"
    alias_dir.mkdir(parents=True, exist_ok=False)
    alias_current_path = alias_dir / "CURRENT336-case78-trajectory-overlay.json"
    alias_current_path, alias_current_sha = _write_alias(alias_current_path, current_alias)
    current_sidecar = {
        "schema": "ds02.stage2.f2-current-catalog-path-overlay.v1",
        "original_catalog_path": str(current_source.resolve()),
        "original_catalog_sha256": _entry_by_role(overlay, "v2:current_catalog")["expected_sha256"],
        "copied_catalog_path": str(current_source.resolve()),
        "copied_catalog_sha256": _entry_by_role(overlay, "v2:current_catalog")["expected_sha256"],
        "alias_path": str(alias_current_path.resolve()),
        "alias_sha256": alias_current_sha,
        "case_index": 78,
        "original_trajectory_path": str(current["cases"][78]["trajectory"]["path"]),
        "relocated_trajectory_path": str(reference_target.resolve()),
        "producer_declared_sha256": current["cases"][78]["trajectory"].get("producer_declared_sha256"),
        "semantic_change": "path overlay only; case identity, shape, producer SHA and all other CURRENT fields preserved",
        "original_path_fallback": "FORBIDDEN",
    }
    current_sidecar_path, _ = _write_alias(alias_dir / "CURRENT336-case78-overlay-sidecar.json", current_sidecar)

    v15 = _rewrite(load_json(v15_source), exact, prefixes)
    if not isinstance(v15, dict):
        raise PortableV4Error("v15 request rewrite failed")
    v15_sources = v15.get("source_files", [])
    for item in v15_sources:
        if isinstance(item, dict) and item.get("role") == "current_catalog":
            item["path"] = str(alias_current_path.resolve())
            item["sha256"] = alias_current_sha
    current_binding = v15.get("current_binding")
    if isinstance(current_binding, dict):
        current_binding["path"] = str(alias_current_path.resolve())
        current_binding["sha256"] = alias_current_sha
        current_binding["binding_status"] = "EXACT_CURRENT_ROW_RELOCATED_PATH_OVERLAY"
    h5 = v15.get("trajectory_h5")
    if isinstance(h5, dict):
        h5["path"] = str(reference_target.resolve())
        stat = reference_target.stat()
        h5["bytes"] = int(stat.st_size)
        h5["mtime_ns"] = int(stat.st_mtime_ns)
    profile = v15.get("observer_profile")
    if isinstance(profile, dict):
        profile["current_binding_sha256"] = alias_current_sha
        profile["source_file_sha256"] = {str(item["role"]): item["sha256"] for item in v15_sources}
        profile["sha256"] = canonical_sha(profile)
    v15_path = alias_dir / "f2-s1-replay-request-v15-relocated.json"
    _, v15_sha = _write_alias(v15_path, v15)

    base = _rewrite(load_json(base_source), exact, prefixes)
    if not isinstance(base, dict):
        raise PortableV4Error("base v2 request rewrite failed")
    base_sources = base.get("source_files", [])
    for item in base_sources:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "current_catalog":
            item["path"] = str(alias_current_path.resolve())
            item["sha256"] = alias_current_sha
        elif item.get("role") == "v15_replay_request":
            item["path"] = str(v15_path.resolve())
            item["sha256"] = v15_sha
    base_current = base.get("current_binding")
    if isinstance(base_current, dict):
        base_current["path"] = str(alias_current_path.resolve())
        base_current["sha256"] = alias_current_sha
        base_current["binding_status"] = "EXACT_CURRENT_ROW_RELOCATED_PATH_OVERLAY"
    base["v15_request"] = v15
    base_path = alias_dir / "f2-s1-native-raw-to-typed-label-request-v2-relocated.json"
    _, base_sha = _write_alias(base_path, base)

    v4 = _rewrite(load_json(v4_source), exact, prefixes)
    if not isinstance(v4, dict):
        raise PortableV4Error("v4 request rewrite failed")
    base_binding = v4.get("base_v2_request")
    if isinstance(base_binding, dict):
        base_binding["path"] = str(base_path.resolve())
        stat = base_path.stat()
        base_binding["bytes"] = int(stat.st_size)
        base_binding["mtime_ns"] = int(stat.st_mtime_ns)
        base_binding["sha256"] = base_sha
    reference = v4.get("reference_typed_hdf5")
    if isinstance(reference, dict):
        reference["path"] = str(reference_target.resolve())
        stat = reference_target.stat()
        reference["bytes"] = int(stat.st_size)
        reference["mtime_ns"] = int(stat.st_mtime_ns)
    modules = v4.get("modules", {})
    if isinstance(modules, dict):
        for item in modules.values():
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                target = Path(item["path"])
                if target.is_file():
                    item["bytes"] = int(target.stat().st_size)
                    item["mtime_ns"] = int(target.stat().st_mtime_ns)
    closure = v4.get("source_closure")
    if isinstance(closure, dict):
        roles = closure.get("raw_v2_source_roles", [])
        if isinstance(roles, list):
            for item in roles:
                if not isinstance(item, dict):
                    continue
                if item.get("role") == "v2:current_catalog":
                    item["path"] = str(alias_current_path.resolve())
                    item["sha256"] = alias_current_sha
                elif item.get("role") == "v2:v15_replay_request":
                    item["path"] = str(v15_path.resolve())
                    item["sha256"] = v15_sha
    wrapper = v4.get("root_canonical_wrapper")
    if isinstance(wrapper, dict):
        identity = wrapper.get("current_identity_binding")
        if isinstance(identity, dict) and isinstance(identity.get("current_catalog"), dict):
            identity["current_catalog"]["path"] = str(alias_current_path.resolve())
            identity["current_catalog"]["sha256"] = alias_current_sha
            identity["current_catalog"]["bytes"] = int(alias_current_path.stat().st_size)
            identity["current_catalog"]["mtime_ns"] = int(alias_current_path.stat().st_mtime_ns)
        wrapper["source_path_policy"] = "all actionable paths target overlay; original paths provenance only; fallback forbidden"
    v4["source_hashes_preverified_by_parent"] = True
    v4["portable_relocation"] = {
        "schema": "ds02.stage2.f2-relocated-native-request.v1",
        "source_bundle_sha256": overlay["bundle"]["canonical_sha256"],
        "original_current_catalog_sha256": current_sidecar["original_catalog_sha256"],
        "relocated_current_catalog_sha256": alias_current_sha,
        "current_alias_sidecar": str(current_sidecar_path.resolve()),
        "original_hdf5_path": _entry_by_role(overlay, "reference_typed_hdf5")["original_path"],
        "relocated_hdf5_path": str(reference_target.resolve()),
        "original_path_fallback": "FORBIDDEN",
        "all_actionable_paths_rebound": True,
        "content_hash_credit": "parent sealed overlay; this request does not suppress source checks",
    }
    v4_path = alias_dir / "f2-s1-native-raw-to-typed-reference-compare-request-v4-relocated.json"
    v4["sha256"] = canonical_sha(v4)
    _, _ = _write_alias(v4_path, v4)
    return v4_path, {"v15": v15_path, "base": base_path, "current_alias": alias_current_path,
                     "current_sidecar": current_sidecar_path, "reference": reference_target}


class _AccessAudit:
    def __init__(self, overlay: Mapping[str, Any], output_root: Path):
        self.overlay = overlay
        self.output_root = output_root.resolve()
        self.events: list[dict[str, Any]] = []
        self.rejected: list[dict[str, Any]] = []
        self.exact, self.prefixes = _path_maps(overlay)
        self.forbidden = [Path(item).expanduser().resolve() for item in overlay.get("forbidden_original_prefixes", [])]
        self.allowed = [Path(overlay["target_root"]).expanduser().resolve(), self.output_root,
                        Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                        Path("/usr"), Path("/lib"), Path("/lib64"), Path("/dev"), Path("/proc")]

    def _path(self, value: Any) -> Path | None:
        if isinstance(value, bytes):
            try:
                value = os.fsdecode(value)
            except UnicodeDecodeError:
                return None
        if not isinstance(value, str) or not value.startswith("/"):
            return None
        return Path(value).expanduser().resolve()

    def _under(self, path: Path, roots: Sequence[Path]) -> bool:
        return any(path == root or root in path.parents for root in roots)

    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        if event not in {"open", "open_code", "os.open"} or not args:
            return
        path = self._path(args[0])
        if path is None:
            return
        record = {"event": event, "path": str(path), "allowed": True}
        if self._under(path, self.forbidden) and not self._under(path, self.allowed):
            record["allowed"] = False
            self.rejected.append(record)
            raise PortableV4Error(f"original source path access rejected: {path}")
        if not self._under(path, self.allowed):
            # Unknown external opens are retained as audit failures.  This
            # prevents a module from silently reaching the old worktree.
            record["allowed"] = False
            self.rejected.append(record)
            raise PortableV4Error(f"unregistered external path access rejected: {path}")
        self.events.append(record)


def run_portable(bundle_path: Path | str, overlay_path: Path | str, output_dir: Path | str,
                 *, io_slot_approved: bool, rehash_after_copy: bool) -> dict[str, Any]:
    if not io_slot_approved:
        raise PortableV4Error("run requires explicit --io-slot-approved")
    bundle = load_json(bundle_path)
    _validate_bundle(bundle, allow_v3=False)
    overlay = _load_overlay(overlay_path)
    if overlay.get("content_hash_verified") is not True:
        raise PortableV4Error("sealed overlay with parent content hashes is required")
    if rehash_after_copy is not True:
        raise PortableV4Error("--rehash-after-copy is required for portable raw replay")
    target = Path(overlay["target_root"]).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise PortableV4Error(f"refusing to reuse existing attempt/output: {output}")
    output.mkdir(parents=True, exist_ok=False)
    # Rehashing is intentionally parent-slot work and proves the copied H5 and
    # all BI4 frames are the declared bytes before the worker opens them.
    seal_receipt = seal_overlay(overlay_path, output / "sealed-overlay-recheck-v4.json")
    sealed_path = output / "sealed-overlay-recheck-v4.json"
    sealed = load_json(sealed_path)
    audit = _AccessAudit(sealed, output)
    sys.addaudithook(audit.hook)
    try:
        relocated_request, aliases = _prepare_relocated_requests(sealed, output)
        worker_path = Path(_entry_by_role(sealed, "compare_worker")["target_path"])
        if not worker_path.is_file():
            raise PortableV4Error(f"relocated compare worker is missing: {worker_path}")
        spec = importlib.util.spec_from_file_location("_ds02_portable_bound_compare_v4", worker_path)
        if spec is None or spec.loader is None:
            raise PortableV4Error("cannot import relocated compare worker")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        native_output = output / "native-v4"
        result = module.run(relocated_request, native_output, io_slot_approved=True,
                            run_labels=True, run_evaluator=False, predictions_path=None)
        status = result.get("status")
    except Exception as error:
        status = "FAILED_PORTABLE_V4_EXECUTION"
        result = {"status": status, "error": str(error)}
    audit_path = output / "portable-python-access-audit-v4.json"
    audit_report = {
        "schema": "ds02.stage2.f2-portable-python-access-audit.v1",
        "python_audit_scope": "open/open_code/os.open events only; HDF5/BI4 C opens require parent OS strace/openat",
        "events": audit.events,
        "rejected": audit.rejected,
        "original_path_access_attempts": len(audit.rejected),
        "status": "PASS_NO_ORIGINAL_PYTHON_ACCESS" if not audit.rejected else "ORIGINAL_ACCESS_REJECTED",
        "qualification": UNKNOWN,
    }
    write_new(audit_path, audit_report)
    report = {
        "schema": RUN_REPORT_SCHEMA,
        "status": status if status != "COMPLETE_DEVELOPMENT_UNKNOWN" else "COMPLETE_PORTABLE_RAW_TO_LABEL_DEVELOPMENT_UNKNOWN",
        "bundle_path": str(Path(bundle_path).expanduser().resolve()),
        "overlay_path": str(Path(overlay_path).expanduser().resolve()),
        "output_dir": str(output),
        "sealed_overlay": seal_receipt,
        "relocated_requests": {key: str(value) for key, value in aliases.items()} if 'aliases' in locals() else {},
        "native_worker_status": result.get("status"),
        "native_worker_report": result,
        "portable_python_access_audit": str(audit_path),
        "os_open_audit_required": True,
        "original_path_fallback": "FORBIDDEN",
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "hdf5_or_bi4_content_read": status != "FAILED_PORTABLE_V4_EXECUTION",
        "limitations": [
            "Python audit hook does not capture native HDF5/BI4 C opens; parent strace/openat receipt is required.",
            "This output remains DEVELOPMENT and carries no QI/QN/QE credit.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    write_new(output / "portable-raw-to-label-run-report-v4.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build-bundle")
    p.add_argument("--parent-bundle", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("build-request")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("build-overlay")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--target-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--overlay", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("seal-overlay")
    p.add_argument("--overlay", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--overlay", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--io-slot-approved", action="store_true")
    p.add_argument("--rehash-after-copy", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-bundle":
            result = build_bundle(args.parent_bundle, args.output)
        elif args.command == "build-request":
            result = build_request(args.bundle, args.output)
        elif args.command == "build-overlay":
            result = build_overlay(args.bundle, args.target_root, args.output)
        elif args.command == "preflight":
            result = preflight_overlay(args.overlay, args.output)
        elif args.command == "seal-overlay":
            result = seal_overlay(args.overlay, args.output)
        else:
            result = run_portable(args.bundle, args.overlay, args.output_dir,
                                  io_slot_approved=args.io_slot_approved,
                                  rehash_after_copy=args.rehash_after_copy)
    except (PortableV4Error, OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
