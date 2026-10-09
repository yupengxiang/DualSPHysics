#!/usr/bin/env python3
"""Verify ROOT314 frame-zero worker output without reopening production BI4.

The frame-zero worker is allowed to report a useful position/identity result
when an initial GenCase product has no Vel/Rhop/Mass arrays.  This verifier is
independent of that worker's result construction: it rechecks the small XML
and terminal receipt joins, the native BI4 pre/post SHA/stat boundary, the
decoder-array records, and the explicit UNKNOWN mass semantics.  It preserves
PASS, UNKNOWN, and FAILED rows; a missing F7 physical identity is never filled
from a sentinel label.

The self-test calls the real frame-zero worker ``run`` on a manufactured
four-case decoder fixture and then verifies its JSON output.  No production
BI4, VTK, HDF5, solver output, or ledger is read by this verifier.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER_PATH = HERE / "stage2_four_sentinel_frame0_support_audit_v2.py"
SCHEMA = "ds02.stage2.four-sentinel-frame0-support-audit.v2"
MANIFEST_SCHEMA = "ds02.stage2.four-sentinel-frame0-support-manifest.v2"
RESULT_SCHEMA = "ds02.stage2.four-sentinel-frame0-support-verifier.v2"
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
MAX_JSON_BYTES = 16 * 1024 * 1024
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}


class VerifyFailure(RuntimeError):
    pass


def _load_worker() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_four_sentinel_frame0_worker_v2_verify", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise VerifyFailure(f"cannot import frame-zero worker: {WORKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _normalize_stat(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} is not a stat object")
    aliases = {"device": ("device", "dev", "st_dev"),
               "inode": ("inode", "ino", "st_ino"),
               "bytes": ("bytes",), "mtime_ns": ("mtime_ns",),
               "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    for target, names in aliases.items():
        found = [name for name in names if name in value]
        if len(found) != 1:
            raise VerifyFailure(f"{label} lacks exactly one {target}")
        raw = value[found[0]]
        if isinstance(raw, bool):
            raise VerifyFailure(f"{label}.{target} is boolean")
        try:
            result[target] = int(raw)
        except (TypeError, ValueError) as exc:
            raise VerifyFailure(f"{label}.{target} is not integer") from exc
    return result


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not SHA-256")
    return value.lower()


def _stable_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_JSON_BYTES:
        raise VerifyFailure(f"{label} exceeds bounded JSON cap")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during read")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                   "bytes": len(raw), "stat": after, "stable_read": True}


def _stable_small_bytes(path: Path, label: str, max_bytes: int = MAX_JSON_BYTES) -> tuple[bytes, dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > max_bytes:
        raise VerifyFailure(f"{label} exceeds bounded read")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during read")
    return raw, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                 "bytes": len(raw), "stat": after, "stable_read": True}


def _record(record: Any, label: str, *, json_value: bool = False) -> tuple[Any, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise VerifyFailure(f"{label} record is missing")
    path = _absolute(Path(record["path"]))
    value, observed = _stable_json(path, label) if json_value else _stable_small_bytes(path, label)
    if record.get("sha256") is not None and _digest(record["sha256"], f"{label} declared SHA") != observed["sha256"]:
        raise VerifyFailure(f"{label} declared SHA differs from observed bytes")
    if record.get("bytes") is not None and int(record["bytes"]) != observed["bytes"]:
        raise VerifyFailure(f"{label} declared byte count differs")
    declared = record.get("stat") or record.get("stat_at_build") or record.get("stat_at_prepare")
    if declared is not None and _normalize_stat(declared, f"{label} declared stat") != observed["stat"]:
        raise VerifyFailure(f"{label} declared stat differs from observed stat")
    return value, observed


def _case_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise VerifyFailure("frame-zero manifest schema mismatch")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != len(CASES):
        raise VerifyFailure("frame-zero manifest must contain four cases")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("sentinel_id") not in CASES:
            raise VerifyFailure("frame-zero manifest has an invalid case")
        sid = str(row["sentinel_id"])
        if sid in result:
            raise VerifyFailure(f"duplicate frame-zero case {sid}")
        result[sid] = row
    if set(result) != set(CASES):
        raise VerifyFailure("frame-zero manifest case set is incomplete")
    return result


def _verify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = _case_map(manifest)
    if manifest.get("scientific_qualification", QUALIFICATION).get("credit", 0) != 0:
        raise VerifyFailure("frame-zero manifest advertises scientific credit")
    bindings: dict[str, dict[str, Any]] = {}
    for sid, case in cases.items():
        if not isinstance(case.get("source_xml"), dict) or not isinstance(case.get("receipt"), dict) or not isinstance(case.get("frame0"), dict):
            raise VerifyFailure(f"{sid} manifest source/receipt/frame0 records are incomplete")
        receipt, receipt_record = _record(case["receipt"], f"{sid} terminal receipt", json_value=True)
        if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
            raise VerifyFailure(f"{sid} terminal receipt is not completed rc=0")
        request = receipt.get("request")
        if not isinstance(request, dict):
            raise VerifyFailure(f"{sid} terminal receipt has no nested request")
        output_root = receipt.get("output_root")
        if not isinstance(output_root, str) or _absolute(Path(output_root)) != _absolute(Path(str(case.get("terminal_output_root", "")))):
            raise VerifyFailure(f"{sid} terminal output root is not bound")
        xml_path = _absolute(Path(case["source_xml"]["path"]))
        _, xml_record = _record(case["source_xml"], f"{sid} source XML")
        if xml_path.parent != _absolute(Path(output_root)):
            raise VerifyFailure(f"{sid} source XML is outside terminal output root")
        request_files = request.get("input_files")
        request_hashes = request.get("input_sha256")
        if not isinstance(request_files, list) or str(xml_path) not in request_files:
            raise VerifyFailure(f"{sid} source XML is not in producer request input_files")
        if not isinstance(request_hashes, dict) or request_hashes.get(str(xml_path)) != xml_record["sha256"]:
            raise VerifyFailure(f"{sid} source XML request SHA join is not closed")
        for map_name in ("input_hashes_at_launch", "input_hashes_after_run"):
            hashes = receipt.get(map_name)
            if not isinstance(hashes, dict) or hashes.get(str(xml_path)) != xml_record["sha256"]:
                raise VerifyFailure(f"{sid} source XML {map_name} SHA join is not closed")
        frame = case["frame0"]
        if not isinstance(frame.get("path"), str):
            raise VerifyFailure(f"{sid} frame-0 path missing")
        if frame.get("known_sha256") not in (None, "PARENT_AFTER_RESERVATION_REQUIRED"):
            _digest(frame["known_sha256"], f"{sid} frame-0 known SHA")
        if frame.get("payload_read_by_builder") is not False:
            raise VerifyFailure(f"{sid} frame-0 was read during preparation")
        decoder = case.get("decoder")
        if not isinstance(decoder, dict) or not isinstance(decoder.get("path"), str):
            raise VerifyFailure(f"{sid} decoder binding missing")
        bindings[sid] = {"receipt": receipt_record, "xml": xml_record,
                         "frame_path": str(_absolute(Path(frame["path"]))),
                         "decoder_path": str(_absolute(Path(decoder["path"]))),
                         "request_identity": {key: request.get(key) for key in ("family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id")}}
    return {"cases": cases, "bindings": bindings}


def _verify_native(row: dict[str, Any], case: dict[str, Any], sid: str) -> None:
    native = row.get("native")
    if not isinstance(native, dict):
        raise VerifyFailure(f"{sid} PASS row lacks native guard record")
    expected_path = _absolute(Path(case["frame0"]["path"]))
    if _absolute(Path(str(native.get("path", "")))) != expected_path:
        raise VerifyFailure(f"{sid} native guard path differs from manifest")
    digest = _digest(native.get("sha256"), f"{sid} native post SHA")
    if native.get("post_equal") is not True:
        raise VerifyFailure(f"{sid} native pre/post guard is not equal")
    native_pre = _normalize_stat(native.get("stat_pre"), f"{sid} native pre stat")
    native_post = _normalize_stat(native.get("stat_post"), f"{sid} native post stat")
    if native_pre != native_post:
        raise VerifyFailure(f"{sid} native pre/post stat differs")
    expected_stat = case["frame0"].get("stat") or case["frame0"].get("stat_at_build") or case["frame0"].get("stat_at_prepare")
    if expected_stat is not None and native_pre != _normalize_stat(expected_stat, f"{sid} manifest frame stat"):
        raise VerifyFailure(f"{sid} native pre stat differs from manifest frame stat")
    if native_post["bytes"] != native_pre["bytes"]:
        raise VerifyFailure(f"{sid} native pre/post byte count differs")
    expected_sha = case["frame0"].get("known_sha256")
    if isinstance(expected_sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha) and digest != expected_sha.lower():
        raise VerifyFailure(f"{sid} native SHA differs from manifest known SHA")
    array_records = row.get("decoder_array_records")
    if not isinstance(array_records, dict) or not array_records:
        raise VerifyFailure(f"{sid} decoder array records are missing")
    for name, record in array_records.items():
        if not isinstance(record, dict) or record.get("stable") is not True:
            raise VerifyFailure(f"{sid} decoder {name} record is not stable")
        _digest(record.get("sha256"), f"{sid} decoder {name} SHA")
        _normalize_stat(record.get("stat_pre"), f"{sid} decoder {name} pre stat")
        _normalize_stat(record.get("stat_post"), f"{sid} decoder {name} post stat")
        if _normalize_stat(record["stat_pre"], f"{sid} decoder {name} pre stat") != _normalize_stat(record["stat_post"], f"{sid} decoder {name} post stat"):
            raise VerifyFailure(f"{sid} decoder {name} pre/post stat differs")


def _verify_fields(row: dict[str, Any], sid: str) -> None:
    qualification = row.get("qualification", QUALIFICATION)
    if not isinstance(qualification, dict) or qualification.get("credit", 0) != 0:
        raise VerifyFailure(f"{sid} row advertises scientific credit")
    presence = row.get("field_presence")
    finite = row.get("finite_fields")
    if not isinstance(presence, dict) or not isinstance(finite, dict):
        raise VerifyFailure(f"{sid} field presence/finite diagnostics missing")
    if presence.get("Idp") is not True and presence.get("Idpd") is not True:
        raise VerifyFailure(f"{sid} identity field is absent")
    if presence.get("Pos") is not True and presence.get("Posd") is not True:
        raise VerifyFailure(f"{sid} position field is absent")
    if finite.get("position") is not True or finite.get("ids_unique") is not True:
        raise VerifyFailure(f"{sid} required finite position/identity check failed")
    sample = row.get("sample_mass")
    if not isinstance(sample, dict):
        raise VerifyFailure(f"{sid} sample mass semantics missing")
    if presence.get("Mass") is not True:
        if sample.get("native_mass_array") != "UNKNOWN_MISSING_MASS_ARRAY" or sample.get("native_fluid_mass_sum_kg") is not None:
            raise VerifyFailure(f"{sid} missing native Mass was converted into a value")
    else:
        if sample.get("native_mass_array") != "PASS" or not isinstance(sample.get("native_fluid_mass_sum_kg"), (int, float)):
            raise VerifyFailure(f"{sid} present native Mass lacks a finite sample result")
    if sample.get("source_constant_is_not_native_mass") is not True or sample.get("continuous_owner_mass") != "UNKNOWN_NOT_DERIVED":
        raise VerifyFailure(f"{sid} mass separation semantics are incomplete")
    identity = row.get("receipt_identity")
    if not isinstance(identity, dict):
        raise VerifyFailure(f"{sid} receipt identity result missing")
    missing = identity.get("missing_fields", [])
    if not isinstance(missing, list):
        raise VerifyFailure(f"{sid} receipt identity missing-fields record malformed")
    # A partial identity is retained as partial.  In particular, F7-S1 is
    # never made complete by copying the sentinel label into physical_case_id.
    if sid == "F7-S1" and "physical_case_id" in missing and identity.get("status") == "PASS_CASE_ATTEMPT_PHYSICAL":
        raise VerifyFailure("F7-S1 missing physical identity was promoted")


def _verify_output(manifest_summary: dict[str, Any], output: dict[str, Any]) -> dict[str, int]:
    if output.get("schema") != SCHEMA:
        raise VerifyFailure("frame-zero worker output schema mismatch")
    rows = output.get("cases")
    if not isinstance(rows, list) or len(rows) != len(CASES):
        raise VerifyFailure("frame-zero worker output must contain four rows")
    by_sid: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("sentinel_id") not in CASES:
            raise VerifyFailure("frame-zero output has invalid sentinel identity")
        sid = str(row["sentinel_id"])
        if sid in by_sid:
            raise VerifyFailure(f"duplicate frame-zero output row {sid}")
        by_sid[sid] = row
    if set(by_sid) != set(CASES):
        raise VerifyFailure("frame-zero output case set is incomplete")
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    for sid, row in by_sid.items():
        status = str(row.get("status", ""))
        if status.startswith("PASS_FRAME0_POSITION_IDENTITY"):
            counts["PASS"] += 1
            case = manifest_summary["cases"][sid]
            receipt, _ = _record(case["receipt"], f"{sid} terminal receipt", json_value=True)
            xml_payload, _ = _record(case["source_xml"], f"{sid} source XML")
            if row.get("source_xml", {}).get("sha256") != hashlib.sha256(xml_payload).hexdigest():
                raise VerifyFailure(f"{sid} output source XML SHA is not actual")
            join = row.get("source_xml_receipt_join")
            if not isinstance(join, dict) or join.get("path") != str(_absolute(Path(case["source_xml"]["path"]))) or join.get("sha256") != row["source_xml"]["sha256"]:
                raise VerifyFailure(f"{sid} output source XML/receipt join is incomplete")
            request = receipt.get("request", {})
            if request.get("input_sha256", {}).get(join["path"]) != join["sha256"]:
                raise VerifyFailure(f"{sid} receipt request XML SHA is not joined in output")
            _verify_native(row, case, sid)
            _verify_fields(row, sid)
        elif status.startswith("UNKNOWN"):
            counts["UNKNOWN"] += 1
            if row.get("qualification", QUALIFICATION).get("credit", 0) != 0:
                raise VerifyFailure(f"{sid} UNKNOWN row advertises credit")
        elif status.startswith("FAILED"):
            counts["FAILED"] += 1
            if row.get("qualification", QUALIFICATION).get("credit", 0) != 0:
                raise VerifyFailure(f"{sid} FAILED row advertises credit")
        else:
            raise VerifyFailure(f"{sid} has unclassified status {status!r}")
    declared = output.get("case_counts")
    expected = {"PASS": counts["PASS"], "FAILED": counts["FAILED"]}
    if isinstance(declared, dict):
        for name, value in expected.items():
            if int(declared.get(name, -1)) != value:
                raise VerifyFailure(f"frame-zero {name} count is wrong")
    else:
        raise VerifyFailure("frame-zero output case_counts missing")
    if output.get("scientific_qualification", QUALIFICATION).get("credit", 0) != 0:
        raise VerifyFailure("frame-zero output advertises scientific credit")
    return counts


def verify(manifest_path: Path, output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = _stable_json(manifest_path, "frame-zero manifest")
    summary = _verify_manifest(manifest)
    output, output_record = _stable_json(output_path, "frame-zero worker output")
    counts = _verify_output(summary, output)
    result = {"schema": RESULT_SCHEMA, "status": "VERIFIED_ROOT314_FRAME0_WORKER_OUTPUT_V2",
              "manifest": manifest_record, "worker_output": output_record,
              "case_counts": counts, "scientific_qualification": QUALIFICATION,
              "read_scope": {"manifest_receipt_xml_json_only": True, "native_payload_reopened": False,
                             "vtk_read": False, "hdf5_read": False, "solver_launch": False,
                             "f7_identity_fallback": False}}
    if verification_output is not None:
        path = _absolute(verification_output)
        if path.exists() or path.is_symlink():
            raise VerifyFailure(f"refusing overwrite: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _write_fixture_decoder(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, struct, sys\n"
        "frame=pathlib.Path(sys.argv[1]); prefix=pathlib.Path(sys.argv[2]); data=prefix/'particles'; data.mkdir(parents=True, exist_ok=True)\n"
        "(prefix.with_suffix('.xml')).write_text('<root><item><double name=\"Npiece\" v=\"1\"/><double name=\"Piece\" v=\"0\"/><double name=\"NpDynamic\" v=\"0\"/><double name=\"ReuseIds\" v=\"0\"/><double name=\"PeriMode\" v=\"0\"/><item name=\"particles\"><double name=\"TimeStep\" v=\"0\"/></item></item></root>')\n"
        "data.joinpath('Idp.bin').write_bytes(struct.pack('<4I',0,1,2,3))\n"
        "data.joinpath('Posd.bin').write_bytes(struct.pack('<12d',0.1,0.1,0.1,0.25,0.25,0.25,0.75,0.75,0.75,0.5,0.5,1.0))\n"
        "if not frame.is_file(): raise SystemExit(3)\n", encoding="utf-8")
    path.chmod(0o755)


def _fixture_xml() -> str:
    return """<case><execution><particles><fixed begin=\"0\" count=\"1\" mk=\"10\"/><fluid begin=\"1\" count=\"2\" mkfluid=\"0\" mk=\"1\"/><floating begin=\"3\" count=\"1\" mk=\"50\"/></particles><constants><rhop0 value=\"1000\"/><massfluid value=\"0.125\"/></constants></execution></case>"""


def _fixture_record(path: Path, *, read: bool = True) -> dict[str, Any]:
    value = path.read_bytes() if read else b""
    stat = _stat(path)
    return {"path": str(path.absolute()), "sha256": hashlib.sha256(value).hexdigest() if read else None,
            "bytes": stat["bytes"], "stat": {"dev": stat["device"], "ino": stat["inode"], "bytes": stat["bytes"], "mtime_ns": stat["mtime_ns"], "ctime_ns": stat["ctime_ns"]},
            "payload_read_by_builder": read}


def _fixture_manifest(root: Path) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    decoder = root / "fixture-bi4-dump.py"; _write_fixture_decoder(decoder)
    observer_source = HERE / "stage2_native_physical_observer_v2.py"
    cases: list[dict[str, Any]] = []
    for index, sid in enumerate(CASES):
        case_root = root / sid; case_root.mkdir()
        xml = case_root / "generated.xml"; xml.write_text(_fixture_xml(), encoding="utf-8")
        native = case_root / "solver_output" / "data" / "Part_0000.bi4"; native.parent.mkdir(parents=True); native.write_bytes(f"tiny-frame-{sid}".encode())
        physical = None if sid == "F7-S1" else f"physical-{sid}"
        request = {"family_id": "DS02-MULTI", "sentinel_id": sid, "physical_case_id": physical, "case_id": f"case-{sid}", "attempt_id": f"attempt-{sid}", "input_files": [str(xml.absolute())], "input_sha256": {str(xml.absolute()): hashlib.sha256(xml.read_bytes()).hexdigest()}}
        receipt = {"status": "completed", "returncode": 0, "output_root": str(case_root.absolute()), "request": request,
                   "input_hashes_at_launch": dict(request["input_sha256"]), "input_hashes_after_run": dict(request["input_sha256"])}
        receipt_path = case_root / "execution-receipt.json"; receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        frame_record = _fixture_record(native, read=False); frame_record["known_sha256"] = hashlib.sha256(native.read_bytes()).hexdigest(); frame_record["payload_read_by_builder"] = False
        cases.append({"sentinel_id": sid, "family_id": "DS02-MULTI", "physical_case_id": physical, "case_id": request["case_id"], "attempt_id": request["attempt_id"],
                      "receipt_identity_expected": {"family_id": "DS02-MULTI", "sentinel_id": sid, "physical_case_id": physical, "case_id": request["case_id"], "attempt_id": request["attempt_id"]},
                      "source_xml": _fixture_record(xml), "receipt": _fixture_record(receipt_path), "terminal_output_root": str(case_root.absolute()),
                      "frame0": frame_record, "decoder": {"path": str(decoder.absolute())}, "decoder_source": {"path": str(observer_source.absolute())}})
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_PARENT_FRAME0_SUPPORT_GUARD_REQUIRED", "cases": cases, "scientific_qualification": QUALIFICATION}
    manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, root / "attempt", root / "output.json"


def self_test() -> None:
    worker = _load_worker()
    with tempfile.TemporaryDirectory(prefix="root314-frame0-verifier-") as directory:
        root = Path(directory); manifest, attempt, output = _fixture_manifest(root)
        worker.run(manifest, attempt, output)
        result = verify(manifest, output)
        assert result["case_counts"] == {"PASS": 4, "UNKNOWN": 0, "FAILED": 0}
        value = json.loads(output.read_text())
        assert value["cases"][-1]["receipt_identity"]["status"] == "PARTIAL_SENTINEL_FIELD_ABSENT"
        assert all(row["sample_mass"]["native_mass_array"] == "UNKNOWN_MISSING_MASS_ARRAY" for row in value["cases"])
        mixed = copy.deepcopy(value)
        mixed["cases"][0]["status"] = "UNKNOWN_POSITION_ONLY_FIELDS"
        mixed["cases"][1]["status"] = "FAILED_FRAME0_POSITION_IDENTITY_DIAGNOSTIC"
        mixed["cases"][1]["reason"] = "manufactured failure"
        mixed["case_counts"] = {"PASS": 2, "FAILED": 1}
        mixed_path = root / "mixed.json"; mixed_path.write_text(json.dumps(mixed), encoding="utf-8")
        mixed_result = verify(manifest, mixed_path)
        assert mixed_result["case_counts"] == {"PASS": 2, "UNKNOWN": 1, "FAILED": 1}
        broken = copy.deepcopy(value)
        broken["cases"][0]["native"]["stat_post"]["device"] += 1
        broken_path = root / "broken.json"; broken_path.write_text(json.dumps(broken), encoding="utf-8")
        try:
            verify(manifest, broken_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("native pre/post stat mutation was accepted")
    print("PASS_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V2_E2E_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V2_SELFTEST: {exc}", file=sys.stderr); return 2
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--verify requires --manifest and --output")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V2: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "case_counts": result["case_counts"], "scientific_credit": 0}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
