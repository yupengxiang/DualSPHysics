#!/usr/bin/env python3
"""Read-only preflight for the materialised F2 RV4 solver inputs.

The checker decodes each copied baseline BI4 with the official ``bi4_dump``
adapter and verifies that its bytes, population, 3-D flag, and authoritative
MassFluid header still match the consumed GenCase source.  It also checks the
new XML's allowed numerical changes.  It never runs GenCase or the solver.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _float3(node: ET.Element, name: str) -> list[float]:
    child = node.find(name)
    if child is None:
        child = next((item for item in node if item.get("name") == name), None)
    if child is None and name in {"posmin", "posmax"}:
        child = node.find(name)
    if child is None:
        raise ValueError(f"missing vector {name}")
    return [float(child.get(axis)) for axis in "xyz"]


def decode_metadata(bi4: Path, temporary: Path) -> dict:
    subprocess.run([str(DECODER), str(bi4), str(temporary)], check=True, stdout=subprocess.DEVNULL)
    root = ET.parse(str(temporary) + ".xml").getroot()
    parent = root.find("item")
    child = parent.find("item")
    values = {node.get("name"): node.get("v") for node in parent if node.tag != "item"}
    child_values = {node.get("name"): node.get("v") for node in child if node.tag != "item"}
    map_min = next(node for node in parent if node.get("name") == "MapPosMin")
    map_max = next(node for node in parent if node.get("name") == "MapPosMax")
    return {
        "case_name": values.get("CaseName"), "data2d": values.get("Data2d"),
        "case_np": int(values["CaseNp"]), "case_nfluid": int(values["CaseNfluid"]),
        "case_nfixed": int(values["CaseNfixed"]), "case_nmoving": int(values["CaseNmoving"]),
        "dp_m": float(values["Dp"]), "massfluid_kg": float(values["MassFluid"]),
        "map_posmin_m": _float3(parent, "MapPosMin"), "map_posmax_m": _float3(parent, "MapPosMax"),
        "frame_name": child.get("name"), "frame_time_s": float(child_values["TimeStep"]),
    }


def check_xml(path: Path) -> dict:
    root = ET.parse(path).getroot()
    params = {node.get("key"): node.get("value") for node in root.findall(".//execution/parameters/parameter")}
    domain = root.find(".//execution/parameters/simulationdomain")
    return {
        "path": str(path), "sha256": sha256(path), "TimeOut_s": float(params["TimeOut"]),
        "DtFixed_s": float(params["DtFixed"]), "DtIni_s": float(params["DtIni"]),
        "DtMin_s": float(params["DtMin"]), "TimeMax_s": float(params["TimeMax"]),
        "domain_low_m": _float3(domain, "posmin"), "domain_high_m": _float3(domain, "posmax"),
    }


def run(manifest_path: Path, output: Path) -> dict:
    manifest = json.loads(Path(manifest_path).read_text())
    baseline = [item for item in manifest["cases"] if item["variant"] == "baseline_save001"]
    if len(baseline) != 6:
        raise ValueError(f"expected six baseline cases, found {len(baseline)}")
    rows = []
    with tempfile.TemporaryDirectory(prefix="f2-rv4-preflight-") as temporary:
        for item in baseline:
            bi4 = Path(item["staged_bi4"]["path"])
            old_bi4 = Path(item["consumed_inputs"]["bi4"]["path"])
            metadata = decode_metadata(bi4, Path(temporary) / item["new_case_id"])
            xml = check_xml(Path(item["generated_xml"]["path"]))
            old_request = json.loads(Path(item["old_request"]).read_text())
            expected = json.loads(Path(old_request["gencase_receipt"]).read_text())
            checks = {
                "copied_bi4_sha256_matches_consumed": sha256(bi4) == sha256(old_bi4),
                "new_xml_sha256_matches_manifest": xml["sha256"] == item["generated_xml"]["sha256"],
                "new_motion_sha256_matches_consumed": item["staged_motion"]["sha256"] == item["consumed_inputs"]["motion"]["sha256"],
                "actual_3d": metadata["data2d"] == "0",
                "positive_fluid": metadata["case_nfluid"] > 0,
                "case_particle_count_matches_completed_gencase": metadata["case_np"] == expected["total_particles"],
                "fluid_count_matches_completed_gencase": metadata["case_nfluid"] == expected["fluid_particles"],
                "dp_matches_recipe": abs(metadata["dp_m"] - item["numerical_fields"]["dp_m"]) <= 1e-15,
                "baseline_save_budget": xml["TimeOut_s"] <= 0.001,
                "time_window_four_seconds": xml["TimeMax_s"] == 4.0,
                "first_step_guard": xml["DtIni_s"] == 0.0 and xml["DtMin_s"] == 0.0,
                "domain_repair_is_explicit": xml["domain_low_m"] == manifest["domain_repair"]["new_low_m"] and xml["domain_high_m"] == manifest["domain_repair"]["new_high_m"],
            }
            rows.append({
                "case_id": item["new_case_id"], "physical_case_id": item["case_id"],
                "new_xml": xml, "copied_bi4": {"path": str(bi4), "sha256": sha256(bi4)},
                "native_bi4_metadata": metadata, "checks": checks,
                "all_checks_pass": bool(all(checks.values())),
            })
    report = {
        "schema": "ds-data-02.f2.recipe-v4-preflight.v1", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": {"path": str(Path(manifest_path).resolve()), "sha256": sha256(manifest_path)},
        "decoder": {"path": str(DECODER.resolve()), "sha256": sha256(DECODER)},
        "cases": rows, "all_six_pass": bool(all(row["all_checks_pass"] for row in rows)),
        "qualification_claim": "none; input preflight only, no solver result or Q-I/Q-N/production claim",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output.resolve()), "all_six_pass": report["all_six_pass"]}, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.manifest.resolve(), args.output.resolve())
    return 0 if report["all_six_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
