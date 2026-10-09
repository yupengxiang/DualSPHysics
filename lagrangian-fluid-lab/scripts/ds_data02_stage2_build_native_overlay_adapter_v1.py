#!/usr/bin/env python3
"""Prepare and admit a proof-bound native/typed join overlay.

``prepare`` consumes only JSON/source metadata for the already prepared
ROOT312 and ROOT315--ROOT321 batches.  It preserves each complete producer
proof and records the selected case contracts without opening JSONL, H5,
BI4, OBI4, PartOut, or RunPARTs payloads.  The resulting request is a
metadata-only parent handoff; it cannot launch a native worker.

``admit`` is the later, guarded-only step.  It accepts one completed generic
worker report per source batch, runs the strict V5 verifier, and emits an
additive join overlay.  The overlay grants saved-frame typed/native join
credit for verified cases only.  It never grants native-cause, physical
fate, legal-flux, dynamics, or QI/QN/QE credit.

The adapter is intentionally separate from the historical V10 overlay.  A
V5 worker report is not silently rewritten as a producer proof and is not
inserted into ``actual_join_proofs`` until an independent consumer performs
that adjudication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT = Path(__file__).resolve()
SCRIPTS = SCRIPT.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ds_data02_stage2_verify_generic_native_join_v5 as v5


ADAPTER_SCHEMA = "ds02.stage2.original118-native-typed-native-join-actual-overlay-adapter.v1"
OVERLAY_SCHEMA = "ds02.stage2.original118-native-typed-native-join-actual-overlay.v1"
REQUEST_SCHEMA = "ds02.stage2.native-overlay-adapter-request.v1"
PLAN_SCHEMA = v5.PLAN_SCHEMA
CURRENT_SCHEMA = v5.CURRENT_SCHEMA
MAX_JSON = 12 * 1024 * 1024
PAYLOAD_SUFFIXES = set(v5.PAYLOAD_SUFFIXES)


class AdapterError(ValueError):
    pass


def _fail(message: str) -> None:
    raise AdapterError(message)


def _sha256(path: Path, label: str, *, max_bytes: int = MAX_JSON) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        _fail(f"{label} is missing: {path}")
    if path.stat().st_size > max_bytes:
        _fail(f"{label} exceeds bounded metadata size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path_value: Any, label: str, *, expected_sha: str | None = None, max_bytes: int = MAX_JSON) -> dict[str, Any]:
    if not isinstance(path_value, (str, Path)) or not str(path_value):
        _fail(f"{label} path is malformed")
    path = Path(path_value).expanduser().resolve()
    before = path.stat()
    actual_sha = _sha256(path, label, max_bytes=max_bytes)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino, before.st_dev) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino, after.st_dev):
        _fail(f"{label} changed during capture: {path}")
    if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and actual_sha != expected_sha:
        _fail(f"{label} SHA differs: {path}")
    return {
        "path": str(path),
        "bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "st_dev": int(after.st_dev),
        "st_ino": int(after.st_ino),
        "sha256": actual_sha,
    }


def _json(path_value: Any, label: str, *, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = _ref(path_value, label, expected_sha=expected_sha)
    try:
        document = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"{label} is not valid bounded JSON: {ref['path']}") from exc
    if not isinstance(document, dict):
        _fail(f"{label} must contain a JSON object")
    return document, ref


def _concrete_ref(value: Any, label: str, *, allow_payload: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        _fail(f"{label} reference is malformed")
    path = Path(value["path"]).expanduser().resolve()
    if not allow_payload and path.suffix.lower() in PAYLOAD_SUFFIXES:
        _fail(f"{label} payload entered static closure: {path}")
    expected = value.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64 or expected == "PARENT_GUARD_COMPUTED":
        _fail(f"{label} requires a concrete SHA-256")
    return _ref(str(path), label, expected_sha=expected)


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_JSON) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > limit:
        _fail(f"output exceeds bounded metadata size: {path}")
    path.write_bytes(encoded)
    return _ref(str(path), f"written output {path}")


def _load_scope(scope_path: Path, plan_path: Path, current_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        scope, scope_ref = v5._load_scope_v5(scope_path, plan_path, current_path)
    except Exception as exc:
        raise AdapterError(f"V5 scope preflight failed: {exc}") from exc
    return scope, scope_ref


def _candidate_ref(candidate: dict[str, Any], field: str, label: str) -> tuple[Path, dict[str, Any]]:
    value = candidate.get(field)
    if not isinstance(value, dict):
        _fail(f"{label} lacks {field} reference")
    path = value.get("path")
    actual = _concrete_ref(value, f"{label} {field}")
    return Path(path).expanduser().resolve(), actual


def _batch_from_manifest(*, source_id: str, family: str, manifest_path: Path, request_path: Path, scope: dict[str, Any], source_preflight_ref: dict[str, Any], selected_hint: list[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        manifest, manifest_ref, contracts = v5._load_worker_manifest_v5(manifest_path, scope)
    except Exception as exc:
        raise AdapterError(f"{source_id} manifest/source proof preflight failed: {exc}") from exc
    if manifest.get("family_id") != family:
        _fail(f"{source_id} manifest family differs: {manifest.get('family_id')} != {family}")
    case_ids = list(manifest.get("physical_case_ids", []))
    if not case_ids or len(case_ids) != len(set(case_ids)):
        _fail(f"{source_id} manifest physical case IDs are not exact")
    if selected_hint is not None and set(selected_hint) != set(case_ids):
        _fail(f"{source_id} preflight selected IDs differ from manifest")
    selected = set(case_ids)
    if not selected.issubset(scope["selected"]):
        _fail(f"{source_id} includes a non-canonical/alias/existing case")
    # Ensure the request itself is source-bound to this manifest.  This opens
    # only the request JSON and static refs; its deferred payloads remain shut.
    request, request_ref = v5.v3.v2._load_request(request_path, manifest_path, manifest_ref, manifest)
    if request.get("family_id") != family:
        _fail(f"{source_id} request family differs")
    rows: list[dict[str, Any]] = []
    proof_paths: dict[str, dict[str, Any]] = {}
    contract_paths: dict[str, dict[str, Any]] = {}
    for case_id in case_ids:
        entry = contracts[case_id]
        contract_paths[case_id] = entry["ref"]
        proof_row = entry.get("v5_proof_row")
        proof_ref = entry.get("v5_proof_ref")
        if not isinstance(proof_row, dict) or not isinstance(proof_ref, dict):
            _fail(f"{source_id}/{case_id} lacks producer proof row")
        proof_paths[proof_ref["path"]] = proof_ref
        typed = proof_row.get("records_stat_only") or proof_row.get("typed_records_stat_only")
        summary = proof_row.get("summary")
        if not isinstance(summary, (str, dict)) or not isinstance(typed, dict):
            _fail(f"{source_id}/{case_id} proof lacks typed summary/records edges")
        # Keep deferred payload references as metadata only.  No bytes are
        # opened here; the parent-reserved worker owns their first SHA.
        summary_ref = summary if isinstance(summary, dict) else {"path": summary, "sha256": proof_row.get("summary_sha256")}
        rows.append({
            "physical_case_id": case_id,
            "contract": contract_paths[case_id],
            "producer_proof": proof_ref,
            "producer_proof_row": {
                "physical_case_id": case_id,
                "summary": summary_ref,
                "records_stat_only": typed,
                "case_manifest": {"path": proof_row.get("case_manifest"), "sha256": proof_row.get("case_manifest_sha256")},
                "receipt": {"path": proof_row.get("receipt"), "sha256": proof_row.get("receipt_sha256")},
            },
            "actual_result": {
                "status": "DEFERRED_UNTIL_PARENT_GUARDED_WORKER_REPORT",
                "report": {"path": "{attempt_root}/generic-native-extract.json", "sha256": "PARENT_GUARD_COMPUTED"},
                "content_opened_by_preparer": False,
            },
        })
    return {
        "source_id": source_id,
        "family_id": family,
        "case_count": len(case_ids),
        "physical_case_ids": case_ids,
        "manifest": manifest_ref,
        "request": request_ref,
        "source_preflight": source_preflight_ref,
        "proof_bundles": [{"path": ref["path"], "sha256": ref["sha256"]} for ref in proof_paths.values()],
        "contracts": rows,
        "launch_allowed": False,
        "payload_content_opened": False,
        "claim_boundary": {"native_id_join": "DEFERRED", "native_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }, request


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    scope, scope_ref = _load_scope(args.scope, args.lifecycle_plan, args.current)
    root_preflight, root_preflight_ref = _json(args.root312_preflight, "ROOT312 source preflight")
    v5_preflight, v5_preflight_ref = _json(args.v5_preflight, "V5 source preflight")
    if root_preflight.get("status") != "SOURCE_ONLY_READY_METADATA_PASS_NO_LAUNCH":
        _fail("ROOT312 source preflight is not a source-only pass")
    if v5_preflight.get("status") not in {"SOURCE_ONLY_PREFLIGHT_COMPLETE_V2", "SOURCE_ONLY_PREFLIGHT_COMPLETE"} or v5_preflight.get("aggregate_selection", {}).get("admission_status") != "PASS_V5_SOURCE_ONLY_NONOVERLAPPING_SCOPE":
        _fail("V5 source preflight is not a non-overlapping source-only pass")
    root_manifest_path, root_manifest_ref = _candidate_ref(root_preflight, "manifest", "ROOT312 preflight")
    root_request_path, root_request_ref = _candidate_ref(root_preflight, "request", "ROOT312 preflight")
    root_selected = root_preflight.get("selected_case_ids")
    if not isinstance(root_selected, list):
        _fail("ROOT312 preflight selected_case_ids is malformed")
    batches: list[dict[str, Any]] = []
    root_batch, _ = _batch_from_manifest(source_id="ROOT312", family="F4", manifest_path=root_manifest_path, request_path=root_request_path, scope=scope, source_preflight_ref=root_preflight_ref, selected_hint=root_selected)
    batches.append(root_batch)
    candidates = v5_preflight.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        _fail("V5 source preflight has no candidates")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            _fail("V5 source preflight candidate is malformed")
        source_id = candidate.get("root_id")
        family = candidate.get("family_id")
        if not isinstance(source_id, str) or not source_id or not isinstance(family, str):
            _fail("V5 candidate lacks source ID/family")
        if candidate.get("status") != "PASS_V5_SOURCE_CLI_PREFLIGHT":
            _fail(f"{source_id} is not a V5 source-only pass")
        manifest_path, _ = _candidate_ref(candidate, "manifest", source_id)
        request_path, _ = _candidate_ref(candidate, "request", source_id)
        case_ids = candidate.get("physical_case_ids")
        if not isinstance(case_ids, list):
            _fail(f"{source_id} physical_case_ids is malformed")
        batch, _ = _batch_from_manifest(source_id=source_id, family=family, manifest_path=manifest_path, request_path=request_path, scope=scope, source_preflight_ref=v5_preflight_ref, selected_hint=case_ids)
        batches.append(batch)
    all_ids = [case_id for batch in batches for case_id in batch["physical_case_ids"]]
    if len(all_ids) != len(set(all_ids)):
        duplicates = sorted({case_id for case_id in all_ids if all_ids.count(case_id) > 1})
        _fail(f"source batches overlap cases: {duplicates[:3]}")
    if not set(all_ids).issubset(scope["selected"]):
        _fail("source batches include an alias, existing join, or out-of-scope case")
    static_refs: dict[str, dict[str, Any]] = {}
    def add(ref: dict[str, Any], role: str) -> None:
        path = ref.get("path")
        if not isinstance(path, str):
            _fail(f"{role} lacks path")
        if Path(path).suffix.lower() in PAYLOAD_SUFFIXES:
            _fail(f"{role} payload entered static closure: {path}")
        prior = static_refs.get(path)
        if prior is not None and prior.get("sha256") != ref.get("sha256"):
            _fail(f"static source SHA conflict: {path}")
        static_refs[path] = {**ref, "role": role, "content_opened_by_preparer": True}
    add(scope_ref, "V10 actual overlay scope")
    add(_ref(str(SCRIPT), "native overlay adapter source"), "native overlay adapter source")
    for dependency, role in (
        (v5.SCRIPT, "V5 verifier source"),
        (v5.v4.SCRIPT, "V4 verifier source"),
        (v5.v3.SCRIPT, "V3 verifier source"),
        (v5.v3.v2.SCRIPT, "V2 verifier source"),
    ):
        add(_ref(str(dependency), role), role)
    # The V5 loader has already checked these concrete bindings; re-capture the
    # JSON files as static edges so a parent can independently recheck them.
    add(_ref(str(args.lifecycle_plan), "lifecycle plan"), "CURRENT336 lifecycle plan")
    add(_ref(str(args.current), "CURRENT336 catalog"), "CURRENT336 catalog")
    add(root_preflight_ref, "ROOT312 source preflight")
    add(v5_preflight_ref, "V5 source preflight")
    for batch in batches:
        add(batch["manifest"], f"{batch['source_id']} manifest")
        add(batch["request"], f"{batch['source_id']} request")
        for proof in batch["proof_bundles"]:
            add(_concrete_ref(proof, f"{batch['source_id']} producer proof"), f"{batch['source_id']} producer proof")
        for row in batch["contracts"]:
            add(row["contract"], f"{batch['source_id']} contract {row['physical_case_id']}")
    adapter = {
        "schema": ADAPTER_SCHEMA,
        "status": "READY_WAITING_FOR_GUARDED_WORKER_REPORTS",
        "base_scope": scope_ref,
        "lifecycle_plan": _ref(str(args.lifecycle_plan), "lifecycle plan"),
        "current_catalog": _ref(str(args.current), "CURRENT336 catalog"),
        "source_batches": batches,
        "physical_case_count": int(scope["case_scope"]["original_case_count"]),
        "selected_case_count": len(all_ids),
        "selected_case_ids": sorted(all_ids),
        "existing_join_case_count_before_adapter": len(scope["existing"]),
        "alias_case_ids_excluded": sorted(scope["aliases"]),
        "static_source_edges": sorted(static_refs.values(), key=lambda item: (item["role"], item["path"])),
        "deferred_result_policy": {"report_sha256": "PARENT_GUARD_COMPUTED", "content_opened_by_preparer": False, "read_after_parent_reservation": True, "one_report_per_source_batch": True},
        "read_policy": {"scope_plan_current_preflight_manifest_proof_contract_json_opened": True, "typed_jsonl_content_opened": False, "h5_bi4_obi4_partout_runparts_content_opened": False, "solver_started": False, "actual_worker_launched": False},
        "claim_boundary": {"native_id_join": "DEFERRED_UNTIL_V5_VERIFIED_REPORT", "native_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "admission_policy": {"new_overlay_schema": OVERLAY_SCHEMA, "cause_credit_granted_by_adapter": False, "existing_v10_actual_join_proofs_untouched": True, "failed_cases_receive_no_join_credit": True, "alias_never_substituted": True},
    }
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "SOURCE_ONLY_READY_NO_LAUNCH",
        "launch_allowed": False,
        "execution_allowed": False,
        "cpu_task_kind": "metadata_only_preflight",
        "family_id": "INFRA",
        "adapter_schema": ADAPTER_SCHEMA,
        "adapter": {"path": "{output_dir}/native-typed-native-join-actual-overlay-adapter-v1.json", "sha256": "GENERATED_AFTER_ATOMIC_WRITE"},
        "command": ["{literal_python}", str(SCRIPT), "prepare", "--source-only"],
        "input_files": sorted(static_refs.values(), key=lambda item: (item["role"], item["path"])),
        "deferred_result_placeholders": [{"source_id": batch["source_id"], "path": "{attempt_root}/generic-native-extract.json", "sha256": "PARENT_GUARD_COMPUTED", "content_opened_by_preparer": False} for batch in batches],
        "resource_policy": {"parent_reservation_required": True, "cpu": 1, "memory_mib": 4096, "max_wall_s": 3600, "payload_reads": "DEFERRED", "solver": False},
        "claim_boundary": adapter["claim_boundary"],
    }
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_path = output_dir / "native-typed-native-join-actual-overlay-adapter-v1.json"
    request_path = output_dir / "native-typed-native-join-actual-overlay-request-v1.json"
    adapter_ref = _atomic(adapter_path, adapter)
    request["adapter"] = {"path": str(adapter_path), "sha256": adapter_ref["sha256"]}
    request["command"] = ["{literal_python}", str(SCRIPT), "prepare", "--source-only"]
    request_ref = _atomic(request_path, request)
    return {"schema": "ds02.stage2.native-overlay-adapter-preflight.v1", "status": "SOURCE_ONLY_READY_NO_LAUNCH", "adapter": adapter_ref, "request": request_ref, "selected_case_count": len(all_ids), "selected_case_ids": sorted(all_ids), "source_batch_count": len(batches), "source_batch_ids": [batch["source_id"] for batch in batches], "static_source_count": len(static_refs), "claim_boundary": adapter["claim_boundary"], "read_policy": adapter["read_policy"]}


def _load_adapter(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    value, ref = _json(path, "native overlay adapter")
    if value.get("schema") != ADAPTER_SCHEMA or value.get("status") not in {"READY_WAITING_FOR_GUARDED_WORKER_REPORTS", "ADMITTED_METADATA_ONLY_JOIN_RESULTS"}:
        _fail("native overlay adapter schema/status differs")
    return value, ref


def _admit(args: argparse.Namespace) -> dict[str, Any]:
    adapter, adapter_ref = _load_adapter(args.adapter)
    result_map, result_map_ref = _json(args.result_map, "guarded worker result map")
    rows = result_map.get("results")
    if not isinstance(rows, list) or not rows:
        _fail("result map lacks results")
    batches = {row.get("source_id"): row for row in adapter.get("source_batches", []) if isinstance(row, dict)}
    if len(batches) != len(adapter.get("source_batches", [])):
        _fail("adapter source batch IDs are not unique")
    if {row.get("source_id") for row in rows} - set(batches):
        _fail("result map includes an unknown source batch")
    seen_results: set[str] = set()
    source_outputs: list[dict[str, Any]] = []
    joined: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    scope_ref = adapter["base_scope"]
    plan_ref = adapter["lifecycle_plan"]
    current_ref = adapter["current_catalog"]
    for result in rows:
        source_id = result.get("source_id")
        if source_id in seen_results:
            _fail(f"result map repeats source batch: {source_id}")
        seen_results.add(source_id)
        batch = batches[source_id]
        report_value = result.get("report")
        report_ref = _concrete_ref(report_value, f"{source_id} guarded report")
        verification = v5.verify(Path(scope_ref["path"]), Path(batch["manifest"]["path"]), Path(batch["request"]["path"]), Path(report_ref["path"]), Path(plan_ref["path"]), Path(current_ref["path"]))
        source_outputs.append({"source_id": source_id, "report": report_ref, "verification": verification})
        for case in verification.get("case_verifications", []):
            if not isinstance(case, dict):
                _fail(f"{source_id} verifier emitted malformed case")
            case_id = case.get("physical_case_id")
            if not isinstance(case_id, str):
                _fail(f"{source_id} verifier emitted a case without identity")
            joined.append({"physical_case_id": case_id, "source_id": source_id, "status": "VERIFIED_TYPED_NATIVE_SAVED_FRAME_JOIN_DIAGNOSTIC_ONLY", "joined_identity_count": case.get("joined_identity_count"), "verification_report": "EMBEDDED_IN_THIS_OVERLAY", "native_cause_credit": "NONE", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
        for case in verification.get("failures", []):
            failed.append({"physical_case_id": case.get("physical_case_id"), "source_id": source_id, "status": "FAILED_NO_JOIN_CREDIT", "error_type": case.get("error_type"), "error_message": case.get("error_message")})
    if len(seen_results) != len(rows):
        _fail("result map source batch set is malformed")
    ids = [row["physical_case_id"] for row in joined]
    if len(ids) != len(set(ids)):
        _fail("admitted V5 reports overlap a physical case")
    selected = set(adapter.get("selected_case_ids", []))
    if not set(ids).issubset(selected):
        _fail("admitted V5 report contains case outside prepared selection")
    overlay = {
        "schema": OVERLAY_SCHEMA,
        "status": "ADMITTED_METADATA_ONLY_JOIN_RESULTS",
        "base_scope": adapter_ref,
        "source_adapter": adapter_ref,
        "result_map": result_map_ref,
        "source_results": [{"source_id": item["source_id"], "report": item["report"]} for item in source_outputs],
        "pending_source_ids": sorted(set(batches) - seen_results),
        "new_typed_native_join_cases": joined,
        "failed_cases": failed,
        "counts": {"prepared_case_count": len(selected), "verified_join_case_count": len(joined), "failed_case_count": len(failed), "native_cause_credit_case_count": 0},
        "existing_v10_actual_join_proofs_untouched": True,
        "claim_boundary": {"typed_native_saved_frame_join": "VERIFIED_PER_CASE_WHERE_V5_COMPLETED", "native_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"adapter_json_opened": True, "worker_report_json_opened": True, "typed_summary_or_csv_read_by_v5_after_guard": True, "production_payload_read_by_prepare": False, "solver_started_by_adapter": False},
    }
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "native-typed-native-join-actual-overlay-v1.json"
    output_ref = _atomic(output_path, overlay)
    return {"schema": "ds02.stage2.native-overlay-admission-v1", "status": overlay["status"], "output": output_ref, "verified_join_case_count": len(joined), "failed_case_count": len(failed), "native_cause_credit_case_count": 0}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--scope", type=Path, required=True)
    prepare.add_argument("--lifecycle-plan", type=Path, required=True)
    prepare.add_argument("--current", type=Path, required=True)
    prepare.add_argument("--root312-preflight", type=Path, required=True)
    prepare.add_argument("--v5-preflight", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    admit = sub.add_parser("admit")
    admit.add_argument("--adapter", type=Path, required=True)
    admit.add_argument("--result-map", type=Path, required=True)
    admit.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = _prepare(args) if args.action == "prepare" else _admit(args)
    except (AdapterError, v5.GenericJoinV5Error, v5.v3.GenericJoinV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"NATIVE_OVERLAY_ADAPTER_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
