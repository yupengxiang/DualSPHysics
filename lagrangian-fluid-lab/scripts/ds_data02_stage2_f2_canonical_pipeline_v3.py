#!/usr/bin/env python3
"""Build and bind the canonical F2 row-65 portable pipeline.

This is an additive successor to the unconsumed v2 contract.  It fixes two
source-level ABI errors in that contract: the restorer is the real
``ds_data02_stage2_f2_native_raw_to_label_loader_v1.py`` and its CLI action is
``prepare``.  The worker and label producer also retain their required
``run`` subcommands.  The reader is an import entrypoint; its module has no
standalone CLI.

Only bounded JSON and source code are read while building or validating a
contract.  BI4/OBI4/IBI4, HDF5, CSV, JSONL, typed, and label payloads remain
parent-reservation inputs.  A bound request records copied source hashes and
fresh target stats; it never permits the historical row-78 alias or an
original-path fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-canonical-pipeline-contract.v3"
REQUEST_SCHEMA = "ds02.stage2.f2-canonical-pipeline-request.v3"
TARGET_BINDING_SCHEMA = "ds02.stage2.f2-canonical-pipeline-target-binding.v2"
PLAN_SCHEMA = "ds02.stage2.f2-canonical-raw-anchor-plan.v3"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CANONICAL_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
HISTORICAL_ALIAS_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
PENDING_RAW_SHA = "PENDING_PARENT_GUARD_CONTENT_SHA256"
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

MODULE_SPECS: dict[str, tuple[str, str]] = {
    "raw_converter": ("ds_data02_f5_bi4.py", "ds_data02_f5_bi4.convert_direct"),
    "v14_operator": ("ds_data02_stage2_f2_replay_v14.py", "historical row-78 code dependency"),
    "v15_operator": ("ds_data02_stage2_f2_replay_v15.py", "replay_trajectory_v15"),
    "v16_operator": ("ds_data02_stage2_f2_flux_v16.py", "forward_result"),
    "worker": ("ds_data02_stage2_f2_native_raw_to_typed_label_v2.py", "run"),
}

# ``argv_tail`` is the real CLI shape after the target script.  The direct
# converter and scorer have no subcommand; the loader, worker, and label
# producer do.  v15 is deliberately an import entrypoint because that source
# has no command-line parser.
STAGE_SPECS: dict[str, dict[str, Any]] = {
    "canonical_adapter": {
        "filename": "ds_data02_stage2_f2_canonical_semantics_adapter_v1.py",
        "entrypoint": "validate", "invocation": "cli", "payload": False,
        "phase": "METADATA_PRECHECK",
        "argv_tail": ["--binding", "<canonical-binding>", "--output", "<adapter-report>"],
    },
    "raw_converter": {
        "filename": "ds_data02_f5_bi4.py", "entrypoint": "convert_direct",
        "invocation": "cli", "payload": True, "phase": "AFTER_PARENT_RESERVATION",
        "argv_tail": ["--data-root", "<raw-data-root>", "--generated-xml", "<generated-xml>",
                       "--output", "<typed-h5>", "--report", "<converter-report>",
                       "--decoder", "<decoder>", "--solver-receipt", "<solver-receipt>",
                       "--gencase-receipt", "<gencase-receipt>", "--owner-metadata",
                       "<owner-metadata>", "--skip-partvtk-validation"],
    },
    "reader": {
        "filename": "ds_data02_stage2_f2_replay_v15.py", "entrypoint": "read_hdf5_window_v15",
        "invocation": "python_import_entrypoint", "payload": True,
        "phase": "AFTER_PARENT_RESERVATION", "argv_tail": [],
    },
    "restorer": {
        "filename": "ds_data02_stage2_f2_native_raw_to_label_loader_v1.py",
        "entrypoint": "prepare_plan", "invocation": "cli", "payload": False,
        "phase": "AFTER_PARENT_RESERVATION",
        "argv_tail": ["prepare", "--bundle", "<bundle>", "--path-map", "<path-map>",
                       "--output-dir", "<restore-plan>", "--io-slot-approved"],
    },
    "worker": {
        "filename": "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py",
        "entrypoint": "run", "invocation": "cli", "payload": True,
        "phase": "AFTER_PARENT_RESERVATION",
        "argv_tail": ["run", "--request", "<bound-request>", "--output-dir", "<fresh-output>",
                       "--io-slot-approved", "--run-labels"],
    },
    "label_producer": {
        "filename": "ds_data02_stage2_f2_typed_labels_only_v1.py", "entrypoint": "run",
        "invocation": "cli", "payload": True, "phase": "AFTER_PARENT_RESERVATION",
        "argv_tail": ["run", "--request", "<typed-label-request>", "--output-dir",
                       "<labels-output>", "--io-slot-approved"],
    },
    "portable_scorer": {
        "filename": "ds_data02_stage2_f2_replay_runner_v23.py", "entrypoint": "run",
        "invocation": "cli", "payload": True, "phase": "AFTER_PARENT_RESERVATION",
        "argv_tail": ["--profile", "<portable-profile>", "--request", "<v15-request>",
                       "--path-map", "<path-map>", "--io-slot-approved"],
    },
}
STAGE_ORDER = tuple(STAGE_SPECS)
MODULE_ORDER = tuple(MODULE_SPECS)


class PipelineError(ValueError):
    pass


def _fail(message: str) -> None:
    raise PipelineError(message)


def _signature(path: Path, role: str) -> dict[str, int]:
    try:
        value = path.lstat()
    except OSError as error:
        _fail(f"{role} cannot be stat'ed: {path}: {error}")
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
        _fail(f"{role} must be a regular non-symlink file: {path}")
    return {"st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns),
            "mode_bits": int(stat.S_IMODE(value.st_mode))}


def _read_bounded(path: Path | str, role: str, limit: int) -> bytes:
    target = Path(path).expanduser()
    before = _signature(target, role)
    if before["bytes"] > limit:
        _fail(f"{role} exceeds bounded read: {target}")
    try:
        with target.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as error:
        _fail(f"{role} cannot be read: {target}: {error}")
    after = _signature(target, role)
    if before != after or len(data) != after["bytes"] or len(data) > limit:
        _fail(f"{role} changed during bounded read: {target}")
    return data


def _json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = json.loads(_read_bounded(target, role, MAX_METADATA_BYTES).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        _fail(f"{role} is not bounded JSON: {target}: {error}")
    if not isinstance(value, dict):
        _fail(f"{role} must be a JSON object")
    return value


def _sha(path: Path | str, role: str, *, limit: int = MAX_SOURCE_BYTES) -> str:
    return hashlib.sha256(_read_bounded(path, role, limit)).hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key not in {"sha256", "file_sha256"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True,
                         allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _repo_script(repo_root: Path, filename: str, role: str) -> Path:
    candidate = (repo_root / "lagrangian-fluid-lab" / "scripts" / filename).resolve(strict=False)
    if not _inside(candidate, repo_root) or not candidate.is_file() or candidate.is_symlink():
        _fail(f"{role} source is missing/nonlocal: {candidate}")
    return candidate


def _check_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA:
        _fail("canonical input plan schema differs")
    selection = plan.get("selection")
    if not isinstance(selection, Mapping) or selection.get("current_index") != 65:
        _fail("pipeline requires canonical CURRENT row 65")
    if selection.get("physical_case_id") != CANONICAL_ID:
        _fail("pipeline case is not canonical RX047/ROT075")
    if selection.get("historical_alias_rejected") != HISTORICAL_ALIAS_ID:
        _fail("historical alias rejection is not bound")
    current = plan.get("current_binding")
    if not isinstance(current, Mapping) or current.get("sha256") != CURRENT_SHA:
        _fail("CURRENT source SHA is not pinned")
    raw = plan.get("raw_binding")
    if not isinstance(raw, Mapping) or raw.get("expected_raw_tree_sha256") != PENDING_RAW_SHA:
        _fail("raw tree content must remain parent-deferred")
    overlay = plan.get("request_overlay")
    request = overlay.get("request") if isinstance(overlay, Mapping) else None
    if not isinstance(request, Mapping) or request.get("schema") != \
            "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2":
        _fail("canonical worker request ABI differs")
    if request.get("source_hashes_preverified_by_parent") is not False:
        _fail("canonical worker request must defer source hashes to parent")
    if overlay.get("no_original_path_fallback") is not True:
        _fail("canonical overlay must reject original-path fallback")


def _source_record(path: Path, role: str, target_relative: str,
                   entrypoint: str, source_kind: str) -> dict[str, Any]:
    return {"role": role, "source_kind": source_kind,
            "source_path_provenance": str(path), "source_sha256": _sha(path, role),
            "source_stat": _signature(path, role), "target_relative_path": target_relative,
            "entrypoint": entrypoint, "target_sha256": None, "target_stat": None,
            "content_verified_after_reservation": False}


def _command(role: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    target = f"<target:{role}>"
    if spec["invocation"] == "python_import_entrypoint":
        return {"stage": role, "entrypoint": spec["entrypoint"],
                "invocation": "python_import_entrypoint", "target": target,
                "import_roots": ["<target:runtime_modules>", "<target:runtime_stages>"],
                "argv_tail": [], "payload_read": True, "phase": spec["phase"],
                "source_fallback": "REJECT"}
    return {"stage": role, "entrypoint": spec["entrypoint"], "invocation": "cli",
            "argv_template": [PYTHON, "-B", "-I", target, *spec["argv_tail"]],
            "payload_read": spec["payload"], "phase": spec["phase"],
            "source_fallback": "REJECT", "literal_venv": True}


def build_contract(*, plan_path: Path | str, repo_root: Path | str,
                   output_path: Path | str) -> dict[str, Any]:
    output = Path(output_path).expanduser().absolute()
    if output.exists():
        _fail(f"contract output already exists: {output}")
    plan_target = Path(plan_path).expanduser().absolute()
    plan = _json(plan_target, "canonical row-65 plan")
    _check_plan(plan)
    repo = Path(repo_root).expanduser().absolute()
    if not repo.is_dir():
        _fail(f"repository root is missing: {repo}")
    modules: list[dict[str, Any]] = []
    for role, (filename, entrypoint) in MODULE_SPECS.items():
        path = _repo_script(repo, filename, role)
        modules.append(_source_record(path, role, f"runtime/modules/{filename}",
                                      entrypoint, "pinned_runtime_module"))
    stages: list[dict[str, Any]] = []
    for role, spec in STAGE_SPECS.items():
        path = _repo_script(repo, str(spec["filename"]), role)
        stages.append(_source_record(path, role, f"runtime/stages/{spec['filename']}",
                                     str(spec["entrypoint"]), "pipeline_stage"))
    contract: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_READY_FOR_PARENT_COPY_AND_HASH",
        "contract_id": "f2-s1-canonical-row65-pipeline-v3-root-forward-pending",
        "case_identity": {"current_index": 65, "family_id": "F2",
                           "physical_case_id": CANONICAL_ID,
                           "historical_alias_rejected": HISTORICAL_ALIAS_ID,
                           "identity_key": "(Zone,Idp)"},
        "current_binding": {"path": plan.get("current_binding", {}).get("path"),
                             "sha256": CURRENT_SHA, "source_schema": "ds02.stage2.current336.v1"},
        "anchor_binding": {"plan_path": str(plan_target),
                           "plan_file_sha256": _sha(plan_target, "canonical row-65 plan"),
                           "raw_frame_count": 401, "raw_expected_file_count": 405,
                           "raw_tree_sha256": PENDING_RAW_SHA,
                           "content_phase": "AFTER_PARENT_RESERVATION",
                           "alias_fallback": "REJECT"},
        "modules": modules, "stages": stages,
        "stage_order": list(STAGE_ORDER), "module_order": list(MODULE_ORDER),
        "stage_abi": {role: {"filename": spec["filename"], "entrypoint": spec["entrypoint"],
                              "invocation": spec["invocation"],
                              "argv_tail": list(spec["argv_tail"])}
                      for role, spec in STAGE_SPECS.items()},
        "legacy_operator_policy": {"v14_v15_v16": "CODE_DEPENDENCY_ONLY",
                                    "row78_semantic_identity": "REJECT",
                                    "canonical_adapter_required_first": True},
        "execution": {"python_executable": PYTHON, "argv0_policy": "LITERAL_PINNED_VENV",
                       "source_fallback": "REJECT", "input_open_policy": "COPIED_NAMESPACE_ONLY",
                       "output_root_policy": "NEW_ATTEMPT_OWNED_ONLY", "max_wall_seconds": 3600,
                       "threads": 1, "parent_death_cleanup": True, "bounded_logs": True,
                       "commands": [_command(role, spec) for role, spec in STAGE_SPECS.items()]},
        "source_closure": {
            "required_roles": [f"module:{role}" for role in MODULE_ORDER] +
                               [f"stage:{role}" for role in STAGE_ORDER],
            "required_runtime_imports": ["runtime/modules", "runtime/stages"],
            "all_actionable_paths_must_be_target_relative": True,
            "original_path_fallback": "FORBIDDEN",
            "raw_and_typed_content": "PARENT_GUARD_REQUIRED",
        },
        "scientific_contract": {"raw_tree_sha256": PENDING_RAW_SHA,
                                "typed_output": "PENDING_PARENT_GUARD",
                                "labels": "PENDING_PARENT_GUARD",
                                "portable_scorer": "PENDING_PARENT_GUARD",
                                "model_invoked": False, "cfd_invoked": False,
                                "qualification": dict(UNKNOWN_QUALIFICATION)},
        "resource_contract": {"raw_frames": 401, "raw_files": 405,
                              "raw_hash_passes": 2, "scratch": "attempt-owned-and-measured",
                              "storage": "parent-computes-copy-and-peak-from-statistics"},
    }
    contract["sha256"] = canonical_sha(contract)
    file_sha = _write_new(output, contract)
    return {"schema": SCHEMA, "status": contract["status"],
            "contract": {"path": str(output), "file_sha256": file_sha,
                          "canonical_sha256": contract["sha256"]},
            "module_count": len(modules), "stage_count": len(stages),
            "raw_payload_read": False, "ledger_mutated": False,
            "qualification": dict(UNKNOWN_QUALIFICATION)}


def _role_map(value: Any, label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        _fail(f"{label} must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            _fail(f"{label} has malformed role")
        role = str(item["role"])
        if role in result:
            _fail(f"{label} repeats role {role}")
        result[role] = item
    return result


def _target_path(item: Mapping[str, Any], expected: Mapping[str, Any], namespace: Path,
                 role: str) -> Path:
    value = item.get("target_path")
    if isinstance(value, str):
        target = Path(value).expanduser().resolve(strict=False)
    else:
        relative = item.get("target_relative_path", expected.get("target_relative_path"))
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or \
                any(part in {"", ".", ".."} for part in Path(relative).parts):
            _fail(f"{role} target_relative_path escapes copied namespace")
        target = (namespace / relative).resolve(strict=False)
    if not _inside(target, namespace) or target == namespace or target.is_symlink() or not target.is_file():
        _fail(f"{role} target is outside/non-regular copied namespace: {target}")
    return target


def _bound_record(item: Mapping[str, Any], expected: Mapping[str, Any], namespace: Path,
                  role: str, *, record_role: str | None = None) -> dict[str, Any]:
    target = _target_path(item, expected, namespace, role)
    source_sha = expected.get("source_sha256")
    if item.get("source_sha256") != source_sha:
        _fail(f"{role} binding source SHA differs from contract")
    actual_sha = _sha(target, f"{role} copied target")
    if actual_sha != source_sha:
        _fail(f"{role} copied target SHA differs")
    if item.get("content_verified_after_reservation") is not True:
        _fail(f"{role} target lacks after-reservation content verification")
    return {"role": record_role or role,
            "source_path_provenance": expected.get("source_path_provenance"),
            "source_sha256": source_sha, "target_path": str(target),
            "target_relative_path": str(target.relative_to(namespace)),
            "target_sha256": actual_sha, "target_stat": _signature(target, role),
            "content_verified_after_reservation": True}


def _bound_command(command: Mapping[str, Any], targets: Mapping[str, str]) -> dict[str, Any]:
    value = dict(command)
    if isinstance(value.get("argv_template"), list):
        value["argv"] = [targets.get(item, item) if isinstance(item, str) else item
                          for item in value["argv_template"]]
    if isinstance(value.get("target"), str):
        value["target_path"] = targets.get(value["target"], value["target"])
        value["import_roots"] = [targets.get(item, item) for item in value.get("import_roots", [])]
    return value


def bind_contract(*, contract_path: Path | str, binding_path: Path | str,
                  namespace_root: Path | str, output_path: Path | str,
                  fresh_output_root: Path | str, attempt_id: str) -> dict[str, Any]:
    output = Path(output_path).expanduser().absolute()
    if output.exists():
        _fail(f"request output already exists: {output}")
    contract_target = Path(contract_path).expanduser().absolute()
    contract = _json(contract_target, "canonical pipeline contract")
    validate_contract(contract_target)
    binding = _json(binding_path, "canonical pipeline target binding")
    if binding.get("schema") != TARGET_BINDING_SCHEMA:
        _fail("target binding schema differs")
    namespace = Path(namespace_root).expanduser().absolute()
    if not namespace.is_dir():
        _fail(f"copied namespace is missing: {namespace}")
    expected_modules = _role_map(contract.get("modules"), "contract modules")
    expected_stages = _role_map(contract.get("stages"), "contract stages")
    supplied_modules = _role_map(binding.get("modules"), "binding modules")
    supplied_stages = _role_map(binding.get("stages"), "binding stages")
    if set(supplied_modules) != set(expected_modules) or set(supplied_stages) != set(expected_stages):
        _fail("target binding roles differ from contract")
    modules = [_bound_record(supplied_modules[role], expected_modules[role], namespace,
                             f"module:{role}", record_role=role)
               for role in MODULE_ORDER]
    stages = [_bound_record(supplied_stages[role], expected_stages[role], namespace,
                            f"stage:{role}", record_role=role)
              for role in STAGE_ORDER]
    fresh = Path(fresh_output_root).expanduser().absolute()
    if not _inside(fresh, namespace) or fresh == namespace:
        _fail("fresh output root must be under copied namespace")
    if fresh.exists() and any(fresh.iterdir()):
        _fail("fresh output root must be new and empty")
    if not isinstance(attempt_id, str) or not attempt_id or "/" in attempt_id or ".." in attempt_id:
        _fail("attempt_id is unsafe")
    targets = {f"<target:module:{item['role']}>": item["target_path"] for item in modules}
    targets.update({f"<target:{item['role']}>": item["target_path"] for item in stages})
    targets["<target:runtime_modules>"] = str(namespace / "runtime/modules")
    targets["<target:runtime_stages>"] = str(namespace / "runtime/stages")
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
        "request_id": f"f2-s1-canonical-row65-pipeline-v3-{attempt_id}",
        "attempt_id": attempt_id, "case_identity": dict(contract["case_identity"]),
        "source_binding": {"contract_path": str(contract_target),
                           "contract_file_sha256": _sha(contract_target, "pipeline contract"),
                           "target_binding_path": str(Path(binding_path).expanduser().absolute()),
                           "target_binding_file_sha256": _sha(binding_path, "target binding"),
                           "current_sha256": CURRENT_SHA, "raw_tree_sha256": PENDING_RAW_SHA,
                           "namespace_root": str(namespace), "source_fallback": "REJECT"},
        "modules": modules, "stages": stages,
        "stage_order": list(STAGE_ORDER), "module_order": list(MODULE_ORDER),
        "execution": {"python_executable": PYTHON, "argv0_policy": "LITERAL_PINNED_VENV",
                       "namespace_root": str(namespace), "fresh_output_root": str(fresh),
                       "max_wall_seconds": contract["execution"]["max_wall_seconds"], "threads": 1,
                       "parent_death_cleanup": True, "source_fallback": "REJECT",
                       "payload_read_phase": "AFTER_PARENT_RESERVATION",
                       "commands": [_bound_command(command, targets)
                                    for command in contract["execution"]["commands"]]},
        "raw_binding": {"frame_count": 401, "expected_file_count": 405,
                        "expected_raw_tree_sha256": PENDING_RAW_SHA,
                        "source_hashes_preverified_by_parent": False,
                        "content_phase": "AFTER_PARENT_RESERVATION"},
        "pipeline": {"schema": SCHEMA, "canonical_adapter_first": True,
                     "legacy_alias_semantics": "PROVENANCE_ONLY_ROW78_REJECTED",
                     "converter_reader_restorer_worker_label_portable_scorer": "BOUND"},
        "outputs": {"root": str(fresh), "must_be_new": True,
                    "typed": "PENDING_PARENT_GUARD", "labels": "PENDING_PARENT_GUARD",
                    "portable_score": "PENDING_PARENT_GUARD"},
        "qualification": dict(UNKNOWN_QUALIFICATION), "model_invoked": False,
        "cfd_invoked": False, "scientific_credit": "NONE_UNTIL_PARENT_CHAIN_COMPLETES",
    }
    request["sha256"] = canonical_sha(request)
    file_sha = _write_new(output, request)
    return {"schema": REQUEST_SCHEMA, "status": request["status"],
            "request": {"path": str(output), "file_sha256": file_sha,
                         "canonical_sha256": request["sha256"]},
            "module_count": len(modules), "stage_count": len(stages),
            "raw_payload_read": False, "ledger_mutated": False,
            "qualification": dict(UNKNOWN_QUALIFICATION)}


def validate_contract(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().absolute()
    contract = _json(target, "canonical pipeline contract")
    if contract.get("schema") != SCHEMA or contract.get("sha256") != canonical_sha(contract):
        _fail("pipeline contract schema/SHA differs")
    identity = contract.get("case_identity")
    if not isinstance(identity, Mapping) or identity.get("current_index") != 65 or \
            identity.get("physical_case_id") != CANONICAL_ID or \
            identity.get("historical_alias_rejected") != HISTORICAL_ALIAS_ID:
        _fail("contract identity is not canonical row 65")
    if contract.get("current_binding", {}).get("sha256") != CURRENT_SHA:
        _fail("contract CURRENT SHA differs")
    if contract.get("anchor_binding", {}).get("raw_tree_sha256") != PENDING_RAW_SHA:
        _fail("contract claims a pre-guard raw tree hash")
    module_map = _role_map(contract.get("modules"), "contract modules")
    stage_map = _role_map(contract.get("stages"), "contract stages")
    if set(module_map) != set(MODULE_SPECS) or set(stage_map) != set(STAGE_SPECS):
        _fail("contract source role closure is incomplete")
    for role, (filename, _) in MODULE_SPECS.items():
        item = module_map[role]
        if Path(str(item.get("source_path_provenance", ""))).name != filename:
            _fail(f"module {role} filename differs")
        if _sha(item["source_path_provenance"], f"module:{role}") != item.get("source_sha256"):
            _fail(f"module {role} source SHA changed")
    for role, spec in STAGE_SPECS.items():
        item = stage_map[role]
        if Path(str(item.get("source_path_provenance", ""))).name != spec["filename"]:
            _fail(f"stage {role} filename differs")
        if _sha(item["source_path_provenance"], f"stage:{role}") != item.get("source_sha256"):
            _fail(f"stage {role} source SHA changed")
        if item.get("target_relative_path", "").startswith("/") or ".." in Path(str(item.get("target_relative_path"))).parts:
            _fail(f"stage {role} target path escapes copied namespace")
    commands = {str(item.get("stage")): item for item in contract.get("execution", {}).get("commands", [])}
    if set(commands) != set(STAGE_SPECS):
        _fail("execution command closure is incomplete")
    for role, spec in STAGE_SPECS.items():
        command = commands[role]
        if command.get("invocation") != spec["invocation"] or command.get("entrypoint") != spec["entrypoint"]:
            _fail(f"stage {role} invocation ABI differs")
        if role in {"restorer", "worker", "label_producer"}:
            argv = command.get("argv_template")
            if not isinstance(argv, list) or spec["argv_tail"][0] not in argv:
                _fail(f"stage {role} required CLI subcommand is missing")
    if contract.get("execution", {}).get("python_executable") != PYTHON:
        _fail("contract interpreter is not the literal pinned venv")
    return {"schema": "ds02.stage2.f2-canonical-pipeline-validation.v3",
            "status": "VALIDATED_SOURCE_BOUND_PARENT_IO_SLOT_REQUIRED",
            "contract_path": str(target), "contract_sha256": contract["sha256"],
            "canonical_row": 65, "stage_count": len(stage_map),
            "module_count": len(module_map), "raw_payload_read": False,
            "qualification": dict(UNKNOWN_QUALIFICATION)}


def validate_bound(path: Path | str) -> dict[str, Any]:
    request_path = Path(path).expanduser().absolute()
    request = _json(request_path, "canonical pipeline request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        _fail("canonical pipeline request schema/SHA differs")
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or identity.get("current_index") != 65 or \
            identity.get("physical_case_id") != CANONICAL_ID:
        _fail("bound request is not canonical row 65")
    if request.get("source_binding", {}).get("source_fallback") != "REJECT":
        _fail("bound request permits source fallback")
    namespace = Path(str(request.get("source_binding", {}).get("namespace_root", ""))).expanduser()
    for section, roles in (("modules", MODULE_ORDER), ("stages", STAGE_ORDER)):
        mapping = _role_map(request.get(section), section)
        for role in roles:
            item = mapping.get(role)
            if item is None:
                _fail(f"bound request lacks {section}.{role}")
            target = Path(str(item.get("target_path", ""))).expanduser()
            if not _inside(target, namespace) or target.is_symlink() or not target.is_file():
                _fail(f"bound request {section}.{role} target is not closed")
            if _sha(target, f"bound {section}.{role}") != item.get("target_sha256"):
                _fail(f"bound request {section}.{role} target SHA changed")
    return {"schema": "ds02.stage2.f2-canonical-pipeline-validation.v3",
            "status": "VALIDATED_COPIED_SOURCE_BOUND_PARENT_IO_SLOT_REQUIRED",
            "request_path": str(request_path), "request_sha256": request["sha256"],
            "canonical_row": 65, "raw_payload_read": False,
            "qualification": dict(UNKNOWN_QUALIFICATION)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-contract")
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate-contract")
    check.add_argument("--contract", type=Path, required=True)
    bound = sub.add_parser("validate-bound")
    bound.add_argument("--request", type=Path, required=True)
    bind = sub.add_parser("bind")
    bind.add_argument("--contract", type=Path, required=True)
    bind.add_argument("--binding", type=Path, required=True)
    bind.add_argument("--namespace-root", type=Path, required=True)
    bind.add_argument("--fresh-output-root", type=Path, required=True)
    bind.add_argument("--attempt-id", required=True)
    bind.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-contract":
            result = build_contract(plan_path=args.plan, repo_root=args.repo_root, output_path=args.output)
        elif args.command == "validate-contract":
            result = validate_contract(args.contract)
        elif args.command == "validate-bound":
            result = validate_bound(args.request)
        else:
            result = bind_contract(contract_path=args.contract, binding_path=args.binding,
                                   namespace_root=args.namespace_root, output_path=args.output,
                                   fresh_output_root=args.fresh_output_root, attempt_id=args.attempt_id)
    except (OSError, PipelineError, json.JSONDecodeError, ValueError) as error:
        print(f"canonical pipeline v3: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
