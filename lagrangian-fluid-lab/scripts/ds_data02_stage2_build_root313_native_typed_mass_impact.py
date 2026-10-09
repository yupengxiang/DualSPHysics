#!/usr/bin/env python3
"""Prepare/audit ROOT313's three-bundle typed initial-mass diagnostic.

ROOT313 is a source-only composition of the already reviewed V4 mass
consumer.  It accepts exactly the completed ROOT258/F6, ROOT264/F4, and
ROOT268/F6 producer proof bundles.  The proof files and their small case
reports are read during preparation; the typed lifecycle JSONL files remain
deferred until an owning parent reservation.  Each producer proof stays an
independent bundle and is mapped case by case.  This product reports saved
sample/identity mass diagnostics only: physical fate, flux, dynamics, and
QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import ds_data02_stage2_build_native_typed_mass_impact_v4 as v4


SCRIPT = Path(__file__).resolve()
PRIMARY = v4.PRIMARY
STAGE2 = v4.STAGE2
V4_WORKER = v4.SCRIPT
V3_WORKER = v4.v3.SCRIPT
ROOT270_V2 = v4.ROOT270_V2
ROOT266_V1 = v4.ROOT266_V1
CURRENT = v4.CURRENT
CURRENT_SHA = v4.CURRENT_SHA
VENV = v4.VENV
PYVENV = v4.PYVENV
RUNTIME = v4.RUNTIME
DISPATCH = v4.DISPATCH
MAX_SMALL = v4.MAX_SMALL
MAX_OUTPUT = v4.MAX_OUTPUT
PAYLOAD_SUFFIXES = v4.PAYLOAD_SUFFIXES

SPEC_SCHEMA = v4.SPEC_SCHEMA
MANIFEST_SCHEMA = "ds02.stage2.native-typed-mass-impact.root313-manifest"
REPORT_SCHEMA = "ds02.stage2.native-typed-mass-impact.root313-report"
MANIFEST_STATUS = "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_ROOT313"
EXPECTED_BUNDLES = {
    "ROOT258": {"family_id": "F6", "case_count": 7},
    "ROOT264": {"family_id": "F4", "case_count": 3},
    "ROOT268": {"family_id": "F6", "case_count": 7},
}


class Root313Error(ValueError):
    pass


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    try:
        return v4._small_ref(path, label, expected)
    except (v4.MassV4Error, v4.v3.ImpactV3Error) as exc:
        raise Root313Error(str(exc)) from exc


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        return v4._json(path, label)
    except (v4.MassV4Error, v4.v3.ImpactV3Error) as exc:
        raise Root313Error(str(exc)) from exc


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT) -> None:
    try:
        v4._atomic(path, value, limit=limit)
    except (v4.MassV4Error, v4.v3.ImpactV3Error) as exc:
        raise Root313Error(str(exc)) from exc


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _loaded_spec(path: Path) -> dict[str, Any]:
    try:
        loaded, _ = v4._spec(path)
    except (v4.MassV4Error, v4.v3.ImpactV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        raise Root313Error(str(exc)) from exc
    spec = loaded["spec"]
    bundles = loaded["bundles"]
    if set(bundles) != set(EXPECTED_BUNDLES) or len(bundles) != len(EXPECTED_BUNDLES):
        raise Root313Error("ROOT313 requires exactly ROOT258, ROOT264, and ROOT268 proof bundles")
    for bundle_id, expected in EXPECTED_BUNDLES.items():
        bundle = bundles[bundle_id]
        if bundle["family_id"] != expected["family_id"] or bundle["case_count"] != expected["case_count"]:
            raise Root313Error(f"{bundle_id} family/case count differs from the ROOT313 contract")
    if len(loaded["cases"]) != sum(item["case_count"] for item in EXPECTED_BUNDLES.values()):
        raise Root313Error("ROOT313 case count is not 17")
    if len({case["physical_case_id"] for case in loaded["cases"].values()}) != 17:
        raise Root313Error("ROOT313 producer bundles contain duplicate physical cases")
    return loaded


def _source_chain(loaded: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = dict(loaded["refs"])
    chain = (
        (SCRIPT, "ROOT313 mass builder", None),
        (V4_WORKER, "V4 imported mass worker", None),
        (V3_WORKER, "V3 imported mass worker", None),
        (ROOT270_V2, "ROOT270 V2 imported mass worker", None),
        (ROOT266_V1, "ROOT266 V1 imported mass worker", None),
        (CURRENT, "CURRENT336", CURRENT_SHA),
        (VENV, "literal Python interpreter", None),
        (VENV.resolve(), "resolved Python interpreter", None),
        (PYVENV, "pyvenv.cfg", None),
        (RUNTIME, "runtime v8", None),
        (DISPATCH, "dispatch v8", None),
    )
    for path, label, expected in chain:
        ref = _small_ref(path, label, expected)
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise Root313Error(f"payload entered ROOT313 static closure: {ref['path']}")
        refs[ref["path"]] = ref
    for ref in refs.values():
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise Root313Error(f"payload entered ROOT313 static closure: {ref['path']}")
    return refs


def _adaptation(loaded: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for bundle_id in ("ROOT258", "ROOT264", "ROOT268"):
        bundle = loaded["bundles"][bundle_id]
        result.append({
            "bundle_id": bundle_id,
            "status": "SUPPORTED_EXACT_SOURCE_MAPPING",
            "proof_schema": "ds02.stage2.root-actual-verification.v1",
            "case_rows_source": "case_verifications[]",
            "completed_count_source": "actual_completed_physical_cases",
            "report_edge_source": "case_verifications[].report + report_sha256",
            "typed_records_edge_source": "case_verifications[].typed_records_stat_SHA_only",
            "independent_proof_preserved": True,
            "unsupported": [
                "case_results/cases aliases without a versioned adapter",
                "missing report/report_sha256 or typed_records_stat_SHA_only",
                "merged producer proof or cross-bundle case deduplication",
                "physical fate/flux/dynamics/Q inference from saved-mask rows",
            ],
        })
    return result


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    loaded = _loaded_spec(args.proof_spec)
    refs = _source_chain(loaded)
    cases = list(loaded["cases"].values())
    bundles = []
    for bundle_id in ("ROOT258", "ROOT264", "ROOT268"):
        bundle = dict(loaded["bundles"][bundle_id])
        bundle_cases = [case for case in cases if case["proof_bundle_id"] == bundle_id]
        bundle_source_bytes = sum(int(case["typed_records_deferred"]["bytes"]) for case in bundle_cases)
        bundle.update({
            "typed_jsonl_source_bytes": bundle_source_bytes,
            "typed_jsonl_minimum_three_pass_read_bytes": bundle_source_bytes * 3,
            "typed_jsonl_case_count": len(bundle_cases),
        })
        bundles.append(bundle)
    source_bytes = sum(int(case["typed_records_deferred"]["bytes"]) for case in cases)
    if source_bytes <= 0:
        raise Root313Error("ROOT313 has no deferred typed source bytes")
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise Root313Error(f"refusing to reuse output root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": MANIFEST_STATUS,
        "namespace": "ROOT313_NATIVE_TYPED_MASS_IMPACT",
        "family_id": "MULTI_FAMILY",
        "case_count": len(cases),
        "bundle_count": len(bundles),
        "proof_spec": loaded["spec_ref"],
        "proof_bundles": bundles,
        "proof_schema_adaptation": _adaptation(loaded),
        "import_source_closure": [
            {"role": "root313_builder", "path": str(SCRIPT)},
            {"role": "v4_mass_worker", "path": str(V4_WORKER)},
            {"role": "v3_mass_worker", "path": str(V3_WORKER)},
            {"role": "root270_v2_mass_worker", "path": str(ROOT270_V2)},
            {"role": "root266_v1_mass_worker", "path": str(ROOT266_V1)},
        ],
        "producer_proof_merge": {"created": False, "meaning": "ROOT258, ROOT264, and ROOT268 remain independent producer proof bundles; only exact case-wise mappings are assembled."},
        "cases": cases,
        "source_refs": sorted(refs.values(), key=lambda item: item["path"]),
        "deferred_payloads": [case["typed_records_deferred"] for case in cases],
        "claim_boundary": {
            "selected_typed_initial_mass": "EXACT_ONLY_WHEN_TYPED_JSONL_ROW_HAS_FINITE_POSITIVE_INITIAL_MASS_KG",
            "missing_selected_typed_mass": "NULL_UNKNOWN_NEVER_ZERO",
            "typed_role_requirement": "initial_role=fluid AND initial_type_code=3; otherwise case failure",
            "role_average_mass_proxy": "UNVERIFIED_NOT_USED",
            "saved_mask_mass_and_count": "DIAGNOSTIC_ONLY",
            "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN",
            "continuous_event_time": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "read_policy": {
            "prepare_opened_jsonl": False, "prepare_opened_h5": False, "prepare_opened_native_payload": False,
            "solver_started": False,
            "audit_deferred_jsonl": "Only after parent reservation; three bounded passes per case (pre-hash, parse+hash, post-hash).",
        },
        "resource_policy": {
            "cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024,
            "typed_jsonl_source_bytes": source_bytes,
            "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3,
            "output_bytes_max": MAX_OUTPUT,
        },
    }
    manifest_path = output_root / "root313-native-typed-mass-impact-manifest.json"
    _atomic(manifest_path, manifest)
    manifest_ref = _small_ref(manifest_path, "ROOT313 manifest")
    refs[manifest_ref["path"]] = manifest_ref
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    request_path = args.request_output.expanduser().resolve()
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/root313-native-typed-mass-impact.json"]
    request = {
        "schema": "ds02.request.v1", "shared_runtime_version": "v8", "family_id": "INFRA",
        "case_id": "ROOT313_NATIVE_TYPED_MASS_IMPACT", "attempt_id": "root313-native-typed-mass-impact-root-forward-313",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_OUTPUT,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()) + source_bytes * 3,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command,
        "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": [case["typed_records_deferred"]["path"] for case in cases],
        "deferred_input_contracts": [case["typed_records_deferred"] for case in cases],
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "source_proofs": bundles,
        "import_source_closure": manifest["import_source_closure"],
        "claim_boundary": manifest["claim_boundary"], "read_policy": manifest["read_policy"],
        "execution_allowed": True, "launch_allowed": True, "launch_owner": "root",
        "request_note": "ROOT313 composes three independent completed native proof bundles (ROOT258/F6 seven cases, ROOT264/F4 three cases, ROOT268/F6 seven cases). It is a saved-mask/sample mass diagnostic only; physical fate, flux, dynamics, and QI/QN/QE remain UNKNOWN.",
    }
    _atomic(request_path, request)
    return {
        "status": MANIFEST_STATUS, "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path),
        "request": str(request_path), "request_sha256": _digest(request_path),
        "bundle_count": len(bundles), "case_count": len(cases),
        "bundle_ids": [bundle["bundle_id"] for bundle in bundles],
        "typed_jsonl_source_bytes": source_bytes,
        "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3,
        "payload_content_opened": False, "launch_allowed": True,
    }


def _validate_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _json(path, "ROOT313 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != MANIFEST_STATUS:
        raise Root313Error("ROOT313 manifest schema/status differs")
    if manifest.get("case_count") != 17 or manifest.get("bundle_count") != 3:
        raise Root313Error("ROOT313 manifest does not contain 17 cases and 3 bundles")
    bundles = manifest.get("proof_bundles")
    cases = manifest.get("cases")
    if not isinstance(bundles, list) or not isinstance(cases, list):
        raise Root313Error("ROOT313 manifest bundles/cases are malformed")
    if {bundle.get("bundle_id") for bundle in bundles} != set(EXPECTED_BUNDLES):
        raise Root313Error("ROOT313 manifest bundle IDs differ")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("physical_case_id"), str):
            raise Root313Error("ROOT313 case is malformed")
        if case["physical_case_id"] in seen:
            raise Root313Error("ROOT313 case IDs are not unique")
        seen.add(case["physical_case_id"])
        v4._deferred(case.get("typed_records_deferred"), f"{case['physical_case_id']} typed records")
    if len(seen) != 17:
        raise Root313Error("ROOT313 case IDs are incomplete")
    for ref in manifest.get("source_refs", []):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise Root313Error("ROOT313 source ref is malformed")
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise Root313Error("ROOT313 static closure contains a payload")
        _small_ref(Path(ref["path"]), "ROOT313 static source ref", ref.get("sha256"))
    return manifest, cases


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest, cases = _validate_manifest(args.manifest)
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            result = v4.v3._audit_case(case)
            v4._require_fluid_roles(result)
            result["proof_bundle_id"] = case.get("proof_bundle_id")
            results.append(result)
        except (Root313Error, v4.MassV4Error, v4.v3.ImpactV3Error, OSError, KeyError, TypeError, ValueError) as exc:
            results.append({"physical_case_id": case.get("physical_case_id"), "proof_bundle_id": case.get("proof_bundle_id"), "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    failed = [row for row in results if row.get("status") == "FAILED"]
    source_bytes = int(manifest["resource_policy"]["typed_jsonl_source_bytes"])
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_ROOT313_NATIVE_TYPED_MASS_IMPACT_DIAGNOSTIC_ONLY",
        "producer_proof_bundles": manifest["proof_bundles"], "proof_schema_adaptation": manifest["proof_schema_adaptation"],
        "producer_proof_merge": manifest["producer_proof_merge"], "case_results": results,
        "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed)},
        "resource_accounting": {"typed_jsonl_source_bytes": source_bytes, "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3},
        "claim_boundary": manifest["claim_boundary"], "read_policy": {"typed_jsonl_content_read_after_parent_reservation": True, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).expanduser().resolve()), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"]}


def _self_test() -> dict[str, Any]:
    if set(EXPECTED_BUNDLES) != {"ROOT258", "ROOT264", "ROOT268"}:
        raise Root313Error("ROOT313 expected bundle contract changed")
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "checks": ["three independent producer bundles required", "17 unique physical cases required", "full V4/V3/ROOT270/ROOT266 import closure required", "three-pass JSONL accounting explicit", "physical fate and Q remain UNKNOWN"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--proof-spec", type=Path, required=True)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--manifest", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (Root313Error, v4.MassV4Error, v4.v3.ImpactV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ROOT313_NATIVE_TYPED_MASS_IMPACT_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
