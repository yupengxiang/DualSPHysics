#!/usr/bin/env python3
"""Prepare/audit the additive ROOT270 V3 native/typed mass sidecar.

ROOT270 V2 correctly reported saved-mask impact and rebound seven small native
reports, but its source contract did not read the typed lifecycle JSONL.  V3
adds a deliberately narrow guarded consumer: for each selected native
``(Zone, Idp)`` row it streams the corresponding deferred V4 records JSONL and
uses the row's own ``initial_mass_kg`` when present.  A missing mass remains
``null``.  A role-average mass is never substituted for a particle mass.

Preparation reads only the ROOT270/ROOT258 proofs, small reports, manifests,
and source code.  The JSONL files are deferred to ``audit`` after the shared
parent reservation; this preparer never opens, hashes, or stats their content.
The output is a saved-record/sample diagnostic.  Physical flux, fate,
dynamics, continuous event time, and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import ds_data02_stage2_build_root270_impact_sidecar as root270


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ORIGINAL = Path("/home/jade/Projects/DualSPHysics")
LAB = ORIGINAL / "lagrangian-fluid-lab"
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
VENV = LAB / ".venv/bin/python"
PYVENV = LAB / ".venv/pyvenv.cfg"
RUNTIME = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
ROOT270_V2 = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_root270_impact_sidecar.py"
ROOT266_V1 = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_root266_impact_sidecar.py"
CURRENT = STAGE2 / "CURRENT336.json"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ROOT270_PROOF_DEFAULT = STAGE2 / "checkpoints/TYPED_NATIVE_SAMPLE_IMPACT_V2_ACTUAL_ROOT_VERIFICATION_270.json"
ROOT270_MANIFEST_DEFAULT = STAGE2 / "requests/root270-impact-sidecar-prepared-004/root270-impact-sidecar-manifest.json"
ROOT270_REPORT_DEFAULT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/ROOT270_TYPED_NATIVE_IMPACT_SIDECAR_V2/root270-typed-native-impact-sidecar-v2-root-forward-root-forward-030-001/root270-impact-sidecar.json")
ROOT258_PROOF_DEFAULT = STAGE2 / "checkpoints/GENERIC_NATIVE_EXTRACT_F6_V1_ACTUAL_ROOT_VERIFICATION_258.json"

MAX_SMALL = 10 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
MAX_JSONL_LINE = 4 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
RECORD_SCHEMA = "ds02.stage2.typed-lifecycle-records.v4"
RECORD_FIELDS = "one row per static (Zone, Idp); saved-frame lifecycle only"
MANIFEST_SCHEMA = "ds02.stage2.root270-impact-sidecar.v3"
REPORT_SCHEMA = "ds02.stage2.root270-impact-sidecar-report.v3"


class ImpactV3Error(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ImpactV3Error(f"{label} is not a SHA-256 digest")
    return value.lower()


def _path(value: Any, label: str, *, payload: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise ImpactV3Error(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ImpactV3Error(f"{label} is missing: {path}")
    if not payload and path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise ImpactV3Error(f"{label} is a payload in the static closure: {path}")
    return path


def _stat(path: Path, label: str, *, payload: bool = False) -> dict[str, Any]:
    path = _path(path, label, payload=payload)
    st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino)}


def _digest(path: Path, label: str, *, limit: int | None = MAX_SMALL, payload: bool = False) -> str:
    path = _path(path, label, payload=payload)
    if limit is not None and path.stat().st_size > limit:
        raise ImpactV3Error(f"{label} exceeds the bounded read")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL:
        raise ImpactV3Error(f"{label} exceeds the small JSON bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ImpactV3Error(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ImpactV3Error(f"{label} must be an object")
    return value


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL:
        raise ImpactV3Error(f"{label} exceeds the small source bound")
    actual = _digest(path, label)
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual != _sha(expected, f"{label} expected SHA"):
        raise ImpactV3Error(f"{label} SHA differs")
    value.update({"sha256": actual, "content_opened": True})
    return value


def _deferred_ref(value: Any, label: str) -> dict[str, Any]:
    """Validate proof metadata without touching the deferred JSONL path."""
    if not isinstance(value, dict):
        raise ImpactV3Error(f"{label} is not a deferred source object")
    required = ("path", "sha256", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "rows")
    if any(key not in value for key in required):
        raise ImpactV3Error(f"{label} lacks a complete deferred stat/SHA contract")
    path_text = value["path"]
    if not isinstance(path_text, str) or Path(path_text).suffix.lower() != ".jsonl":
        raise ImpactV3Error(f"{label} is not a JSONL payload path")
    digest = _sha(value["sha256"], f"{label} SHA")
    ints = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "rows")
    if any(isinstance(value[key], bool) or not isinstance(value[key], int) for key in ints):
        raise ImpactV3Error(f"{label} has non-integer deferred stat/row fields")
    if value["bytes"] <= 0 or value["rows"] <= 0:
        raise ImpactV3Error(f"{label} has non-positive deferred size/rows")
    if value.get("deferred") is not True or value.get("content_opened_by_preparer") is not False or value.get("read_after_parent_reservation") is not True:
        raise ImpactV3Error(f"{label} is not explicitly deferred until parent reservation")
    return {
        "path": path_text, "sha256": digest, "bytes": value["bytes"], "mtime_ns": value["mtime_ns"],
        "ctime_ns": value["ctime_ns"], "st_dev": value["st_dev"], "st_ino": value["st_ino"],
        "rows": value["rows"], "deferred": True, "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
    }


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ImpactV3Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise ImpactV3Error(f"{path} exceeds output bound")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _add_ref(refs: dict[str, dict[str, Any]], ref: dict[str, Any]) -> None:
    old = refs.get(ref["path"])
    if old is not None and old["sha256"] != ref["sha256"]:
        raise ImpactV3Error(f"conflicting source SHA for {ref['path']}")
    refs[ref["path"]] = ref


def _proof_case_rows(proof: dict[str, Any], label: str) -> list[dict[str, Any]]:
    if proof.get("schema") != root270.PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise ImpactV3Error(f"{label} is not a completed verified proof")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        raise ImpactV3Error(f"{label} lacks case_verifications")
    completed = proof.get("actual_completed_physical_cases")
    if not isinstance(completed, int) or completed != len(rows):
        raise ImpactV3Error(f"{label} completed count differs from case rows")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise ImpactV3Error(f"{label} has malformed case row")
        case_id = row["physical_case_id"]
        if case_id in seen:
            raise ImpactV3Error(f"{label} duplicates {case_id}")
        seen.add(case_id)
        result.append(row)
    return result


def _selected_native_rows(report: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    try:
        rows = root270._native_rows(report, case_id)
    except (root270.ImpactV2Error, KeyError, TypeError, ValueError) as exc:
        raise ImpactV3Error(str(exc)) from exc
    seen: set[tuple[int, int]] = set()
    selected: list[dict[str, Any]] = []
    for row in rows:
        key = row.get("identity_key")
        if not isinstance(key, list) or len(key) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in key):
            raise ImpactV3Error(f"{case_id} native identity is not an integer (Zone, Idp)")
        pair = (int(key[0]), int(key[1]))
        if pair in seen:
            raise ImpactV3Error(f"{case_id} native rows duplicate {pair}")
        seen.add(pair)
        selected.append(dict(row))
    if not selected:
        raise ImpactV3Error(f"{case_id} has no selected native IDs")
    return selected


def _root270_context(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    manifest_ref = _small_ref(args.root270_manifest, "ROOT270 V2 manifest")
    manifest = _json(args.root270_manifest, "ROOT270 V2 manifest")
    if manifest.get("schema") != root270.MANIFEST_SCHEMA or manifest.get("status") != "READY_SOURCE_ONLY_ROOT270_ADDITIVE_NATIVE_REBIND_IMPACT_DIAGNOSTIC":
        raise ImpactV3Error("ROOT270 V2 manifest schema/status differs")
    if int(manifest.get("case_count", -1)) != 19:
        raise ImpactV3Error("ROOT270 V2 manifest is not the immutable 19-case source")
    proof_ref = _small_ref(args.root270_proof, "ROOT270 V2 actual proof")
    proof = _json(args.root270_proof, "ROOT270 V2 actual proof")
    proof_rows = _proof_case_rows(proof, "ROOT270 V2 actual proof")
    if len(proof_rows) != 19:
        raise ImpactV3Error("ROOT270 V2 actual proof does not contain 19 cases")
    report_ref = _small_ref(args.root270_report, "ROOT270 V2 actual report")
    report = _json(args.root270_report, "ROOT270 V2 actual report")
    if report.get("schema") != root270.REPORT_SCHEMA or not str(report.get("status", "")).startswith("COMPLETED"):
        raise ImpactV3Error("ROOT270 V2 actual report is not completed")
    report_rows = report.get("case_results")
    if not isinstance(report_rows, list) or len(report_rows) != 19:
        raise ImpactV3Error("ROOT270 V2 actual report case count differs")
    proof_ids = {row["physical_case_id"] for row in proof_rows}
    report_ids = {row.get("physical_case_id") for row in report_rows if isinstance(row, dict)}
    manifest_ids = {row.get("physical_case_id") for row in manifest.get("cases", []) if isinstance(row, dict)}
    if proof_ids != report_ids or proof_ids != manifest_ids:
        raise ImpactV3Error("ROOT270 V2 proof/report/manifest case identities differ")
    if str(proof.get("manifest")) != str(args.root270_manifest.expanduser().resolve()):
        raise ImpactV3Error("ROOT270 actual proof does not bind the supplied immutable manifest")
    if str(proof.get("report")) != str(args.root270_report.expanduser().resolve()):
        raise ImpactV3Error("ROOT270 actual proof does not bind the supplied immutable report")
    by_id = {row["physical_case_id"]: row for row in proof_rows}
    refs: dict[str, dict[str, Any]] = {manifest_ref["path"]: manifest_ref, proof_ref["path"]: proof_ref, report_ref["path"]: report_ref}
    # Preserve the V2 small source closure, but never promote its deferred or
    # payload entries into the V3 static input closure.
    for ref_value in manifest.get("source_refs", []):
        if not isinstance(ref_value, dict) or not isinstance(ref_value.get("path"), str):
            raise ImpactV3Error("ROOT270 source_refs contains a malformed entry")
        path = Path(ref_value["path"])
        if path.suffix.lower() in PAYLOAD_SUFFIXES:
            raise ImpactV3Error("ROOT270 V2 static closure contains a payload")
        checked = _small_ref(path, "ROOT270 preserved source ref", ref_value.get("sha256"))
        _add_ref(refs, checked)
    return manifest, proof, report, {"manifest": manifest_ref, "proof": proof_ref, "report": report_ref}, by_id | {"__refs__": refs}


def _load_selected(args: argparse.Namespace, v2_by_id: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    proof_ref = _small_ref(args.root258_proof, "ROOT258 actual proof")
    proof = _json(args.root258_proof, "ROOT258 actual proof")
    rows = _proof_case_rows(proof, "ROOT258 actual proof")
    if len(rows) != 7 or proof.get("actual_completed_physical_cases") != 7:
        raise ImpactV3Error("ROOT258 selection must contain exactly seven completed cases")
    selected: list[dict[str, Any]] = []
    refs = {proof_ref["path"]: proof_ref}
    seen: set[str] = set()
    for proof_row in rows:
        case_id = proof_row["physical_case_id"]
        if case_id in seen:
            raise ImpactV3Error(f"ROOT258 duplicates {case_id}")
        seen.add(case_id)
        if case_id not in v2_by_id:
            raise ImpactV3Error(f"ROOT258 selection is outside ROOT270's 19 cases: {case_id}")
        record_ref = _deferred_ref(proof_row.get("typed_records_stat_SHA_only"), f"{case_id} typed records")
        report_path = proof_row.get("report")
        if not isinstance(report_path, str):
            raise ImpactV3Error(f"{case_id} ROOT258 report path is missing")
        report_ref = _small_ref(Path(report_path), f"{case_id} ROOT258 case report", proof_row.get("report_sha256"))
        report = _json(Path(report_ref["path"]), f"{case_id} ROOT258 case report")
        if report.get("physical_case_id") != case_id or report.get("family_id") != "F6" or report.get("status") != "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY":
            raise ImpactV3Error(f"{case_id} ROOT258 report identity/status differs")
        native_rows = _selected_native_rows(report, case_id)
        expected_count = proof_row.get("target_fluid_identity_count")
        if isinstance(expected_count, int) and expected_count != len(native_rows):
            raise ImpactV3Error(f"{case_id} ROOT258 selected ID count differs")
        v2_row = v2_by_id[case_id]
        typed_summary = v2_row.get("typed_summary")
        if not isinstance(typed_summary, str):
            raise ImpactV3Error(f"{case_id} ROOT270 proof lacks typed summary")
        typed_summary_ref = _small_ref(Path(typed_summary), f"{case_id} ROOT270 typed summary", v2_row.get("typed_summary_sha256"))
        selected_ids = []
        for row in native_rows:
            selected_ids.append({
                "identity_key": list(row["identity_key"]),
                "zone": int(row["identity_key"][0]), "idp": int(row["identity_key"][1]),
                "native_motive_code": row.get("motive_code"),
                "native_first_missing_frame": row.get("frame"),
                "native_first_missing_time_s": row.get("time_s"),
                "native_saved_bracket_s": row.get("bracket_s"),
                "native_row_initial_mass_kg": row.get("initial_mass_kg") if row.get("initial_mass_kg") is not None else None,
            })
        selected.append({
            "physical_case_id": case_id, "family_id": "F6", "selected_native_ids": selected_ids,
            "selected_native_id_count": len(selected_ids), "native_report": report_ref,
            "typed_summary": typed_summary_ref, "typed_records_deferred": record_ref,
            "typed_records_source": "ROOT258_TYPED_LIFECYCLE_V4_RECORDS_STAT_ONLY",
            "historical_118_membership": proof_row.get("new_original118_cause_bound_physical_case"),
            "native_report_claim_boundary": proof_row.get("physical_fate_legal_flux_dynamics_Q", "UNKNOWN"),
        })
        _add_ref(refs, report_ref)
        _add_ref(refs, typed_summary_ref)
    if len(selected) != 7 or len({row["physical_case_id"] for row in selected}) != 7:
        raise ImpactV3Error("ROOT258 selected source is not seven unique cases")
    return selected, refs


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    _manifest, root270_proof, root270_report, root270_refs, context = _root270_context(args)
    v2_by_id = {key: value for key, value in context.items() if key != "__refs__"}
    cases, selected_refs = _load_selected(args, v2_by_id)
    refs: dict[str, dict[str, Any]] = dict(context["__refs__"])
    for ref in selected_refs.values():
        _add_ref(refs, ref)
    for path, label in ((SCRIPT, "ROOT270 V3 worker"), (ROOT270_V2, "ROOT270 V2 worker"), (ROOT266_V1, "ROOT266 V1 worker"), (CURRENT, "CURRENT336"), (VENV, "literal Python interpreter"), (VENV.resolve(), "resolved Python interpreter"), (PYVENV, "pyvenv.cfg"), (RUNTIME, "runtime v8"), (DISPATCH, "dispatch v8")):
        _add_ref(refs, _small_ref(path, label, CURRENT_SHA if path == CURRENT else None))
    for ref in refs.values():
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise ImpactV3Error(f"payload entered ROOT270 V3 static closure: {ref['path']}")
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise ImpactV3Error(f"refusing to reuse output root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_SOURCE_ONLY_ROOT270_SELECTED_NATIVE_TYPED_JSONL_MASS_IMPACT",
        "namespace": "ROOT270_V3",
        "family_id": "F6",
        "root270_actual_context": {"proof": root270_refs["proof"], "report": root270_refs["report"], "manifest": root270_refs["manifest"], "case_count": 19},
        "root258_selection": {"proof": selected_refs[next(path for path in selected_refs if path.endswith("GENERIC_NATIVE_EXTRACT_F6_V1_ACTUAL_ROOT_VERIFICATION_258.json"))], "case_count": 7},
        "current_catalog": _small_ref(CURRENT, "CURRENT336", CURRENT_SHA),
        "case_count": len(cases), "cases": cases,
        "source_refs": sorted(refs.values(), key=lambda item: item["path"]),
        "deferred_payloads": [case["typed_records_deferred"] for case in cases],
        "claim_boundary": {
            "selected_typed_initial_mass": "EXACT_ONLY_WHEN_JSONL_ROW_HAS_FINITE_POSITIVE_INITIAL_MASS_KG",
            "missing_selected_typed_mass": "NULL_UNKNOWN; NEVER_ZERO",
            "native_report_initial_mass": "NULL_WHEN_NATIVE_ROW_HAS_NO_MASS_FIELD",
            "role_average_mass_proxy": "UNVERIFIED_PROXY_NOT_USED_AS_PER_ID_MASS",
            "saved_mask_mass_and_count": "DIAGNOSTIC_ONLY",
            "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN",
            "continuous_event_time": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "read_policy": {
            "prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False,
            "prepare_opened_obi4": False, "prepare_opened_native_payload": False, "solver_started": False,
            "audit_deferred_payloads": "After parent reservation only: three bounded JSONL passes per case (pre-hash, parse+hash, post-hash); small native reports are revalidated.",
        },
        "resource_policy": {
            "cpu_threads": 1, "max_wall_seconds": 1200, "memory_max_bytes": 1024 * 1024 * 1024,
            "small_json_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()),
            "deferred_jsonl_read_bytes_lower_bound": sum(int(case["typed_records_deferred"]["bytes"]) * 3 for case in cases),
            "deferred_jsonl_output_bytes": MAX_OUTPUT, "native_payload_read": False,
        },
    }
    manifest_path = output_root / "root270-impact-sidecar-v3-manifest.json"
    _atomic(manifest_path, manifest)
    manifest_ref = _small_ref(manifest_path, "ROOT270 V3 manifest")
    refs[str(manifest_path)] = manifest_ref
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    request_path = args.request_output.expanduser().resolve()
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/root270-impact-sidecar-v3.json"]
    deferred_paths = [case["typed_records_deferred"]["path"] for case in cases]
    request = {
        "schema": "ds02.request.v1", "shared_runtime_version": "v8", "family_id": "INFRA",
        "case_id": "ROOT270_TYPED_NATIVE_IMPACT_SIDECAR_V3", "attempt_id": "root270-typed-native-impact-sidecar-v3-root-forward",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 1200, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_OUTPUT,
        "estimated_input_read_bytes": int(manifest["resource_policy"]["small_json_read_bytes"] + manifest["resource_policy"]["deferred_jsonl_read_bytes_lower_bound"]),
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command,
        "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": deferred_paths,
        "deferred_input_contracts": [{"path": case["typed_records_deferred"]["path"], "sha256": case["typed_records_deferred"]["sha256"], "bytes": case["typed_records_deferred"]["bytes"], "rows": case["typed_records_deferred"]["rows"], "read_after_parent_reservation": True} for case in cases],
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "source_proofs": [root270_refs["proof"], root258_proof_ref := selected_refs[next(path for path in selected_refs if path.endswith("GENERIC_NATIVE_EXTRACT_F6_V1_ACTUAL_ROOT_VERIFICATION_258.json"))]],
        "claim_boundary": manifest["claim_boundary"], "read_policy": manifest["read_policy"],
        "execution_allowed": True, "launch_allowed": True, "launch_owner": "root",
        "request_note": "Additive ROOT270 V3. Selected native (Zone, Idp) rows are joined to deferred V4 JSONL records. Per-ID typed initial mass is used only when present and finite; absent mass remains null. No role-average proxy is converted to particle mass. Saved-mask impact is diagnostic and physical fate/flux/dynamics/Q remain UNKNOWN.",
    }
    _atomic(request_path, request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT270 V3 manifest"), "request": str(request_path), "request_sha256": _digest(request_path, "ROOT270 V3 request"), "case_count": len(cases), "selected_native_ids": sum(case["selected_native_id_count"] for case in cases), "deferred_jsonl_cases": len(deferred_paths), "payload_content_opened": False, "launch_allowed": True}


def _payload_stat(path: Path, label: str) -> dict[str, Any]:
    return _stat(path, label, payload=True)


def _payload_hash(path: Path, label: str) -> str:
    return _digest(path, label, limit=None, payload=True)


def _stat_equal(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    fields = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    for field in fields:
        if actual.get(field) != expected.get(field):
            raise ImpactV3Error(f"{label} {field} differs")


def _finite_mass(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ImpactV3Error(f"{label} is not finite positive mass")
    return float(value)


def _stream_typed_records(case: dict[str, Any]) -> dict[str, Any]:
    ref = case["typed_records_deferred"]
    path = _path(ref["path"], f"{case['physical_case_id']} deferred typed records", payload=True)
    pre_stat = _payload_stat(path, f"{case['physical_case_id']} typed records pre-read")
    _stat_equal(pre_stat, ref, f"{case['physical_case_id']} typed records pre-stat")
    pre_sha = _payload_hash(path, f"{case['physical_case_id']} typed records pre-read")
    if pre_sha != ref["sha256"]:
        raise ImpactV3Error(f"{case['physical_case_id']} typed records pre-SHA differs")
    targets = {(int(item["zone"]), int(item["idp"])): item for item in case["selected_native_ids"]}
    found: dict[tuple[int, int], dict[str, Any]] = {}
    seen: set[tuple[int, int]] = set()
    total_rows = 0
    fluid_rows = 0
    fluid_mass = 0.0
    fluid_mass_missing = False
    header: dict[str, Any] | None = None
    stream_digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            if len(raw) > MAX_JSONL_LINE:
                raise ImpactV3Error(f"{case['physical_case_id']} JSONL line exceeds bound")
            stream_digest.update(raw)
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ImpactV3Error(f"{case['physical_case_id']} malformed JSONL line {line_number}") from exc
            if line_number == 1:
                if not isinstance(value, dict) or value.get("schema") != RECORD_SCHEMA or value.get("physical_case_id") != case["physical_case_id"] or value.get("record_fields") != RECORD_FIELDS:
                    raise ImpactV3Error(f"{case['physical_case_id']} typed JSONL header differs from V4 producer contract")
                header = value
                continue
            if not isinstance(value, dict):
                raise ImpactV3Error(f"{case['physical_case_id']} JSONL row is not an object")
            zone, idp = value.get("zone"), value.get("idp")
            if isinstance(zone, bool) or isinstance(idp, bool) or not isinstance(zone, int) or not isinstance(idp, int):
                raise ImpactV3Error(f"{case['physical_case_id']} JSONL identity is not integer at line {line_number}")
            key = (int(zone), int(idp))
            if key in seen:
                raise ImpactV3Error(f"{case['physical_case_id']} JSONL duplicate identity {key}")
            seen.add(key)
            total_rows += 1
            role = value.get("initial_role")
            type_code = value.get("initial_type_code")
            is_fluid = role == "fluid" or type_code == 3
            if role == "fluid" and type_code not in (None, 3):
                raise ImpactV3Error(f"{case['physical_case_id']} fluid role/type mismatch for {key}")
            if type_code == 3 and role not in (None, "fluid"):
                raise ImpactV3Error(f"{case['physical_case_id']} fluid type/role mismatch for {key}")
            mass = _finite_mass(value.get("initial_mass_kg"), f"{case['physical_case_id']} {key} initial mass")
            if is_fluid:
                fluid_rows += 1
                if mass is None:
                    fluid_mass_missing = True
                else:
                    fluid_mass += mass
            if key in targets:
                if key in found:
                    raise ImpactV3Error(f"{case['physical_case_id']} selected identity repeated")
                found[key] = {"initial_mass_kg": mass, "initial_role": role, "initial_type_code": type_code, "first_disappeared_frame": value.get("first_disappeared_frame"), "first_disappeared_time_s": value.get("first_disappeared_time_s"), "censoring": value.get("censoring")}
    if header is None or total_rows != int(ref["rows"]):
        raise ImpactV3Error(f"{case['physical_case_id']} typed JSONL row count differs")
    missing = sorted(set(targets) - set(found))
    if missing:
        raise ImpactV3Error(f"{case['physical_case_id']} selected native IDs missing from typed JSONL: {missing[:3]}")
    stream_sha = stream_digest.hexdigest()
    if stream_sha != ref["sha256"]:
        raise ImpactV3Error(f"{case['physical_case_id']} typed JSONL parse-pass SHA differs")
    post_stat = _payload_stat(path, f"{case['physical_case_id']} typed records post-read")
    _stat_equal(post_stat, pre_stat, f"{case['physical_case_id']} typed records post-stat")
    post_sha = _payload_hash(path, f"{case['physical_case_id']} typed records post-read")
    if post_sha != pre_sha:
        raise ImpactV3Error(f"{case['physical_case_id']} typed records post-SHA differs")
    return {"header": header, "rows": total_rows, "found": found, "fluid_initial_count": fluid_rows, "fluid_initial_mass_kg": None if fluid_mass_missing else fluid_mass, "fluid_initial_mass_missing": fluid_mass_missing, "pre_stat": pre_stat, "post_stat": post_stat, "pre_sha256": pre_sha, "stream_sha256": stream_sha, "post_sha256": post_sha, "hash_passes": 3}


def _audit_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = case["physical_case_id"]
    native_ref = case["native_report"]
    native_path = _path(native_ref["path"], f"{case_id} native report")
    if _digest(native_path, f"{case_id} native report") != _sha(native_ref["sha256"], f"{case_id} native report SHA"):
        raise ImpactV3Error(f"{case_id} native report changed")
    native_report = _json(native_path, f"{case_id} native report")
    native_rows = _selected_native_rows(native_report, case_id)
    if len(native_rows) != case["selected_native_id_count"]:
        raise ImpactV3Error(f"{case_id} native selected count changed")
    native_keys = {tuple(row["identity_key"]) for row in native_rows}
    expected_keys = {tuple(item["identity_key"]) for item in case["selected_native_ids"]}
    if native_keys != expected_keys:
        raise ImpactV3Error(f"{case_id} native selected identity set changed")
    typed = _stream_typed_records(case)
    per_id = []
    masses: list[float] = []
    for item in case["selected_native_ids"]:
        key = (int(item["zone"]), int(item["idp"]))
        row = typed["found"][key]
        mass = row["initial_mass_kg"]
        if mass is not None:
            masses.append(mass)
        native_mass = item.get("native_row_initial_mass_kg")
        per_id.append({**item, "typed_initial_mass_kg": mass, "typed_mass_status": "EXACT_TYPED_JSONL_INITIAL_MASS" if mass is not None else "UNKNOWN_MISSING_TYPED_INITIAL_MASS", "native_report_initial_mass_kg": native_mass if native_mass is not None else None, "typed_initial_role": row.get("initial_role"), "typed_initial_type_code": row.get("initial_type_code"), "typed_first_disappeared_frame": row.get("first_disappeared_frame"), "typed_first_disappeared_time_s": row.get("first_disappeared_time_s"), "typed_censoring": row.get("censoring"), "role_average_proxy_mass_kg": None, "role_average_proxy_status": "UNVERIFIED_NOT_USED_AS_PER_ID_MASS"})
    exact_selected_sum = sum(masses) if len(masses) == len(per_id) else None
    return {
        "physical_case_id": case_id, "family_id": case["family_id"], "status": "COMPLETED_SELECTED_NATIVE_TYPED_INITIAL_MASS_DIAGNOSTIC_ONLY",
        "selected_native_ids": per_id, "selected_native_id_count": len(per_id),
        "typed_records": {"path": case["typed_records_deferred"]["path"], "rows": typed["rows"], "pre_stat": typed["pre_stat"], "post_stat": typed["post_stat"], "pre_sha256": typed["pre_sha256"], "stream_sha256": typed["stream_sha256"], "post_sha256": typed["post_sha256"], "hash_passes": typed["hash_passes"]},
        "typed_fluid_initial_count": typed["fluid_initial_count"], "typed_fluid_initial_mass_kg": typed["fluid_initial_mass_kg"],
        "selected_typed_initial_mass_sum_kg": exact_selected_sum,
        "selected_typed_initial_mass_status": "EXACT_ALL_SELECTED_ROWS" if exact_selected_sum is not None else "UNKNOWN_AT_LEAST_ONE_SELECTED_ROW_MASS_MISSING",
        "role_average_proxy_mass_kg": None, "role_average_proxy_status": "UNVERIFIED_NOT_USED_AS_PER_ID_MASS",
        "impact": {"selected_saved_native_identity_count": len(per_id), "selected_typed_initial_mass_kg": exact_selected_sum, "typed_fluid_initial_mass_kg": typed["fluid_initial_mass_kg"], "diagnostic_only": True, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _validate_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _json(path, "ROOT270 V3 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_SOURCE_ONLY_ROOT270_SELECTED_NATIVE_TYPED_JSONL_MASS_IMPACT":
        raise ImpactV3Error("ROOT270 V3 manifest schema/status differs")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 7 or len({case.get("physical_case_id") for case in cases if isinstance(case, dict)}) != 7:
        raise ImpactV3Error("ROOT270 V3 manifest must contain seven unique cases")
    for ref in manifest.get("source_refs", []):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise ImpactV3Error("ROOT270 V3 static source ref is malformed/payload")
        checked = _small_ref(Path(ref["path"]), "ROOT270 V3 static source ref", ref.get("sha256"))
        if checked["sha256"] != ref.get("sha256"):
            raise ImpactV3Error("ROOT270 V3 static source changed")
    for case in cases:
        if not isinstance(case, dict):
            raise ImpactV3Error("ROOT270 V3 case is malformed")
        _deferred_ref(case.get("typed_records_deferred"), f"{case.get('physical_case_id')} typed records")
    return manifest, cases


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest, cases = _validate_manifest(args.manifest)
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            results.append(_audit_case(case))
        except (ImpactV3Error, OSError, KeyError, TypeError, ValueError) as exc:
            results.append({"physical_case_id": case.get("physical_case_id"), "family_id": case.get("family_id"), "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    failed = [row for row in results if row.get("status") == "FAILED"]
    complete = [row for row in results if row.get("status") != "FAILED"]
    report = {
        "schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_SELECTED_NATIVE_TYPED_INITIAL_MASS_DIAGNOSTIC_ONLY",
        "source_manifest": {"path": str(Path(args.manifest).expanduser().resolve()), "sha256": _digest(args.manifest, "ROOT270 V3 manifest")},
        "case_results": results, "counts": {"requested": len(results), "completed": len(complete), "failed": len(failed), "selected_native_ids": sum(int(row.get("selected_native_id_count", 0)) for row in complete)},
        "claim_boundary": manifest["claim_boundary"], "read_policy": {"typed_jsonl_opened_after_parent_reservation": True, "typed_jsonl_content_read": True, "native_case_report_read": True, "h5_content_read": False, "bi4_content_read": False, "obi4_content_read": False, "solver_started": False, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "semantic_note": "Only selected native identities are joined to their typed JSONL records. initial_mass_kg is exact only when present in that row; missing masses are null. Role-average mass proxies are explicitly not used. This is a saved-record/sample diagnostic and grants no physical fate/flux/dynamics/Q credit.",
    }
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).expanduser().resolve()), "completed": len(complete), "failed": len(failed), "selected_native_ids": report["counts"]["selected_native_ids"]}


def _self_test() -> dict[str, Any]:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "records.jsonl"
        header = {"schema": RECORD_SCHEMA, "status": "COMPLETED_TYPED_LIFECYCLE_RECORDS_NO_PHYSICAL_CREDIT", "family_id": "F6", "physical_case_id": "FIXTURE", "record_fields": RECORD_FIELDS}
        rows = [header, {"zone": 0, "idp": 10, "initial_type_code": 3, "initial_role": "fluid", "initial_mass_kg": 0.001, "first_disappeared_frame": 2, "first_disappeared_time_s": 1.0, "censoring": "OBSERVED_DISAPPEARANCE"}, {"zone": 0, "idp": 11, "initial_type_code": 3, "initial_role": "fluid", "initial_mass_kg": None, "first_disappeared_frame": 3, "first_disappeared_time_s": 1.5, "censoring": "OBSERVED_DISAPPEARANCE"}, {"zone": 0, "idp": 12, "initial_type_code": 1, "initial_role": "moving", "initial_mass_kg": 0.002, "first_disappeared_frame": None, "first_disappeared_time_s": None, "censoring": "ACTIVE_AT_WINDOW_END_RIGHT_CENSORED"}]
        path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
        st = path.stat()
        ref = {"path": str(path), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino, "rows": 3, "sha256": _digest(path, "fixture", limit=None, payload=True), "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
        case = {"physical_case_id": "FIXTURE", "family_id": "F6", "selected_native_ids": [{"identity_key": [0, 10], "zone": 0, "idp": 10, "native_motive_code": 1, "native_first_missing_frame": 2, "native_first_missing_time_s": 1.0, "native_saved_bracket_s": [0.5, 1.0], "native_row_initial_mass_kg": None}, {"identity_key": [0, 11], "zone": 0, "idp": 11, "native_motive_code": 1, "native_first_missing_frame": 3, "native_first_missing_time_s": 1.5, "native_saved_bracket_s": [1.0, 1.5], "native_row_initial_mass_kg": None}], "selected_native_id_count": 2, "typed_records_deferred": ref, "native_report": {"path": str(path), "sha256": ref["sha256"]}}
        result = _stream_typed_records(case)
        if result["found"][(0, 10)]["initial_mass_kg"] != 0.001 or result["found"][(0, 11)]["initial_mass_kg"] is not None:
            raise ImpactV3Error("fixture did not preserve exact/null per-ID mass")
        if result["fluid_initial_mass_kg"] is not None:
            raise ImpactV3Error("fixture missing fluid mass was incorrectly filled")
        if any(item.get("role_average_proxy_mass_kg") is not None for item in case["selected_native_ids"]):
            raise ImpactV3Error("fixture role-average proxy was used")
        bad = path.with_name("bad.jsonl")
        bad.write_text("\n".join(json.dumps(row, sort_keys=True) for row in [header, rows[1], rows[1]]) + "\n", encoding="utf-8")
        bad_ref = dict(ref); bad_ref.update({"path": str(bad), "bytes": bad.stat().st_size, "mtime_ns": bad.stat().st_mtime_ns, "ctime_ns": bad.stat().st_ctime_ns, "st_ino": bad.stat().st_ino, "rows": 2, "sha256": _digest(bad, "bad fixture", limit=None, payload=True)})
        bad_case = dict(case); bad_case["typed_records_deferred"] = bad_ref
        try:
            _stream_typed_records(bad_case)
        except ImpactV3Error:
            pass
        else:
            raise ImpactV3Error("duplicate identity fixture was accepted")
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "payload_opened": False, "checks": ["selected native (Zone, Idp) exact join", "typed JSONL initial mass exact-or-null", "missing mass never zero", "role-average proxy never used", "duplicate/full row contract"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--root270-proof", type=Path, default=ROOT270_PROOF_DEFAULT)
    prep.add_argument("--root270-manifest", type=Path, default=ROOT270_MANIFEST_DEFAULT)
    prep.add_argument("--root270-report", type=Path, default=ROOT270_REPORT_DEFAULT)
    prep.add_argument("--root258-proof", type=Path, default=ROOT258_PROOF_DEFAULT)
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
    except (ImpactV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ROOT270_IMPACT_SIDECAR_V3_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
