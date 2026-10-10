#!/usr/bin/env python3
"""ROOT276 F6 role contract with mandatory selected-proof closure.

V3 closes the parent manifest tables.  V4 adds the same proof-level checks
used by the retry-aware event adapter: every selected producer must point to a
real successful root verification with request/manifest/receipt/report
bindings and a case-specific verification row.  Failed retry history remains
provenance and is never credited.
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


_V3 = _load("f6_producer_role_contract_v3_for_v4", SCRIPT_DIR / "ds_data02_stage2_f6_producer_role_contract_v3.py")
_V8 = _load("namespace331_event_v8_for_f6_v4", SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v8.py")

SCHEMA = "ds02.stage2.f6.producer-role-contract.v4"


class F6ProducerRoleContractV4Error(ValueError):
    """The selected F6 producer proof is incomplete or crossed."""


def _fail(message: str) -> None:
    raise F6ProducerRoleContractV4Error(message)


def build_contract_v4(
    manifest_path: Path | str,
    parent_request_path: Path | str,
    *,
    current_plan_path: Path | str,
    registry_path: Path | str,
    output_path: Path | str | None = None,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    try:
        result = _V3.build_contract_v3(
            manifest_path, parent_request_path,
            current_plan_path=current_plan_path, registry_path=registry_path,
            output_path=None, case_ids=case_ids,
        )
    except Exception as error:
        _fail(f"F6 V4 base contract: {error}")
    result = copy.deepcopy(result)
    plan_path = Path(current_plan_path).expanduser()
    registry_path = Path(registry_path).expanduser()
    plan, _ = _V8._V7._metadata_ref({"path": str(plan_path), "sha256": _V8._V7._file_sha(plan_path)}, role="F6 V4 current plan")
    registry, _ = _V8._V7._metadata_ref({"path": str(registry_path), "sha256": _V8._V7._file_sha(registry_path)}, role="F6 V4 producer registry")
    lifecycle_cases = result.get("current_v4_lifecycle", {}).get("cases", {})
    if case_ids is None:
        wanted = set(lifecycle_cases.keys()) if isinstance(lifecycle_cases, Mapping) else set()
    else:
        wanted = set(case_ids)
    if not wanted:
        _fail("F6 V4 requires at least one selected case")
    joined = result.get("current_v4_lifecycle", {}).get("cases")
    if not isinstance(joined, Mapping):
        _fail("V3 result lacks selected lifecycle cases")
    for case_id in sorted(wanted):
        selected = joined.get(case_id)
        if not isinstance(selected, Mapping):
            _fail(f"F6 V4 selected case {case_id} is missing")
        join = {
            "producer_id": selected.get("producer_id"),
            "plan_attempt_id": selected.get("attempt_id"),
            "failed_history_count": 0,
        }
        try:
            proof_closure = _V8._selected_proof_join(plan, registry, case_id, join)
        except Exception as error:
            _fail(f"F6 V4 selected proof {case_id}: {error}")
        selected = dict(selected)
        selected["mandatory_selected_proof_closure"] = proof_closure
        joined[case_id] = selected
    result["schema"] = SCHEMA
    result["proof_contract"] = {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "required_fields": ["request", "request_sha256", "manifest", "manifest_sha256",
                             "receipt", "receipt_sha256", "report", "report_sha256",
                             "case_verifications", "counts", "failed_cases",
                             "parent_reservation_released", "guarded_receipt_status",
                             "outer_unit_result"],
        "selected_case_crossbind": ["case_manifest", "case_receipt", "summary", "source_trajectory"],
        "scientific_credit": "NONE",
    }
    result["claim_boundary"]["contract_version"] = "v4"
    if output_path is not None:
        target = Path(output_path).expanduser()
        if target.exists() or target.is_symlink():
            _fail(f"refusing to overwrite: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_contract(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return build_contract_v4(*args, **kwargs)


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
        result = build_contract_v4(
            args.manifest, args.parent_request, current_plan_path=args.current_plan,
            registry_path=args.registry, output_path=args.output,
            case_ids=set(args.cases) if args.cases else None,
        )
    except (OSError, F6ProducerRoleContractV4Error) as error:
        print(f"F6_PRODUCER_ROLE_CONTRACT_V4_ERROR: {error}")
        return 2
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "output": str(args.output), "cases": len(result["cases"]),
                      "production_eligible": result["production_eligible"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
