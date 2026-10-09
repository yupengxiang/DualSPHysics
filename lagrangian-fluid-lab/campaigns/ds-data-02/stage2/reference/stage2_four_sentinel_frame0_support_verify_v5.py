#!/usr/bin/env python3
"""ROOT314 V5 verifier with an exact producer-input bridge for external XML.

ROOT314 V4 required source_xml.parent == receipt.output_root.  That is too
strong for a generated XML that is a legitimate producer input staged outside
the terminal output tree.  This additive verifier permits the external path
only when the exact absolute path and bytes are present in the nested producer
request input_files/input_sha256 and in both receipt input hash maps.  No
label, basename, output-root relation, or fallback path can satisfy the join.

The V4 native/stat/decoder checks remain in force.  This module is metadata
only and never opens BI4/VTK/HDF5 payloads.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
V4_PATH = HERE / "stage2_four_sentinel_frame0_support_verify_v4.py"
V4_SPEC = importlib.util.spec_from_file_location("stage2_root314_verify_v4_for_v5", V4_PATH)
if V4_SPEC is None or V4_SPEC.loader is None:
    raise RuntimeError(f"cannot load ROOT314 V4: {V4_PATH}")
V4 = importlib.util.module_from_spec(V4_SPEC)
V4_SPEC.loader.exec_module(V4)
V2 = V4.V2

SCHEMA = "ds02.stage2.four-sentinel.frame0-support-verifier.v5"
CASES = V2.CASES
EXTERNAL_XML_BRIDGE = "EXACT_RECEIPT_REQUEST_AND_LAUNCH_AFTER_RUN_INPUT_SHA_BRIDGE"
QUALIFICATION = V2.QUALIFICATION
UNKNOWN_SHA_MARKERS = V4.UNKNOWN_SHA_MARKERS


class VerifyFailure(RuntimeError):
    pass


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not a concrete SHA-256 digest")
    return value.lower()


def _bridge_source_xml(case: dict[str, Any], receipt: dict[str, Any],
                       xml_record: dict[str, Any], sid: str) -> dict[str, Any]:
    """Require exact producer input path and three SHA records for external XML."""
    source = case.get("source_xml")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise VerifyFailure(f"{sid} source XML record is missing")
    xml_path = str(Path(source["path"]).expanduser().absolute())
    observed_sha = xml_record["sha256"]
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise VerifyFailure(f"{sid} receipt has no nested request")
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(files, list) or xml_path not in {str(Path(x).expanduser().absolute()) for x in files if isinstance(x, str)}:
        raise VerifyFailure(f"{sid} source XML is not an exact nested request input")
    if not isinstance(hashes, dict):
        raise VerifyFailure(f"{sid} nested request input_sha256 is missing")
    request_matches = [(str(Path(k).expanduser().absolute()), v) for k, v in hashes.items() if isinstance(k, str)]
    exact = [v for k, v in request_matches if k == xml_path]
    if len(exact) != 1 or _digest(exact[0], f"{sid} nested request source XML SHA") != observed_sha:
        raise VerifyFailure(f"{sid} nested request source XML SHA bridge failed")
    checked_maps = {}
    for map_name in ("input_hashes_at_launch", "input_hashes_after_run"):
        values = receipt.get(map_name)
        if not isinstance(values, dict):
            raise VerifyFailure(f"{sid} receipt {map_name} is missing")
        mapped = [v for k, v in values.items() if isinstance(k, str) and str(Path(k).expanduser().absolute()) == xml_path]
        if len(mapped) != 1 or _digest(mapped[0], f"{sid} receipt {map_name} source XML SHA") != observed_sha:
            raise VerifyFailure(f"{sid} receipt {map_name} source XML SHA bridge failed")
        checked_maps[map_name] = observed_sha
    return {"status": "PASS_EXTERNAL_SOURCE_XML_INPUT_BRIDGE",
            "path": xml_path, "sha256": observed_sha,
            "request_input_files_exact": True, "request_sha256": observed_sha,
            "receipt_hashes_at_launch": checked_maps["input_hashes_at_launch"],
            "receipt_hashes_after_run": checked_maps["input_hashes_after_run"],
            "output_root_relation": "NOT_REQUIRED_WHEN_EXACT_INPUT_BRIDGE_CLOSED",
            "arbitrary_external_xml_fallback": False}


def _verify_manifest_v5(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = V2._case_map(manifest)
    qualification = manifest.get("scientific_qualification", QUALIFICATION)
    if not isinstance(qualification, dict) or qualification.get("credit", 0) != 0:
        raise VerifyFailure("frame-zero manifest advertises scientific credit")
    bindings: dict[str, dict[str, Any]] = {}
    for sid, case in cases.items():
        if not all(isinstance(case.get(name), dict) for name in ("source_xml", "receipt", "frame0")):
            raise VerifyFailure(f"{sid} manifest source/receipt/frame0 records are incomplete")
        receipt, receipt_record = V2._record(case["receipt"], f"{sid} terminal receipt", json_value=True)
        if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
            raise VerifyFailure(f"{sid} terminal receipt is not completed rc=0")
        request = receipt.get("request")
        if not isinstance(request, dict):
            raise VerifyFailure(f"{sid} terminal receipt has no nested request")
        output_root = receipt.get("output_root")
        if not isinstance(output_root, str) or V2._absolute(Path(output_root)) != V2._absolute(Path(str(case.get("terminal_output_root", "")))):
            raise VerifyFailure(f"{sid} terminal output root is not bound")
        xml_path = V2._absolute(Path(case["source_xml"]["path"]))
        _, xml_record = V2._record(case["source_xml"], f"{sid} source XML")
        bridge = _bridge_source_xml(case, receipt, xml_record, sid)
        frame = case["frame0"]
        if not isinstance(frame.get("path"), str):
            raise VerifyFailure(f"{sid} frame-0 path missing")
        if frame.get("known_sha256") not in UNKNOWN_SHA_MARKERS:
            _digest(frame["known_sha256"], f"{sid} frame-0 known SHA")
        if frame.get("payload_read_by_builder") is not False:
            raise VerifyFailure(f"{sid} frame-0 was read during preparation")
        decoder = case.get("decoder")
        if not isinstance(decoder, dict) or not isinstance(decoder.get("path"), str):
            raise VerifyFailure(f"{sid} decoder binding missing")
        bindings[sid] = {
            "receipt": receipt_record, "xml": xml_record,
            "source_xml_bridge": bridge,
            "frame_path": str(V2._absolute(Path(frame["path"]))),
            "decoder_path": str(V2._absolute(Path(decoder["path"]))),
            "request_identity": {key: request.get(key) for key in ("family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id")},
        }
    return {"cases": cases, "bindings": bindings,
            "source_xml_bridge_policy": EXTERNAL_XML_BRIDGE}


def verify_manifest_only(manifest_path: Path) -> dict[str, Any]:
    manifest, manifest_record = V2._stable_json(manifest_path, "ROOT314 V5 frame-zero manifest")
    summary = _verify_manifest_v5(manifest)
    return {"schema": SCHEMA, "status": "VERIFIED_ROOT314_MANIFEST_SOURCE_XML_INPUT_BRIDGE_V5",
            "manifest": manifest_record, "case_count": len(summary["cases"]),
            "source_xml_bridges": {sid: value["source_xml_bridge"] for sid, value in summary["bindings"].items()},
            "scientific_qualification": QUALIFICATION,
            "read_scope": {"manifest_receipt_xml_json_stat_only": True, "native_payload_reopened": False,
                           "vtk_read": False, "hdf5_read": False, "solver_launch": False}}


def verify(manifest_path: Path, output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = V2._stable_json(manifest_path, "ROOT314 V5 frame-zero manifest")
    summary = _verify_manifest_v5(manifest)
    output, output_record = V2._stable_json(output_path, "ROOT314 V5 frame-zero worker output")
    counts, output_unknown = V4._strict_output(summary, output, manifest)
    result = {"schema": SCHEMA, "status": "VERIFIED_ROOT314_FRAME0_WORKER_OUTPUT_V5_EXTERNAL_XML_BRIDGE",
              "manifest": manifest_record, "worker_output": output_record, "case_counts": counts,
              "sourceSHA_basis": V4.FIRST_ESTABLISHED if output_unknown else V4.HISTORICALLY_PREBOUND,
              "source_xml_bridge_policy": EXTERNAL_XML_BRIDGE,
              "source_xml_bridges": {sid: value["source_xml_bridge"] for sid, value in summary["bindings"].items()},
              "scientific_qualification": QUALIFICATION,
              "read_scope": {"manifest_receipt_xml_json_only": True, "native_payload_reopened": False,
                             "vtk_read": False, "hdf5_read": False, "solver_launch": False,
                             "f7_identity_fallback": False}}
    if verification_output is not None:
        V2._write_once(verification_output, result)
    return result


def _move_xml_outside(manifest_path: Path, root: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    external = root / "external-source-inputs"
    external.mkdir()
    for case in manifest["cases"]:
        old = Path(case["source_xml"]["path"])
        new = external / f"{case['sentinel_id']}.xml"
        new.write_bytes(old.read_bytes())
        digest = hashlib.sha256(new.read_bytes()).hexdigest()
        case_root = Path(case["terminal_output_root"])
        receipt_path = Path(case["receipt"]["path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        request = receipt["request"]
        old_abs = str(old.absolute())
        new_abs = str(new.absolute())
        request["input_files"] = [new_abs if str(Path(x).absolute()) == old_abs else x for x in request["input_files"]]
        request["input_sha256"] = {new_abs if str(Path(k).absolute()) == old_abs else k: (digest if str(Path(k).absolute()) == old_abs else v) for k, v in request["input_sha256"].items()}
        receipt["input_hashes_at_launch"] = dict(request["input_sha256"])
        receipt["input_hashes_after_run"] = dict(request["input_sha256"])
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        case["source_xml"] = V2._fixture_record(new)
        case["receipt"] = V2._fixture_record(receipt_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def self_test() -> None:
    worker = V2._load_worker()
    with tempfile.TemporaryDirectory(prefix="root314-frame0-v5-") as directory:
        root = Path(directory)
        manifest, attempt, output = V2._fixture_manifest(root)
        _move_xml_outside(manifest, root)
        worker.run(manifest, attempt, output)
        only = verify_manifest_only(manifest)
        assert only["status"] == "VERIFIED_ROOT314_MANIFEST_SOURCE_XML_INPUT_BRIDGE_V5"
        result = verify(manifest, output)
        assert result["case_counts"] == {"PASS": 4, "UNKNOWN": 0, "FAILED": 0}
        broken = json.loads(manifest.read_text(encoding="utf-8"))
        first = broken["cases"][0]
        receipt = json.loads(Path(first["receipt"]["path"]).read_text(encoding="utf-8"))
        xml_path = str(Path(first["source_xml"]["path"]).absolute())
        receipt["request"]["input_sha256"][xml_path] = "0" * 64
        bad_receipt = Path(first["receipt"]["path"]).with_name("bad-receipt.json")
        bad_receipt.write_text(json.dumps(receipt), encoding="utf-8")
        first["receipt"] = V2._fixture_record(bad_receipt)
        bad_manifest = root / "bad-manifest.json"
        bad_manifest.write_text(json.dumps(broken), encoding="utf-8")
        try:
            verify_manifest_only(bad_manifest)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("request SHA mismatch was accepted")
    print("PASS_ROOT314_FRAME0_SUPPORT_VERIFIER_V5_EXTERNAL_XML_BRIDGE_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--verify-manifest", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_ROOT314_FRAME0_SUPPORT_VERIFIER_V5_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None:
        parser.error("--verify/--verify-manifest requires --manifest")
    try:
        if args.verify_manifest:
            result = verify_manifest_only(args.manifest)
        else:
            if args.output is None:
                parser.error("--verify requires --output")
            result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT314_FRAME0_SUPPORT_VERIFIER_V5: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "case_counts": result.get("case_counts"),
                      "scientific_credit": 0}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
