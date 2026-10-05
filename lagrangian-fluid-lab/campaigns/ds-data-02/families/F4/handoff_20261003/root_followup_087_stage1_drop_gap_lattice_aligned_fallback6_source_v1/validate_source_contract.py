#!/usr/bin/env python3
"""Validate fresh087 source contracts without opening scientific arrays."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csha(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    package = parser.parse_args().package
    plan = load(package / "source-plan.json")
    receipt = load(package / "source-build-receipt.json")
    if plan["stage_contract"]["launch_allowed"] is not False:
        raise SystemExit("launch allowed")
    if sorted(round(float(item["gap_m"]), 5) for item in plan["endpoints"]) != [0.19, 0.2, 0.21, 0.23, 0.24, 0.25]:
        raise SystemExit("gap set drift")
    mother = Path(plan["mother_binding"]["source_definition_xml"])
    old = mother.read_bytes()
    old_literal = plan["mutation_contract"]["old_literal"].encode()
    if old.count(old_literal) != 1:
        raise SystemExit("mother literal count")
    rows = {row["endpoint_id"]: row for row in receipt["endpoints"]}
    ids = []
    for endpoint in plan["endpoints"]:
        eid = endpoint["endpoint_id"]
        ids.append(endpoint["physical_case_id"])
        source = package / endpoint["source_definition_output"]
        expected = old.replace(old_literal, endpoint["drop_point_z_literal"].encode(), 1)
        observed = source.read_bytes()
        if observed != expected or len(observed) != len(old):
            raise SystemExit(f"{eid}: nonlocal XML mutation")
        ET.fromstring(observed)
        if observed.count(endpoint["drop_point_z_literal"].encode()) != 1:
            raise SystemExit(f"{eid}: literal count")
        if sha(source) != endpoint["source_definition_sha256"] or sha(source) != rows[eid]["source_definition_sha256"]:
            raise SystemExit(f"{eid}: source hash")
        owner = load(package / "owners" / f"{eid}.owner.json")
        metadata = load(package / "metadata" / f"{eid}.metadata.json")
        if csha(owner["physical_binding"]) != owner["physical_binding_sha256"]:
            raise SystemExit(f"{eid}: owner binding hash")
        if owner["physical_condition_sha256"] != endpoint["physical_condition_sha256"]:
            raise SystemExit(f"{eid}: condition hash")
        if owner["source_recipe"]["source_particle_counts"] is not None:
            raise SystemExit(f"{eid}: fabricated actual counts")
        if owner["physical_binding"]["initial_state"]["initial_mass_by_source_kg"] is not None:
            raise SystemExit(f"{eid}: fabricated native mass")
        if metadata["physical_binding"] != owner["physical_binding"] or metadata["generated_xml_partition"] is not None:
            raise SystemExit(f"{eid}: metadata binding/future drift")
        if metadata["native_mass_by_source_kg"] is not None or metadata["expected_counts_by_source"] is not None:
            raise SystemExit(f"{eid}: metadata fabricated actuals")
    if len(set(ids)) != 6:
        raise SystemExit("canonical id collision")
    for request_path in sorted((package / "requests").glob("*.request.json")):
        request = load(request_path)
        if request["launch"] is not False or request["launch_allowed"] is not False or request["status"] != "source_only_disabled":
            raise SystemExit(f"{request_path}: launch contract")
        if request["launch_owner"] != "root" or request["independent_case_count_increment"] != 0:
            raise SystemExit(f"{request_path}: owner/count contract")
        for input_path, digest in request.get("input_sha256", {}).items():
            path = Path(input_path)
            if not path.is_file() or sha(path) != digest:
                raise SystemExit(f"{request_path}: input hash closure {path}")
        if any(value is not None for value in request.get("deferred_input_sha256", {}).values()):
            raise SystemExit(f"{request_path}: future hash prefilled")
        if any(Path(path).suffix.lower() in {".bi4", ".h5", ".csv"} for path in request.get("input_files", [])):
            raise SystemExit(f"{request_path}: active scientific array input")
    print(json.dumps({"status": "pass", "scope_id": plan["scope_id"], "endpoint_count": 6, "arrays_read": False, "jobs_started": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
