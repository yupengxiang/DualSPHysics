#!/usr/bin/env python3
"""Build a ROOT191 V3 request from the main worktree's frozen evidence.

This is a metadata-only admission helper.  It imports the already integrated
ROOT191 V3 implementation from the main worktree, binds its evaluator/runtime
roles to that same worktree, and records the literal project venv invocation.
The 179C V66 request is used only as a small provenance envelope: its embedded
``v15_replay_request`` entry must point to the separately bound V15 request.
The V66 solver request is never accepted as the frozen replay request.

The helper reads bounded JSON/code metadata and H5 stat declarations.  It does
not open the deferred V16 result, H5, BI4, native frames, or a solver/evaluator
process.  ROOT owns reservation, admission, and any later ``run`` operation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


MAIN_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SCRIPT_DIR = MAIN_ROOT / "lagrangian-fluid-lab/scripts"
MAIN_V3_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v3.py"
MAIN_V4_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v4.py"
LITERAL_VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")

REQUEST_SCHEMA = "ds02.stage2.f2-root191-typed-only-no-model-evaluator-request.v3"
BUILDER_SCHEMA = "ds02.stage2.f2-root191-v3-primary-builder.v1"
FROZEN_V15_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
V66_PRODUCER_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-parent-request.v64"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_METADATA_BYTES = 32 * 1024 * 1024

STAGE2 = MAIN_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
ROOT200_INNER = STAGE2 / (
    "requests/f2-root200-profile-output-fresh-proof-root-prepared-200-001/"
    "root200-profile-proof-request.json"
)
ROOT200_WRAPPER = STAGE2 / "requests/f2-root200-profile-output-fresh-proof-root-forward-200-001.json"
ROOT200_RECEIPT = DATA_ROOT / (
    "families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/"
    "f2-s1-root200-v14-profile-output-001-root-forward-030-001/execution-receipt.json"
)
ROOT200_CHECKPOINT = STAGE2 / "checkpoints/F2_FRESH_V16_PROFILE_OUTPUT_ROOT_PROOF_V12_ACTUAL_ROOT_VERIFICATION_200.json"
ROOT200_V12_PROOF = DATA_ROOT / (
    "families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/"
    "f2-s1-root200-v14-profile-output-001-root-forward-030-001/fresh-v16-proof-v12.json"
)
PRODUCER_REQUEST = STAGE2 / "requests/f2-s1-root145-v66-root179c-primary-prepared-003.json"
PRODUCER_PARENT_REPORT = DATA_ROOT / (
    "families/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/"
    "f2-s1-v66-root179c-003/actual-returned-parent-report.json"
)
PRODUCER_RECEIPT = DATA_ROOT / (
    "families/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/"
    "f2-s1-v66-root179c-003/execution-receipt.json"
)
PRODUCER_ROOT_PROOF = STAGE2 / "checkpoints/F2_ROOT179C_V66_ACTUAL_CONVERSION_LABEL_INTERFACE_ROOT_VERIFICATION.json"
FROZEN_V15 = STAGE2 / "replay/v15/f2-s1-replay-request-v15-001.json"

AGENT_STAGE2 = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2"
DEFAULT_OUTPUT = AGENT_STAGE2 / (
    "native-reconstruction/root191-v3-primary-agent-20261009/"
    "f2-s1-root191-v3-primary-request.json"
)
DEFAULT_FRESH_ROOT = Path("/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT191_V3_PRIMARY_20261009")
DEFAULT_CASE = "f2-s1-root191-v3-primary-root200-001"
DEFAULT_ATTEMPT = "f2-s1-root191-v3-primary-root200-001-root-forward-030-001"


class PrimaryBuilderError(RuntimeError):
    """A strict main-worktree binding or metadata admission error."""


def _load_main_v3() -> Any:
    if not MAIN_V3_SCRIPT.is_file() or MAIN_V3_SCRIPT.is_symlink():
        raise PrimaryBuilderError(f"main ROOT191 V3 source is unavailable: {MAIN_V3_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ds02_main_root191_v3_primary_builder", MAIN_V3_SCRIPT)
    if spec is None or spec.loader is None:
        raise PrimaryBuilderError(f"cannot import main ROOT191 V3 source: {MAIN_V3_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V3 = _load_main_v3()


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise PrimaryBuilderError(f"expected a regular source file: {path}")
    size = path.stat().st_size
    if size > MAX_METADATA_BYTES:
        raise PrimaryBuilderError(f"metadata source exceeds bounded size: {path}")
    return V3.sha256_file(path, max_bytes=MAX_METADATA_BYTES)


def _json(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PrimaryBuilderError(f"{role} is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise PrimaryBuilderError(f"{role} exceeds bounded metadata size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PrimaryBuilderError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PrimaryBuilderError(f"{role} must be a JSON object")
    return value


def _stat(path: Path) -> dict[str, Any]:
    info = path.stat()
    return {
        "bytes": info.st_size,
        "mode_bits": info.st_mode & 0o7777,
        "mtime_ns": info.st_mtime_ns,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
    }


def _source_binding(role: str, path: Path, *, phase: str, imported: bool = True) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PrimaryBuilderError(f"{role} source is not a regular file: {path}")
    return {
        "role": role,
        "path": str(path),
        "sha256": _sha(path),
        "stat": _stat(path),
        "phase": phase,
        "imported_or_consumed": imported,
    }


def _literal_interpreter_binding() -> dict[str, Any]:
    if not LITERAL_VENV.is_symlink() or not LITERAL_VENV.exists():
        raise PrimaryBuilderError(f"literal project venv interpreter is unavailable: {LITERAL_VENV}")
    if not PYVENV_CFG.is_file() or PYVENV_CFG.is_symlink():
        raise PrimaryBuilderError(f"project pyvenv.cfg is unavailable: {PYVENV_CFG}")
    link = LITERAL_VENV.lstat()
    target = Path(os.path.realpath(LITERAL_VENV))
    if not target.is_file():
        raise PrimaryBuilderError(f"literal venv target is unavailable: {target}")
    return {
        "role": "literal_project_venv_python",
        "invocation_path": str(LITERAL_VENV),
        "invocation_path_is_literal": True,
        "do_not_resolve_argv0": True,
        "symlink_target_provenance": str(target),
        "link_stat": {
            "bytes": link.st_size,
            "mode_bits": link.st_mode & 0o7777,
        },
        "target_stat": _stat(target),
        "pyvenv_cfg": _source_binding("project_pyvenv_cfg", PYVENV_CFG, phase="interpreter_environment"),
        "abi_smoke": "ROOT-owned after reservation; no system-Python fallback",
    }


def _runtime_closure() -> dict[str, Any]:
    names = (
        ("root191_v3_entrypoint", "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v3.py", "executed"),
        ("root191_v2_binding", "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v2.py", "imported"),
        ("root191_v1_binding", "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v1.py", "imported"),
        ("fresh_v16_proof_consumer_v8", "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py", "imported"),
        ("fresh_v16_proof_consumer_v12", "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py", "imported"),
        ("typed_only_evaluator_v1", "ds_data02_stage2_f2_typed_only_evaluator_v1.py", "imported"),
        ("no_model_evaluator_v3", "ds_data02_stage2_f2_no_model_evaluator_v3.py", "transitive_import"),
        ("fresh_proof_request_v66_schema", "ds_data02_stage2_f2_fresh_v16_proof_request_v66.py", "transitive_contract"),
        ("replay_v14_source_contract", "ds_data02_stage2_f2_replay_v14.py", "source_contract"),
        ("replay_v15_source_contract", "ds_data02_stage2_f2_replay_v15.py", "source_contract"),
        ("flux_v16_source_contract", "ds_data02_stage2_f2_flux_v16.py", "source_contract"),
        ("runtime_v2", "ds_data02_runtime_v2.py", "parent_runtime_dependency"),
        ("runtime_v6", "ds_data02_runtime_v6.py", "parent_runtime_dependency"),
    )
    bindings = []
    if MAIN_V4_SCRIPT.is_file() and not MAIN_V4_SCRIPT.is_symlink():
        bindings.append(_source_binding("root191_v4_hardened_entrypoint", MAIN_V4_SCRIPT, phase="executed"))
    for role, filename, phase in names:
        bindings.append(_source_binding(role, SCRIPT_DIR / filename, phase=phase))
    return {
        "schema": "ds02.stage2.root191-main-runtime-closure.v1",
        "main_worktree_root": str(MAIN_ROOT),
        "script_root": str(SCRIPT_DIR),
        "import_mode": "isolated_literal_venv_with_explicit_script_sibling_imports",
        "original_worktree_fallback": "FORBIDDEN",
        "literal_interpreter": _literal_interpreter_binding(),
        "roles": bindings,
        "preferred_entrypoint": str(MAIN_V4_SCRIPT if MAIN_V4_SCRIPT.is_file() else MAIN_V3_SCRIPT),
    }


def _v15_lineage(producer_path: Path, frozen_path: Path) -> dict[str, Any]:
    producer = _json(producer_path, "179C V66 producer request")
    if producer.get("schema") != V66_PRODUCER_SCHEMA:
        raise PrimaryBuilderError("179C producer envelope is not the expected V66 request")
    frozen = _json(frozen_path, "frozen V15 replay request")
    if frozen.get("schema") != FROZEN_V15_SCHEMA:
        raise PrimaryBuilderError("the frozen replay input must be the actual V15 request")
    frozen_sha = _sha(frozen_path)
    matches = []
    for entry in producer.get("source_closure", []):
        if isinstance(entry, Mapping) and entry.get("role") == "v15_replay_request":
            matches.append(entry)
    if len(matches) != 1:
        raise PrimaryBuilderError("179C V66 producer must have exactly one v15_replay_request source entry")
    entry = matches[0]
    if entry.get("expected_sha256") != frozen_sha:
        raise PrimaryBuilderError("179C embedded V15 expected SHA differs from the bound frozen V15 file")
    if entry.get("source_kind") != "V15_EMBEDDED_SOURCE_FILE":
        raise PrimaryBuilderError("179C V15 source entry has the wrong source kind")
    return {
        "schema": "ds02.stage2.root191-v15-lineage.v1",
        "outer_producer_schema": producer.get("schema"),
        "outer_producer_request_path": str(producer_path),
        "outer_producer_request_file_sha256": _sha(producer_path),
        "embedded_role": entry.get("role"),
        "embedded_target_path_provenance": entry.get("path"),
        "embedded_expected_sha256": entry.get("expected_sha256"),
        "embedded_target_content_read_by_builder": False,
        "frozen_request_path": str(frozen_path),
        "frozen_request_file_sha256": frozen_sha,
        "frozen_request_schema": frozen.get("schema"),
        "outer_v66_request_used_as_frozen_v15": False,
    }


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise PrimaryBuilderError(f"refusing to overwrite primary request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def _default_args() -> dict[str, Path]:
    return {
        "root200_inner": ROOT200_INNER,
        "root200_wrapper": ROOT200_WRAPPER,
        "root200_receipt": ROOT200_RECEIPT,
        "root200_checkpoint": ROOT200_CHECKPOINT,
        "root200_v12_proof": ROOT200_V12_PROOF,
        "producer_request": PRODUCER_REQUEST,
        "producer_parent_report": PRODUCER_PARENT_REPORT,
        "producer_receipt": PRODUCER_RECEIPT,
        "producer_root_proof": PRODUCER_ROOT_PROOF,
        "frozen_request": FROZEN_V15,
    }


def build_primary(*, output: Path = DEFAULT_OUTPUT, fresh_output_root: Path = DEFAULT_FRESH_ROOT,
                  case_id: str = DEFAULT_CASE, attempt_id: str = DEFAULT_ATTEMPT,
                  inputs: Mapping[str, Path] | None = None) -> dict[str, Any]:
    paths = _default_args()
    if inputs:
        paths.update({key: Path(value) for key, value in inputs.items()})
    if output.exists() or output.is_symlink():
        raise PrimaryBuilderError(f"refusing to overwrite primary request: {output}")
    lineage = _v15_lineage(paths["producer_request"], paths["frozen_request"])
    # V3 itself performs the complete ROOT200/179C/V15 metadata admission.  It
    # is imported from MAIN_ROOT, so all evaluator bindings start on the main
    # worktree rather than silently referring to this consumer checkout.
    built = V3._build_request(
        root200_inner=paths["root200_inner"].absolute(), root200_wrapper=paths["root200_wrapper"].absolute(),
        root200_receipt=paths["root200_receipt"].absolute(), root200_checkpoint=paths["root200_checkpoint"].absolute(),
        root200_v12_proof=paths["root200_v12_proof"].absolute(), producer_request=paths["producer_request"].absolute(),
        producer_parent_report=paths["producer_parent_report"].absolute(), producer_receipt=paths["producer_receipt"].absolute(),
        producer_root_proof=paths["producer_root_proof"].absolute(), frozen_request=paths["frozen_request"].absolute(),
        output=output.absolute(), case_id=case_id, attempt_id=attempt_id,
        fresh_output_root=fresh_output_root.absolute(),
    )
    request = _json(output, "new ROOT191 V3 request")
    closure = _runtime_closure()
    entrypoint = MAIN_V4_SCRIPT if MAIN_V4_SCRIPT.is_file() and not MAIN_V4_SCRIPT.is_symlink() else MAIN_V3_SCRIPT
    request["evaluator_binding"]["entrypoint"]["path"] = str(entrypoint)
    request["evaluator_binding"]["entrypoint"]["sha256"] = _sha(entrypoint)
    request["execution"].update({
        "python_executable": str(LITERAL_VENV),
        "python_executable_is_literal": True,
        "runtime_root": str(SCRIPT_DIR),
        "runtime_closure_schema": closure["schema"],
        "command_template": [str(LITERAL_VENV), "-B", "-I", str(entrypoint), "run",
                              "--request", "{request}", "--output", "{output}", "--parent-pid", "{parent_pid}"],
    })
    request["root191_primary_builder"] = {
        "schema": BUILDER_SCHEMA,
        "main_worktree_root": str(MAIN_ROOT),
        "request_built_from_main_v3": True,
        "runtime_closure": closure,
        "v15_lineage": lineage,
        "metadata_read_pass": {
            "bounded_json_and_code_sources": True,
            "root200_receipt_checkpoint_v12_proof_read": True,
            "root179c_parent_receipt_root_proof_read": True,
            "frozen_v15_request_read": True,
            "v16_result_content_read": False,
            "typed_h5_content_read": False,
            "bi4_native_frame_content_read": False,
            "solver_or_evaluator_launched": False,
        },
        "deferred_products": {
            "v16_json": {"bytes": 62365973, "sha256": "69d2ea956b86013135c2418a8b3bc9fc2983b8395cb5a62a243d997bb3d914a5", "read_phase": "PARENT_AFTER_RESERVATION"},
            "typed_h5": {"bytes": 1191110528, "sha256": "2a2ef5cf5c0e1f164018466fa4815a4465ab72dbf1071bf60e76c33657288664", "read_phase": "NEVER_BY_THIS_BUILDER_OR_RUN"},
        },
        "resource_limits": {
            "max_wall_seconds": 900.0,
            "max_memory_bytes": 16 * 1024 * 1024 * 1024,
            "max_metadata_bytes_per_file": MAX_METADATA_BYTES,
            "max_deferred_v16_bytes": 62365973,
            "max_report_bytes": 128 * 1024 * 1024,
            "storage_scope": "ROOT parent must reserve and charge actual result/report bytes; builder reserves nothing",
        },
    }
    request["sha256"] = V3.canonical_sha(request)
    # V3 wrote this new file; overwrite only that newly-created file after the
    # main-root binding augmentation.  Existing requests are rejected above.
    output.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    return {
        "schema": BUILDER_SCHEMA,
        "status": "ROOT191_V3_PRIMARY_METADATA_BUILT",
        "request": str(output),
        "request_file_sha256": _sha(output),
        "request_canonical_sha256": request["sha256"],
        "source_frozen_v15": lineage,
        "runtime_role_count": len(closure["roles"]),
        "payload_read": False,
        "hdf5_bi4_native_read": False,
        "solver_or_evaluator_launched": False,
        "qualification": dict(UNKNOWN),
        **built,
    }


def validate_primary(path: Path) -> dict[str, Any]:
    request = _json(path, "ROOT191 V3 primary request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise PrimaryBuilderError("primary request does not use ROOT191 V3 schema")
    result = V3.validate_request(path)
    primary = request.get("root191_primary_builder")
    if not isinstance(primary, Mapping) or primary.get("schema") != BUILDER_SCHEMA:
        raise PrimaryBuilderError("primary builder sidecar is missing")
    if primary.get("main_worktree_root") != str(MAIN_ROOT):
        raise PrimaryBuilderError("primary request is bound to a different main worktree")
    execution = request.get("execution")
    if not isinstance(execution, Mapping) or execution.get("python_executable") != str(LITERAL_VENV):
        raise PrimaryBuilderError("primary command does not preserve literal venv invocation")
    closure = primary.get("runtime_closure")
    if not isinstance(closure, Mapping) or closure.get("main_worktree_root") != str(MAIN_ROOT):
        raise PrimaryBuilderError("main runtime closure is missing")
    command = execution.get("command_template")
    preferred = closure.get("preferred_entrypoint")
    if not isinstance(command, list) or not command or command[0] != str(LITERAL_VENV) or preferred not in command:
        raise PrimaryBuilderError("primary command template is not the isolated main V3 command")
    for binding in closure.get("roles", []):
        if not isinstance(binding, Mapping):
            raise PrimaryBuilderError("runtime closure contains a malformed role")
        source = Path(str(binding.get("path")))
        if binding.get("sha256") != _sha(source):
            raise PrimaryBuilderError(f"runtime source SHA changed: {source}")
    lineage = primary.get("v15_lineage")
    if not isinstance(lineage, Mapping) or lineage.get("frozen_request_schema") != FROZEN_V15_SCHEMA:
        raise PrimaryBuilderError("V15 lineage is missing")
    if lineage.get("outer_v66_request_used_as_frozen_v15") is not False:
        raise PrimaryBuilderError("V66 outer request was incorrectly used as frozen V15")
    return {
        "schema": "ds02.stage2.f2-root191-v3-primary-metadata-preflight.v1",
        "status": "ROOT191_V3_PRIMARY_METADATA_VALIDATED_READY_FOR_PARENT",
        "request": result["request"],
        "runtime_role_count": len(closure.get("roles", [])),
        "payload_read": False,
        "hdf5_bi4_native_read": False,
        "solver_or_evaluator_launched": False,
        "qualification": dict(UNKNOWN),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-primary")
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--fresh-output-root", type=Path, default=DEFAULT_FRESH_ROOT)
    build.add_argument("--case-id", default=DEFAULT_CASE)
    build.add_argument("--attempt-id", default=DEFAULT_ATTEMPT)
    validate = sub.add_parser("validate-primary")
    validate.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-primary":
            value = build_primary(output=args.output, fresh_output_root=args.fresh_output_root,
                                  case_id=args.case_id, attempt_id=args.attempt_id)
        else:
            value = validate_primary(args.request)
    except (PrimaryBuilderError, V3.Root191V3Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT191 V3 primary builder: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
