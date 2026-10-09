#!/usr/bin/env python3
"""Run the additive ROOT276 F6 support audit with per-case identity gates.

This wrapper retains ROOT272 V5's guarded decoder/VTK implementation for
cases whose producer identity is actually closed.  It fixes the V5 failure
mode where a missing ``physical_case_id`` was treated as if the sentinel name
were a physical identity.  Unknown cases are emitted in a partial report and
are not passed to the native/VTK reader.  A failed case remains FAILED; it is
never converted to a success by the partial-report path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V5_WORKER = HERE / "stage2_f6_initial_native_support_audit_v5.py"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v6"
SCHEMA = "ds02.stage2.f6-initial-native-support-audit.v6"
PASS_STATUS = "COMPLETE_PARTIAL_F6_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_V6_NO_SCIENTIFIC_Q"
UNKNOWN_STATUS = "UNKNOWN_F6_INITIAL_NATIVE_SUPPORT_IDENTITY_V6"
FAIL_STATUS = "FAILED_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V6"


class AuditFailure(RuntimeError):
    pass


def _load_v5() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_f6_initial_native_support_audit_v5_source", V5_WORKER)
    if spec is None or spec.loader is None:
        raise AuditFailure(f"cannot load V5 dependency: {V5_WORKER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stable_manifest(path: Path) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"manifest is not a regular file: {path}")
    before = path.stat()
    if before.st_size > 32 * 1024 * 1024:
        raise AuditFailure("manifest exceeds bounded JSON limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise AuditFailure("manifest changed while read")
    if not isinstance(value, dict):
        raise AuditFailure("manifest must be an object")
    return value


def _identity_case(v5: Any, case: dict[str, Any]) -> dict[str, Any]:
    """Validate receipt/request/XML/mapping without touching deferred payloads."""
    receipt_record = case.get("producer_receipt")
    if not isinstance(receipt_record, dict):
        return {"status": "UNKNOWN", "reason": "producer receipt record missing", "missing_fields": ["producer_receipt"]}
    try:
        receipt, record = v5._stable_json(receipt_record, f"{case.get('sentinel_id')}/{case.get('grid')} producer receipt")
    except Exception as exc:
        return {"status": "FAILED", "reason": f"receipt metadata read failed: {exc}"}
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        return {"status": "FAILED", "reason": "producer receipt is not completed rc=0", "receipt": record}
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    mapping = case.get("domain_mapping_v6")
    identity = case.get("producer_identity_v6")
    if not isinstance(mapping, dict) or not isinstance(identity, dict):
        return {"status": "UNKNOWN", "reason": "V6 identity/mapping sidecar missing", "receipt": record}
    missing: list[str] = []
    actual_case = request.get("case_id")
    actual_attempt = request.get("attempt_id") or request.get("attempt_root") or receipt.get("attempt_id")
    actual_physical = request.get("physical_case_id")
    if not isinstance(actual_case, str) or not actual_case:
        missing.append("request.case_id")
    if not isinstance(actual_attempt, str) or not actual_attempt:
        missing.append("request.attempt_id")
    if not isinstance(actual_physical, str) or not actual_physical:
        missing.append("request.physical_case_id")
    if not mapping.get("domain_label"):
        missing.append("domain_mapping.domain_label")
    if not isinstance(request.get("input_files"), list):
        missing.append("request.input_files")
    if not isinstance(request.get("input_hashes", request.get("input_sha256")), dict):
        missing.append("request.input_hashes")
    xml_record = case.get("xml")
    xml_path = str(xml_record.get("path")) if isinstance(xml_record, dict) else ""
    output_root = str(receipt.get("output_root", ""))
    if not xml_path:
        missing.append("generated_xml.path")
    if not output_root:
        missing.append("receipt.output_root")
    if xml_path and output_root and Path(xml_path).parent.absolute() != Path(output_root).absolute():
        return {"status": "FAILED", "reason": "receipt output_root does not contain generated XML", "receipt": record}
    if missing:
        return {
            "status": "UNKNOWN",
            "reason": "producer identity/input closure incomplete; no sentinel fallback",
            "missing_fields": missing,
            "receipt": record,
            "actual": {"case_id": actual_case, "attempt_id": actual_attempt, "physical_case_id": actual_physical,
                        "output_root": output_root, "generated_xml": xml_path},
            "mapping": mapping,
        }
    if identity.get("case_id") != actual_case or identity.get("attempt_id") != actual_attempt or identity.get("physical_case_id") != actual_physical:
        return {"status": "FAILED", "reason": "V6 manifest identity differs from actual producer request", "receipt": record}
    return {
        "status": "PASS",
        "receipt": record,
        "actual": {"case_id": actual_case, "attempt_id": actual_attempt, "physical_case_id": actual_physical,
                    "output_root": output_root, "generated_xml": xml_path},
        "mapping": mapping,
    }


def _unknown_entry(case: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "sentinel_id": case.get("sentinel_id"),
        "grid": case.get("grid"),
        "status": "UNKNOWN_PRODUCER_IDENTITY",
        "identity": identity,
        "field_scope": "POSITION_ONLY_INITIAL_SUPPORT_NOT_RUN",
        "support": "UNKNOWN",
        "mass_separation": "UNKNOWN",
        "deferred_payload_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }


def run(manifest_path: Path, attempt_root: Path, output: Path) -> dict[str, Any]:
    manifest = _stable_manifest(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AuditFailure("ROOT276 V6 manifest schema mismatch")
    v5 = _load_v5()
    outputs: list[dict[str, Any]] = []
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    for case in manifest.get("cases", []):
        if not isinstance(case, dict):
            raise AuditFailure("manifest case is not an object")
        identity = _identity_case(v5, case)
        status = identity.get("status")
        if status == "UNKNOWN":
            outputs.append(_unknown_entry(case, identity)); counts["UNKNOWN"] += 1; continue
        if status != "PASS":
            outputs.append({"sentinel_id": case.get("sentinel_id"), "grid": case.get("grid"), "status": "FAILED_PRODUCER_IDENTITY", "identity": identity, "deferred_payload_read": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}})
            counts["FAILED"] += 1; continue
        try:
            # V5 performs the stable XML/native/VTK work only after this V6
            # identity gate.  It never sees a sentinel fallback physical ID.
            xml_root, xml_record = v5._stable_xml(case["xml"], f"{case['sentinel_id']}/{case['grid']} XML")
            item = v5._native_case(case, xml_root, Path(str(case["xml"]["path"])).expanduser().absolute(), attempt_root)
            item["producer_join"] = identity
            item["producer_join"]["xml"] = xml_record
            v5._vtk_case(case, item)
            item["status"] = "PASS_CASE_INITIAL_SUPPORT_DIAGNOSTIC"
            item["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
            outputs.append(item); counts["PASS"] += 1
        except Exception as exc:
            outputs.append({"sentinel_id": case.get("sentinel_id"), "grid": case.get("grid"), "status": "FAILED_CASE_INITIAL_SUPPORT", "reason": repr(exc), "identity": identity, "deferred_payload_read": True, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}})
            counts["FAILED"] += 1
    if not outputs:
        raise AuditFailure("ROOT276 manifest has no cases")
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS if counts["PASS"] or counts["UNKNOWN"] else FAIL_STATUS,
        "manifest": {"path": str(manifest_path.expanduser().absolute())},
        "cases": outputs,
        "case_counts": counts,
        "identity_policy": {
            "physical_case_id_fallback": "FORBIDDEN",
            "partial_report": True,
            "unknown_cases_do_not_read_payload": True,
            "failed_cases_are_not_success": True,
        },
        "mass_semantics": {
            "continuous_owner_mass_kg": 4851.988676250775,
            "physical_massbody_kg": 128.0,
            "legacy_source_sample_mass_kg": 5120.0,
            "sample_mass_is_not_continuous_owner": True,
            "no_rescale": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "read_scope": {"builder_payload_read": False, "worker_unknown_case_payload_read": False, "full_native_tree_scan": False, "hdf5_read": False, "solver_launch": False},
    }
    v5._write_once(output, result)
    return result


def _self_test() -> None:
    v5 = _load_v5()
    mapping = {"domain_label": "fixture F6-S1/coarse", "source_authority": "fixture owner edges"}
    case = {"sentinel_id": "F6-S1", "grid": "coarse", "xml": {"path": "/tmp/generated.xml"},
            "producer_receipt": {"path": "fixture-receipt.json"}, "domain_mapping_v6": mapping,
            "producer_identity_v6": {"case_id": "actual", "attempt_id": "a1", "physical_case_id": "physical"}}
    good = {"status": "completed", "returncode": 0, "output_root": "/tmp", "request": {"case_id": "actual", "attempt_id": "a1", "physical_case_id": "physical", "input_files": ["x"], "input_hashes": {"x": "sha"}}}
    bad = json.loads(json.dumps(good)); del bad["request"]["physical_case_id"]
    # Exercise the same metadata shape used by the actual worker without
    # opening a production file.  The request builder owns the equivalent
    # pure validation function; the worker's complete fixture is V5's
    # established six-case CLI test.
    original = v5._stable_json
    try:
        v5._stable_json = lambda record, label: (good, {"path": "fixture-receipt", "sha256": "fixture", "bytes": 1, "stat": {}, "stable_read": True})
        out = _identity_case(v5, case)
        assert out["status"] == "PASS"
        v5._stable_json = lambda record, label: (bad, {"path": "fixture-receipt", "sha256": "fixture", "bytes": 1, "stat": {}, "stable_read": True})
        out = _identity_case(v5, case)
        assert out["status"] == "UNKNOWN" and "request.physical_case_id" in out["missing_fields"]
    finally:
        v5._stable_json = original
    # Exercise the real CLI entry with the receipt shape that caused ROOT272:
    # a completed coarse producer whose request omits physical_case_id.  The
    # V6 process must write a partial UNKNOWN case and exit cleanly without
    # opening any deferred payload.
    with tempfile.TemporaryDirectory(prefix="root276-v6-cli-") as td:
        root = Path(td)
        receipt_path = root / "coarse-receipt.json"
        receipt_path.write_text(json.dumps({
            "status": "completed", "returncode": 0, "output_root": str(root / "attempt"),
            "request": {"case_id": "F6_S1_SPATIAL_V1_COARSE", "attempt_id": "coarse-001",
                        "input_files": ["source.xml"], "input_hashes": {"source.xml": "sha"}},
        }) + "\n", encoding="utf-8")
        raw = receipt_path.read_bytes(); stat = receipt_path.stat()
        receipt_record = {"path": str(receipt_path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                          "stat": {"dev": stat.st_dev, "ino": stat.st_ino, "bytes": stat.st_size,
                                   "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}}
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps({
            "schema": MANIFEST_SCHEMA,
            "status": "PREPARED_NOT_RUN_ROOT276_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V6",
            "cases": [{
                "sentinel_id": "F6-S1", "grid": "coarse", "xml": {"path": str(root / "attempt" / "generated.xml")},
                "producer_receipt": receipt_record,
                "producer_identity_v6": {"status": "UNKNOWN", "physical_case_id": None, "case_id": "F6_S1_SPATIAL_V1_COARSE", "attempt_id": "coarse-001"},
                "domain_mapping_v6": {"domain_label": "fixture F6-S1 coarse"},
            }],
        }) + "\n", encoding="utf-8")
        output = root / "observer.json"
        completed = subprocess.run([
            sys.executable, "-B", str(HERE / Path(__file__).name), "--run",
            "--manifest", str(manifest_path), "--attempt-root", str(root / "attempt"), "--output", str(output),
        ], check=False, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        cli_result = json.loads(output.read_text(encoding="utf-8"))
        assert cli_result["case_counts"] == {"PASS": 0, "UNKNOWN": 1, "FAILED": 0}
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_WORKER_V6_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--manifest, --attempt-root, and --output are required with --run")
    try:
        result = run(args.manifest, args.attempt_root, args.output)
        print(json.dumps({"status": result["status"], "output": str(args.output.absolute()), "case_counts": result["case_counts"]}, sort_keys=True))
        return 0 if result["status"] != FAIL_STATUS else 2
    except Exception as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_WORKER_V6: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
