#!/usr/bin/env python3
"""Prepare the remaining 335-case scientific-field H5 requests.

The seven completed ROOT346--352 pilots established the real V10 -> V3
worker -> V5 verifier/runtime closure.  This builder reuses that closure for
the other 328 rows in the current 335-case source manifest.  It creates one
serial, source-bound request per row and keeps the one producer row without a
case manifest as an explicit non-executable UNKNOWN record.

Only bounded JSON and ``stat(2)`` are read here.  HDF5 content is deferred to
the parent after reservation; HDF5 read I/O is reported separately from new
attempt storage.  The builder never reserves resources, launches a worker,
or mutates a ledger.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V3_PATH = SCRIPT.with_name("ds_data02_stage2_scientific_field_h5_pilot_v10_prepare_v3.py")
INDEX_SCHEMA = "ds02.stage2.scientific-field-h5-remaining-v4-request-index.v1"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-remaining-v4-source-report.v1"
REQUEST_STATUS = "SOURCE_PREPARED_SINGLE_CASE_V10_NOT_RUN"
INDEX_STATUS = "SOURCE_PREPARED_REMAINING_327_PLUS_ONE_UNKNOWN_V10_NOT_RUN"
MANIFEST_STATUS = "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT"
SOURCE_MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-batch-source.v1"
PILOT_INDEX_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-request-index.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MAX_METADATA_BYTES = 10 * 1024 * 1024
PILOT_FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V3 = _load(V3_PATH, "ds02_scientific_field_h5_prepare_v3_for_remaining_v4")


class RemainingPrepareError(ValueError):
    """The current 335-case source package cannot be prepared."""


def _fail(message: str) -> None:
    raise RemainingPrepareError(message)


def _json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        _fail(f"{label} exceeds bounded metadata size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not bounded JSON: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _sha(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        _fail(f"{label} exceeds bounded metadata hash size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, label: str) -> dict[str, Any]:
    try:
        return V3.file_stat(path, label)
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc


def _write(path: Path, value: Mapping[str, Any], *, max_bytes: int = MAX_METADATA_BYTES) -> str:
    try:
        V3.atomic_json(path, dict(value), max_bytes=max_bytes)
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc
    return _sha(path, f"generated metadata {path}")


def _digest(value: Any, label: str) -> str:
    try:
        return V3.digest(value, label)
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc


def _ref(value: Any, label: str, args: argparse.Namespace) -> dict[str, Any]:
    try:
        return V3._rebind_source_ref(value, label, args)
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc


def _dedupe(refs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        return V3._dedupe_refs(list(refs))
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc


def _current_row(current: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    try:
        return V3._find_current_row(dict(current), case_id)
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc


def _adapt_case(source_case: Mapping[str, Any], current: Mapping[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Translate the canonical batch row into the proven V3 worker shape."""
    case_id = source_case.get("physical_case_id")
    family = source_case.get("family_id")
    if not isinstance(case_id, str) or not isinstance(family, str) or family not in PILOT_FAMILIES:
        _fail("source manifest contains an invalid case identity")
    row = _current_row(current, case_id)
    if row.get("family_id") != family:
        _fail(f"{case_id}: source/CURRENT family differs")
    producer = source_case.get("producer")
    evidence = source_case.get("typed_lifecycle_evidence")
    if not isinstance(producer, Mapping) or not isinstance(evidence, Mapping):
        _fail(f"{case_id}: producer/evidence closure is missing")
    proof = producer.get("proof")
    producer_manifest = producer.get("manifest")
    producer_request = producer.get("request")
    receipt = evidence.get("case_receipt")
    summary = evidence.get("typed_summary")
    case_manifest = evidence.get("case_manifest")
    for value, label in (
        (proof, "producer proof"), (producer_request, "producer request"),
        (receipt, "case receipt"), (summary, "typed summary"),
    ):
        if not isinstance(value, Mapping):
            _fail(f"{case_id}: {label} is missing")
    # F2H10V2_OFFSET_V1 has a completed producer proof/request but no
    # producer manifest as well as no case manifest.  It is retained as the
    # explicit UNKNOWN row below; executable rows still require both
    # manifest edges.
    if producer_manifest is not None and not isinstance(producer_manifest, Mapping):
        _fail(f"{case_id}: producer manifest is not an object or null")
    if producer_manifest is None and case_manifest is not None:
        _fail(f"{case_id}: executable case lacks producer manifest")
    if case_manifest is not None and not isinstance(case_manifest, Mapping):
        _fail(f"{case_id}: case manifest is not an object or null")

    # V3 expects these names at the case level.  Preserve the original nested
    # producer/evidence fields as provenance while binding the exact refs used
    # by the real V3 worker contract.
    adapted = copy.deepcopy(dict(source_case))
    adapted.update({
        "producer_terminal_proof": dict(proof),
        "producer_receipt": dict(receipt),
        "typed_summary": dict(summary),
        "case_manifest": dict(case_manifest) if case_manifest is not None else None,
        "case_manifest_status": "UNKNOWN_MISSING_MANIFEST" if case_manifest is None else "BOUND",
        "expected_frames": row.get("frames"),
        "expected_particles": row.get("particles"),
        "expected_units": dict((row.get("header") or {}).get("units") or {}),
        "pilot_current_row": {
            "family_id": row.get("family_id"),
            "frames": row.get("frames"),
            "particles": row.get("particles"),
        },
        "producer_metadata": {
            "identity_key": ((row.get("header") or {}).get("identity_key")),
            "producer_id": source_case.get("producer_id"),
            "saved_mask_status": source_case.get("saved_mask_status"),
            "source_join_status": source_case.get("source_join_status"),
            "units_status": "DECLARED_ONLY_UNVERIFIED",
        },
        "source_content_read_by_preparer": False,
        "scientific_credit": 0,
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        "current_index": row.get("current_index"),
    })
    try:
        selected, case_refs = V3._case_from_pilot(adapted, dict(current), case_id, args)
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc

    # Keep the actual producer request/manifest in the static closure too.
    # They are bounded JSON provenance, not scientific payloads; the parent
    # still revalidates all input SHA/stat pairs after reservation.
    extra = [
        _ref(producer_request, f"{case_id} producer request", args),
        _ref(proof, f"{case_id} producer proof", args),
    ]
    if producer_manifest is not None:
        extra.insert(0, _ref(producer_manifest, f"{case_id} producer manifest", args))
    return selected, _dedupe([*case_refs, *extra])


def _cost(case: Mapping[str, Any], refs: Sequence[Mapping[str, Any]], max_memory: int) -> dict[str, Any]:
    try:
        value = V3._cost(dict(case), [dict(ref) for ref in refs], max_memory=max_memory)
    except Exception as exc:
        raise RemainingPrepareError(str(exc)) from exc
    value.update({
        "source_h5_storage_bytes": 0,
        "temporary_copy_bytes": 0,
        "worker_scratch_bytes": 0,
        "read_io_excluded_from_storage": True,
        "one_case_at_a_time": True,
        "reservation_released_between_cases": True,
    })
    return value


def _runtime_refs(all_refs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    required = (
        "runtime_v10_git_bound", "runtime_v9_git_bound", "runtime_v8", "runtime_v6", "runtime_v2",
        "git_snapshot_v1", "git_snapshot_v2", "git_snapshot_v3", "dispatch_v9", "strict_dispatch_v9",
        "official_runtime_config",
    )
    result: dict[str, dict[str, Any]] = {}
    for role in required:
        matches = [dict(item) for item in all_refs if item.get("role") == role]
        if len(matches) != 1:
            _fail(f"runtime closure role is missing or duplicated: {role}")
        result[role] = matches[0]
    return result


def _write_case_request(args: argparse.Namespace, output_dir: Path, selected: Mapping[str, Any], refs: Sequence[dict[str, Any]], cost: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    family = str(selected["family_id"])
    case_id = str(selected["physical_case_id"])
    case_dir = output_dir / f"{family}-{case_id}"
    manifest_path = case_dir / "scientific-field-h5-audit-manifest.json"
    request_path = case_dir / "scientific-field-h5-remaining-request.json"
    manifest = {
        "schema": V3.MANIFEST_SCHEMA,
        "status": MANIFEST_STATUS,
        "pilot_scope": {
            "family_id": family,
            "physical_case_id": case_id,
            "one_case_only": True,
            "remaining_batch_v4": True,
            "historical_alias_excluded": True,
        },
        "current_catalog": args.current_binding,
        "source_contract": {
            "source_manifest": args.source_manifest_ref,
            "pilot_index": args.pilot_index_ref,
            "plan": args.plan_ref,
            "registry": args.registry_ref,
            "verified_pilot_runtime": args.pilot_runtime_report_ref,
        },
        "static_source_refs": list(refs),
        "cases": [dict(selected)],
        "worker_contract": {
            "worker_version": "v3_vectorized_postread_guard",
            "sequential_cases": True,
            "bounded_memory": True,
            "required_static_datasets": ["time", "particle_id", "particle_zone", "initial_type", "initial_mass"],
            "required_frame_datasets": ["position", "velocity", "density", "mass", "pressure", "valid", "type"],
            "post_guard": "final HDF5 stat/hash after all deferred datasets are read",
            "source_h5_storage": "reused_in_place; no source copy in attempt namespace",
            "temporary_copy_bytes": 0,
            "persistent_scratch_bytes": 0,
            "aggregate_output_only": True,
        },
        "read_policy": {
            "prepare_json_and_stat_only": True,
            "trajectory_h5_opened_by_preparer": False,
            "trajectory_h5_hashed_by_preparer": False,
            "trajectory_h5_opened_after_parent_reservation": True,
            "raw_bi4_opened": False,
            "solver_started": False,
        },
        "claim_boundary": {
            "scientific_credit": 0, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "units": "DECLARED_ONLY_UNVERIFIED", "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        },
        "source_read_cost": dict(cost),
        "verified_pilot_runtime": {
            "index": args.pilot_index_ref,
            "report": args.pilot_runtime_report_ref,
            "scientific_credit": 0,
            "h5_rescan_by_preparer": False,
        },
    }
    manifest_sha = _write(manifest_path, manifest)
    manifest_ref = V3.static_ref(manifest_path, "remaining V4 generated manifest")
    all_refs = _dedupe([*refs, manifest_ref])
    input_files = [str(item["path"]) for item in all_refs]
    input_sha = {str(item["path"]): str(item["sha256"]) for item in all_refs}
    literal_python = str(Path(args.python).expanduser())
    runtime = _runtime_refs(all_refs)
    resolved_python = Path(literal_python).resolve()
    py_ref = next(item for item in all_refs if item.get("path") == str(resolved_python))
    request = {
        "schema": V3.REQUEST_SCHEMA,
        "request_id": f"scientific-field-h5-remaining-v4-{family}-{case_id}",
        "attempt_id": f"scientific-field-h5-remaining-v4-{family}-{case_id}",
        "family_id": family, "case_id": case_id, "physical_case_ids": [case_id],
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": int(args.max_wall_seconds), "max_memory_bytes": int(args.max_memory_bytes),
        "estimated_peak_memory_bytes": int(cost["estimated_memory_bytes"]),
        "estimated_storage_bytes": int(cost["estimated_storage_bytes"]),
        "cwd": str(args.lab_root), "worktree_root": str(args.worktree_root),
        "command": [literal_python, "-B", str(Path(args.worker).expanduser().resolve()), "audit", "--manifest", str(manifest_path.resolve()), "--output", "{attempt_root}/scientific-field-h5-audit.json", "--chunk", str(args.chunk)],
        "input_files": input_files, "input_sha256": input_sha,
        "deferred_input_files": [selected["trajectory_h5"]["path"]],
        "deferred_input_records": [selected["trajectory_h5"]],
        "output_files": ["{attempt_root}/scientific-field-h5-audit.json"],
        "manifest_contract": {"path": str(manifest_path.resolve()), "sha256": manifest_sha},
        "interpreter_binding": {"literal_path": literal_python, "resolved_path": str(resolved_python), "sha256": py_ref["sha256"]},
        "runtime_binding": runtime,
        "storage_scope": {
            "schema": "ds02.storage-scope.v2",
            "home_storage_bytes": cost["home_storage_bytes"], "external_storage_bytes": cost["external_storage_bytes"],
            "estimated_storage_bytes": cost["estimated_storage_bytes"], "home_headroom_bytes": V3.HOME_HEADROOM_BYTES,
            "external_headroom_bytes": V3.EXTERNAL_HEADROOM_BYTES,
            "source_h5_storage_bytes": 0, "temporary_copy_bytes": 0, "worker_scratch_bytes": 0,
            "storage_measurement": "new_attempt_files_peak_only; source_h5_read_io_excluded",
            "read_io_excluded_from_storage": True, "legacy_scope_defaulted": False,
        },
        "source_read_cost": {**dict(cost), "family": family, "case_count": 1},
        "read_policy": manifest["read_policy"], "claim_boundary": manifest["claim_boundary"],
        "verified_pilot_runtime": manifest["verified_pilot_runtime"],
        "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": True,
        "status": REQUEST_STATUS, "remaining_batch_status": "SOURCE_PREPARED_REMAINING_SINGLE_CASE_V10_NOT_RUN",
        "scientific_credit": 0,
        "request_note": "Remaining 335-batch single-case source closure. HDF5 content/stat/hash is deferred until the parent reservation; this request carries no scientific credit and reuses the verified seven-pilot runtime contract without rescanning pilot HDF5 content.",
    }
    request_sha = _write(request_path, request)
    return request_path, {"path": str(request_path), "sha256": request_sha, "manifest": {"path": str(manifest_path), "sha256": manifest_sha}, "cost": dict(cost)}


def _unknown_entry(args: argparse.Namespace, source_case: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(source_case["physical_case_id"])
    family = str(source_case["family_id"])
    adapted, refs = _adapt_case(source_case, current, args)
    cost = _cost(adapted, refs, int(args.max_memory_bytes))
    return {
        "family_id": family, "physical_case_id": case_id,
        "case_manifest_status": "UNKNOWN_MISSING_MANIFEST",
        "request": None, "manifest": None,
        "reason": "producer did not expose a case manifest; no executable V3 request is admitted",
        "deferred_h5": {"path": adapted["trajectory_h5"]["path"], "bytes": adapted["trajectory_h5"]["bytes"], "known_sha256": adapted["trajectory_h5"]["known_sha256"], "content_read_by_preparer": False},
        "source_ref_count": len(refs), "source_read_cost": cost,
        "scientific_credit": 0, "production_eligible": False,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.source_rebind_from) != bool(args.source_rebind_to):
        _fail("source rebinding requires both --source-rebind-from and --source-rebind-to")
    pilot_path, pilot = V3.read_json(args.pilot_index, "verified seven-pilot index")
    if pilot.get("schema") != PILOT_INDEX_SCHEMA or pilot.get("status") != "SOURCE_PREPARED_SEVEN_SINGLE_CASE_V10_NOT_RUN":
        _fail("pilot index is not the seven-pilot V10 output index")
    pilot_rows = pilot.get("requests")
    if not isinstance(pilot_rows, list) or len(pilot_rows) != 7:
        _fail("verified seven-pilot index does not contain seven request rows")
    pilot_ids = {row.get("physical_case_id") for row in pilot_rows if isinstance(row, Mapping)}
    if len(pilot_ids) != 7 or any(not isinstance(value, str) for value in pilot_ids):
        _fail("verified seven-pilot index has invalid or duplicate IDs")
    pilot_report_path = pilot_path.parent / "scientific-field-h5-pilot-v10-source-report.json"
    if not pilot_report_path.is_file():
        _fail(f"verified seven-pilot source report is missing: {pilot_report_path}")
    current_path, current = V3.read_json(args.current, "CURRENT336")
    current_binding = V3._current_binding(current_path, current)
    source_path, source = V3.read_json(args.source_manifest, "335 source manifest")
    if source.get("schema") != SOURCE_MANIFEST_SCHEMA or not isinstance(source.get("cases"), list) or len(source["cases"]) != 335:
        _fail("source manifest is not the canonical 335-case package")
    plan_path, plan = V3.read_json(args.plan, "typed lifecycle plan")
    registry_path, registry = V3.read_json(args.registry, "typed lifecycle registry")
    if not isinstance(plan.get("schema"), str) or not isinstance(registry.get("schema"), str):
        _fail("plan/registry schema is missing")
    source_by_id: dict[str, dict[str, Any]] = {}
    for row in source["cases"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("physical_case_id"), str):
            _fail("source manifest contains an invalid case row")
        cid = str(row["physical_case_id"])
        if cid in source_by_id:
            _fail(f"source manifest duplicates {cid}")
        source_by_id[cid] = dict(row)
    if not pilot_ids <= set(source_by_id):
        _fail("one or more verified pilot IDs are absent from current 335 source manifest")

    args.current_binding = current_binding
    args.pilot_index_ref = V3.static_ref(pilot_path, "verified seven-pilot index")
    args.pilot_runtime_report_ref = V3.static_ref(pilot_report_path, "verified seven-pilot source report")
    args.source_manifest_ref = V3.static_ref(source_path, "335 source manifest")
    args.plan_ref = V3.static_ref(plan_path, "typed lifecycle plan")
    args.registry_ref = V3.static_ref(registry_path, "typed lifecycle registry")
    common = _dedupe([current_binding, args.pilot_index_ref, args.pilot_runtime_report_ref, args.source_manifest_ref, args.plan_ref, args.registry_ref, *V3._core_refs(args)])
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists():
        if any(output_dir.iterdir()):
            _fail(f"refusing non-empty output namespace: {output_dir}")
    else:
        output_dir.mkdir(parents=True)

    rows: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    by_family: dict[str, int] = {family: 0 for family in PILOT_FAMILIES}
    for source_case in source["cases"]:
        cid = str(source_case["physical_case_id"])
        if cid in pilot_ids:
            continue
        family = str(source_case["family_id"])
        by_family[family] = by_family.get(family, 0) + 1
        # No case manifest is available for this one row.  Keep its stat and
        # known HDF5 provenance, but do not create a command that could be
        # mistaken for an executable audit.
        evidence = source_case.get("typed_lifecycle_evidence") or {}
        if evidence.get("case_manifest") is None:
            entry = _unknown_entry(args, source_case, current)
            unknown.append(entry)
            rows.append(entry)
            continue
        adapted, case_refs = _adapt_case(source_case, current, args)
        refs = _dedupe([*common, *case_refs])
        cost = _cost(adapted, refs, int(args.max_memory_bytes))
        request_path, request_info = _write_case_request(args, output_dir, adapted, refs, cost)
        rows.append({
            "family_id": family, "physical_case_id": cid,
            "case_manifest_status": adapted["case_manifest_status"],
            "request": {"path": request_info["path"], "sha256": request_info["sha256"]},
            "manifest": request_info["manifest"],
            "deferred_h5": {"path": adapted["trajectory_h5"]["path"], "bytes": adapted["trajectory_h5"]["bytes"], "known_sha256": adapted["trajectory_h5"]["known_sha256"], "content_read_by_preparer": False},
            "source_read_cost": cost, "source_ref_count": len(refs),
            "scientific_credit": 0, "production_eligible": False,
        })
    if len(rows) != 328 or len(unknown) != 1 or len(rows) - len(unknown) != 327:
        _fail(f"remaining case split is not 327 executable + 1 UNKNOWN: {len(rows)} total, {len(unknown)} unknown")

    executable = [row for row in rows if row.get("request") is not None]
    aggregate = {
        "cases_total": len(rows), "executable_cases": len(executable), "unknown_cases": len(unknown),
        "estimated_h5_read_bytes_executable": sum(int(row["source_read_cost"]["estimated_h5_read_bytes"]) for row in executable),
        "deferred_h5_bytes_all_rows": sum(int(row["deferred_h5"]["bytes"]) for row in rows),
        "sum_per_case_new_storage_bytes": sum(int(row["source_read_cost"]["estimated_storage_bytes"]) for row in executable),
        "peak_serial_new_storage_bytes": max(int(row["source_read_cost"]["estimated_storage_bytes"]) for row in executable),
        "estimated_storage_bytes": max(int(row["source_read_cost"]["estimated_storage_bytes"]) for row in executable),
        "source_h5_storage_bytes": 0, "temporary_copy_bytes": 0,
        "one_case_at_a_time": True, "reservation_released_between_cases": True,
        "source_h5_read_io_excluded_from_storage": True,
        "missing_manifest_cases_are_not_executable": True,
    }
    index = {
        "schema": INDEX_SCHEMA, "status": INDEX_STATUS,
        "case_count": len(rows), "executable_case_count": len(executable), "unknown_case_count": len(unknown),
        "pilot_cases_excluded": sorted(pilot_ids), "requests": rows,
        "family_case_counts": by_family,
        "current_binding": current_binding,
        "source_contract": {
            "source_manifest": args.source_manifest_ref, "pilot_index": args.pilot_index_ref,
            "pilot_runtime_report": args.pilot_runtime_report_ref,
            "plan": args.plan_ref, "registry": args.registry_ref,
        },
        "runtime_contract": {
            "runtime_version": "v10_git_bound", "verified_by_seven_actual_pilots": True,
            "pilot_index_sha256": args.pilot_index_ref["sha256"], "pilot_source_report_sha256": args.pilot_runtime_report_ref["sha256"],
            "literal_python": str(Path(args.python).expanduser()), "source_fallback": False,
        },
        "read_policy": {
            "metadata_only": True, "trajectory_h5_opened": False, "trajectory_h5_hashed": False,
            "bi4_opened": False, "solver_started": False, "launch_performed": False,
        },
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0, "production_eligible": False},
        "source_read_cost": aggregate,
        "unknown_cases": [{"family_id": row["family_id"], "physical_case_id": row["physical_case_id"], "reason": row["reason"]} for row in unknown],
        "execution": {
            "parent_reservation_required": True, "serial_only": True,
            "post_read_h5_sha_and_stat_required": True,
            "reuse_verified_pilot_runtime_without_h5_rescan": True,
            "missing_manifest_policy": "UNKNOWN_NO_EXECUTION",
        },
    }
    index_path = output_dir / "scientific-field-h5-remaining-v4-request-index.json"
    index_sha = _write(index_path, index)
    report = {
        "schema": REPORT_SCHEMA, "status": INDEX_STATUS,
        "index": {"path": str(index_path), "sha256": index_sha},
        "case_count": len(rows), "executable_case_count": len(executable), "unknown_case_count": len(unknown),
        "family_case_counts": by_family, "source_read_cost": aggregate,
        "pilot_runtime_reused": True, "scientific_credit": 0, "production_eligible": False,
        "payload_read_by_preparer": False, "ledger_mutated": False, "launch_performed": False,
    }
    report_path = output_dir / "scientific-field-h5-remaining-v4-source-report.json"
    report_sha = _write(report_path, report)
    return {"status": INDEX_STATUS, "index": str(index_path), "index_sha256": index_sha, "report": str(report_path), "report_sha256": report_sha, "case_count": len(rows), "executable_cases": len(executable), "unknown_cases": len(unknown), "estimated_h5_read_bytes": aggregate["estimated_h5_read_bytes_executable"], "peak_serial_storage_bytes": aggregate["peak_serial_new_storage_bytes"], "payload_read": False, "ledger_mutated": False}


def validate(index_path: Path) -> dict[str, Any]:
    path, index = V3.read_json(index_path, "remaining V4 index")
    if index.get("schema") != INDEX_SCHEMA or index.get("status") != INDEX_STATUS:
        _fail("remaining V4 index schema/status differs")
    rows = index.get("requests")
    if not isinstance(rows, list) or len(rows) != 328:
        _fail("remaining V4 index must contain exactly 328 rows")
    current = index.get("current_binding")
    if not isinstance(current, Mapping) or current.get("sha256") != CURRENT_SHA256:
        _fail("remaining V4 CURRENT binding differs")
    current_path = Path(str(current.get("path"))).expanduser().resolve()
    if _sha(current_path, "CURRENT336") != CURRENT_SHA256:
        _fail("CURRENT336 content differs")
    # V7 is the independent real V3 request verifier.  It is called per
    # executable request, so the batch index status can remain additive while
    # each worker request keeps the established V10 request status.
    v7 = _load(SCRIPT.with_name("ds_data02_stage2_scientific_field_h5_pilot_v10_verify_v7.py"), "ds02_scientific_field_h5_verify_v7_for_remaining")
    checked = []
    unknown = []
    seen: set[str] = set()
    # V7 normally installs these adapters while verifying its seven-row
    # index.  Install the same immutable adapters around this additive
    # 328-row loop so its real V6 checks see the V3 schema/runtime roles.
    base = v7.BASE
    old_values = {
        "MANIFEST_SCHEMA": base.MANIFEST_SCHEMA,
        "REQUIRED_RUNTIME_ROLES": base.REQUIRED_RUNTIME_ROLES,
        "_verify_manifest": base._verify_manifest,
        "_verify_request": base._verify_request,
    }
    base.MANIFEST_SCHEMA = v7.MANIFEST_SCHEMA
    base.REQUIRED_RUNTIME_ROLES = set(v7.REQUIRED_RUNTIME_ROLES)
    base._verify_manifest = v7._verify_v3_manifest
    base._verify_request = v7._verify_v3_request
    try:
        for row in rows:
            if not isinstance(row, Mapping):
                _fail("remaining V4 row is not an object")
            cid = row.get("physical_case_id")
            if not isinstance(cid, str) or cid in seen:
                _fail(f"remaining V4 duplicate/invalid case ID: {cid}")
            seen.add(cid)
            request_ref = row.get("request")
            if request_ref is None:
                if row.get("case_manifest_status") != "UNKNOWN_MISSING_MANIFEST":
                    _fail(f"{cid}: missing request is not explicitly UNKNOWN_MISSING_MANIFEST")
                unknown.append(cid)
                continue
            if not isinstance(request_ref, Mapping):
                _fail(f"{cid}: request reference is malformed")
            request_path = Path(str(request_ref.get("path"))).expanduser().resolve()
            if _sha(request_path, f"{cid} request") != _digest(request_ref.get("sha256"), f"{cid} request SHA"):
                _fail(f"{cid}: request file SHA differs")
            try:
                result = v7._verify_v3_request(request_path, {**dict(current), "path": str(current_path)})
            except Exception as exc:
                _fail(f"{cid}: independent V7 verification failed: {exc}")
            checked.append(result)
    finally:
        for key, value in old_values.items():
            setattr(base, key, value)
    if len(checked) != 327 or len(unknown) != 1:
        _fail(f"remaining V4 executable/unknown split differs: {len(checked)} / {len(unknown)}")
    aggregate = index.get("source_read_cost")
    if not isinstance(aggregate, Mapping):
        _fail("remaining V4 aggregate source cost is missing")
    expected_read = sum(int(item["deferred_h5"]["bytes"]) * 3 for item in rows if item.get("request") is not None)
    if int(aggregate.get("estimated_h5_read_bytes_executable", -1)) != expected_read:
        _fail("remaining V4 HDF5 read-I/O aggregate differs")
    expected_peak = max(int(item["estimated_storage_bytes"]) for item in (result for result in checked))
    if int(aggregate.get("peak_serial_new_storage_bytes", -1)) != expected_peak:
        _fail("remaining V4 serial storage peak differs")
    return {"status": "VERIFIED_REMAINING_327_PLUS_ONE_UNKNOWN_V10_METADATA", "index": str(path), "case_count": 328, "executable_cases": 327, "unknown_cases": unknown, "verified_requests": len(checked), "estimated_h5_read_bytes": expected_read, "peak_serial_storage_bytes": expected_peak, "payload_read": False, "ledger_mutated": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("pilot-index", "source-manifest", "current", "plan", "registry", "worker", "verifier", "runtime-v10", "runtime-v9", "runtime-v8", "runtime-v6", "runtime-v2", "git-helper-v1", "git-helper-v2", "git-helper-v3", "dispatch", "strict-dispatch", "python", "config", "output-dir"):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--lab-root", type=Path, required=True)
    build.add_argument("--worktree-root", type=Path, required=True)
    build.add_argument("--source-rebind-from", type=Path)
    build.add_argument("--source-rebind-to", type=Path)
    build.add_argument("--chunk", type=int, default=65536)
    build.add_argument("--max-wall-seconds", type=int, default=900)
    build.add_argument("--max-memory-bytes", type=int, default=4 * 1024**3)
    check = sub.add_parser("validate")
    check.add_argument("--index", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate(args.index)
        else:
            if args.chunk <= 0 or args.max_wall_seconds <= 0 or args.max_memory_bytes <= 0:
                _fail("chunk, max-wall-seconds, and max-memory-bytes must be positive")
            result = prepare(args)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (RemainingPrepareError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"scientific-field-h5-remaining-v4: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
