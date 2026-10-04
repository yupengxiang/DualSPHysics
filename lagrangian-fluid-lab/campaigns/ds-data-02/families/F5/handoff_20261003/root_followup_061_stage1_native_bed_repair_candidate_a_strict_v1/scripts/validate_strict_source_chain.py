"""Validate F5-061 source provenance and disabled request contracts.

This validator intentionally opens only XML and bounded JSON metadata.  It
does not open BI4, H5, CSV, solver output, or native particle arrays, and it
never invokes GenCase, the solver, or the shared dispatcher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061"
PHYSICAL_CASE_ID = "F5_COMPACT_STILL_WATER_RUNUP_REPAIR_A_V1"
CONDITION_ID = "F5_RUNUP_DP020_EQUILIBRIUM_ROOT050_A_EXPLICIT_CLOSED_MESH"
STRICT_DISPATCH = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    scope = args.scope.resolve()

    binding = load(scope / "physical-binding.json")
    chain = load(scope / "strict-source-chain.json")
    patch = load(scope / "candidate_a_patch.json")
    summary = load(scope / "audit_057_bounded_summary.json")

    for document in (binding, chain, patch):
        require(document["case_id"] == CASE_ID, "case_id is not F5-061")
        require(document["physical_case_id"] == PHYSICAL_CASE_ID, "physical_case_id is stale")
        require(document["condition_id"] == CONDITION_ID, "condition_id is stale")
    require(binding["execution_policy"]["genuine_gencase_required"], "genuine GenCase is not required")
    require(binding["execution_policy"]["fictional_clone_forbidden"], "fictional clone policy is absent")
    require(binding["execution_policy"]["launch_allowed_in_family_scope"] is False, "family launch must remain disabled")

    source = scope / "candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A_Def.xml"
    require(sha256(source) == binding["source_recipe"]["derived_definition_sha256"], "derived Def hash differs")
    xml = ET.parse(source).getroot()
    triangles = xml.find(".//drawtriangles")
    require(triangles is not None, "explicit mesh is missing")
    require(len(triangles.findall("./points/point")) == 156, "explicit point count changed")
    require(len(triangles.findall("./triangles/triangle")) == 52, "explicit triangle count changed")
    text = source.read_text(encoding="utf-8")
    require("drawfilestl" not in text, "candidate A still invokes STL")
    require('shapeout file="continuous_bed"' not in text, "candidate A still emits shapeout")
    require(xml.find(".//clipplane") is not None, "clipplane was changed or removed")

    require(summary["source_arrays_opened_by_this_summary"] is False, "bounded summary opened arrays")
    frame_reports = summary["frame_reports"]
    require([frame["frame"] for frame in frame_reports] == [0, 2, 400], "unexpected audit frames")
    require(all(frame["near_mid_y_strip_count"] == 0 for frame in frame_reports), "mid-y metadata changed")
    require(all(len(frame["bed_segment_bins"]) == 6 for frame in frame_reports), "x segmentation evidence missing")
    require(frame_reports[0]["relative_layer_summary"]["evaluated_layer_min"] == -32, "layer evidence changed")
    require(summary["native_identity"]["bed_support_valid_count"] == 149532, "mk40 cohort evidence changed")

    request_names = ("gencase-request.json", "initial-qa-request.json", "short-event-solver-request.json")
    requests = [load(scope / name) for name in request_names]
    require(all(request["case_id"] == CASE_ID for request in requests), "request case binding is stale")
    require(all(request["physical_case_id"] == PHYSICAL_CASE_ID for request in requests), "request physical binding is stale")
    require(all(request["condition_id"] == CONDITION_ID for request in requests), "request condition binding is stale")
    require(all(request["launch_allowed"] is False for request in requests), "a request is enabled")
    require(requests[0]["kind"] == "cpu" and requests[0]["cpu_task_kind"] == "gencase", "GenCase request kind changed")
    require(requests[1]["kind"] == "cpu" and requests[1]["cpu_task_kind"] == "audit", "QA request kind changed")
    require(requests[2]["kind"] == "qualification", "short event request kind changed")
    require(all(request["genuine_gencase_required"] for request in requests), "genuine GenCase is not bound to every stage")
    require(all(request["fictional_clone_forbidden"] for request in requests), "clone prohibition is not bound to every stage")
    require(all(request["strict_dispatch_entrypoint"] == STRICT_DISPATCH for request in requests), "strict dispatcher binding is stale")
    require(requests[2]["gencase_receipt"].startswith("{gencase_attempt_root}/"), "short-event receipt is not Root-bound")
    require(requests[2]["initial_typed_qa"].startswith("{initial_qa_attempt_root}/"), "short-event QA is not Root-bound")
    require(requests[2]["execution_contract"]["full16_not_authorized"], "full16 authorization was widened")

    print("F5-061 strict source chain validation passed: A only, 156 points/52 triangles, 3 disabled requests")


if __name__ == "__main__":
    main()
