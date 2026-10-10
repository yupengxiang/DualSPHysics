#!/usr/bin/env python3
"""Build the first guarded execution phase for canonical CURRENT row 65.

The canonical raw anchor planner records source paths and statistics, but its
request is intentionally too sparse for the pinned native worker.  This
adapter fills the worker's *metadata* contract from the exact row-65 saved-mask
receipt while keeping all BI4/HDF5/CSV content hashes parent-deferred.  The
result is a concrete ``raw_to_typed`` phase request: a parent may reserve the
resources, copy/rebind the source closure, compute the pending hashes, and then
promote the request to ``READY_FOR_PARENT_GUARD``.  This builder itself never
opens scientific payloads.

The later typed-to-label phase is deliberately separate.  It can only be
constructed from the terminal raw-to-typed report and cannot inherit a
historical row-78 V15 request.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
PLANNER_PATH = SCRIPT.with_name("ds_data02_stage2_f2_canonical_raw_anchor_v3.py")
_SPEC = importlib.util.spec_from_file_location("canonical_raw_anchor_v3_for_phase_v1", PLANNER_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load canonical source planner: {PLANNER_PATH}")
PLANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PLANNER)


SCHEMA = "ds02.stage2.f2-canonical65-raw-to-typed-phase.v1"
REQUEST_SCHEMA = PLANNER.REQUEST_SCHEMA
PROOF_SCHEMA = PLANNER.PROOF_SCHEMA
CURRENT_SHA = PLANNER.CURRENT_SHA
CANONICAL_ID = PLANNER.CANONICAL_ID
HISTORICAL_ALIAS_ID = PLANNER.HISTORICAL_ALIAS_ID
PENDING = PLANNER.PENDING
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
DECODER_DEFAULT = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump"
PYTHON_DEFAULT = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
METADATA_LIMIT = 10 * 1024 * 1024
HEX = frozenset("0123456789abcdef")


class PhaseError(ValueError):
    """The canonical phase cannot be made source-bound."""


def _fail(message: str) -> None:
    raise PhaseError(message)


def _signature(path: Path, role: str) -> dict[str, int]:
    try:
        value = path.lstat()
    except OSError as error:
        _fail(f"{role} cannot be stat'ed: {path}: {error}")
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
        _fail(f"{role} must be a regular non-symlink file: {path}")
    return {
        "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
        "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns), "mode_bits": int(stat.S_IMODE(value.st_mode)),
    }


def _bounded_bytes(path: Path, role: str, limit: int = METADATA_LIMIT) -> bytes:
    before = _signature(path, role)
    if before["bytes"] > limit:
        _fail(f"{role} exceeds bounded metadata read ({before['bytes']} > {limit}): {path}")
    try:
        with path.open("rb") as stream:
            payload = stream.read(limit + 1)
    except OSError as error:
        _fail(f"{role} cannot be read: {error}")
    after = _signature(path, role)
    if before != after or len(payload) > limit:
        _fail(f"{role} changed during bounded read: {path}")
    return payload


def _json(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(_bounded_bytes(path, role).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        _fail(f"{role} is not bounded JSON: {path}: {error}")
    if not isinstance(value, dict):
        _fail(f"{role} must be a JSON object")
    return value


def _sha(path: Path, role: str, *, limit: int = METADATA_LIMIT) -> str:
    return hashlib.sha256(_bounded_bytes(path, role, limit)).hexdigest()


def _canonical(value: Any) -> str:
    body = {key: item for key, item in value.items()
            if key not in {"sha256", "file_sha256"}} if isinstance(value, Mapping) else value
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any], role: str) -> tuple[str, dict[str, int]]:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite {role}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                          allow_nan=False) + "\n").encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError as error:  # pragma: no cover
        raise PhaseError(f"refusing to overwrite {role}: {path}") from error
    return hashlib.sha256(encoded).hexdigest(), _signature(path, role)


def _pending_source_hashes(request: dict[str, Any]) -> int:
    pending = 0
    sources = request.get("source_files")
    if not isinstance(sources, list):
        _fail("worker source_files must be a list")
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            _fail("worker source_files contains a malformed role")
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            _fail(f"source role has no absolute path: {item.get('role')}")
        # The planner has already bounded metadata and stat'ed each source.
        # Unknown scientific/source bytes remain an explicit parent obligation.
        if item.get("sha256") in (None, "", PENDING):
            item["sha256"] = PENDING
            item["content_sha_status"] = "PARENT_GUARD_REQUIRED"
            item["content_read_by_planner"] = False
            pending += 1
        elif (not isinstance(item.get("sha256"), str) or
              len(item["sha256"]) != 64 or any(c not in HEX for c in item["sha256"])):
            _fail(f"source role has malformed SHA: {item['role']}")
        item["content_verification_phase"] = "AFTER_PARENT_RESERVATION"
        item["source_fallback"] = "REJECT"
    return pending


def _proof_case(proof: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    if proof.get("schema") != PROOF_SCHEMA:
        _fail("saved-mask proof schema differs")
    rows = [row for row in proof.get("case_verifications", [])
            if isinstance(row, Mapping) and row.get("physical_case_id") == case_id]
    if len(rows) != 1:
        _fail("saved-mask proof must contain exactly one row-65 case")
    row = rows[0]
    if row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        _fail("row-65 proof is not diagnostic-only saved-mask evidence")
    return row


def _raw_stat_bytes(raw_root: Path) -> int:
    total = 0
    try:
        entries = list(raw_root.iterdir())
    except OSError as error:
        _fail(f"cannot enumerate raw root for stat-only budget: {error}")
    for entry in entries:
        try:
            value = entry.lstat()
        except OSError as error:
            _fail(f"cannot stat raw entry {entry}: {error}")
        if stat.S_ISLNK(value.st_mode):
            _fail(f"raw tree contains a symlink: {entry}")
        if stat.S_ISREG(value.st_mode):
            total += int(value.st_size)
    return total


def _source_stat(item: Mapping[str, Any]) -> dict[str, Any]:
    path = item.get("path")
    if not isinstance(path, str):
        _fail(f"source role lacks path: {item.get('role')}")
    return {key: item[key] for key in
            ("role", "path", "bytes", "mtime_ns", "ctime_ns", "mode_bits", "sha256")
            if key in item}


def _replace_old_paths(value: Any) -> None:
    """Reject the known row-78 / ROOT242 path graph recursively."""
    if isinstance(value, str):
        forbidden = (HISTORICAL_ALIAS_ID, "ROOT242", "root242", "RX056", "ROT090",
                     "f2-s1-native-raw-to-typed-label-request-v2-001")
        if any(token in value for token in forbidden):
            _fail(f"historical row-78/ROOT242 path leaked into canonical phase: {value}")
    elif isinstance(value, Mapping):
        for item in value.values():
            _replace_old_paths(item)
    elif isinstance(value, list):
        for item in value:
            _replace_old_paths(item)


def _phase_request(*, plan: Mapping[str, Any], proof: Mapping[str, Any], proof_path: Path,
                   decoder_path: Path, python_path: str, attempt_id: str) -> dict[str, Any]:
    base = copy.deepcopy(dict(plan["request_overlay"]["request"]))
    selection = plan["selection"]
    case_id = str(selection["physical_case_id"])
    row = plan["current_binding"]["row"]
    proof_row = _proof_case(proof, case_id)
    timeline = proof_row.get("actual_timeline")
    if not isinstance(timeline, Mapping) or not isinstance(timeline.get("time_s"), list):
        _fail("saved-mask proof does not expose the frozen timeline")
    times = timeline["time_s"]
    if len(times) != int(row["frames"]):
        _fail("saved-mask timeline length differs from CURRENT row")
    if any(not isinstance(value, (int, float)) for value in times):
        _fail("saved-mask timeline contains a nonnumeric time")
    if not decoder_path.is_file() or decoder_path.is_symlink() or not os.access(decoder_path, os.X_OK):
        _fail(f"decoder is not an executable regular file: {decoder_path}")
    decoder_sha = _sha(decoder_path, "BI4 decoder", limit=4 * 1024 * 1024)
    current_binding = base["current_binding"]
    current_binding.update({
        "case_index": 65, "physical_case_id": case_id,
        "runtime_case_alias": selection.get("runtime_case_alias"),
        "frames": int(row["frames"]), "particles": int(row["particles"]),
        "actual_time_window_s": list(row["time_window_s"]),
        "saved_mask_proof_status": proof_row["status"],
    })
    base.update({
        "request_id": f"f2-s1-canonical65-raw-to-typed-{attempt_id}",
        "status": "PENDING_PARENT_GUARD_CONTENT_SHA256",
        "phase": "raw_to_typed",
        "next_phase": "typed_to_label_from_actual_raw_to_typed_receipt",
        "case_identity": {
            "current_case_index": 65, "family_id": "F2",
            "manifest_case_id": selection.get("runtime_case_alias"),
            "manifest_physical_case_id": case_id, "physical_case_id": case_id,
            "runtime_case_alias": selection.get("runtime_case_alias"),
            "identity_status": "CANONICAL_CURRENT_SAVED_MASK",
        },
        "current_binding": current_binding,
        "source_hashes_preverified_by_parent": False,
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
    })
    pending_sources = _pending_source_hashes(base)
    base["decoder"] = {
        "role": "upstream_bi4_dump_decoder", "path": str(decoder_path),
        "sha256": decoder_sha, "source": "trusted ds_data02_f5_bi4.decode_frame",
        "content_verification_phase": "PARENT_AFTER_RESERVATION",
    }
    base["cohort"] = {
        "expected_initial_fluid_count": 21114, "identity_key": "(Zone,Idp)",
        "initial_mk_codes": [1, 2, 3], "initial_type_code": 3, "max_particles": None,
        "selection": "initial_csv_type_mk_identity_set",
        "small_cohort": "none; exact 21114 Type3/MK1-3 identities from source-bound initial.csv",
        "source_definition": "initial.csv frame0 identity set; Type=3 and Mk in {1,2,3}; (Zone,Idp) hash",
        "source_identity_set_sha256": IDENTITY_SHA,
        "source_identity_content_phase": "PARENT_AFTER_RESERVATION",
        "source_csv_role": "initial_csv",
        "initial_mk_counts": {"1": 7038, "2": 7038, "3": 7038},
        "source_fallback": "REJECT",
    }
    base["initial_mass_denominator"] = {
        "denominator_kg": 21.114001002861187,
        "initial_fluid_mass_kg": 21.114001002861187,
        "initial_missing_mass_kg": 0.0, "initially_absent_count": 0,
        "later_missing_mass_kg": 0.003000000142492354,
        "later_missing_unique_count": 3,
        "mass_source": "ROOT206 saved-mask fluid ledger; parent rechecks typed output",
        "missing_scope": "initial denominator excludes initially absent fluid; later missing IDs remain unknown",
    }
    base["typed_output_contract"] = {
        "schema": "ds-data-02.hdf5-schema.v1", "frames": int(row["frames"]),
        "particles": int(row["particles"]), "identity_key": "(Zone,Idp)",
        "expected_times_s": [float(value) for value in times],
        "fluid_identity_ids": None, "fluid_identity_zones": None, "fluid_identity_mks": None,
        "fluid_identity_source": "initial.csv Type=3 Mk in {1,2,3}; exact parent-verified identity SHA",
        "fluid_mk_counts": {"1": 7038, "2": 7038, "3": 7038},
        "initial_identity_sha256": IDENTITY_SHA,
        "particle_chunk": 65536,
        "raw_header_fields": ["CaseNp", "CaseNpFixed", "CaseNpMoving", "CaseNpFluid",
                               "CaseNpBound", "CaseNpFloat", "CaseNpSensor", "TimeStep",
                               "CellCode", "BoundaryCode", "Idp", "Mk", "Type"],
        "inactive_semantics": "valid=false; state fields unknown; identity/type/MK retained only for active rows",
        "validation_phase": "AFTER_PARENT_RESERVATION_AND_TYPED_OUTPUT",
    }
    base["label_contract"] = {
        "status": "DEFERRED_AFTER_RAW_TO_TYPED_RECEIPT", "v15_operator": "replay_trajectory_v15",
        "v15_operator_module": "v15_operator", "v16_operator": "forward_result",
        "v16_operator_module": "v16_operator", "evaluator": "v15.evaluate_receiver_manual_predictions_v15",
        "predictions_required_for_score": True, "qualification": "UNKNOWN",
        "source_fallback": "REJECT", "phase": "NOT_RUN_IN_RAW_TO_TYPED_PHASE",
    }
    base["v15_request"] = {
        "status": "DEFERRED_UNTIL_TYPED_RECEIPT", "phase": "typed_to_label",
        "canonical_case_id": case_id, "current_sha256": CURRENT_SHA,
        "source_fallback_forbidden": True, "request_path": None,
        "builder_input": "actual raw_to_typed report and typed output SHA/stat only",
    }
    base["evidence_scope"] = {
        "status": "SAVED_MASK_DIAGNOSTIC_ONLY",
        "scientific_credit": "NONE",
        "raw_payload_read_by_planner": False,
        "historical_alias_fallback": False,
        "current": {"path": current_binding["path"], "sha256": CURRENT_SHA, "case_index": 65},
        "saved_mask_proof": {"path": str(proof_path), "sha256": _sha(proof_path, "saved-mask proof")},
        "case_manifest": {"path": proof_row["case_manifest"], "sha256": proof_row["case_manifest_sha256"]},
        "case_receipt": {"path": proof_row["receipt"], "sha256": proof_row["receipt_sha256"]},
        "summary": {"path": proof_row["summary"], "sha256": proof_row["summary_sha256"]},
        "source_trajectory": copy.deepcopy(dict(proof_row["source_trajectory"])),
        "role": "DEVELOPMENT",
    }
    raw = base.get("raw_binding")
    if not isinstance(raw, dict):
        _fail("planner did not produce raw_binding")
    raw["expected_raw_tree_sha256"] = PENDING
    raw["content_hash_status"] = "PARENT_GUARD_REQUIRED"
    raw["content_hash_phase"] = "AFTER_PARENT_RESERVATION"
    raw["parent_rehash_required"] = True
    for frame in raw.get("frames", []):
        if isinstance(frame, dict):
            frame["sha256"] = PENDING
            frame["content_hash_status"] = "PARENT_GUARD_REQUIRED"
            frame["content_hash_phase"] = "AFTER_PARENT_RESERVATION"
    raw_root = Path(str(raw["data_root"])).expanduser()
    raw_bytes = _raw_stat_bytes(raw_root)
    base["resource_request"] = {
        "cpu_cores": 1, "threads": 1, "max_wall_seconds": 3600,
        "raw_tree_bytes_stat_only": raw_bytes, "raw_source_copy_bytes": raw_bytes,
        "typed_output_estimate_bytes": 1_191_366_281,
        "converter_report_estimate_bytes": 2_000_000,
        "decoder_scratch_peak_bound_bytes": 128 * 1024 * 1024,
        "new_output_and_log_bound_bytes": 512 * 1024 * 1024,
        "external_storage_reservation_bytes": raw_bytes + 1_191_366_281 + 128 * 1024 * 1024 + 512 * 1024 * 1024,
        "storage_estimate_basis": "stat-only source copy + typed estimate + bounded decoder/log/output allowance; parent recomputes",
        "requires_parent_stage2guard": True, "source_read_after_reservation": True,
        "hdf5_read": "typed output is read only in a later phase",
        "scratch": "attempt-owned per-frame decoder scratch; parent must measure peak",
    }
    base["execution"] = {
        "python": python_path, "python_argv0_policy": "LITERAL_PINNED_VENV",
        "requires_parent_stage2guard": True, "parent_pid_required": True,
        "source_fallback": "REJECT", "raw_payload_read_phase": "AFTER_PARENT_RESERVATION",
        "run_labels": False, "run_evaluator": False,
        "command_template": [python_path, "-B", "-I", "<bound_worker_path>", "run",
                              "--request", "<bound_request_path>", "--output-dir",
                              "<attempt_owned_output_dir>", "--io-slot-approved"],
    }
    base["parent_guard"] = {
        "status": "READY_FOR_PARENT_PHASE_GUARD",
        "request_status_after_content_hash": "READY_FOR_PARENT_GUARD",
        "pending_raw_tree_sha256": True,
        "pending_raw_frame_sha256_count": len(raw.get("frames", [])),
        "pending_source_sha256_count": pending_sources,
        "required_pre_post": ["raw_tree", "all_raw_frames", "all_source_files", "decoder", "request"],
        "same_parent_ledger": True, "no_original_path_fallback": True,
        "worker_launch_allowed_before_fill": False,
    }
    base["worker_ready"] = False
    base["launch_allowed"] = False
    base["source_fallback"] = "REJECT"
    base["phase_request_schema"] = SCHEMA
    # Keep the digest over the request body before adding the digest field;
    # unlike the worker's ``sha256`` convention this field is explicitly a
    # canonical-body digest and is not self-referential.
    base["phase_request_canonical_sha256"] = _canonical(base)
    _replace_old_paths(base)
    return base


def build_phase(*, current_path: Path, catalog_path: Path, physical_index_path: Path,
                proof_path: Path, repo_root: Path, output_dir: Path,
                decoder_path: Path | None = None, python_path: str = PYTHON_DEFAULT,
                attempt_id: str = "root-canonical65-phase-001") -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        _fail(f"refusing to overwrite non-empty phase output: {output_dir}")
    proof = _json(proof_path, "ROOT saved-mask proof")
    decoder = decoder_path or Path(DECODER_DEFAULT)
    with tempfile.TemporaryDirectory(prefix="canonical65-plan-") as temporary:
        plan = PLANNER.build_plan(
            current_path=current_path, catalog_path=catalog_path,
            physical_index_path=physical_index_path, proof_path=proof_path,
            repo_root=repo_root, output_dir=Path(temporary), index=65,
        )
        request = _phase_request(plan=plan, proof=proof, proof_path=proof_path,
                                 decoder_path=decoder, python_path=python_path,
                                 attempt_id=attempt_id)
    output_dir.mkdir(parents=True, exist_ok=False)
    request_path = output_dir / "f2-s1-canonical65-raw-to-typed-phase-request-v1.json"
    request_file_sha, request_stat = _write_new(request_path, request, "phase request")
    manifest = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_PHASE_GUARD",
        "phase": "raw_to_typed", "next_phase": "typed_to_label_from_actual_receipt",
        "request": {"path": str(request_path), "file_sha256": request_file_sha,
                     "canonical_sha256": request["phase_request_canonical_sha256"], "stat": request_stat},
        "case_identity": request["case_identity"],
        "current_binding": request["current_binding"],
        "saved_mask_evidence": request["evidence_scope"],
        "parent_guard": request["parent_guard"],
        "worker_ready": False, "launch_allowed": False,
        "scientific_payload_read_by_builder": False,
        "qualification": dict(UNKNOWN), "scientific_credit": "NONE",
        "source_fallback": "REJECT", "ledger_mutated": False,
    }
    manifest["manifest_canonical_sha256"] = _canonical(manifest)
    manifest_path = output_dir / "f2-s1-canonical65-raw-to-typed-phase-manifest-v1.json"
    manifest_file_sha, manifest_stat = _write_new(manifest_path, manifest, "phase manifest")
    return {"schema": SCHEMA, "status": manifest["status"],
            "request": {"path": str(request_path), "file_sha256": request_file_sha},
            "manifest": {"path": str(manifest_path), "file_sha256": manifest_file_sha},
            "pending_raw_frames": request["parent_guard"]["pending_raw_frame_sha256_count"],
            "pending_source_hashes": request["parent_guard"]["pending_source_sha256_count"],
            "worker_ready": False, "launch_allowed": False,
            "raw_payload_read": False, "ledger_mutated": False,
            "qualification": dict(UNKNOWN)}


def validate_phase(path: Path) -> dict[str, Any]:
    request = _json(path, "canonical65 phase request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("phase_request_schema") != SCHEMA:
        _fail("phase request schema differs")
    if request.get("status") != "PENDING_PARENT_GUARD_CONTENT_SHA256":
        _fail("phase request must remain parent-content pending")
    # The digest is computed before this field is added, so remove it for the
    # comparison rather than accepting a caller-controlled marker.
    body = dict(request)
    body.pop("phase_request_canonical_sha256", None)
    if request.get("phase_request_canonical_sha256") != _canonical(body):
        _fail("phase request canonical digest differs")
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or identity.get("current_case_index") != 65 or \
            identity.get("physical_case_id") != CANONICAL_ID:
        _fail("phase request is not exact canonical CURRENT row 65")
    if request.get("current_binding", {}).get("sha256") != CURRENT_SHA:
        _fail("phase request CURRENT SHA differs")
    if request.get("source_hashes_preverified_by_parent") is not False:
        _fail("phase request cannot claim parent source hashes")
    raw = request.get("raw_binding")
    if not isinstance(raw, Mapping) or raw.get("expected_raw_tree_sha256") != PENDING:
        _fail("phase request must defer raw tree hash")
    contract = request.get("typed_output_contract")
    if not isinstance(contract, Mapping) or len(contract.get("expected_times_s", [])) != 401:
        _fail("phase request typed timeline is incomplete")
    if request.get("worker_ready") is not False or request.get("launch_allowed") is not False:
        _fail("parent-pending phase cannot claim runnable status")
    if request.get("qualification") != UNKNOWN:
        _fail("qualification must remain UNKNOWN")
    _replace_old_paths(request)
    if request.get("parent_guard", {}).get("no_original_path_fallback") is not True:
        _fail("phase request permits source fallback")
    return {"schema": SCHEMA, "status": "VALIDATED_PARENT_PHASE_GUARD_REQUIRED",
            "canonical_case_id": CANONICAL_ID, "current_index": 65,
            "worker_ready": False, "launch_allowed": False, "raw_payload_read": False,
            "qualification": dict(UNKNOWN)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("current", "catalog", "physical_index", "proof", "repo_root", "output_dir"):
        build.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    build.add_argument("--decoder", type=Path)
    build.add_argument("--python", default=PYTHON_DEFAULT)
    build.add_argument("--attempt-id", default="root-canonical65-phase-001")
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_phase(args.request)
        else:
            result = build_phase(current_path=args.current, catalog_path=args.catalog,
                                 physical_index_path=args.physical_index, proof_path=args.proof,
                                 repo_root=args.repo_root, output_dir=args.output_dir,
                                 decoder_path=args.decoder, python_path=args.python,
                                 attempt_id=args.attempt_id)
    except (PhaseError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "REJECTED", "error": str(error)},
                         sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
