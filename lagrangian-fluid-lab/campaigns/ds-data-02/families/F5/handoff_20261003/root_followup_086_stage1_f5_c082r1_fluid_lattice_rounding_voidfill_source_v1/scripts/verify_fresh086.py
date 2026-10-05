#!/usr/bin/env python3
"""Static fresh086 contract checks; no scientific arrays or jobs are opened."""
from __future__ import annotations

import ast
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD_SOURCE = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_085_stage1_f5_c082r1_gencase_lattice_source_diagnostic_v1/candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082R1_Def.xml")
SOURCE_ANALYSIS = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_085_stage1_f5_c082r1_gencase_lattice_source_diagnostic_v1/source-draw-order-analysis.json")
CURRENT_SOURCE_ANALYSIS_SHA = "d1726c08a9085b4bd84f62664a38ed98eedfd02063e56700a74a061e2019fbec"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commands_without_fluid(root: ET.Element) -> list[str]:
    main = root.find("./casedef/geometry/commands/mainlist")
    require(main is not None, "mainlist missing")
    return [ET.tostring(node, encoding="unicode") for node in main if node.tag not in {"drawbox", "fillbox"} or node.attrib.get("cmt") not in {"initial_fluid_equilibrium_cell_centres_dp020", "official_void_fill_candidate_same_fluid_window"}]


def main() -> None:
    binding = load("fluid-lattice-text-diagnostic-binding.json")
    request = load("fluid-lattice-text-diagnostic-request.json")
    candidate_binding = load("candidate-gencase-binding.json")
    candidate_request = load("candidate-gencase-request.json")
    comparison = load("candidate-source-comparison.json")
    disabled = load("downstream-disabled.json")

    require(binding["schema"] == "ds02.f5.c082r1.fluid-lattice-text-rounding-binding.fresh086.v1", "diagnostic binding schema")
    require(binding.get("attempt_id") == "root-stage1-f5-c082r1-fluid-lattice-text-rounding-occupancy-diagnostic-257", "worker attempt_id binding")
    require(binding["actual_root256"]["report_sha256"] == "22ca07e1b92fedba878722f7a99079f118fac3084e2ca26f9f9787c0722e8113", "Root256 report hash")
    require(binding["actual_root256"]["official_csv_sha256"] == "a1165d9d1d6645f22774eb57c6be0a236b1fbba90f46577cc2ab3fa51d2abfb8", "Root CSV opaque hash")
    require(binding["actual_root256"]["source_report_is_prior_metadata_only"] is True, "Root256 report source role")
    require(request["launch_allowed"] is False and request["execution_allowed"] is False, "fluid diagnostic enabled")
    require(request["arrays_allowed"] is False and request["bi4_h5_read_allowed"] is False, "fluid diagnostic array policy")
    require(request["input_sha256"].get(str(SOURCE_ANALYSIS)) == CURRENT_SOURCE_ANALYSIS_SHA, "current source analysis hash not bound")
    require("42702d6ef95f1b5d6f286337c9e681c4049d145aac04badbbf8443661ae36709" not in json.dumps(request, sort_keys=True), "stale source hash reused")
    require(request["input_sha256"].get(binding["actual_root256"]["official_csv"]) == binding["actual_root256"]["official_csv_sha256"], "CSV opaque hash mismatch")
    diagnostic_worker = ROOT / "workers" / "diagnose_r1_fluid_lattice_text_rounding.py"
    diagnostic_binding = ROOT / "fluid-lattice-text-diagnostic-binding.json"
    require(request["input_sha256"].get(str(diagnostic_worker)) == sha(diagnostic_worker), "diagnostic worker hash not bound")
    require(request["input_sha256"].get(str(diagnostic_binding)) == sha(diagnostic_binding), "diagnostic binding hash not bound")
    require(disabled["all_downstream_disabled"] is True, "downstream stage enabled")

    require(candidate_binding["schema"] == "ds02.f5.c082r1.void-fill-genuine-gencase-binding.fresh086.v1", "candidate binding schema")
    require(candidate_binding["expected_fluid"] is None, "candidate fluid count was predicted")
    require(candidate_binding["execution_policy"]["launch_allowed"] is False and candidate_binding["execution_policy"]["execution_allowed"] is False, "candidate GenCase enabled")
    require(candidate_request["cpu_task_kind"] == "gencase" and candidate_request["genuine_gencase"] is True, "candidate is not genuine GenCase")
    require(candidate_request["launch_allowed"] is False and candidate_request["execution_allowed"] is False, "candidate request enabled")
    require(candidate_request["input_sha256"].get(str(SOURCE_ANALYSIS)) == CURRENT_SOURCE_ANALYSIS_SHA, "candidate request stale source hash")
    candidate_source = ROOT / "candidate_source" / "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082R1_VOID_FILL_Def.xml"
    candidate_binding_path = ROOT / "candidate-gencase-binding.json"
    require(candidate_request["input_sha256"].get(str(candidate_source)) == sha(candidate_source), "candidate source hash not bound")
    require(candidate_request["input_sha256"].get(str(candidate_binding_path)) == sha(candidate_binding_path), "candidate binding hash not bound")
    require(candidate_request["full16_authorized"] is False and candidate_request["full801_authorized"] is False, "candidate downstream authorization")
    require(comparison["decision_boundary"]["candidate_success"] is False and comparison["decision_boundary"]["candidate_fluid_count_is_not_predicted"] is True, "candidate success/count claim")

    old_root = ET.parse(OLD_SOURCE).getroot()
    candidate_path = candidate_source
    candidate_root = ET.parse(candidate_path).getroot()
    require(sha(OLD_SOURCE) == comparison["old_source"]["sha256"], "old source hash changed")
    require(sha(candidate_path) == comparison["prospective_candidate"]["sha256"], "candidate source hash changed")
    require(commands_without_fluid(old_root) == commands_without_fluid(candidate_root), "candidate changed non-fluid geometry/control")
    old_main = old_root.find("./casedef/geometry/commands/mainlist")
    new_main = candidate_root.find("./casedef/geometry/commands/mainlist")
    require(old_main is not None and new_main is not None, "mainlist missing")
    old_fluid = next(node for node in old_main if node.tag == "drawbox" and node.attrib.get("cmt") == "initial_fluid_equilibrium_cell_centres_dp020")
    new_fluid = next(node for node in new_main if node.tag == "fillbox" and node.attrib.get("cmt") == "official_void_fill_candidate_same_fluid_window")
    require(ET.tostring(old_fluid.find("point"), encoding="unicode") == ET.tostring(new_fluid.find("point"), encoding="unicode"), "fluid point changed")
    require(ET.tostring(old_fluid.find("size"), encoding="unicode") == ET.tostring(new_fluid.find("size"), encoding="unicode"), "fluid size changed")
    require(new_fluid.findtext("modefill") == "void", "official void mode missing")
    require(new_fluid.attrib.get("x") == "1.010" and new_fluid.attrib.get("y") == "0.000" and new_fluid.attrib.get("z") == "0.030", "candidate interior seed changed")

    worker = diagnostic_worker
    tree = ast.parse(worker.read_text(encoding="utf-8"), filename=str(worker))
    imported = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported.update(alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    require(imported <= {"__future__", "argparse", "csv", "hashlib", "json", "math", "statistics", "struct", "collections", "decimal", "pathlib", "xml"}, f"non-stdlib worker import: {sorted(imported)}")
    source = worker.read_text(encoding="utf-8")
    require("subprocess" not in imported and "Popen" not in source, "worker invokes a process")
    for phrase in ("float32_exact_binary64", "text_rounding_half_step_bound_m", "strict_vs_native_occupancy", "contact_distance_envelope", "native_type0_mk50_support", "no_gap_fill_or_coordinate_transform"):
        require(phrase in source or phrase in json.dumps(load("fluid-lattice-text-diagnostic-binding.json")), f"worker contract missing: {phrase}")

    print(json.dumps({"status": "fresh086_source_contract_pass", "candidate_enabled": False, "fluid_diagnostic_enabled": False, "arrays_opened": False, "jobs_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
