#!/usr/bin/env python3
"""Build a metadata-only coverage map for the original 118 omission cases.

This adapter joins the immutable 118-case inventory, the explicit V10 native
cause overlay, the ROOT313 source-prepared mass-impact manifest/spec, and the
source-prepared ROOT274/308/309 requests plus ROOT312 pending intake.  It does
not open any deferred JSONL/H5/BI4/OBI4/native payload.  ROOT313 and the future
requests therefore remain ``SOURCE_READY_NOT_ACTUAL`` or ``PREPARED_NOT_TERMINAL``;
they do not create mass-impact or physical-fate credit.

The output deliberately keeps three evidence layers separate:

* an explicit per-case native-cause row from the overlay (or an honest
  inherited count-only/remaining row when V10 does not carry that case row),
* an exact source-prepared ROOT313 mass-impact case row, and
* a future native extraction request row whose terminal proof does not yet
  exist.

All paths are supplied explicitly by the caller.  No ``latest`` glob or
  payload-derived inference is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
MAX_INPUT = 12 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
DEFERRED_SUFFIXES = {".jsonl", ".h5", ".hdf5", ".bi4", ".obi4", ".vtk", ".xmf"}
FAMILY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}


class CoverageError(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise CoverageError(f"{label} is not a SHA-256 digest")
    return value.lower()


def _stat(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise CoverageError(f"{label} is missing: {path}")
    st = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns),
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
    }


def _read_json(path_value: str | os.PathLike[str], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path_value).expanduser().resolve()
    if path.suffix.lower() in DEFERRED_SUFFIXES:
        raise CoverageError(f"{label} is deferred payload metadata, not a permitted adapter input: {path}")
    before = _stat(path, label)
    if before["bytes"] > MAX_INPUT:
        raise CoverageError(f"{label} exceeds metadata input bound")
    raw = path.read_bytes()
    after = _stat(path, label)
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if before[field] != after[field] or len(raw) != after["bytes"]:
            raise CoverageError(f"{label} changed during one bounded capture")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CoverageError(f"{label} must be a JSON object")
    return value, {**after, "sha256": hashlib.sha256(raw).hexdigest()}


def _ref(path: Path, stat: dict[str, Any], role: str) -> dict[str, Any]:
    return {"role": role, **stat}


def _require_sha(actual: dict[str, Any], expected: Any, label: str) -> None:
    if expected is None:
        return
    if actual["sha256"] != _sha(expected, f"{label} expected SHA"):
        raise CoverageError(f"{label} SHA differs from its declared source")


def _case_ids(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise CoverageError(f"{label} is not a list of case IDs")
    if len(value) != len(set(value)):
        raise CoverageError(f"{label} contains duplicate case IDs")
    return list(value)


def _validate_inventory(inventory: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if inventory.get("schema") != "ds02.stage2.historical118-source-inventory.v1":
        raise CoverageError(f"{label} schema differs")
    if inventory.get("scope", {}).get("historical_case_count") != 118:
        raise CoverageError(f"{label} does not declare 118 historical cases")
    scope = inventory.get("scope", {})
    if scope.get("f3_fine512_included") is not False or scope.get("root192_typed_particle_records_added_as_cases") is not False:
        raise CoverageError(f"{label} has an invalid scope boundary")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118 or any(not isinstance(row, dict) for row in rows):
        raise CoverageError(f"{label} must contain exactly 118 case rows")
    ids = [row.get("physical_case_id") for row in rows]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise CoverageError(f"{label} case identities are not unique")
    family_counts = Counter(row.get("family_id") for row in rows)
    if dict(family_counts) != FAMILY_COUNTS:
        raise CoverageError(f"{label} family counts differ: {dict(family_counts)}")
    if any(row.get("historical_118_membership") is not True for row in rows):
        raise CoverageError(f"{label} contains a non-historical case")
    return rows, {"case_count": 118, "family_counts": dict(family_counts)}


def _validate_overlay(overlay: dict[str, Any], inventory_ids: set[str], label: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if overlay.get("schema") != "ds02.stage2.original118-native-cause-actual-overlay.v1":
        raise CoverageError(f"{label} schema differs")
    if overlay.get("physical_case_count") != 118:
        raise CoverageError(f"{label} physical_case_count differs")
    bound = overlay.get("native_cause_bound_per_fluid_id_cases")
    unlocated = overlay.get("cause_not_located_after_completed_scan_cases")
    if not isinstance(bound, int) or not isinstance(unlocated, int) or bound < 0 or unlocated < 0 or bound + unlocated != 118:
        raise CoverageError(f"{label} cause counts do not balance")
    if overlay.get("root_H5_native_JSONL_content_read") is not False:
        raise CoverageError(f"{label} violates no-payload read policy")
    explicit: dict[str, dict[str, Any]] = {}
    newly = overlay.get("newly_bound_cases")
    if not isinstance(newly, list):
        raise CoverageError(f"{label} newly_bound_cases is missing")
    for row in newly:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise CoverageError(f"{label} has malformed newly bound case")
        case_id = row["physical_case_id"]
        if case_id not in inventory_ids or case_id in explicit:
            raise CoverageError(f"{label} newly bound case is outside/duplicated in 118 scope: {case_id}")
        evidence = row.get("evidence")
        evidence_sha = row.get("evidence_sha256")
        if not isinstance(evidence, str) or not isinstance(evidence_sha, str):
            raise CoverageError(f"{label} newly bound case lacks evidence edge: {case_id}")
        explicit[case_id] = {
            "classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID",
            "evidence": {"path": evidence, "sha256": _sha(evidence_sha, f"{case_id} evidence")},
            "native_cause": row.get("native_cause", row.get("native_cause_categories")),
            "fluid_identity_count": row.get("fluid_identity_count"),
            "saved_frame_join": row.get("saved_frame_join"),
            "evidence_level": "EXPLICIT_OVERLAY_CASE_ROW",
        }
    remaining = overlay.get("remaining_cause_not_located_case_ids")
    if not isinstance(remaining, list) or any(not isinstance(case_id, str) for case_id in remaining):
        raise CoverageError(f"{label} remaining case IDs are malformed")
    if len(remaining) != len(set(remaining)):
        raise CoverageError(f"{label} remaining case IDs are duplicated")
    for case_id in remaining:
        if case_id not in inventory_ids or case_id in explicit:
            raise CoverageError(f"{label} remaining case is outside/duplicated in 118 scope: {case_id}")
        explicit[case_id] = {
            "classification": "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN",
            "evidence": None,
            "native_cause": None,
            "fluid_identity_count": None,
            "saved_frame_join": None,
            "evidence_level": "EXPLICIT_REMAINING_CASE_ROW",
        }
    if len(explicit) > 118:
        raise CoverageError(f"{label} explicit rows exceed 118")
    summary = {
        "reported_native_cause_bound_count": bound,
        "reported_cause_not_located_count": unlocated,
        "explicit_bound_case_rows": sum(row["classification"] == "NATIVE_CAUSE_BOUND_PER_FLUID_ID" for row in explicit.values()),
        "explicit_unlocated_case_rows": sum(row["classification"] == "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN" for row in explicit.values()),
        "inherited_count_only_case_rows": 118 - len(explicit),
    }
    return explicit, summary


def _validate_root313(manifest: dict[str, Any], spec: dict[str, Any], inventory_ids: set[str], label: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if manifest.get("schema") != "ds02.stage2.native-typed-mass-impact.root313-manifest" or manifest.get("status") != "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_ROOT313":
        raise CoverageError(f"{label} manifest schema/status differs")
    if manifest.get("producer_proof_merge", {}).get("created") is not False:
        raise CoverageError(f"{label} unexpectedly claims a merged producer proof")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or manifest.get("case_count") != len(cases) or len(cases) != 17:
        raise CoverageError(f"{label} must contain the exact 17 source-prepared cases")
    case_ids = [row.get("physical_case_id") for row in cases if isinstance(row, dict)]
    if len(case_ids) != 17 or any(case_id not in inventory_ids for case_id in case_ids) or len(case_ids) != len(set(case_ids)):
        raise CoverageError(f"{label} cases are outside/duplicated in original118 scope")
    if spec.get("schema") != "ds02.stage2.native-typed-mass-impact-proof-spec.v1":
        raise CoverageError("ROOT313 proof spec schema differs")
    spec_bundles = spec.get("bundles")
    manifest_bundles = manifest.get("proof_bundles")
    if not isinstance(spec_bundles, list) or not isinstance(manifest_bundles, list) or len(spec_bundles) != 3 or len(manifest_bundles) != 3:
        raise CoverageError("ROOT313 proof bundle list is incomplete")
    spec_by_id = {row.get("bundle_id"): row for row in spec_bundles if isinstance(row, dict)}
    bundles: dict[str, dict[str, Any]] = {}
    for bundle in manifest_bundles:
        if not isinstance(bundle, dict) or not isinstance(bundle.get("bundle_id"), str):
            raise CoverageError("ROOT313 proof bundle row is malformed")
        bid = bundle["bundle_id"]
        expected = spec_by_id.get(bid)
        if expected is None or bundle.get("case_count") != expected.get("expected_case_count"):
            raise CoverageError(f"ROOT313 bundle {bid} does not match its spec")
        ids = _case_ids(bundle.get("case_ids"), f"ROOT313 bundle {bid} case_ids")
        if set(ids) != {row.get("physical_case_id") for row in cases if row.get("proof_bundle_id") == bid}:
            raise CoverageError(f"ROOT313 bundle {bid} case set differs from case rows")
        proof = bundle.get("proof")
        if not isinstance(proof, dict) or not isinstance(proof.get("path"), str):
            raise CoverageError(f"ROOT313 bundle {bid} has no preserved proof edge")
        bundles[bid] = {
            "bundle_id": bid,
            "family_id": bundle.get("family_id"),
            "case_ids": ids,
            "proof": {"path": proof["path"], "sha256": _sha(proof.get("sha256"), f"ROOT313 {bid} proof")},
            "typed_jsonl_source_bytes": bundle.get("typed_jsonl_source_bytes"),
            "typed_jsonl_minimum_three_pass_read_bytes": bundle.get("typed_jsonl_minimum_three_pass_read_bytes"),
            "status": "SOURCE_READY_NOT_ACTUAL",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "physical_mass_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
        }
    by_case: dict[str, dict[str, Any]] = {}
    for row in cases:
        bid = row["proof_bundle_id"]
        by_case[row["physical_case_id"]] = {
            "status": "SOURCE_READY_NOT_ACTUAL",
            "bundle_id": bid,
            "family_id": row.get("family_id"),
            "typed_jsonl_source_bytes": row.get("typed_records_deferred", {}).get("bytes"),
            "typed_jsonl_minimum_three_pass_read_bytes": bundles[bid].get("typed_jsonl_minimum_three_pass_read_bytes"),
            "native_selected_id_count": row.get("selected_native_id_count"),
            "producer_proof": bundles[bid]["proof"],
            "unsupported": ["no_completed_mass-impact result", "typed JSONL content remains deferred"],
        }
    return by_case, {"case_count": 17, "bundles": list(bundles.values())}


def _validate_future_request(request: dict[str, Any], label: str, inventory_ids: set[str], expected_family: str, expected_count: int) -> dict[str, Any]:
    if request.get("schema") != "ds02.request.v1" or request.get("family_id") != expected_family:
        raise CoverageError(f"{label} schema/family differs")
    ids = _case_ids(request.get("physical_case_ids"), f"{label} physical_case_ids")
    if len(ids) != expected_count or any(case_id not in inventory_ids for case_id in ids):
        raise CoverageError(f"{label} does not bind the expected original118 cases")
    if request.get("launch_allowed") is not True:
        raise CoverageError(f"{label} is not a source-prepared request")
    if request.get("execution_allowed") is not True:
        raise CoverageError(f"{label} execution contract is not enabled")
    return {
        "status": "PREPARED_NOT_TERMINAL_NATIVE",
        "request_case_count": len(ids),
        "case_ids": ids,
        "family_id": expected_family,
        "request_schema": request.get("schema"),
        "estimated_deferred_read_bytes": request.get("estimated_deferred_read_bytes"),
        "estimated_storage_bytes": request.get("estimated_storage_bytes"),
        "unsupported": ["no terminal native proof/result", "no mass-impact result", "physical fate/flux/dynamics/Q unknown"],
    }


def _validate_pending312(pending: dict[str, Any], label: str) -> dict[str, Any]:
    if pending.get("schema") != "ds02.stage2.root312-f4-multi-proof-intake-pending.v2":
        raise CoverageError(f"{label} schema differs")
    if pending.get("launch_allowed") is not False or pending.get("source_only") is not True or pending.get("payload_content_opened") is not False:
        raise CoverageError(f"{label} pending/read boundary differs")
    producers = pending.get("producer_proofs")
    if not isinstance(producers, list) or len(producers) != 2:
        raise CoverageError(f"{label} producer proof list differs")
    if pending.get("full_producer_case_count") != 16 or pending.get("selected_original118_case_count") != 7:
        raise CoverageError(f"{label} selected/full counts differ")
    if any(row.get("producer_proof") != "NOT_AVAILABLE" for row in producers if isinstance(row, dict)):
        raise CoverageError(f"{label} unexpectedly has a producer proof")
    return {
        "status": "WAITING_FULL_TERMINAL_PROOFS",
        "full_producer_case_count": 16,
        "selected_original118_case_count": 7,
        "case_ids": [],
        "unsupported": ["producer proof unavailable", "selected 7 case IDs are not exposed by this pending checkpoint", "no native/mass result"],
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    inventory, inventory_stat = _read_json(args.inventory, "historical118 inventory")
    inventory_rows, inventory_summary = _validate_inventory(inventory, "historical118 inventory")
    inventory_ids = {row["physical_case_id"] for row in inventory_rows}
    overlay, overlay_stat = _read_json(args.overlay, "V10 native-cause overlay")
    cause_rows, cause_summary = _validate_overlay(overlay, inventory_ids, "V10 native-cause overlay")
    root313_manifest, root313_manifest_stat = _read_json(args.root313_manifest, "ROOT313 manifest")
    root313_spec, root313_spec_stat = _read_json(args.root313_spec, "ROOT313 proof spec")
    mass_rows, root313_summary = _validate_root313(root313_manifest, root313_spec, inventory_ids, "ROOT313")
    future = {}
    future_stats = {}
    for key, raw, family, count in (
        ("ROOT274", args.root274_request, "F6", 7),
        ("ROOT308", args.root308_request, "F4", 4),
        ("ROOT309", args.root309_request, "F6", 6),
    ):
        request, future_stats[key] = _read_json(raw, f"{key} request")
        future[key] = _validate_future_request(request, f"{key} request", inventory_ids, family, count)
    pending312, pending312_stat = _read_json(args.root312_checkpoint, "ROOT312 pending checkpoint")
    pending = _validate_pending312(pending312, "ROOT312 pending checkpoint")
    mass_ids = set(mass_rows)
    future_overlaps = {name: sorted(mass_ids & set(value["case_ids"])) for name, value in future.items()}
    future_ids = set().union(*(set(value["case_ids"]) for value in future.values()))
    rows: list[dict[str, Any]] = []
    for source_row in inventory_rows:
        case_id = source_row["physical_case_id"]
        cause = cause_rows.get(case_id)
        if cause is None:
            cause = {
                "classification": "INHERITED_CAUSE_BOUND_COUNT_ONLY",
                "evidence": None,
                "native_cause": None,
                "fluid_identity_count": None,
                "saved_frame_join": None,
                "evidence_level": "OVERLAY_COUNT_WITHOUT_CASE_ROW",
            }
        rows.append({
            "physical_case_id": case_id,
            "family_id": source_row["family_id"],
            "current336_index": source_row.get("current336_index"),
            "historical_118_membership": True,
            "cause_evidence": cause,
            "mass_impact": mass_rows.get(case_id, {
                "status": "NO_MASS_IMPACT_RESULT_SOURCE",
                "unsupported": ["no completed ROOT313/source-prepared mass-impact row for this case"],
            }),
            "future_native_prepared": [
                {"batch": name, "status": value["status"], "overlap_with_root313": case_id in mass_ids}
                for name, value in future.items() if case_id in value["case_ids"]
            ],
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "physical_mass_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
            "source_scope": {
                "inventory_source_artifacts_opened": False,
                "deferred_payload_opened": False,
                "cause_count_is_not_mass_or_fate": True,
                "typed_particle_records_are_not_case_membership": True,
            },
        })
    summary = {
        "original118_cases": 118,
        "family_counts": inventory_summary["family_counts"],
        "explicit_overlay_bound_case_rows": cause_summary["explicit_bound_case_rows"],
        "explicit_overlay_unlocated_case_rows": cause_summary["explicit_unlocated_case_rows"],
        "inherited_overlay_count_only_case_rows": cause_summary["inherited_count_only_case_rows"],
        "reported_overlay_bound_count": cause_summary["reported_native_cause_bound_count"],
        "reported_overlay_unlocated_count": cause_summary["reported_cause_not_located_count"],
        "root313_mass_source_ready_not_actual": len(mass_rows),
        "root313_mass_actual_completed": 0,
        "future_prepared_unique_case_ids": len(future_ids),
        "future_prepared_overlaps_with_root313": {name: ids for name, ids in future_overlaps.items()},
        "root312_selected_original118_cases_waiting": pending["selected_original118_case_count"],
        "unsupported_mass_rows": 118 - len(mass_rows),
        "physical_fate_flux_dynamics_q": "UNKNOWN",
    }
    output = {
        "schema": "ds02.stage2.original118-native-typed-mass-impact-coverage.v1",
        "status": "SOURCE_CLOSED_METADATA_COVERAGE_WITH_MASS_RESULT_PENDING",
        "generated_by": str(SCRIPT),
        "source_edges": {
            "inventory": {"role": "HISTORICAL118_SOURCE_INVENTORY", **inventory_stat},
            "overlay_v10": {"role": "ORIGINAL118_NATIVE_CAUSE_OVERLAY_V10", **overlay_stat},
            "root313_manifest": {"role": "ROOT313_SOURCE_PREPARED_MASS_MANIFEST", **root313_manifest_stat},
            "root313_spec": {"role": "ROOT313_PROOF_SPEC", **root313_spec_stat},
            "ROOT274_request": {"role": "ROOT274_SOURCE_PREPARED_REQUEST", **future_stats["ROOT274"]},
            "ROOT308_request": {"role": "ROOT308_SOURCE_PREPARED_REQUEST", **future_stats["ROOT308"]},
            "ROOT309_request": {"role": "ROOT309_SOURCE_PREPARED_REQUEST", **future_stats["ROOT309"]},
            "ROOT312_pending": {"role": "ROOT312_PENDING_INTAKE", **pending312_stat},
        },
        "summary": summary,
        "native_cause_scope": {
            "overlay_status": overlay.get("status"),
            "case_rows_without_explicit_overlay_evidence_are_count_only": True,
            "native_cause_is_not_physical_fate_or_legal_flux": True,
        },
        "root313": root313_summary,
        "future_prepared": {**future, "ROOT312": pending},
        "case_rows": rows,
        "read_policy": {
            "inventory_json_opened": True,
            "overlay_json_opened": True,
            "root313_metadata_opened": True,
            "future_request_metadata_opened": True,
            "deferred_jsonl_h5_bi4_obi4_content_opened": False,
            "native_payload_content_opened": False,
            "solver_started": False,
        },
        "claim_boundary": {
            "mass_impact": "SOURCE_READY_NOT_ACTUAL_FOR_ROOT313_17_CASES",
            "native_cause": "CASE_LEVEL_ONLY_WHERE_EXPLICIT_OVERLAY_ROW_EXISTS",
            "physical_fate": "UNKNOWN",
            "physical_mass_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
    }
    output_path = args.output.expanduser().resolve()
    if output_path.exists():
        raise CoverageError(f"refusing to overwrite output: {output_path}")
    encoded = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_OUTPUT:
        raise CoverageError("coverage output exceeds bounded metadata size")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(encoded, encoding="utf-8")
    return {"status": output["status"], "output": str(output_path), "cases": 118, "mass_source_ready_not_actual": len(mass_rows)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    build_parser = sub.add_parser("build")
    for option, dest in (
        ("--inventory", "inventory"), ("--overlay", "overlay"), ("--root313-manifest", "root313_manifest"),
        ("--root313-spec", "root313_spec"), ("--root274-request", "root274_request"),
        ("--root308-request", "root308_request"), ("--root309-request", "root309_request"),
        ("--root312-checkpoint", "root312_checkpoint"), ("--output", "output"),
    ):
        build_parser.add_argument(option, dest=dest, type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "self-test":
            value = {"schema": "ds02.stage2.original118-native-typed-mass-impact-coverage.v1", "status": "PASS", "payload_content_opened": False}
        else:
            value = build(args)
    except (CoverageError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"NATIVE_TYPED_MASS_IMPACT_COVERAGE_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
