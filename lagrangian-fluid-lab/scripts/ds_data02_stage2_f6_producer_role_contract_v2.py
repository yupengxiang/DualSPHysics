#!/usr/bin/env python3
"""Strict F6 source-current contract for the real lifecycle v4 products.

The consumed v1 contract only recognized generic completion strings and
checked the parent request schema.  This forward adapter binds the actual
v4 plan, v4 evidence registry, CURRENT336 catalog, and ROOT276 manifest
metadata.  It remains a source/initial-support contract: ROOT276 is still
wait-only, event roles and Q fields remain UNKNOWN, and no native payload is
opened by this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_V1 = _load(
    "f6_producer_role_contract_v1_for_contract_v2",
    SCRIPT_DIR / "ds_data02_stage2_f6_producer_role_contract_v1.py",
)

SCHEMA = "ds02.stage2.f6.producer-role-contract.v2"
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
REGISTRY_SCHEMA = "ds02.stage2.typed-lifecycle-evidence-registry.v4"
CURRENT_STATUS = "ACTUAL_SAVED_MASK_COMPLETED"
SOURCE_JOIN = "EXACT_CURRENT_AUDIT_METADATA_JOIN"
SOURCE_CLOSURE = "COMPLETED_H5_PREPOST_SHA_AND_STAT_EQUAL"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v8"
PARENT_SCHEMA = "ds02.request.v1"


class F6ProducerRoleContractV2Error(ValueError):
    """The real lifecycle or parent binding is not admissible."""


def _fail(message: str) -> None:
    raise F6ProducerRoleContractV2Error(message)


def _read_json(path: Path | str, role: str) -> tuple[dict[str, Any], str, dict[str, int]]:
    try:
        return _V1._read_json(Path(path).expanduser(), role)
    except Exception as error:
        _fail(str(error))


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        _fail(f"{role} must be a SHA-256 string")
    try:
        int(value, 16)
    except ValueError:
        _fail(f"{role} is not hexadecimal")
    return value


def _same_path(left: Any, right: Any) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _ref_equal(left: Any, right: Any, role: str) -> None:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        _fail(f"{role} reference is missing")
    if not _same_path(left.get("path"), right.get("path")):
        _fail(f"{role} path differs")
    lsha = left.get("sha256", left.get("file_sha256"))
    rsha = right.get("sha256", right.get("file_sha256"))
    if not isinstance(lsha, str) or not isinstance(rsha, str) or lsha != rsha:
        _fail(f"{role} SHA differs")


def _verify_metadata_ref(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{role} reference is malformed")
    path = value.get("path")
    declared = value.get("sha256", value.get("known_sha256"))
    if not isinstance(path, str):
        _fail(f"{role} path is missing")
    # These are request/proof/manifest/receipt JSON documents.  BI4/H5 and
    # trajectory paths remain deferred by the inherited v1 case contract.
    if Path(path).suffix.lower() in {".bi4", ".ibi4", ".obi4", ".h5", ".hdf5", ".vtk", ".vtu"}:
        _fail(f"{role} is a deferred payload, not a bounded metadata reference")
    declared = _sha(declared, f"{role}.sha256")
    _, observed, stat_record = _read_json(Path(path), role)
    if observed != declared:
        _fail(f"{role} SHA differs from the producer record")
    return {"path": str(Path(path).expanduser().resolve()), "sha256": observed, "stat": stat_record}


def _validate_current_plan_and_registry(
    plan_path: Path, registry_path: Path, case_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    plan, plan_sha, plan_stat = _read_json(plan_path, "CURRENT v4 lifecycle plan")
    registry, registry_sha, registry_stat = _read_json(registry_path, "v4 lifecycle evidence registry")
    if plan.get("schema") != PLAN_SCHEMA:
        _fail(f"CURRENT plan schema must be {PLAN_SCHEMA}")
    if registry.get("schema") != REGISTRY_SCHEMA:
        _fail(f"evidence registry schema must be {REGISTRY_SCHEMA}")
    plan_catalog = plan.get("current_catalog")
    registry_catalog = registry.get("current")
    _ref_equal(plan_catalog, registry_catalog, "CURRENT catalog")
    _verify_metadata_ref(plan_catalog, "CURRENT336 catalog")
    plan_registry = plan.get("evidence_registry")
    _ref_equal(plan_registry, {"path": str(registry_path), "sha256": registry_sha}, "plan evidence registry")
    rows = plan.get("case_records")
    if not isinstance(rows, list):
        _fail("CURRENT v4 plan lacks case_records")
    selected: dict[str, dict[str, Any]] = {}
    producers = registry.get("producers")
    if not isinstance(producers, list):
        _fail("v4 evidence registry lacks producers")
    for case_id in sorted(case_ids):
        found = [row for row in rows if isinstance(row, Mapping) and row.get("physical_case_id") == case_id]
        if len(found) != 1:
            _fail(f"CURRENT v4 plan has {len(found)} rows for {case_id}")
        row = found[0]
        predicates = {
            "historical_alias": row.get("historical_alias") == "NONE",
            "actual_saved_mask_coverage": row.get("actual_saved_mask_coverage") is True,
            "source_join_status": row.get("source_join_status") == SOURCE_JOIN,
            "status": row.get("status") == CURRENT_STATUS,
        }
        bad = [key for key, ok in predicates.items() if not ok]
        if bad:
            _fail(f"CURRENT v4 plan case {case_id} failed: {','.join(bad)}")
        evidence = row.get("producer_evidence")
        if not isinstance(evidence, Mapping):
            _fail(f"CURRENT v4 plan case {case_id} lacks producer_evidence")
        if evidence.get("status") != CURRENT_STATUS:
            _fail(f"CURRENT v4 producer evidence {case_id} status differs")
        if evidence.get("reported_status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            _fail(f"CURRENT v4 producer evidence {case_id} is not diagnostic-only")
        if evidence.get("source_closure") != SOURCE_CLOSURE:
            _fail(f"CURRENT v4 producer evidence {case_id} source closure differs")
        attempt_id = evidence.get("attempt_id")
        lineage = row.get("attempt_lineage")
        if not isinstance(attempt_id, str) or not isinstance(lineage, list) or len(lineage) != 1:
            _fail(f"CURRENT v4 plan case {case_id} has ambiguous attempt")
        line = lineage[0]
        if not isinstance(line, Mapping) or line.get("attempt_id") != attempt_id or line.get("status") != CURRENT_STATUS:
            _fail(f"CURRENT v4 plan case {case_id} attempt lineage differs")
        matching = [producer for producer in producers if isinstance(producer, Mapping) and case_id in producer.get("case_ids", [])]
        if len(matching) != 1:
            _fail(f"v4 registry has {len(matching)} producer rows for {case_id}")
        producer = matching[0]
        if producer.get("status") != "COMPLETED":
            _fail(f"v4 registry producer for {case_id} is not COMPLETED")
        if producer.get("producer_id") != line.get("producer_id"):
            _fail(f"v4 registry producer id for {case_id} differs from plan lineage")
        refs = {
            key: _verify_metadata_ref(producer.get(key), f"{case_id} registry {key}")
            for key in ("request", "proof", "manifest")
        }
        for key in ("case_manifest", "case_receipt", "summary"):
            if key in evidence:
                _verify_metadata_ref(evidence[key], f"{case_id} producer evidence {key}")
        selected[case_id] = {
            "case_id": case_id,
            "status": CURRENT_STATUS,
            "historical_alias": "NONE",
            "source_join_status": SOURCE_JOIN,
            "source_closure": SOURCE_CLOSURE,
            "attempt_id": attempt_id,
            "producer_id": producer.get("producer_id"),
            "registry_status": producer.get("status"),
            "registry_metadata_refs": refs,
            "scientific_credit": "NONE_PHYSICAL_SAVED_MASK_ONLY",
        }
    plan_ref = {"path": str(plan_path.resolve()), "sha256": plan_sha, "stat": plan_stat}
    registry_ref = {"path": str(registry_path.resolve()), "sha256": registry_sha, "stat": registry_stat}
    current_ref = {
        "path": str(Path(plan_catalog["path"]).expanduser().resolve()),
        "sha256": plan_catalog["sha256"],
    }
    return plan, registry, plan_ref, registry_ref, {"current": current_ref, **selected}


def _validate_parent_manifest(parent: Mapping[str, Any], manifest_path: Path, manifest_sha: str) -> dict[str, Any]:
    if parent.get("schema") != _V1.__dict__.get("PARENT_SCHEMA", "ds02.request.v1") and parent.get("schema") != "ds02.request.v1":
        _fail("ROOT276 parent request is not ds02.request.v1")
    expected = {"path": str(manifest_path.resolve()), "sha256": manifest_sha}
    _ref_equal(parent.get("manifest"), expected, "ROOT276 parent manifest")
    _ref_equal(parent.get("manifest_contract"), expected, "ROOT276 parent manifest contract")
    input_sha = parent.get("input_sha256")
    if isinstance(input_sha, Mapping) and str(manifest_path) in input_sha and input_sha[str(manifest_path)] != manifest_sha:
        _fail("ROOT276 parent input_sha256 manifest binding differs")
    input_records = parent.get("input_records")
    if isinstance(input_records, Mapping) and str(manifest_path) in input_records:
        record = input_records[str(manifest_path)]
        if isinstance(record, Mapping):
            _ref_equal(record, expected, "ROOT276 parent input record manifest")
    root_binding = parent.get("root_canonical_binding")
    if isinstance(root_binding, Mapping):
        direct = root_binding.get("immutable_manifest_direct_path")
        if direct is not None and not _same_path(direct, str(manifest_path)):
            _fail("ROOT276 root canonical manifest path differs")
    return {
        "schema": parent["schema"],
        "manifest": expected,
        "status": parent.get("status"),
        "launch_performed": parent.get("launch_performed", parent.get("solver_started")),
    }


def build_contract_v2(
    manifest_path: Path | str,
    parent_request_path: Path | str,
    *,
    current_plan_path: Path | str,
    registry_path: Path | str,
    output_path: Path | str | None = None,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser()
    parent_request_path = Path(parent_request_path).expanduser()
    plan_path = Path(current_plan_path).expanduser()
    registry_path = Path(registry_path).expanduser()
    manifest, manifest_sha, manifest_stat = _read_json(manifest_path, "F6 v8 support manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        _fail(f"F6 support manifest schema must be {MANIFEST_SCHEMA}")
    parent, parent_sha, parent_stat = _read_json(parent_request_path, "ROOT276 parent request")
    parent_binding = _validate_parent_manifest(parent, manifest_path, manifest_sha)
    wanted = set(case_ids or {
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
    })
    plan, registry, plan_ref, registry_ref, joined = _validate_current_plan_and_registry(
        plan_path, registry_path, wanted,
    )
    cases = [_V1._case_contract(case, manifest) for case in _V1._source_current_cases(manifest, wanted)]
    current = joined.pop("current")
    result = {
        "schema": SCHEMA,
        "status": "SOURCE_PREPARED_CURRENT_V4_LIFECYCLE_METADATA_ONLY",
        "production_eligible": False,
        "launch_performed": False,
        "root276_launch_status": "WAIT_ONLY_NOT_LAUNCHED",
        "payload_content_read_by_builder": False,
        "source_manifest": {"path": str(manifest_path.resolve()), "sha256": manifest_sha, "stat": manifest_stat},
        "parent_task": {
            "namespace": 276,
            "path": str(parent_request_path.resolve()),
            "sha256": parent_sha,
            "stat": parent_stat,
            "manifest_binding": parent_binding,
            "parent_v8_is_sole_resource_owner": True,
        },
        "current_v4_lifecycle": {
            "plan": plan_ref,
            "evidence_registry": registry_ref,
            "current_catalog": current,
            "cases": joined,
            "plan_schema": PLAN_SCHEMA,
            "registry_schema": REGISTRY_SCHEMA,
        },
        "cases": cases,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "claim_boundary": {
            "scope": "F6 source-current position-only initial support and saved-mask lifecycle metadata",
            "event_labels": "UNKNOWN",
            "region_owner": "UNKNOWN",
            "control": "UNKNOWN_FOR_INITIAL_SUPPORT_ONLY",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "scientific_credit": "NONE",
        },
    }
    if output_path is not None:
        output_path = Path(output_path).expanduser()
        if output_path.exists() or output_path.is_symlink():
            _fail(f"refusing to overwrite: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_contract(
    manifest_path: Path | str,
    parent_request_path: Path | str,
    *,
    current_plan_path: Path | str | None = None,
    registry_path: Path | str | None = None,
    plan_path: Path | str | None = None,
    output_path: Path | str | None = None,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Compatibility-named entry point with strict v2 inputs required.

    ``plan_path`` is accepted as an explicit spelling used by the consumed
    v1 builder, but a v2 call still must supply both the v4 plan and registry.
    There is no pending/no-plan fallback in this version.
    """
    if current_plan_path is None:
        current_plan_path = plan_path
    if current_plan_path is None or registry_path is None:
        _fail("v2 contract requires both current_plan_path and registry_path")
    return build_contract_v2(
        manifest_path, parent_request_path,
        current_plan_path=current_plan_path, registry_path=registry_path,
        output_path=output_path, case_ids=case_ids,
    )


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
        result = build_contract_v2(
            args.manifest, args.parent_request,
            current_plan_path=args.current_plan, registry_path=args.registry,
            output_path=args.output, case_ids=set(args.cases) if args.cases else None,
        )
    except (OSError, F6ProducerRoleContractV2Error, _V1.F6ProducerRoleContractError) as error:
        print(f"F6_PRODUCER_ROLE_CONTRACT_V2_ERROR: {error}")
        return 2
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "output": str(args.output), "cases": len(result["cases"]),
                      "production_eligible": result["production_eligible"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
