#!/usr/bin/env python3
"""Prepare and audit bounded native/typed mass diagnostics for exact joins.

This additive V6 consumer is intentionally a source adapter around the
already-consumed V4 stream reader.  The input catalogue contains 47 exact
native/typed joins, while the ROOT313 mass sidecar consumed 17 of them.  V6
selects the remaining rows in small, single-family batches (at most eight
cases) and normalizes the historical producer proof/report shapes:

* ROOT205/212/216/219 proofs are one-case documents with a top-level
  ``physical_case_id``;
* later producer proofs contain complete ``case_verifications`` arrays; and
* native case reports use either top-level ``rows``, ``native.rows``, or the
  generic ``rows`` representation.

Preparation reads only bounded JSON and source metadata.  Typed JSONL,
trajectory/H5, BI4, OBI4, and solver payloads remain deferred until a parent
reservation.  The audit result is a saved-record mass diagnostic only:
missing per-particle mass is null, role averages are never substituted, and
physical fate, flux, dynamics, and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(Path(__file__).resolve().parent))

import ds_data02_stage2_build_native_typed_mass_impact_v4 as v4
import ds_data02_stage2_build_root270_impact_sidecar_v3 as impact
import ds_data02_stage2_verify_generic_native_join_v3 as join_v3


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
SOURCE_DEFAULT = STAGE2 / "requests/native-typed-native-join-source-root315-prepared-001/native-typed-native-join-source-v1.json"
EXCLUDE_DEFAULT = STAGE2 / "requests/root313-native-typed-mass-impact-prepared-004/root313-native-typed-mass-impact-manifest.json"
CURRENT = impact.CURRENT
CURRENT_SHA = impact.CURRENT_SHA
VENV = v4.VENV
PYVENV = v4.PYVENV
RUNTIME = v4.RUNTIME
DISPATCH = v4.DISPATCH
ROOT266_V1 = v4.ROOT266_V1
ROOT270_V2 = v4.ROOT270_V2
ROOT270_V3 = v4.ROOT270_V2.replace("build_root270_impact_sidecar.py", "build_root270_impact_sidecar_v3.py") if isinstance(v4.ROOT270_V2, str) else (PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_root270_impact_sidecar_v3.py")
MAX_SMALL = 10 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
MANIFEST_SCHEMA = "ds02.stage2.native-typed-mass-impact.v6-manifest"
REPORT_SCHEMA = "ds02.stage2.native-typed-mass-impact.v6-report"


class MassV6Error(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise MassV6Error(f"{label} is not a SHA-256 digest")
    return value.lower()


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise MassV6Error(f"{label} is missing: {path}")
    st = path.stat()
    return {
        "path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino),
    }


def _digest(path: Path, label: str, *, limit: int | None = MAX_SMALL) -> str:
    path = Path(path).expanduser().resolve()
    size = path.stat().st_size
    if limit is not None and size > limit:
        raise MassV6Error(f"{label} exceeds bounded source read: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _small_ref(path: Path, label: str, expected: Any = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL:
        raise MassV6Error(f"{label} exceeds bounded source read")
    actual = _digest(path, label)
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual != _sha(expected, f"{label} expected SHA"):
        raise MassV6Error(f"{label} SHA differs")
    value["sha256"] = actual
    value["content_opened"] = True
    return value


def _json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.stat().st_size > MAX_SMALL:
        raise MassV6Error(f"{label} exceeds bounded JSON read")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MassV6Error(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise MassV6Error(f"{label} must be a JSON object")
    return value


def _atomic(path: Path, value: dict[str, Any], limit: int = MAX_OUTPUT) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise MassV6Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temp.stat().st_size > limit:
            raise MassV6Error(f"{path} exceeds output bound")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _deferred(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MassV6Error(f"{label} has no deferred record contract")
    path = value.get("path")
    if not isinstance(path, str) or Path(path).suffix.lower() != ".jsonl":
        raise MassV6Error(f"{label} is not a JSONL deferred path")
    required = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "rows", "sha256")
    if any(key not in value for key in required):
        raise MassV6Error(f"{label} lacks a complete pre/post stat/SHA declaration")
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "rows"):
        if isinstance(value[key], bool) or not isinstance(value[key], int):
            raise MassV6Error(f"{label}.{key} is not an integer")
    if value["bytes"] <= 0 or value["rows"] <= 0:
        raise MassV6Error(f"{label} has non-positive bytes/rows")
    if value.get("deferred") is not True or value.get("content_opened_by_preparer") is not False or value.get("read_after_parent_reservation") is not True:
        raise MassV6Error(f"{label} is not explicitly parent-deferred")
    return {key: value[key] for key in required} | {
        "path": path, "sha256": _sha(value["sha256"], f"{label}.sha256"),
        "deferred": True, "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
    }


def _records_contract(source_row: dict[str, Any], report: dict[str, Any], case_id: str) -> dict[str, Any]:
    """Normalize old single-case and batch report record-stat edges.

    ROOT220/226 reports put the records edge under ``typed.records``; old
    single-case reports put it at top-level.  No JSONL is opened here.
    """
    candidate: dict[str, Any] = {}
    if isinstance(source_row.get("typed_records_stat_only"), dict):
        candidate.update(source_row["typed_records_stat_only"])
    typed_parent = report.get("typed") if isinstance(report.get("typed"), dict) else None
    typed_records_parent = typed_parent.get("records") if isinstance(typed_parent, dict) else None
    for parent in (report.get("records"), typed_records_parent, typed_parent):
        if isinstance(parent, dict):
            for key, value in parent.items():
                candidate.setdefault(key, value)
    if not isinstance(candidate.get("path"), str):
        raise MassV6Error(f"{case_id} lacks a typed records path in source/report")
    pre = candidate.get("pre_stat") if isinstance(candidate.get("pre_stat"), dict) else None
    post = candidate.get("post_stat") if isinstance(candidate.get("post_stat"), dict) else None
    stat = pre or post
    if stat is not None:
        for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if key not in candidate and key in stat:
                candidate[key] = stat[key]
    if candidate.get("sha256") in (None, "PARENT_GUARD_COMPUTED"):
        if isinstance(candidate.get("observed_sha256"), str):
            candidate["sha256"] = candidate["observed_sha256"]
    candidate["deferred"] = True
    candidate["content_opened_by_preparer"] = False
    candidate["read_after_parent_reservation"] = True
    try:
        return _deferred(candidate, f"{case_id} typed records")
    except MassV6Error:
        # Keep the failure tied to the case.  A source row with no producer
        # record edge must never be repaired by a count or role average.
        raise


def _native_rows(report: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    """Normalize the actual small native report row variants."""
    # Prefer the report's joined rows when present: F4 V4 keeps native CSV
    # rows and the saved-frame identity/time join in separate arrays, and the
    # latter is the authoritative per-ID event edge.  Other producer reports
    # expose the same edge at top-level ``rows`` or ``native.rows``.
    exact = report.get("exact_join")
    raw: Any = exact.get("rows") if isinstance(exact, dict) else None
    if not isinstance(raw, list):
        raw = report.get("rows")
    if not isinstance(raw, list):
        native = report.get("native")
        raw = native.get("rows") if isinstance(native, dict) else None
    if not isinstance(raw, list) or not raw:
        raise MassV6Error(f"{case_id} native report has no per-ID rows")
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for raw_row in raw:
        if not isinstance(raw_row, dict):
            raise MassV6Error(f"{case_id} native row is not an object")
        key = raw_row.get("identity_key")
        if not (isinstance(key, list) and len(key) == 2):
            zone = raw_row.get("zone", 0)
            idp = raw_row.get("idp")
            key = [zone, idp]
        if any(isinstance(v, bool) or not isinstance(v, int) for v in key):
            raise MassV6Error(f"{case_id} native row identity is not integer")
        pair = (int(key[0]), int(key[1]))
        if pair in seen:
            raise MassV6Error(f"{case_id} native report duplicates identity {pair}")
        seen.add(pair)
        frame = raw_row.get("first_missing_frame", raw_row.get("native_first_missing_frame", raw_row.get("first_disappeared_frame", raw_row.get("typed_first_disappeared_frame"))))
        time_s = raw_row.get("first_missing_time_s", raw_row.get("native_first_missing_time_s", raw_row.get("first_disappeared_time_s", raw_row.get("typed_first_disappeared_time_s"))))
        bracket = raw_row.get("bracket_s", raw_row.get("native_first_missing_bracket_s", raw_row.get("first_disappeared_bracket_s", raw_row.get("typed_first_disappeared_bracket_s"))))
        if isinstance(frame, bool) or not isinstance(frame, int) or not isinstance(time_s, (int, float)) or isinstance(time_s, bool) or not math.isfinite(float(time_s)):
            raise MassV6Error(f"{case_id} native row saved-frame fields are malformed")
        if not isinstance(bracket, list) or len(bracket) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in bracket):
            raise MassV6Error(f"{case_id} native row bracket is malformed")
        motive = raw_row.get("motive_code", raw_row.get("native_motive_code"))
        if motive is not None and (isinstance(motive, bool) or not isinstance(motive, int)):
            raise MassV6Error(f"{case_id} native row motive is malformed")
        mass = raw_row.get("initial_mass_kg", raw_row.get("native_row_initial_mass_kg"))
        if mass is not None and (isinstance(mass, bool) or not isinstance(mass, (int, float)) or not math.isfinite(float(mass)) or float(mass) <= 0):
            raise MassV6Error(f"{case_id} native row mass is malformed")
        result.append({
            "identity_key": [pair[0], pair[1]], "zone": pair[0], "idp": pair[1],
            "frame": int(frame), "time_s": float(time_s), "bracket_s": [float(bracket[0]), float(bracket[1])],
            "motive_code": None if motive is None else int(motive), "initial_mass_kg": None if mass is None else float(mass),
        })
    return result


def _proof_rows(proof: dict[str, Any], label: str) -> list[str]:
    if proof.get("schema") != join_v3.PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise MassV6Error(f"{label} is not a completed actual producer proof")
    ids: list[str] = []
    rows = proof.get("case_verifications")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str):
                ids.append(row["physical_case_id"])
    top = proof.get("physical_case_id")
    if isinstance(top, str):
        ids.append(top)
    if not ids or len(ids) != len(set(ids)):
        raise MassV6Error(f"{label} lacks unique physical-case proof rows")
    return ids


def _load_source(source_path: Path, exclude_path: Path, *, family: str | None, batch_index: int | None, batch_size: int) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    source_ref = _small_ref(source_path, "native/typed join source")
    source = _json(source_path, "native/typed join source")
    if source.get("schema") != "ds02.stage2.native-typed-native-join-source-entry.v1":
        raise MassV6Error("native/typed join source schema differs")
    rows = source.get("actual_case_rows")
    if not isinstance(rows, list) or not rows:
        raise MassV6Error("native/typed join source has no actual rows")
    source_ids = [row.get("physical_case_id") for row in rows if isinstance(row, dict)]
    if len(rows) != 47 or len(source_ids) != len(set(source_ids)) or any(not isinstance(case_id, str) or not case_id for case_id in source_ids):
        raise MassV6Error("native/typed join source must contain 47 unique exact physical cases")
    exclude_ref = _small_ref(exclude_path, "ROOT313 exclusion manifest")
    exclude = _json(exclude_path, "ROOT313 exclusion manifest")
    excluded = {case.get("physical_case_id") for case in exclude.get("cases", []) if isinstance(case, dict)}
    if len(excluded) != 17 or any(not isinstance(item, str) for item in excluded):
        raise MassV6Error("ROOT313 exclusion set is malformed")
    if not excluded.issubset(set(source_ids)):
        raise MassV6Error("ROOT313 exclusion contains a case outside the exact join source")
    remaining = [row for row in rows if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str) and row["physical_case_id"] not in excluded]
    if len(remaining) != 30:
        raise MassV6Error(f"expected 30 remaining exact joins after ROOT313, got {len(remaining)}")
    if family is not None:
        remaining = [row for row in remaining if row.get("family_id") == family]
    remaining.sort(key=lambda row: (str(row.get("family_id")), int(row.get("current336_index", 10**9)), row["physical_case_id"]))
    if batch_index is not None:
        if batch_index < 0:
            raise MassV6Error("batch index must be non-negative")
        start = batch_index * batch_size
        remaining = remaining[start:start + batch_size]
    if not remaining:
        raise MassV6Error("selection is empty")
    if len(remaining) > batch_size:
        raise MassV6Error(f"selection exceeds batch size {batch_size}")
    return source_ref, exclude_ref, source, remaining


def _add_ref(refs: dict[str, dict[str, Any]], value: dict[str, Any]) -> None:
    old = refs.get(value["path"])
    if old is not None and old["sha256"] != value["sha256"]:
        raise MassV6Error(f"source SHA conflict for {value['path']}")
    refs[value["path"]] = value


def _normalize_case(row: dict[str, Any], proof_cache: dict[str, dict[str, Any]], refs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = row["physical_case_id"]
    report_decl = row.get("native_report")
    if not isinstance(report_decl, dict) or not isinstance(report_decl.get("path"), str):
        raise MassV6Error(f"{case_id} lacks native report ref")
    report_ref = _small_ref(Path(report_decl["path"]), f"{case_id} native report", report_decl.get("sha256"))
    report = _json(Path(report_ref["path"]), f"{case_id} native report")
    if report.get("physical_case_id") != case_id:
        raise MassV6Error(f"{case_id} native report identity differs")
    native_rows = _native_rows(report, case_id)
    records = _records_contract(row, report, case_id)
    _add_ref(refs, report_ref)

    proof_decl = row.get("producer_proof")
    if not isinstance(proof_decl, dict) or not isinstance(proof_decl.get("path"), str):
        raise MassV6Error(f"{case_id} lacks producer proof ref")
    proof_path = Path(proof_decl["path"])
    proof_ref = _small_ref(proof_path, f"{case_id} producer proof", proof_decl.get("sha256"))
    proof = proof_cache.get(proof_ref["path"])
    if proof is None:
        proof = _json(proof_path, f"{case_id} producer proof")
        proof_cache[proof_ref["path"]] = proof
    proof_ids = _proof_rows(proof, f"{case_id} producer proof")
    if case_id not in proof_ids:
        raise MassV6Error(f"{case_id} is absent from its producer proof")
    bundle_id = f"proof-{Path(proof_ref['path']).stem}"
    _add_ref(refs, proof_ref)
    summary_ref: dict[str, Any] | None = None
    summary_decl = row.get("typed_summary")
    if isinstance(summary_decl, dict) and isinstance(summary_decl.get("path"), str):
        summary_ref = _small_ref(Path(summary_decl["path"]), f"{case_id} typed summary", summary_decl.get("sha256"))
        _add_ref(refs, summary_ref)
    return {
        "physical_case_id": case_id, "family_id": row.get("family_id"),
        "current336_index": row.get("current336_index"), "native_cause": row.get("native_cause"),
        "producer_proof": proof_ref, "producer_proof_case_index": row.get("producer_proof_case_index"),
        "proof_bundle_id": bundle_id, "native_report": report_ref,
        "typed_summary": summary_ref, "typed_records_deferred": records,
        "selected_native_ids": [
            {"identity_key": item["identity_key"], "zone": item["zone"], "idp": item["idp"],
             "native_motive_code": item["motive_code"], "native_first_missing_frame": item["frame"],
             "native_first_missing_time_s": item["time_s"], "native_saved_bracket_s": item["bracket_s"],
             "native_row_initial_mass_kg": item["initial_mass_kg"]}
            for item in native_rows
        ],
        "selected_native_id_count": len(native_rows),
        "typed_records_source": "ACTUAL_PRODUCER_REPORT_RECORDS_STAT_EDGE; CONTENT_DEFERRED",
        "mass_impact_status": "NOT_MEASURED_BY_TYPED_NATIVE_JOIN_PROOF",
    }


def _prepare_one(args: argparse.Namespace, selected_family: str | None = None, batch_index: int | None = None, batch_id: str | None = None) -> dict[str, Any]:
    family = selected_family if selected_family is not None else args.family
    index = batch_index if batch_index is not None else args.batch_index
    source_ref, exclude_ref, source, rows = _load_source(args.source_join, args.exclude_manifest, family=family, batch_index=index, batch_size=args.batch_size)
    refs: dict[str, dict[str, Any]] = {source_ref["path"]: source_ref, exclude_ref["path"]: exclude_ref}
    proof_cache: dict[str, dict[str, Any]] = {}
    cases = [_normalize_case(row, proof_cache, refs) for row in rows]
    case_ids = [case["physical_case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise MassV6Error("selected cases are not unique")
    bundles: dict[str, dict[str, Any]] = {}
    for case in cases:
        bundle_id = case["proof_bundle_id"]
        proof_ref = case["producer_proof"]
        proof = proof_cache[proof_ref["path"]]
        ids = _proof_rows(proof, f"{bundle_id} proof")
        existing = bundles.get(bundle_id)
        if existing is None:
            existing = {"bundle_id": bundle_id, "family_id": case["family_id"], "producer_proof": proof_ref, "full_case_ids": ids, "selected_case_ids": []}
            bundles[bundle_id] = existing
        if case["physical_case_id"] not in existing["selected_case_ids"]:
            existing["selected_case_ids"].append(case["physical_case_id"])

    # Include the V6 worker and its complete imported source chain.  All of
    # these are small static files; deferred JSONL/native paths never enter
    # input_files or get opened during preparation.
    static_paths = [SCRIPT, v4.SCRIPT, impact.SCRIPT, ROOT270_V2, ROOT266_V1, CURRENT, VENV, VENV.resolve(), PYVENV, RUNTIME, DISPATCH]
    for path, label, expected in ((SCRIPT, "V6 worker", None), (v4.SCRIPT, "V4 imported worker", None), (impact.SCRIPT, "ROOT270 V3 imported worker", None), (ROOT270_V2, "ROOT270 V2 imported worker", None), (ROOT266_V1, "ROOT266 V1 imported worker", None), (CURRENT, "CURRENT336", CURRENT_SHA), (VENV, "literal Python interpreter", None), (VENV.resolve(), "resolved Python interpreter", None), (PYVENV, "pyvenv.cfg", None), (RUNTIME, "runtime v8", None), (DISPATCH, "dispatch v8", None)):
        _add_ref(refs, _small_ref(Path(path), label, expected))
    if any(Path(item["path"]).suffix.lower() in PAYLOAD_SUFFIXES for item in refs.values()):
        raise MassV6Error("payload entered V6 static closure")
    out = args.output_root.expanduser().resolve()
    if out.exists():
        raise MassV6Error(f"refusing to reuse output root: {out}")
    out.mkdir(parents=True, exist_ok=False)
    deferred = [case["typed_records_deferred"] for case in cases]
    source_bytes = sum(int(item["bytes"]) for item in deferred)
    namespace = f"NATIVE_TYPED_MASS_IMPACT_V6_ROOT_{batch_id or args.batch_id or 'SOURCE'}"
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_V6",
        "namespace": namespace, "family_id": family or "MULTI_FAMILY", "batch_id": batch_id or args.batch_id,
        "source_catalog": source_ref, "root313_exclusion": exclude_ref,
        "cases": cases, "case_count": len(cases), "proof_bundles": list(bundles.values()),
        "producer_proof_merge": {"created": False, "meaning": "Producer proofs remain complete and independent; selected case rows are an audit subset."},
        "source_refs": sorted(refs.values(), key=lambda item: item["path"]), "deferred_payloads": deferred,
        "claim_boundary": {
            "selected_typed_initial_mass": "EXACT_ONLY_WHEN_SELECTED_JSONL_ROW_HAS_FINITE_POSITIVE_INITIAL_MASS_KG",
            "missing_selected_mass": "NULL_UNKNOWN_NEVER_ZERO", "role_average_proxy": "UNVERIFIED_NOT_USED_AS_PER_ID_MASS",
            "saved_mask_mass_and_count": "DIAGNOSTIC_ONLY", "native_cause": "SOURCE_BOUND_WHERE_PRODUCER_REPORTS_IT",
            "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "read_policy": {"prepare_opened_jsonl": False, "prepare_opened_h5": False, "prepare_opened_bi4": False, "prepare_opened_obi4": False, "prepare_opened_native_payload": False, "solver_started": False, "audit_after_parent_reservation": True},
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024**3, "typed_jsonl_source_bytes": source_bytes, "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3, "output_bytes_max": MAX_OUTPUT},
    }
    manifest_path = out / "native-typed-mass-impact-v6-manifest.json"
    _atomic(manifest_path, manifest)
    manifest_ref = _small_ref(manifest_path, "V6 manifest")
    refs[str(manifest_path)] = manifest_ref
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    request_path = args.request_output.expanduser().resolve()
    request = {
        "schema": "ds02.request.v1", "shared_runtime_version": "v8", "family_id": "INFRA", "case_id": namespace,
        "attempt_id": f"{namespace.lower()}-root-source-only", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 1800, "max_memory_bytes": 2 * 1024**3, "estimated_storage_bytes": MAX_OUTPUT,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()) + source_bytes * 3,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY),
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/native-typed-mass-impact-v6.json"],
        "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": [item["path"] for item in deferred], "deferred_input_contracts": deferred,
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]}, "source_proofs": list(bundles.values()),
        "claim_boundary": manifest["claim_boundary"], "read_policy": manifest["read_policy"],
        "launch_allowed": True, "execution_allowed": True, "launch_owner": "root",
        "request_note": "V6 selected exact joins only; old singleton and multi-case producer proofs remain separate. This is a saved-mask/initial-mass diagnostic and grants no physical fate/flux/dynamics/Q credit.",
    }
    _atomic(request_path, request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": manifest_ref["sha256"], "request": str(request_path), "request_sha256": _digest(request_path, "V6 request"), "batch_id": batch_id or args.batch_id, "family_id": family, "case_count": len(cases), "case_ids": case_ids, "selected_native_ids": sum(case["selected_native_id_count"] for case in cases), "typed_jsonl_source_bytes": source_bytes, "typed_jsonl_minimum_three_pass_read_bytes": source_bytes * 3, "payload_content_opened": False}


def prepare_all(args: argparse.Namespace) -> dict[str, Any]:
    specs = (("322", "F2", 0), ("323", "F4", 0), ("324", "F6", 0), ("325", "F6", 1), ("326", "F6", 2))
    suffix = str(args.name_suffix)
    results = []
    for batch_id, family, index in specs:
        child = argparse.Namespace(**vars(args))
        child.family = family
        child.batch_index = index
        child.batch_id = batch_id
        child.output_root = args.output_base / f"native-typed-mass-impact-v6-root-{batch_id}-prepared-{suffix}"
        child.request_output = args.request_dir / f"native-typed-mass-impact-v6-root-forward-{batch_id}-source-only-{suffix}.json"
        results.append(_prepare_one(child, family, index, batch_id))
    return {"status": "PREPARED_SOURCE_ONLY_V6_BATCHES", "batches": results, "total_cases": sum(item["case_count"] for item in results), "payload_content_opened": False}


def _audit_case(case: dict[str, Any]) -> dict[str, Any]:
    """V4 stream audit with V6's normalized native report rows."""
    case_id = case["physical_case_id"]
    native_path = Path(case["native_report"]["path"])
    native_report = _json(native_path, f"{case_id} native report")
    native_rows = _native_rows(native_report, case_id)
    expected_keys = {tuple(item["identity_key"]) for item in case["selected_native_ids"]}
    actual_keys = {tuple(item["identity_key"]) for item in native_rows}
    if expected_keys != actual_keys:
        raise MassV6Error(f"{case_id} native identity set changed")
    typed = v4.v3._stream_typed_records(case)
    results = []
    masses: list[float] = []
    for item in case["selected_native_ids"]:
        key = (int(item["zone"]), int(item["idp"]))
        found = typed["found"][key]
        role, type_code = found.get("initial_role"), found.get("initial_type_code")
        if role != "fluid" or type_code != 3:
            raise MassV6Error(f"{case_id} selected identity {key} is not typed fluid/type3")
        mass = found.get("initial_mass_kg")
        if mass is not None:
            masses.append(float(mass))
        results.append({**item, "typed_initial_role": role, "typed_initial_type_code": type_code, "typed_initial_mass_kg": mass, "typed_mass_status": "EXACT_TYPED_JSONL_INITIAL_MASS" if mass is not None else "UNKNOWN_MISSING_TYPED_INITIAL_MASS", "role_average_proxy_mass_kg": None, "role_average_proxy_status": "UNVERIFIED_NOT_USED_AS_PER_ID_MASS"})
    exact_sum = sum(masses) if len(masses) == len(results) else None
    return {"physical_case_id": case_id, "family_id": case["family_id"], "status": "COMPLETED_SELECTED_NATIVE_TYPED_INITIAL_MASS_DIAGNOSTIC_ONLY", "selected_native_ids": results, "selected_native_id_count": len(results), "typed_records": {"path": case["typed_records_deferred"]["path"], "rows": typed["rows"], "pre_stat": typed["pre_stat"], "post_stat": typed["post_stat"], "pre_sha256": typed["pre_sha256"], "stream_sha256": typed["stream_sha256"], "post_sha256": typed["post_sha256"], "hash_passes": typed["hash_passes"]}, "selected_typed_initial_mass_sum_kg": exact_sum, "selected_typed_initial_mass_status": "EXACT_ALL_SELECTED_ROWS" if exact_sum is not None else "UNKNOWN_AT_LEAST_ONE_SELECTED_ROW_MASS_MISSING", "role_average_proxy_mass_kg": None, "role_average_proxy_status": "UNVERIFIED_NOT_USED_AS_PER_ID_MASS", "impact": {"selected_saved_native_identity_count": len(results), "selected_typed_initial_mass_kg": exact_sum, "diagnostic_only": True, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def _validate_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _json(path, "V6 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_V6":
        raise MassV6Error("V6 manifest schema/status differs")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 8 or len({case.get("physical_case_id") for case in cases if isinstance(case, dict)}) != len(cases):
        raise MassV6Error("V6 manifest case set is malformed or exceeds eight")
    for case in cases:
        if not isinstance(case, dict):
            raise MassV6Error("V6 case is malformed")
        _deferred(case.get("typed_records_deferred"), f"{case.get('physical_case_id')} typed records")
    return manifest, cases


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest, cases = _validate_manifest(args.manifest)
    results = []
    for case in cases:
        try:
            results.append(_audit_case(case))
        except (MassV6Error, impact.ImpactV3Error, OSError, KeyError, TypeError, ValueError) as exc:
            results.append({"physical_case_id": case.get("physical_case_id"), "family_id": case.get("family_id"), "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    failed = [row for row in results if row.get("status") == "FAILED"]
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_NATIVE_TYPED_MASS_IMPACT_V6_DIAGNOSTIC_ONLY", "source_manifest": {"path": str(Path(args.manifest).expanduser().resolve()), "sha256": _digest(args.manifest, "V6 manifest")}, "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed), "selected_native_ids": sum(int(row.get("selected_native_id_count", 0)) for row in results if row.get("status") != "FAILED")}, "claim_boundary": manifest["claim_boundary"], "read_policy": {"typed_jsonl_content_read_after_parent_reservation": True, "native_reports_read": True, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).expanduser().resolve()), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source-join", type=Path, default=SOURCE_DEFAULT)
    prep.add_argument("--exclude-manifest", type=Path, default=EXCLUDE_DEFAULT)
    prep.add_argument("--family", choices=("F2", "F4", "F6"), required=True)
    prep.add_argument("--batch-index", type=int, default=0)
    prep.add_argument("--batch-id", required=True)
    prep.add_argument("--batch-size", type=int, default=8)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    all_p = sub.add_parser("prepare-all")
    all_p.add_argument("--source-join", type=Path, default=SOURCE_DEFAULT)
    all_p.add_argument("--exclude-manifest", type=Path, default=EXCLUDE_DEFAULT)
    all_p.add_argument("--batch-size", type=int, default=8)
    all_p.add_argument("--output-base", type=Path, required=True)
    all_p.add_argument("--request-dir", type=Path, required=True)
    all_p.add_argument("--name-suffix", default="001")
    audit_p = sub.add_parser("audit")
    audit_p.add_argument("--manifest", type=Path, required=True)
    audit_p.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare_all(args) if args.action == "prepare-all" else _prepare_one(args) if args.action == "prepare" else audit(args)
    except (MassV6Error, impact.ImpactV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"NATIVE_TYPED_MASS_IMPACT_V6_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
