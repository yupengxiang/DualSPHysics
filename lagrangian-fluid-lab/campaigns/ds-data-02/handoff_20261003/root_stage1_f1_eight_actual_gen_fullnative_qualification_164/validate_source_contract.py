#!/usr/bin/env python3
"""Bounded fresh076 source verifier.

It validates JSON/XML metadata, registered input closure, and the disabled worker
contract. It deliberately never reads or hashes any BI4 file.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return value

def assert_input_closure(req: dict, item: dict) -> None:
    files = set(req["input_files"])
    hashes = set(req["input_sha256"])
    assert files == hashes, (req["case_id"], "input_files/input_sha256 key mismatch")
    bi4 = item["generated_bi4"]
    for name in sorted(files):
        path = Path(name)
        assert path.is_file(), (req["case_id"], "missing input", name)
        registered = req["input_sha256"][name]
        if name == bi4:
            # BI4 is only bound to the already recorded Root prepared-report SHA.
            assert registered == item["generated_bi4_sha256_recorded"], (req["case_id"], "BI4 recorded SHA mismatch")
        else:
            assert sha(path) == registered, (req["case_id"], "input digest mismatch", name)

def main():
    agg = load(ROOT / "metadata/actual-gen162-bindings.json")
    assert agg["schema"] == "ds02.f1.actual-gen162-native-qualification-inputs.v1"
    assert agg["source_only"] is True and agg["execution_allowed"] is False
    assert len(agg["cases"]) == 8
    worker_text = (ROOT / "native_initial_vx_frame0_audit.py").read_text(encoding="utf-8")
    for token in ('parser.add_argument("--binding"', 'parser.add_argument("--output-dir"', 'binding["cases"]', 'Part_0000.bi4', '"-dirdata"'):
        assert token in worker_text, ("worker contract token missing", token)
    checked = []
    for item in agg["cases"]:
        case = item["case_id"]
        rec = Path(item["receipt"]); report = Path(item["prepared_input_report"])
        xml = Path(item["generated_xml"]); bi4 = Path(item["generated_bi4"])
        source = Path(item["source_definition_package"])
        assert rec.is_file() and report.is_file() and xml.is_file() and bi4.is_file() and source.is_file(), case
        r = load(rec); p = load(report)
        assert r.get("status") == "completed" and r.get("returncode") == 0, case
        assert int(r["solver_dimension_from_gencase"]) == 3, case
        assert int(r["total_particles"]) == int(item["total_particles"]), case
        assert int(r["fluid_particles"]) == int(item["fluid_particles"]), case
        assert sha(rec) == item["receipt_sha256"] and sha(report) == item["prepared_input_report_sha256"], case
        assert sha(xml) == item["generated_xml_sha256"] == p["xml_sha256"], case
        assert sha(source) == item["source_definition_package_sha256"], case
        assert item["generated_bi4_sha256_recorded"] == p["bi4_sha256"], case
        checked.append({"case_id": case, "receipt": "completed/0", "dimension": 3,
                        "total_particles": item["total_particles"], "fluid_particles": item["fluid_particles"],
                        "xml_sha256": item["generated_xml_sha256"],
                        "bi4_sha256_recorded": item["generated_bi4_sha256_recorded"]})
        req = load(ROOT / "requests" / f"{case}.full-native-qualification.request.json")
        assert req["kind"] == "qualification" and req["launch_owner"] == "root"
        assert req["launch_allowed"] is False and req["execution_allowed"] is False
        assert req["root_actual_launch_source"].endswith("root_stage1_f6_actual_qualifications_strict_entry_146/launch.py")
        assert req["root_solver_concurrency_cap"] == 8 and req["estimated_peak_gpu_mib"] == 8192
        assert req["cpu_threads"] == 4 and req["max_wall_seconds"] == 14400
        assert req["estimated_storage_bytes"] == 16 * 1024 ** 3
        assert req["gencase_receipt_sha256"] == item["receipt_sha256"]
        assert req["gencase_report_sha256"] == item["prepared_input_report_sha256"]
        assert req["gencase_xml_sha256"] == item["generated_xml_sha256"]
        assert req["gencase_bi4_sha256"] == item["generated_bi4_sha256_recorded"]
        assert req["gencase_expected"]["dimension"] == 3
        expected_tmax = "1.6" if "ECC" in case else "4.0"
        assert req["actual_execution_parameters"]["TimeMax"] == expected_tmax, case
        assert req["actual_execution_parameters"]["TimeOut"] == "0.01", case
        assert req["future_outputs"]["native_execution_receipt_sha256"] is None
        assert req["future_outputs"]["native_frame0_audit_report_sha256"] is None
        assert_input_closure(req, item)
        bind = load(ROOT / "native-vx-bindings" / f"{case}.json")
        assert bind["source_only"] is True and bind["execution_allowed"] is False
        assert bind["cases"][0]["gencase_receipt_sha256"] == item["receipt_sha256"]
        assert bind["cases"][0]["generated_xml_sha256"] == item["generated_xml_sha256"]
        audit = load(ROOT / "requests" / f"{case}.native-frame0-vx-qa.request.json")
        assert audit["kind"] == "cpu" and audit["launch_allowed"] is False
        assert audit["execution_allowed"] is False and audit["cpu_threads"] == 4
        assert audit["command"][2] == "--binding" and audit["command"][4] == "--output-dir"
        assert audit["command"][1] == str(ROOT / "native_initial_vx_frame0_audit.py")
    result = {"schema": "ds02.f1.fresh076-source-validation.v2", "passed": True,
              "arrays_read": False, "bi4_bytes_read": False, "actual_input_hashes_verified": True,
              "input_file_hash_sets_closed": True, "worker_required_args_verified": True,
              "case_count": len(checked), "cases": checked}
    if "--write" in sys.argv:
        (ROOT / "metadata/static-validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
