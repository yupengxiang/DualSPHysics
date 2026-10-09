#!/usr/bin/env python3
"""ROOT276 V7 worker: V6 support audit with a strict source-domain bridge."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
V5_WORKER = HERE / "stage2_f6_initial_native_support_audit_v5.py"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v7"
SCHEMA = "ds02.stage2.f6-initial-native-support-audit.v7"
PASS_STATUS = "COMPLETE_PARTIAL_F6_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_V7_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V7"


class AuditFailure(RuntimeError):
    pass


def _load_v5() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_f6_initial_native_support_audit_v5_source_v7", V5_WORKER)
    if spec is None or spec.loader is None:
        raise AuditFailure(f"cannot load V5 dependency: {V5_WORKER}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _stable_manifest(path: Path) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file(): raise AuditFailure(f"manifest is not regular: {path}")
    before = path.stat(); value = json.loads(path.read_text(encoding="utf-8")); after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns): raise AuditFailure("manifest changed while read")
    if not isinstance(value, dict): raise AuditFailure("manifest must be object")
    return value


def _identity_case(v5: Any, case: dict[str, Any]) -> dict[str, Any]:
    rec = case.get("producer_receipt_v6") or case.get("producer_receipt")
    if not isinstance(rec, dict): return {"status": "UNKNOWN", "reason": "producer receipt missing"}
    try: receipt, record = v5._stable_json(rec, f"{case.get('sentinel_id')}/{case.get('grid')} producer receipt")
    except Exception as exc: return {"status": "FAILED", "reason": f"receipt metadata read failed: {exc}"}
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0: return {"status": "FAILED", "reason": "producer receipt is not completed rc=0", "receipt": record}
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    bridge = case.get("domain_equivalence_v7") if isinstance(case.get("domain_equivalence_v7"), dict) else {}
    expected_case = case.get("producer_case_id")
    actual_case = request.get("case_id")
    actual_attempt = request.get("attempt_id") or request.get("attempt_root") or receipt.get("attempt_id")
    actual_physical = request.get("physical_case_id")
    xml = case.get("xml") if isinstance(case.get("xml"), dict) else {}
    xml_path = str(xml.get("path", "")); output_root = str(receipt.get("output_root", ""))
    if not actual_case or not actual_attempt or not xml_path or not output_root: return {"status": "UNKNOWN", "reason": "producer identity fields incomplete", "receipt": record}
    if expected_case and actual_case != expected_case: return {"status": "FAILED", "reason": "producer case_id differs from manifest", "receipt": record}
    if Path(xml_path).expanduser().absolute().parent != Path(output_root).expanduser().absolute(): return {"status": "FAILED", "reason": "generated XML outside receipt output_root", "receipt": record}
    if actual_physical:
        if case.get("physical_case_id") and actual_physical != case.get("physical_case_id"): return {"status": "FAILED", "reason": "direct physical identity differs", "receipt": record}
        return {"status": "PASS", "physical_identity_mode": "DIRECT_PRODUCER_REQUEST", "receipt": record, "actual": {"case_id": actual_case, "attempt_id": actual_attempt, "physical_case_id": actual_physical, "output_root": output_root}}
    if bridge.get("status") != "PASS_EXACT_SOURCE_DOMAIN" or not isinstance(bridge.get("source_physical_case_id"), str):
        return {"status": "UNKNOWN", "reason": "missing physical ID and no exact V7 domain bridge", "bridge": bridge, "receipt": record}
    return {"status": "PASS", "physical_identity_mode": "SOURCE_DOMAIN_BRIDGE", "receipt": record, "actual": {"case_id": actual_case, "attempt_id": actual_attempt, "physical_case_id": bridge["source_physical_case_id"], "output_root": output_root}, "bridge": bridge}


def run(manifest_path: Path, attempt_root: Path, output: Path) -> dict[str, Any]:
    manifest = _stable_manifest(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA: raise AuditFailure("ROOT276 V7 manifest schema mismatch")
    v5 = _load_v5(); outputs = []; counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    for case in manifest.get("cases", []):
        if not isinstance(case, dict): raise AuditFailure("manifest case not object")
        identity = _identity_case(v5, case)
        if identity.get("status") == "UNKNOWN":
            outputs.append({"sentinel_id": case.get("sentinel_id"), "grid": case.get("grid"), "status": "UNKNOWN_PRODUCER_OR_DOMAIN_IDENTITY", "identity": identity, "deferred_payload_read": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}); counts["UNKNOWN"] += 1; continue
        if identity.get("status") != "PASS":
            outputs.append({"sentinel_id": case.get("sentinel_id"), "grid": case.get("grid"), "status": "FAILED_PRODUCER_OR_DOMAIN_IDENTITY", "identity": identity, "deferred_payload_read": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}); counts["FAILED"] += 1; continue
        try:
            # V5's readers are reused only after the direct or exact source
            # domain gate.  The source-current physical ID is an authority
            # sidecar; it is never written back into the producer receipt.
            working = dict(case)
            working["physical_case_id"] = identity["actual"]["physical_case_id"]
            xml_root, xml_record = v5._stable_xml(working["xml"], f"{case['sentinel_id']}/{case['grid']} XML")
            item = v5._native_case(working, xml_root, Path(str(working["xml"]["path"])).expanduser().absolute(), attempt_root)
            item["producer_join"] = identity; item["producer_join"]["xml"] = xml_record
            v5._vtk_case(working, item); item["status"] = "PASS_CASE_INITIAL_SUPPORT_DIAGNOSTIC"; item["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
            outputs.append(item); counts["PASS"] += 1
        except Exception as exc:
            outputs.append({"sentinel_id": case.get("sentinel_id"), "grid": case.get("grid"), "status": "FAILED_CASE_INITIAL_SUPPORT", "reason": repr(exc), "identity": identity, "deferred_payload_read": True, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}); counts["FAILED"] += 1
    result = {"schema": SCHEMA, "status": PASS_STATUS if counts["PASS"] or counts["UNKNOWN"] else FAIL_STATUS, "manifest": {"path": str(manifest_path.absolute())}, "cases": outputs, "case_counts": counts, "identity_policy": {"physical_case_id_fallback": "FORBIDDEN", "domain_bridge": "source-current physical ID and exact source/control hash evidence", "unknown_cases_do_not_read_payload": True, "failed_cases_are_not_success": True}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "read_scope": {"builder_payload_read": False, "unknown_case_payload_read": False, "full_native_tree_scan": False, "hdf5_read": False, "solver_launch": False}}
    v5._write_once(output, result); return result


def _self_test() -> None:
    v5 = _load_v5(); assert callable(v5._native_case); assert MANIFEST_SCHEMA.endswith("v7")
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_WORKER_V7_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); group = parser.add_mutually_exclusive_group(required=True); group.add_argument("--self-test", action="store_true"); group.add_argument("--run", action="store_true"); parser.add_argument("--manifest", type=Path); parser.add_argument("--attempt-root", type=Path); parser.add_argument("--output", type=Path); args = parser.parse_args()
    if args.self_test: _self_test(); return 0
    if args.manifest is None or args.attempt_root is None or args.output is None: parser.error("--run requires --manifest, --attempt-root, --output")
    try:
        result = run(args.manifest, args.attempt_root, args.output); print(json.dumps({"status": result["status"], "output": str(args.output.absolute()), "case_counts": result["case_counts"]}, sort_keys=True)); return 0 if result["status"] != FAIL_STATUS else 2
    except Exception as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_WORKER_V7: {exc}"); return 2


if __name__ == "__main__": raise SystemExit(main())
