#!/usr/bin/env python3
"""Metadata-only validator for the fresh117 first-24 source pack.

The validator checks source/JSON/XML contracts and disabled gates.  It never
opens or hashes DAT/BI4/H5/CSV/VTK/solver payloads and never launches a task.
"""
from __future__ import annotations

import ast
import hashlib
import json
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
SCIENCE = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
SOURCE = {".json", ".py", ".xml", ".md", ".txt", ".log"}
BASE_MOTION = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-clip-direction-fix-gencase-050/prepared/assets/f5_compact_packet_motion.dat"
BASE_MOTION_SHA = "51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a"
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_LAUNCH_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
TAGS = tuple(f"M{amp:03d}_T{time:03d}" for amp in (85, 95, 105, 115) for time in (80, 90, 100, 120))
SCALES = {"M085": Decimal("0.85"), "M095": Decimal("0.95"), "M105": Decimal("1.05"), "M115": Decimal("1.15")}
TIMES = {"T080": Decimal("0.8"), "T090": Decimal("0.9"), "T100": Decimal("1.0"), "T120": Decimal("1.2")}
FULL_TMAX = Decimal("26.0")
FULL_FRAMES = 1301


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def sha_source(path: Path) -> str:
    require(path.suffix.lower() in SOURCE, f"source hash forbidden for {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tag_values(tag: str) -> tuple[Decimal, Decimal, Decimal]:
    amp = SCALES[tag[:4]]
    scale = TIMES[tag[5:]]
    return amp, scale, Decimal(16) * scale


def dec_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def check_manifest() -> int:
    manifest, _ = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh117-source-manifest.v1", "manifest schema")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "manifest report exclusion")
    require("metadata/fresh117-validator-report.json" not in manifest.get("files", {}), "validator self-reference")
    require(manifest.get("full801_authorized") is False and manifest.get("q_n_granted") is False, "manifest acceptance")
    files = manifest.get("files", {})
    require(isinstance(files, dict), "manifest files")
    for rel, declared in files.items():
        path = PKG / rel
        require(path.is_file(), f"manifest missing file {path}")
        require(path.suffix.lower() in SOURCE, f"science/unsupported package file {path}")
        require(isinstance(declared, str) and len(declared) == 64 and sha_source(path) == declared, f"manifest hash mismatch {rel}")
    return len(files)


def check_closure(request: dict[str, Any], label: str) -> dict[str, int]:
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    provenance = request.get("input_sha256_provenance", {})
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{label}: closure shape")
    static = payload = placeholders = 0
    for raw in files:
        text = str(raw)
        require(text in hashes and text in provenance, f"{label}: closure missing {text}")
        if text.startswith("<root-bind:"):
            require(hashes[text] is None, f"{label}: placeholder hash not null")
            placeholders += 1
            continue
        suffix = Path(text).suffix.lower()
        if suffix in SCIENCE:
            require(suffix == ".dat" and text == BASE_MOTION, f"{label}: unexpected science path {text}")
            require(hashes[text] == BASE_MOTION_SHA, f"{label}: base motion producer SHA")
            require("producer" in str(provenance[text]).lower() and "did not" in str(provenance[text]).lower(), f"{label}: base DAT provenance")
            payload += 1
            continue
        if suffix in SOURCE:
            path = Path(text)
            require(path.is_file(), f"{label}: missing static input {path}")
            require(isinstance(hashes[text], str) and len(hashes[text]) == 64 and sha_source(path) == hashes[text], f"{label}: static hash mismatch {path}")
            static += 1
            continue
        require(hashes[text] is None, f"{label}: executable must remain un-hashed {text}")
    return {"static": static, "producer_dat": payload, "placeholders": placeholders}


def check_parent_inventory() -> dict[str, Any]:
    path = PKG / "metadata/parent-condition-inventory.json"
    inventory, _ = load(path)
    require(inventory.get("schema") == "ds02.f5.c082s1.first24-parent-condition-inventory.fresh117.v1", "parent inventory schema")
    parents = inventory.get("parents", [])
    require(inventory.get("parent_count") == 8 and len(parents) == 8, "parent inventory count")
    require(len({item.get("candidate_id") for item in parents}) == 8, "parent candidate uniqueness")
    require(len({item.get("physical_condition_sha256") for item in parents}) == 8, "parent physical uniqueness")
    require(inventory.get("new_candidate_counts_are_null") is True and inventory.get("new_case_credit") == 0, "parent provenance policy")
    return inventory


def check_request_common(request: dict[str, Any], label: str) -> None:
    require(request.get("schema") == "ds02.runner-request.v2", f"{label}: schema")
    require(request.get("disabled") is True and request.get("launch") is False and request.get("launch_allowed") is False and request.get("execution_allowed") is False, f"{label}: enabled")
    require(request.get("solver_allowed") is False and request.get("conversion_allowed") is False and request.get("arrays_allowed") is False and request.get("shared_registry_write_allowed") is False, f"{label}: policy")
    require(request.get("full801_authorized") is False and request.get("q_n_granted") is False and request.get("independent_case_count_increment") == 0, f"{label}: acceptance")
    require(request.get("root_live_uuid_inventory") is None and request.get("root_shared_gpu_lease") is None and request.get("root_full_launch_approval") is None, f"{label}: Root230 live gate")
    require(request.get("root_inventory_policy_source_sha256") == ROOT230_POLICY_SHA and request.get("root_actual_launch_source_sha256") == ROOT230_LAUNCH_SHA, f"{label}: Root230 source")
    require(request.get("resource_window", {}).get("gpu_hours") == 512 and request.get("resource_window", {}).get("cpu_core_hours") == 3840 and request.get("resource_window", {}).get("qualification_attempts") == 1024 and request.get("resource_window", {}).get("production_attempts") == 720, f"{label}: resource window")
    future = request.get("future_output_hashes", {})
    require(isinstance(future, dict) and all(value is None for value in future.values()), f"{label}: future hashes")


def check_definition(tag: str, owner: dict[str, Any]) -> dict[str, Any]:
    amp, time_scale, motion_end = tag_values(tag)
    path = PKG / "candidates" / tag / f"{CASE}_{tag}_Def.xml"
    root = ET.parse(path).getroot()
    require(root.tag == "case", f"{tag}: DefXML root")
    file_nodes = root.findall(".//mvpredef/file")
    require(len(file_nodes) == 1 and file_nodes[0].get("name") == f"assets/f5_c082s1_motion_{tag.lower()}.dat", f"{tag}: motion asset relative name")
    begin = root.find(".//objreal/begin")
    mv = root.find(".//objreal/mvpredef")
    require(begin is not None and mv is not None, f"{tag}: motion nodes")
    require(Decimal(begin.get("finish", "-1")) == motion_end and Decimal(mv.get("duration", "-1")) == motion_end, f"{tag}: transformed motion endpoint")
    require(root.find(".//setmkbound") is not None, f"{tag}: geometry commands")
    require("c082_closed_analytic_extruded_thick_bed" in ET.tostring(root, encoding="unicode"), f"{tag}: analytic bed marker")
    time_values = [n.get("value") for n in root.findall(".//parameter") if n.get("key") == "TimeMax"]
    require(len(time_values) == 1 and Decimal(time_values[0]) == FULL_TMAX, f"{tag}: full TimeMax")
    out_times = root.findall(".//_outputtime")
    compute_times = root.findall(".//_computetime")
    require(out_times and compute_times and all(Decimal(n.get("end", "-1")) == FULL_TMAX for n in out_times + compute_times), f"{tag}: output window")
    require(owner.get("amplitude_scale") == float(amp) and owner.get("time_scale") == float(time_scale), f"{tag}: owner control")
    require(owner.get("expected_counts") is None and owner.get("native_bed_mk") == 50 and owner.get("source_mkbound") == 40, f"{tag}: owner producer-bound counts")
    return {"definition_sha256": sha_source(path), "motion_end_s": float(motion_end), "full_frames": FULL_FRAMES}


def check_candidate(tag: str) -> dict[str, Any]:
    amp, time_scale, motion_end = tag_values(tag)
    owner_path = PKG / "candidates" / tag / "owner.json"
    owner, owner_sha = load(owner_path)
    physical_path = PKG / "bindings" / f"{tag}-physical-binding.json"
    physical, physical_sha = load(physical_path)
    require(owner["candidate_id"] == f"C082S1_MOTION_{tag}", f"{tag}: candidate ID")
    require(owner["condition_id"].endswith("_117") and owner["physical_case_id"].endswith(tag), f"{tag}: unique IDs")
    require(owner["physical_condition_sha256"] == physical["physical_condition_sha256"], f"{tag}: canonical hash")
    require(physical["owner_source_sha256"] == owner_sha and physical["source_definition_sha256"] == owner["source_definition_sha256"], f"{tag}: owner binding")
    definition = check_definition(tag, owner)
    gencase_binding, _ = load(PKG / "bindings" / f"{tag}-gencase-binding.json")
    require(gencase_binding["actual_counts"] is None and gencase_binding["expected_fluid"] is None, f"{tag}: GenCase counts must be null")
    require(gencase_binding["assets"][0]["source"] == "<root-bind:scaled_motion_output>" and gencase_binding["assets"][0]["sha256"] is None, f"{tag}: future asset binding")
    qa_binding, _ = load(PKG / "bindings" / f"{tag}-initial-qa-mk50-binding.json")
    require(qa_binding["expected_counts"] is None and qa_binding["required_transverse_y_levels"] == 15 and qa_binding["native_bed_marker_mk"] == 50, f"{tag}: QA binding")

    names = {
        "motion": f"requests/{tag}-motion-transform-request.json",
        "gencase": f"requests/{tag}-gencase-request.json",
        "qa": f"requests/{tag}-initial-placement-mk50-request.json",
        "short": f"requests/{tag}-short-native-qualification-request.json",
        "short_bed": f"requests/{tag}-short-dynamic-bed-audit-request.json",
        "full": f"requests/{tag}-full-native-qualification-request.json",
        "full_bed": f"requests/{tag}-full-dynamic-bed-audit-request.json",
    }
    requests = {key: load(PKG / rel)[0] for key, rel in names.items()}
    for key, request in requests.items():
        check_request_common(request, f"{tag} {key}")
        check_closure(request, f"{tag} {key}")
    motion = requests["motion"]
    require(motion.get("kind") == "cpu" and motion.get("cpu_task_kind") == "audit", f"{tag}: motion CPU kind")
    require(motion.get("amplitude_scale") == float(amp) and motion.get("time_scale") == float(time_scale) and motion.get("motion_rows") == 641, f"{tag}: motion scales")
    require(motion.get("motion_output_sha256") is None and motion.get("future_scaled_motion", {}).get("sha256") is None, f"{tag}: motion future hash")
    require(motion["command"][-4:] == ["--amplitude-scale", dec_text(amp), "--time-scale", dec_text(time_scale)], f"{tag}: motion command")
    gencase = requests["gencase"]
    require(gencase.get("kind") == "cpu" and gencase.get("cpu_task_kind") == "gencase" and gencase.get("genuine_gencase_required") is True, f"{tag}: GenCase request")
    require(gencase.get("expected_counts") is None and gencase.get("motion_asset_sha256") is None, f"{tag}: GenCase producer fields")
    qa = requests["qa"]
    require(qa.get("kind") == "cpu" and qa.get("cpu_task_kind") == "audit" and qa.get("expected_counts") is None and qa.get("expected_particles") is None, f"{tag}: QA request")
    require(qa.get("binding_contract", {}).get("no_precision_threshold_relaxation") is True, f"{tag}: precision boundary")
    short = requests["short"]
    require(short.get("kind") == "qualification" and short.get("cpu_task_kind") == "solver" and short.get("tmax_s") == 1.0 and short.get("expected_frames") == 51 and short.get("expected_particles") is None, f"{tag}: short native")
    full = requests["full"]
    require(full.get("kind") == "qualification" and full.get("cpu_task_kind") == "solver" and full.get("tmax_s") == float(FULL_TMAX) and full.get("tout_s") == 0.02 and full.get("expected_frames") == FULL_FRAMES and full.get("expected_particles") is None, f"{tag}: full native")
    require(full.get("full_event_window", {}).get("not_a_slice_of_old_output") is True, f"{tag}: full window semantics")
    require(full.get("upstream_visual_gate") == "WAIT_existing_A080_A120_all801_bed_and_root_visual_review" and full.get("fresh117_full_enablement_requires_root574_complete_case_review") is True, f"{tag}: upstream visual gate")
    short_bed = requests["short_bed"]
    full_bed = requests["full_bed"]
    require(short_bed.get("kind") == "cpu" and short_bed.get("cpu_task_kind") == "audit" and short_bed.get("expected_frames") == 51 and short_bed.get("diagnostic_only") is True, f"{tag}: short bed")
    require(full_bed.get("kind") == "cpu" and full_bed.get("cpu_task_kind") == "audit" and full_bed.get("expected_frames") == FULL_FRAMES and full_bed.get("diagnostic_only") is True, f"{tag}: full bed")
    return {"owner_sha256": owner_sha, "physical_condition_sha256": owner["physical_condition_sha256"], "definition_sha256": definition["definition_sha256"], "motion_end_s": float(motion_end), "requests": {key: hashlib.sha256(json.dumps(requests[key], sort_keys=True).encode()).hexdigest() for key in requests}}


def main() -> int:
    manifest_count = check_manifest()
    source_hashes = {}
    for path in sorted((PKG / "scripts").glob("*.py")) + sorted((PKG / "workers").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        source_hashes[str(path.relative_to(PKG))] = sha_source(path)
    science_files = [str(path.relative_to(PKG)) for path in PKG.rglob("*") if path.is_file() and path.suffix.lower() in SCIENCE]
    require(not science_files, f"science files in source package: {science_files}")
    results = {tag: check_candidate(tag) for tag in TAGS}
    require(len({value["owner_sha256"] for value in results.values()}) == 16, "owner hashes are not unique")
    require(len({value["physical_condition_sha256"] for value in results.values()}) == 16, "physical condition hashes are not unique")
    plan, _ = load(PKG / "metadata/fresh117-source-plan.json")
    parent_inventory = check_parent_inventory()
    require(plan.get("candidate_count") == 16 and plan.get("cartesian_product_complete") is True and plan.get("full801_authorized") is False, "source plan")
    require(plan.get("first24_parent_count") == 8 and plan.get("first24_new_count") == 16 and plan.get("first24_total_count") == 24, "first24 count plan")
    gate = plan.get("upstream_full_native_gate", {})
    require(gate.get("status") == "WAIT" and gate.get("required_current_cases") == ["A080", "A120"] and gate.get("requires_actual_all801_bed_audit") is True and gate.get("requires_root_visual_pass") is True and gate.get("short_window_native_approval_insufficient") is True and gate.get("new_full_native_enablement") is False, "upstream full-native gate")
    require(len({item.get("owner_sha256") for item in plan.get("candidates", [])}) == 16 and len({item.get("physical_condition_sha256") for item in plan.get("candidates", [])}) == 16, "source plan owner/condition uniqueness")
    parent_ids = {item.get("candidate_id") for item in parent_inventory.get("parents", [])}
    require(not parent_ids & {f"C082S1_MOTION_{tag}" for tag in TAGS}, "new candidate duplicates parent")
    report = {
        "schema": "ds02.f5.c082s1.fresh117-source-validator-report.v1",
        "status": "passed_sixteen_unique_amplitude_time_first24_disabled_contract",
        "manifest_source_files": manifest_count,
        "candidates": results,
        "source_hashes": source_hashes,
        "all_expected_counts_null": True,
        "full_event_window_s": [0.0, float(FULL_TMAX)],
        "full_event_frames": FULL_FRAMES,
        "exact_dp_lattice_negative_retained": True,
        "historical_A_B_penetration_failures_retained": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "source_only": True,
    }
    (PKG / "metadata/fresh117-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidate_count": 16, "first24_total_count": 24, "science_payloads_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
