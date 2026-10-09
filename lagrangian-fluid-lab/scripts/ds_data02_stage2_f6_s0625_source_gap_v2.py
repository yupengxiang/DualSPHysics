#!/usr/bin/env python3
"""Prepare a source-only evidence bridge for the F6 S0625/YAWM06 case.

This product opens only bounded JSON metadata and the already-produced compact
native omission report.  It does not open the trajectory H5, Part*.bi4,
PartOut.csv, RunPARTs.csv, or any typed JSONL.  The report's three identities
remain a report-level/native-reference edge until a parent-guarded consumer
joins them to the post-ROOT210 typed lifecycle product.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
HISTORICAL_INVENTORY_SCHEMA = "ds02.stage2.historical118-source-inventory.v1"
SCOPE_SCHEMA = "ds02.stage2.native-typed-case-dependency-inventory.v2"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
REPORT_SCHEMA = "ds02.stage2.omission-forensics.v2"
OUTPUT_SCHEMA = "ds02.stage2.f6-s0625-source-gap.v2"
ROOT210_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
ROOT210_PROOF_STATUS = "VERIFIED_ACTUAL_F6_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT"
ROOT210_SUMMARY_SCHEMA = "ds02.stage2.typed-lifecycle-sidecar.v4"
ROOT210_SUMMARY_STATUS = "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT"
CASE_ID = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0625_YAWM06_DP025"
FAMILY_ID = "F6"
EXPECTED_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
DEFERRED_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".jsonl", ".vtk", ".csv"}


class SourceGapError(ValueError):
    """Raised when the bounded source graph is not exact."""


def _sha256(path: Path, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    stat = path.stat()
    if stat.st_size > max_bytes:
        raise SourceGapError(f"refusing to hash {stat.st_size} bytes above bound: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, label: str, *, allow_deferred: bool = False) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file() and not path.is_dir():
        raise SourceGapError(f"{label} is missing: {path}")
    if not allow_deferred and path.suffix.lower() in DEFERRED_SUFFIXES:
        raise SourceGapError(f"{label} is deferred payload content: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
    }


def _read_json(path: Path, label: str, *, allow_deferred: bool = False) -> tuple[dict[str, Any], dict[str, Any], str]:
    path = Path(path).expanduser().resolve()
    if not allow_deferred and path.suffix.lower() in DEFERRED_SUFFIXES:
        raise SourceGapError(f"{label} is deferred payload content: {path}")
    stat = _stat(path, label, allow_deferred=allow_deferred)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise SourceGapError(f"{label} exceeds bounded JSON size: {path}")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceGapError(f"{label} is not bounded JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SourceGapError(f"{label} must be a JSON object")
    return value, stat, hashlib.sha256(raw).hexdigest()


def _ref(path: Any, label: str, expected_sha: Any | None = None, *, allow_deferred: bool = False) -> dict[str, Any]:
    if not isinstance(path, (str, os.PathLike)) or not str(path):
        raise SourceGapError(f"{label} lacks a path")
    result = _stat(Path(path), label, allow_deferred=allow_deferred)
    result["content_opened"] = False
    if expected_sha is not None:
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            raise SourceGapError(f"{label} expected SHA is malformed")
        result["declared_sha256"] = expected_sha.lower()
    return result


def _case(rows: Any, label: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise SourceGapError(f"{label} rows are missing")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == CASE_ID]
    if len(matches) != 1:
        raise SourceGapError(f"{label} does not contain one exact {CASE_ID}")
    return matches[0]


def _same_identity(left: dict[str, Any], right: dict[str, Any], label: str) -> None:
    if left.get("zone") != right.get("zone") or left.get("idp") != right.get("idp"):
        raise SourceGapError(f"{label} identity differs")
    if left.get("first_missing_frame") != right.get("first_missing_frame"):
        raise SourceGapError(f"{label} first-missing frame differs")
    left_bracket = left.get("first_missing_bracket_s")
    right_bracket = right.get("first_missing_bracket_s")
    # The compact typed_identity list intentionally carries only identity and
    # first frame; the richer excluded_particles row carries the saved
    # bracket.  Compare brackets only when both evidence rows expose them.
    if left_bracket is not None and right_bracket is not None and left_bracket != right_bracket:
        raise SourceGapError(f"{label} saved bracket differs")


def _same_stat_only(left: dict[str, Any], right: dict[str, Any], label: str) -> None:
    """Compare a deferred artifact's complete stat tuple without opening it."""
    fields = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    for field in fields:
        if left.get(field) != right.get(field):
            raise SourceGapError(f"{label} {field} differs")


def _root210_bridge(args: argparse.Namespace, current_trajectory: dict[str, Any]) -> dict[str, Any] | None:
    """Bind the completed ROOT210 compact proof and one case summary.

    The records JSONL remains deferred: this function only opens the bounded
    proof/summary JSON and stats the declared records path.  It therefore
    cannot grant a per-ID native/typed join or any physical interpretation.
    """
    if args.root210_proof is None and args.root210_summary is None:
        return None
    if args.root210_proof is None or args.root210_summary is None:
        raise SourceGapError("ROOT210 proof and summary must be supplied together")
    proof, proof_stat, proof_sha = _read_json(args.root210_proof, "ROOT210 actual proof")
    if proof.get("schema") != ROOT210_PROOF_SCHEMA or proof.get("status") != ROOT210_PROOF_STATUS:
        raise SourceGapError("ROOT210 proof schema/status differs")
    verifications = proof.get("case_verifications")
    if not isinstance(verifications, list):
        raise SourceGapError("ROOT210 proof case_verifications is missing")
    matches = [row for row in verifications if isinstance(row, dict) and row.get("physical_case_id") == CASE_ID]
    if len(matches) != 1:
        raise SourceGapError("ROOT210 proof does not contain one exact target case")
    verification = matches[0]
    if verification.get("family_id") != FAMILY_ID or verification.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise SourceGapError("ROOT210 target verification status/family differs")
    if verification.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
        raise SourceGapError("ROOT210 target H5 source closure is not explicitly stable")
    source_trajectory = verification.get("source_trajectory")
    if not isinstance(source_trajectory, dict):
        raise SourceGapError("ROOT210 target trajectory edge is missing")
    if source_trajectory.get("path") != current_trajectory.get("path") or source_trajectory.get("known_sha256") != current_trajectory.get("producer_declared_sha256"):
        raise SourceGapError("ROOT210 target trajectory differs from CURRENT")
    if source_trajectory.get("pre_sha256") != source_trajectory.get("post_sha256") or source_trajectory.get("pre_sha256") != source_trajectory.get("known_sha256"):
        raise SourceGapError("ROOT210 target trajectory hashes are not equal")

    summary, summary_stat, summary_sha = _read_json(args.root210_summary, "ROOT210 typed summary")
    summary_path = Path(args.root210_summary).expanduser().resolve()
    if summary.get("schema") != ROOT210_SUMMARY_SCHEMA or summary.get("status") != ROOT210_SUMMARY_STATUS:
        raise SourceGapError("ROOT210 typed summary schema/status differs")
    if summary.get("physical_case_id") != CASE_ID or summary.get("family_id") != FAMILY_ID:
        raise SourceGapError("ROOT210 typed summary identity differs")
    if verification.get("summary") != str(summary_path) or verification.get("summary_sha256") != summary_sha:
        raise SourceGapError("ROOT210 proof does not bind the supplied summary path/SHA")
    records = summary.get("records")
    records_stat_only = verification.get("records_stat_only")
    if not isinstance(records, dict) or not isinstance(records_stat_only, dict):
        raise SourceGapError("ROOT210 records references are missing")
    if records.get("path") != records_stat_only.get("path") or records.get("sha256") != records_stat_only.get("sha256") or records.get("bytes") != records_stat_only.get("bytes") or records.get("rows") != records_stat_only.get("rows"):
        raise SourceGapError("ROOT210 proof and summary records references differ")
    records_path = Path(records["path"]).expanduser().resolve()
    current_records_stat = _stat(records_path, "ROOT210 typed records", allow_deferred=True)
    expected_records_stat = {key: records_stat_only.get(key) for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}
    _same_stat_only(current_records_stat, expected_records_stat, "ROOT210 typed records")
    fluid = summary.get("role_ledgers", {}).get("fluid") if isinstance(summary.get("role_ledgers"), dict) else None
    if not isinstance(fluid, dict) or fluid.get("first_disappearance_count") != 3:
        raise SourceGapError("ROOT210 fluid first-disappearance count is not exactly three")
    if fluid.get("unknown_active_id_count") != 0 or fluid.get("unknown_type_count") != 0:
        raise SourceGapError("ROOT210 fluid identity/type uncertainty is nonzero")
    timeline = summary.get("timeline")
    metadata = summary.get("metadata")
    if not isinstance(timeline, dict) or timeline.get("frames") != 241 or timeline.get("particles") != 417505:
        raise SourceGapError("ROOT210 target timeline dimensions differ")
    return {
        "proof": {"path": str(Path(args.root210_proof).expanduser().resolve()), "sha256": proof_sha, "stat": proof_stat, "content_opened": True},
        "case_verification": {"status": verification.get("status"), "summary_path": str(summary_path), "summary_sha256": summary_sha, "source_h5_prepost_stable": True, "scientific_qualification": verification.get("scientific_qualification")},
        "summary": {"path": str(summary_path), "sha256": summary_sha, "stat": summary_stat, "schema": summary.get("schema"), "status": summary.get("status"), "timeline": {"frames": timeline.get("frames"), "particles": timeline.get("particles"), "time_first_s": (timeline.get("time_s") or [None])[0], "time_last_s": (timeline.get("time_s") or [None])[-1]}, "metadata": {"identity_key": metadata.get("identity_key") if isinstance(metadata, dict) else None, "identity_unique": metadata.get("identity_unique") if isinstance(metadata, dict) else None, "units_status": metadata.get("units_status") if isinstance(metadata, dict) else None}, "fluid": {"first_disappearance_count": fluid.get("first_disappearance_count"), "initial_count": fluid.get("initial_count"), "initial_mass_kg": fluid.get("initial_mass_kg"), "unknown_active_id_count": fluid.get("unknown_active_id_count"), "unknown_type_count": fluid.get("unknown_type_count"), "inactive_type_sentinel_count": fluid.get("inactive_type_sentinel_count")}},
        "records_deferred": {"path": str(records_path), "bytes": records.get("bytes"), "rows": records.get("rows"), "sha256": records.get("sha256"), "stat": current_records_stat, "content_opened": False},
        "join_scope": "ROOT210 typed saved-mask summary is bound; per-ID native PartOut/RunPARTs join remains deferred",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    current, current_stat, current_sha = _read_json(args.current, "CURRENT336")
    if current.get("schema") != CURRENT_SCHEMA or len(current.get("cases", [])) != 336:
        raise SourceGapError("CURRENT schema or case count differs")
    if current_sha != EXPECTED_CURRENT_SHA:
        raise SourceGapError(f"CURRENT SHA differs: {current_sha}")
    current_row = _case(current.get("cases"), "CURRENT")
    if current_row.get("family_id") != FAMILY_ID or current_row.get("physical_case_id") != CASE_ID:
        raise SourceGapError("CURRENT family/case differs")
    if int(current_row.get("current_index", -1)) not in {-1, 247} and int(current_row.get("index", -1)) not in {-1, 247}:
        raise SourceGapError("CURRENT index is not 247")

    scope, scope_stat, scope_sha = _read_json(args.scope, "native typed scope V2")
    if scope.get("schema") != SCOPE_SCHEMA or scope.get("status") != "SOURCE_ONLY_SCOPE_REFINED_NO_LAUNCH":
        raise SourceGapError("scope V2 schema/status differs")
    scope_row = _case(scope.get("case_rows"), "scope V2")
    if scope_row.get("family_id") != FAMILY_ID or scope_row.get("classification") != "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN":
        raise SourceGapError("scope does not preserve the unlocated F6 classification")
    if scope_row.get("historical_ids_match_scan") is not False or scope_row.get("historical_joined_count") is not None:
        raise SourceGapError("scope unexpectedly grants a historical ID join")
    if int(scope_row.get("report_excluded_particle_count", -1)) != 3 or int(scope_row.get("report_typed_missing_fluid_count", -1)) != 3:
        raise SourceGapError("scope report count differs")
    if scope_row.get("typed_native_first_missing_join_scope") != "NOT_PROVEN_FOR_THIS_CASE":
        raise SourceGapError("scope unexpectedly grants typed/native first-missing credit")

    inventory, inventory_stat, inventory_sha = _read_json(args.inventory, "historical source inventory")
    if inventory.get("schema") != HISTORICAL_INVENTORY_SCHEMA:
        raise SourceGapError("historical source inventory schema differs")
    inventory_row = _case(inventory.get("rows"), "historical source inventory")
    # The historical V1 inventory is the exact small metadata source used by
    # the scope V2 product; it intentionally has no typed lifecycle attempt
    # for this case until ROOT210 finishes.
    if inventory_row.get("family_id") != FAMILY_ID or inventory_row.get("current336_index") != 247:
        raise SourceGapError("dependency inventory CURRENT join differs")
    if inventory_row.get("typed_lifecycle_attempts") not in ([], None):
        raise SourceGapError("inventory unexpectedly contains a typed lifecycle attempt")

    report, report_stat, report_sha = _read_json(args.report, "native omission report")
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "CAUSES_RECONCILED":
        raise SourceGapError("native report schema/status differs")
    if report.get("physical_case_id") != CASE_ID or report.get("family_id") != FAMILY_ID:
        raise SourceGapError("native report identity differs")
    report_trajectory = report.get("trajectory")
    current_trajectory = current_row.get("trajectory")
    if not isinstance(report_trajectory, dict) or not isinstance(current_trajectory, dict):
        raise SourceGapError("report/CURRENT trajectory edge missing")
    if report_trajectory.get("path") != current_trajectory.get("path") or report_trajectory.get("sha256") != current_trajectory.get("producer_declared_sha256"):
        raise SourceGapError("native report trajectory edge differs from CURRENT")
    excluded = report.get("excluded_particles")
    typed_ids = report.get("typed_identity", {}).get("ids") if isinstance(report.get("typed_identity"), dict) else None
    if not isinstance(excluded, list) or len(excluded) != 3 or not isinstance(typed_ids, list) or len(typed_ids) != 3:
        raise SourceGapError("native report target IDs are not exactly three")
    excluded_by_key = {(row.get("zone"), row.get("idp")): row for row in excluded if isinstance(row, dict)}
    typed_by_key = {(row.get("zone"), row.get("idp")): row for row in typed_ids if isinstance(row, dict)}
    if len(excluded_by_key) != 3 or set(excluded_by_key) != set(typed_by_key):
        raise SourceGapError("native report typed/excluded identity sets differ")
    for key, row in excluded_by_key.items():
        _same_identity(row, typed_by_key[key], f"report {key}")
        if row.get("native_exit_cause") != "NUMERICAL_POSITION_EXCLUSION" or row.get("native_motive_code") != 1:
            raise SourceGapError(f"report {key} native category differs")
    native_decode = report.get("native_decode")
    provenance = report.get("source_provenance")
    if not isinstance(native_decode, dict) or not isinstance(provenance, dict):
        raise SourceGapError("native report source edges are missing")

    artifact_rows = inventory_row.get("source_artifacts", {}).get("artifacts")
    if not isinstance(artifact_rows, dict):
        raise SourceGapError("inventory source artifacts are missing")
    artifacts: dict[str, Any] = {}
    for role, item in artifact_rows.items():
        if not isinstance(item, dict):
            raise SourceGapError(f"inventory artifact is malformed: {role}")
        path = item.get("path") or item.get("canonical_path")
        if path is None:
            # The historical inventory keeps the solver_output directory as
            # an aggregate entry whose concrete Run.out/RunPARTs/data edges
            # are listed below it; the per-edge references are already bound
            # by the compact native report.  Preserve that index without
            # pretending the aggregate has a file path of its own.
            artifacts[role] = {
                "role": item.get("role", role),
                "inventory_status": item.get("status"),
                "content_opened_by_inventory": item.get("content_opened_by_inventory", False),
                "hash_checked_by_inventory": item.get("hash_checked_by_inventory", False),
                "aggregate_index_only": True,
            }
            continue
        allow_deferred = role in {"typed_trajectory_h5", "native_part_directory", "raw_solver_root", "xmf"} or str(path).lower().endswith(tuple(DEFERRED_SUFFIXES))
        artifacts[role] = {"role": item.get("role", role), "reference": _ref(path, f"inventory {role}", item.get("declared_sha256"), allow_deferred=allow_deferred), "inventory_status": item.get("status"), "content_opened_by_inventory": item.get("content_opened_by_inventory", False), "hash_checked_by_inventory": item.get("hash_checked_by_inventory", False)}

    native_refs = {
        "report": {"path": str(Path(args.report).resolve()), "sha256": report_sha, "bytes": report_stat["bytes"], "content_opened": True},
        "partout": native_decode.get("partout"),
        "runparts": native_decode.get("runparts"),
        "receipt": native_decode.get("receipt"),
        "binary": native_decode.get("binary"),
        "data_root": provenance.get("data_root"),
    }
    source_edges = {
        "current": {"path": str(Path(args.current).resolve()), "sha256": current_sha, "stat": current_stat, "case_index": 247, "scientific_scan_status": current_row.get("scientific_scan_status"), "trajectory": {"path": current_trajectory.get("path"), "producer_declared_sha256": current_trajectory.get("producer_declared_sha256"), "bytes": current_trajectory.get("bytes"), "content_opened": False}},
        "scope_v2": {"path": str(Path(args.scope).resolve()), "sha256": scope_sha, "classification": scope_row.get("classification"), "historical_ids_match_scan": scope_row.get("historical_ids_match_scan"), "historical_joined_count": scope_row.get("historical_joined_count"), "scan_completed_in_scope": scope_row.get("scan_completed"), "typed_native_first_missing_join_scope": scope_row.get("typed_native_first_missing_join_scope")},
        "historical_inventory_v1": {"path": str(Path(args.inventory).resolve()), "sha256": inventory_sha, "current_index": inventory_row.get("current336_index"), "typed_lifecycle_attempts": inventory_row.get("typed_lifecycle_attempts", []), "native_first_missing_source_join": inventory_row.get("native_first_missing_source_join")},
        "native_report": native_refs,
        "solver": {"generated_xml": provenance.get("generated_xml"), "gencase_receipt": provenance.get("gencase_receipt"), "solver_receipt": provenance.get("solver_receipt"), "control_sha256": provenance.get("control_sha256"), "raw_solver_root": artifacts.get("raw_solver_root", {}).get("reference")},
        "conversion": {"path": artifacts.get("conversion_report", {}).get("reference", {}).get("path"), "declared_sha256": artifacts.get("conversion_report", {}).get("reference", {}).get("declared_sha256"), "CURRENT_recomputed_sha256": current_row.get("conversion_report", {}).get("recomputed_sha256")},
        "identity": {"key": "(Zone,Idp)", "report_typed_identity_count": len(typed_by_key), "report_excluded_count": len(excluded_by_key), "report_ids": [[int(zone), int(idp)] for zone, idp in sorted(excluded_by_key)]},
    }
    root210 = _root210_bridge(args, current_trajectory)
    output_status = "SOURCE_ONLY_PREPARED_ROOT210_TYPED_SUMMARY_BOUND" if root210 is not None else "SOURCE_ONLY_PREPARED_WAITING_ROOT210_TYPED_TERMINAL"
    output = {
        "schema": OUTPUT_SCHEMA,
        "status": output_status,
        "physical_case_id": CASE_ID,
        "family_id": FAMILY_ID,
        "current_index": 247,
        "source_inputs": {"current": {"path": str(Path(args.current).resolve()), "sha256": current_sha, "bytes": current_stat["bytes"]}, "scope_v2": {"path": str(Path(args.scope).resolve()), "sha256": scope_sha, "bytes": scope_stat["bytes"]}, "historical_inventory_v1": {"path": str(Path(args.inventory).resolve()), "sha256": inventory_sha, "bytes": inventory_stat["bytes"]}, "native_report": {"path": str(Path(args.report).resolve()), "sha256": report_sha, "bytes": report_stat["bytes"]}},
        "source_edges": source_edges,
        "artifacts": artifacts,
        "native_reference": {"category": "NUMERICAL_POSITION_EXCLUSION", "motive_code": 1, "report_target_count": 3, "report_ids": [[int(zone), int(idp)] for zone, idp in sorted(excluded_by_key)], "report_first_missing_frames": {f"{zone}:{idp}": excluded_by_key[(zone, idp)].get("first_missing_frame") for zone, idp in sorted(excluded_by_key)}, "report_first_missing_brackets_s": {f"{zone}:{idp}": excluded_by_key[(zone, idp)].get("first_missing_bracket_s") for zone, idp in sorted(excluded_by_key)}, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "root210_typed_lifecycle": root210,
        "evidence_gap": {"current_scan_status": current_row.get("scientific_scan_status"), "historical_scope_scan_completed": scope_row.get("scan_completed"), "historical_ids_match_scan": scope_row.get("historical_ids_match_scan"), "historical_joined_count": scope_row.get("historical_joined_count"), "typed_lifecycle_status": "NO_ATTEMPT_IN_INVENTORY; ROOT210_TERMINAL_PENDING", "report_identity_join": "REPORT_INTERNAL_TYPED_IDENTITY_EQUALS_EXCLUDED_ROWS_ONLY", "native_csv_content": "DEFERRED_AFTER_PARENT_RESERVATION", "typed_jsonl_content": "DEFERRED_AFTER_ROOT210_TERMINAL_AND_PARENT_RESERVATION", "h5_content": "NOT_OPENED", "bi4_content": "NOT_OPENED", "conclusion": "The compact report is source-bound to the solver/conversion/XML edges, but the historical index did not bind its three IDs to a completed scan and CURRENT presently says NOT_SCANNED; no per-fluid native cause credit is issued."},
        "next_guarded_consumer": {"status": "NOT_READY_UNTIL_ROOT210_TERMINAL_PROOF", "required_inputs": ["ROOT210 completed typed summary and records path/SHA/stat", "exact ROOT210 case manifest and receipt", "existing PartOut.csv and RunPARTs.csv paths/SHA/stat", "current/source report edges above"], "operation": "stream only the ROOT210 typed lifecycle output, then read the existing compact PartOut/RunPARTs outputs under one parent reservation and exact stat/SHA pre/post checks", "resource_policy": {"cpu_threads": 1, "max_memory_bytes": 1073741824, "max_wall_seconds": 900, "output_cap_bytes": 8388608, "h5_content_read": False, "bi4_content_read": False, "solver_launch": False}, "comparison": "exact (Zone,Idp), first saved frame and saved bracket; continuous event time, physical fate, legal flux, and dynamics remain UNKNOWN"},
        "content_policy": {"bounded_json_opened": True, "report_json_opened": True, "root210_proof_json_opened": root210 is not None, "root210_summary_json_opened": root210 is not None, "h5_opened": False, "jsonl_opened": False, "native_bi4_opened": False, "partout_csv_opened": False, "runparts_csv_opened": False, "solver_started": False},
        "launch_allowed": False,
    }
    if root210 is not None:
        output["evidence_gap"].update({
            "typed_lifecycle_status": "ROOT210_COMPLETED_TYPED_SAVED_MASK_SUMMARY_BOUND; RECORDS_DEFERRED",
            "typed_first_missing_count": 3,
            "typed_native_first_missing_join": "NOT_YET_PER_ID_JOINED",
            "conclusion": "ROOT210 binds the completed typed saved-mask summary and stable source H5 edge for this exact CURRENT case. The three typed fluid first-disappearance observations are not yet joined to native PartOut/RunPARTs rows here; native numerical cause remains a separate report-level edge, and physical fate, legal flux, dynamics, and QI/QN/QE remain UNKNOWN.",
        })
        output["next_guarded_consumer"].update({
            "status": "READY_PARENT_GUARDED_TYPED_NATIVE_JOIN_NOT_LAUNCHED",
            "required_inputs": ["ROOT210 typed records path/SHA/stat and exact case proof", "existing PartOut.csv and RunPARTs.csv paths/SHA/stat", "CURRENT/source/report edges above"],
        })
    raw = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    if len(raw) > MAX_OUTPUT_BYTES:
        raise SourceGapError(f"source gap output exceeds cap: {len(raw)}")
    # A file cannot contain its own final digest.  Keep the digest of the
    # canonical body for reproducibility; the CLI also prints the full file
    # SHA after serializing this object.
    output["content_sha256_without_self_digest"] = hashlib.sha256(raw).hexdigest()
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--root210-proof", type=Path)
    parser.add_argument("--root210-summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = build(args)
        output = args.output.expanduser().resolve()
        if output.exists() or output.is_symlink():
            raise SourceGapError(f"refusing to overwrite immutable output: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
        with output.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"status": value["status"], "output": str(output), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "launch_allowed": False}, sort_keys=True))
        return 0
    except (SourceGapError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
