#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

FORBIDDEN = {".h5", ".dat", ".bi4", ".csv", ".vtk"}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()

def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path)
    return value

def req(c, msg):
    if not c: raise ValueError(msg)

def main():
    root = Path(__file__).resolve().parents[1]
    plan = load(root / "metadata/fresh120-source-plan.json")
    actual = load(root / "metadata/fresh120-actual-typed590-metadata.json")
    req(plan["schema"].startswith("ds02.f5.c082s1.fresh120"), "plan schema")
    req(len(actual["cases"]) == 2, "two cases required")
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in FORBIDDEN:
            raise ValueError(f"science payload copied into source package: {path}")
    manifest = load(root / "manifest.json")
    for item in manifest["files"]:
        path = root / item["path"]
        req(path.is_file(), f"manifest missing {path}")
        req(sha(path) == item["sha256"], f"manifest mismatch {path}")
    req(not any(item["path"] == "metadata/fresh120-validator-report.json" for item in manifest["files"]), "validator report self-reference")
    worker = root / "workers/typed590_control_dynamic_audit.py"
    worker_text = worker.read_text(encoding="utf-8")
    req('BINDING_SCHEMA = "ds02.f5.c082s1.typed590-control-dynamic-binding.fresh120.v1"' in worker_text, "worker schema")
    for tag in ("A080", "A120"):
        bind_path = root / f"bindings/{tag}-typed590-control-dynamic-binding.json"
        req_path = root / f"requests/{tag}-typed590-control-dynamic-audit-request.json"
        b = load(bind_path); r = load(req_path)
        req(r["disabled"] is True and r["execution_allowed"] is False and r["launch"] is False and r["solver_allowed"] is False, f"{tag} not disabled")
        req(r["kind"] == "cpu" and r["cpu_task_kind"] == "audit" and r["cpu_threads"] == 2, f"{tag} runtime kind")
        req(r["arrays_allowed"] is True and r["array_edit_allowed"] is False, f"{tag} array read contract")
        req(r["fullnative_gate"]["status"] == "WAIT" and r["full801_authorized"] is False, f"{tag} full gate")
        req(b["execution_allowed"] is False and b["source_only"] is True, f"{tag} binding gate")
        req(r["binding_sha256"] == sha(bind_path), f"{tag} binding hash")
        req(r["input_sha256"][str(bind_path)] == sha(bind_path), f"{tag} input binding hash")
        conversion = load(Path(b["conversion_report"]))
        motion = load(Path(b["motion_transform_report"]))
        req(conversion["conversion_status"] == "completed" and conversion["frames"] == 801 and conversion["particles"] == 194427, f"{tag} conversion metadata")
        req(conversion["output_hdf5"] == b["trajectory_h5"] and conversion["output_sha256"] == b["trajectory_h5_sha256"], f"{tag} H5 attestation")
        req(motion["status"] == "completed" and motion["rows"] == 641 and motion["output_motion"] == b["motion_file"] and motion["output_motion_sha256"] == b["motion_file_sha256"], f"{tag} motion attestation")
        req(r["input_sha256"][b["trajectory_h5"]] == b["trajectory_h5_sha256"], f"{tag} H5 source attestation")
        req(r["input_sha256"][b["motion_file"]] == b["motion_file_sha256"], f"{tag} DAT source attestation")
        req(r["future_output_hashes"]["audit_report_sha256"] is None, f"{tag} future output hash")
        req(b["native_bed_marker_mk"] == 50 and b["source_mkbound"] == 40, f"{tag} Mk map")
        req(isinstance(b.get("source_h5_condition_sha256"), str) and b.get("source_h5_scope_schema") == "legacy-owner-scope.v0", f"{tag} legacy H5 scope")
        xml = ET.parse(root / f"inputs/{tag}-Definition.xml").getroot()
        obj = xml.find('./casedef/motion/objreal'); begin = obj.find('./begin'); mv = obj.find('./mvpredef'); file_node = mv.find('./file')
        req(obj.attrib.get("ref") == "10" and begin.attrib.get("mov") == "1" and begin.attrib.get("start") == "0.00" and begin.attrib.get("finish") == "16", f"{tag} XML motion")
        req(mv.attrib.get("id") == "1" and mv.attrib.get("duration") == "16" and file_node.attrib.get("fieldtime") == "0" and file_node.attrib.get("fieldx") == "1", f"{tag} XML motion fields")
        req(len(b["focus_frames"]) == 7 and [x["frame"] for x in b["focus_frames"]] == [0, 97, 153, 219, 400, 718, 800], f"{tag} focus frames")
    report = {
        "schema": "ds02.f5.c082s1.fresh120-validator-report.v1",
        "status": "passed_metadata_only",
        "candidate_count": 2,
        "typed590_producer_rows_checked": 2,
        "focus_frames": [0, 97, 153, 219, 400, 718, 800],
        "science_payloads_opened_or_hashed_by_validator": False,
        "fullnative_gate": "WAIT",
        "visual_mechanism_acceptance": False,
        "case_increment": 0,
    }
    (root / "metadata/fresh120-validator-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))

if __name__ == "__main__": main()
