#!/usr/bin/env python3
"""ROOT228 forward executor with a closed V12 proof-output directory alias.

ROOT213 executor V2 copies unknown nested provenance files, but ROOT222
exposed a different category of unbound value: the V12 ``output_root_rebind``
object contains a directory anchor rather than a file role.  This adapter
preserves the consumed V2 implementation and adds one schema-bound alias:
the current V14 proof-output namespace is rebound to the fresh private
``reports`` directory.  Historical ``old_*_output_root`` values remain
explicit, non-actionable provenance; every other absolute value still fails
closed.

The alias is admitted only when the exact V14 schema, ``proof_output_only``
predicate, and equal current ``path``/``new_output_root`` values are present.
The host-side overlay build is patched for that one operation.  The copied V2
child remains byte-bound to the consumed V2 source and sees only the generated
target-relative request.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V2_EXECUTOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root213_portable_typed_executor_v2.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V2_EXECUTOR = _load(V2_EXECUTOR_SCRIPT, "ds02_root213_portable_typed_executor_v2_for_v3")
V3_REPORT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-executor-report.v3"
V14_OUTPUT_SCHEMA = "ds02.stage2.f2-fresh-v16-profile-output-root-builder-v14.v1"
REPORTS_ALIAS = "reports"


class Root213ExecutorV3Error(RuntimeError):
    """A schema, directory-alias, or strict relocated-overlay failure."""


_ORIGINAL_REWRITE = None
_ORIGINAL_DIRECTORY_REBIND = None
_ORIGINAL_MAKE_MANIFEST = None
_ACTIVE_ALIAS_INFO: dict[str, Any] | None = None


def _pointer(parts: Sequence[str]) -> str:
    return "" if not parts else "".join(
        "/" + str(item).replace("~", "~0").replace("/", "~1") for item in parts
    )


def _absolute(value: Any, pointer: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root213ExecutorV3Error(f"{pointer} must be an absolute path")
    return value


def _mapping_at(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None


def _prepare_alias_info(value: Any) -> dict[str, Any]:
    """Validate the exact V14 directory contract before rewriting anything."""
    if not isinstance(value, Mapping):
        raise Root213ExecutorV3Error("ROOT200 inner request must be an object")
    node = _mapping_at(value, "v12_forward", "output_root_rebind_v14")
    aliases: dict[tuple[str, ...], dict[str, Any]] = {}
    manual: dict[tuple[str, ...], dict[str, Any]] = {}
    historical: dict[tuple[str, ...], dict[str, Any]] = {}

    if node is not None:
        pointer = "/v12_forward/output_root_rebind_v14"
        if node.get("schema") != V14_OUTPUT_SCHEMA:
            raise Root213ExecutorV3Error(f"{pointer}/schema is not the V14 output-root schema")
        if node.get("proof_output_only") is not True:
            raise Root213ExecutorV3Error(f"{pointer}/proof_output_only is not true")
        current = _absolute(node.get("path"), pointer + "/path")
        new_root = _absolute(node.get("new_output_root", current), pointer + "/new_output_root")
        if current != new_root:
            raise Root213ExecutorV3Error(f"{pointer} current and new output roots differ")
        aliases[("v12_forward", "output_root_rebind_v14")] = {
            "source": current, "schema": V14_OUTPUT_SCHEMA,
            "reason": "V14 proof-output directory alias",
        }
        old = node.get("old_v13_output_root")
        if old is not None:
            historical[("v12_forward", "output_root_rebind_v14", "old_v13_output_root")] = {
                "path": _absolute(old, pointer + "/old_v13_output_root"),
                "reason": "historical V13 output namespace; never read by V8/V12/scorer",
            }

    provenance = value.get("output_root_rebind_provenance")
    if provenance is not None:
        if not isinstance(provenance, Mapping):
            raise Root213ExecutorV3Error("/output_root_rebind_provenance must be an object")
        new_root = provenance.get("new_output_root")
        if new_root is not None:
            new_root = _absolute(new_root, "/output_root_rebind_provenance/new_output_root")
            if node is not None and new_root != aliases[("v12_forward", "output_root_rebind_v14")]["source"]:
                raise Root213ExecutorV3Error("output-root provenance disagrees with V14 alias")
            manual[("output_root_rebind_provenance", "new_output_root")] = {
                "source": new_root, "schema": V14_OUTPUT_SCHEMA,
                "reason": "current V14 proof-output directory metadata alias",
                "target_relative": REPORTS_ALIAS,
            }
        old_root = provenance.get("old_output_root")
        if old_root is not None:
            historical[("output_root_rebind_provenance", "old_output_root")] = {
                "path": _absolute(old_root, "/output_root_rebind_provenance/old_output_root"),
                "reason": "historical V13 output namespace; never read by V8/V12/scorer",
            }

    profile = value.get("profile_rebind_provenance")
    if profile is not None:
        if not isinstance(profile, Mapping):
            raise Root213ExecutorV3Error("/profile_rebind_provenance must be an object")
        proof_root = profile.get("proof_output_root")
        if proof_root is not None:
            proof_root = _absolute(proof_root, "/profile_rebind_provenance/proof_output_root")
            if node is not None and proof_root != aliases[("v12_forward", "output_root_rebind_v14")]["source"]:
                raise Root213ExecutorV3Error("profile proof output root disagrees with V14 alias")
            manual[("profile_rebind_provenance", "proof_output_root")] = {
                "source": proof_root, "schema": V14_OUTPUT_SCHEMA,
                "reason": "current V14 proof-output directory metadata alias",
                "target_relative": REPORTS_ALIAS,
            }

    # If a V14 object is present, all three current aliases must be present in
    # the actual ROOT200 request.  This catches partial handcrafted contracts.
    if node is not None:
        for pointer in (
            ("output_root_rebind_provenance", "new_output_root"),
            ("profile_rebind_provenance", "proof_output_root"),
        ):
            if pointer not in manual:
                raise Root213ExecutorV3Error(f"missing required current directory alias at {_pointer(pointer)}")

    # These fields are metadata carried by the producer contract.  The
    # relocated V8/V12/scorer code does not read them (the source-only audit
    # is part of this forward version), so they are rebound as explicit
    # non-actionable aliases rather than left as original absolute paths.
    producer_result = _mapping_at(value, "fresh_proof_namespace")
    if producer_result is not None and producer_result.get("producer_result_path") is not None:
        result = _mapping_at(value, "result")
        result_path = result.get("path") if result is not None else None
        producer_path = _absolute(
            producer_result.get("producer_result_path"),
            "/fresh_proof_namespace/producer_result_path")
        if isinstance(result_path, str) and producer_path != result_path:
            raise Root213ExecutorV3Error("producer result path disagrees with result binding")
        manual[("fresh_proof_namespace", "producer_result_path")] = {
            "source": producer_path, "schema": "deferred-result-alias.v1",
            "reason": "V8/V12/scorer do not consume producer namespace metadata",
            "target_relative": "products/v16-result.json",
        }

    execution = value.get("execution")
    if isinstance(execution, Mapping):
        python_binding = execution.get("python_binding")
        if isinstance(python_binding, Mapping):
            for key in ("literal_invocation_path",):
                if python_binding.get(key) is not None:
                    manual[("execution", "python_binding", key)] = {
                        "source": _absolute(python_binding[key], f"/execution/python_binding/{key}"),
                        "schema": "pinned-interpreter-environment-exception.v1",
                        "reason": "outer guard owns literal venv invocation; inner metadata is not executed",
                        "target_relative": "environment/python",
                    }
            resolved = python_binding.get("resolved_provenance_path")
            if resolved is not None:
                historical[("execution", "python_binding", "resolved_provenance_path")] = {
                    "path": _absolute(resolved, "/execution/python_binding/resolved_provenance_path"),
                    "reason": "resolved interpreter provenance; outer literal venv remains executable",
                }
        executable = execution.get("python_executable")
        if executable is not None:
            manual[("execution", "python_executable")] = {
                "source": _absolute(executable, "/execution/python_executable"),
                "schema": "pinned-interpreter-environment-exception.v1",
                "reason": "outer guard owns literal venv invocation; inner metadata is not executed",
                "target_relative": "environment/python",
            }

    relocation = value.get("relocation")
    if isinstance(relocation, Mapping):
        proof_binding = relocation.get("proof_output_root_binding")
        if isinstance(proof_binding, Mapping) and proof_binding.get("replaced_v13_output_root") is not None:
            historical[("relocation", "proof_output_root_binding", "replaced_v13_output_root")] = {
                "path": _absolute(
                    proof_binding["replaced_v13_output_root"],
                    "/relocation/proof_output_root_binding/replaced_v13_output_root"),
                "reason": "historical V13 output namespace; never read by V8/V12/scorer",
            }

    return {"aliases": aliases, "manual": manual, "historical": historical}


def _prepare_value(value: Any, info: Mapping[str, Any], root: Path,
                   parts: tuple[str, ...] = ()) -> Any:
    manual = info.get("manual", {})
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, child in value.items():
            pointer = parts + (str(key),)
            if pointer in manual:
                output[key] = str(root / REPORTS_ALIAS)
                target_relative = str(manual[pointer].get("target_relative", REPORTS_ALIAS))
                output[key] = str(root / target_relative)
            else:
                output[key] = _prepare_value(child, info, root, pointer)
        return output
    if isinstance(value, list):
        return [_prepare_value(child, info, root, parts + (str(index),))
                for index, child in enumerate(value)]
    return value


def _directory_rebind_v3(parts: tuple[str, ...], root: Path) -> Path | None:
    info = _ACTIVE_ALIAS_INFO
    if info is not None and tuple(str(part).lower() for part in parts) in info.get("aliases", {}):
        return root / REPORTS_ALIAS
    return _ORIGINAL_DIRECTORY_REBIND(parts, root)


def _make_manifest_v3(request: Mapping[str, Any], root: Path,
                      reservation_started: float):
    """Normalize the two historical scorer aliases before V2 builds roles.

    The consumed V1 builder emitted ``typed_scorer_v2/v3`` for two runtime
    files, while the consumed V2 runtime contract requires the explicit
    ``typed_only_evaluator_v2/v3`` names.  The target paths and source SHA are
    unchanged; only the logical role names are normalized in this fresh
    forward contract.  Existing V1/V2 contracts are never edited.
    """
    manifest_path, contract_path, built = _ORIGINAL_MAKE_MANIFEST(
        request, root, reservation_started)
    table = built["table"]
    aliases = {
        "typed_scorer_v2": "typed_only_evaluator_v2",
        "typed_scorer_v3": "typed_only_evaluator_v3",
    }
    changed = False
    for item in table.items:
        replacement = aliases.get(str(item.get("logical_role")))
        if replacement is not None:
            item["logical_role"] = replacement
            changed = True
    if not changed:
        return manifest_path, contract_path, built

    manifest_path = Path(manifest_path)
    # V1's return value does not expose manifest_path, but its fixed path is
    # deterministic.  Re-canonicalize the same manifest and regenerate the
    # contract so its role list and manifest SHA agree.
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest["artifacts"] = table.items
    manifest["sha256"] = V2_EXECUTOR.V1._canonical(manifest)
    Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # V1 already wrote its immutable v1 contract.  Keep that file untouched
    # and emit the normalized forward contract under a new filename.
    contract_path = Path(contract_path).with_name("root213-copy-contract-v3.json")
    contract = V2_EXECUTOR.V1.V1.build_contract(
        manifest_path=manifest_path, relocated_root=root, output=contract_path,
        contract_id=request["attempt_id"])
    built["manifest"] = manifest
    built["contract"] = contract
    return manifest_path, contract_path, built


def _annotate_directory_bindings(bindings: list[dict[str, Any]], info: Mapping[str, Any]) -> None:
    aliases = info.get("aliases", {})
    for pointer_parts, value in aliases.items():
        pointer = _pointer(pointer_parts + ("path",))
        for binding in bindings:
            if binding.get("pointer") == pointer:
                binding.update({
                    "directory_alias_schema": value["schema"],
                    "directory_alias_reason": value["reason"],
                    "source_directory_provenance": value["source"],
                    "target_directory_relative_path": REPORTS_ALIAS,
                })
                break

    for pointer_parts, value in info.get("manual", {}).items():
        bindings.append({
            "pointer": _pointer(pointer_parts),
            "actionable": False,
            "provenance_path": value["source"],
            "provenance_reason": value["reason"],
            "directory_alias_schema": value["schema"],
            "directory_alias_reason": value["reason"],
            "source_directory_provenance": value["source"],
            "target_alias_relative_path": value.get("target_relative", REPORTS_ALIAS),
        })
    for pointer_parts, value in info.get("historical", {}).items():
        bindings.append({
            "pointer": _pointer(pointer_parts),
            "actionable": False,
            "provenance_path": value["path"],
            "provenance_reason": value["reason"],
        })


def _assert_absolute_values_closed(value: Any, root: Path,
                                   info: Mapping[str, Any],
                                   parts: tuple[str, ...] = ()) -> None:
    allowed = set(info.get("historical", {}))
    if isinstance(value, Mapping):
        for key, child in value.items():
            pointer = parts + (str(key),)
            if isinstance(child, str) and child.startswith("/"):
                try:
                    Path(child).resolve(strict=False).relative_to(root.resolve(strict=False))
                    inside = True
                except ValueError:
                    inside = False
                if not inside and pointer not in allowed and not (
                    len(pointer) >= 2 and pointer[-2] == "original_roots"
                ):
                    raise Root213ExecutorV3Error(
                        f"unbound absolute value remains at {_pointer(pointer)}: {child}"
                    )
            _assert_absolute_values_closed(child, root, info, pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_absolute_values_closed(child, root, info, parts + (str(index),))


def _rewrite_request_v3(value: Any, *, root: Path, source_map: Mapping[str, tuple[Mapping[str, Any], Path]],
                        role_by_target: Mapping[str, Mapping[str, Any]], bindings: list[dict[str, Any]],
                        parts: tuple[str, ...] = ()) -> Any:
    # The consumed V2 function recursively resolves itself through its module
    # global.  Prepare only the top-level request, then delegate all normal
    # file/provenance handling to the byte-frozen implementation.
    global _ACTIVE_ALIAS_INFO
    if parts:
        return _ORIGINAL_REWRITE(value, root=root, source_map=source_map,
                                  role_by_target=role_by_target, bindings=bindings,
                                  parts=parts)
    info = _prepare_alias_info(value)
    _ACTIVE_ALIAS_INFO = info
    try:
        prepared = _prepare_value(value, info, root)
        result = _ORIGINAL_REWRITE(prepared, root=root, source_map=source_map,
                                   role_by_target=role_by_target, bindings=bindings,
                                   parts=parts)
        _annotate_directory_bindings(bindings, info)
        _assert_absolute_values_closed(result, root, info)
        return result
    finally:
        _ACTIVE_ALIAS_INFO = None


def _install_hooks() -> None:
    global _ORIGINAL_REWRITE, _ORIGINAL_DIRECTORY_REBIND, _ORIGINAL_MAKE_MANIFEST
    V2_EXECUTOR.REPORT_SCHEMA = V3_REPORT_SCHEMA
    V2_EXECUTOR._install_forward_hooks()
    v2 = V2_EXECUTOR.V1.V2
    if _ORIGINAL_REWRITE is None:
        _ORIGINAL_REWRITE = v2._rewrite_request
        _ORIGINAL_DIRECTORY_REBIND = v2._directory_rebind
        _ORIGINAL_MAKE_MANIFEST = V2_EXECUTOR.V1._make_manifest
    v2._rewrite_request = _rewrite_request_v3
    v2._directory_rebind = _directory_rebind_v3
    V2_EXECUTOR.V1._make_manifest = _make_manifest_v3


def _restore_hooks() -> None:
    if _ORIGINAL_REWRITE is None:
        return
    v2 = V2_EXECUTOR.V1.V2
    v2._rewrite_request = _ORIGINAL_REWRITE
    v2._directory_rebind = _ORIGINAL_DIRECTORY_REBIND
    V2_EXECUTOR.V1._make_manifest = _ORIGINAL_MAKE_MANIFEST


def run(*, request_path: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    _install_hooks()
    try:
        return V2_EXECUTOR.run(request_path=request_path, output_root=output_root,
                               parent_pid=parent_pid, max_wall_seconds=max_wall_seconds)
    finally:
        _restore_hooks()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-root", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    run_parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _install_hooks()
    try:
        args = _parser().parse_args(argv)
        try:
            if args.command == "validate":
                value = V2_EXECUTOR.V1.ROOT213.validate_request(args.request)
            else:
                value = V2_EXECUTOR.V1.run(
                    request_path=args.request, output_root=args.output_root,
                    parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
            print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
            return 0
        except (V2_EXECUTOR.V1.Root213ExecutorError,
                V2_EXECUTOR.V1.ROOT213.Root213Error,
                V2_EXECUTOR.V1.V1.PortableRebindError,
                V2_EXECUTOR.V1.V2.PortableRebindV2Error,
                Root213ExecutorV3Error, OSError, ValueError, KeyError) as error:
            print(f"ROOT213 portable typed executor V3: {error}", file=sys.stderr)
            return 2
    finally:
        _restore_hooks()


if __name__ == "__main__":
    raise SystemExit(main())
