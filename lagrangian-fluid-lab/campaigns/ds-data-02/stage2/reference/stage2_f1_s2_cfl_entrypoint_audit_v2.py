#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Audit the actual CFL/timestep/output entry points for F1 source runs.

This is a bounded provenance consumer.  It joins request JSON, terminal
receipts, the XML actually handed to the solver, and a small set of official
source files.  It reports whether the actual launch exposed ``-cfl`` or
``-tout`` and whether the XML ``cflnumber``/``TimeOut`` declarations were the
only available controls.  It does not read BI4/native output or launch a
solver.  A half-CFL label is not evidence unless the receipt/XML pair proves
the value and the source code path is bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f1-s2.cfl-entrypoint-audit.v2"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.cfl-entrypoint-manifest.v2"
PASS_STATUS = "PASS_F1_CFL_ENTRYPOINT_SOURCE_AND_REQUEST_LINEAGE_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F1_CFL_ENTRYPOINT_AUDIT_V2"
MAX_JSON = 8 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
SOURCE_PATTERNS = (
    "SetCFLnumber", "GetCFLnumber", "CFLnumber", "CoefDtMin",
    "TimeOut", "TimeMax", "DtVariable", "SaveDt->Config", "ReadXmlRun",
)


class AuditFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _read(path: Path, label: str, limit: int, kind: str) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular file")
    before = _stat(path)
    if before["bytes"] > limit:
        raise AuditFailure(f"{label} exceeds bounded limit: {before['bytes']}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            chunks.append(chunk)
    after = _stat(path)
    if before != after:
        raise AuditFailure(f"{label} changed during read")
    raw = b"".join(chunks)
    if kind == "json":
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditFailure(f"{label} is not JSON") from exc
        if not isinstance(value, dict):
            raise AuditFailure(f"{label} is not a JSON object")
    elif kind == "xml":
        try:
            value = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise AuditFailure(f"{label} is not XML") from exc
    elif kind == "text":
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuditFailure(f"{label} is not UTF-8 source") from exc
    else:
        raise AssertionError(kind)
    return value, {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"], "stat": after, "stable_read": True, "content_scope": {"json": "bounded_request_or_receipt_metadata", "xml": "small_solver_input_XML", "text": "bounded_official_source_excerpt_input"}[kind]}


def _record(binding: Any, label: str, kind: str) -> tuple[Any, dict[str, Any]]:
    if isinstance(binding, str):
        binding = {"path": binding}
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise AuditFailure(f"{label} binding missing path")
    value, record = _read(Path(binding["path"]), label, {"json": MAX_JSON, "xml": MAX_XML, "text": MAX_SOURCE}[kind], kind)
    for key in ("sha256", "bytes"):
        if binding.get(key) is not None and (str(binding[key]).lower() != record[key] if key == "sha256" else int(binding[key]) != record[key]):
            raise AuditFailure(f"{label} {key} differs from binding")
    if isinstance(binding.get("stat"), dict):
        for key in ("dev", "ino", "bytes", "mtime_ns", "ctime_ns"):
            if key in binding["stat"] and int(binding["stat"][key]) != record["stat"][key]:
                raise AuditFailure(f"{label} stat.{key} differs from binding")
    return value, record


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: Any, label: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _xml_controls(root: ET.Element) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for node in root.iter():
        if _local(node.tag).lower() == "parameter":
            key = node.get("key") or node.get("name")
            if key and node.get("value") is not None:
                parameters[str(key)] = _number(node.get("value"), f"parameter {key}")
    cfl = [_number(node.get("value"), "cflnumber") for node in root.iter() if _local(node.tag).lower() == "cflnumber" and node.get("value") is not None]
    cfl = [value for value in cfl if value is not None]
    savedt = []
    for node in root.iter():
        if _local(node.tag).lower() == "savedt":
            savedt.append(dict(node.attrib))
    selected = {key: parameters[key] for key in ("CoefDtMin", "DtIni", "DtMin", "DtFixed", "DtAllParticles", "TimeOut", "TimeMax") if key in parameters}
    return {"parameters": selected, "cflnumber_values": cfl, "savedt_nodes": savedt}


def _argv_controls(argv: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    aliases = {"cfl": "CFL", "tout": "TimeOut", "tmax": "TimeMax", "toutx": "TimeOutExtra", "dtini": "DtIni", "dtmin": "DtMin", "dtfixed": "DtFixed", "coefdtmin": "CoefDtMin"}
    for token in argv:
        body = str(token).lstrip("-")
        if ":" in body:
            name, value = body.split(":", 1)
        elif "=" in body:
            name, value = body.split("=", 1)
        else:
            continue
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if key in aliases:
            number = _number(value, name)
            result[aliases[key]] = {"raw": value, "value": number, "token": str(token)}
    return result


def _argv(request: dict[str, Any], receipt: dict[str, Any]) -> tuple[list[str], str]:
    execution = receipt.get("execution") if isinstance(receipt.get("execution"), dict) else {}
    if isinstance(execution.get("launch_argv"), list):
        return [str(item) for item in execution["launch_argv"]], "receipt.execution.launch_argv"
    if isinstance(receipt.get("command"), list):
        return [str(item) for item in receipt["command"]], "receipt.command"
    if isinstance(request.get("command"), list):
        return [str(item) for item in request["command"]], "request.command_fallback"
    return [], "missing"


def _source_evidence(source_records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for index, binding in enumerate(source_records):
        text, record = _record(binding, f"official CFL source {index}", "text")
        records.append(record)
        lines = []
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(pattern in line for pattern in SOURCE_PATTERNS):
                lines.append({"line": line_no, "text": line.strip()})
        evidence.append({"source": record, "matching_lines": lines[:80], "matching_line_count": len(lines)})
    return records, evidence


def _same_path(left: Any, right: str) -> bool:
    return isinstance(left, str) and Path(left).expanduser().absolute() == Path(right).expanduser().absolute()


def _request_lineage(receipt: dict[str, Any], source_request: dict[str, Any],
                     source_request_record: dict[str, Any], label: str) -> dict[str, Any]:
    """Join a source request to the request embedded in a terminal receipt.

    Root forwarding can wrap a source request in a new runtime request.  The
    old worker compared the receipt's request path directly to the source
    request and therefore either rejected this legitimate lineage or, when
    used only as metadata, failed to prove the join.  The wrapper is accepted
    only when its ``root_canonical_binding`` names the exact source path and
    SHA.  A direct path/SHA request remains supported for the two F1-S1
    solver receipts.
    """
    embedded = receipt.get("request")
    if not isinstance(embedded, dict):
        raise AuditFailure(f"{label} receipt has no embedded request object")
    binding = embedded.get("root_canonical_binding")
    source_path = source_request_record["path"]
    source_sha = source_request_record["sha256"]
    if isinstance(binding, dict):
        bound_path = binding.get("source_request")
        bound_sha = binding.get("source_sha256")
        if not _same_path(bound_path, source_path):
            raise AuditFailure(f"{label} root_canonical_binding.source_request mismatch")
        if str(bound_sha or "").lower() != source_sha:
            raise AuditFailure(f"{label} root_canonical_binding.source_sha256 mismatch")
        join_kind = "source_request_to_embedded_root_canonical_binding"
    else:
        if not (_same_path(embedded.get("path"), source_path)
                and str(embedded.get("sha256") or "").lower() == source_sha):
            raise AuditFailure(f"{label} receipt request is neither direct source request nor bound wrapper")
        join_kind = "direct_source_request"
    actual_identity = {
        key: embedded[key] for key in ("case_id", "physical_case_id", "attempt_id", "schema")
        if key in embedded
    }
    return {
        "status": "PASS_SOURCE_REQUEST_LINEAGE_JOIN",
        "join_kind": join_kind,
        "source_request": source_request_record,
        "source_request_semantics": {
            "schema": source_request.get("schema"),
            "case_id": source_request.get("case_id"),
            "physical_case_id": source_request.get("physical_case_id"),
            "attempt_id": source_request.get("attempt_id"),
        },
        "embedded_receipt_request": actual_identity,
        "direct_source_to_receipt_request_sha": join_kind == "direct_source_request",
        "root_canonical_binding_verified": isinstance(binding, dict),
    }


def _entry(entry: dict[str, Any], label: str, source_records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    request, request_record = _record(entry.get("request"), f"{label} request", "json")
    receipt, receipt_record = _record(entry.get("receipt"), f"{label} receipt", "json")
    root, xml_record = _record(entry.get("xml"), f"{label} solver XML", "xml")
    lineage = _request_lineage(receipt, request, request_record, label)
    argv, authority = _argv(request, receipt)
    xml = _xml_controls(root)
    launch = _argv_controls(argv)
    runtime = receipt.get("status")
    execution = receipt.get("execution") if isinstance(receipt.get("execution"), dict) else {}
    return {
        "label": label,
        "variant": entry.get("variant"),
        "pair_group": entry.get("pair_group"),
        "grid": entry.get("grid"),
        "request": request_record,
        "receipt": receipt_record,
        "request_lineage": lineage,
        "solver_xml": xml_record,
        "request_command": [str(item) for item in request.get("command", [])] if isinstance(request.get("command"), list) else [],
        "receipt_launch_argv": argv,
        "launch_control_authority": authority,
        "request_command_controls": _argv_controls([str(item) for item in request.get("command", [])]) if isinstance(request.get("command"), list) else {},
        "receipt_launch_controls": launch,
        "xml_declared_controls": xml,
        "receipt_status": runtime,
        "returncode": execution.get("returncode", receipt.get("returncode")),
        "completed": str(runtime or "").lower().startswith(("complete", "success")) and execution.get("returncode", receipt.get("returncode")) in (None, 0),
        "cfl_entry": {
            "xml_cflnumber": xml["cflnumber_values"],
            "argv_cfl": launch.get("CFL"),
            "runtime_cfl_override_present": "CFL" in launch,
            "actual_cfl_authority": "receipt launch -cfl override" if "CFL" in launch else ("solver XML constants/cflnumber" if xml["cflnumber_values"] else "UNKNOWN"),
        },
        "output_entry": {
            "xml_TimeOut": xml["parameters"].get("TimeOut"),
            "argv_TimeOut": launch.get("TimeOut"),
            "savedt_nodes": xml["savedt_nodes"],
            "actual_output_authority": "receipt launch -tout" if "TimeOut" in launch else ("solver XML TimeOut/special.savedt" if xml["parameters"].get("TimeOut") is not None else "UNKNOWN"),
        },
        "source_evidence": _source_evidence(source_records)[1],
    }, {record["path"]: record for record in source_records}


def _pair(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    same_group = left.get("pair_group") == right.get("pair_group") and left.get("pair_group") is not None
    out: dict[str, Any] = {"left": left["label"], "right": right["label"], "same_pair_group": same_group, "status": "NOT_A_DECLARED_PAIR"}
    if not same_group:
        return out
    if not left["completed"] or not right["completed"]:
        out["status"] = "BLOCKED_TERMINAL_RECEIPT"; return out
    lc, rc = left["receipt_launch_controls"], right["receipt_launch_controls"]
    lx, rx = left["xml_declared_controls"], right["xml_declared_controls"]
    common_launch = {key: lc.get(key) == rc.get(key) for key in ("TimeOut", "TimeMax", "TimeOutExtra", "DtIni", "DtMin", "DtFixed", "CoefDtMin")}
    cfl_left = (lx.get("cflnumber_values") or [None])[0]
    cfl_right = (rx.get("cflnumber_values") or [None])[0]
    out.update({
        "status": "OBSERVED_XML_CFL_ONLY_DIFFERENCE_NO_SCIENTIFIC_Q" if cfl_left is not None and cfl_right is not None and cfl_left != cfl_right and all(common_launch.values()) else "BLOCKED_OTHER_RUNTIME_CONTROLS_OR_CFL_MISSING",
        "left_xml_cfl": cfl_left,
        "right_xml_cfl": cfl_right,
        "left_argv_cfl": lc.get("CFL"),
        "right_argv_cfl": rc.get("CFL"),
        "launch_common_controls": common_launch,
        "output_controls_same": common_launch.get("TimeOut") is True and common_launch.get("TimeMax") is True,
        "field_error": "UNKNOWN",
        "time_integration_error": "UNKNOWN",
        "interpolation": False,
        "neighbor_grid_truth": False,
    })
    return out


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise AuditFailure(f"refusing overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _record({"path": str(manifest_path)}, "F1 CFL entrypoint manifest", "json")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_CFL_ENTRYPOINT_AUDIT_V2":
        raise AuditFailure("manifest schema/status mismatch")
    source_bindings = manifest.get("official_sources")
    entries = manifest.get("entries")
    if not isinstance(source_bindings, list) or not source_bindings or not isinstance(entries, list) or not entries:
        raise AuditFailure("manifest sources/entries missing")
    source_records, _ = _source_evidence(source_bindings)
    loaded = []
    records = {manifest_record["path"]: manifest_record}
    records.update({record["path"]: record for record in source_records})
    for entry in entries:
        item, entry_records = _entry(entry, str(entry.get("label", "entry")), source_records)
        loaded.append(item); records.update(entry_records)
        records[item["request"]["path"]] = item["request"]
        records[item["receipt"]["path"]] = item["receipt"]
        records[item["solver_xml"]["path"]] = item["solver_xml"]
    pairs = [_pair(loaded[i], loaded[j]) for i in range(len(loaded)) for j in range(i + 1, len(loaded))]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "entries": loaded,
        "pairs": pairs,
        "source_authority": {
            "xml_cflnumber": "JCaseCtes::ReadXmlDef reads case constants cflnumber; JCaseCtes::ReadXmlRun reads execution constants used for the actual run",
            "runtime_cfl_override": "JSphCfgRun parses -cfl; JSph::LoadConfig applies cfg override when present",
            "dt_formula": "JSphCpu/JSphGpu::DtVariable multiplies the limiting dt by CFLnumber",
            "output": "JSph::LoadConfigParameters reads TimeOut and configures special savedt independently; JDsOutputTime/JDsSaveDt implement output scheduling",
            "actual_launch_precedence": "receipt.execution.launch_argv, then receipt.command, then request.command fallback",
            "execution_lineage": "source request is authoritative only after exact receipt.request.root_canonical_binding.source_request/source_sha256 (or exact direct request path/SHA) is verified",
        },
        "interpretation": {
            "half_cfl": "proven only by a bound XML cflnumber difference or explicit receipt -cfl; labels alone are not evidence",
            "f1_s2_missing_half_pair": "a new source-bound overlay/request is required before calling F1-S2 a half-CFL comparison",
            "request_lineage": "F1-S2 receipt request may be a root-forward wrapper; it is not a direct source-request SHA join",
            "output_vs_timestep": "-tout/savedt is output cadence; cflnumber/-cfl is timestep coefficient; no field error is inferred",
            "interpolation": False,
            "neighbor_grid_truth": False,
        },
        "next_request": {
            "status": "SOURCE_ONLY_PREPARED_NOT_RUN",
            "scope": "F1-S2 matched-control half-CFL overlay",
            "single_change": "change only case.execution.constants.cflnumber from bound same-CFL value 0.2 to 0.1 (or use an explicit -cfl:0.1 only if the parent request contract chooses the command override); preserve BI4/source geometry and output controls",
            "admission": "parent must bind new overlay XML, source/BI4 identity, actual command and receipt before any solver launch",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "read_scope": {"bounded_json_xml_source_only": True, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "runparts_read": False, "solver_launch": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    _write_once(output, result)
    return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="ds02-f1-cfl-entry-") as directory:
        root = Path(directory)
        source = root / "source.cpp"
        source.write_text("void f(){ SetCFLnumber(0.2); double dt=CFLnumber*dt1; }\n", encoding="utf-8")
        xml_same = root / "same.xml"
        xml_same.write_text("<case><constants><cflnumber value='0.2'/></constants><parameter key='TimeOut' value='0.01'/></case>", encoding="utf-8")
        xml_half = root / "half.xml"
        xml_half.write_text("<case><constants><cflnumber value='0.1'/></constants><parameter key='TimeOut' value='0.01'/></case>", encoding="utf-8")
        def make(name: str, xml: Path, request_argv: list[str], launch_argv: list[str]) -> dict[str, Any]:
            request = root / f"{name}.request.json"; receipt = root / f"{name}.receipt.json"
            request.write_text(json.dumps({"command": request_argv}), encoding="utf-8")
            receipt.write_text(json.dumps({"status": "completed", "request": {"path": str(request), "sha256": hashlib.sha256(request.read_bytes()).hexdigest()}, "execution": {"returncode": 0, "launch_argv": launch_argv}}), encoding="utf-8")
            return {"label": name, "variant": name, "pair_group": "fixture", "request": {"path": str(request)}, "receipt": {"path": str(receipt)}, "xml": {"path": str(xml)}}
        manifest = root / "manifest.json"; output = root / "out.json"
        manifest.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_F1_CFL_ENTRYPOINT_AUDIT_V2", "official_sources": [{"path": str(source)}], "entries": [make("same", xml_same, ["solver", "-tout:0.005"], ["solver", "-tout:0.005"]), make("half", xml_half, ["solver", "-tout:0.005"], ["solver", "-tout:0.005"])]}), encoding="utf-8")
        result = run(manifest, output)
        assert result["pairs"][0]["status"] == "OBSERVED_XML_CFL_ONLY_DIFFERENCE_NO_SCIENTIFIC_Q"
        assert result["entries"][0]["cfl_entry"]["runtime_cfl_override_present"] is False
        bad = root / "bad.xml"; bad.write_text("<case>", encoding="utf-8")
        try: _record({"path": str(bad)}, "bad XML", "xml")
        except AuditFailure: pass
        else: raise AssertionError("malformed XML accepted")
    print("PASS_F1_CFL_ENTRYPOINT_AUDIT_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required unless --self-test")
    try:
        result = run(args.manifest, args.output)
    except Exception as exc:
        print(f"{FAIL_STATUS}: {exc}"); return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute()), "entries": len(result["entries"])}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
