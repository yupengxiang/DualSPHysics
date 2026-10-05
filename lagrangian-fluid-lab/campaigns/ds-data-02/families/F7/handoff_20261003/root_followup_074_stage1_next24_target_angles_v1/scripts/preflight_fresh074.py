#!/usr/bin/env python3
"""Bounded fresh074 source/request preflight.

Only JSON, XML, Python source and executable metadata are read.  This tool
deliberately refuses BI4/CSV/H5/VTK/motion payload paths and never launches a
worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise RuntimeError(message)


def check_request(path: Path) -> None:
    value = load(path)
    for key in ("launch", "launch_allowed", "execution_allowed"):
        if value.get(key) is not False:
            fail(f"{path}: {key} is not false")
    if value.get("future_hashes_null") is not True:
        fail(f"{path}: future_hashes_null missing")
    files = value.get("input_files", [])
    hashes = value.get("input_sha256", {})
    if set(files) != set(hashes):
        fail(f"{path}: input_files/input_sha256 key closure mismatch")
    for raw, expected in hashes.items():
        p = Path(raw)
        if not p.is_file():
            fail(f"{path}: missing bounded input {p}")
        if sha(p) != expected:
            fail(f"{path}: bounded input hash mismatch {p}")
    future = value.get("future_input_files", [])
    future_hashes = value.get("future_input_sha256", {})
    if set(future) != set(future_hashes):
        fail(f"{path}: future input/hash closure mismatch")
    if any(v is not None for v in future_hashes.values()):
        fail(f"{path}: future hash was fabricated")
    text = path.read_text(encoding="utf-8").lower()
    if any(token in text for token in ("production_approval\": \"approved", "q_n\": \"pass", "precision_status\": \"accepted")):
        fail(f"{path}: source request contains an acceptance claim")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = load(PACKAGE / "metadata/next24-plan.json")
    if plan.get("launch_allowed") is not False or plan.get("source_only") is not True:
        fail("plan is not disabled source-only")
    endpoints = plan.get("endpoints", [])
    if len(endpoints) != 24:
        fail(f"expected 24 endpoints, got {len(endpoints)}")
    ids = [e["endpoint_id"] for e in endpoints]
    amplitudes = [e["amplitude_deg"] for e in endpoints]
    if len(set(ids)) != 24 or len(set(amplitudes)) != 24:
        fail("endpoint IDs or amplitudes are not unique")
    if any(a in plan["existing_registry"]["amplitudes_deg"] for a in amplitudes):
        fail("proposed amplitude collides with existing integer registry")
    owners = []
    for endpoint in endpoints:
        cid = endpoint["endpoint_id"]
        source = PACKAGE / "source" / f"{cid}_Def.xml"
        owner_path = PACKAGE / "owners" / f"{cid}.owner.json"
        if not source.is_file() or not owner_path.is_file():
            fail(f"missing source/owner {cid}")
        if sha(source) != endpoint["source_definition_clone_sha256"]:
            fail(f"source XML hash mismatch {cid}")
        tree = ET.parse(source).getroot()
        definition = tree.find("./casedef/geometry/definition")
        parameters = {n.get("key"): n.get("value") for n in tree.findall("./execution/parameters/parameter")}
        if definition is None or definition.get("dp") != "0.02" or parameters.get("TimeMax") != "12" or parameters.get("TimeOut") != "0.02":
            fail(f"recipe changed {cid}")
        owner = load(owner_path)
        if owner.get("launch_allowed") is not False:
            fail(f"owner enabled {cid}")
        if hashlib.sha256(canonical(owner["physical_binding"])).hexdigest() != owner["canonical_physical_binding_sha256"]:
            fail(f"canonical owner hash mismatch {cid}")
        if owner["physical_condition_sha256"] != endpoint["physical_condition_sha256"] or owner["canonical_physical_binding_sha256"] != endpoint["canonical_physical_binding_sha256"]:
            fail(f"owner hash binding mismatch {cid}")
        owners.append(cid)
    requests = sorted((PACKAGE / "requests").glob("*.json")) + sorted((PACKAGE / "requests/gencase").glob("*.json")) + sorted((PACKAGE / "requests/native").glob("*.json"))
    if len(requests) != 52:  # 4 aggregate + 24 GenCase + 24 native
        fail(f"expected 52 disabled requests, got {len(requests)}")
    for request in requests:
        check_request(request)
    report = {
        "schema": "ds02.f7.fresh074.preflight-report.v1",
        "scope_id": plan["scope_id"],
        "all_passed": True,
        "endpoint_count": len(endpoints),
        "request_count": len(requests),
        "owner_count": len(owners),
        "future_hashes_null": True,
        "arrays_read": False,
        "jobs_started": False,
        "shared_registry_write": False,
        "claim_boundary": "Static bounded source/request contract only; no scientific payload, GenCase, PartVTK, solver, conversion, rendering, precision, Q-N, visual or production result.",
    }
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
