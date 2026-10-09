#!/usr/bin/env python3
"""Strict V4 verifier for rolling native/typed joins and ROOT312 proofs.

V3 remains immutable.  This additive verifier fixes three source-closure
edges that matter when a rolling original-118 overlay is consumed:

* the canonical selected set is derived from the base inventory, cumulative
  ``newly_bound_cases``, actual proof rows, and the current unresolved list;
  cause-bound cases without a typed/native join are therefore still eligible;
* a typed summary that exposes only a first-disappearance count is accepted
  when that count equals the report rows, while saved time/brackets still
  have to match the summary timeline; and
* the official decoder path/SHA/command and the PartOut CSV position/density
  fields are checked as source evidence.

The worker still receives the complete ROOT296/ROOT297 producer proofs and a
3/4 selected subset.  No proof is merged and no physical fate, flux,
dynamics, or QI/QN/QE credit is granted.  Only bounded metadata, JSON, CSV,
and stat/SHA edges are opened; typed JSONL, H5, BI4, and OBI4 content remain
parent-reserved inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import ds_data02_stage2_verify_generic_native_join_v3 as v3


SCRIPT = Path(__file__).resolve()
OVERLAY_SCHEMA = v3.OVERLAY_SCHEMA
SCOPE_SCHEMA = v3.SCOPE_SCHEMA
DEPENDENCY_SCOPE_SCHEMA = "ds02.stage2.native-typed-case-dependency-inventory.v2"
PROOF_SCHEMA = v3.PROOF_SCHEMA
GENERIC_MANIFEST_SCHEMA = v3.GENERIC_MANIFEST_SCHEMA
ROOT312_MANIFEST_SCHEMA = v3.ROOT312_MANIFEST_SCHEMA
WORKER_REPORT_SCHEMA = v3.WORKER_REPORT_SCHEMA
WORKER_CASE_SCHEMA = v3.WORKER_CASE_SCHEMA
ROOT312_REPORT_SCHEMA = v3.ROOT312_REPORT_SCHEMA
REQUEST_SCHEMA = v3.REQUEST_SCHEMA
MAX_SMALL = v3.MAX_SMALL
MAX_REPORT = v3.MAX_REPORT
MAX_CSV = 64 * 1024 * 1024
PAYLOAD_SUFFIXES = v3.PAYLOAD_SUFFIXES
OUTPUT_SCHEMA = "ds02.stage2.generic-native-typed-native-join-v4-verification"


class GenericJoinV4Error(v3.GenericJoinV3Error):
    pass


def _error(message: str) -> None:
    raise GenericJoinV4Error(message)


def _sha(value: Any, label: str) -> str:
    try:
        return v3.v2._sha(value, label)
    except Exception as exc:  # keep the public error type versioned
        raise GenericJoinV4Error(str(exc)) from exc


def _json_ref(value: Any, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return v3.v2._json_ref(value, label)
    except Exception as exc:
        raise GenericJoinV4Error(str(exc)) from exc


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    try:
        return v3._list_ids(value, label, allow_empty=allow_empty)
    except Exception as exc:
        raise GenericJoinV4Error(str(exc)) from exc


def _proof_ids(ref: Any, label: str) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    try:
        proof, actual, ids = v3._validate_proof_ref_v3(ref, label)
    except Exception as exc:
        raise GenericJoinV4Error(str(exc)) from exc
    return proof, actual, ids


def _base_inventory(path: Path, expected: dict[str, Any] | None = None, seen: tuple[str, ...] = ()) -> dict[str, Any]:
    """Derive exact physical-case classes from a V2 scope or older overlay."""
    path = path.expanduser().resolve()
    if str(path) in seen:
        _error("rolling overlay base_scope contains a cycle")
    value, actual = _json_ref({**(expected or {}), "path": str(path)}, f"rolling base scope {path}")
    if expected is not None and expected.get("sha256") not in (None, "PARENT_GUARD_COMPUTED"):
        if actual["sha256"] != _sha(expected["sha256"], f"rolling base scope {path} SHA"):
            _error(f"rolling base scope SHA differs: {path}")
    schema = value.get("schema")
    if schema in {SCOPE_SCHEMA, DEPENDENCY_SCOPE_SCHEMA}:
        rows = value.get("case_rows")
        if not isinstance(rows, list) or not rows:
            _error("base V2 scope has no case_rows")
        ids = [row.get("physical_case_id") for row in rows if isinstance(row, dict)]
        if len(ids) != len(rows) or any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
            _error("base V2 scope case identities are not exact")
        bound = {row["physical_case_id"] for row in rows if row.get("classification") == "NATIVE_CAUSE_BOUND_PER_FLUID_ID"}
        unresolved = {row["physical_case_id"] for row in rows if row.get("classification") == "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN"}
        aliases = set()
        scope = value.get("scope") if isinstance(value.get("scope"), dict) else {}
        if isinstance(scope.get("unresolved_alias_case_ids"), list):
            aliases = set(_string_list(scope["unresolved_alias_case_ids"], "base V2 unresolved aliases", allow_empty=True))
        if bound | unresolved | aliases != set(ids) or bound & unresolved or bound & aliases or unresolved & aliases:
            _error("base V2 scope classes do not partition its exact cases")
        return {"path": str(path), "ref": actual, "ids": set(ids), "bound": bound, "unresolved": unresolved, "aliases": aliases, "existing": set(), "proof_ids": set(), "schema": schema}
    if schema != OVERLAY_SCHEMA:
        _error(f"unsupported rolling base scope schema: {schema}")
    base_ref = value.get("base_scope")
    if not isinstance(base_ref, dict) or not isinstance(base_ref.get("path"), str):
        _error("rolling overlay lacks a source-bound base_scope")
    previous = _base_inventory(Path(base_ref["path"]), base_ref, seen + (str(path),))
    ids = set(previous["ids"])
    physical_count = value.get("physical_case_count")
    if isinstance(physical_count, bool) or not isinstance(physical_count, int) or physical_count != len(ids):
        _error("rolling overlay physical_case_count differs from exact base inventory")
    new_rows = value.get("newly_bound_cases", [])
    if not isinstance(new_rows, list):
        _error("rolling overlay newly_bound_cases is not a list")
    newly_bound: set[str] = set()
    for row in new_rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            _error("rolling overlay newly_bound_cases has a malformed row")
        case_id = row["physical_case_id"]
        if case_id not in ids:
            _error(f"rolling overlay newly bound case is outside base inventory: {case_id}")
        if case_id in newly_bound:
            _error(f"rolling overlay repeats newly bound case: {case_id}")
        if row.get("classification") not in (None, "NATIVE_CAUSE_BOUND_PER_FLUID_ID"):
            _error(f"rolling overlay newly bound case has unsupported classification: {case_id}")
        newly_bound.add(case_id)
    bound = set(previous["bound"]) | newly_bound
    unresolved = set(_string_list(value.get("remaining_cause_not_located_case_ids", []), "rolling overlay unresolved cases", allow_empty=True))
    if not unresolved.issubset(ids):
        _error("rolling overlay unresolved cases are outside exact inventory")
    aliases = set(previous["aliases"])
    aliases.update(_string_list(value.get("unresolved_alias_case_ids", []), "rolling overlay aliases", allow_empty=True))
    if not aliases.issubset(ids):
        _error("rolling overlay aliases are outside exact inventory")
    if bound & unresolved or bound & aliases or unresolved & aliases or bound | unresolved | aliases != ids:
        _error("rolling overlay classes do not partition exact current inventory")

    proof_ids: set[str] = set()
    proofs = value.get("actual_join_proofs")
    if not isinstance(proofs, list) or not proofs:
        _error("rolling overlay lacks actual_join_proofs")
    proof_paths: set[str] = set()
    for index, proof_ref in enumerate(proofs):
        _, actual_proof_ref, ids_for_proof = _proof_ids(proof_ref, f"rolling overlay proof[{index}]")
        if actual_proof_ref["path"] in proof_paths:
            _error("rolling overlay repeats an actual proof path")
        proof_paths.add(actual_proof_ref["path"])
        if proof_ids & ids_for_proof:
            _error("rolling overlay actual proofs overlap physical cases")
        proof_ids |= ids_for_proof
    if not proof_ids.issubset(bound):
        _error("rolling overlay actual proof includes an unresolved/non-bound case")
    declared_join = value.get("actual_typed_native_saved_frame_join_physical_cases")
    if isinstance(declared_join, bool):
        _error("rolling overlay declared join count is boolean")
    if isinstance(declared_join, int):
        if declared_join != len(proof_ids):
            _error("rolling overlay declared join count differs from actual proof rows")
    elif isinstance(declared_join, list):
        declared_join_ids = set(_string_list(declared_join, "rolling overlay declared join IDs", allow_empty=True))
        if declared_join_ids != proof_ids:
            _error("rolling overlay declared join IDs differ from actual proof rows")
    else:
        _error("rolling overlay declared join count/IDs are missing")
    return {"path": str(path), "ref": actual, "ids": ids, "bound": bound, "unresolved": unresolved, "aliases": aliases, "existing": proof_ids, "proof_ids": proof_ids, "schema": schema}


def _load_scope_v4(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    document, scope_ref = _json_ref({"path": str(path.expanduser().resolve())}, "native/typed join scope")
    if document.get("schema") == OVERLAY_SCHEMA:
        inventory = _base_inventory(path)
        selected = (inventory["bound"] - inventory["existing"]) | inventory["unresolved"]
        existing = inventory["existing"]
        aliases = inventory["aliases"]
        case_scope = {
            "original_case_count": len(inventory["ids"]),
            "current_bound_count": len(inventory["bound"]),
            "existing_exact_join_count": len(existing),
            "cause_bound_missing_join_count": len(inventory["bound"] - existing),
            "cause_not_located_count": len(inventory["unresolved"]),
            "selected_canonical_count": len(selected),
        }
    elif document.get("schema") == SCOPE_SCHEMA:
        # Preserve V3's explicit selected/existing scope contract for small
        # worker fixtures and already-materialized generic scopes.
        loaded, _ = v3._load_scope_v3(path)
        return loaded, scope_ref
    elif document.get("schema") == DEPENDENCY_SCOPE_SCHEMA:
        inventory = _base_inventory(path)
        selected = inventory["bound"] | inventory["unresolved"]
        existing = set()
        aliases = inventory["aliases"]
        case_scope = {
            "original_case_count": len(inventory["ids"]),
            "current_bound_count": len(inventory["bound"]),
            "existing_exact_join_count": 0,
            "cause_bound_missing_join_count": len(inventory["bound"]),
            "cause_not_located_count": len(inventory["unresolved"]),
            "selected_canonical_count": len(selected),
        }
        return {
            "document": document, "ref": scope_ref, "selected": set(selected),
            "existing": existing, "aliases": set(aliases), "producer_by_case": {},
            "actual_join_proof_count": 0, "actual_join_proof_ids": set(),
            "case_scope": case_scope,
            "derived_inventory": {"physical_cases": len(inventory["ids"]), "bound": len(inventory["bound"]), "unresolved": len(inventory["unresolved"]), "existing": 0, "cause_bound_missing": len(inventory["bound"]), "aliases": len(aliases)},
        }, scope_ref
    else:
        _error(f"unsupported scope schema: {document.get('schema')}")
    if selected & existing or selected & aliases or existing & aliases:
        _error("scope selected/existing/alias sets overlap")
    return {
        "document": document,
        "ref": scope_ref,
        "selected": set(selected),
        "existing": set(existing),
        "aliases": set(aliases),
        "producer_by_case": {},
        "actual_join_proof_count": len(existing),
        "actual_join_proof_ids": set(existing),
        "case_scope": case_scope,
        "derived_inventory": {"physical_cases": len(inventory["ids"]), "bound": len(inventory["bound"]), "unresolved": len(inventory["unresolved"]), "existing": len(existing), "cause_bound_missing": len(inventory["bound"] - existing), "aliases": len(aliases)},
    }, scope_ref


def _summary_matches_rows_v4(summary: dict[str, Any], rows: list[dict[str, Any]], case_id: str) -> None:
    """V3 summary check with count-only first-missing fallback fixed."""
    if summary.get("physical_case_id") not in (None, case_id):
        _error(f"{case_id} typed summary identity differs")
    timeline = summary.get("timeline")
    times = timeline.get("time_s") if isinstance(timeline, dict) else None
    if not isinstance(times, list) or not times:
        _error(f"{case_id} typed summary has no saved timeline")
    first_rows = v3._summary_first_rows(summary)
    fluid = summary.get("role_ledgers", {}).get("fluid", {}) if isinstance(summary.get("role_ledgers"), dict) else {}
    expected_count = fluid.get("first_disappearance_count")
    if first_rows is not None:
        if set(first_rows) != {v3.v2._identity(row, f"{case_id} report row") for row in rows}:
            _error(f"{case_id} report/summary first-missing identity sets differ")
    elif isinstance(expected_count, int) and not isinstance(expected_count, bool):
        if expected_count != len(rows):
            _error(f"{case_id} report/summary first-missing count differs")
        # A count-only summary is accepted.  Per-ID report fields below still
        # have to map to this saved timeline; no independent target identity
        # credit is inferred from the count.
    else:
        _error(f"{case_id} typed summary does not expose first-missing identity records or count")
    for row in rows:
        key = v3.v2._identity(row, f"{case_id} report row")
        summary_row = first_rows.get(key) if first_rows is not None else None
        frame = row.get("first_missing_frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or frame <= 0 or frame >= len(times):
            _error(f"{case_id} {key} first-missing frame is outside summary timeline")
        frame_fields = ("first_missing_frame", "first_disappeared_frame", "frame")
        time_fields = ("first_missing_time_s", "first_disappeared_time_s", "time_s", "time")
        bracket_fields = ("bracket_s", "first_missing_bracket_s", "first_disappeared_bracket_s")
        if summary_row is not None:
            sf = next((summary_row.get(name) for name in frame_fields if summary_row.get(name) is not None), None)
            st = next((summary_row.get(name) for name in time_fields if summary_row.get(name) is not None), None)
            sb = next((summary_row.get(name) for name in bracket_fields if summary_row.get(name) is not None), None)
            v3._compare_optional(frame, sf, f"{case_id} {key} report/summary frame")
            v3._compare_optional(row.get("first_missing_time_s"), st, f"{case_id} {key} report/summary time")
            v3._compare_optional(row.get("bracket_s"), sb, f"{case_id} {key} report/summary bracket")
        expected_time = float(times[frame])
        reported_time = v3.v2._number(row.get("first_missing_time_s"), f"{case_id} {key} first-missing time")
        if not math.isclose(expected_time, reported_time, rel_tol=0.0, abs_tol=1e-12):
            _error(f"{case_id} {key} report time differs from summary timeline")
        bracket = row.get("bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            _error(f"{case_id} {key} report bracket is malformed")
        expected_bracket = [float(times[frame - 1]), expected_time]
        if any(not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12) for a, b in zip(bracket, expected_bracket)):
            _error(f"{case_id} {key} report bracket differs from summary timeline")


def _read_partout_csv_v4(path_ref: dict[str, Any], label: str) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    try:
        raw, actual = v3.v2._capture(v3.v2._path(path_ref.get("path"), label), label, limit=MAX_CSV)
        v3.v2._compare_stat(actual, path_ref, label)
        expected_sha = path_ref.get("sha256")
        if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != _sha(expected_sha, f"{label} SHA"):
            _error(f"{label} SHA differs")
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GenericJoinV4Error(f"{label} is not UTF-8") from exc
    except Exception as exc:
        if isinstance(exc, GenericJoinV4Error):
            raise
        raise GenericJoinV4Error(str(exc)) from exc
    reader = csv.DictReader(text.splitlines())
    fields = [field.strip() for field in (reader.fieldnames or [])]
    required = {"Idp", "Motive", "PartOut", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Rhop [kg/m^3]"}
    if not required.issubset(fields):
        _error(f"{label} lacks exact Pos/Rhop identity columns")
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    for line_no, row in enumerate(reader, 2):
        if not row or all(not str(value or "").strip() for value in row.values()):
            continue
        try:
            idp = int(str(row.get("Idp", "")).strip())
            motive = int(str(row.get("Motive", "")).strip())
            part_out = int(str(row.get("PartOut", "")).strip())
            zone = int(str(row.get("Zone", "0")).strip() or "0")
            position = [float(str(row[name]).strip()) for name in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")]
            density = float(str(row["Rhop [kg/m^3]"]).strip())
        except (ValueError, KeyError, TypeError) as exc:
            raise GenericJoinV4Error(f"{label} row {line_no} has malformed identity/Pos/Rhop") from exc
        if not all(math.isfinite(value) for value in position + [density]):
            _error(f"{label} row {line_no} has non-finite Pos/Rhop")
        key = (zone, idp)
        if key in rows:
            _error(f"{label} duplicates identity {key}")
        rows[key] = {"zone": zone, "idp": idp, "motive_code": motive, "part_out": part_out, "position_m": position, "density_kg_m3": density}
    if not rows:
        _error(f"{label} has no rows")
    return rows, actual


def _float_equal(actual: Any, expected: Any, label: str) -> None:
    try:
        a, e = float(actual), float(expected)
    except (TypeError, ValueError) as exc:
        raise GenericJoinV4Error(f"{label} is not numeric") from exc
    if not math.isfinite(a) or not math.isfinite(e) or not math.isclose(a, e, rel_tol=0.0, abs_tol=1e-12):
        _error(f"{label} differs")


def _validate_decoder_binding(manifest: dict[str, Any], request: dict[str, Any], contract: dict[str, Any], case_report: dict[str, Any], case_id: str) -> dict[str, Any]:
    official = manifest.get("official_sources") if isinstance(manifest.get("official_sources"), dict) else {}
    tool_ref = official.get("partvtkout") or manifest.get("official_tool")
    if not isinstance(tool_ref, dict) or not isinstance(tool_ref.get("path"), str):
        _error(f"{case_id} manifest lacks official decoder path/SHA")
    tool_path = str(Path(tool_ref["path"]).expanduser().resolve())
    tool_sha = _sha(tool_ref.get("sha256"), f"{case_id} official decoder SHA")
    # The decoder is a source input, not a native payload.  Its bytes are
    # checked once here and the request closure must carry the same digest.
    try:
        actual_tool = v3.v2._static_ref({"path": tool_path, "sha256": tool_sha}, f"{case_id} official decoder", limit=64 * 1024 * 1024)
    except Exception as exc:
        raise GenericJoinV4Error(str(exc)) from exc
    request_tools = request.get("official_sources") if isinstance(request.get("official_sources"), dict) else {}
    if request_tools:
        request_tool = request_tools.get("partvtkout")
        if not isinstance(request_tool, dict) or str(Path(request_tool.get("path", "")).expanduser().resolve()) != tool_path or request_tool.get("sha256") != tool_sha:
            _error(f"{case_id} request official decoder binding differs")
    native = case_report.get("native")
    evidence = native.get("official_tool") if isinstance(native, dict) else None
    if not isinstance(evidence, dict):
        _error(f"{case_id} case report lacks official decoder evidence")
    if str(Path(evidence.get("path", "")).expanduser().resolve()) != tool_path:
        _error(f"{case_id} case report decoder path differs")
    if evidence.get("sha256", tool_sha) != tool_sha:
        _error(f"{case_id} case report decoder SHA differs")
    command = evidence.get("command")
    if not isinstance(command, list) or any(not isinstance(item, str) for item in command):
        _error(f"{case_id} case report decoder command is malformed")
    native_deferred = contract.get("native_deferred") if isinstance(contract.get("native_deferred"), dict) else {}
    data_dir = native_deferred.get("data_dir") if isinstance(native_deferred.get("data_dir"), dict) else {}
    expected_data_dir = str(Path(data_dir.get("path", "")).expanduser().resolve())
    csv_evidence = native.get("partout_csv") if isinstance(native, dict) else None
    csv_path = str(Path((csv_evidence or {}).get("pre_stat", {}).get("path", "")).expanduser().resolve())
    if len(command) != 9 or command[0] != tool_path or command[1:2] != ["-dirdata"] or command[2] != expected_data_dir or command[3:4] != ["-savecsv"] or command[4] != csv_path or command[5:6] != ["-saveresume"] or not Path(command[6]).is_absolute() or command[7:] != ["-createdirs:1", "-csvsep:1"]:
        _error(f"{case_id} official decoder command differs from the bound PartVTKOut contract")
    return {"path": tool_path, "sha256": tool_sha, "command": command, "source_ref": actual_tool}


def _verify_case_v4(case_id: str, entry: dict[str, Any], contract: dict[str, Any], family: str, manifest: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    try:
        case_report, case_ref = v3.v2._json(v3.v2._path(entry["output"], f"{case_id} generic case output"), f"{case_id} generic case output", limit=MAX_REPORT)
    except Exception as exc:
        raise GenericJoinV4Error(str(exc)) from exc
    if case_report.get("schema") != v3.WORKER_CASE_SCHEMA or case_report.get("status") != "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY":
        _error(f"{case_id} generic case report schema/status differs")
    if case_report.get("physical_case_id") != case_id or case_report.get("family_id") != family:
        _error(f"{case_id} generic case report identity differs")
    counts, rows = case_report.get("counts"), case_report.get("rows")
    if not isinstance(counts, dict) or not isinstance(rows, list) or not rows:
        _error(f"{case_id} generic case report lacks rows/counts")
    if counts.get("joined") != len(rows) or counts.get("typed_targets") != len(rows) or counts.get("native_rows") != len(rows):
        _error(f"{case_id} generic case report counts differ")
    keys: set[tuple[int, int]] = set()
    brackets: list[list[float]] = []
    row_summary: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = v3.v2._identity(row, f"{case_id} generic case row")
        if key in keys:
            _error(f"{case_id} generic case report duplicates {key}")
        keys.add(key)
        motive = row.get("motive_code", row.get("native_motive_code"))
        if motive not in (1, 2, 3):
            _error(f"{case_id} generic case row motive is unsupported")
        bracket = row.get("bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            _error(f"{case_id} generic case row lacks saved bracket")
        bracket_values = [v3.v2._number(value, f"{case_id} bracket") for value in bracket]
        first_time = v3.v2._number(row.get("first_missing_time_s"), f"{case_id} first missing time")
        if bracket_values[0] > first_time or first_time > bracket_values[1]:
            _error(f"{case_id} first missing time is outside saved bracket")
        brackets.append(bracket_values)
        row_summary[key] = {**row, "motive_code": motive}
    typed = case_report.get("typed")
    if not isinstance(typed, dict):
        _error(f"{case_id} generic case report lacks typed evidence")
    typed_deferred = contract.get("typed_deferred")
    if not isinstance(typed_deferred, dict) or not isinstance(typed_deferred.get("summary"), dict) or not isinstance(typed_deferred.get("records"), dict):
        _error(f"{case_id} contract lacks typed summary/records refs")
    summary, summary_ref = v3.v2._json_ref(typed_deferred["summary"], f"{case_id} typed summary")
    records_ref = typed_deferred["records"]
    records_path = v3.v2._path(records_ref.get("path"), f"{case_id} typed records", allow_payload=True)
    records_stat = v3.v2._stat(records_path, f"{case_id} typed records", allow_payload=True)
    v3.v2._compare_stat(records_stat, records_ref, f"{case_id} typed records")
    for edge in (typed.get("pre_stat"), typed.get("post_stat")):
        if not isinstance(edge, dict):
            _error(f"{case_id} typed evidence lacks pre/post stat")
        v3.v2._compare_stat(edge, records_stat, f"{case_id} typed report/contract stat")
    if typed.get("rows") != records_ref.get("rows") or typed.get("target_count") != len(rows):
        _error(f"{case_id} typed report rows/target_count are not bound to producer records")
    if typed.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and records_ref.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and typed.get("sha256") != records_ref.get("sha256"):
        _error(f"{case_id} typed report SHA differs from producer records contract")
    _summary_matches_rows_v4(summary, rows, case_id)
    decoder = _validate_decoder_binding(manifest, request, contract, case_report, case_id)
    native = case_report.get("native")
    if not isinstance(native, dict) or not isinstance(native.get("partout_csv"), dict) or not isinstance(native.get("runparts"), dict):
        _error(f"{case_id} generic case report lacks native CSV/RunPARTs evidence")
    obi4 = v3._verify_obi4(contract, native, case_id)
    partout = native["partout_csv"]
    pre, post = partout.get("pre_stat"), partout.get("post_stat")
    if not isinstance(pre, dict) or not isinstance(post, dict):
        _error(f"{case_id} PartOut CSV evidence lacks pre/post stat")
    v3.v2._compare_stat(post, pre, f"{case_id} PartOut CSV pre/post")
    native_rows, native_stat = _read_partout_csv_v4(pre, f"{case_id} PartOut CSV")
    if partout.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and native_stat["sha256"] != _sha(partout["sha256"], f"{case_id} PartOut CSV SHA"):
        _error(f"{case_id} PartOut CSV report SHA differs")
    if set(native_rows) != keys:
        _error(f"{case_id} PartOut/native identity set differs")
    for key, value in native_rows.items():
        row = row_summary[key]
        if value["motive_code"] != row.get("motive_code") or value["part_out"] != row.get("part_out"):
            _error(f"{case_id} PartOut identity/motive differs for {key}")
        report_position = row.get("position_m", row.get("native_position_m"))
        report_density = row.get("density_kg_m3", row.get("native_density_kg_m3"))
        if not isinstance(report_position, list) or len(report_position) != 3 or report_density is None:
            _error(f"{case_id} case report does not expose PartOut Pos/Rhop for {key}")
        for index, (actual, expected) in enumerate(zip(value["position_m"], report_position)):
            _float_equal(actual, expected, f"{case_id} {key} Pos[{index}]")
        _float_equal(value["density_kg_m3"], report_density, f"{case_id} {key} Rhop")
    runparts = v3.v2._read_runparts(native["runparts"], brackets, case_id)
    return {"physical_case_id": case_id, "status": "COMPLETED", "joined_identity_count": len(keys), "case_output": case_ref, "typed_summary": summary_ref, "typed_records_stat_only": records_stat, "native_obi4": obi4, "native_csv": native_stat, "runparts": runparts, "official_decoder": decoder, "summary_first_missing_identity_rows": v3._summary_first_rows(summary) is not None}


def verify(scope_path: Path, manifest_path: Path, request_path: Path, report_path: Path) -> dict[str, Any]:
    scope, scope_ref = _load_scope_v4(scope_path)
    manifest, manifest_ref, contracts = v3._load_worker_manifest_v3(manifest_path, scope)
    request, request_ref = v3.v2._load_request(request_path, manifest_path, manifest_ref, manifest)
    report, report_ref = v3.v2._json(report_path, "generic worker batch report", limit=MAX_REPORT)
    if report.get("schema") not in {WORKER_REPORT_SCHEMA, ROOT312_REPORT_SCHEMA} or report.get("family_id") != manifest.get("family_id"):
        _error("generic/ROOT312 worker batch report schema/family differs")
    if report.get("status") not in {"COMPLETED_ALL_CASES", "COMPLETED_WITH_CASE_FAILURES", "COMPLETED_SELECTED_ORIGINAL118_NATIVE_DIAGNOSTIC_ONLY"}:
        _error("generic/ROOT312 worker batch report status differs")
    for field in ("physical_fate", "legal_flux", "dynamics", "QI", "QN", "QE"):
        if report.get(field) not in (None, "UNKNOWN"):
            _error(f"worker batch report overclaims {field}")
    results, counts = report.get("case_results"), report.get("counts")
    if not isinstance(results, list) or not isinstance(counts, dict):
        _error("generic worker batch report lacks case results/counts")
    result_ids = [row.get("physical_case_id") for row in results if isinstance(row, dict)]
    if len(result_ids) != len(results) or len(result_ids) != len(set(result_ids)) or set(result_ids) != set(manifest["physical_case_ids"]):
        _error("generic worker result case identities differ")
    if counts.get("requested") != len(results) or counts.get("completed") + counts.get("failed") != counts.get("requested"):
        _error("generic worker report counts do not balance")
    verified: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for result in results:
        case_id = result["physical_case_id"]
        if result.get("status") == "FAILED":
            failures.append({"physical_case_id": case_id, "status": "FAILED_NO_JOIN_CREDIT", "error_type": result.get("error_type"), "error_message": result.get("error_message")})
            continue
        verified.append(_verify_case_v4(case_id, result, contracts[case_id]["document"], manifest["_v3_family"], manifest, request))
    if counts.get("completed") != len(verified) or counts.get("failed") != len(failures):
        _error("generic worker report completed/failed counts differ")
    output = {"schema": OUTPUT_SCHEMA, "status": "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_WITH_CASE_FAILURES" if failures else "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES", "scope": scope_ref, "manifest": manifest_ref, "request": request_ref, "report": report_ref, "derived_scope": scope.get("derived_inventory"), "counts": {"worker_requested": len(results), "worker_completed": len(verified), "worker_failed": len(failures), "actual_join_proofs_checked": scope.get("actual_join_proof_count", 0)}, "case_verifications": verified, "failures": failures, "read_policy": {"scope_manifest_json_opened": True, "producer_proof_json_opened": True, "typed_summary_json_opened": True, "typed_jsonl_content_opened": False, "h5_content_opened": False, "bi4_content_opened": False, "obi4_content_opened": False, "partout_csv_content_opened": True, "runparts_csv_content_opened": True}, "claim_boundary": {"native_id_join": "VERIFIED_PER_CASE_WHERE_COMPLETED", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    return output


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        _error(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--scope", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--request", type=Path, required=True)
    verify_parser.add_argument("--report", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "self-test":
            value = {"schema": OUTPUT_SCHEMA, "status": "PASS", "checks": ["rolling overlay canonical partition", "ROOT312 complete proof plus selected subset", "count-only typed summary timeline", "official decoder path/SHA/exact command", "PartOut Pos/Rhop/identity", "physical fate UNKNOWN"]}
        else:
            value = verify(args.scope, args.manifest, args.request, args.report)
            _atomic(args.output, value)
    except (GenericJoinV4Error, v3.GenericJoinV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"GENERIC_NATIVE_JOIN_V4_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
