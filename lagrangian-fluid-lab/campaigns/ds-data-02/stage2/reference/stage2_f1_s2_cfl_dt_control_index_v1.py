#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Index F1-S2 CFL, timestep, and output-control provenance.

This is a bounded metadata consumer.  It reads request/receipt JSON and
generated XML only; it does not open BI4, native Part files, RunPARTs, H5 or
VTK and never infers a runtime setting from a case label.  A receipt launch
argv is authoritative when present.  XML values are reported as declarations
and are marked unproven when the actual launch argv does not expose them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f1-s2.cfl-dt-control-index.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.cfl-dt-control-manifest.v1"
PASS_STATUS = "COMPLETE_F1_S2_CONTROL_PROVENANCE_INDEX_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F1_S2_CONTROL_PROVENANCE_INDEX"
MAX_JSON = 4 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024
CONTROL_KEYS = ("cfl", "coefdtmin", "dtini", "dtmin", "dtfixed", "dtallparticles", "tout", "tmax", "timout", "timemax")


class IndexFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _read_bytes(path: Path, label: str, limit: int) -> tuple[bytes, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise IndexFailure(f"{label} is not a regular file")
    before = _stat(path)
    if before["bytes"] > limit:
        raise IndexFailure(f"{label} exceeds bounded limit: {before['bytes']}")
    digest = hashlib.sha256(); chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk); chunks.append(chunk)
    after = _stat(path)
    if before != after:
        raise IndexFailure(f"{label} changed while being read")
    return b"".join(chunks), {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"], "stat": after, "stable_read": True}


def _read_json(record: Any, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise IndexFailure(f"{label} record missing")
    raw, actual = _read_bytes(Path(record["path"]), label, MAX_JSON)
    if record.get("sha256") and str(record["sha256"]).lower() != actual["sha256"]:
        raise IndexFailure(f"{label} SHA differs from binding")
    if record.get("bytes") is not None and int(record["bytes"]) != actual["bytes"]:
        raise IndexFailure(f"{label} byte count differs from binding")
    try: value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise IndexFailure(f"{label} is not JSON") from exc
    if not isinstance(value, dict): raise IndexFailure(f"{label} is not an object")
    return value, actual


def _read_xml(record: Any, label: str) -> tuple[ET.Element, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise IndexFailure(f"{label} record missing")
    raw, actual = _read_bytes(Path(record["path"]), label, MAX_XML)
    if record.get("sha256") and str(record["sha256"]).lower() != actual["sha256"]:
        raise IndexFailure(f"{label} SHA differs from binding")
    try: root = ET.fromstring(raw)
    except ET.ParseError as exc: raise IndexFailure(f"{label} XML parse failed") from exc
    return root, actual


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError): return None
    return result if math.isfinite(result) else None


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _xml_controls(root: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "parameter": continue
        name = node.get("key") or node.get("name")
        value = node.get("value")
        if not name or value is None: continue
        k = _key(name)
        if k in CONTROL_KEYS or k in {"cflnumber", "cfl"}:
            result[name] = value
    return result


def _argv(request: dict[str, Any], receipt: dict[str, Any]) -> list[str]:
    execution = receipt.get("execution") if isinstance(receipt.get("execution"), dict) else {}
    value = execution.get("launch_argv") or receipt.get("launch_argv")
    if not isinstance(value, list):
        value = request.get("command")
    return [str(x) for x in value] if isinstance(value, list) else []


def _argv_controls(argv: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    aliases = {"cfl": "CFL", "cflnumber": "CFL", "coefdtmin": "CoefDtMin", "dtini": "DtIni", "dtmin": "DtMin", "dtfixed": "DtFixed", "dtallparticles": "DtAllParticles", "tout": "TimeOut", "tmax": "TimeMax", "timemax": "TimeMax"}
    i = 0
    while i < len(argv):
        token = argv[i]
        body = token.lstrip("-")
        name, sep, value = re.split(r"[:=]", body, maxsplit=1)[0], (":" if ":" in body else ("=" if "=" in body else "")), (re.split(r"[:=]", body, maxsplit=1)[1] if re.search(r"[:=]", body) else None)
        normalized = _key(name)
        if normalized in aliases:
            if value is None and i + 1 < len(argv) and not str(argv[i + 1]).startswith("-"):
                value = argv[i + 1]; i += 1
            parsed = _num(value)
            result[aliases[normalized]] = {"raw": value, "value": parsed, "token": token}
        i += 1
    return result


def _runtime_status(receipt: dict[str, Any]) -> dict[str, Any]:
    execution = receipt.get("execution") if isinstance(receipt.get("execution"), dict) else {}
    rc = execution.get("returncode", receipt.get("returncode"))
    status = receipt.get("status")
    return {"receipt_status": status, "returncode": rc, "completed": str(status or "").lower().startswith(("complete", "success")) and rc in {None, 0}}


def _entry(entry: dict[str, Any], label: str) -> dict[str, Any]:
    request, request_rec = _read_json(entry.get("request"), f"{label} request")
    receipt, receipt_rec = _read_json(entry.get("receipt"), f"{label} receipt")
    root, xml_rec = _read_xml(entry.get("xml"), f"{label} XML")
    receipt_request = receipt.get("request")
    if isinstance(receipt_request, dict):
        if receipt_request.get("path") and Path(receipt_request["path"]).expanduser().absolute() != Path(request_rec["path"]):
            raise IndexFailure(f"{label} receipt/request path mismatch")
        if receipt_request.get("sha256") and str(receipt_request["sha256"]).lower() != request_rec["sha256"]:
            raise IndexFailure(f"{label} receipt/request SHA mismatch")
    xml = _xml_controls(root); argv = _argv(request, receipt); runtime = _argv_controls(argv)
    source = entry.get("source_group", entry.get("grid"))
    return {"label": label, "grid": entry.get("grid"), "variant": entry.get("variant"), "evidence_role": entry.get("evidence_role"), "source_group": source, "request": request_rec, "receipt": receipt_rec, "xml": xml_rec, "xml_declared_controls": xml, "request_command_controls": _argv_controls([str(x) for x in request.get("command", [])]) if isinstance(request.get("command"), list) else {}, "receipt_launch_argv": argv, "receipt_launch_controls": runtime, "runtime": _runtime_status(receipt), "control_authority": "receipt.execution.launch_argv" if isinstance(receipt.get("execution", {}).get("launch_argv") if isinstance(receipt.get("execution"), dict) else None, list) else "request.command_fallback", "source_identity": entry.get("source_identity", "UNKNOWN_NOT_ASSERTED"), "case_id": request.get("case_id") or request.get("physical_case_id")}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, dict) and isinstance(b, dict): return a.get("value") == b.get("value") and a.get("value") is not None
    return a == b


def _pair(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    same_source = a.get("source_group") == b.get("source_group") and a.get("grid") == b.get("grid")
    out = {"left": a["label"], "right": b["label"], "same_grid_and_source": same_source, "output_cadence_isolation": {"status": "BLOCKED_NOT_SAME_GRID_OR_SOURCE"}, "time_step_isolation": {"status": "BLOCKED_NOT_SAME_GRID_OR_SOURCE"}}
    if not same_source: return out
    la, lb = a["receipt_launch_controls"], b["receipt_launch_controls"]
    if not a["runtime"]["completed"] or not b["runtime"]["completed"]:
        out["output_cadence_isolation"] = {"status": "BLOCKED_RECEIPT_NOT_COMPLETED"}; out["time_step_isolation"] = {"status": "BLOCKED_RECEIPT_NOT_COMPLETED"}; return out
    compared = ["CFL", "CoefDtMin", "DtIni", "DtMin", "DtFixed", "DtAllParticles", "TimeMax"]
    same_dt = all(_same(la.get(k), lb.get(k)) for k in compared)
    tout_a, tout_b = la.get("TimeOut"), lb.get("TimeOut")
    if not la.get("TimeOut") or not lb.get("TimeOut"):
        out["output_cadence_isolation"] = {"status": "BLOCKED_RUNTIME_CONTROL_UNPROVEN", "reason": "receipt launch argv has no explicit tout"}
    elif same_dt and not _same(tout_a, tout_b):
        out["output_cadence_isolation"] = {"status": "OBSERVED_RUNTIME_OUTPUT_ONLY_DIFFERENCE", "left_tout": tout_a, "right_tout": tout_b, "field_error": "UNKNOWN"}
    else:
        out["output_cadence_isolation"] = {"status": "BLOCKED_OTHER_RUNTIME_CONTROLS_DIFFER_OR_ARE_MISSING"}
    cfl_keys = ["CFL", "CoefDtMin", "DtIni", "DtMin", "DtFixed", "DtAllParticles"]
    dt_diff = any(la.get(k) and lb.get(k) and not _same(la.get(k), lb.get(k)) for k in cfl_keys)
    if dt_diff and _same(tout_a, tout_b):
        out["time_step_isolation"] = {"status": "OBSERVED_RUNTIME_TIMESTEP_ONLY_DIFFERENCE", "left": {k: la.get(k) for k in cfl_keys}, "right": {k: lb.get(k) for k in cfl_keys}, "field_error": "UNKNOWN"}
    else:
        out["time_step_isolation"] = {"status": "BLOCKED_EXPLICIT_DT_CONTROL_MISSING_OR_OTHER_CONTROL_DIFFERS"}
    return out


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink(): raise IndexFailure(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try: tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"); os.replace(tmp, path)
    finally: tmp.unlink(missing_ok=True)


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_rec = _read_json({"path": str(manifest_path)}, "F1-S2 control manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_S2_CONTROL_INDEX": raise IndexFailure("manifest schema/status mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries: raise IndexFailure("manifest entries missing")
    loaded = [_entry(item, str(item.get("label", f"entry{idx}"))) for idx, item in enumerate(entries)]
    pairs = [_pair(loaded[i], loaded[j]) for i in range(len(loaded)) for j in range(i + 1, len(loaded))]
    result = {"schema": SCHEMA, "status": PASS_STATUS, "manifest": manifest_rec, "entries": loaded, "pairs": pairs, "evidence_index": [{"label": e["label"], "evidence_role": e.get("evidence_role"), "status": e["runtime"]} for e in loaded], "semantics": {"receipt_launch_argv_authority": True, "xml_is_declaration": True, "labels_are_not_evidence": True, "interpolation": False, "neighbor_grid_truth": False, "time_integration_error": "UNKNOWN", "output_error": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "read_scope": {"bounded_json_and_xml_only": True, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "runparts_read": False, "solver_launch": False}}
    _write_once(output, result); return result


def _self_test() -> None:
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        p = Path(d); xml = p / "case.xml"; xml.write_text('<case><parameter key="CoefDtMin" value="0.05"/><parameter key="TimeOut" value="0.01"/></case>')
        def make(label: str, tout: str) -> dict[str, Any]:
            req = p / f"{label}.request.json"; rec = p / f"{label}.receipt.json"
            req.write_text(json.dumps({"command": ["solver", "-coefdtmin:0.05", f"-tout:{tout}"], "case_id": "x"}))
            rec.write_text(json.dumps({"status": "completed", "request": {"path": str(req), "sha256": hashlib.sha256(req.read_bytes()).hexdigest()}, "execution": {"returncode": 0, "launch_argv": ["solver", "-coefdtmin:0.05", f"-tout:{tout}"]}}))
            return {"label": label, "grid": "g", "source_group": "s", "variant": label, "evidence_role": label, "request": {"path": str(req)}, "receipt": {"path": str(rec)}, "xml": {"path": str(xml)}}
        a, b = _entry(make("same", "0.01"), "same"), _entry(make("half_output", "0.005"), "half_output")
        assert _pair(a, b)["output_cadence_isolation"]["status"] == "OBSERVED_RUNTIME_OUTPUT_ONLY_DIFFERENCE"
        bad = make("bad", "0.01"); bad["variant"] = "half_cfl"; bad["request"]["path"] = str(p / "missing.json")
        try: _entry(bad, "bad")
        except IndexFailure: pass
        else: raise AssertionError("missing request was accepted")
    print("PASS_F1_S2_CFL_DT_CONTROL_INDEX_V1_SELFTEST")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--manifest", type=Path); p.add_argument("--output", type=Path); p.add_argument("--self-test", action="store_true"); args = p.parse_args()
    if args.self_test: _self_test(); return 0
    if args.manifest is None or args.output is None: p.error("--manifest and --output are required unless --self-test")
    try: result = run(args.manifest, args.output)
    except Exception as exc: print(f"{FAIL_STATUS}: {exc}"); return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute())}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
