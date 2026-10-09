#!/usr/bin/env python3
"""V58 direct recovery runner for the ROOT145 copied source.

V57 still entered the V34 executor and therefore copied ``source_entries``
again.  This forward runner has a deliberately smaller execution boundary:
the ROOT145 ``bundle-target`` is an explicit read-only raw/source root and
only a new code overlay and new products directory are created.  The native
V2 worker is launched directly after the parent guard has reserved resources.

The builder is metadata-only.  The runner never copies a BI4/HDF5 payload;
the worker is the only process allowed to read the reused raw root.  The
request keeps QI/QN/QE UNKNOWN and carries no fresh-cold qualification.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V57_SCHEMA = "ds02.stage2.f2-portable-executor-v57-forward.v1"
SCHEMA = "ds02.stage2.f2-root145-copied-recovery-v58.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
PINNED_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PAYLOAD_SUFFIXES = {".bi4", ".obi4", ".h5", ".hdf5", ".xmf"}
MAX_METADATA_BYTES = 8 * 1024 * 1024
CODE_ROLES = (
    "worker", "raw_converter", "v14_operator", "v15_operator", "v16_operator",
    "decoder", "motion_engine_jmotion_data", "motion_engine_jmotion_mov",
    "motion_engine_jmotion_obj",
)


class PortableV58Error(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(path: Path, *, max_bytes: int | None = None) -> str:
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise PortableV58Error(f"metadata file exceeds bound: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _absolute(value: Path | str, role: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PortableV58Error(f"{role} must be absolute: {path}")
    return path


def _load_json(path: Path | str, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    target = _absolute(path, role)
    if target.is_symlink() or not target.is_file():
        raise PortableV58Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise PortableV58Error(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV58Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV58Error(f"{role} must be an object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(path, "output")
    if target.exists() or target.is_symlink():
        raise PortableV58Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _fresh(path: Path | str, role: str) -> Path:
    target = _absolute(path, role)
    if target.exists() or target.is_symlink():
        raise PortableV58Error(f"{role} must be absent before recovery: {target}")
    return target


def _regular_code(path: Path | str, role: str, *, executable: bool = False) -> Path:
    target = _absolute(path, role)
    if target.is_symlink() or not target.is_file():
        raise PortableV58Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise PortableV58Error(f"{role} exceeds code bound: {target}")
    if executable and not os.access(target, os.X_OK):
        raise PortableV58Error(f"{role} is not executable: {target}")
    return target


def _copy_code(source: Path, target: Path, *, executable: bool = False) -> None:
    """Copy a bounded code/metadata file and reject payload roles by suffix."""
    if source.suffix.lower() in PAYLOAD_SUFFIXES or source.name.startswith("Part_"):
        raise PortableV58Error(f"payload copy is forbidden in V58: {source}")
    _regular_code(source, "code source", executable=executable)
    if target.exists() or target.is_symlink():
        raise PortableV58Error(f"refusing existing code target: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    os.chmod(target, stat.S_IMODE(source.stat().st_mode))
    if _sha(source) != _sha(target):
        raise PortableV58Error(f"code overlay SHA differs: {source}")
    if executable and not os.access(target, os.X_OK):
        raise PortableV58Error(f"executable mode was not preserved: {target}")


def _entry_by_role(v57: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    values = [item for item in v57.get("source_entries", [])
              if isinstance(item, Mapping) and item.get("role") == role]
    if len(values) != 1:
        raise PortableV58Error(f"expected one V57 source entry for {role}, got {len(values)}")
    return values[0]


def _runtime_by_role(v57: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    values = [item for item in v57.get("runtime_sources", [])
              if isinstance(item, Mapping) and item.get("role") == role]
    if len(values) != 1:
        raise PortableV58Error(f"expected one V57 runtime source for {role}, got {len(values)}")
    return values[0]


def _bundle_file(bundle: Path, entry: Mapping[str, Any], role: str) -> Path:
    relative = entry.get("target_relative_path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise PortableV58Error(f"V57 entry has no safe target path: {role}")
    result = (bundle / relative).resolve()
    try:
        result.relative_to(bundle.resolve())
    except ValueError as error:
        raise PortableV58Error(f"V57 target escapes reused bundle: {role}") from error
    return result


def _safe_path_map(v57: Mapping[str, Any], bundle: Path) -> dict[str, str]:
    """Map original provenance paths to files in the immutable copied bundle."""
    result: dict[str, str] = {}
    for item in v57.get("source_entries", []):
        if not isinstance(item, Mapping):
            continue
        original = item.get("path")
        relative = item.get("target_relative_path")
        if isinstance(original, str) and isinstance(relative, str):
            result[original] = str(_bundle_file(bundle, item, str(item.get("role"))))
    return result


def _replace_exact(value: Any, path_map: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return path_map.get(value, value)
    if isinstance(value, list):
        return [_replace_exact(item, path_map) for item in value]
    if isinstance(value, dict):
        return {key: _replace_exact(item, path_map) for key, item in value.items()}
    return value


def _source_entry_for_v2(v57: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    return _entry_by_role(v57, f"v2:{role}")


def _rebind_v2_request(v57: Mapping[str, Any], bundle: Path, target: Path) -> dict[str, Any]:
    base = _bundle_file(bundle, _entry_by_role(v57, "immutable_base_v2_request"),
                        "immutable_base_v2_request")
    v2 = _load_json(base, "copied V2 request")
    if v2.get("schema") != REQUEST_SCHEMA:
        raise PortableV58Error("copied V2 request has unexpected schema")
    v2 = copy.deepcopy(v2)
    raw = v2.get("raw_binding")
    if not isinstance(raw, dict):
        raise PortableV58Error("V2 raw_binding is missing")
    raw["data_root"] = str(bundle)
    frames = raw.get("frames")
    if not isinstance(frames, list) or len(frames) != int(raw.get("frame_count", 0)):
        raise PortableV58Error("V2 frame contract is incomplete")
    for index, item in enumerate(frames):
        if not isinstance(item, dict) or item.get("frame") != index:
            raise PortableV58Error("V2 frame records are not contiguous")
        item["path"] = str(bundle / f"Part_{index:04d}.bi4")
        # Parent's post-reservation raw-tree check supplies these content SHAs.
        item["sha256"] = "PENDING_PARENT_GUARD_CONTENT_SHA256"
        item["content_sha256_source"] = "reused_ROOT145_source_after_parent_reservation"
    raw["reused_immutable_source_root"] = str(bundle)
    raw["new_payload_copy_forbidden"] = True
    raw["source_tree_verification_phase"] = "AFTER_ATOMIC_PARENT_RESERVATION_BEFORE_WORKER"

    # Every V2 source file is already present under the old bundle.  Keep the
    # producer SHA, but bind the actionable path to the copied source file.
    source_files = v2.get("source_files")
    if not isinstance(source_files, list):
        raise PortableV58Error("V2 source_files is missing")
    for item in source_files:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise PortableV58Error("malformed V2 source file")
        entry = _source_entry_for_v2(v57, item["role"])
        item["path"] = str(_bundle_file(bundle, entry, f"v2:{item['role']}"))
        item["original_path_provenance"] = entry.get("path")
    v2["source_hashes_preverified_by_parent"] = True

    modules = v2.get("modules")
    if not isinstance(modules, dict):
        raise PortableV58Error("V2 modules are missing")
    module_rows = {
        "raw_converter": ("copied_module_raw_converter", "ds_data02_f5_bi4.py"),
        "v14_operator": ("copied_module_v14_operator", "ds_data02_stage2_f2_replay_v14.py"),
        "v15_operator": ("copied_module_v15_operator", "ds_data02_stage2_f2_replay_v15.py"),
        "v16_operator": ("copied_module_v16_operator", "ds_data02_stage2_f2_flux_v16.py"),
        "worker": ("raw_worker_v2", "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"),
    }
    for role, (entry_role, filename) in module_rows.items():
        entry = _runtime_by_role(v57, entry_role)
        item = modules.get(role)
        if not isinstance(item, dict):
            item = {}
            modules[role] = item
        item["path"] = str(target / "runtime" / "native" / filename)
        item["original_path_provenance"] = entry.get("path")
        item["sha256"] = entry.get("sha256", item.get("sha256"))

    decoder = v2.get("decoder")
    if not isinstance(decoder, dict):
        raise PortableV58Error("V2 decoder binding is missing")
    decoder_entry = _entry_by_role(v57, "native_bi4_decoder")
    decoder["path"] = str(target / "runtime" / "native" / "bi4_dump")
    decoder["original_path_provenance"] = decoder_entry.get("path")
    decoder["sha256"] = decoder_entry.get("sha256", decoder.get("sha256"))

    # Rebind all nested V15 provenance paths to copied source metadata, then
    # replace its three official JMotion source paths with the new code overlay
    # (those headers are small source code, not payload data).
    path_map = _safe_path_map(v57, bundle)
    v15 = v2.get("v15_request")
    if not isinstance(v15, dict):
        raise PortableV58Error("V2 nested V15 request is missing")
    v15 = _replace_exact(v15, path_map)
    # Some V15 metadata was authored from a different worktree than the V2
    # source-entry record.  Bind by the frozen semantic role as well as by
    # exact provenance string; otherwise one stale absolute path survives the
    # relocation and is an actionable fallback.
    v15_sources = v15.get("source_files")
    if not isinstance(v15_sources, list):
        raise PortableV58Error("nested V15 source_files are missing")
    for item in v15_sources:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise PortableV58Error("malformed nested V15 source file")
        try:
            entry = _source_entry_for_v2(v57, item["role"])
        except PortableV58Error:
            # V15's source list is a strict subset of V2's list; a role not
            # present in the V2 contract cannot silently remain actionable.
            raise PortableV58Error(f"nested V15 role is not in copied V2 source closure: {item['role']}")
        item["path"] = str(_bundle_file(bundle, entry, f"v2:{item['role']}"))
        item["original_path_provenance"] = entry.get("path")
    trajectory = v15.get("trajectory_h5")
    if isinstance(trajectory, dict):
        entry = _entry_by_role(v57, "reference_typed_hdf5")
        trajectory["path"] = str(_bundle_file(bundle, entry, "reference_typed_hdf5"))
        trajectory["original_path_provenance"] = entry.get("path")
    engine_targets: dict[str, str] = {}
    engine = v15.get("motion_engine_sources")
    if isinstance(engine, dict):
        for role, item in engine.items():
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                engine_targets[role] = str(target / "runtime" / "native" / Path(item["path"]).name)
                item["original_path_provenance"] = item["path"]
                item["path"] = engine_targets[role]
    source_code = v15.get("source_code_binding")
    if isinstance(source_code, dict):
        official = source_code.get("official_motion_engine")
        if isinstance(official, dict):
            for role, item in official.items():
                if isinstance(item, dict) and role in engine_targets and isinstance(item.get("path"), str):
                    item["original_path_provenance"] = item["path"]
                    item["path"] = engine_targets[role]
    v2["v15_request"] = v15
    v2["recovery_binding"] = {
        "schema": "ds02.stage2.f2-root145-recovery-binding.v1",
        "reused_raw_root": str(bundle),
        "new_code_root": str(target / "runtime" / "native"),
        "new_output_root": "<V58_OUTPUT_ROOT>",
        "raw_copy_forbidden": True,
        "source_path_fallback": "FORBIDDEN",
        "engine_source_targets": engine_targets,
        "parent_content_verification": "AFTER_ATOMIC_PARENT_RESERVATION",
    }
    return v2


def _copy_rows(v57: Mapping[str, Any], bundle: Path, target: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    mapping = {
        "worker": ("v2_worker", "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py", False),
        "raw_converter": ("raw_converter", "runtime/native/ds_data02_f5_bi4.py", False),
        "v14_operator": ("v14_operator", "runtime/native/ds_data02_stage2_f2_replay_v14.py", False),
        "v15_operator": ("v15_operator", "runtime/native/ds_data02_stage2_f2_replay_v15.py", False),
        "v16_operator": ("v16_operator", "runtime/native/ds_data02_stage2_f2_flux_v16.py", False),
        "decoder": ("native_bi4_decoder", "runtime/native/bi4_dump", True),
    }
    for role, (entry_role, relative, executable) in mapping.items():
        entry = (_entry_by_role(v57, entry_role)
                 if entry_role == "native_bi4_decoder"
                 else _runtime_by_role(v57, entry_role))
        source = _bundle_file(bundle, entry, entry_role)
        dest = target / relative
        _copy_code(source, dest, executable=executable)
        rows.append({"role": role, "source": str(source), "target": str(dest),
                     "sha256": _sha(dest), "mode_bits": stat.S_IMODE(dest.stat().st_mode),
                     "payload_copied": False})
    # Official motion implementation sources are not in ROOT145's small
    # source list.  They are explicit code inputs from the frozen V15 request;
    # copy them into the new overlay and never import them from the worktree.
    base = _bundle_file(bundle, _entry_by_role(v57, "immutable_base_v2_request"),
                        "immutable_base_v2_request")
    v2 = _load_json(base, "copied V2 request")
    v15 = v2.get("v15_request")
    engine = v15.get("motion_engine_sources") if isinstance(v15, dict) else None
    if isinstance(engine, dict):
        for role, item in engine.items():
            if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
                raise PortableV58Error(f"missing source for {role}")
            source = _regular_code(item["path"], role)
            dest = target / "runtime" / "native" / source.name
            _copy_code(source, dest)
            expected = item.get("sha256")
            if expected and _sha(dest) != expected:
                raise PortableV58Error(f"motion source SHA differs: {role}")
            rows.append({"role": role, "source": str(source), "target": str(dest),
                         "sha256": _sha(dest), "mode_bits": stat.S_IMODE(dest.stat().st_mode),
                         "payload_copied": False})
    return rows


def _planned_code_bindings(v57: Mapping[str, Any], bundle: Path, target: Path,
                           embedded: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return explicit source/target bindings for the small direct overlay.

    These are metadata attestations only.  The parent guard performs the
    content SHA/stat check after reservation; this builder does not read a
    raw/HDF5 payload and does not copy any file.
    """
    rows: list[dict[str, Any]] = []
    mapping = {
        "worker": ("raw_worker_v2", "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py", False),
        "raw_converter": ("copied_module_raw_converter", "runtime/native/ds_data02_f5_bi4.py", False),
        "v14_operator": ("copied_module_v14_operator", "runtime/native/ds_data02_stage2_f2_replay_v14.py", False),
        "v15_operator": ("copied_module_v15_operator", "runtime/native/ds_data02_stage2_f2_replay_v15.py", False),
        "v16_operator": ("copied_module_v16_operator", "runtime/native/ds_data02_stage2_f2_flux_v16.py", False),
    }
    for role, (source_role, relative, executable) in mapping.items():
        entry = _runtime_by_role(v57, source_role)
        source = _bundle_file(bundle, entry, source_role)
        rows.append({"role": role, "source_path": str(source),
                     "source_path_provenance": entry.get("path"),
                     "target_path": str(target / relative),
                     "target_relative_path": relative,
                     "sha256": entry.get("sha256"),
                     "bytes": entry.get("bytes"),
                     "mode_bits": entry.get("mode_bits", entry.get("source_mode_bits")),
                     "required_executable": executable,
                     "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION"})
    decoder_entry = _entry_by_role(v57, "native_bi4_decoder")
    decoder_source = _bundle_file(bundle, decoder_entry, "native_bi4_decoder")
    rows.append({"role": "decoder", "source_path": str(decoder_source),
                 "source_path_provenance": decoder_entry.get("path"),
                 "target_path": str(target / "runtime/native/bi4_dump"),
                 "target_relative_path": "runtime/native/bi4_dump",
                 "sha256": decoder_entry.get("sha256"),
                 "bytes": decoder_entry.get("bytes"),
                 "mode_bits": decoder_entry.get("mode_bits", decoder_entry.get("source_mode_bits")),
                 "required_executable": True,
                 "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION"})
    v15 = embedded.get("v15_request")
    engine = v15.get("motion_engine_sources") if isinstance(v15, Mapping) else None
    if isinstance(engine, Mapping):
        for role, item in engine.items():
            if not isinstance(item, Mapping) or not isinstance(item.get("original_path_provenance"), str):
                raise PortableV58Error(f"engine source provenance is missing: {role}")
            source = _regular_code(item["original_path_provenance"], role)
            relative = "runtime/native/" + source.name
            rows.append({"role": role, "source_path": str(source),
                         "source_path_provenance": str(source),
                         "target_path": str(target / relative),
                         "target_relative_path": relative,
                         "sha256": item.get("sha256"), "bytes": source.stat().st_size,
                         "mode_bits": stat.S_IMODE(source.stat().st_mode),
                         "required_executable": False,
                         "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION"})
    return rows


def build_recovery(*, v57_request: Path | str, reused_bundle_root: Path | str,
                   output_request: Path | str, target_root: Path | str,
                   output_root: Path | str) -> dict[str, Any]:
    v57_path = _absolute(v57_request, "V57 request")
    v57 = _load_json(v57_path, "V57 request")
    marker = v57.get("forward_v57")
    if not isinstance(marker, Mapping) or marker.get("schema") != V57_SCHEMA:
        raise PortableV58Error("input is not the frozen V57 request")
    bundle = _absolute(reused_bundle_root, "reused bundle root").resolve()
    if not bundle.is_dir() or bundle.is_symlink():
        raise PortableV58Error(f"reused bundle root is not a directory: {bundle}")
    recorded = marker.get("reused_immutable_copy", {})
    if not isinstance(recorded, Mapping) or Path(str(recorded.get("bundle_root", ""))).resolve() != bundle:
        raise PortableV58Error("reused bundle does not match frozen V57 source identity")
    target = _fresh(target_root, "target root")
    product = _fresh(output_root, "output root")
    if target == product or target in product.parents or product in target.parents:
        raise PortableV58Error("target and output roots must be distinct")

    # The builder reads only the V2 JSON and code/source metadata.  It does not
    # hash or open raw frame/HDF5 payloads.
    embedded = _rebind_v2_request(v57, bundle, target)
    attempt = "f2-s1-root145-v58-direct-recovery-20261009-001"
    runtime = {
        "schema": "ds02.stage2.f2-root145-direct-recovery-runtime.v1",
        "worker_mode": "DIRECT_V2_NO_V34_COPY_CHAIN",
        "worker_source_role": "v2_worker",
        "worker_target": str(target / "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"),
        "worker_request_target": str(target / "runtime/native/f2-s1-v58-worker-request.json"),
        "pinned_python": PINNED_PYTHON,
        "literal_argv0_preserved": True,
        "source_path_fallback": "FORBIDDEN",
        "raw_copy_forbidden": True,
        "raw_root": str(bundle),
        "raw_tree_expected_sha256": embedded["raw_binding"]["expected_raw_tree_sha256"],
        "raw_tree_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_BEFORE_WORKER",
        "small_code_overlay_only": True,
        "copy_roles": list(CODE_ROLES),
        "decoder_scratch": {
            "attempt_owned": True,
            "default_tmp_forbidden": True,
            "per_frame": True,
            "max_live_directories": 1,
            "max_frame_bytes": 536870912,
            "timeout_seconds": 180,
        },
    }
    runtime["code_overlay_bindings"] = _planned_code_bindings(v57, bundle, target, embedded)
    command = [PINNED_PYTHON, "-B", "-I", runtime["worker_target"], "run",
               "--request", runtime["worker_request_target"], "--output-dir", str(product),
               "--io-slot-approved", "--run-labels"]
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "role": "DEVELOPMENT",
        "request_id": attempt,
        "case_id": v57.get("case_id", "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"),
        "family_id": "F2",
        "fresh_roots": {"target_root": str(target), "output_root": str(product),
                        "supervisor_root": str(product.parent / "supervisor")},
        "v57_provenance": {"path": str(v57_path), "sha256": _sha(v57_path),
                           "schema": v57.get("schema"),
                           "raw_source_binding": marker.get("reused_immutable_copy")},
        "reused_immutable_copy": {
            "bundle_root": str(bundle),
            "raw_data_root": str(bundle),
            "source_role": "ROOT145_V55_COPIED_RAW_SOURCE",
            "new_payload_copy_forbidden": True,
            "old_namespace_immutable": True,
            "content_verification": "AFTER_ATOMIC_PARENT_RESERVATION",
            "source_path_fallback": "FORBIDDEN",
            "raw_tree_sha256": embedded["raw_binding"]["expected_raw_tree_sha256"],
            "raw_tree_file_count": embedded["raw_binding"]["expected_file_count"],
            "raw_tree_frame_count": embedded["raw_binding"]["frame_count"],
        },
        "embedded_worker_request": embedded,
        "runtime": runtime,
        "execution": {
            "python": PINNED_PYTHON, "command": command, "command_is_direct_v2": True,
            "no_v34_v55_v57_delegation": True, "io_slot_required": True,
            "max_wall_seconds": 6000.0, "memory_max_bytes": 8 * 1024**3,
            "new_output_root": str(product), "old_output_reuse_forbidden": True,
            "env": {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"},
        },
        "parent_resource_binding": {
            "attempt_id": attempt, "reservation_id": attempt + "::reservation",
            "charge_id": attempt + "::charge", "same_parent_ledger": True,
            "ledger_reset": False, "allow_missing_parent": True,
            "storage_policy": "home_free_floor", "external_filesystem": "/var/tmp",
            "external_reservation_bytes": 12 * 1024**3,
            "external_min_free_bytes": 20 * 1024**3,
            "home_min_free_bytes": 500 * 1024**3, "home_receipt_bytes": 65536,
            "cpu_reservation_seconds": 6000.0,
            "source_content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        },
        "storage_scope": {
            "source_copy_bytes": 0, "reused_source_copy_bytes_not_recharged": True,
            "new_code_overlay_bytes_estimate": 2 * 1024**2,
            "declared_typed_output_budget_bytes": 2 * 1024**3,
            "declared_decoder_scratch_bytes": 512 * 1024**2,
            "external_reservation_bytes": 12 * 1024**3,
            "external_output_root": str(product), "supervisor_output_root": str(product.parent / "supervisor"),
            "two_filesystem_charge_required": True, "new_namespace_absent_before_run": True,
            "raw_payload_copy_forbidden": True,
        },
        "copy_contract": {
            "schema": "ds02.stage2.f2-root145-recovery-copy-contract.v1",
            "allowed": "code_and_small_metadata_only",
            "forbidden_suffixes": sorted(PAYLOAD_SUFFIXES),
            "forbidden_roles": ["raw_frame_input", "raw_auxiliary", "trajectory_h5", "reference_typed_hdf5"],
            "old_namespace_write": "FORBIDDEN",
            "raw_copy_attempts_expected": 0,
            "target_inodes_must_be_distinct": True,
        },
        "source_contract": {
            "base_request_schema": REQUEST_SCHEMA,
            "source_hashes_preverified_by_parent": True,
            "full_raw_prepost_required": True,
            "payload_read_phase": "AFTER_PARENT_RESERVATION_ONLY",
            "original_path_fallback": "FORBIDDEN",
        },
        "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
        "hdf5_opened": False, "fresh_cold_credit": False,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "This is a recovery over an immutable copied ROOT145 raw source; it is not a fresh cold replay.",
            "No scientific credit is granted until a parent-verified worker report and independent V16 semantic proof exist.",
            "The build phase reads no BI4, HDF5, or result payload content.",
        ],
    }
    # The request is written once and cannot be silently changed after root
    # binds its source SHA.  The nested worker JSON is included in the parent
    # request; run writes the same object to the fresh target after reserve.
    request["sha256"] = _canonical(request)
    out = _write_new(output_request, request)
    return {"schema": SCHEMA, "status": request["status"], "request": str(out),
            "request_sha256": _sha(out), "payload_read": False,
            "raw_copy_bytes": 0, "worker_mode": runtime["worker_mode"],
            "fresh_cold_credit": False, "qualification": dict(UNKNOWN)}


def _assert_reused_raw_root(bundle: Path, embedded: Mapping[str, Any]) -> dict[str, Any]:
    raw = embedded.get("raw_binding")
    if not isinstance(raw, Mapping) or raw.get("data_root") != str(bundle):
        raise PortableV58Error("worker request is not bound to the reused raw root")
    frames = raw.get("frames")
    if not isinstance(frames, list):
        raise PortableV58Error("worker frames are missing")
    # Stat-only preflight; content hashes remain the parent/worker after-reserve
    # responsibility.  This loop never opens a BI4 file.
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or item.get("path") != str(bundle / f"Part_{index:04d}.bi4"):
            raise PortableV58Error(f"worker frame path is not top-level reused Part path: {index}")
        path = bundle / f"Part_{index:04d}.bi4"
        if not path.is_file() or path.is_symlink():
            raise PortableV58Error(f"reused raw frame is missing or symlinked: {path}")
    return {"frame_count": len(frames), "file_count": raw.get("expected_file_count"),
            "tree_sha256": raw.get("expected_raw_tree_sha256")}


def _old_namespace_stat(bundle: Path) -> dict[str, Any]:
    # Directory/entry stats are enough to prove the runner did not create or
    # alter an old output.  No file contents are read here.
    entries = []
    for name in ("PartInfo.ibi4", "PartMotionRef.ibi4", "PartOut_000.obi4", "Part_Head.ibi4"):
        path = bundle / name
        if path.exists():
            st = path.stat()
            entries.append({"name": name, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
                            "st_ino": st.st_ino, "st_dev": st.st_dev})
    return {"raw_root": str(bundle), "auxiliary_entries": entries}


def _load_worker_result(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, max_wall_seconds: float | None = None,
        worker_override: Path | None = None) -> dict[str, Any]:
    """Directly run V2 against a reused raw root; never call V34/V55/V57."""
    if not io_slot_approved:
        raise PortableV58Error("V58 requires an approved parent I/O slot")
    path = _absolute(request_path, "V58 request")
    request = _load_json(path, "V58 request")
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_STAGE2_GUARD":
        raise PortableV58Error("request is not a V58 parent-guard request")
    if request.get("qualification") != UNKNOWN or request.get("fresh_cold_credit") is not False:
        raise PortableV58Error("V58 qualification boundary was changed")
    roots = request.get("fresh_roots")
    reused = request.get("reused_immutable_copy")
    if not isinstance(roots, Mapping) or not isinstance(reused, Mapping):
        raise PortableV58Error("fresh/reused roots are missing")
    target = _fresh(str(roots["target_root"]), "target root")
    product = _fresh(str(roots["output_root"]), "output root")
    bundle = _absolute(str(reused["bundle_root"]), "reused bundle root").resolve()
    if not bundle.is_dir():
        raise PortableV58Error("reused bundle root is missing")
    embedded = request.get("embedded_worker_request")
    if not isinstance(embedded, Mapping):
        raise PortableV58Error("embedded worker request is missing")
    raw_info = _assert_reused_raw_root(bundle, embedded)
    before = _old_namespace_stat(bundle)
    target.mkdir(parents=True, exist_ok=False)
    product.mkdir(parents=True, exist_ok=False)
    supervisor = product.parent / "supervisor"
    supervisor.mkdir(parents=True, exist_ok=False)
    native = target / "runtime" / "native"
    native.mkdir(parents=True, exist_ok=False)
    worker_request = native / "f2-s1-v58-worker-request.json"
    worker_path: Path
    code_rows: list[dict[str, Any]] = []
    try:
        # Normally copy the immutable code from ROOT145.  Tests may provide a
        # bounded worker stub, but it is still copied and launched by this
        # exact direct-recovery path.
        frozen_v57 = _load_json(request["v57_provenance"]["path"], "frozen V57 request")
        if worker_override is not None:
            source = _regular_code(worker_override, "worker override")
            worker_path = native / "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
            _copy_code(source, worker_path)
            code_rows.append({"role": "worker_override", "source": str(source), "target": str(worker_path),
                              "payload_copied": False})
        else:
            code_rows = _copy_rows(frozen_v57, bundle, target)
            worker_path = native / "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
        if worker_path != Path(str(request["runtime"]["worker_target"])):
            raise PortableV58Error("worker target differs from request runtime binding")
        embedded_value = copy.deepcopy(dict(embedded))
        embedded_value["recovery_binding"]["new_output_root"] = str(product)
        embedded_value["raw_binding"]["data_root"] = str(bundle)
        embedded_value["raw_binding"]["new_payload_copy_forbidden"] = True
        _write_new(worker_request, embedded_value)
        timeout = float(max_wall_seconds if max_wall_seconds is not None
                        else request["execution"]["max_wall_seconds"])
        if timeout <= 0:
            raise PortableV58Error("max wall seconds must be positive")
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME"}}
        env.update({str(k): str(v) for k, v in request["execution"].get("env", {}).items()})
        command = [PINNED_PYTHON, "-B", "-I", str(worker_path), "run", "--request",
                   str(worker_request), "--output-dir", str(product), "--io-slot-approved",
                   "--run-labels"]
        started = time.monotonic()
        completed = subprocess.run(command, cwd=str(native), env=env, capture_output=True,
                                   text=True, check=False, timeout=timeout)
        elapsed = time.monotonic() - started
        child_result = _load_worker_result(completed.stdout)
        status = "PASS_RECOVERY_WORKER_COMPLETED_PENDING_SEMANTIC_PROOF" if completed.returncode == 0 else "FAILED_RECOVERY_WORKER"
        report = {
            "schema": "ds02.stage2.f2-root145-copied-recovery-report-v58.v1",
            "status": status, "request_path": str(path), "request_sha256": _sha(path),
            "worker_returncode": completed.returncode, "worker_result": child_result,
            "worker_command": command, "worker_elapsed_seconds": elapsed,
            "worker_mode": "DIRECT_V2_NO_V34_COPY_CHAIN", "parent_pid": parent_pid,
            "raw_copy_attempts": 0, "source_copy_bytes": 0,
            "reused_source_root": str(bundle), "new_code_overlay": code_rows,
            "new_output_root": str(product), "raw_binding": raw_info,
            "old_namespace_before": before, "old_namespace_after": _old_namespace_stat(bundle),
            "raw_tree_verification": "WORKER_REPORT_REQUIRED_AFTER_PARENT_RESERVATION",
            "stdout_tail": completed.stdout[-8000:], "stderr_tail": completed.stderr[-8000:],
            "payload_read": True, "model_invoked": False, "cfd_invoked": False,
            "fresh_cold_credit": False, "qualification": dict(UNKNOWN),
        }
        report_path = supervisor / "f2-s1-root145-v58-recovery-report.json"
        _write_new(report_path, report)
        return report | {"report_path": str(report_path)}
    except subprocess.TimeoutExpired as error:
        report = {
            "schema": "ds02.stage2.f2-root145-copied-recovery-report-v58.v1",
            "status": "FAILED_RECOVERY_WORKER_TIMEOUT", "request_path": str(path),
            "request_sha256": _sha(path), "worker_returncode": None,
            "raw_copy_attempts": 0, "source_copy_bytes": 0, "reused_source_root": str(bundle),
            "new_code_overlay": code_rows, "new_output_root": str(product),
            "old_namespace_before": before, "old_namespace_after": _old_namespace_stat(bundle),
            "stdout_tail": str(error.stdout)[-8000:], "stderr_tail": str(error.stderr)[-8000:],
            "payload_read": True, "fresh_cold_credit": False, "qualification": dict(UNKNOWN),
        }
        report_path = supervisor / "f2-s1-root145-v58-recovery-report.json"
        _write_new(report_path, report)
        return report | {"report_path": str(report_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-recovery")
    build.add_argument("--v57-request", type=Path, required=True)
    build.add_argument("--reused-bundle-root", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--max-wall-seconds", type=float)
    run_parser.add_argument("--worker-override", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-recovery":
            result = build_recovery(v57_request=args.v57_request,
                                     reused_bundle_root=args.reused_bundle_root,
                                     output_request=args.output_request,
                                     target_root=args.target_root,
                                     output_root=args.output_root)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds,
                         worker_override=args.worker_override)
    except (PortableV58Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v58: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
