#!/usr/bin/env python3
"""Strict F6 v3 forward contract with complete ROOT276 manifest closure.

V2 binds the parent ``manifest`` and ``manifest_contract`` fields, but an
old parent request could omit the same manifest from its input hash/record
tables.  This additive version requires all three independently declared
bindings before delegating the v2 lifecycle/producer join.  It does not
modify or replace v1/v2 artifacts.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_V2 = _load("f6_producer_role_contract_v2_for_v3", SCRIPT_DIR / "ds_data02_stage2_f6_producer_role_contract_v2.py")

SCHEMA = "ds02.stage2.f6.producer-role-contract.v3"


class F6ProducerRoleContractV3Error(ValueError):
    """The parent manifest closure is incomplete or inconsistent."""


def _fail(message: str) -> None:
    raise F6ProducerRoleContractV3Error(message)


def _same_path(left: Any, right: Any) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _read(path: Path | str, role: str) -> tuple[dict[str, Any], str, dict[str, int]]:
    try:
        return _V2._read_json(Path(path).expanduser(), role)
    except Exception as error:
        _fail(str(error))


def _require_ref(value: Any, path: Path, sha: str, role: str) -> None:
    if not isinstance(value, Mapping) or not _same_path(value.get("path"), str(path)):
        _fail(f"{role} path is absent or differs")
    declared = value.get("sha256", value.get("file_sha256"))
    if declared != sha:
        _fail(f"{role} SHA differs")


def _validate_full_parent_manifest(parent: Mapping[str, Any], manifest_path: Path, manifest_sha: str) -> dict[str, Any]:
    if parent.get("schema") != "ds02.request.v1":
        _fail("ROOT276 parent request is not ds02.request.v1")
    _require_ref(parent.get("manifest"), manifest_path, manifest_sha, "parent manifest")
    _require_ref(parent.get("manifest_contract"), manifest_path, manifest_sha, "parent manifest contract")
    expected_key = str(manifest_path)
    input_sha = parent.get("input_sha256")
    if not isinstance(input_sha, Mapping) or expected_key not in input_sha:
        _fail("ROOT276 parent input_sha256 lacks the v8 manifest")
    if input_sha[expected_key] != manifest_sha:
        _fail("ROOT276 parent input_sha256 manifest differs")
    input_records = parent.get("input_records")
    if not isinstance(input_records, Mapping) or expected_key not in input_records:
        _fail("ROOT276 parent input_records lacks the v8 manifest")
    _require_ref(input_records[expected_key], manifest_path, manifest_sha, "parent input record manifest")
    root_binding = parent.get("root_canonical_binding")
    if not isinstance(root_binding, Mapping):
        _fail("ROOT276 root canonical binding is missing")
    if not _same_path(root_binding.get("immutable_manifest_direct_path"), str(manifest_path)):
        _fail("ROOT276 root canonical manifest path differs")
    return {"path": str(manifest_path.resolve()), "sha256": manifest_sha,
            "input_sha256_bound": True, "input_record_bound": True,
            "root_canonical_bound": True}


def build_contract_v3(
    manifest_path: Path | str,
    parent_request_path: Path | str,
    *, current_plan_path: Path | str,
    registry_path: Path | str,
    output_path: Path | str | None = None,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser()
    parent_request_path = Path(parent_request_path).expanduser()
    manifest, manifest_sha, _ = _read(manifest_path, "F6 v8 support manifest")
    if manifest.get("schema") != "ds02.stage2.f6-initial-native-support-manifest.v8":
        _fail("unsupported F6 v8 manifest schema")
    parent, _, _ = _read(parent_request_path, "ROOT276 parent request")
    parent_manifest = _validate_full_parent_manifest(parent, manifest_path, manifest_sha)
    result = _V2.build_contract_v2(
        manifest_path, parent_request_path,
        current_plan_path=current_plan_path, registry_path=registry_path,
        output_path=None, case_ids=case_ids,
    )
    result = copy.deepcopy(result)
    result["schema"] = SCHEMA
    result["parent_task"]["manifest_binding"] = parent_manifest
    result["parent_task"]["input_manifest_closure"] = "manifest + manifest_contract + input_sha256 + input_records + root_canonical_binding"
    result["claim_boundary"]["contract_version"] = "v3"
    if output_path is not None:
        target = Path(output_path).expanduser()
        if target.exists() or target.is_symlink():
            _fail(f"refusing to overwrite: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_contract(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return build_contract_v3(*args, **kwargs)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--parent-request", required=True, type=Path)
    parser.add_argument("--current-plan", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args(argv)
    try:
        result = build_contract_v3(
            args.manifest, args.parent_request, current_plan_path=args.current_plan,
            registry_path=args.registry, output_path=args.output,
            case_ids=set(args.cases) if args.cases else None,
        )
    except (OSError, F6ProducerRoleContractV3Error, _V2.F6ProducerRoleContractV2Error, _V2._V1.F6ProducerRoleContractError) as error:
        print(f"F6_PRODUCER_ROLE_CONTRACT_V3_ERROR: {error}")
        return 2
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "output": str(args.output), "cases": len(result["cases"]),
                      "production_eligible": result["production_eligible"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
