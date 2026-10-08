#!/usr/bin/env python3
"""Index source-closed native identities into bounded development scopes.

This is a JSON/CSV metadata consumer for the completed root064 products.  It
does not decode PartOut, open H5/BI4 content, rerun a solver, or merge physical
cases across the existing v25 condition components.  Its useful output is a
source-closed audit subset for identity/motive/source-MK/saved-bracket tasks;
physical fate, legal flux, dynamics, and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.native-source-identity-development-subset.v1"
ROOT064_CLOSURE_SCHEMA = "ds02.stage2.f2-s1-native-source-closure-118.v2"
NATIVE_MOTIVE_SCHEMA = "ds02.stage2.f1.dp0025.native-motive-audit.v2"


class AuditError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.name.endswith(".h5") or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
        raise AuditError(f"{label} points at forbidden trajectory content: {path}")
    if not path.is_file():
        raise AuditError(f"{label} is missing: {path}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def read_json(path: Path, label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = Path(path).expanduser().resolve()
    binding = bind(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} is not a JSON object")
    return path, value, binding


def read_product(report_path: Path, receipt_path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path, report, report_binding = read_json(report_path, f"{label} report")
    receipt_path, receipt, receipt_binding = read_json(receipt_path, f"{label} receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError(f"{label} receipt is not completed code 0")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if output_root != path.parent:
        raise AuditError(f"{label} report is outside its completed receipt output root")
    guard = receipt.get("terminal_storage_guard", {})
    if guard.get("status") != "passed" or guard.get("actual_bytes") != receipt.get("bytes"):
        raise AuditError(f"{label} terminal storage receipt is not fixed-point passed")
    if receipt.get("source_preflight", {}).get("status") != "PASS_AFTER_RESERVATION":
        raise AuditError(f"{label} source preflight is not reservation-before-read passed")
    if receipt.get("model_invoked") is not False or receipt.get("cfd_invoked") is not False:
        raise AuditError(f"{label} invokes forbidden model/CFD")
    return report, {
        "report": report_binding,
        "receipt": receipt_binding,
        "receipt_status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "bytes": receipt.get("bytes"),
        "terminal_storage_guard": guard,
        "source_preflight": receipt.get("source_preflight"),
    }


def read_receipt_only(receipt_path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind a completed producer receipt without reopening its payload.

    The root063 PartVTKOut receipts are lineage evidence for the root064
    semantic audits.  This helper reads only their JSON receipt; it never
    follows an input path listed by the receipt.
    """
    path, receipt, binding = read_json(receipt_path, f"{label} receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError(f"{label} receipt is not completed code 0")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if output_root != path.parent:
        raise AuditError(f"{label} receipt output root is not its own directory")
    guard = receipt.get("terminal_storage_guard", {})
    if guard.get("status") != "passed" or guard.get("actual_bytes") != receipt.get("bytes"):
        raise AuditError(f"{label} terminal storage receipt is not fixed-point passed")
    if receipt.get("source_preflight", {}).get("status") != "PASS_AFTER_RESERVATION":
        raise AuditError(f"{label} source preflight is not reservation-before-read passed")
    if receipt.get("model_invoked") is not False or receipt.get("cfd_invoked") is not False:
        raise AuditError(f"{label} invokes forbidden model/CFD")
    return receipt, {
        "receipt": binding,
        "receipt_status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "bytes": receipt.get("bytes"),
        "terminal_storage_guard": guard,
        "source_preflight": receipt.get("source_preflight"),
    }


def _root063_lineage(
    f2_report_path: Path,
    f2_receipt_path: Path,
    f1_half_receipt_path: Path,
    f1_same_receipt_path: Path,
) -> dict[str, Any]:
    """Validate the direct root063 producer receipts behind root064 outputs."""
    f2_report_path, f2_report, f2_report_binding = read_json(f2_report_path, "root063 F2 singleton report")
    f2_receipt, f2_receipt_summary = read_receipt_only(f2_receipt_path, "root063 F2 singleton")
    if f2_report.get("schema") != "ds02.stage2.f2-s1-native-source-adapter.v3":
        raise AuditError("root063 F2 singleton report schema differs")
    if f2_report.get("status") != "COMPLETED_F2_S1_NATIVE_SOURCE_JOIN_WITH_PHYSICAL_FATE_UNKNOWN":
        raise AuditError("root063 F2 singleton report status differs")
    identity = f2_report.get("native_identity", {})
    ids = identity.get("ids", [])
    if identity.get("id_count") != 3 or {row.get("idp") for row in ids} != {397194, 403829, 404024}:
        raise AuditError("root063 F2 singleton native identity set differs")
    if identity.get("motive_counts") != {"density": 0, "movement": 0, "position": 3}:
        raise AuditError("root063 F2 singleton motive counts differ")
    if f2_report.get("claim_boundary", {}).get("physical_fate") != "UNKNOWN; native numerical position exclusion is not legal spill or physical outflow":
        raise AuditError("root063 F2 singleton widened physical-fate claim")
    if f2_report.get("read_policy", {}).get("trajectory_h5_opened") is not False or f2_report.get("read_policy", {}).get("part_frames_opened") is not False:
        raise AuditError("root063 F2 singleton read forbidden trajectory content")

    f1_half_receipt, f1_half_summary = read_receipt_only(f1_half_receipt_path, "root063 F1 half decoder")
    f1_same_receipt, f1_same_summary = read_receipt_only(f1_same_receipt_path, "root063 F1 same decoder")
    for label, receipt in (("root063 F1 half decoder", f1_half_receipt), ("root063 F1 same decoder", f1_same_receipt)):
        command = receipt.get("request", {}).get("command", [])
        if not command or "PartVTKOut" not in Path(str(command[0])).name:
            raise AuditError(f"{label} receipt is not bound to official PartVTKOut")
        if "-threads:1" in command:
            raise AuditError(f"{label} receipt contains unsupported -threads:1")
    return {
        "f2_s1_singleton": {
            "report": f2_report_binding,
            **f2_receipt_summary,
            "native_id_count": identity.get("id_count"),
            "native_ids": sorted(row.get("idp") for row in ids),
            "native_motive_counts": identity.get("motive_counts"),
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "f1_half_decoder_receipt": {**f1_half_summary, "official_tool": "PartVTKOut", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "f1_same_decoder_receipt": {**f1_same_summary, "official_tool": "PartVTKOut", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }


def _native_rows(closure: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if closure.get("schema") != ROOT064_CLOSURE_SCHEMA:
        raise AuditError("root064 closure schema differs")
    if closure.get("status") != "PASS_ACTUAL_118_CASE_SOURCE_CLOSED_WITH_PRIOR_GAP_SPECTRUM_PRESERVED":
        raise AuditError("root064 closure status differs")
    counts = closure.get("case_counts", {})
    if counts != {
        "native_identity_source_closed": 118,
        "prior_v2_source_incomplete": 1,
        "requested": 118,
        "source_binding_rejected": 0,
        "source_incomplete_active": 0,
    }:
        raise AuditError("root064 closure case counts differ")
    cases = closure.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise AuditError("root064 closure does not contain 118 cases")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    family_cases = Counter()
    family_motive_ids = Counter()
    source_mk = Counter()
    motive = Counter()
    bad_brackets = 0
    for case in cases:
        key = case.get("case_key")
        family = case.get("family_id")
        if not isinstance(key, str) or family not in {"F2", "F4", "F6"}:
            raise AuditError("root064 closure contains an unexpected case family/key")
        if case.get("case_status") != "NATIVE_IDENTITY_SOURCE_CLOSED":
            raise AuditError(f"root064 case is not source closed: {key}")
        family_cases[family] += 1
        native = case.get("native_identity", {})
        ids = native.get("ids")
        if not isinstance(ids, list):
            raise AuditError(f"root064 native IDs missing for {key}")
        for item in ids:
            idp = item.get("idp")
            if not isinstance(idp, int):
                raise AuditError(f"root064 Idp is not integer for {key}")
            identity_key = (key, idp)
            if identity_key in seen:
                raise AuditError(f"duplicate case-qualified native identity: {identity_key}")
            seen.add(identity_key)
            bracket = item.get("first_missing_bracket_s")
            if not isinstance(bracket, list) or len(bracket) != 2 or not all(isinstance(x, (int, float)) for x in bracket) or not bracket[0] < bracket[1]:
                bad_brackets += 1
            native_motive = item.get("native_motive", item.get("motive"))
            if native_motive not in {"position", "density", "movement"}:
                raise AuditError(f"unknown native motive for {identity_key}")
            motive[native_motive] += 1
            family_motive_ids[(family, native_motive)] += 1
            source_mk[(family, str(item.get("mk")))] += 1
            rows.append({
                "case_key": key,
                "family_id": family,
                "physical_case_id": case.get("physical_case_id"),
                "idp": idp,
                "mk": item.get("mk"),
                "type": item.get("type"),
                "native_motive": native_motive,
                "first_missing_bracket_s": bracket,
                "initial_mass_kg": item.get("initial_mass_kg"),
            })
    if bad_brackets:
        raise AuditError(f"{bad_brackets} invalid first-missing brackets")
    if len(rows) != 1328 or closure.get("native_id_count") != len(rows):
        raise AuditError("root064 native row count differs: case-qualified (case_key,Idp) rows are required")
    if family_cases != Counter({"F2": 48, "F4": 22, "F6": 48}):
        raise AuditError(f"root064 family case counts differ: {family_cases}")
    if family_motive_ids != Counter({("F2", "position"): 1078, ("F4", "density"): 51, ("F6", "position"): 199}):
        raise AuditError(f"root064 family motive counts differ: {family_motive_ids}")
    return rows, {
        "case_count": len(cases),
        "row_count": len(rows),
        "identity_key": "(case_key, Idp); Idp is not globally unique across physical cases",
        "family_case_counts": dict(sorted(family_cases.items())),
        "family_motive_id_counts": {f"{f}:{m}": n for (f, m), n in sorted(family_motive_ids.items())},
        "motive_counts": dict(sorted(motive.items())),
        "source_mk_counts": {f"{f}:MK{mk}": n for (f, mk), n in sorted(source_mk.items())},
        "invalid_first_missing_brackets": bad_brackets,
    }


def _validate_f1(report: dict[str, Any], label: str, expected: int, expected_motives: dict[str, int]) -> dict[str, Any]:
    if report.get("schema") != NATIVE_MOTIVE_SCHEMA or report.get("status") != "COMPLETED_NATIVE_MOTIVE_AUDIT":
        raise AuditError(f"{label} report schema/status differs")
    if report.get("expected_excluded_count") != expected or report.get("motive_counts") != expected_motives:
        raise AuditError(f"{label} native row/motive count differs")
    if report.get("runparts_totals", {}).get("NpOut") != expected:
        raise AuditError(f"{label} RunPARTs total differs")
    if report.get("runout_counts", {}).get("excluded_particles") != expected:
        raise AuditError(f"{label} Run.out total differs")
    if report.get("read_policy", {}).get("h5_opened") is not False or report.get("read_policy", {}).get("trajectory_part_frames_opened") is not False:
        raise AuditError(f"{label} read policy opened forbidden trajectory content")
    if any(report.get("qualification", {}).get(k) != "UNKNOWN" for k in ("physical_fate", "dynamical_impact", "QI", "QN", "QE")):
        raise AuditError(f"{label} qualification boundary was widened")
    rows = report.get("native_rows")
    if not isinstance(rows, list) or len(rows) != expected or len({row.get("idp") for row in rows}) != expected:
        raise AuditError(f"{label} Idp rows are not unique/count-consistent")
    return {
        "case_id": report.get("case_id"),
        "physical_case_id": report.get("physical_case_id"),
        "row_count": expected,
        "motive_counts": report.get("motive_counts"),
        "runparts_totals": report.get("runparts_totals"),
        "runout_counts": report.get("runout_counts"),
        "native_identity": "SOURCE_CLOSED",
        "physical_fate": "UNKNOWN",
        "legal_outflow": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }


def _split_reference(split: dict[str, Any]) -> dict[str, Any]:
    if split.get("schema") != "ds02.stage2.source-closed-development-split.v25":
        raise AuditError("v25 split schema differs")
    assignments = split.get("development_split", {}).get("assignments")
    if not isinstance(assignments, list) or len(assignments) != 7:
        raise AuditError("v25 split does not contain seven anchor assignments")
    if any(row.get("scientific_split_safe") != "UNKNOWN" for row in assignments):
        raise AuditError("v25 split incorrectly claims scientific split safety")
    return {
        "status": split.get("status"),
        "assignments": assignments,
        "supported_task_scopes": split["development_split"].get("supported_task_scopes", []),
        "scientific_split_safe": "UNKNOWN",
        "cross_component_transfer_edges": split["development_split"].get("cross_component_transfer_edges", []),
        "native_motive_physical_fate": "UNKNOWN",
    }


def _qualification_reference(qualification: dict[str, Any], task_scope: dict[str, Any]) -> dict[str, Any]:
    if qualification.get("schema") != "ds02.stage2.final-qualification-catalog.v29":
        raise AuditError("v29 qualification schema differs")
    if qualification.get("status") != "ACTUAL_336_CASE_AUDIT_AND_118_NATIVE_IMPACT_BOUND_NO_SCIENTIFIC_QUALIFICATION":
        raise AuditError("v29 qualification status differs")
    coverage = qualification.get("coverage", {})
    if coverage.get("current_cases") != 336 or coverage.get("audit_native_intersection") != 118 or coverage.get("native_impact_cases") != 118:
        raise AuditError("v29 qualification coverage differs")
    boundary = qualification.get("claim_boundary", {})
    for key in ("physical_fate", "legal_outflow_or_spill", "dynamical_impact", "QI", "QN", "QE"):
        if boundary.get(key) not in {"UNKNOWN", "UNKNOWN_NOT_PROVEN"}:
            raise AuditError(f"v29 qualification boundary widened for {key}")
    if task_scope.get("schema") != "ds02.stage2.task-scope-catalog.v30":
        raise AuditError("v30 task scope schema differs")
    if task_scope.get("status") != "ACTUAL_V29_TASK_SCOPE_INDEX_WITH_QN_QE_QI_UNKNOWN":
        raise AuditError("v30 task scope status differs")
    tq = task_scope.get("task_qualification", {})
    if any(tq.get(key) != "UNKNOWN" for key in ("QN", "QE", "QI", "physical_fate", "legal_flux", "dynamical_impact", "effective_split_safe")):
        raise AuditError("v30 task scope widened an unknown qualification dimension")
    if tq.get("native_mk_motive_and_id") != "ELIGIBLE_118_SOURCE_CLOSED_CASES" or tq.get("saved_record_censor") != "ELIGIBLE_118_SAVED_BRACKET_CASES":
        raise AuditError("v30 task-scoped native eligibility differs")
    return {
        "v29_status": qualification.get("status"),
        "v29_coverage": coverage,
        "v29_claim_boundary": boundary,
        "v30_status": task_scope.get("status"),
        "v30_coverage": task_scope.get("coverage"),
        "v30_task_qualification": tq,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    root063 = _root063_lineage(
        args.f2_root063_report,
        args.f2_root063_receipt,
        args.f1_half_root063_receipt,
        args.f1_same_root063_receipt,
    )
    closure, closure_src = read_product(args.closure_report, args.closure_receipt, "root064 all118 source closure")
    closure_rows, closure_stats = _native_rows(closure)
    half, half_src = read_product(args.f1_half_report, args.f1_half_receipt, "root064 F1 half audit")
    same, same_src = read_product(args.f1_same_report, args.f1_same_receipt, "root064 F1 same audit")
    half_summary = _validate_f1(half, "F1 half", 19, {"density": 1, "movement": 0, "position": 18})
    same_summary = _validate_f1(same, "F1 same", 22, {"density": 4, "movement": 0, "position": 18})
    split, split_src = read_product(args.split_report, args.split_receipt, "v25 source-closed split")
    qualification, qualification_src = read_product(args.qualification_report, args.qualification_receipt, "v29 qualification catalog")
    task_scope, task_scope_src = read_product(args.task_scope_report, args.task_scope_receipt, "v30 task scope")
    split_summary = _split_reference(split)
    qualification_summary = _qualification_reference(qualification, task_scope)
    return {
        "schema": SCHEMA,
        "status": "PASS_ACTUAL_SOURCE_CLOSED_DEVELOPMENT_SUBSET_NO_PHYSICAL_QUALIFICATION",
        "source_bindings": {
            "root063_lineage": root063,
            "root064_all118_closure": closure_src,
            "root064_f1_half": half_src,
            "root064_f1_same": same_src,
            "v25_split": split_src,
            "v29_qualification": qualification_src,
            "v30_task_scope": task_scope_src,
        },
        "root063_lineage": root063,
        "native_source_closed_subset": {
            **closure_stats,
            "eligible_scopes": [
                "native (case_key, Idp, motive) identity/motive audit",
                "source-MK/type bookkeeping with case-qualified IDs",
                "saved first-missing bracket and source-visible mass lower-bound bookkeeping",
            ],
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "continuous_event_time": "UNKNOWN beyond saved bracket",
        },
        "f1_dp0025_extension_audits": {
            "split_assignment": "NOT_ASSIGNED_TO_V25_CURRENT336_ANCHOR_COMPONENTS",
            "scientific_split_safe": "UNKNOWN",
            "half": half_summary,
            "same": same_summary,
            "combined_rows": 41,
            "combined_motive_counts": {"density": 5, "movement": 0, "position": 36},
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "existing_split_reference": split_summary,
        "existing_qualification_reference": qualification_summary,
        "statistical_checks": {
            "closure_case_qualified_identity_rows": len(closure_rows),
            "closure_reported_native_id_count": closure.get("native_id_count"),
            "closure_global_idp_uniqueness_claim": False,
            "f1_half_runparts_runout_match": True,
            "f1_same_runparts_runout_match": True,
            "all118_physical_qualification_credit": "NONE",
        },
        "claim_boundary": {
            "source_identity": "SOURCE_CLOSED for root064 all118 and the two F1 DP0025 audit outputs",
            "native_motive": "SOURCE_CLOSED within each exact case-qualified source binding",
            "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_spill": "UNKNOWN",
            "continuous_event_time": "UNKNOWN; saved brackets only",
            "flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "scientific_split_safe": "UNKNOWN",
        },
        "read_policy": {
            "json_reports_receipts_opened": True,
            "csv_summary_fields_opened": True,
            "h5_opened": False,
            "bi4_frames_opened": False,
            "raw_partout_opened": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
    }


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise AuditError(f"preserve existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", choices=["build"])
    for name in ("closure", "f1_half", "f1_same", "split", "qualification", "task_scope"):
        option_name = name.replace("_", "-")
        parser.add_argument(f"--{option_name}-report", dest=f"{name}_report", required=True, type=Path)
        parser.add_argument(f"--{option_name}-receipt", dest=f"{name}_receipt", required=True, type=Path)
    parser.add_argument("--f2-root063-report", required=True, type=Path)
    parser.add_argument("--f2-root063-receipt", required=True, type=Path)
    parser.add_argument("--f1-half-root063-receipt", required=True, type=Path)
    parser.add_argument("--f1-same-root063-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args)
    write_atomic(args.output, result)
    print(json.dumps({"status": result["status"], "native_rows": result["native_source_closed_subset"]["row_count"], "f1_rows": result["f1_dp0025_extension_audits"]["combined_rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
