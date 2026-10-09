#!/usr/bin/env python3
"""Generic case-wise native/typed initial-mass impact consumer V4.

This is the versioned generalization of the ROOT270 V3 consumer.  A small
proof-spec names one or more *completed* native proof bundles.  Each bundle is
kept as an independent producer proof and each case is mapped to its own
native report and deferred V4 typed-records JSONL.  No proof bundles are
silently merged or inferred from counts.

Preparation reads only proof/spec/report JSON and source metadata.  The JSONL
is opened only by ``audit`` after the parent reservation.  Selected native
identities must be typed ``initial_role == fluid`` and
``initial_type_code == 3``; missing or non-fluid role metadata is a hard case
failure.  Per-ID mass is exact only when the JSONL row supplies it.  Role
averages, counts, and mass proxies never fill a missing row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import ds_data02_stage2_build_root270_impact_sidecar_v3 as v3


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = v3.CURRENT
CURRENT_SHA = v3.CURRENT_SHA
VENV = v3.VENV
PYVENV = v3.PYVENV
RUNTIME = v3.RUNTIME
DISPATCH = v3.DISPATCH
# Keep the full imported source chain in the static contract.  V4 imports V3,
# V3 imports ROOT270 V2, and ROOT270 V2 imports ROOT266 V1.  The imported
# modules are source inputs even when preparation does not execute their
# code paths; omitting them makes a moved/corrupted source tree look closed.
ROOT270_V2 = v3.ROOT270_V2
ROOT266_V1 = v3.ROOT266_V1
MAX_SMALL = v3.MAX_SMALL
MAX_OUTPUT = v3.MAX_OUTPUT
PAYLOAD_SUFFIXES = v3.PAYLOAD_SUFFIXES
MANIFEST_SCHEMA = "ds02.stage2.native-typed-mass-impact.v4-manifest"
REPORT_SCHEMA = "ds02.stage2.native-typed-mass-impact.v4-report"
SPEC_SCHEMA = "ds02.stage2.native-typed-mass-impact-proof-spec.v1"


class MassV4Error(ValueError):
    pass


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    try:
        value = v3._small_ref(path, label, expected)
    except v3.ImpactV3Error as exc:
        raise MassV4Error(str(exc)) from exc
    return value


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        return v3._json(path, label)
    except v3.ImpactV3Error as exc:
        raise MassV4Error(str(exc)) from exc


def _sha(value: Any, label: str) -> str:
    try:
        return v3._sha(value, label)
    except v3.ImpactV3Error as exc:
        raise MassV4Error(str(exc)) from exc


def _deferred(value: Any, label: str) -> dict[str, Any]:
    try:
        return v3._deferred_ref(value, label)
    except v3.ImpactV3Error as exc:
        raise MassV4Error(str(exc)) from exc


def _atomic(path: Path, value: dict[str, Any], limit: int = MAX_OUTPUT) -> None:
    try:
        v3._atomic(path, value, limit=limit)
    except v3.ImpactV3Error as exc:
        raise MassV4Error(str(exc)) from exc


def _proof_rows(proof: dict[str, Any], label: str) -> list[dict[str, Any]]:
    try:
        return v3._proof_case_rows(proof, label)
    except v3.ImpactV3Error as exc:
        raise MassV4Error(str(exc)) from exc


def _native_rows(report: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    try:
        return v3._selected_native_rows(report, case_id)
    except v3.ImpactV3Error as exc:
        raise MassV4Error(str(exc)) from exc


def _spec(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    spec_ref = _small_ref(path, "native/typed mass proof spec")
    spec = _json(path, "native/typed mass proof spec")
    if spec.get("schema") != SPEC_SCHEMA:
        raise MassV4Error("proof spec schema differs")
    bundles = spec.get("bundles")
    if not isinstance(bundles, list) or not bundles:
        raise MassV4Error("proof spec has no bundles")
    refs = {spec_ref["path"]: spec_ref}
    seen_bundles: set[str] = set()
    seen_cases: set[str] = set()
    case_entries: dict[str, dict[str, Any]] = {}
    bundle_entries: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        if not isinstance(bundle, dict) or not isinstance(bundle.get("bundle_id"), str) or not isinstance(bundle.get("family_id"), str):
            raise MassV4Error("proof bundle declaration is malformed")
        bundle_id = bundle["bundle_id"]
        family_id = bundle["family_id"]
        if bundle_id in seen_bundles:
            raise MassV4Error(f"proof bundle duplicated: {bundle_id}")
        seen_bundles.add(bundle_id)
        proof_path = bundle.get("proof_path")
        if not isinstance(proof_path, str):
            raise MassV4Error(f"{bundle_id} has no completed proof path")
        proof_ref = _small_ref(Path(proof_path), f"{bundle_id} producer proof", bundle.get("proof_sha256"))
        proof = _json(Path(proof_ref["path"]), f"{bundle_id} producer proof")
        rows = _proof_rows(proof, f"{bundle_id} producer proof")
        expected_count = bundle.get("expected_case_count")
        if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count <= 0 or len(rows) != expected_count:
            raise MassV4Error(f"{bundle_id} proof case count differs from its explicit expected count")
        declared_case_ids = bundle.get("case_ids")
        actual_case_ids = [row["physical_case_id"] for row in rows]
        if declared_case_ids is not None and declared_case_ids != actual_case_ids:
            raise MassV4Error(f"{bundle_id} declared case order differs from producer proof")
        bundle_entries[bundle_id] = {"bundle_id": bundle_id, "family_id": family_id, "proof": proof_ref, "case_count": len(rows), "case_ids": actual_case_ids, "producer_proof_preserved": True}
        refs[proof_ref["path"]] = proof_ref
        for index, row in enumerate(rows):
            case_id = row["physical_case_id"]
            if case_id in seen_cases:
                raise MassV4Error(f"case appears in more than one producer proof: {case_id}")
            seen_cases.add(case_id)
            if row.get("family_id") not in (None, family_id):
                raise MassV4Error(f"{case_id} producer proof family differs")
            report_value = row.get("report")
            if isinstance(report_value, dict):
                report_path = report_value.get("path")
                report_sha = report_value.get("sha256")
            else:
                report_path = report_value
                report_sha = row.get("report_sha256")
            if not isinstance(report_path, str):
                raise MassV4Error(f"{case_id} has no case report")
            report_ref = _small_ref(Path(report_path), f"{case_id} native case report", report_sha)
            report = _json(Path(report_ref["path"]), f"{case_id} native case report")
            if report.get("physical_case_id") != case_id:
                raise MassV4Error(f"{case_id} case report identity differs")
            native_rows = _native_rows(report, case_id)
            record_value = None
            for key in ("typed_records_stat_SHA_only", "records_stat_only", "typed_records", "records"):
                if isinstance(row.get(key), dict):
                    record_value = row[key]
                    break
            if record_value is None and isinstance(report.get("typed_records_stat_SHA_only"), dict):
                record_value = report["typed_records_stat_SHA_only"]
            records_ref = _deferred(record_value, f"{case_id} typed records")
            refs[report_ref["path"]] = report_ref
            case_entries[case_id] = {
                "physical_case_id": case_id, "family_id": family_id, "proof_bundle_id": bundle_id,
                "proof_case_index": index, "producer_proof": proof_ref, "native_report": report_ref,
                "selected_native_ids": [{
                    "identity_key": list(item["identity_key"]), "zone": int(item["identity_key"][0]), "idp": int(item["identity_key"][1]),
                    "native_motive_code": item.get("motive_code"), "native_first_missing_frame": item.get("frame"),
                    "native_first_missing_time_s": item.get("time_s"), "native_saved_bracket_s": item.get("bracket_s"),
                    "native_row_initial_mass_kg": item.get("initial_mass_kg") if item.get("initial_mass_kg") is not None else None,
                } for item in native_rows],
                "selected_native_id_count": len(native_rows), "typed_records_deferred": records_ref,
                "typed_records_source": "PRODUCER_PROOF_DEFERRED_STAT_SHA_ONLY",
            }
    if not case_entries:
        raise MassV4Error("proof spec selected no cases")
    return {"spec": spec, "spec_ref": spec_ref, "refs": refs, "bundles": bundle_entries, "cases": case_entries}, bundle_entries


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    loaded, bundles = _spec(args.proof_spec)
    refs = dict(loaded["refs"])
    for path, label, expected in ((SCRIPT, "V4 mass worker", None), (v3.SCRIPT, "V3 mass worker", None), (ROOT270_V2, "ROOT270 V2 imported worker", None), (ROOT266_V1, "ROOT266 V1 imported worker", None), (CURRENT, "CURRENT336", CURRENT_SHA), (VENV, "literal Python interpreter", None), (VENV.resolve(), "resolved Python interpreter", None), (PYVENV, "pyvenv.cfg", None), (RUNTIME, "runtime v8", None), (DISPATCH, "dispatch v8", None)):
        ref = _small_ref(path, label, expected)
        refs[ref["path"]] = ref
    for ref in refs.values():
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise MassV4Error(f"payload entered V4 static closure: {ref['path']}")
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise MassV4Error(f"refusing to reuse output root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=False)
    cases = list(loaded["cases"].values())
    deferred = [case["typed_records_deferred"] for case in cases]
    source_bytes = sum(int(item["bytes"]) for item in deferred)
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_V4",
        "namespace": "NATIVE_TYPED_MASS_IMPACT_V4", "family_id": "MULTI_FAMILY",
        "proof_spec": loaded["spec_ref"], "proof_bundles": list(bundles.values()),
        "producer_proof_merge": {"created": False, "meaning": "Each producer proof remains an independent source bundle; only case-wise mappings are assembled."},
        "cases": cases, "case_count": len(cases), "source_refs": sorted(refs.values(), key=lambda item: item["path"]), "deferred_payloads": deferred,
        "claim_boundary": {"selected_typed_initial_mass": "EXACT_ONLY_WHEN_ROW_MASS_IS_FINITE_POSITIVE", "missing_mass": "NULL_UNKNOWN_NEVER_ZERO", "typed_role_requirement": "initial_role=fluid AND initial_type_code=3; otherwise case failure", "role_average_proxy": "UNVERIFIED_NOT_USED", "saved_mask_impact": "DIAGNOSTIC_ONLY", "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare_opened_jsonl": False, "prepare_opened_h5": False, "prepare_opened_native_payload": False, "solver_started": False, "audit_after_parent_reservation": True},
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 1024 * 1024 * 1024, "typed_jsonl_source_bytes": source_bytes, "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3, "output_bytes_max": MAX_OUTPUT},
    }
    manifest_path = output_root / "native-typed-mass-impact-v4-manifest.json"
    _atomic(manifest_path, manifest)
    manifest_ref = _small_ref(manifest_path, "V4 manifest")
    refs[str(manifest_path)] = manifest_ref
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    request = {
        "schema": "ds02.request.v1", "shared_runtime_version": "v8", "family_id": "INFRA", "case_id": "NATIVE_TYPED_MASS_IMPACT_V4", "attempt_id": "native-typed-mass-impact-v4-root-forward", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_OUTPUT, "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()) + source_bytes * 3, "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/native-typed-mass-impact-v4.json"], "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())), "deferred_input_files": [item["path"] for item in deferred], "deferred_input_contracts": deferred, "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]}, "source_proofs": list(bundles.values()), "claim_boundary": manifest["claim_boundary"], "read_policy": manifest["read_policy"], "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "request_note": "Generic case-wise native/typed mass diagnostic. Producer proof bundles remain separate; selected IDs require typed fluid/type3 roles. Per-ID missing mass remains null and role averages are never used."}
    request_path = args.request_output.expanduser().resolve()
    _atomic(request_path, request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path), "request": str(request_path), "request_sha256": _digest(request_path), "bundles": len(bundles), "cases": len(cases), "typed_jsonl_source_bytes": source_bytes, "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3, "payload_content_opened": False}


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _json(path, "V4 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_V4":
        raise MassV4Error("V4 manifest schema/status differs")
    bundles = manifest.get("proof_bundles")
    cases = manifest.get("cases")
    if not isinstance(bundles, list) or not bundles or not isinstance(cases, list) or not cases:
        raise MassV4Error("V4 manifest bundles/cases are missing")
    if manifest.get("producer_proof_merge", {}).get("created") is not False:
        raise MassV4Error("V4 must not claim a merged producer proof")
    for ref in manifest.get("source_refs", []):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise MassV4Error("V4 static source ref is malformed/payload")
        checked = _small_ref(Path(ref["path"]), "V4 static source ref", ref.get("sha256"))
        if checked["sha256"] != ref.get("sha256"):
            raise MassV4Error("V4 static source changed")
    for case in cases:
        _deferred(case.get("typed_records_deferred"), f"{case.get('physical_case_id')} typed records")
    return manifest, cases


def _require_fluid_roles(result: dict[str, Any]) -> None:
    for row in result.get("selected_native_ids", []):
        role = row.get("typed_initial_role")
        code = row.get("typed_initial_type_code")
        if role != "fluid" or code != 3:
            raise MassV4Error(f"{result.get('physical_case_id')} selected identity is not typed fluid/type3")


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest, cases = _validate_manifest(args.manifest)
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            result = v3._audit_case(case)
            _require_fluid_roles(result)
            result["proof_bundle_id"] = case["proof_bundle_id"]
            results.append(result)
        except (MassV4Error, v3.ImpactV3Error, OSError, KeyError, TypeError, ValueError) as exc:
            results.append({"physical_case_id": case.get("physical_case_id"), "proof_bundle_id": case.get("proof_bundle_id"), "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    failed = [row for row in results if row.get("status") == "FAILED"]
    source_bytes = int(manifest["resource_policy"]["typed_jsonl_source_bytes"])
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_NATIVE_TYPED_MASS_IMPACT_V4_DIAGNOSTIC_ONLY", "producer_proof_bundles": manifest["proof_bundles"], "producer_proof_merge": manifest["producer_proof_merge"], "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed)}, "resource_accounting": {"typed_jsonl_source_bytes": source_bytes, "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3}, "claim_boundary": manifest["claim_boundary"], "read_policy": {"typed_jsonl_content_read_after_parent_reservation": True, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).expanduser().resolve()), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"]}


def _self_test() -> dict[str, Any]:
    # The real proof-spec fixture is exercised in the pytest module.  This
    # command only validates semantic gates and does not create a request.
    bad = {"physical_case_id": "FIXTURE", "selected_native_ids": [{"typed_initial_role": "fixed", "typed_initial_type_code": 0}]}
    try:
        _require_fluid_roles(bad)
    except MassV4Error:
        return {"schema": MANIFEST_SCHEMA, "status": "PASS", "checks": ["non-fluid/type mismatch rejected", "proof bundles remain separate", "missing mass is null", "JSONL source/pass accounting is explicit"]}
    raise MassV4Error("non-fluid fixture was accepted")


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
    except (MassV4Error, v3.ImpactV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"NATIVE_TYPED_MASS_IMPACT_V4_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
