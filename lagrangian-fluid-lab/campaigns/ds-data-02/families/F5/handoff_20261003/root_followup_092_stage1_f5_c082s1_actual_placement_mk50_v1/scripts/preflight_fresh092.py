#!/usr/bin/env python3
"""Metadata/XML-only preflight for F5 fresh092.

This script intentionally does not open the official particle CSV, BI4 or
motion data.  Their producer/helper SHA values are checked as provenance
bindings only; the Root-run worker performs the actual stage-one audit.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL_PREFIX = "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_092_stage1_f5_c082s1_actual_placement_mk50_v1"
GATT = "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293"
AATT = "root-stage1-f5-c082s1-solid-fluid-recovery-stage1-placement-mk50-audit-315"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
COUNTS = {"total_particles": 194427, "fixed_particles": 158559,
          "moving_particles": 4210, "floating_particles": 0,
          "fluid_particles": 31658}
CSV_SHA = "a1165d9d1d6645f22774eb57c6be0a236b1fbba90f46577cc2ab3fa51d2abfb8"
BI4_SHA = "ca47865795da43a42f8b58d9b15118a2c71ab4c7ba19bbb22a15ef2dd208e198"
XML_SHA = "19102e12efb4ba6d36f12bc020135fbcd7013949b9089fe1b6197b8e23c51e8e"
MOTION_SHA = "51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a"


def require(value: object, message: str) -> None:
    if not value:
        raise AssertionError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"not a JSON object: {path}")
    return value


def map_local(path: str) -> Path:
    if path.startswith(FINAL_PREFIX):
        return ROOT / path[len(FINAL_PREFIX):].lstrip("/")
    return Path(path)


def check_request(path: Path, *, audit: bool = False) -> None:
    request = load(path)
    require(request.get("execution_allowed") is False and request.get("launch_allowed") is False,
            f"{path.name} is not disabled")
    require(request.get("full801_authorized") is False and request.get("full16_authorized") is False,
            f"{path.name} solver authorization leaked")
    require(not any("resource-ledger.json" in value for value in request.get("input_files", [])),
            f"{path.name} includes live ledger")
    if audit:
        require(request.get("attempt_id") == AATT and request.get("cpu_task_kind") == "audit",
                "audit request identity/task kind mismatch")
        require(request.get("estimated_storage_bytes") == 2147483648,
                "audit storage guard mismatch")
    require(set(request.get("input_files", [])) == set(request.get("input_sha256", {})),
            f"{path.name} input hash closure")
    for name in request.get("input_files", []):
        ref = map_local(name)
        require(ref.is_file(), f"missing request input: {name}")
        digest = request["input_sha256"][name]
        if ref.suffix == ".bi4":
            require(digest == BI4_SHA, f"{path.name} BI4 provenance mismatch")
        elif ref.suffix == ".csv":
            require(digest == CSV_SHA, f"{path.name} official CSV provenance mismatch")
        elif ref.suffix == ".dat":
            require(digest == MOTION_SHA, f"{path.name} motion provenance mismatch")
        else:
            require(sha(ref) == digest, f"{path.name} input SHA mismatch: {name}")
    future = request.get("future_output_hashes")
    if future is not None:
        require(all(value in (None, "null", "") for value in future.values()),
                f"{path.name} future hash was invented")


def main() -> None:
    binding = load(ROOT / "bindings/actual-placement-mk50-315-binding.json")
    require(binding.get("schema") == "ds02.f5.c082s1.stage1-placement-mk50-binding.fresh092.v1",
            "binding schema")
    require(binding.get("case_id") == CASE and binding.get("gencase_attempt_id") == GATT,
            "binding identity")
    require(binding.get("audit_attempt_id") == AATT, "audit identity")
    require(binding.get("actual_counts") == COUNTS, "actual count binding")
    require(binding.get("dimension") == 3 and binding.get("source_mkbound") == 40
            and binding.get("native_bed_mk") == 50, "physical marker binding")
    require(binding.get("historical_precision_failure", {}).get("accepted_for_stage1_placement") is False,
            "precision failure accidentally accepted")
    files = binding["files"]
    require(set(files) == {"actual_gencase_binding", "gencase_receipt", "prepared_input_report",
                           "generated_xml", "generated_bi4", "gencase_output_root",
                           "previous_qa_receipt", "initial_qa_report",
                           "physical_geometry_diagnostic", "official_csv"},
            "binding file contract")
    side = load(map_local(files["actual_gencase_binding"]["path"]))
    require(side.get("actual_counts") == COUNTS and side.get("attempt_id") == GATT,
            "producer sidecar")
    receipt = load(Path(files["gencase_receipt"]["path"]))
    prepared = load(Path(files["prepared_input_report"]["path"]))
    require(sha(Path(files["gencase_receipt"]["path"])) == files["gencase_receipt"]["sha256"],
            "producer receipt SHA")
    require(sha(Path(files["prepared_input_report"]["path"])) == files["prepared_input_report"]["sha256"],
            "prepared report SHA")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0
            and receipt.get("request", {}).get("attempt_id") == GATT, "producer receipt")
    require(prepared.get("actual_total_particles") == COUNTS["total_particles"],
            "prepared report total")
    xml_path = Path(files["generated_xml"]["path"])
    require(sha(xml_path) == XML_SHA and files["generated_xml"]["sha256"] == XML_SHA,
            "producer XML SHA")
    xml = ET.parse(xml_path).getroot()
    require(xml.find("./execution/constants/data2d").get("value") == "false", "producer XML 3-D")
    particles = xml.find("./execution/particles")
    require(particles is not None and int(particles.get("np", "-1")) == COUNTS["total_particles"],
            "producer XML total")
    previous = load(Path(files["previous_qa_receipt"]["path"]))
    require(sha(Path(files["previous_qa_receipt"]["path"])) == files["previous_qa_receipt"]["sha256"],
            "Root314 receipt SHA")
    require(previous.get("status") == "failed" and previous.get("returncode") == 1,
            "Root314 failure was not preserved")
    qa = load(Path(files["initial_qa_report"]["path"]))
    geometry = load(Path(files["physical_geometry_diagnostic"]["path"]))
    require(qa.get("cases", [{}])[0].get("official_csv_sha256") == CSV_SHA,
            "helper CSV SHA")
    require(geometry.get("provenance", {}).get("official_csv_sha256") == CSV_SHA,
            "geometry CSV SHA")
    require(geometry.get("actual_native_fluid") == COUNTS["fluid_particles"]
            and geometry.get("actual_unique_fluid_y_levels") == 15
            and geometry.get("expected_unique_fluid_y_levels") == 15,
            "helper scalar placement evidence")
    check_request(ROOT / "requests/placement-mk50-audit-request.json", audit=True)
    check_request(ROOT / "requests/short-native-qualification-request.json")
    print(json.dumps({
        "status": "preflight_pass",
        "actual_counts": COUNTS,
        "actual_gencase_attempt": GATT,
        "audit_attempt": AATT,
        "root314_precision_failure_preserved": True,
        "official_csv_sha_from_root_helper": CSV_SHA,
        "official_particle_csv_opened_by_source_agent": False,
        "bi4_opened_or_rehashed_by_source_agent": False,
        "stage1_basic_placement": "pending_root_audit",
        "short_solver": "disabled_pending_root_review",
        "full801": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
