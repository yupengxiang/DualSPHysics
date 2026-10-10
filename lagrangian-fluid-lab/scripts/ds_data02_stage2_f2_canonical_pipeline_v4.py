#!/usr/bin/env python3
"""Build a parent-ready canonical F2 row-65 execution request.

The v3 source contract names the real seven stages, but its scorer command
stops before the scorer's required ``--output`` argument and leaves the
stage paths as placeholders.  This additive adapter keeps the v3 contract
immutable, adds the missing ABI argument, and emits a concrete attempt-owned
command graph.  Code targets are SHA-bound after copy; raw, typed, and label
content remain parent-reservation inputs.

This module intentionally delegates source discovery and code-copy checks to
the immutable v3 implementation.  The generated v4 request is a new file
with a new schema and never mutates a v3 contract, request, or target tree.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any, Iterator, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V3_PATH = SCRIPT.with_name("ds_data02_stage2_f2_canonical_pipeline_v3.py")
_SPEC = importlib.util.spec_from_file_location("f2_canonical_pipeline_v3_for_v4", V3_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import failure is fatal
    raise RuntimeError(f"cannot load immutable v3 canonical pipeline: {V3_PATH}")
V3 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(V3)


SCHEMA = "ds02.stage2.f2-canonical-pipeline-contract.v4"
REQUEST_SCHEMA = "ds02.stage2.f2-canonical-pipeline-request.v4"
TARGET_BINDING_SCHEMA = "ds02.stage2.f2-canonical-pipeline-target-binding.v3"
VALIDATION_SCHEMA = "ds02.stage2.f2-canonical-pipeline-validation.v4"
CURRENT_SHA = V3.CURRENT_SHA
CANONICAL_ID = V3.CANONICAL_ID
HISTORICAL_ALIAS_ID = V3.HISTORICAL_ALIAS_ID
PENDING = V3.PENDING_RAW_SHA
PYTHON = V3.PYTHON
STAGE_SPECS: dict[str, dict[str, Any]] = copy.deepcopy(V3.STAGE_SPECS)
STAGE_SPECS["portable_scorer"]["argv_tail"] = [
    *STAGE_SPECS["portable_scorer"]["argv_tail"],
    "--output", "<portable-score-report>",
]
STAGE_ORDER = tuple(STAGE_SPECS)
MODULE_ORDER = tuple(V3.MODULE_SPECS)

_CLI_REQUIRED: dict[str, frozenset[str]] = {
    "canonical_adapter": frozenset({"--binding", "--output"}),
    "raw_converter": frozenset({"--data-root", "--generated-xml", "--output", "--report",
                                 "--decoder", "--solver-receipt", "--gencase-receipt",
                                 "--owner-metadata", "--skip-partvtk-validation"}),
    "restorer": frozenset({"prepare", "--bundle", "--path-map", "--output-dir",
                            "--io-slot-approved"}),
    "worker": frozenset({"run", "--request", "--output-dir", "--io-slot-approved", "--run-labels"}),
    "label_producer": frozenset({"run", "--request", "--output-dir", "--io-slot-approved"}),
    "portable_scorer": frozenset({"--profile", "--request", "--path-map", "--output",
                                   "--io-slot-approved"}),
}


class PipelineV4Error(ValueError):
    """The concrete v4 request cannot be made safe."""


def _fail(message: str) -> None:
    raise PipelineV4Error(message)


def _json(path: Path | str, role: str) -> dict[str, Any]:
    try:
        value = V3._json(Path(path), role)
    except Exception as error:
        if isinstance(error, PipelineV4Error):
            raise
        raise PipelineV4Error(str(error)) from error
    if not isinstance(value, dict):
        _fail(f"{role} must be an object")
    return value


def _sha(path: Path | str, role: str) -> str:
    return V3._sha(Path(path), role)


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return V3.canonical_sha(value)


@contextmanager
def _v3_abi() -> Iterator[None]:
    """Run immutable v3 helpers against this adapter's ABI constants."""
    names = ("SCHEMA", "REQUEST_SCHEMA", "TARGET_BINDING_SCHEMA", "STAGE_SPECS", "STAGE_ORDER")
    saved = {name: getattr(V3, name) for name in names}
    V3.SCHEMA = SCHEMA
    V3.REQUEST_SCHEMA = REQUEST_SCHEMA
    V3.TARGET_BINDING_SCHEMA = TARGET_BINDING_SCHEMA
    V3.STAGE_SPECS = STAGE_SPECS
    V3.STAGE_ORDER = STAGE_ORDER
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(V3, name, value)


def _commands() -> list[dict[str, Any]]:
    return [V3._command(role, spec) for role, spec in STAGE_SPECS.items()]


def _normalise_contract(value: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(value)
    value["schema"] = SCHEMA
    value["contract_id"] = "f2-s1-canonical-row65-pipeline-v4-parent-ready"
    value["stage_order"] = list(STAGE_ORDER)
    value["execution"]["commands"] = _commands()
    value["stage_abi"] = {
        role: {"filename": spec["filename"], "entrypoint": spec["entrypoint"],
               "invocation": spec["invocation"], "argv_tail": list(spec["argv_tail"])}
        for role, spec in STAGE_SPECS.items()
    }
    value.setdefault("source_closure", {})["builder_source"] = {
        "path": str(SCRIPT), "v3_dependency_path": str(V3_PATH),
        "v3_dependency_sha256": _sha(V3_PATH, "canonical pipeline v3 dependency"),
    }
    value["abi_contract"] = {
        "portable_scorer_output_required": True,
        "required_cli_flags": {role: sorted(flags) for role, flags in _CLI_REQUIRED.items()},
        "all_payload_stages": [role for role, spec in STAGE_SPECS.items() if spec["payload"]],
    }
    value["sha256"] = _canonical_sha(value)
    return value


def build_contract(*, plan_path: Path | str, repo_root: Path | str,
                   output_path: Path | str) -> dict[str, Any]:
    output = Path(output_path).expanduser().absolute()
    if output.exists() or output.is_symlink():
        _fail(f"refusing to overwrite immutable contract: {output}")
    with tempfile.TemporaryDirectory(prefix="f2-canonical-v4-contract-") as scratch:
        temporary = Path(scratch) / "v3-output.json"
        with _v3_abi():
            V3.build_contract(plan_path=plan_path, repo_root=repo_root, output_path=temporary)
        contract = _normalise_contract(_json(temporary, "v4 temporary contract"))
    file_sha = V3._write_new(output, contract)
    validate_contract(output)
    return {
        "schema": SCHEMA, "status": contract["status"],
        "contract": {"path": str(output), "file_sha256": file_sha,
                      "canonical_sha256": contract["sha256"]},
        "module_count": len(MODULE_ORDER), "stage_count": len(STAGE_ORDER),
        "raw_payload_read": False, "ledger_mutated": False,
        "qualification": dict(V3.UNKNOWN_QUALIFICATION),
    }


def _replace(value: Any, paths: Mapping[str, str]) -> Any:
    if isinstance(value, list):
        return [_replace(item, paths) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, paths) for key, item in value.items()}
    return paths.get(value, value) if isinstance(value, str) else value


def _attempt_paths(namespace: Path, fresh: Path, output: Path) -> dict[str, str]:
    metadata = namespace / "metadata"
    reports = namespace / "reports"
    inputs = namespace / "inputs"
    products = fresh / "products"
    return {
        "<canonical-binding>": str(metadata / "canonical-semantics-binding.json"),
        "<adapter-report>": str(reports / "canonical-semantics-report.json"),
        "<raw-data-root>": str(inputs / "raw"),
        "<generated-xml>": str(inputs / "generated.xml"),
        "<typed-h5>": str(products / "typed.h5"),
        "<converter-report>": str(reports / "converter-report.json"),
        "<decoder>": str(namespace / "runtime" / "tools" / "bi4-decoder"),
        "<solver-receipt>": str(inputs / "solver-receipt.json"),
        "<gencase-receipt>": str(inputs / "gencase-receipt.json"),
        "<owner-metadata>": str(inputs / "owner-metadata.json"),
        "<bound-request>": str(output),
        "<bundle>": str(namespace / "inputs" / "bundle"),
        "<path-map>": str(metadata / "path-map.json"),
        "<restore-plan>": str(fresh / "restore-plan"),
        "<fresh-output>": str(fresh),
        "<typed-label-request>": str(metadata / "typed-label-request.json"),
        "<labels-output>": str(products / "labels"),
        "<portable-profile>": str(metadata / "portable-profile.json"),
        "<v15-request>": str(metadata / "v15-request.json"),
        "<portable-score-report>": str(products / "portable-score.json"),
    }


def _deferred_inputs(paths: Mapping[str, str]) -> list[dict[str, Any]]:
    roles = {
        "raw_data_root": "<raw-data-root>", "generated_xml": "<generated-xml>",
        "typed_output": "<typed-h5>", "decoder": "<decoder>",
        "solver_receipt": "<solver-receipt>", "gencase_receipt": "<gencase-receipt>",
        "owner_metadata": "<owner-metadata>", "portable_profile": "<portable-profile>",
        "v15_request": "<v15-request>",
    }
    return [{"role": role, "path": paths[token],
             "expected_sha256": PENDING, "content_phase": "AFTER_PARENT_RESERVATION",
             "source_fallback": "REJECT"}
            for role, token in roles.items()]


def _normalise_request(value: dict[str, Any], *, contract_path: Path,
                       binding_path: Path, namespace: Path, fresh: Path,
                       output: Path, attempt_id: str) -> dict[str, Any]:
    value = copy.deepcopy(value)
    paths = _attempt_paths(namespace, fresh, output)
    value["schema"] = REQUEST_SCHEMA
    value["request_id"] = f"f2-s1-canonical-row65-pipeline-v4-{attempt_id}"
    value["attempt_id"] = attempt_id
    value["stage_order"] = list(STAGE_ORDER)
    value["execution"]["commands"] = _replace(value["execution"]["commands"], paths)
    # The reader is an import entrypoint rather than a CLI.  A bare ``-I
    # script.py`` invocation loses the copied v14 sibling that v15 imports.
    # Emit a concrete, isolated bootstrap so the parent can execute the
    # reader against the copied module/stage roots without worktree PYTHONPATH.
    commands = {item.get("stage"): item for item in value["execution"]["commands"]}
    reader = commands["reader"]
    reader_path = reader.get("target_path")
    if not isinstance(reader_path, str):
        _fail("reader target path is missing from bound v4 request")
    module_root = namespace / "runtime" / "modules"
    stage_root = namespace / "runtime" / "stages"
    reader["argv"] = [
        PYTHON, "-B", "-I", "-c",
        "import sys;sys.path[:0]=[" + repr(str(module_root)) + "," +
        repr(str(stage_root)) + "];import importlib.util as _u;" +
        "_s=_u.spec_from_file_location('row65_reader'," + repr(reader_path) + ");" +
        "_m=_u.module_from_spec(_s);_s.loader.exec_module(_m);" +
        "assert callable(_m.read_hdf5_window_v15)",
    ]
    reader["bootstrap"] = "COPIED_MODULE_AND_STAGE_ROOTS_ONLY"
    value["execution"].update({
        "case_id": CANONICAL_ID, "attempt_id": attempt_id,
        "attempt_root": str(namespace), "fresh_output_root": str(fresh),
        "product_roots": {
            "typed": str(fresh / "products" / "typed.h5"),
            "labels": str(fresh / "products" / "labels"),
            "portable_score": str(fresh / "products" / "portable-score.json"),
        },
        "commands_are_concrete": True,
    })
    value["source_binding"].update({
        "contract_path": str(contract_path),
        "contract_file_sha256": _sha(contract_path, "v4 contract"),
        "target_binding_path": str(binding_path),
        "target_binding_file_sha256": _sha(binding_path, "v4 target binding"),
        "namespace_root": str(namespace), "source_fallback": "REJECT",
        "current_sha256": CURRENT_SHA, "raw_tree_sha256": PENDING,
    })
    value["parent_request"] = {
        "schema": "ds02.stage2.f2-canonical-parent-request.v1",
        "case_id": CANONICAL_ID, "current_index": 65, "attempt_id": attempt_id,
        "reservation_required_before_payload": True,
        "payload_content_hash_phase": "AFTER_PARENT_RESERVATION",
        "home_receipt_path": str(namespace / "receipt" / "parent-receipt.json"),
        "external_output_root": str(fresh),
        "deferred_inputs": _deferred_inputs(paths),
        "source_fallback": "REJECT",
        "qualification": dict(V3.UNKNOWN_QUALIFICATION),
    }
    value["outputs"] = {
        "root": str(fresh), "must_be_new": True,
        "typed": {"path": str(fresh / "products" / "typed.h5"),
                  "sha256": PENDING, "content_phase": "AFTER_PARENT_RESERVATION"},
        "labels": {"path": str(fresh / "products" / "labels"),
                   "sha256": PENDING, "content_phase": "AFTER_PARENT_RESERVATION"},
        "portable_score": {"path": str(fresh / "products" / "portable-score.json"),
                            "sha256": PENDING, "content_phase": "AFTER_PARENT_RESERVATION"},
    }
    value["abi_contract"] = {
        "portable_scorer_output_required": True,
        "required_cli_flags": {role: sorted(flags) for role, flags in _CLI_REQUIRED.items()},
        "stage_count": len(STAGE_ORDER),
    }
    value["sha256"] = _canonical_sha(value)
    return value


def bind_request(*, contract_path: Path | str, binding_path: Path | str,
                 namespace_root: Path | str, fresh_output_root: Path | str,
                 output_path: Path | str, attempt_id: str) -> dict[str, Any]:
    output = Path(output_path).expanduser().absolute()
    namespace = Path(namespace_root).expanduser().absolute()
    fresh = Path(fresh_output_root).expanduser().absolute()
    if not V3._inside(output, namespace):
        _fail("v4 bound request must be written inside the copied namespace")
    if output.exists() or output.is_symlink():
        _fail(f"refusing to overwrite immutable request: {output}")
    if not attempt_id or "/" in attempt_id or ".." in attempt_id:
        _fail("attempt_id is unsafe")
    with tempfile.TemporaryDirectory(prefix="f2-canonical-v4-request-") as scratch:
        temp_contract = Path(scratch) / "contract.json"
        contract = _json(contract_path, "v4 contract")
        V3._write_new(temp_contract, contract)
        temp_request = Path(scratch) / "v3-request.json"
        with _v3_abi():
            V3.bind_contract(contract_path=temp_contract, binding_path=binding_path,
                             namespace_root=namespace, output_path=temp_request,
                             fresh_output_root=fresh, attempt_id=attempt_id)
        request = _normalise_request(_json(temp_request, "v4 temporary request"),
                                     contract_path=Path(contract_path).expanduser().absolute(),
                                     binding_path=Path(binding_path).expanduser().absolute(),
                                     namespace=namespace, fresh=fresh, output=output,
                                     attempt_id=attempt_id)
    file_sha = V3._write_new(output, request)
    validate_bound(output)
    return {
        "schema": REQUEST_SCHEMA, "status": request["status"],
        "request": {"path": str(output), "file_sha256": file_sha,
                     "canonical_sha256": request["sha256"]},
        "case_id": CANONICAL_ID, "current_index": 65, "attempt_id": attempt_id,
        "stage_count": len(STAGE_ORDER), "raw_payload_read": False,
        "ledger_mutated": False, "qualification": dict(V3.UNKNOWN_QUALIFICATION),
    }


def _absolute_values(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _absolute_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _absolute_values(child)
    elif isinstance(value, str) and value.startswith("/"):
        yield value


def validate_contract(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().absolute()
    contract = _json(target, "v4 contract")
    if contract.get("schema") != SCHEMA or contract.get("sha256") != _canonical_sha(contract):
        _fail("v4 contract schema/SHA differs")
    if contract.get("case_identity", {}).get("current_index") != 65 or \
            contract.get("case_identity", {}).get("physical_case_id") != CANONICAL_ID:
        _fail("v4 contract is not canonical CURRENT row 65")
    if contract.get("case_identity", {}).get("historical_alias_rejected") != HISTORICAL_ALIAS_ID:
        _fail("v4 contract does not preserve row-78 rejection")
    commands = {item.get("stage"): item for item in contract.get("execution", {}).get("commands", [])}
    if set(commands) != set(STAGE_ORDER):
        _fail("v4 contract seven-stage command closure is incomplete")
    scorer = commands["portable_scorer"]
    if "--output" not in scorer.get("argv_template", []):
        _fail("portable scorer output flag is missing")
    return {"schema": VALIDATION_SCHEMA, "status": "VALIDATED_V4_SOURCE_BOUND_PARENT_REQUIRED",
            "contract_path": str(target), "contract_sha256": contract["sha256"],
            "canonical_row": 65, "stage_count": len(STAGE_ORDER),
            "raw_payload_read": False, "qualification": dict(V3.UNKNOWN_QUALIFICATION)}


def validate_bound(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().absolute()
    request = _json(target, "v4 bound request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != _canonical_sha(request):
        _fail("v4 request schema/SHA differs")
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or identity.get("current_index") != 65 or \
            identity.get("physical_case_id") != CANONICAL_ID or \
            identity.get("physical_case_id") == HISTORICAL_ALIAS_ID:
        _fail("v4 bound request is not canonical CURRENT row 65")
    namespace = Path(str(request.get("source_binding", {}).get("namespace_root", ""))).expanduser()
    if not namespace.is_dir():
        _fail("v4 copied namespace is missing")
    for section, roles in (("modules", MODULE_ORDER), ("stages", STAGE_ORDER)):
        records = {item.get("role"): item for item in request.get(section, [])
                   if isinstance(item, Mapping)}
        if set(records) != set(roles):
            _fail(f"v4 {section} closure is incomplete")
        for role in roles:
            item = records[role]
            path_value = Path(str(item.get("target_path", ""))).expanduser()
            if not V3._inside(path_value, namespace) or path_value.is_symlink() or not path_value.is_file():
                _fail(f"v4 {section}.{role} target is not closed")
            if _sha(path_value, f"v4 {section}.{role}") != item.get("target_sha256"):
                _fail(f"v4 {section}.{role} target SHA changed")
    commands = {item.get("stage"): item for item in request.get("execution", {}).get("commands", [])}
    if set(commands) != set(STAGE_ORDER):
        _fail("v4 bound seven-stage command closure is incomplete")
    for role, required in _CLI_REQUIRED.items():
        argv = commands[role].get("argv")
        if not isinstance(argv, list) or not required.issubset({str(item) for item in argv}):
            _fail(f"v4 {role} command is missing required CLI arguments")
    reader_argv = commands["reader"].get("argv")
    if not isinstance(reader_argv, list) or reader_argv[:4] != [PYTHON, "-B", "-I", "-c"]:
        _fail("v4 reader lacks an isolated copied-root bootstrap")
    bootstrap = reader_argv[4]
    if not isinstance(bootstrap, str) or str(namespace / "runtime" / "modules") not in bootstrap or \
            str(namespace / "runtime" / "stages") not in bootstrap:
        _fail("v4 reader bootstrap does not bind copied module/stage roots")
    for command in commands.values():
        for value in _absolute_values(command.get("argv", [])):
            if value == PYTHON:
                continue
            if not V3._inside(Path(value), namespace):
                _fail(f"v4 command retains an original absolute path: {value}")
        if any(isinstance(item, str) and item.startswith("<") for item in command.get("argv", [])):
            _fail("v4 command contains an unresolved placeholder")
    parent = request.get("parent_request")
    if not isinstance(parent, Mapping) or parent.get("reservation_required_before_payload") is not True:
        _fail("v4 parent reservation gate is missing")
    for item in parent.get("deferred_inputs", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            _fail("v4 deferred input is malformed")
        if not V3._inside(Path(str(item["path"])), namespace):
            _fail("v4 deferred input escapes copied namespace")
    outputs = request.get("outputs", {})
    if not isinstance(outputs, Mapping) or not V3._inside(Path(str(outputs.get("root", ""))), namespace):
        _fail("v4 output root is not attempt-owned")
    return {"schema": VALIDATION_SCHEMA, "status": "VALIDATED_V4_CONCRETE_PARENT_REQUEST",
            "request_path": str(target), "request_sha256": request["sha256"],
            "canonical_row": 65, "attempt_id": request.get("attempt_id"),
            "stage_count": len(STAGE_ORDER), "raw_payload_read": False,
            "qualification": dict(V3.UNKNOWN_QUALIFICATION)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-contract")
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    bind = sub.add_parser("bind")
    bind.add_argument("--contract", type=Path, required=True)
    bind.add_argument("--binding", type=Path, required=True)
    bind.add_argument("--namespace-root", type=Path, required=True)
    bind.add_argument("--fresh-output-root", type=Path, required=True)
    bind.add_argument("--output", type=Path, required=True)
    bind.add_argument("--attempt-id", required=True)
    validate = sub.add_parser("validate-contract")
    validate.add_argument("--contract", type=Path, required=True)
    bound = sub.add_parser("validate-bound")
    bound.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-contract":
            result = build_contract(plan_path=args.plan, repo_root=args.repo_root,
                                    output_path=args.output)
        elif args.command == "bind":
            result = bind_request(contract_path=args.contract, binding_path=args.binding,
                                  namespace_root=args.namespace_root,
                                  fresh_output_root=args.fresh_output_root,
                                  output_path=args.output, attempt_id=args.attempt_id)
        elif args.command == "validate-contract":
            result = validate_contract(args.contract)
        else:
            result = validate_bound(args.request)
    except (OSError, PipelineV4Error, ValueError, json.JSONDecodeError) as error:
        print(f"canonical pipeline v4: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
