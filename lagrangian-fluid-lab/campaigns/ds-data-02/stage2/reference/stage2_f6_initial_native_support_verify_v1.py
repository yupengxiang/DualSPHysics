#!/usr/bin/env python3
"""Verify ROOT276 V8 identity/support reports without reopening payloads.

This is a downstream structural verifier.  It rechecks the two producer-local
physical identities and the four explicit source-domain bridges before it
accepts any case result.  It reads only bounded JSON manifests/reports and
never opens the deferred BI4 or VTK files.  A mixed PASS/UNKNOWN/FAILED
report remains mixed; failed cases cannot be promoted by aggregate status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v8"
OUTPUT_SCHEMA = "ds02.stage2.f6-initial-native-support-audit.v8"
RESULT_SCHEMA = "ds02.stage2.f6-initial-native-support-verifier.v1"
SENTINELS = ("F6-S1", "F6-S2")
GRIDS = ("source_current", "coarse", "fine")
MAX_JSON_BYTES = 32 * 1024 * 1024
DIRECT_STATUS = "PASS_DIRECT_PRODUCER_PHYSICAL_ID"
BRIDGE_STATUS = "PASS_EXACT_SOURCE_DOMAIN"
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}


class VerifyFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > MAX_JSON_BYTES:
        raise VerifyFailure(f"{label} exceeds bounded JSON cap: {path}")
    raw = path.read_bytes()
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if tuple(getattr(before, field) for field in fields) != tuple(getattr(after, field) for field in fields):
        raise VerifyFailure(f"{label} changed during read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be a JSON object")
    stat = {"device": int(after.st_dev), "inode": int(after.st_ino), "bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)}
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": stat}


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise VerifyFailure(f"{label} is not a SHA-256 digest")
    return value.lower()


def _case_map(manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != 6:
        raise VerifyFailure("ROOT276 manifest must contain exactly six cases")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str) or not isinstance(row.get("grid"), str):
            raise VerifyFailure("ROOT276 case lacks sentinel_id/grid")
        key = (row["sentinel_id"], row["grid"])
        if key in result or key[0] not in SENTINELS or key[1] not in GRIDS:
            raise VerifyFailure(f"invalid or duplicate ROOT276 case {key}")
        result[key] = row
    expected = {(sid, grid) for sid in SENTINELS for grid in GRIDS}
    if set(result) != expected:
        raise VerifyFailure(f"ROOT276 case set differs: {sorted(result)}")
    return result


def _source_record(identity: dict[str, Any], name: str, label: str) -> dict[str, Any]:
    value = identity.get(name)
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerifyFailure(f"{label} source record is missing")
    _digest(value.get("sha256"), f"{label} SHA")
    if value.get("payload_read_by_builder") is not False:
        raise VerifyFailure(f"{label} is not marked metadata-only")
    return value


def _producer_identity(case: dict[str, Any], key: tuple[str, str], direct: bool) -> dict[str, Any]:
    identity = case.get("domain_equivalence_v8")
    if not isinstance(identity, dict):
        raise VerifyFailure(f"{key} lacks domain_equivalence_v8")
    if identity.get("no_label_fallback") is not True:
        raise VerifyFailure(f"{key} permits label fallback")
    if identity.get("sentinel_id") != key[0] or identity.get("grid") != key[1]:
        raise VerifyFailure(f"{key} domain identity labels do not match the case key")
    source = identity.get("source_identity")
    if not isinstance(source, dict):
        raise VerifyFailure(f"{key} lacks source identity")
    for field in ("case_id", "attempt_id", "physical_case_id", "source_def_sha256", "source_bi4_sha256", "source_receipt_sha256"):
        if field not in source:
            raise VerifyFailure(f"{key} source identity lacks {field}")
    _digest(source["source_def_sha256"], f"{key} source Def SHA")
    _digest(source["source_bi4_sha256"], f"{key} source BI4 SHA")
    _digest(source["source_receipt_sha256"], f"{key} source receipt SHA")
    _source_record(source, "source_def_record", f"{key} source Def")
    _source_record(source, "source_xml", f"{key} source XML")
    # V8 carries the normalized metadata-only receipt in producer_receipt_v6;
    # the legacy producer_receipt is retained for lineage but does not carry
    # the explicit payload_read_by_builder declaration.
    receipt = case.get("producer_receipt_v6") or case.get("producer_receipt")
    if not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
        raise VerifyFailure(f"{key} producer receipt record is missing")
    _digest(receipt.get("sha256"), f"{key} producer receipt SHA")
    if receipt.get("payload_read_by_builder") is not False:
        raise VerifyFailure(f"{key} producer receipt is not metadata-only")
    if direct:
        if not isinstance(identity.get("physical_case_id"), str) or not identity["physical_case_id"]:
            raise VerifyFailure(f"{key} lacks direct physical_case_id")
        if identity.get("status") != DIRECT_STATUS:
            raise VerifyFailure(f"{key} direct case is not marked {DIRECT_STATUS}")
        if identity.get("physical_case_id") != source.get("physical_case_id"):
            raise VerifyFailure(f"{key} direct physical identity differs from source identity")
        if case.get("physical_case_id") != identity.get("physical_case_id"):
            raise VerifyFailure(f"{key} case physical identity is not bound to the producer")
        return {"mode": "DIRECT_PRODUCER_PHYSICAL_ID", "physical_case_id": identity["physical_case_id"]}

    if identity.get("status") != BRIDGE_STATUS:
        raise VerifyFailure(f"{key} bridge is not marked {BRIDGE_STATUS}")
    if identity.get("source_physical_case_id") != source.get("physical_case_id"):
        raise VerifyFailure(f"{key} bridge source physical identity is not exact")
    comparison = identity.get("def_xml_comparison")
    if not isinstance(comparison, dict) or comparison.get("status") != "PASS_ONLY_DP_RESOLUTION_CHANGE":
        raise VerifyFailure(f"{key} does not have the exact dp-only Def comparison")
    if comparison.get("allowed_path") != "/case[0]/casedef[2]/geometry[0]/definition":
        raise VerifyFailure(f"{key} Def comparison path is not the registered geometry path")
    diffs = comparison.get("diffs")
    if not isinstance(diffs, list) or len(diffs) != 1 or diffs[0].get("key") != "dp" or diffs[0].get("path") != comparison["allowed_path"]:
        raise VerifyFailure(f"{key} Def comparison has changes beyond dp")
    common = identity.get("common_hashes")
    if not isinstance(common, dict):
        raise VerifyFailure(f"{key} bridge common hashes are missing")
    required = {"source_def": source["source_def_sha256"], "source_generated_bi4": source["source_bi4_sha256"], "source_generated_xml": source["source_xml"].get("sha256"), "source_producer_receipt": source["source_receipt_sha256"]}
    for name, expected in required.items():
        if common.get(name) != expected:
            raise VerifyFailure(f"{key} bridge common hash {name} is not joined to source")
        _digest(common.get(name), f"{key} bridge common hash {name}")
    semantic = identity.get("semantic_input_paths")
    if not isinstance(semantic, dict) or set(("source_def", "source_generated_bi4", "source_generated_xml", "source_producer_receipt")) - set(semantic):
        raise VerifyFailure(f"{key} bridge semantic source paths are incomplete")
    if identity.get("no_label_fallback") is not True:
        raise VerifyFailure(f"{key} bridge permits label fallback")
    owner = identity.get("owner_proofs")
    if not isinstance(owner, dict) or owner.get("continuous_owner") != "ROOT252" or owner.get("rigid") != "ROOT244":
        raise VerifyFailure(f"{key} bridge owner proof references are incomplete")
    return {"mode": "EXACT_SOURCE_DOMAIN", "physical_case_id": source["physical_case_id"]}


def verify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_ROOT276_F6_INITIAL_NATIVE_SUPPORT_V8_DOMAIN_BRIDGE":
        raise VerifyFailure("ROOT276 V8 manifest schema/status mismatch")
    cases = _case_map(manifest)
    modes: dict[str, int] = {"DIRECT_PRODUCER_PHYSICAL_ID": 0, "EXACT_SOURCE_DOMAIN": 0}
    bindings: dict[str, dict[str, Any]] = {}
    for key, case in cases.items():
        direct = key[1] == "source_current"
        info = _producer_identity(case, key, direct)
        modes[info["mode"]] += 1
        bindings[f"{key[0]}/{key[1]}"] = info
        deferred = case.get("deferred")
        if not isinstance(deferred, dict) or set(deferred) != {"native_bi4", "fluid_vtk", "bound_vtk"}:
            raise VerifyFailure(f"{key} deferred payload roles are incomplete")
        source_identity = (case.get("domain_equivalence_v8") or {}).get("source_identity") or {}
        for role, record in deferred.items():
            if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not isinstance(record.get("bytes"), int) or record["bytes"] < 0:
                raise VerifyFailure(f"{key}/{role} deferred record is malformed")
            known_sha = record.get("known_sha256")
            # The source-current native BI4 already has a trusted producer
            # SHA in the V8 source identity.  Generated candidates and VTK
            # payloads remain unknown until the parent reservation/worker.
            if known_sha not in (None, ""):
                if not (key[1] == "source_current" and role == "native_bi4" and known_sha == source_identity.get("source_bi4_sha256")):
                    raise VerifyFailure(f"{key}/{role} has an unrelated deferred SHA")
            if record.get("worker_must_full_sha_pre_and_post") is not True or record.get("worker_must_reject_stat_or_sha_change") is not True:
                raise VerifyFailure(f"{key}/{role} lacks worker stability requirements")
    deferred_rows = manifest.get("deferred_input_records")
    if not isinstance(deferred_rows, list) or len(deferred_rows) != 18:
        raise VerifyFailure("ROOT276 V8 manifest must expose 18 deferred payload records")
    expected_paths = {record["path"] for case in cases.values() for record in case["deferred"].values()}
    actual_paths = {record.get("path") for record in deferred_rows if isinstance(record, dict)}
    if actual_paths != expected_paths or len(actual_paths) != 18:
        raise VerifyFailure("top-level deferred records do not exactly match case deferred records")
    qualification = manifest.get("scientific_qualification") or manifest.get("qualification")
    if not isinstance(qualification, dict) or qualification.get("QI") != "UNKNOWN" or qualification.get("QN") != "UNKNOWN" or qualification.get("QE") != "UNKNOWN" or qualification.get("credit") != 0:
        raise VerifyFailure("manifest advertises scientific credit")
    return {"cases": len(cases), "direct_identity_cases": modes["DIRECT_PRODUCER_PHYSICAL_ID"], "exact_source_domain_cases": modes["EXACT_SOURCE_DOMAIN"], "deferred_payloads": len(actual_paths), "bindings": bindings}


def _result_case_map(output: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows = output.get("cases")
    if not isinstance(rows, list):
        raise VerifyFailure("worker output cases is not a list")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str) or not isinstance(row.get("grid"), str):
            raise VerifyFailure("worker output case identity is malformed")
        key = (row["sentinel_id"], row["grid"])
        if key in result:
            raise VerifyFailure(f"duplicate worker output case {key}")
        result[key] = row
    return result


def verify_output(output: dict[str, Any], manifest_summary: dict[str, Any]) -> dict[str, Any]:
    if output.get("schema") != OUTPUT_SCHEMA:
        raise VerifyFailure("worker output schema is not ROOT276 V8")
    rows = _result_case_map(output)
    expected_keys = {(sid, grid) for sid in SENTINELS for grid in GRIDS}
    if set(rows) != expected_keys:
        raise VerifyFailure("worker output does not contain exactly six sentinel/grid cases")
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    for key, row in rows.items():
        status = row.get("status")
        if isinstance(status, str) and status.startswith("PASS_CASE_INITIAL_SUPPORT"):
            counts["PASS"] += 1
            if row.get("deferred_payload_read") is not True:
                raise VerifyFailure(f"{key} PASS case does not record guarded payload read")
            identity = row.get("producer_join") or row.get("identity")
            if not isinstance(identity, dict):
                raise VerifyFailure(f"{key} PASS case lacks producer join")
            if identity.get("status") not in ("PASS", "PASS_EXACT_SOURCE_DOMAIN"):
                raise VerifyFailure(f"{key} PASS case has no successful identity join")
            if not isinstance(row.get("native_header"), dict):
                raise VerifyFailure(f"{key} PASS case lacks native header record")
            if not isinstance(row.get("typed_role_counts"), dict):
                raise VerifyFailure(f"{key} PASS case lacks typed role counts")
            for role, count in row["typed_role_counts"].items():
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise VerifyFailure(f"{key} has invalid typed role count {role}")
            header = row["native_header"]
            if "frame_native_sha256" in header:
                _digest(header.get("frame_native_sha256"), f"{key} native frame SHA")
                if isinstance(header.get("frame_native_bytes"), bool) or not isinstance(header.get("frame_native_bytes"), int) or header["frame_native_bytes"] < 0:
                    raise VerifyFailure(f"{key} native frame byte count is invalid")
                if header.get("frame_native_sha_matches_guarded_post") is not True:
                    raise VerifyFailure(f"{key} native frame is not joined to the guarded post-SHA")
            for field in ("MassFluid", "MassBound", "Dp"):
                value = header.get(field)
                if isinstance(value, dict) and value.get("value") is not None:
                    try:
                        numeric = float(value["value"])
                    except (TypeError, ValueError) as exc:
                        raise VerifyFailure(f"{key} {field} value is not numeric") from exc
                    if not __import__("math").isfinite(numeric):
                        raise VerifyFailure(f"{key} {field} value is non-finite")
            support = row.get("support")
            if isinstance(support, dict):
                if not isinstance(support.get("fluid_inside_explicit_owner_box"), bool):
                    raise VerifyFailure(f"{key} support lacks explicit owner-box result")
                if isinstance(support.get("fluid_outside_count"), bool) or not isinstance(support.get("fluid_outside_count"), int) or support["fluid_outside_count"] < 0:
                    raise VerifyFailure(f"{key} support outside count is invalid")
            mass = row.get("mass_separation")
            if isinstance(mass, dict) and mass.get("no_rescale") is not True:
                raise VerifyFailure(f"{key} mass separation allows rescaling")
            vtk = row.get("vtk")
            if isinstance(vtk, dict):
                for role in ("fluid_vtk", "bound_vtk"):
                    entry = vtk.get(role)
                    if not isinstance(entry, dict):
                        raise VerifyFailure(f"{key} missing {role} VTK diagnostic")
                    source = entry.get("source_record")
                    if not isinstance(source, dict):
                        raise VerifyFailure(f"{key} {role} lacks guarded source record")
                    _digest(source.get("sha256"), f"{key} {role} source SHA")
                    if source.get("stable_read") is not True or source.get("pre_post_sha_equal") is not True:
                        raise VerifyFailure(f"{key} {role} source is not stable across the worker read")
                comparison = row.get("vtk_comparison")
                if not isinstance(comparison, dict) or not all(isinstance(comparison.get(name), bool) for name in ("fluid_count_matches_native", "bound_count_matches_native_nonfluid")):
                    raise VerifyFailure(f"{key} VTK/native count comparison is incomplete")
            # Native mass may be absent in an initial position-only product;
            # this is a field UNKNOWN, never an XML-derived pass.
            if "MassFluid" not in row["native_header"]:
                row.setdefault("field_status", {})["native_massfluid"] = "UNKNOWN_MISSING_NATIVE_MASSFLUID"
        elif isinstance(status, str) and status.startswith("UNKNOWN"):
            counts["UNKNOWN"] += 1
            if row.get("scientific_qualification", QUALIFICATION).get("credit", 0) != 0:
                raise VerifyFailure(f"{key} UNKNOWN case advertises credit")
        elif isinstance(status, str) and status.startswith("FAILED"):
            counts["FAILED"] += 1
            if row.get("scientific_qualification", QUALIFICATION).get("credit", 0) != 0:
                raise VerifyFailure(f"{key} FAILED case advertises credit")
        else:
            raise VerifyFailure(f"{key} has unclassified status {status!r}")
    declared = output.get("case_counts")
    if not isinstance(declared, dict) or {k: int(declared.get(k, -1)) for k in counts} != counts:
        raise VerifyFailure(f"worker case_counts do not preserve mixed outcome: expected {counts}, got {declared}")
    if output.get("scientific_qualification", QUALIFICATION).get("credit", 0) != 0:
        raise VerifyFailure("worker aggregate advertises scientific credit")
    return counts


def verify(manifest_path: Path, output_path: Path | None = None, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = _read_json(manifest_path, "ROOT276 V8 manifest")
    summary = verify_manifest(manifest)
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "status": "VERIFIED_ROOT276_V8_MANIFEST_IDENTITY_AND_DEFERRED_CONTRACT",
        "manifest": manifest_record,
        "manifest_summary": {key: value for key, value in summary.items() if key != "bindings"},
        "identity_bindings": summary["bindings"],
        "worker_output": None,
        "scientific_qualification": QUALIFICATION,
        "read_scope": {"manifest_json_only": True, "worker_output_json_only": output_path is not None, "native_bi4_read": False, "vtk_read": False, "solver_launch": False},
    }
    if output_path is not None:
        output, output_record = _read_json(output_path, "ROOT276 V8 worker output")
        result["worker_output"] = {"record": output_record, "case_counts": verify_output(output, summary)}
        result["status"] = "VERIFIED_ROOT276_V8_MANIFEST_AND_MIXED_WORKER_OUTCOMES"
    if verification_output is not None:
        _write_once(verification_output, result)
    return result


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise VerifyFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{__import__('os').getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _tiny_record(path: Path, payload: str) -> dict[str, Any]:
    path.write_text(payload, encoding="utf-8")
    raw = path.read_bytes(); st = path.stat()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "payload_read_by_builder": False, "stat": {"bytes": st.st_size, "dev": st.st_dev, "ino": st.st_ino, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns}}


def _fixture_manifest(root: Path) -> Path:
    cases: list[dict[str, Any]] = []
    deferred_rows: list[dict[str, Any]] = []
    for sid in SENTINELS:
        for grid in GRIDS:
            source_def = _tiny_record(root / f"{sid}-{grid}-Def.json", "source-def")
            source_xml = _tiny_record(root / f"{sid}-{grid}-XML.json", "source-xml")
            source = {"case_id": f"{sid}-{grid}", "attempt_id": f"attempt-{sid}-{grid}", "physical_case_id": f"physical-{sid}", "source_def_sha256": source_def["sha256"], "source_bi4_sha256": "a" * 64, "source_receipt_sha256": "b" * 64, "source_def_record": source_def, "source_xml": source_xml}
            direct = grid == "source_current"
            eq: dict[str, Any] = {"sentinel_id": sid, "grid": grid, "no_label_fallback": True, "physical_case_id": source["physical_case_id"], "source_identity": source, "status": DIRECT_STATUS if direct else BRIDGE_STATUS}
            case: dict[str, Any] = {"sentinel_id": sid, "grid": grid, "physical_case_id": source["physical_case_id"], "domain_equivalence_v8": eq, "producer_receipt": {"path": str(root / f"{sid}-{grid}-receipt.json"), "sha256": "c" * 64, "payload_read_by_builder": False}, "deferred": {}}
            if not direct:
                eq.update({"source_physical_case_id": source["physical_case_id"], "common_hashes": {"source_def": source["source_def_sha256"], "source_generated_bi4": source["source_bi4_sha256"], "source_generated_xml": source_xml["sha256"], "source_producer_receipt": source["source_receipt_sha256"]}, "def_xml_comparison": {"status": "PASS_ONLY_DP_RESOLUTION_CHANGE", "allowed_path": "/case[0]/casedef[2]/geometry[0]/definition", "diffs": [{"key": "dp", "path": "/case[0]/casedef[2]/geometry[0]/definition"}]}, "semantic_input_paths": {"source_def": source_def["path"], "source_generated_bi4": "fixture.bi4", "source_generated_xml": source_xml["path"], "source_producer_receipt": "fixture-receipt.json"}, "owner_proofs": {"continuous_owner": "ROOT252", "rigid": "ROOT244"}})
            for role in ("native_bi4", "fluid_vtk", "bound_vtk"):
                record = {"path": str(root / f"{sid}-{grid}-{role}.payload"), "bytes": 1, "known_sha256": None, "worker_must_full_sha_pre_and_post": True, "worker_must_reject_stat_or_sha_change": True}
                case["deferred"][role] = record; deferred_rows.append(record)
            cases.append(case)
    return_data = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_ROOT276_F6_INITIAL_NATIVE_SUPPORT_V8_DOMAIN_BRIDGE", "cases": cases, "deferred_input_records": deferred_rows, "scientific_qualification": QUALIFICATION}
    path = root / "manifest.json"; path.write_text(json.dumps(return_data), encoding="utf-8"); return path


def _fixture_output(root: Path) -> Path:
    rows: list[dict[str, Any]] = []
    statuses = ["PASS_CASE_INITIAL_SUPPORT_DIAGNOSTIC", "PASS_CASE_INITIAL_SUPPORT_DIAGNOSTIC", "PASS_CASE_INITIAL_SUPPORT_DIAGNOSTIC", "PASS_CASE_INITIAL_SUPPORT_DIAGNOSTIC", "UNKNOWN_PRODUCER_OR_DOMAIN_IDENTITY", "FAILED_CASE_INITIAL_SUPPORT"]
    for (sid, grid), status in zip(((sid, grid) for sid in SENTINELS for grid in GRIDS), statuses):
        row: dict[str, Any] = {"sentinel_id": sid, "grid": grid, "status": status, "scientific_qualification": QUALIFICATION}
        if status.startswith("PASS"):
            row.update({"deferred_payload_read": True, "producer_join": {"status": "PASS"}, "native_header": {"MassFluid": {"value": 1.0}}, "typed_role_counts": {"fluid": 1}})
        rows.append(row)
    path = root / "output.json"; path.write_text(json.dumps({"schema": OUTPUT_SCHEMA, "status": "COMPLETE_PARTIAL_F6_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_V8_NO_SCIENTIFIC_Q", "cases": rows, "case_counts": {"PASS": 4, "UNKNOWN": 1, "FAILED": 1}, "scientific_qualification": QUALIFICATION}), encoding="utf-8"); return path


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f6-v8-verifier-") as td:
        root = Path(td); manifest = _fixture_manifest(root); output = _fixture_output(root)
        result = verify(manifest, output)
        assert result["worker_output"]["case_counts"] == {"PASS": 4, "UNKNOWN": 1, "FAILED": 1}
        bad = json.loads(manifest.read_text()); bad["cases"][2]["domain_equivalence_v8"]["def_xml_comparison"]["diffs"] = [{"key": "size", "path": "/case[0]/casedef[2]/geometry[0]/definition"}]
        bad_path = root / "bad-manifest.json"; bad_path.write_text(json.dumps(bad))
        try:
            verify(bad_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("non-dp domain bridge accepted")
        bad_output = json.loads(output.read_text()); bad_output["cases"][-1]["status"] = "PASS_CASE_INITIAL_SUPPORT_DIAGNOSTIC"; bad_output["case_counts"]["FAILED"] = 0; bad_output["case_counts"]["PASS"] = 5
        bad_output_path = root / "bad-output.json"; bad_output_path.write_text(json.dumps(bad_output))
        try:
            verify(manifest, bad_output_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("failed case was promoted to success")
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if args.manifest is None:
        parser.error("--verify requires --manifest")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V1: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "scientific_credit": 0, "manifest_summary": result["manifest_summary"], "worker_output": result["worker_output"]}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
