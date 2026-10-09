#!/usr/bin/env python3
"""Prepare and audit the additive ROOT270 saved-mask impact sidecar.

ROOT266 produced a useful 19-case saved-frame diagnostic, but its seven
typed-only cases encoded unavailable native quantities as zero.  ROOT270
keeps the 19 typed-summary paths and the ROOT266 result as immutable source
provenance, then binds the seven actual ROOT258 native case reports.  A
typed-only case therefore has ``None``/``UNKNOWN`` native fields.  A native
case may use a per-row ``initial_mass_kg`` when the report supplies one;
otherwise its role-average mass is reported as an explicitly unverified
proxy.  No value here is a physical flux, fate, dynamics, or Q result.

The preparer and audit read only small JSON/proof files and typed summary
JSON.  They do not open trajectory JSONL/HDF5, BI4/OBI4, or PartOut
payloads.  The parent runner owns any guarded execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import ds_data02_stage2_build_root266_impact_sidecar as root266


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ORIGINAL = Path("/home/jade/Projects/DualSPHysics")
LAB = ORIGINAL / "lagrangian-fluid-lab"
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
VENV = LAB / ".venv/bin/python"
PYVENV = LAB / ".venv/pyvenv.cfg"
RUNTIME = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
CURRENT = STAGE2 / "CURRENT336.json"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ROOT264_OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT264_ACTUAL_OVERLAY_V9.json"
MAX_SMALL = 10 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
PROOF_SCHEMA = root266.PROOF_SCHEMA
MANIFEST_SCHEMA = "ds02.stage2.root270-impact-sidecar.v2"
REPORT_SCHEMA = "ds02.stage2.root270-impact-sidecar-report.v2"


class ImpactV2Error(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ImpactV2Error(f"{label} is not a SHA-256 digest")
    return value.lower()


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise ImpactV2Error(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ImpactV2Error(f"{label} is missing: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    st = path.stat()
    return {
        "path": str(path),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns),
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
    }


def _digest(path: Path, label: str, *, limit: int | None = None) -> str:
    path = _path(path, label)
    if limit is not None and path.stat().st_size > limit:
        raise ImpactV2Error(f"{label} exceeds bounded read")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL:
        raise ImpactV2Error(f"{label} exceeds the small-JSON bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ImpactV2Error(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ImpactV2Error(f"{label} must be an object")
    return value


def _ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL:
        raise ImpactV2Error(f"{label} exceeds the small source bound")
    actual = _digest(path, label, limit=MAX_SMALL)
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual != _sha(expected, f"{label} expected SHA"):
        raise ImpactV2Error(f"{label} SHA differs")
    value.update({"sha256": actual, "content_opened": True})
    return value


def _atomic(path: Path, value: dict[str, Any], limit: int = MAX_OUTPUT) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ImpactV2Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if tmp.stat().st_size > limit:
            raise ImpactV2Error(f"{path} exceeds output bound")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ImpactV2Error(f"{label} must be finite numeric")
    return float(value)


def _add_ref(refs: dict[str, dict[str, Any]], ref: dict[str, Any]) -> None:
    path = str(ref["path"])
    old = refs.get(path)
    if old is not None and old["sha256"] != ref["sha256"]:
        raise ImpactV2Error(f"source path has conflicting SHA: {path}")
    refs[path] = ref


def _proof_rows(path: Path, label: str, *, allowed_families: set[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    proof_ref = _ref(path, f"{label} proof")
    proof = _json(path, f"{label} proof")
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise ImpactV2Error(f"{label} is not a completed verified proof")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        rows = proof.get("case_results") if isinstance(proof.get("case_results"), list) else []
    counts = proof.get("counts")
    completed = counts.get("completed") if isinstance(counts, dict) else proof.get("actual_completed_physical_cases")
    if not isinstance(completed, int) or completed != len(rows):
        raise ImpactV2Error(f"{label} completed count does not match rows")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise ImpactV2Error(f"{label} has malformed case row")
        case_id = row["physical_case_id"]
        if case_id in seen:
            raise ImpactV2Error(f"{label} duplicates {case_id}")
        seen.add(case_id)
        family = row.get("family_id")
        if allowed_families is not None and family not in allowed_families:
            raise ImpactV2Error(f"{label} row family differs: {case_id}")
        normalized.append(dict(row))
    return proof_ref, normalized, proof


def _typed_summary_ref(row: dict[str, Any], case_id: str) -> tuple[Path, str | None]:
    value = row.get("typed_summary", row.get("summary"))
    if isinstance(value, str):
        return Path(value), row.get("typed_summary_sha256", row.get("summary_sha256"))
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return Path(value["path"]), value.get("sha256")
    raise ImpactV2Error(f"{case_id} has no typed summary path")


def _validate_summary(summary: dict[str, Any], case_id: str) -> None:
    try:
        root266._validate_summary(summary, case_id)
    except (root266.ImpactError, KeyError, TypeError, ValueError) as exc:
        raise ImpactV2Error(str(exc)) from exc


def _load_root266(root266_proof_path: Path, root266_report_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    proof_ref, proof_rows, proof = _proof_rows(root266_proof_path, "ROOT266 V1", allowed_families={"F4", "F6"})
    report_ref = _ref(root266_report_path, "ROOT266 V1 actual report")
    report = _json(root266_report_path, "ROOT266 V1 actual report")
    if report.get("schema") != root266.REPORT_SCHEMA or not str(report.get("status", "")).startswith("COMPLETED"):
        raise ImpactV2Error("ROOT266 V1 report is not a completed report")
    report_rows = report.get("case_results")
    if not isinstance(report_rows, list) or len(report_rows) != len(proof_rows):
        raise ImpactV2Error("ROOT266 V1 report/proof case counts differ")
    by_report_id: dict[str, dict[str, Any]] = {}
    for row in report_rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise ImpactV2Error("ROOT266 V1 report has malformed case row")
        case_id = row["physical_case_id"]
        if case_id in by_report_id:
            raise ImpactV2Error(f"ROOT266 V1 report duplicates {case_id}")
        by_report_id[case_id] = row
    entries: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    proof_by_id: dict[str, dict[str, Any]] = {}
    for row in proof_rows:
        case_id = row["physical_case_id"]
        if case_id not in by_report_id:
            raise ImpactV2Error(f"ROOT266 V1 report misses {case_id}")
        report_row = by_report_id[case_id]
        summary_path, summary_sha = _typed_summary_ref(row, case_id)
        summary_ref = _ref(summary_path, f"{case_id} ROOT266 typed summary", summary_sha)
        summary = _json(summary_path, f"{case_id} ROOT266 typed summary")
        _validate_summary(summary, case_id)
        entry = {
            "physical_case_id": case_id,
            "family_id": row.get("family_id", report_row.get("family_id", "UNKNOWN")),
            "typed_summary": summary_ref,
            "typed_summary_sha256": summary_ref["sha256"],
            "source_v1_status": report_row.get("status"),
            "source_v1_native_join": report_row.get("native_join"),
            "source_v1_case_result": {"status": report_row.get("status"), "native_join": report_row.get("native_join")},
            "root266_proof_row": row,
            "root266_proof": proof_ref,
            "root266_report": report_ref,
        }
        entries.append(entry)
        by_id[case_id] = entry
        proof_by_id[case_id] = row
    if len(entries) != 19:
        raise ImpactV2Error(f"ROOT270 requires 19 immutable ROOT266 cases, got {len(entries)}")
    return proof_ref, report_ref, entries, by_id, {"proof": proof, "report": report}


def _load_root258(root258_proof_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    proof_ref, rows, proof = _proof_rows(root258_proof_path, "ROOT258 actual", allowed_families={"F6"})
    aggregate_path = proof.get("report")
    aggregate_sha = proof.get("report_sha256")
    if not isinstance(aggregate_path, str):
        raise ImpactV2Error("ROOT258 proof has no aggregate report path")
    aggregate_ref = _ref(Path(aggregate_path), "ROOT258 actual aggregate report", aggregate_sha)
    aggregate = _json(Path(aggregate_path), "ROOT258 actual aggregate report")
    if aggregate.get("schema") != "ds02.stage2.generic-native-extract-report.v1" or aggregate.get("status") != "COMPLETED_ALL_CASES":
        raise ImpactV2Error("ROOT258 aggregate report is not completed")
    aggregate_rows = aggregate.get("case_results")
    if not isinstance(aggregate_rows, list) or len(aggregate_rows) != len(rows):
        raise ImpactV2Error("ROOT258 aggregate/proof counts differ")
    aggregate_ids = {row.get("physical_case_id") for row in aggregate_rows if isinstance(row, dict)}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row["physical_case_id"]
        if case_id not in aggregate_ids:
            raise ImpactV2Error(f"ROOT258 aggregate misses {case_id}")
        report_path = row.get("report")
        if not isinstance(report_path, str):
            raise ImpactV2Error(f"ROOT258 proof has no case report for {case_id}")
        report_ref = _ref(Path(report_path), f"{case_id} ROOT258 case report", row.get("report_sha256"))
        case_report = _json(Path(report_path), f"{case_id} ROOT258 case report")
        if case_report.get("physical_case_id") != case_id or case_report.get("family_id") != "F6":
            raise ImpactV2Error(f"ROOT258 case report identity differs: {case_id}")
        if case_report.get("status") != "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY":
            raise ImpactV2Error(f"ROOT258 case report is not completed: {case_id}")
        typed = row.get("typed_summary")
        if not isinstance(typed, dict) or not isinstance(typed.get("path"), str):
            raise ImpactV2Error(f"ROOT258 proof has no typed summary for {case_id}")
        typed_ref = _ref(Path(typed["path"]), f"{case_id} ROOT258 typed summary", typed.get("sha256"))
        result[case_id] = {"proof_row": row, "report": case_report, "report_ref": report_ref, "typed_ref": typed_ref, "proof": proof_ref}
    if len(result) != 7:
        raise ImpactV2Error(f"ROOT270 requires seven ROOT258 rebindings, got {len(result)}")
    return proof_ref, aggregate_ref, result


def _native_rows(report: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    try:
        return root266._native_rows(report, case_id)
    except (root266.ImpactError, KeyError, TypeError, ValueError) as exc:
        raise ImpactV2Error(str(exc)) from exc


def _typed_ledger(summary: dict[str, Any], case_id: str) -> dict[str, Any]:
    fluid = summary["role_ledgers"]["fluid"]
    counts = fluid["active_count_by_frame"]
    masses = fluid["active_mass_kg_by_frame"]
    initial_count = int(fluid["initial_count"])
    initial_mass = _finite(fluid["initial_mass_kg"], f"{case_id} initial fluid mass")
    final_count = int(counts[-1])
    final_mass = _finite(masses[-1], f"{case_id} final fluid mass")
    return {
        "initial_fluid_count": initial_count,
        "initial_fluid_mass_kg": initial_mass,
        "final_active_count": final_count,
        "final_active_mass_kg": final_mass,
        "saved_active_count_deficit": initial_count - final_count,
        "saved_active_mass_deficit_kg": initial_mass - final_mass,
        "typed_role_average_mass_proxy_kg": (initial_mass / initial_count if initial_count else None),
        "proxy_uniformity": "UNVERIFIED_ROLE_AVERAGE_PROXY_ONLY",
        "timeline_frame_count": len(counts),
    }


def _native_mass(rows: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    values = [row.get("initial_mass_kg") for row in rows]
    numeric = [_finite(value, f"{case_id} native row initial mass") for value in values if value is not None]
    all_present = bool(rows) and len(numeric) == len(rows)
    return {
        "native_target_count": len(rows),
        "native_exact_initial_mass_kg": (sum(numeric) if all_present else None),
        # Zero would be misleading for the seven ROOT258 rebinding cases:
        # their actual reports have no per-row mass field.  Keep the count
        # unknown/null unless at least one audited mass field is present.
        "native_exact_mass_rows": (len(numeric) if numeric else None),
        "native_initial_mass_source": ("NATIVE_REPORT_ROW_INITIAL_MASS_KG" if all_present else "NO_PER_ROW_INITIAL_MASS_FIELD"),
        "proxy_uniformity": "UNVERIFIED_ROLE_AVERAGE_PROXY_ONLY",
    }


def _semantic_case(entry: dict[str, Any], summary: dict[str, Any], native_rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    case_id = entry["physical_case_id"]
    typed = _typed_ledger(summary, case_id)
    if native_rows is None:
        native = {
            "status": "UNKNOWN_NO_NATIVE_BINDING",
            "native_target_count": None,
            "native_exact_initial_mass_kg": None,
            "native_exact_mass_rows": None,
            "native_initial_mass_source": "UNKNOWN",
            "native_saved_frame_join": "UNKNOWN",
            "native_physical_cause": "UNKNOWN",
            "role_average_proxy_mass_kg": None,
            "proxy_uniformity": "UNKNOWN_NO_NATIVE_BINDING",
        }
    else:
        native = {"status": "BOUND_ACTUAL_NATIVE_REPORT", "native_saved_frame_join": "EXACT_ID_AND_SAVED_BRACKET_INPUT_REPORT", **_native_mass(native_rows, case_id)}
        native["role_average_proxy_mass_kg"] = typed["typed_role_average_mass_proxy_kg"]
        native["native_physical_cause"] = "NUMERICAL_NATIVE_CAUSE_ONLY; physical fate UNKNOWN"
    return {
        "typed_saved_mask": typed,
        "native_binding": native,
        "sample_mass_impact": {
            "saved_active_mass_deficit_kg": typed["saved_active_mass_deficit_kg"],
            "saved_active_count_deficit": typed["saved_active_count_deficit"],
            "native_exact_initial_mass_kg": native["native_exact_initial_mass_kg"],
            "native_role_average_proxy_mass_kg": native["role_average_proxy_mass_kg"],
            "diagnostic_only": True,
            "physical_mass_flux": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _case_entry(entry: dict[str, Any], root258_case: dict[str, Any] | None, refs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = entry["physical_case_id"]
    typed_ref = entry["typed_summary"]
    summary = _json(Path(typed_ref["path"]), f"{case_id} typed summary")
    _validate_summary(summary, case_id)
    native_ref: dict[str, Any] | None = None
    native_report: dict[str, Any] | None = None
    native_source = "UNKNOWN_NO_NATIVE_BINDING"
    proof_ref = None
    if root258_case is not None:
        native_ref = root258_case["report_ref"]
        native_report = root258_case["report"]
        proof_ref = root258_case["proof"]
        native_source = "ROOT258_ACTUAL_NATIVE_REPORT_REBOUND"
        # The seven rebindings must point to exactly the same immutable typed
        # summary source used by ROOT266.
        typed_ref_258 = root258_case["typed_ref"]
        if typed_ref_258["path"] != typed_ref["path"] or typed_ref_258["sha256"] != typed_ref["sha256"]:
            raise ImpactV2Error(f"{case_id} ROOT258 typed summary is not ROOT266's unchanged source")
    else:
        old_native = entry["root266_proof_row"].get("native_report")
        if isinstance(old_native, dict) and isinstance(old_native.get("path"), str):
            native_ref = _ref(Path(old_native["path"]), f"{case_id} preserved ROOT266 native report", old_native.get("sha256"))
            native_report = _json(Path(native_ref["path"]), f"{case_id} preserved ROOT266 native report")
            native_source = "PRESERVED_ROOT266_NATIVE_REPORT"
            _native_rows(native_report, case_id)
            refs[native_ref["path"]] = native_ref
    if native_ref is not None:
        refs[native_ref["path"]] = native_ref
        native_rows = _native_rows(native_report or {}, case_id)
        semantic = _semantic_case(entry, summary, native_rows)
        semantic["native_binding"]["report"] = native_ref
        semantic["native_binding"]["proof"] = proof_ref
        semantic["native_binding"]["source"] = native_source
    else:
        semantic = _semantic_case(entry, summary, None)
        semantic["native_binding"]["source"] = native_source
    return {
        "physical_case_id": case_id,
        "family_id": entry["family_id"],
        "typed_summary": typed_ref,
        "typed_summary_origin": "ROOT266_V1_ACTUAL_PROOF_UNCHANGED",
        "source_v1": {
            **entry["source_v1_case_result"],
            "legacy_typed_only_zero_native_fields": entry["root266_proof_row"].get("typed_only_zero_native_fields"),
        },
        "semantic_v2": semantic,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root266_proof_ref, root266_report_ref, root266_entries, by_id, root266_data = _load_root266(args.root266_proof, args.root266_report)
    root258_proof_ref, root258_aggregate_ref, root258_cases = _load_root258(args.root258_proof)
    for case_id, native in root258_cases.items():
        if case_id not in by_id:
            raise ImpactV2Error(f"ROOT258 case is outside the immutable ROOT266 19-case source: {case_id}")
    overlay_ref = _ref(args.root264_overlay, "ROOT264 actual overlay V9")
    overlay = _json(args.root264_overlay, "ROOT264 actual overlay V9")
    if overlay.get("status") != "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS":
        raise ImpactV2Error("ROOT264 overlay is not the actual V9 metadata overlay")
    refs: dict[str, dict[str, Any]] = {}
    for ref in (
        _ref(CURRENT, "CURRENT336", CURRENT_SHA),
        _ref(SCRIPT, "ROOT270 sidecar worker"),
        _ref(root266.SCRIPT, "ROOT266 V1 sidecar worker"),
        _ref(args.root266_proof, "ROOT266 V1 proof"),
        _ref(args.root266_report, "ROOT266 V1 actual report"),
        _ref(args.root266_manifest, "ROOT266 V1 manifest"),
        root258_proof_ref,
        root258_aggregate_ref,
        overlay_ref,
        _ref(VENV, "literal Python interpreter"),
        _ref(VENV.resolve(), "resolved Python interpreter"),
        _ref(PYVENV, "pyvenv.cfg"),
        _ref(RUNTIME, "runtime v8"),
        _ref(DISPATCH, "dispatch v8"),
    ):
        _add_ref(refs, ref)
    cases: list[dict[str, Any]] = []
    for entry in root266_entries:
        root258_case = root258_cases.get(entry["physical_case_id"])
        case = _case_entry(entry, root258_case, refs)
        _add_ref(refs, entry["typed_summary"])
        cases.append(case)
    if len(cases) != 19 or len({case["physical_case_id"] for case in cases}) != 19:
        raise ImpactV2Error("ROOT270 case source is not exactly 19 unique ROOT266 cases")
    for ref in refs.values():
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise ImpactV2Error(f"payload entered ROOT270 static closure: {ref['path']}")
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise ImpactV2Error(f"refusing to reuse ROOT270 output root: {output_root}")
    proof_roles = [
        {"role": "root266_v1_actual_proof", "ref": root266_proof_ref, "case_count": 19},
        {"role": "root258_actual_native_proof", "ref": root258_proof_ref, "case_count": 7},
        {"role": "root258_actual_aggregate_report", "ref": root258_aggregate_ref, "case_count": 7},
    ]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_SOURCE_ONLY_ROOT270_ADDITIVE_NATIVE_REBIND_IMPACT_DIAGNOSTIC",
        "namespace": "ROOT270",
        "family_id": "INFRA",
        "current_catalog": _ref(CURRENT, "CURRENT336", CURRENT_SHA),
        "root266_v1_source": {"proof": root266_proof_ref, "report": root266_report_ref, "manifest": _ref(args.root266_manifest, "ROOT266 V1 manifest"), "case_count": 19},
        "root258_actual_rebinding": {"proof": root258_proof_ref, "aggregate_report": root258_aggregate_ref, "case_count": 7, "case_ids": sorted(root258_cases)},
        "legacy_v1_typed_only_rebound_count": sum(entry["source_v1_status"] == "TYPED_ONLY_NO_NATIVE_JOIN" for entry in root266_entries),
        "scope_context_only": {"overlay_v9": overlay_ref, "label": "ROOT264 actual overlay V9; no ROOT269/V8 label is used", "affects_root270_cases": False},
        "proof_roles": proof_roles,
        "case_count": len(cases),
        "cases": cases,
        "source_refs": sorted(refs.values(), key=lambda item: item["path"]),
        "claim_boundary": {
            "saved_frame_mass_and_count_effect": "DIAGNOSTIC_ONLY",
            "native_per_row_initial_mass": "AUDITED_ONLY_WHEN_REPORT_ROW_SUPPLIES_INITIAL_MASS_KG",
            "role_average_mass_proxy": "UNVERIFIED_NONUNIFORM_PROXY_ONLY",
            "physical_mass_flux": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "read_policy": {
            "prepare_opened_h5": False,
            "prepare_opened_jsonl": False,
            "prepare_opened_bi4": False,
            "prepare_opened_obi4": False,
            "native_payload_read": False,
            "solver_started": False,
            "audit_inputs": "ROOT266 proof/report, ROOT258 proof/reports, immutable typed summary JSON, and ROOT264 V9 overlay only",
        },
        "resource_policy": {
            "cpu_threads": 1,
            "max_wall_seconds": 900,
            "memory_max_bytes": 1024 * 1024 * 1024,
            "small_json_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()),
            "h5_content_read": False,
            "jsonl_content_read": False,
            "native_payload_read": False,
        },
    }
    manifest_path = output_root / "root270-impact-sidecar-manifest.json"
    _atomic(manifest_path, manifest)
    manifest_ref = _ref(manifest_path, "ROOT270 manifest")
    refs[str(manifest_path)] = manifest_ref
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    request_path = args.request_output.expanduser().resolve()
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/root270-impact-sidecar.json"]
    request = {
        "schema": "ds02.request.v1",
        "shared_runtime_version": "v8",
        "family_id": "INFRA",
        "case_id": "ROOT270_TYPED_NATIVE_IMPACT_SIDECAR_V2",
        "attempt_id": "root270-typed-native-impact-sidecar-v2-root-forward",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": MAX_OUTPUT,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()),
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY),
        "command": command,
        "input_files": sorted(input_sha),
        "input_sha256": input_sha,
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "source_proofs": proof_roles,
        "claim_boundary": manifest["claim_boundary"],
        "read_policy": manifest["read_policy"],
        "execution_allowed": True,
        "launch_allowed": True,
        "launch_owner": "root",
        "request_note": "Additive ROOT270 source-bound V2. ROOT266's 19 typed-summary sources remain unchanged; seven actual ROOT258 native reports replace the prior unavailable F6 native bindings. Typed-only native fields are UNKNOWN/null. Mass loss is a saved-mask diagnostic only; native row mass is audited only when supplied, otherwise the role-average proxy is explicitly unverified. Physical flux/fate/dynamics/Q remain UNKNOWN.",
    }
    _atomic(request_path, request)
    return {
        "status": manifest["status"],
        "manifest": str(manifest_path),
        "manifest_sha256": _digest(manifest_path, "ROOT270 manifest", limit=MAX_OUTPUT),
        "request": str(request_path),
        "request_sha256": _digest(request_path, "ROOT270 request", limit=MAX_OUTPUT),
        "case_count": len(cases),
        "native_rebindings": len(root258_cases),
        "legacy_typed_only_rebound": sum(case["source_v1"].get("status") == "TYPED_ONLY_NO_NATIVE_JOIN" for case in cases),
        "native_per_row_mass_unknown": sum(case["semantic_v2"]["native_binding"].get("native_exact_mass_rows") is None for case in cases),
        "payload_content_opened": False,
        "launch_allowed": True,
    }


def _audit_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _json(manifest_path, "ROOT270 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_SOURCE_ONLY_ROOT270_ADDITIVE_NATIVE_REBIND_IMPACT_DIAGNOSTIC":
        raise ImpactV2Error("ROOT270 manifest schema/status differs")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 19 or len({case.get("physical_case_id") for case in cases if isinstance(case, dict)}) != 19:
        raise ImpactV2Error("ROOT270 manifest must contain 19 unique cases")
    for ref in manifest.get("source_refs", []):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise ImpactV2Error("ROOT270 source ref is malformed")
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise ImpactV2Error("ROOT270 manifest contains a payload source ref")
        checked = _ref(Path(ref["path"]), "ROOT270 source ref", ref.get("sha256"))
        if checked["sha256"] != ref.get("sha256"):
            raise ImpactV2Error("ROOT270 source ref changed")
    return manifest, cases


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest, cases = _audit_manifest(args.manifest)
    results: list[dict[str, Any]] = []
    for entry in cases:
        case_id = entry.get("physical_case_id")
        try:
            if not isinstance(case_id, str):
                raise ImpactV2Error("case has no physical_case_id")
            typed_ref = entry["typed_summary"]
            typed_path = _path(typed_ref["path"], f"{case_id} typed summary")
            if _digest(typed_path, f"{case_id} typed summary", limit=MAX_SMALL) != _sha(typed_ref["sha256"], f"{case_id} typed summary SHA"):
                raise ImpactV2Error(f"{case_id} typed summary changed")
            summary = _json(typed_path, f"{case_id} typed summary")
            _validate_summary(summary, case_id)
            native_binding = entry["semantic_v2"]["native_binding"]
            source = native_binding.get("source")
            native_ref = native_binding.get("report")
            if source == "UNKNOWN_NO_NATIVE_BINDING":
                if native_ref is not None or any(native_binding.get(field) is not None for field in ("native_target_count", "native_exact_initial_mass_kg", "native_exact_mass_rows", "role_average_proxy_mass_kg")):
                    raise ImpactV2Error(f"{case_id} typed-only native fields are not UNKNOWN/null")
                semantic = _semantic_case(entry, summary, None)
                semantic["native_binding"]["source"] = source
            else:
                if not isinstance(native_ref, dict):
                    raise ImpactV2Error(f"{case_id} native binding has no report")
                report_path = _path(native_ref["path"], f"{case_id} native report")
                if _digest(report_path, f"{case_id} native report", limit=MAX_SMALL) != _sha(native_ref["sha256"], f"{case_id} native report SHA"):
                    raise ImpactV2Error(f"{case_id} native report changed")
                report = _json(report_path, f"{case_id} native report")
                if report.get("physical_case_id") != case_id:
                    raise ImpactV2Error(f"{case_id} native report identity changed")
                native_rows = _native_rows(report, case_id)
                expected = native_binding.get("native_target_count")
                if expected is not None and expected != len(native_rows):
                    raise ImpactV2Error(f"{case_id} native target count changed")
                semantic = _semantic_case(entry, summary, native_rows)
                semantic["native_binding"]["source"] = source
                semantic["native_binding"]["report"] = native_ref
            results.append({"physical_case_id": case_id, "family_id": entry.get("family_id"), "status": "COMPLETED_SAVED_MASK_SAMPLE_MASS_IMPACT_DIAGNOSTIC_ONLY", "semantic_v2": semantic, "source_v1": entry.get("source_v1"), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
        except (ImpactV2Error, OSError, KeyError, TypeError, ValueError) as exc:
            results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    failed = [row for row in results if row.get("status") == "FAILED"]
    typed_only = [row for row in results if row.get("semantic_v2", {}).get("native_binding", {}).get("source") == "UNKNOWN_NO_NATIVE_BINDING"]
    native_rebound = [row for row in results if row.get("semantic_v2", {}).get("native_binding", {}).get("source") == "ROOT258_ACTUAL_NATIVE_REPORT_REBOUND"]
    legacy_rebound = [row for row in results if row.get("source_v1", {}).get("status") == "TYPED_ONLY_NO_NATIVE_JOIN"]
    mass_unknown = [row for row in results if row.get("semantic_v2", {}).get("native_binding", {}).get("native_exact_mass_rows") is None]
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_JSON_ONLY_ROOT270_TYPED_NATIVE_IMPACT_DIAGNOSTIC",
        "source_manifest": {"path": str(Path(args.manifest).expanduser().resolve()), "sha256": _digest(args.manifest, "ROOT270 manifest", limit=MAX_OUTPUT)},
        "case_results": results,
        "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed), "typed_only_native_binding_unknown": len(typed_only), "legacy_v1_typed_only_rebound": len(legacy_rebound), "root258_native_rebound": len(native_rebound), "native_per_row_mass_unknown": len(mass_unknown)},
        "claim_boundary": manifest["claim_boundary"],
        "read_policy": {"typed_summary_read": True, "native_case_report_read": True, "h5_content_read": False, "jsonl_content_read": False, "bi4_content_read": False, "obi4_content_read": False, "native_payload_read": False, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "semantic_note": "ROOT266's 19 typed-summary sources are unchanged. Seven actual ROOT258 native reports are rebound. Typed-only native quantities are UNKNOWN/null, not zero. Per-row native initial mass is audited only when present; role-average mass is an explicitly unverified proxy.",
    }
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).expanduser().resolve()), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"], "typed_only_native_binding_unknown": report["counts"]["typed_only_native_binding_unknown"], "legacy_v1_typed_only_rebound": report["counts"]["legacy_v1_typed_only_rebound"], "root258_native_rebound": report["counts"]["root258_native_rebound"], "native_per_row_mass_unknown": report["counts"]["native_per_row_mass_unknown"]}


def _self_test() -> dict[str, Any]:
    summary = {"role_ledgers": {"fluid": {"initial_count": 4, "initial_mass_kg": 4.0, "units": {"mass": "kg", "time": "s"}, "active_count_by_frame": [4, 3], "active_mass_kg_by_frame": [4.0, 3.0]}}, "timeline": {"time_s": [0.0, 1.0]}}
    entry = {"physical_case_id": "FIXTURE", "family_id": "F6"}
    typed = _semantic_case(entry, summary, None)
    binding = typed["native_binding"]
    if binding["native_target_count"] is not None or binding["native_exact_initial_mass_kg"] is not None or binding["role_average_proxy_mass_kg"] is not None:
        raise ImpactV2Error("typed-only fields were encoded as a zero/proxy")
    native = [{"identity_key": [0, 2], "frame": 1, "time_s": 1.0, "bracket_s": [0.5, 1.5], "motive_code": 1, "initial_mass_kg": 1.25}]
    typed_native = _semantic_case(entry, summary, native)
    if typed_native["native_binding"]["native_exact_initial_mass_kg"] != 1.25:
        raise ImpactV2Error("per-row native initial mass was not audited")
    if typed_native["native_binding"]["proxy_uniformity"] != "UNVERIFIED_ROLE_AVERAGE_PROXY_ONLY":
        raise ImpactV2Error("proxy uniformity boundary was lost")
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "payload_opened": False, "checks": ["19-source preservation contract", "seven actual native rebindings", "typed-only native fields UNKNOWN/null", "per-row mass only when supplied", "role-average proxy explicitly unverified", "flux/fate/dynamics/Q remain UNKNOWN"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--root266-proof", type=Path, required=True)
    prep.add_argument("--root266-report", type=Path, required=True)
    prep.add_argument("--root266-manifest", type=Path, required=True)
    prep.add_argument("--root258-proof", type=Path, required=True)
    prep.add_argument("--root264-overlay", type=Path, default=ROOT264_OVERLAY)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--manifest", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (ImpactV2Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ROOT270_IMPACT_SIDECAR_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
