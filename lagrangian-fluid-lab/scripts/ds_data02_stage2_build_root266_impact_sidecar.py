#!/usr/bin/env python3
"""Prepare/audit a small typed/native saved-frame impact sidecar.

The sidecar consumes only completed, source-bound JSON summaries and native
case reports.  It never opens trajectory HDF5, JSONL records, BI4/OBI4, or
PartOut payloads.  It reports the fluid ledger's active mass/count changes and
the mass represented by native excluded identities.  The latter is an
identity-weighted saved-record diagnostic; it is not a physical mass flux or
fate measurement, and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


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
MAX_SMALL = 10 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
MANIFEST_SCHEMA = "ds02.stage2.root266-impact-sidecar.v1"
REPORT_SCHEMA = "ds02.stage2.root266-impact-sidecar-report.v1"


class ImpactError(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ImpactError(f"{label} is not a SHA-256 digest")
    return value.lower()


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise ImpactError(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ImpactError(f"{label} is missing: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino)}


def _digest(path: Path, label: str, *, limit: int | None = None) -> str:
    path = _path(path, label)
    if limit is not None and path.stat().st_size > limit:
        raise ImpactError(f"{label} exceeds bounded read")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL:
        raise ImpactError(f"{label} exceeds the small-JSON bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ImpactError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ImpactError(f"{label} must be an object")
    return value


def _ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL:
        raise ImpactError(f"{label} exceeds the small source bound")
    actual = _digest(path, label, limit=MAX_SMALL)
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual != _sha(expected, f"{label} expected SHA"):
        raise ImpactError(f"{label} SHA differs")
    value.update({"sha256": actual, "content_opened": True})
    return value


def _atomic(path: Path, value: dict[str, Any], limit: int = MAX_OUTPUT) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ImpactError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if tmp.stat().st_size > limit:
            raise ImpactError(f"{path} exceeds output bound")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ImpactError(f"{label} must be finite numeric")
    return float(value)


def _proof_rows(proof_path: Path, family: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    proof_ref = _ref(proof_path, f"{family} terminal proof")
    proof = _json(proof_path, f"{family} terminal proof")
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise ImpactError(f"{family} proof is not a completed verified proof")
    counts = proof.get("counts")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        rows = proof.get("case_results") if isinstance(proof.get("case_results"), list) else []
    completed = counts.get("completed") if isinstance(counts, dict) else proof.get("actual_completed_physical_cases")
    if not isinstance(completed, int) or completed != len(rows):
        raise ImpactError(f"{family} proof completed count does not match its rows")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise ImpactError(f"{family} proof has malformed case row")
        case_id = row["physical_case_id"]
        if case_id in seen:
            raise ImpactError(f"{family} proof duplicates {case_id}")
        seen.add(case_id)
        if row.get("family_id") not in (None, family):
            raise ImpactError(f"{family} row family differs: {case_id}")
        normalized.append(dict(row))
    return proof_ref, normalized, proof


def _summary_ref_from_report(report: dict[str, Any], case_id: str) -> tuple[Path, str | None]:
    typed = report.get("typed")
    if not isinstance(typed, dict):
        raise ImpactError(f"{case_id} native report has no typed edge")
    summary = typed.get("summary")
    if isinstance(summary, dict):
        post = summary.get("post_stat")
        if isinstance(post, dict) and isinstance(post.get("path"), str):
            return Path(post["path"]), summary.get("sha256")
    source_summary = typed.get("source_summary")
    if isinstance(source_summary, dict) and isinstance(source_summary.get("path"), str):
        return Path(source_summary["path"]), source_summary.get("sha256")
    raise ImpactError(f"{case_id} native report has no typed summary path")


def _case_source(row: dict[str, Any], family: str, proof_ref: dict[str, Any], proof_tag: str) -> dict[str, Any]:
    case_id = row["physical_case_id"]
    native_report_ref: dict[str, Any] | None = None
    summary_path: Path | None = None
    summary_expected: str | None = None
    value = row.get("summary")
    if isinstance(value, str):
        summary_path, summary_expected = Path(value), row.get("summary_sha256")
    elif isinstance(row.get("typed_summary"), dict):
        typed = row["typed_summary"]
        if isinstance(typed.get("path"), str):
            summary_path, summary_expected = Path(typed["path"]), typed.get("sha256")
    report_value = row.get("report")
    if isinstance(report_value, str):
        native_report_ref = _ref(Path(report_value), f"{case_id} native report", row.get("report_sha256"))
        native_report = _json(Path(report_value), f"{case_id} native report")
        if native_report.get("physical_case_id") != case_id or native_report.get("family_id") not in (None, family):
            raise ImpactError(f"{case_id} native report identity differs")
        if summary_path is None:
            summary_path, report_summary_sha = _summary_ref_from_report(native_report, case_id)
            summary_expected = report_summary_sha
        elif summary_expected in (None, "PARENT_GUARD_COMPUTED"):
            _, report_summary_sha = _summary_ref_from_report(native_report, case_id)
            summary_expected = report_summary_sha
    if summary_path is None:
        raise ImpactError(f"{case_id} has no typed summary")
    summary_ref = _ref(summary_path, f"{case_id} typed summary", summary_expected)
    summary = _json(summary_path, f"{case_id} typed summary")
    _validate_summary(summary, case_id)
    return {"physical_case_id": case_id, "family_id": family, "proof_tag": proof_tag, "proof": proof_ref, "typed_summary": summary_ref, "native_report": native_report_ref, "native_report_status": "BOUND" if native_report_ref else "NOT_AVAILABLE", "typed_initial": {"fluid_count": int(summary["role_ledgers"]["fluid"]["initial_count"]), "fluid_mass_kg": _finite(summary["role_ledgers"]["fluid"]["initial_mass_kg"], f"{case_id} fluid initial mass")}}


def _validate_summary(summary: dict[str, Any], case_id: str) -> None:
    ledgers = summary.get("role_ledgers")
    timeline = summary.get("timeline")
    if not isinstance(ledgers, dict) or not isinstance(ledgers.get("fluid"), dict) or not isinstance(timeline, dict):
        raise ImpactError(f"{case_id} summary does not expose role ledger/timeline")
    fluid = ledgers["fluid"]
    units = fluid.get("units")
    if not isinstance(units, dict) or units.get("mass") != "kg" or units.get("time") != "s":
        raise ImpactError(f"{case_id} fluid ledger units are not explicit SI")
    counts, masses, times = fluid.get("active_count_by_frame"), fluid.get("active_mass_kg_by_frame"), timeline.get("time_s")
    if not isinstance(counts, list) or not isinstance(masses, list) or not isinstance(times, list) or not counts or len(counts) != len(masses) or len(counts) != len(times):
        raise ImpactError(f"{case_id} fluid ledger frame arrays are incomplete")
    for index, (count, mass, time) in enumerate(zip(counts, masses, times)):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ImpactError(f"{case_id} active count is invalid at frame {index}")
        _finite(mass, f"{case_id} active mass frame {index}")
        _finite(time, f"{case_id} timeline frame {index}")


def _native_rows(report: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    rows = report.get("rows")
    if not isinstance(rows, list):
        exact = report.get("exact_join")
        rows = exact.get("rows") if isinstance(exact, dict) else None
    if not isinstance(rows, list):
        raise ImpactError(f"{case_id} native report has no exact joined rows")
    seen: set[tuple[int, int]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("idp"), int) or not isinstance(row.get("zone"), int):
            raise ImpactError(f"{case_id} native row identity is malformed")
        key = (int(row["zone"]), int(row["idp"]))
        if key in seen:
            raise ImpactError(f"{case_id} native report duplicates identity {key}")
        seen.add(key)
        frame = row.get("first_missing_frame", row.get("first_disappeared_frame"))
        time = row.get("first_missing_time_s", row.get("first_disappeared_time_s"))
        bracket = row.get("bracket_s", row.get("first_disappeared_bracket_s"))
        if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0 or not isinstance(bracket, list) or len(bracket) != 2:
            raise ImpactError(f"{case_id} native row saved-frame fields are malformed")
        t = _finite(time, f"{case_id} native first-missing time")
        lo, hi = _finite(bracket[0], f"{case_id} native bracket low"), _finite(bracket[1], f"{case_id} native bracket high")
        if lo > hi:
            raise ImpactError(f"{case_id} native bracket is reversed")
        mass = row.get("initial_mass_kg")
        out.append({"identity_key": [key[0], key[1]], "frame": frame, "time_s": t, "bracket_s": [lo, hi], "motive_code": row.get("motive_code", row.get("native_motive_code")), "initial_mass_kg": (_finite(mass, f"{case_id} native initial mass") if mass is not None else None)})
    return out


def _frame_sample(summary: dict[str, Any], native: list[dict[str, Any]]) -> dict[str, Any]:
    fluid = summary["role_ledgers"]["fluid"]
    counts = fluid["active_count_by_frame"]
    masses = fluid["active_mass_kg_by_frame"]
    times = summary["timeline"]["time_s"]
    initial_count = int(fluid["initial_count"])
    initial_mass = _finite(fluid["initial_mass_kg"], "fluid initial mass")
    frames = sorted({row["frame"] for row in native})
    if any(frame >= len(times) for frame in frames):
        raise ImpactError("native first-missing frame exceeds typed timeline")
    checks: list[dict[str, Any]] = []
    for row in native:
        frame = row["frame"]
        if abs(float(times[frame]) - row["time_s"]) > 1e-9 or not (row["bracket_s"][0] - 1e-12 <= row["time_s"] <= row["bracket_s"][1] + 1e-12):
            raise ImpactError(f"native/typed saved-frame join mismatch for {row['identity_key']}")
    for frame in frames:
        checks.append({"frame": frame, "time_s": float(times[frame]), "active_count": int(counts[frame]), "active_mass_kg": float(masses[frame]), "active_count_fraction": int(counts[frame]) / initial_count if initial_count else None, "active_mass_fraction": float(masses[frame]) / initial_mass if initial_mass else None})
    exact_masses = [row["initial_mass_kg"] for row in native if row["initial_mass_kg"] is not None]
    proxy_mass = initial_mass / initial_count if initial_count else None
    return {"initial_fluid_count": initial_count, "initial_fluid_mass_kg": initial_mass, "native_target_count": len(native), "native_exact_initial_mass_kg": sum(exact_masses) if len(exact_masses) == len(native) else None, "native_exact_mass_rows": len(exact_masses), "typed_role_ledger_mass_per_particle_proxy_kg": proxy_mass, "proxy_target_mass_kg": (proxy_mass * len(native) if proxy_mass is not None else None), "proxy_target_mass_fraction_of_initial": (len(native) / initial_count if initial_count else None), "saved_frame_effects": checks, "final_active_count": int(counts[-1]), "final_active_mass_kg": float(masses[-1]), "final_active_count_fraction": int(counts[-1]) / initial_count if initial_count else None, "final_active_mass_fraction": float(masses[-1]) / initial_mass if initial_mass else None, "native_mass_semantics": "exact per-row native mass where report supplies initial_mass_kg; otherwise typed fluid-role homogeneous proxy only", "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    proof_specs = [("F6_ROOT256", args.proof256, "F6"), ("F6_ROOT259", args.proof259, "F6"), ("F4_ROOT250", args.proof250, "F4")]
    entries: list[dict[str, Any]] = []
    static_refs: list[dict[str, Any]] = [_ref(CURRENT, "CURRENT336", CURRENT_SHA), _ref(SCRIPT, "ROOT266 sidecar worker"), _ref(VENV, "literal Python interpreter"), _ref(VENV.resolve(), "resolved Python interpreter"), _ref(PYVENV, "pyvenv.cfg"), _ref(RUNTIME, "runtime v8"), _ref(DISPATCH, "dispatch v8")]
    seen: set[str] = set()
    proof_tags: list[dict[str, Any]] = []
    for tag, proof_arg, family in proof_specs:
        proof_ref, rows, _ = _proof_rows(proof_arg, family)
        static_refs.append(proof_ref)
        proof_tags.append({"tag": tag, "proof": proof_ref, "case_count": len(rows)})
        for row in rows:
            case_id = row["physical_case_id"]
            if case_id in seen:
                raise ImpactError(f"ROOT266 proof sets overlap at {case_id}")
            seen.add(case_id)
            entry = _case_source(row, family, proof_ref, tag)
            static_refs.append(entry["typed_summary"])
            if entry["native_report"] is not None:
                static_refs.append(entry["native_report"])
            entries.append(entry)
    # A JSON-only sidecar must never smuggle a payload into its parent request.
    for ref in static_refs:
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise ImpactError(f"payload entered ROOT266 static closure: {ref['path']}")
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise ImpactError(f"refusing to reuse ROOT266 output root: {output_root}")
    manifest = {"schema": MANIFEST_SCHEMA, "status": "READY_SOURCE_ONLY_TYPED_NATIVE_IMPACT_DIAGNOSTIC", "namespace": "ROOT266", "current_catalog": _ref(CURRENT, "CURRENT336", CURRENT_SHA), "proofs": proof_tags, "case_count": len(entries), "cases": entries, "claim_boundary": {"saved_frame_mass_and_count_effect": "DIAGNOSTIC_ONLY", "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "read_policy": {"prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False, "prepare_opened_obi4": False, "native_payload_read": False, "solver_started": False, "audit_inputs": "small completed typed summaries and native case reports only"}, "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 900, "memory_max_bytes": 1024 * 1024 * 1024, "small_json_read_bytes": sum(int(ref["bytes"]) for ref in static_refs), "h5_content_read": False, "jsonl_content_read": False, "native_payload_read": False}}
    manifest_path = output_root / "root266-impact-sidecar-manifest.json"
    _atomic(manifest_path, manifest)
    static_refs.append(_ref(manifest_path, "ROOT266 manifest"))
    input_sha = {ref["path"]: ref["sha256"] for ref in static_refs}
    request_path = args.request_output.expanduser().resolve()
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/root266-impact-sidecar.json"]
    request = {"schema": "ds02.request.v1", "shared_runtime_version": "v8", "family_id": "INFRA", "case_id": "ROOT266_TYPED_NATIVE_IMPACT_SIDECAR", "attempt_id": "root266-typed-native-impact-sidecar-001-root-forward", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_OUTPUT, "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in static_refs), "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command, "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())), "manifest_contract": {"path": str(manifest_path), "sha256": input_sha[str(manifest_path)]}, "source_proofs": proof_tags, "claim_boundary": manifest["claim_boundary"], "read_policy": manifest["read_policy"], "execution_allowed": True, "launch_allowed": True, "launch_owner": "root", "request_note": "JSON-only saved-frame impact diagnostic. It quantifies typed fluid active mass/count changes and exact/native identity mass where supplied; it never reports physical mass flux, fate, dynamics, or Q credit."}
    _atomic(request_path, request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT266 manifest", limit=MAX_OUTPUT), "request": str(request_path), "request_sha256": _digest(request_path, "ROOT266 request", limit=MAX_OUTPUT), "case_count": len(entries), "payload_content_opened": False, "launch_allowed": True}


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _json(args.manifest, "ROOT266 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_SOURCE_ONLY_TYPED_NATIVE_IMPACT_DIAGNOSTIC":
        raise ImpactError("ROOT266 manifest schema/status differs")
    results: list[dict[str, Any]] = []
    for entry in manifest.get("cases", []):
        case_id = entry.get("physical_case_id")
        try:
            summary_ref = entry["typed_summary"]
            summary_path = _path(summary_ref["path"], f"{case_id} typed summary")
            if _digest(summary_path, f"{case_id} typed summary", limit=MAX_SMALL) != _sha(summary_ref["sha256"], f"{case_id} typed summary SHA"):
                raise ImpactError(f"{case_id} typed summary changed")
            summary = _json(summary_path, f"{case_id} typed summary")
            _validate_summary(summary, case_id)
            native_ref = entry.get("native_report")
            if native_ref is None:
                results.append({"physical_case_id": case_id, "family_id": entry["family_id"], "status": "TYPED_ONLY_NO_NATIVE_JOIN", "impact": _frame_sample(summary, []), "native_join": "NOT_AVAILABLE", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
                continue
            report_path = _path(native_ref["path"], f"{case_id} native report")
            if _digest(report_path, f"{case_id} native report", limit=MAX_SMALL) != _sha(native_ref["sha256"], f"{case_id} native report SHA"):
                raise ImpactError(f"{case_id} native report changed")
            report = _json(report_path, f"{case_id} native report")
            if report.get("physical_case_id") != case_id:
                raise ImpactError(f"{case_id} native report identity changed")
            native = _native_rows(report, case_id)
            impact = _frame_sample(summary, native)
            results.append({"physical_case_id": case_id, "family_id": entry["family_id"], "status": "COMPLETED_SAVED_FRAME_IMPACT_DIAGNOSTIC_ONLY", "native_join": "EXACT_ID_AND_SAVED_BRACKET_INPUT_REPORT", "native_rows": len(native), "impact": impact, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
        except (ImpactError, OSError, KeyError, TypeError, ValueError) as exc:
            results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    failed = [row for row in results if row.get("status") == "FAILED"]
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_JSON_ONLY_SAVED_FRAME_IMPACT_DIAGNOSTIC", "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed), "typed_only": sum(row.get("status") == "TYPED_ONLY_NO_NATIVE_JOIN" for row in results)}, "claim_boundary": manifest["claim_boundary"], "read_policy": {"typed_summary_read": True, "native_case_report_read": True, "h5_content_read": False, "jsonl_content_read": False, "native_payload_read": False, "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).expanduser().resolve()), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"], "typed_only": report["counts"]["typed_only"]}


def _self_test() -> dict[str, Any]:
    # Keep this test payload-free: it validates the semantic gates that prevent
    # a typed active-ledger diagnostic from becoming a flux/fate claim.
    summary = {"role_ledgers": {"fluid": {"initial_count": 10, "initial_mass_kg": 1.0, "units": {"mass": "kg", "time": "s"}, "active_count_by_frame": [10, 9], "active_mass_kg_by_frame": [1.0, 0.9]}}, "timeline": {"time_s": [0.0, 1.0]}}
    _validate_summary(summary, "fixture")
    native = [{"identity_key": [0, 4], "frame": 1, "time_s": 1.0, "bracket_s": [0.0, 1.0], "motive_code": 1, "initial_mass_kg": 0.1}]
    result = _frame_sample(summary, native)
    if result["native_exact_initial_mass_kg"] != 0.1 or result["physical_mass_flux"] != "UNKNOWN":
        raise ImpactError("fixture impact semantics failed")
    try:
        bad = dict(summary)
        bad["role_ledgers"] = {"fluid": {**summary["role_ledgers"]["fluid"], "units": {"mass": "g", "time": "s"}}}
        _validate_summary(bad, "bad-units")
    except ImpactError:
        pass
    else:
        raise ImpactError("invalid units were accepted")
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "payload_opened": False, "checks": ["SI role-ledger units", "exact saved-frame bracket", "optional exact native per-row mass", "typed homogeneous mass proxy is labeled", "physical flux/fate/Q remain UNKNOWN"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--proof256", type=Path, required=True)
    prep.add_argument("--proof259", type=Path, required=True)
    prep.add_argument("--proof250", type=Path, required=True)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--manifest", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (ImpactError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ROOT266_IMPACT_SIDECAR_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
