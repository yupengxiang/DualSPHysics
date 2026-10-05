#!/usr/bin/env python3
"""Source-only contract validator for F5 fresh118.

It checks the actual registered CPU argv/schema contracts and disabled gates. It
never opens or hashes DAT, BI4, H5, CSV, VTK, solver output, or any other
scientific payload, and it never launches a task.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

PKG = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
PYTHON = LAB / ".venv/bin/python"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
ROOT230 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
POLICY = ROOT230 / "root_native_home_floor_inventory_policy.py"
LAUNCH = ROOT230 / "launch.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
GENCASE_WORKER = LAB / "campaigns/ds-data-02/handoff_20261003/root_native_source_preflight_tools_003/gencase.py"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
QA_WRAPPER = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualGen426_two_registered_initialQA_fresh103_441/export_then_fresh103_placement_qa.py"
QA_WORKER = LAB / "campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1/workers/initial_placement_mk50_audit.py"
BASE_MOTION = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-clip-direction-fix-gencase-050/prepared/assets/f5_compact_packet_motion.dat"
BASE_MOTION_SHA = "51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a"
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_LAUNCH_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
STATIC = {".json", ".py", ".xml", ".md", ".txt", ".log"}
SCIENCE = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
TAGS = tuple(f"M{amp:03d}_T{time:03d}" for amp in (85, 95, 105, 115) for time in (80, 90, 100, 120))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hash(path: Path) -> str:
    require(path.suffix.lower() in STATIC, f"science or unsupported hash requested: {path}")
    return sha(path)


def check_manifest() -> int:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh118-cpu-contract-source-manifest.v1", "manifest schema")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "validator exclusion")
    require("metadata/fresh118-validator-report.json" not in manifest.get("files", {}), "validator self-reference")
    files = manifest.get("files")
    require(isinstance(files, dict), "manifest files")
    for rel, declared in files.items():
        path = PKG / rel
        require(path.is_file(), f"manifest file missing: {path}")
        require(path.suffix.lower() in STATIC, f"manifest science/unsupported file: {path}")
        require(isinstance(declared, str) and len(declared) == 64 and source_hash(path) == declared, f"manifest hash mismatch: {rel}")
    return len(files)


def check_closure(request: dict, label: str) -> dict[str, int]:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    provenance = request.get("input_sha256_provenance")
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{label}: closure shape")
    static = placeholders = producer_dat = binaries = 0
    for raw in files:
        raw = str(raw)
        require(raw in hashes and raw in provenance, f"{label}: closure missing {raw}")
        if raw.startswith("<root-bind:"):
            require(hashes[raw] is None, f"{label}: future placeholder hash must be null")
            placeholders += 1
            continue
        path = Path(raw)
        suffix = path.suffix.lower()
        if suffix == ".dat":
            require(raw == BASE_MOTION and hashes[raw] == BASE_MOTION_SHA, f"{label}: only registered base motion DAT is permitted")
            require("producer" in str(provenance[raw]).lower() and "did not" in str(provenance[raw]).lower(), f"{label}: base DAT provenance")
            producer_dat += 1
            continue
        require(suffix not in SCIENCE, f"{label}: scientific payload path in source closure: {raw}")
        require(path.is_file(), f"{label}: static/binary input missing: {path}")
        if suffix in STATIC:
            require(isinstance(hashes[raw], str) and len(hashes[raw]) == 64 and source_hash(path) == hashes[raw], f"{label}: static source hash mismatch: {path}")
            static += 1
        else:
            require(hashes[raw] is None, f"{label}: executable hash must remain source-null: {path}")
            binaries += 1
    return {"static": static, "producer_dat": producer_dat, "placeholders": placeholders, "binaries": binaries}


def check_common(req: dict, label: str) -> None:
    require(req.get("schema") == "ds02.runner-request.v2", f"{label}: runner schema")
    require(req.get("kind") in {"cpu", "qualification"}, f"{label}: kind")
    require(req.get("worktree_root") == str(INTEGRATION), f"{label}: runtime worktree_root")
    require(req.get("cwd") in {str(LAB), "<root-bind:gencase_prepared_root>"}, f"{label}: cwd")
    require(req.get("disabled") is True and req.get("launch") is False and req.get("launch_allowed") is False and req.get("execution_allowed") is False, f"{label}: disabled gate")
    require(req.get("solver_allowed") is False and req.get("conversion_allowed") is False and req.get("arrays_allowed") is False and req.get("shared_registry_write_allowed") is False, f"{label}: policy gate")
    require(req.get("full801_authorized") is False and req.get("q_n_granted") is False and req.get("independent_case_count_increment") == 0, f"{label}: acceptance gate")
    require(req.get("root_inventory_policy_source_sha256") == ROOT230_POLICY_SHA and req.get("root_actual_launch_source_sha256") == ROOT230_LAUNCH_SHA, f"{label}: Root230 source hashes")
    resource = req.get("resource_window", {})
    require(resource.get("gpu_hours") == 512 and resource.get("cpu_core_hours") == 3840 and resource.get("qualification_attempts") == 1024 and resource.get("production_attempts") == 720, f"{label}: resource window")
    future = req.get("future_output_hashes", {})
    require(isinstance(future, dict) and all(value is None for value in future.values()), f"{label}: future output hash must be null")
    check_closure(req, label)


def check_initial_binding(tag: str, path: Path, gencase_attempt: str, qa_attempt: str) -> dict:
    binding = load(path)
    require(binding.get("schema") == "ds02.f5.c082s1.stage1-placement-mk50-binding.fresh103.v1", f"{tag}: exact initial QA worker schema")
    require(binding.get("case_id") == CASE and binding.get("qa_attempt_id") == qa_attempt and binding.get("gencase_attempt_id") == gencase_attempt, f"{tag}: separate QA/GenCase identities")
    require(binding.get("actual_counts") is None and binding.get("dimension") == 3, f"{tag}: candidate counts must remain null/3D")
    require(binding.get("source_mkbound") == 40 and binding.get("native_bed_mk") == 50, f"{tag}: Mk mapping")
    precision = binding.get("numerical_precision", {})
    require(precision.get("diagnostic_only") is True and precision.get("accepted_as_stage1_placement_gate") is False and precision.get("exact_dp_lattice_threshold") == 1e-6, f"{tag}: precision boundary")
    files = binding.get("files", {})
    required = ("actual_gencase_binding", "gencase_receipt", "prepared_input_report", "generated_xml", "generated_bi4", "official_particle_csv", "gencase_output_root")
    require(set(required) <= set(files), f"{tag}: initial QA files contract")
    for key in required:
        require(files[key].get("path", "").startswith("<root-bind:") and files[key].get("sha256") is None, f"{tag}: future binding placeholder {key}")
    return binding


def check_tag(tag: str) -> dict:
    reqdir = PKG / "requests"
    bindir = PKG / "bindings"
    defn = PKG / "candidates" / tag / f"{CASE}_{tag}_Def.xml"
    owner = load(PKG / "candidates" / tag / "owner.json")
    physical = load(bindir / f"{tag}-physical-binding.json")
    motion = load(reqdir / f"{tag}-motion-transform-request.json")
    gencase = load(reqdir / f"{tag}-gencase-request.json")
    qa = load(reqdir / f"{tag}-initial-placement-mk50-request.json")
    short = load(reqdir / f"{tag}-short-native-qualification-request.json")
    full = load(reqdir / f"{tag}-full-native-qualification-request.json")
    short_bed = load(reqdir / f"{tag}-short-dynamic-bed-audit-request.json")
    full_bed = load(reqdir / f"{tag}-full-dynamic-bed-audit-request.json")
    for label, req in (("motion", motion), ("gencase", gencase), ("initial-qa", qa), ("short", short), ("full", full), ("short-bed", short_bed), ("full-bed", full_bed)):
        check_common(req, f"{tag} {label}")
        require(req.get("candidate_id") == f"C082S1_MOTION_{tag}" and req.get("physical_condition_sha256") == physical.get("physical_condition_sha256"), f"{tag} {label}: identity")
    require(motion.get("kind") == "cpu" and motion.get("cpu_task_kind") == "audit" and motion["command"][:2] == [str(PYTHON), str(PKG / "workers/transform_motion.py")], f"{tag}: motion worker argv")
    require(motion["command"][-4:] == ["--amplitude-scale", str(motion["amplitude_scale"]), "--time-scale", str(motion["time_scale"])], f"{tag}: motion scale argv")
    require(motion.get("motion_output_sha256") is None and motion.get("future_scaled_motion", {}).get("sha256") is None, f"{tag}: motion future hash")
    require(gencase.get("kind") == "cpu" and gencase.get("cpu_task_kind") == "gencase" and gencase.get("genuine_gencase_required") is True, f"{tag}: GenCase CPU contract")
    require(gencase["command"][:2] == [str(PYTHON), str(GENCASE_WORKER)] and gencase["command"][2:4] == ["--binding", gencase["binding"]] and gencase["command"][-2:] == ["--output-dir", "{attempt_root}/prepared"], f"{tag}: GenCase worker argv")
    gb = load(bindir / f"{tag}-gencase-binding.json")
    require(gb.get("actual_counts") is None and gb.get("expected_fluid") is None and gb.get("assets", [{}])[0].get("source") == "<root-bind:scaled_motion_output>" and gb.get("assets", [{}])[0].get("sha256") is None, f"{tag}: GenCase binding future fields")
    require(qa.get("kind") == "cpu" and qa.get("cpu_task_kind") == "audit", f"{tag}: initial QA CPU contract")
    require(qa["command"] == [str(PYTHON), str(QA_WRAPPER), "--binding", qa["binding"], "--partvtk", str(PARTVTK), "--audit-worker", str(QA_WORKER), "--output-dir", "{attempt_root}/initial-qa"], f"{tag}: initial QA wrapper argv")
    check_initial_binding(tag, bindir / f"{tag}-initial-qa-mk50-binding.json", gencase["attempt_id"], qa["attempt_id"])
    require(qa.get("expected_counts") is None and qa.get("expected_particles") is None, f"{tag}: initial QA counts must be null")
    require(short.get("kind") == "qualification" and short.get("cpu_task_kind") == "solver" and short.get("expected_particles") is None, f"{tag}: short template")
    require(full.get("kind") == "qualification" and full.get("cpu_task_kind") == "solver" and full.get("expected_particles") is None and full.get("tmax_s") == 26.0 and full.get("expected_frames") == 1301, f"{tag}: full template")
    require(full.get("upstream_visual_gate") == "WAIT_existing_A080_A120_all801_bed_and_root_visual_review" and full.get("fresh117_full_enablement_requires_root574_complete_case_review") is True, f"{tag}: full WAIT gate")
    require(short_bed.get("kind") == "cpu" and short_bed.get("cpu_task_kind") == "audit" and short_bed.get("expected_frames") == 51, f"{tag}: short bed template")
    require(full_bed.get("kind") == "cpu" and full_bed.get("cpu_task_kind") == "audit" and full_bed.get("expected_frames") == 1301, f"{tag}: full bed template")
    return {"physical_condition_sha256": physical["physical_condition_sha256"], "owner_sha256": sha(PKG / "candidates" / tag / "owner.json"), "definition_sha256": sha(defn)}


def main() -> int:
    manifest_count = check_manifest()
    require(PKG.name.startswith("root_followup_118"), "fresh118 package identity")
    local_py = list((PKG / "scripts").glob("*.py")) + list((PKG / "workers").glob("*.py"))
    for path in local_py:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    science_files = [str(path.relative_to(PKG)) for path in PKG.rglob("*") if path.is_file() and path.suffix.lower() in SCIENCE]
    require(not science_files, f"science file in package: {science_files}")
    results = {tag: check_tag(tag) for tag in TAGS}
    require(len({row["physical_condition_sha256"] for row in results.values()}) == 16, "physical conditions are not unique")
    plan = load(PKG / "metadata/fresh118-source-plan.json")
    require(plan.get("candidate_count") == 16 and plan.get("full801_authorized") is False and plan.get("q_n_granted") is False, "source plan gate")
    gate = plan.get("upstream_full_native_gate", {})
    require(gate.get("status") == "WAIT" and gate.get("required_current_cases") == ["A080", "A120"] and gate.get("requires_actual_all801_bed_audit") is True and gate.get("requires_root_visual_pass") is True and gate.get("new_full_native_enablement") is False, "upstream full-native gate")
    guidance = load(PKG / "metadata/fresh118-enable-guidance.json")
    require(guidance.get("future_payload_hashes_are_null") is True and guidance.get("counts_are_null_until_each_own_gencase_report") is True, "enable guidance future fields")
    audit = load(PKG / "metadata/fresh118-contract-audit.json")
    require(audit.get("not_changed") and audit.get("source_agent_did_not_read_or_hash_science_payloads") is True, "contract audit provenance")
    report = {
        "schema": "ds02.f5.c082s1.fresh118-cpu-contract-validator-report.v1",
        "status": "passed_true_motion_gencase_initial_qa_cpu_contract_all_disabled",
        "manifest_source_files": manifest_count,
        "candidate_count": 16,
        "results": results,
        "runtime_source_sha256": sha(RUNTIME),
        "strict_source_sha256": sha(STRICT),
        "motion_worker_sha256": sha(PKG / "workers/transform_motion.py"),
        "gencase_worker_sha256": sha(GENCASE_WORKER),
        "initial_qa_wrapper_sha256": sha(QA_WRAPPER),
        "initial_qa_worker_sha256": sha(QA_WORKER),
        "worktree_root_present_on_all_requests": True,
        "future_motion_hashes_null": True,
        "future_generated_counts_null": True,
        "full801_gate": "WAIT",
        "exact_dp_lattice_negative_retained": True,
        "historical_A_B_penetration_failures_retained": True,
        "science_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "source_only": True,
    }
    (PKG / "metadata/fresh118-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidate_count": 16, "science_payloads_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
