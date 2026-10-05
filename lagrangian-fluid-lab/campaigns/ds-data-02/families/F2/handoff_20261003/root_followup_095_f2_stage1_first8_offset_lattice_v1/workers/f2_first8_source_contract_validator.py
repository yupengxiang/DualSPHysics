#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def check(case: dict) -> dict:
    definition = Path(case["definition"]["path"])
    metadata = Path(case["metadata"]["path"])
    request_paths = [Path(x) for x in case["requests"].values()]
    root = ET.parse(definition).getroot()
    errors = []
    geometry = root.find(".//geometry/definition")
    if geometry is None or abs(float(geometry.attrib.get("dp", "nan")) - 0.01) > 1e-12:
        errors.append("dp is not .01")
    params = {n.attrib.get("key"): n.attrib.get("value") for n in root.findall(".//execution/parameters/parameter")}
    for key, expected in (("TimeMax", "4"), ("TimeOut", "0.01")):
        if params.get(key) != expected:
            errors.append(f"{key}={params.get(key)!r}")
    points = root.findall(".//geometry/commands/mainlist/drawbox/point")
    receiver = [p for p in points if p.attrib.get("y") == "-0.16" and p.attrib.get("z") == "0"]
    if len(receiver) != 1:
        errors.append("receiver point is not uniquely identified")
    m = json.loads(metadata.read_text(encoding="utf-8"))
    if sha(definition) != case["definition"]["sha256"]:
        errors.append("definition hash drift")
    if m.get("actual_counts") is not None or any(m.get("future_receipt_hashes", {}).values()):
        errors.append("future evidence was prefilled")
    for request in request_paths:
        q = json.loads(request.read_text(encoding="utf-8"))
        if q.get("launch_allowed") is not False or q.get("execution_allowed") is not False:
            errors.append(f"request enabled: {request.name}")
    return {"case_id": case["case_id"], "status": "pass" if not errors else "fail", "errors": errors,
            "definition_sha256": sha(definition), "metadata_sha256": sha(metadata),
            "arrays_opened": False}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    reports = [check(c) for c in manifest["cases"]]
    report = {"schema": "ds02.f2.stage1.first8.source-contract-audit.v1",
              "status": "pass" if all(x["status"] == "pass" for x in reports) else "fail",
              "source_only": True, "arrays_opened": False, "cases": reports}
    output = Path(args.output) if args.output else None
    if output:
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())
