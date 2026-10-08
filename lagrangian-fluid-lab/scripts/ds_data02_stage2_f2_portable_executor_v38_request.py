#!/usr/bin/env python3
"""Build a fresh V38 full-cold F2 request and its parent-v3 envelope.

The V37 attempt is immutable.  Its raw converter reached a typed HDF5, but
the label subprocess stopped at the relocated V15 import.  The V38 executor
fixes that import closure.  This builder supplies the missing request boundary
around it:

* the V36 V34-envelope is copied into a fresh namespace;
* the four parent-guarded auxiliary raw files are added to the overlay;
* the frozen 401-frame + four-auxiliary tree identity is carried as
  provenance, without hashing BI4/OBI4 payloads during build;
* the V38 wrapper and private V14/V15/V16 module bindings are explicit; and
* the existing parent-v3 builder is used for the same parent ledger, two
  filesystem reservation, filtered strace, and terminal charge.

No ledger is created or mutated here.  ``build-executor`` is metadata/stat
only.  ``build-parent`` delegates to the immutable parent-v3 implementation,
whose actual run remains parent-guarded.  QI/QN/QE and all scientific status
remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V38_EXECUTOR = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v38.py"
PARENT_V3 = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_parent_v3.py"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
PARENT_V3_SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
# This is the marker consumed by the immutable V38 wrapper.  The outer
# builder's filename/version is separate from the compatibility envelope.
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v38-forward.v1"
AUX_SCHEMA = "ds02.stage2.f2-raw-auxiliary-binding.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
FROZEN_RAW_TREE_SHA256 = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
FROZEN_RAW_FILE_COUNT = 405
FROZEN_FRAME_COUNT = 401
V38_PARENT_FALLBACK = (
    "scoped_same_parent_charge_only; V37 missing-parent failure was repaired "
    "once and is not reused; this fresh attempt has a distinct reservation/charge id"
)


class V38RequestError(RuntimeError):
    """The fresh V38 request or its source closure is unsafe."""


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


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V38RequestError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise V38RequestError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise V38RequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_file(path: Any, role: str) -> Path:
    if not isinstance(path, (str, os.PathLike)) or not str(path):
        raise V38RequestError(f"{role} path is missing")
    target = Path(path).expanduser()
    if not target.is_file():
        raise V38RequestError(f"{role} is missing: {target}")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise V38RequestError(f"{name} must be a lowercase SHA-256")
    return value


def _stat_binding(path: Path, role: str) -> dict[str, Any]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise V38RequestError(f"{role} is not a regular file: {path}")
    return {"path": str(path), "bytes": int(info.st_size),
            "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _check_metadata_stat(item: Mapping[str, Any], role: str) -> dict[str, Any]:
    """Check a declared source by stat only; never hash raw payload here."""
    path = _require_file(item.get("path"), role)
    expected_bytes = int(item.get("bytes", -1))
    info = _stat_binding(path, role)
    if info["bytes"] != expected_bytes:
        raise V38RequestError(f"{role} byte stat differs: {path}")
    _require_sha(item.get("sha256"), f"{role}.sha256")
    result = dict(item)
    result.update(info)
    return result


def _load_previous(path: Path | str) -> tuple[Path, dict[str, Any]]:
    source = _require_file(path, "previous V36 executor request")
    value = load_json(source)
    if value.get("schema") != V34_SCHEMA:
        raise V38RequestError(f"previous request schema differs: {value.get('schema')!r}")
    if value.get("sha256") != canonical_sha(value):
        raise V38RequestError("previous V36 executor request canonical SHA differs")
    if value.get("status") != "READY_FOR_PARENT_STAGE2_GUARD":
        raise V38RequestError("previous V36 executor request is not parent-ready")
    if value.get("role") != "DEVELOPMENT" or value.get("model_invoked") is not False:
        raise V38RequestError("previous request is not model-free DEVELOPMENT")
    if value.get("cfd_invoked") is not False or value.get("qualification") != UNKNOWN:
        raise V38RequestError("previous request must keep CFD false and UNKNOWN qualification")
    forward = value.get("forward_v36")
    if not isinstance(forward, Mapping) or forward.get("schema") != "ds02.stage2.f2-portable-executor-v36-forward.v1":
        raise V38RequestError("previous V36 forward marker is missing")
    source_entries = value.get("source_entries")
    if not isinstance(source_entries, list) or not source_entries:
        raise V38RequestError("previous source_entries are missing")
    # The V36 source closure is 401 frames plus 42 small files.  Keep exact
    # counts in the request and reject a guessed/prefix-only source set.
    raw = [x for x in source_entries if isinstance(x, Mapping) and x.get("role") == "raw_frame_input"]
    if len(raw) != FROZEN_FRAME_COUNT:
        raise V38RequestError(f"previous request has {len(raw)} raw frames; expected {FROZEN_FRAME_COUNT}")
    frame_names = {str(x.get("target_relative_path", "")).split("/")[-1] for x in raw}
    expected_names = {f"Part_{index:04d}.bi4" for index in range(FROZEN_FRAME_COUNT)}
    if frame_names != expected_names:
        raise V38RequestError("previous raw frame closure is not exactly Part_0000..Part_0400")
    # These are stats only.  Content SHA is deliberately deferred to parent
    # reservation + child copy, including the 7.37 GB raw frame files.
    checked_entries = [_check_metadata_stat(item, f"source_entries[{idx}]")
                       for idx, item in enumerate(source_entries)
                       if isinstance(item, Mapping)]
    if len(checked_entries) != len(source_entries):
        raise V38RequestError("previous source entry is malformed")
    template_binding = value.get("v5_overlay_template")
    if not isinstance(template_binding, Mapping):
        raise V38RequestError("previous v5 overlay binding is missing")
    template_path = _require_file(template_binding.get("path"), "previous v5 overlay")
    if sha256_file(template_path) != _require_sha(template_binding.get("sha256"), "previous v5 overlay.sha256"):
        raise V38RequestError("previous v5 overlay content differs")
    template = load_json(template_path)
    if template.get("sha256") != canonical_sha(template):
        raise V38RequestError("previous v5 overlay canonical SHA differs")
    if not isinstance(template.get("entries"), list) or len(template["entries"]) != len(source_entries):
        raise V38RequestError("previous overlay/source entry counts differ")
    return source, value


def _load_auxiliary(path: Path | str) -> tuple[Path, dict[str, Any]]:
    source = _require_file(path, "parent-guarded V37 auxiliary binding")
    value = load_json(source)
    if value.get("schema") != AUX_SCHEMA or value.get("status") != "COMPLETE_PARENT_GUARDED":
        raise V38RequestError("auxiliary binding is not completed parent-guarded evidence")
    if value.get("sha256") != canonical_sha(value):
        raise V38RequestError("auxiliary binding canonical SHA differs")
    expected = value.get("expected_raw_tree")
    if not isinstance(expected, Mapping) or int(expected.get("file_count", -1)) != FROZEN_RAW_FILE_COUNT:
        raise V38RequestError("auxiliary binding does not declare the frozen 405-file tree")
    if expected.get("tree_sha256") != FROZEN_RAW_TREE_SHA256:
        raise V38RequestError("auxiliary binding raw-tree SHA differs from frozen producer")
    request_tree = value.get("request_expected_raw_tree")
    if not isinstance(request_tree, Mapping) or int(request_tree.get("frame_count", -1)) != FROZEN_FRAME_COUNT:
        raise V38RequestError("auxiliary request frame count is not 401")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) != 4:
        raise V38RequestError("exactly four guarded auxiliary files are required")
    seen: set[str] = set()
    checked: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise V38RequestError(f"auxiliary entry {index} is malformed")
        filename = raw.get("filename")
        if not isinstance(filename, str) or not filename or "/" in filename or filename in seen:
            raise V38RequestError(f"auxiliary filename is unsafe/duplicate: {filename!r}")
        seen.add(filename)
        sha = _require_sha(raw.get("sha256"), f"auxiliary[{filename}].sha256")
        if raw.get("content_hash_status") != "PARENT_GUARDED_CONTENT_SHA256":
            raise V38RequestError(f"auxiliary {filename} is not parent-guarded")
        checked_item = _check_metadata_stat({**raw, "path": raw.get("path"),
                                             "bytes": raw.get("bytes"), "sha256": sha},
                                            f"auxiliary[{filename}]")
        checked_item["role"] = f"raw_auxiliary:{filename}"
        checked.append(checked_item)
    frozen = value.get("frozen_frame_manifest")
    if not isinstance(frozen, list) or len(frozen) != FROZEN_FRAME_COUNT:
        raise V38RequestError("auxiliary binding lacks the complete frozen frame manifest")
    frame_by_name = {str(x.get("relative_path")): x for x in frozen if isinstance(x, Mapping)}
    if set(frame_by_name) != {f"Part_{index:04d}.bi4" for index in range(FROZEN_FRAME_COUNT)}:
        raise V38RequestError("frozen frame manifest is not exactly 401 frames")
    return source, {"binding": value, "entries": checked,
                    "expected_raw_tree": dict(expected),
                    "frozen_frame_manifest": frozen}


def _overlay_entry_for_source(item: Mapping[str, Any], target_relative: str) -> dict[str, Any]:
    path = Path(str(item["path"])).expanduser()
    return {
        "role": str(item["role"]),
        "original_path": str(path),
        "bundle_relative_path": target_relative,
        "expected_bytes": int(item["bytes"]),
        "expected_sha256": _require_sha(item["sha256"], f"{item['role']}.sha256"),
        "original_mtime_ns": int(item["mtime_ns"]),
        "source_mode_bits": int(item.get("mode_bits", stat.S_IMODE(path.stat().st_mode))),
        "target_mode_bits": int(item.get("mode_bits", stat.S_IMODE(path.stat().st_mode))),
        "preserve_mode": True,
        "required_executable": False,
        "target_inode_must_differ": True,
        "content_hash_status": "PENDING_PARENT_COPY",
    }


def _make_overlay(previous: Mapping[str, Any], template: Mapping[str, Any],
                  aux: Mapping[str, Any], aux_path: Path,
                  output: Path, target_root: Path) -> tuple[Path, dict[str, Any]]:
    entries = template.get("entries")
    if not isinstance(entries, list):
        raise V38RequestError("previous overlay entries are missing")
    result = copy.deepcopy(dict(template))
    # V34's runtime builder replaces target_root/target_path and recalculates
    # these fields.  Keeping only source/provenance paths here makes it
    # impossible to accidentally reuse a consumed V36 destination.
    result["target_root"] = str(target_root)
    result["target_paths_are_new"] = True
    result["content_hash_verified"] = False
    result["status"] = "READY_FOR_PARENT_COPY"
    result.pop("target_path", None)
    result["forward_v38"] = {
        "schema": FORWARD_SCHEMA,
        "frozen_raw_tree": dict(aux["expected_raw_tree"]),
        "auxiliary_binding": {"path": str(aux_path), "sha256": sha256_file(aux_path),
                               "entry_count": len(aux["entries"])},
        "payload_hashes_deferred_to_parent": True,
        "qualification": dict(UNKNOWN),
    }
    existing_targets = {str(x.get("bundle_relative_path")) for x in entries if isinstance(x, Mapping)}
    for item in aux["entries"]:
        filename = str(item["filename"])
        if filename in existing_targets:
            raise V38RequestError(f"auxiliary target collides with V36 overlay: {filename}")
        entries.append(_overlay_entry_for_source(item, filename))
        existing_targets.add(filename)
    sidecar_item = {
        "role": "raw_auxiliary_binding_v37",
        "path": str(aux_path),
        "bytes": int(aux_path.stat().st_size),
        "mtime_ns": int(aux_path.stat().st_mtime_ns),
        "mode_bits": int(stat.S_IMODE(aux_path.stat().st_mode)),
        "sha256": sha256_file(aux_path),
    }
    if "sources/0038-raw-auxiliary-binding-v37.json" in existing_targets:
        raise V38RequestError("auxiliary provenance sidecar target collides")
    entries.append(_overlay_entry_for_source(sidecar_item, "sources/0038-raw-auxiliary-binding-v37.json"))
    result["entries"] = entries
    result["source_hash_seal"] = {
        "raw_frame_count": FROZEN_FRAME_COUNT,
        "auxiliary_count": len(aux["entries"]),
        "frozen_tree_sha256": FROZEN_RAW_TREE_SHA256,
        "content_hash_phase": "parent_after_reservation",
    }
    result["sha256"] = canonical_sha(result)
    target = write_new(output, result)
    return target, result


def build_executor(*, previous_request: Path | str, auxiliary_binding: Path | str,
                   output_request: Path | str, overlay_output: Path | str,
                   target_root: Path | str, output_root: Path | str) -> dict[str, Any]:
    previous_path, previous = _load_previous(previous_request)
    aux_path, aux = _load_auxiliary(auxiliary_binding)
    target = Path(target_root).expanduser()
    output = Path(output_root).expanduser()
    if target.exists() or output.exists():
        raise V38RequestError("V38 fresh target/output roots must not already exist")
    old_roots = previous.get("fresh_roots", {})
    if isinstance(old_roots, Mapping) and (str(target) in {str(old_roots.get("target_root", "")),
                                                          str(old_roots.get("output_root", ""))}):
        raise V38RequestError("V38 cannot reuse a consumed V36/V37 root")
    template_binding = previous["v5_overlay_template"]
    template = load_json(template_binding["path"])
    overlay_path, overlay = _make_overlay(previous, template, aux, aux_path,
                                          Path(overlay_output).expanduser(), target)

    runtime = previous.get("runtime_sources")
    if not isinstance(runtime, list):
        raise V38RequestError("previous runtime_sources are missing")
    if any(isinstance(x, Mapping) and x.get("role") == "executor_v38" for x in runtime):
        raise V38RequestError("executor_v38 is already bound in previous request")
    python = next((x for x in runtime if isinstance(x, Mapping) and x.get("role") == "python_executable"), None)
    if not isinstance(python, Mapping):
        raise V38RequestError("literal venv Python binding is missing")
    invocation = python.get("invocation_path", python.get("path"))
    _require_file(invocation, "literal venv Python invocation")
    wrapper = {"role": "executor_v38", "path": str(V38_EXECUTOR),
               "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v38.py",
               "bytes": int(V38_EXECUTOR.stat().st_size),
               "mtime_ns": int(V38_EXECUTOR.stat().st_mtime_ns),
               "mode_bits": int(stat.S_IMODE(V38_EXECUTOR.stat().st_mode)),
               "sha256": sha256_file(V38_EXECUTOR), "invocation_path": str(V38_EXECUTOR),
               "forward_only": True}
    sources = [dict(x) for x in previous["source_entries"]]
    existing_source_paths = {str(Path(str(x["path"])).expanduser()) for x in sources}
    added_source_entries: list[dict[str, Any]] = []
    for item in aux["entries"]:
        path = str(item["path"])
        # V36 already binds PartOut_000.obi4 as a small source under
        # ``sources/0016-*``.  The 405-tree contract needs the same immutable
        # bytes once more at the raw data-root name, so the overlay gets a
        # second target while the V34 source-entry list keeps one unique source
        # path (its validator rejects duplicate source paths).
        if path in existing_source_paths:
            existing = next(x for x in sources if str(Path(str(x["path"])).expanduser()) == path)
            if int(existing.get("bytes", -1)) != int(item["bytes"]):
                raise V38RequestError(f"existing auxiliary source byte stat differs: {path}")
            if _require_sha(existing.get("sha256"), "existing auxiliary source.sha256") != item["sha256"]:
                raise V38RequestError(f"existing auxiliary source SHA binding differs: {path}")
            continue
        added = dict(item)
        added.update({"role": f"raw_auxiliary:{item['filename']}",
                      "target_relative_path": str(item["filename"]),
                      "preserve_mode": True, "required_executable": False,
                      "source_mode_bits": int(item["mode_bits"])})
        added_source_entries.append(added)
        existing_source_paths.add(path)
    sidecar = {"role": "raw_auxiliary_binding_v37", "path": str(aux_path),
               "bytes": int(aux_path.stat().st_size), "mtime_ns": int(aux_path.stat().st_mtime_ns),
               "mode_bits": int(stat.S_IMODE(aux_path.stat().st_mode)),
               "sha256": sha256_file(aux_path), "target_relative_path": "sources/0038-raw-auxiliary-binding-v37.json",
               "preserve_mode": True, "required_executable": False,
               "source_mode_bits": int(stat.S_IMODE(aux_path.stat().st_mode))}
    sources.extend(added_source_entries)
    sources.append(sidecar)
    request = copy.deepcopy(previous)
    request["request_id"] = str(previous.get("request_id", "f2-s1-v36")) + "-v38"
    request["fresh_roots"] = {"target_root": str(target), "output_root": str(output)}
    request["source_entries"] = sources
    request["runtime_sources"] = [*runtime, wrapper]
    request["v5_overlay_template"] = {
        "path": str(overlay_path), "sha256": sha256_file(overlay_path),
        "canonical_sha256": overlay["sha256"], "forward_v38": True,
    }
    execution = dict(request.get("execution", {}))
    command = list(execution.get("command", []))
    if not command:
        command = [str(invocation), "-B", "-I", str(V38_EXECUTOR), "run"]
    else:
        command[0] = str(invocation)
        # V34 command is [python,-B,-I,script,...]; index 3 is the script.
        if len(command) >= 4 and command[2] == "-I":
            command[3] = str(V38_EXECUTOR)
        else:
            try:
                command[command.index(str(previous.get("execution", {}).get("command", [""])[3]))] = str(V38_EXECUTOR)
            except (ValueError, IndexError):
                command = [str(invocation), "-B", "-I", str(V38_EXECUTOR), "run"] + command[4:]
    execution["command"] = command
    execution.update({
        "v38_import_closure": True,
        "private_transitive_import_preflight": True,
        "bootstrap_inserts_only_copied_worker_dir": True,
        "original_path_fallback": "FORBIDDEN",
        "raw_tree_binding": {"file_count": FROZEN_RAW_FILE_COUNT,
                              "frame_count": FROZEN_FRAME_COUNT,
                              "tree_sha256": FROZEN_RAW_TREE_SHA256},
    })
    request["execution"] = execution
    request["forward_v38"] = {
        "schema": FORWARD_SCHEMA,
        "compatibility_envelope": V34_SCHEMA,
        "previous_request": {"path": str(previous_path), "sha256": sha256_file(previous_path)},
        "wrapper": {"path": str(V38_EXECUTOR), "sha256": wrapper["sha256"]},
        # Keep the flat fields consumed by the immutable V38 worker loader.
        "wrapper_path": str(V38_EXECUTOR),
        "wrapper_sha256": wrapper["sha256"],
        "canonical_aliases": {
            "v14_operator": "ds_data02_stage2_f2_replay_v14.py",
            "v15_operator": "ds_data02_stage2_f2_replay_v15.py",
            "v16_operator": "ds_data02_stage2_f2_flux_v16.py",
        },
        "import_order": ["v14_operator", "v15_operator", "v16_operator"],
        "bootstrap": "-B -I plus explicit copied worker directory only",
        "parent_v3_source": {"path": str(PARENT_V3), "sha256": sha256_file(PARENT_V3),
                              "schema": PARENT_V3_SCHEMA},
        "private_operator_roles": [
            {"role": str(x.get("role")), "path": str(x.get("path")),
             "sha256": _require_sha(x.get("sha256"), f"runtime {x.get('role')}.sha256")}
             for x in runtime if isinstance(x, Mapping) and x.get("role") in {
                 "v14_operator", "v15_operator", "v16_operator",
                 "operator_v14", "operator_v15", "operator_v16"}
        ],
        "frozen_raw_tree": {"file_count": FROZEN_RAW_FILE_COUNT,
                            "frame_count": FROZEN_FRAME_COUNT,
                            "tree_sha256": FROZEN_RAW_TREE_SHA256},
        "auxiliary_binding": {"path": str(aux_path), "sha256": sha256_file(aux_path),
                               "entry_count": len(aux["entries"]),
                               "filenames": [str(x["filename"]) for x in aux["entries"]]},
        "payload_sha_phase": "parent_after_same_parent_reservation",
        "parent_missing_fallback_policy": V38_PARENT_FALLBACK,
        "payload_read_during_build": False,
        "hdf5_or_bi4_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    request["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    request["raw_opened"] = False
    request["hdf5_opened"] = False
    request["model_invoked"] = False
    request["cfd_invoked"] = False
    request["qualification"] = dict(UNKNOWN)
    request["sha256"] = canonical_sha(request)
    request_path = write_new(output_request, request)
    return {"status": request["status"], "request": str(request_path),
            "sha256": request["sha256"], "overlay": str(overlay_path),
            "source_entry_count": len(sources), "raw_frame_count": FROZEN_FRAME_COUNT,
            "raw_tree_file_count": FROZEN_RAW_FILE_COUNT,
            "auxiliary_entry_count": len(aux["entries"]),
            "payload_read": False, "hdf5_or_bi4_read": False,
            "qualification": dict(UNKNOWN)}


def _load_parent_v3() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_parent_v3_for_v38_builder", PARENT_V3)
    if spec is None or spec.loader is None:
        raise V38RequestError(f"cannot load parent-v3 builder: {PARENT_V3}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parent(*, executor_request: Path | str, output: Path | str,
                 external_filesystem: Path | str, ledger: Path | str,
                 parent_attempt_id: str, supervisor_output_root: Path | str,
                 home_receipt: Path | str, max_wall_seconds: float = 6000.0,
                 external_bytes: int | None = None,
                 runtime_v6: Path | str | None = None,
                 allow_missing_parent: bool = True) -> dict[str, Any]:
    """Build a fresh parent-v3 request around the V38 executor.

    The parent-v3 implementation performs only metadata/stat validation in
    this call and writes no ledger state.  Missing-parent fallback defaults to
    the scoped, explicit mode so a pre-existing V37 finalization gap cannot
    reappear as an uncharged terminal path.
    """
    executor_path = _require_file(executor_request, "V38 executor request")
    executor = load_json(executor_path)
    if executor.get("schema") != V34_SCHEMA or executor.get("status") != "READY_FOR_PARENT_STAGE2_GUARD":
        raise V38RequestError("executor is not a parent-ready V34-envelope V38 request")
    if executor.get("sha256") != canonical_sha(executor):
        raise V38RequestError("V38 executor canonical SHA differs")
    parent = _load_parent_v3()
    runtime = Path(runtime_v6).expanduser() if runtime_v6 is not None else parent.RUNTIME_V6_DEFAULT
    value = parent.build_request(
        executor_request=executor_path, output=output,
        external_filesystem=external_filesystem, ledger_path=ledger,
        parent_attempt_id=parent_attempt_id, max_wall_seconds=max_wall_seconds,
        external_bytes=external_bytes, home_receipt_bytes=64 * 1024,
        home_receipt_path=home_receipt, supervisor_output_root=supervisor_output_root,
        home_path=Path("/home/jade"), runtime_v6=runtime,
        executor_script=V38_EXECUTOR, allow_missing_parent=allow_missing_parent,
    )
    # Parent-v3 already canonicalizes and writes the request.  Re-open only
    # the small JSON to assert the full closure; never rewrite that fresh file.
    written = load_json(output)
    if written.get("schema") != PARENT_V3_SCHEMA:
        raise V38RequestError("parent-v3 builder returned an unexpected schema")
    script = next((x for x in written.get("static_bindings", [])
                   if isinstance(x, Mapping) and x.get("role") == "executor_v34"), None)
    if not isinstance(script, Mapping) or Path(str(script.get("path"))).expanduser() != V38_EXECUTOR:
        raise V38RequestError("parent-v3 request does not bind the V38 executor script")
    if written.get("executor_request", {}).get("sha256") != sha256_file(executor_path):
        raise V38RequestError("parent-v3 request does not bind the fresh V38 executor bytes")
    parent_binding = written.get("parent_resource_binding", {})
    if bool(parent_binding.get("allow_missing_parent")) != bool(allow_missing_parent):
        raise V38RequestError("parent missing-row policy was not preserved")
    value["parent_request_sha256"] = written.get("sha256")
    value["executor_request_sha256"] = sha256_file(executor_path)
    value["parent_schema"] = PARENT_V3_SCHEMA
    value["allow_missing_parent"] = bool(allow_missing_parent)
    value["qualification"] = dict(UNKNOWN)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    executor = sub.add_parser("build-executor")
    executor.add_argument("--previous-request", type=Path, required=True)
    executor.add_argument("--auxiliary-binding", type=Path, required=True)
    executor.add_argument("--output-request", type=Path, required=True)
    executor.add_argument("--overlay-output", type=Path, required=True)
    executor.add_argument("--target-root", type=Path, required=True)
    executor.add_argument("--output-root", type=Path, required=True)
    parent = sub.add_parser("build-parent")
    parent.add_argument("--executor-request", type=Path, required=True)
    parent.add_argument("--output", type=Path, required=True)
    parent.add_argument("--external-filesystem", type=Path, required=True)
    parent.add_argument("--ledger", type=Path, required=True)
    parent.add_argument("--parent-attempt-id", required=True)
    parent.add_argument("--supervisor-output-root", type=Path, required=True)
    parent.add_argument("--home-receipt", type=Path, required=True)
    parent.add_argument("--max-wall-seconds", type=float, default=6000.0)
    parent.add_argument("--external-bytes", type=int)
    parent.add_argument("--runtime-v6", type=Path)
    parent.add_argument("--disallow-missing-parent", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-executor":
            result = build_executor(
                previous_request=args.previous_request, auxiliary_binding=args.auxiliary_binding,
                output_request=args.output_request, overlay_output=args.overlay_output,
                target_root=args.target_root, output_root=args.output_root)
        else:
            result = build_parent(
                executor_request=args.executor_request, output=args.output,
                external_filesystem=args.external_filesystem, ledger=args.ledger,
                parent_attempt_id=args.parent_attempt_id,
                supervisor_output_root=args.supervisor_output_root,
                home_receipt=args.home_receipt, max_wall_seconds=args.max_wall_seconds,
                external_bytes=args.external_bytes, runtime_v6=args.runtime_v6,
                allow_missing_parent=not args.disallow_missing_parent)
    except (V38RequestError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 V38 request builder: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
