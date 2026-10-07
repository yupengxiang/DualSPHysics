#!/usr/bin/env python3
"""Build a source-bound index for the historical F2/F4/F6 omission registry.

This is a forward-only metadata audit.  It reads CURRENT336, the immutable
Stage 1 lifecycle proof, completed scientific-scan JSON/receipts, and already
consumed native sidecars.  It never opens trajectory HDF5 and never reruns a
scan or a decoder.  The output deliberately separates:

* the 118 historical membership rows (48 F2 + 22 F4 + 48 F6);
* an exact current physical identity/conversion/trajectory mapping;
* native cause evidence that is actually joined to the current scan; and
* F4 zero-missing controls, which are not members of the historical 118.

The historical review did not claim a conversion, type-count, or recovery
lineage cause.  A completed current scan without a native join therefore
remains UNKNOWN for that attribution.  A native numerical exclusion is also
kept separate from physical fate, dynamics, QN, and QE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


class CoverageError(RuntimeError):
    """Raised when a claimed source binding cannot be proven."""


FAMILIES = ("F2", "F4", "F6")
EXPECTED_LEGACY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
EXPECTED_CURRENT_COUNTS = {"F2": 48, "F4": 48, "F6": 48}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    path = Path(path)
    if not path.is_file():
        raise CoverageError(f"{label} is missing: {path}")
    return path


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(path, label)
    try:
        value = json.loads(path.read_text())
    except Exception as exc:  # pragma: no cover - useful receipt failure text
        raise CoverageError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CoverageError(f"{label} is not a JSON object: {path}")
    return path, value


def file_ref(path: str | Path, *, expected_sha256: str | None = None,
             label: str = "evidence") -> dict[str, Any]:
    path = Path(path)
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        result["sha256"] = None
        if expected_sha256:
            result["expected_sha256"] = expected_sha256
            result["hash_matches_expected"] = False
        return result
    actual = sha256(path)
    result.update({"sha256": actual, "bytes": path.stat().st_size})
    if expected_sha256:
        result["expected_sha256"] = expected_sha256
        result["hash_matches_expected"] = actual == expected_sha256
        if actual != expected_sha256:
            raise CoverageError(
                f"{label} hash differs from its declared binding: {path}")
    return result


def canonical(path: str | Path) -> str:
    return str(Path(path).resolve(strict=False))


def load_source(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def git_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True)
        return result.stdout.strip()
    except Exception:
        return None


def scan_inventory(data_root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    by_id: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for family in FAMILIES:
        # F2-S1 is a separate completed scan lineage for the exact CURRENT
        # case RX056/ROT090; the regular 048..095 batch intentionally lacks
        # that number.  Include both stage2 science roots.
        pattern = f"families/{family}/STAGE2*SCIENCE/**/scientific-scan.json"
        for path in sorted(data_root.glob(pattern)):
            _, scan = read_json(path, "scientific scan")
            if scan.get("family_id") != family:
                raise CoverageError(f"scan family mismatch: {path}")
            physical_id = scan.get("physical_case_id")
            if not physical_id:
                raise CoverageError(f"scan has no physical_case_id: {path}")
            by_id.setdefault(physical_id, []).append((path, scan))
    return by_id


def scan_receipt(scan_path: Path) -> tuple[Path, dict[str, Any]]:
    receipt_path = require_file(scan_path.parent / "execution-receipt.json",
                                "scientific scan execution receipt")
    receipt = load_source(receipt_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise CoverageError(f"scientific scan receipt is not completed: {receipt_path}")
    return receipt_path, receipt


def fluid_summary(scan: dict[str, Any]) -> dict[str, Any]:
    ledger = scan.get("type_ledgers", {}).get("fluid")
    if not isinstance(ledger, dict):
        raise CoverageError("scientific scan has no fluid type ledger")
    records = scan.get("missing_id_records", [])
    first = min((int(row["first_missing_frame"]) for row in records),
                default=None)
    return {
        "typed_initial_count": ledger.get("typed_initial_count"),
        "typed_initial_mass_kg": ledger.get("typed_initial_mass_kg"),
        "cumulative_unique_missing": ledger.get("cumulative_unique_missing"),
        "missing_at_final": ledger.get("missing_at_final"),
        "maximum_instantaneous_missing": ledger.get("maximum_instantaneous_missing"),
        "missing_particle_frames": ledger.get("missing_particle_frames"),
        "first_missing_frame": first,
        "missing_record_count": len(records),
    }


def scan_evidence(current: dict[str, Any], scan_path: Path,
                  scan: dict[str, Any]) -> dict[str, Any]:
    receipt_path, receipt = scan_receipt(scan_path)
    trajectory = current["trajectory"]
    current_trajectory_path = str(trajectory["path"])
    scan_trajectory_path = str(scan.get("trajectory", ""))
    if scan_trajectory_path != current_trajectory_path:
        raise CoverageError(
            f"scan trajectory differs from CURRENT for {current['physical_case_id']}")
    if int(scan.get("source_bytes", -1)) != int(trajectory["bytes"]):
        raise CoverageError(
            f"scan source bytes differ from CURRENT for {current['physical_case_id']}")

    request = receipt.get("request", {})
    input_sha = request.get("input_sha256", {})
    launch_sha = receipt.get("input_hashes_at_launch", {})
    end_sha = receipt.get("input_hashes_after_run", {})
    declared_sha = trajectory.get("producer_declared_sha256")
    observed = {
        "request_input_sha256": input_sha.get(current_trajectory_path),
        "launch_input_sha256": launch_sha.get(current_trajectory_path),
        "end_input_sha256": end_sha.get(current_trajectory_path),
        "current_producer_declared_sha256": declared_sha,
    }
    observed_values = [observed[k] for k in (
        "request_input_sha256", "launch_input_sha256", "end_input_sha256")]
    hash_stable = bool(declared_sha) and all(value == declared_sha
                                             for value in observed_values)
    if not hash_stable:
        raise CoverageError(
            f"scan launch/end trajectory hashes do not close for {current['physical_case_id']}")
    return {
        "scientific_scan": file_ref(scan_path, label="scientific scan"),
        "execution_receipt": file_ref(receipt_path, label="scientific scan receipt"),
        "schema": scan.get("schema"),
        "scan_status": scan.get("scan_status"),
        "trajectory_path": scan_trajectory_path,
        "trajectory_path_matches_current": True,
        "source_bytes": scan.get("source_bytes"),
        "source_bytes_matches_current": True,
        "trajectory_sha256_observation": observed,
        "trajectory_sha256_stable": True,
        "full_saved_timeline_scanned": scan.get("full_saved_timeline_scanned"),
        "frames": scan.get("frames"),
        "time_window_s": [scan.get("time_s", [None])[0],
                          scan.get("time_s", [None])[-1]],
        "fluid": fluid_summary(scan),
    }


def ids_from_scan(scan: dict[str, Any]) -> set[tuple[int, int]]:
    return {(int(row["zone"]), int(row["idp"]))
            for row in scan.get("missing_id_records", [])}


def native_sidecar_inventory(data_root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    by_id: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for family in FAMILIES:
        for path in sorted(data_root.glob(
                f"families/{family}/STAGE2_OMISSION_*/**/omission-forensics.json")):
            _, sidecar = read_json(path, "native omission sidecar")
            physical_id = sidecar.get("physical_case_id")
            if physical_id:
                by_id.setdefault(physical_id, []).append((path, sidecar))
    # F2-S1 predates the omission-forensics schema but is the exact native
    # join for the CURRENT RX056/ROT090 case.  Keep it as a separately
    # qualified, source-bound legacy join.
    s1 = data_root / "families/F2/STAGE2_F2_S1_EXCLUSIONS/join-F2-S1-001/native-reconciliation.json"
    if s1.is_file():
        _, sidecar = read_json(s1, "F2-S1 native reconciliation")
        by_id.setdefault(sidecar.get("physical_case_id"), []).append((s1, sidecar))
    return by_id


def native_evidence(current: dict[str, Any], scan_path: Path,
                    scan: dict[str, Any], candidates: list[tuple[Path, dict[str, Any]]]
                    ) -> dict[str, Any]:
    if len(candidates) > 1:
        # A duplicate sidecar is not allowed to silently choose another run.
        raise CoverageError(
            f"multiple native sidecars for {current['physical_case_id']}: "
            f"{[str(path) for path, _ in candidates]}")
    if not candidates:
        return {
            "status": "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN",
            "evidence": None,
            "history_cause": "UNKNOWN",
            "history_cause_explanation": (
                "The current scan is complete, but no source-bound native join "
                "distinguishes conversion filtering, type miscount, recovery "
                "lineage replacement, or another cause."),
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        }

    sidecar_path, sidecar = candidates[0]
    sidecar_ref = file_ref(sidecar_path, label="native omission sidecar")
    scan_ids = ids_from_scan(scan)
    schema = str(sidecar.get("schema", ""))
    is_s1 = schema == "ds02.stage2.native-exclusion-reconciliation.v1"
    if sidecar.get("physical_case_id") != current["physical_case_id"]:
        raise CoverageError(f"native sidecar identity differs: {sidecar_path}")

    if is_s1:
        # The old F2-S1 join did not copy source paths into its JSON.  Its
        # completed execution receipt is the binding source and contains the
        # scan/PartOut/RunPARTs command plus input hashes.
        receipt_path = require_file(sidecar_path.parent / "execution-receipt.json",
                                    "F2-S1 native join receipt")
        receipt = load_source(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise CoverageError(f"F2-S1 native join receipt is not completed: {receipt_path}")
        command = receipt.get("command", [])
        scan_arg = command[command.index("--scan") + 1] if "--scan" in command else ""
        if canonical(scan_arg) != canonical(scan_path):
            raise CoverageError(f"F2-S1 native join scan differs: {receipt_path}")
        joined = {(int(row["zone"]), int(row["idp"]))
                  for row in sidecar.get("missing_fluid_ids", [])}
        if joined != scan_ids:
            raise CoverageError(f"F2-S1 native IDs differ from scan: {sidecar_path}")
        totals = sidecar.get("runparts_totals", {})
        return {
            "status": "NATIVE_CAUSE_RECONCILED",
            "schema": schema,
            "evidence": sidecar_ref,
            "receipt": file_ref(receipt_path, label="F2-S1 native join receipt"),
            "source_provenance_qualification": (
                "legacy join receipt binding; sidecar has no copied conversion/native "
                "source_provenance object"),
            "joined_count": sidecar.get("joined_count"),
            "native_motive_counts": sidecar.get("native_motive_counts", {}),
            "runparts_totals": totals,
            "ids_match_scan": True,
            "history_cause": "NATIVE_NUMERICAL_EXCLUSION_RECONCILED",
            "history_cause_explanation": (
                "Completed native join records numerical position exclusion for the "
                "same current scan identity; physical fate remains UNKNOWN."),
            "physical_fate": sidecar.get("physical_fate", "UNKNOWN"),
            "dynamical_impact": sidecar.get("dynamical_impact", "UNKNOWN"),
            "QN": sidecar.get("QN", "NOT_ASSESSED"),
            "QE": sidecar.get("QE", "NOT_ASSESSED"),
        }

    if sidecar.get("status") != "CAUSES_RECONCILED":
        raise CoverageError(f"native sidecar is not CAUSES_RECONCILED: {sidecar_path}")
    bound_scan = sidecar.get("scan", {})
    if bound_scan.get("path") != str(scan_path):
        raise CoverageError(f"native sidecar scan path differs: {sidecar_path}")
    if bound_scan.get("sha256") != sidecar_ref_for_scan(scan_path):
        raise CoverageError(f"native sidecar scan hash differs: {sidecar_path}")
    trajectory = current["trajectory"]
    bound_trajectory = sidecar.get("trajectory", {})
    if bound_trajectory.get("path") != trajectory.get("path"):
        raise CoverageError(f"native sidecar trajectory path differs: {sidecar_path}")
    if bound_trajectory.get("sha256") != trajectory.get("producer_declared_sha256"):
        raise CoverageError(f"native sidecar trajectory hash differs: {sidecar_path}")
    typed = sidecar.get("typed_identity", {})
    typed_ids = {(int(row["zone"]), int(row["idp"]))
                 for row in typed.get("ids", [])}
    if typed_ids != scan_ids:
        raise CoverageError(f"native sidecar typed IDs differ from scan: {sidecar_path}")
    native_decode = sidecar.get("native_decode", {})
    receipt_obj = native_decode.get("receipt", {})
    receipt_path_value = receipt_obj.get("path") if isinstance(receipt_obj, dict) else receipt_obj
    native_receipt_path = require_file(receipt_path_value, "native decoder receipt")
    native_receipt = load_source(native_receipt_path)
    if native_receipt.get("status") != "completed" or native_receipt.get("returncode") != 0:
        raise CoverageError(f"native decoder receipt is not completed: {native_receipt_path}")
    if native_receipt.get("output_root") and Path(native_receipt["output_root"]).resolve() != native_receipt_path.parent.resolve():
        raise CoverageError(f"native decoder receipt output root differs: {native_receipt_path}")
    totals = native_decode.get("runparts_totals", {})
    return {
        "status": "NATIVE_CAUSE_RECONCILED",
        "schema": schema,
        "evidence": sidecar_ref,
        "native_decoder_receipt": file_ref(native_receipt_path,
                                             expected_sha256=receipt_obj.get("sha256"),
                                             label="native decoder receipt"),
        "native_tool": native_decode.get("tool"),
        "native_binary": native_decode.get("binary"),
        "native_output_root": native_decode.get("output_root"),
        "joined_count": len(typed_ids),
        "native_motive_counts": totals,
        "runparts_totals": totals,
        "ids_match_scan": True,
        "history_cause": "NATIVE_NUMERICAL_EXCLUSION_RECONCILED",
        "history_cause_explanation": (
            "Completed official PartVTKOut/RunPARTs join matches every current "
            "missing fluid identity; this identifies a native numerical exclusion "
            "category, not physical spill or dynamics."),
        "physical_fate": sidecar.get("physical_fate", "UNKNOWN"),
        "dynamical_impact": sidecar.get("dynamical_impact", "UNKNOWN"),
        "QN": sidecar.get("QN", "NOT_ASSESSED"),
        "QE": sidecar.get("QE", "NOT_ASSESSED"),
    }


def sidecar_ref_for_scan(scan_path: Path) -> str:
    """Hash a scan JSON without opening the HDF5 named inside it."""
    return sha256(scan_path)


def impact_inventory(data_root: Path) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for family in FAMILIES:
        for path in sorted(data_root.glob(
                f"families/{family}/STAGE2_OMISSION_*/**/task-impact.json")):
            try:
                _, impact = read_json(path, "task impact sidecar")
            except CoverageError:
                continue
            physical_id = impact.get("physical_case_id")
            if not physical_id:
                continue
            by_id.setdefault(physical_id, []).append({
                "evidence": file_ref(path, label="task impact sidecar"),
                "schema": impact.get("schema"),
                "status": impact.get("status"),
                "uniform_mass_proven": impact.get("uniform_mass_proven"),
                "dynamics": impact.get("dynamical_impact", "UNKNOWN"),
            })
    return by_id


def f4_zero_inventory(data_root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    by_id: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path in sorted(data_root.glob(
            "families/F4/STAGE2_OMISSION_F4_*/**/no-native-exclusion.json")):
        _, sidecar = read_json(path, "F4 no-native sidecar")
        if sidecar.get("schema") != "ds02.stage2.no-native-exclusion-observed.v2":
            continue
        physical_id = sidecar.get("physical_case_id")
        if physical_id:
            by_id.setdefault(physical_id, []).append((path, sidecar))
    return by_id


def zero_native_evidence(current: dict[str, Any], scan_path: Path,
                         scan: dict[str, Any],
                         candidates: list[tuple[Path, dict[str, Any]]]
                         ) -> dict[str, Any]:
    if len(candidates) != 1:
        raise CoverageError(
            f"expected exactly one F4 v2 zero-native sidecar for "
            f"{current['physical_case_id']}, got {len(candidates)}")
    path, sidecar = candidates[0]
    if sidecar.get("status") != "NO_NATIVE_EXCLUSION_OBSERVED":
        raise CoverageError(f"F4 zero-native status mismatch: {path}")
    evidence = sidecar.get("evidence", {})
    scan_evidence_ref = evidence.get("scan", {})
    conversion_evidence_ref = evidence.get("conversion_report", {})
    if scan_evidence_ref.get("path") != str(scan_path):
        raise CoverageError(f"F4 zero-native scan path differs: {path}")
    if conversion_evidence_ref.get("path") != current["conversion_report"]["path"]:
        raise CoverageError(f"F4 zero-native conversion path differs: {path}")
    totals = sidecar.get("native", {}).get("runparts_totals", {})
    if any(int(totals.get(name, -1)) != 0
           for name in ("NpOut", "NpOutMov", "NpOutPos", "NpOutRho")):
        raise CoverageError(f"F4 zero-native RunPARTs totals are not zero: {path}")
    fluid = fluid_summary(scan)
    if fluid["cumulative_unique_missing"] != 0 or fluid["missing_at_final"] != 0:
        raise CoverageError(f"F4 zero-native scan has missing fluid: {path}")
    return {
        "status": "NO_NATIVE_EXCLUSION_OBSERVED",
        "evidence": file_ref(path, label="F4 no-native sidecar"),
        "scan_path": str(scan_path),
        "scan_sha256": sha256(scan_path),
        "conversion_report": file_ref(current["conversion_report"]["path"],
                                       expected_sha256=current["conversion_report"].get("recomputed_sha256"),
                                       label="F4 conversion report"),
        "runparts_totals": totals,
        "fluid_missing_unique": fluid["cumulative_unique_missing"],
        "partout_required": sidecar.get("native", {}).get("partout_required"),
        "partout_interpretation": sidecar.get("native", {}).get("raw_partout_interpretation"),
        "physical_fate": sidecar.get("physical_fate", "UNKNOWN"),
        "dynamical_impact": sidecar.get("dynamical_impact", "UNKNOWN"),
        "historical_118_membership": False,
        "interpretation": (
            "Current exact case has zero cumulative fluid omissions and zero "
            "RunPARTs native exclusions. It is a control observation and does "
            "not explain any historical 118 omission row or grant dynamics credit."),
    }


def make_index(current_path: Path, legacy_path: Path, family_summaries_path: Path,
               review_findings_path: Path, batch_draft_path: Path,
               data_root: Path) -> dict[str, Any]:
    current_file, current_doc = read_json(current_path, "CURRENT336")
    legacy_file, legacy_doc = read_json(legacy_path, "legacy lifecycle proof")
    family_file, family_doc = read_json(family_summaries_path, "FAMILY_SUMMARIES")
    review_file, review_doc = read_json(review_findings_path, "REVIEW_FINDINGS")
    batch_file, batch_doc = read_json(batch_draft_path, "BATCH_DRAFT_DIAGNOSTIC")
    cases = current_doc.get("cases", [])
    current_by_id = {row.get("physical_case_id"): row for row in cases}
    if len(current_by_id) != len(cases):
        raise CoverageError("CURRENT336 contains duplicate or missing physical_case_id")

    fluid_summaries = family_doc.get("fluid_omissions", {})
    old_rows = [row for row in legacy_doc.get("rows", [])
                if row.get("family_id") in FAMILIES and
                int(row.get("maximum_missing_fluid_at_any_frame", 0)) > 0]
    if len(old_rows) != sum(EXPECTED_LEGACY_COUNTS.values()):
        raise CoverageError(f"legacy omission row count is {len(old_rows)}, expected 118")
    old_by_id = {row.get("physical_case_id"): row for row in old_rows}
    if len(old_by_id) != len(old_rows):
        raise CoverageError("legacy omission rows contain duplicate physical IDs")
    for family, expected in EXPECTED_LEGACY_COUNTS.items():
        actual = sum(row.get("family_id") == family for row in old_rows)
        if actual != expected:
            raise CoverageError(f"legacy {family} count {actual} != {expected}")
        summary = fluid_summaries.get(family, {})
        if summary.get("cases_with_fluid_omissions") != expected:
            raise CoverageError(f"FAMILY_SUMMARIES {family} count differs")

    scans = scan_inventory(data_root)
    scan_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for physical_id, candidates in scans.items():
        if len(candidates) != 1:
            raise CoverageError(
                f"multiple current scans for exact physical ID {physical_id}: "
                f"{[str(path) for path, _ in candidates]}")
        scan_by_id[physical_id] = candidates[0]
    current_family_scan_counts = {family: 0 for family in FAMILIES}
    for physical_id, (_, scan) in scan_by_id.items():
        if physical_id in current_by_id and current_by_id[physical_id].get("family_id") in FAMILIES:
            current_family_scan_counts[current_by_id[physical_id]["family_id"]] += 1
    if current_family_scan_counts != EXPECTED_CURRENT_COUNTS:
        raise CoverageError(f"current completed scan counts differ: {current_family_scan_counts}")

    native = native_sidecar_inventory(data_root)
    impacts = impact_inventory(data_root)
    rows: list[dict[str, Any]] = []
    for legacy in sorted(old_rows, key=lambda row: (row["family_id"], row["physical_case_id"])):
        physical_id = legacy["physical_case_id"]
        current = current_by_id.get(physical_id)
        if current is None:
            raise CoverageError(f"legacy case is absent from CURRENT336: {physical_id}")
        if current.get("family_id") != legacy.get("family_id"):
            raise CoverageError(f"legacy/current family mismatch: {physical_id}")
        scan_pair = scan_by_id.get(physical_id)
        if scan_pair is None:
            raise CoverageError(f"legacy case has no completed current scan: {physical_id}")
        scan_path, scan = scan_pair
        scan_ref = scan_evidence(current, scan_path, scan)
        conversion_path = Path(current["conversion_report"]["path"])
        conversion_ref, conversion_doc = read_json(conversion_path, "current conversion report")
        conversion_hash = sha256(conversion_ref)
        declared_conversion_hash = current["conversion_report"].get("recomputed_sha256")
        if declared_conversion_hash and conversion_hash != declared_conversion_hash:
            raise CoverageError(f"CURRENT conversion report hash changed: {physical_id}")
        old_conversion = legacy.get("producer_conversion_report", {})
        conversion_path_exact = str(conversion_ref) == old_conversion.get("path")
        conversion_hash_exact = conversion_hash == old_conversion.get("sha256")
        trajectory_path_exact = scan.get("trajectory") == current["trajectory"]["path"]
        current_mapping = (
            "EXACT_CURRENT_PHYSICAL_ID_AND_CONVERSION_TRAJECTORY_HASH"
            if conversion_path_exact and conversion_hash_exact and trajectory_path_exact
            else "CURRENT_MAPPING_MISMATCH"
        )
        if current_mapping != "EXACT_CURRENT_PHYSICAL_ID_AND_CONVERSION_TRAJECTORY_HASH":
            raise CoverageError(f"legacy/current source mapping differs: {physical_id}")
        cause = native_evidence(current, scan_path, scan, native.get(physical_id, []))
        row = {
            "family_id": legacy["family_id"],
            "physical_case_id": physical_id,
            "historical_118_membership": True,
            "historical_membership_source": {
                "legacy_proof": file_ref(legacy_file, label="legacy lifecycle proof"),
                "legacy_row_max_missing_fluid": legacy["maximum_missing_fluid_at_any_frame"],
                "legacy_row_first_missing_frame": legacy["first_missing_frame"],
                "legacy_row_final_missing_fluid": legacy["final_missing_fluid"],
                "legacy_row_initial_fluid_particles": legacy["initial_fluid_particles"],
                "legacy_row_cumulative_particle_frame_omissions": legacy["cumulative_particle_frame_omissions"],
            },
            "current_identity": {
                "runtime_case_alias": current.get("runtime_case_alias"),
                "frames": current.get("frames"),
                "particles": current.get("particles"),
                "actual_time_window_s": current.get("actual_time_window_s"),
                "trajectory": {
                    "path": current["trajectory"]["path"],
                    "producer_declared_sha256": current["trajectory"].get("producer_declared_sha256"),
                    "bytes": current["trajectory"].get("bytes"),
                    "h5_opened_by_index": False,
                },
                "raw_root": current.get("raw_root", {}).get("path"),
                "conversion_report": file_ref(
                    conversion_ref,
                    expected_sha256=declared_conversion_hash,
                    label="current conversion report"),
                "legacy_conversion_path_exact": conversion_path_exact,
                "legacy_conversion_hash_exact": conversion_hash_exact,
                "mapping_status": current_mapping,
            },
            "current_scan": scan_ref,
            "cause": cause,
            "impact_evidence": impacts.get(physical_id, []),
            "history_reconciliation": {
                "conversion_filtering": (
                    "NOT_ESTABLISHED_BY_THIS_INDEX; current scan retains typed identity"),
                "type_miscount": (
                    "NOT_ESTABLISHED_BY_THIS_INDEX; typed scan/native ID join is separate from history"),
                "recovery_lineage_replacement": (
                    "NO_PATH_OR_HASH_REPLACEMENT_OBSERVED" if current_mapping.startswith("EXACT")
                    else "UNKNOWN"),
                "cause_credit_scope": (
                    "native numerical exclusion only" if cause["status"] == "NATIVE_CAUSE_RECONCILED"
                    else "UNKNOWN"),
                "physical_fate": cause.get("physical_fate", "UNKNOWN"),
                "dynamical_impact": cause.get("dynamical_impact", "UNKNOWN"),
                "QN": cause.get("QN", "NOT_ASSESSED"),
                "QE": cause.get("QE", "NOT_ASSESSED"),
            },
        }
        rows.append(row)

    zero_controls: list[dict[str, Any]] = []
    zero_by_id = f4_zero_inventory(data_root)
    for physical_id, candidates in sorted(zero_by_id.items()):
        current = current_by_id.get(physical_id)
        if current is None or current.get("family_id") != "F4":
            raise CoverageError(f"F4 zero-native case absent/mis-family in CURRENT: {physical_id}")
        if physical_id in old_by_id:
            raise CoverageError(f"F4 zero-native case overlaps historical 118: {physical_id}")
        scan_pair = scan_by_id.get(physical_id)
        if scan_pair is None:
            raise CoverageError(f"F4 zero-native case has no current scan: {physical_id}")
        scan_path, scan = scan_pair
        zero_controls.append({
            "family_id": "F4",
            "physical_case_id": physical_id,
            "current_identity": {
                "runtime_case_alias": current.get("runtime_case_alias"),
                "trajectory": {
                    "path": current["trajectory"]["path"],
                    "producer_declared_sha256": current["trajectory"].get("producer_declared_sha256"),
                    "bytes": current["trajectory"].get("bytes"),
                    "h5_opened_by_index": False,
                },
                "conversion_report": file_ref(
                    current["conversion_report"]["path"],
                    expected_sha256=current["conversion_report"].get("recomputed_sha256"),
                    label="F4 zero-native conversion report"),
            },
            "current_scan": scan_evidence(current, scan_path, scan),
            "zero_native": zero_native_evidence(
                current, scan_path, scan, candidates),
        })
    if len(zero_controls) != 26:
        raise CoverageError(f"F4 zero-native v2 controls count {len(zero_controls)} != 26")

    finding = next((item for item in review_doc.get("findings", [])
                    if item.get("title") == "118个案例有流体遗漏记录"), None)
    if finding is None:
        raise CoverageError("REVIEW_FINDINGS does not contain the 118 finding")

    cause_counts = {}
    for family in FAMILIES:
        subset = [row for row in rows if row["family_id"] == family]
        cause_counts[family] = {
            "historical_rows": len(subset),
            "native_cause_reconciled": sum(
                row["cause"]["status"] == "NATIVE_CAUSE_RECONCILED" for row in subset),
            "cause_not_located_after_completed_scan": sum(
                row["cause"]["status"] == "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN" for row in subset),
        }

    source_inputs = [
        file_ref(current_file, label="CURRENT336"),
        file_ref(legacy_file, label="legacy lifecycle proof"),
        file_ref(family_file, label="FAMILY_SUMMARIES"),
        file_ref(review_file, label="REVIEW_FINDINGS"),
        file_ref(batch_file, label="BATCH_DRAFT_DIAGNOSTIC"),
    ]
    return {
        "schema": "ds02.stage2.omission-coverage-index.v1",
        "purpose": (
            "Exact current identity and evidence coverage for the historical 118 "
            "F2/F4/F6 fluid omission cases; F4 zero-native controls are separate."),
        "generator": {
            "script": file_ref(Path(__file__), label="coverage index generator"),
            "git_commit": git_commit(),
            "trajectory_h5_opened": False,
            "scientific_scan_reexecuted": False,
            "native_decoder_reexecuted": False,
        },
        "historical_sources": {
            "review_findings": {
                **file_ref(review_file, label="REVIEW_FINDINGS"),
                "finding": finding,
            },
            "family_summaries": {
                **file_ref(family_file, label="FAMILY_SUMMARIES"),
                "fluid_omissions": fluid_summaries,
            },
            "legacy_lifecycle_proof": {
                **file_ref(legacy_file, label="legacy lifecycle proof"),
                "schema": legacy_doc.get("schema"),
                "membership_row_count": len(old_rows),
                "family_counts": EXPECTED_LEGACY_COUNTS,
            },
            "batch_draft_diagnostic": {
                **file_ref(batch_file, label="BATCH_DRAFT_DIAGNOSTIC"),
                "schema": batch_doc.get("schema"),
                "contains_case_id_registry": False,
                "interpretation": (
                    "Runtime PIPE backpressure diagnostic only; it is retained as "
                    "provenance and is not used to invent the 118 case membership."),
            },
        },
        "scope_counts": {
            "historical_118_rows": len(rows),
            "current_scans_by_family": current_family_scan_counts,
            "f4_zero_native_controls": len(zero_controls),
        },
        "cause_counts": cause_counts,
        "interpretation": {
            "exact_current_mapping": (
                "All 118 legacy rows map to the same CURRENT physical_case_id and "
                "the same conversion-report path/hash; no recovery-lineage path or "
                "hash replacement was observed in this registry."),
            "unresolved_history": (
                "For rows without a completed native join, conversion filtering, type "
                "miscount, and recovery-lineage replacement remain UNKNOWN even when "
                "the current scan is complete."),
            "native_scope": (
                "NATIVE_CAUSE_RECONCILED means the official native accounting identity "
                "matches the current missing IDs. Physical fate, bounded dynamics, "
                "QN, and QE remain UNKNOWN/NOT_ASSESSED."),
            "f4_zero_controls": (
                "The 26 F4 v2 zero-native controls are exact current cases outside "
                "the historical 118. Their zero observation does not explain the "
                "historical F4 omissions and grants no dynamics credit."),
        },
        "source_inputs": source_inputs,
        "rows": rows,
        "f4_zero_native_controls": zero_controls,
    }


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.",
                                     dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--legacy-proof", required=True, type=Path)
    parser.add_argument("--family-summaries", required=True, type=Path)
    parser.add_argument("--review-findings", required=True, type=Path)
    parser.add_argument("--batch-draft", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = make_index(
        args.current.resolve(), args.legacy_proof.resolve(),
        args.family_summaries.resolve(), args.review_findings.resolve(),
        args.batch_draft.resolve(), args.data_root.resolve())
    write_atomic(args.output, result)
    print(json.dumps({
        "status": "completed",
        "output": str(args.output),
        "historical_rows": result["scope_counts"]["historical_118_rows"],
        "f4_zero_native_controls": result["scope_counts"]["f4_zero_native_controls"],
        "cause_counts": result["cause_counts"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CoverageError as exc:
        raise SystemExit(f"CoverageError: {exc}")
