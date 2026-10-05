#!/usr/bin/env python3
"""Build disabled Root230 native requests gated by fresh092 QA.

The builder consumes Root444 GenCase JSON/XML evidence and the fresh092
source requests. It hashes JSON, XML, Python and the approved solver binary;
it never opens, hashes, copies or decodes BI4/H5/VTK/CSV payloads and never
launches a process. Raw GenCase receipts remain immutable inputs. The native
requests are disabled until Root completes the matching fresh092 initial QA
and separately verifies the saved frame-0 velocity audit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
PACKAGE = Path(__file__).resolve().parent
FRESH091 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_091_stage1_f4_first24_coverage_audit_v1"
F4_FAMILY = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4"
FRESH092 = PACKAGE.parent / "root_followup_092_stage1_f4_actual_gencase_root237_initial_qa_bind_v1"
FRESH092_MANIFEST = FRESH092 / "F4_STAGE1_FRESH092_ACTUAL_GENCASE_ROOT237_INITIAL_QA_BIND_MANIFEST.json"
FRESH092_PLAN = FRESH092 / "metadata/fresh092-actual-gencase-plan.json"
FRESH092_BINDING = FRESH092 / "metadata/fresh092-actual-gencase-binding.json"
FRESH092_INTERFACE = FRESH092 / "metadata/root237-interface-contract.json"
FRESH092_WORKER = FRESH092 / "workers/run_f4_fresh092_native_initial_qa_root237.py"
FRESH094 = PACKAGE.parent / "root_followup_094_stage1_f4_basic_native_input_qa_v1"
FRESH094_MANIFEST = FRESH094 / "F4_STAGE1_FRESH094_BASIC_NATIVE_INPUT_QA_MANIFEST.json"
ROOT444 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_fresh091_first24_registered_genuine_GenCase_444"
ROOT444_REVIEW = ROOT444 / "actual-root-GenCase-first24-enable-review.json"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_GPU = ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64").resolve()
SCOPE_ID = "F4_STAGE1_FIRST24_FRESH092_QA_TO_ROOT230_NATIVE_V1"
FRESH092_COMMIT = "77bf479761b182d7a3ffab39fba0bb1894e4c20d"
ROOT230_PROFILE = "root_live_all_idle_uuid_leased_eight_solver_v2"
ROOT230_DATASET_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"
ROOT230_EFFECTIVE_RESERVATION_SHA = "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
ROOT230_HOME_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_ENTRY_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
ROOT230_GPU_SHA = "4e6f340222f7823ae9df1a145ccda884dcf401c9740fc78c51a88066ae1c88cd"
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
STATIC_SUFFIXES = {".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log", ".linux64", ""}
HEX = set("0123456789abcdef")


def load(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific payload cannot be loaded as metadata: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"metadata object required: {path}")
    return value


def sha(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific payload hash refused: {path}")
    if path != SOLVER and path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"static input required: {path}")
    if not path.is_file():
        raise ValueError(f"static input required: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def unique(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def verify_root230() -> dict[str, Any]:
    for path in (ROOT230_ENTRY, ROOT230_HOME, ROOT230_GPU, ROOT230_CONTRACT, RUNTIME, STRICT, RESOURCE, SOLVER):
        if not path.is_file():
            raise FileNotFoundError(path)
    contract = load(ROOT230_CONTRACT)
    refs = {"entry": ref(ROOT230_ENTRY), "home_policy": ref(ROOT230_HOME), "gpu_policy": ref(ROOT230_GPU), "contract": ref(ROOT230_CONTRACT), "runtime": ref(RUNTIME), "strict": ref(STRICT), "resource_window": ref(RESOURCE), "solver": ref(SOLVER)}
    if contract.get("schema") != "ds02.root.native-home-floor-policy.v1":
        raise ValueError("Root230 contract schema drift")
    if contract.get("entry_sha256") != refs["entry"]["sha256"] or contract.get("new_policy_sha256") != refs["home_policy"]["sha256"]:
        raise ValueError("Root230 contract digest drift")
    if refs["entry"]["sha256"] != ROOT230_ENTRY_SHA or refs["home_policy"]["sha256"] != ROOT230_HOME_SHA or refs["gpu_policy"]["sha256"] != ROOT230_GPU_SHA:
        raise ValueError("Root230 reviewed source digest drift")
    if contract.get("runtime_file_unchanged") is not True or contract.get("source_only_no_jobs_started") is not True:
        raise ValueError("Root230 source policy does not preserve runtime/source-only guards")
    gpu_text = ROOT230_GPU.read_text(encoding="utf-8")
    if "root_live_all_idle_uuid_leased_eight_solver_v2" not in gpu_text:
        raise ValueError("Root230 GPU profile drift")
    return {"profile": ROOT230_PROFILE, "dataset_inventory_profile": ROOT230_DATASET_PROFILE, "effective_reservation_function_sha256": ROOT230_EFFECTIVE_RESERVATION_SHA, "references": refs, "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "solver_concurrency_cap": 8}


def xml_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    particles = root.find("execution/particles")
    if particles is None:
        raise ValueError(f"XML lacks execution/particles: {path}")
    total = int(particles.attrib["np"])
    fixed = int(particles.attrib["nb"])
    fluid = sum(int(node.attrib["count"]) for node in particles.findall("fluid"))
    if total <= 0 or fixed <= 0 or fluid <= 0 or total != fixed + fluid:
        raise ValueError(f"XML counts do not close: {path}")
    return {"total": total, "fixed": fixed, "fluid": fluid, "moving": 0, "floating": 0}


def verify_physical(owner: dict[str, Any], plan_row: dict[str, Any]) -> None:
    geometry = owner.get("geometry", {})
    for name in ("tank", "drop", "pool"):
        box = geometry.get(name)
        if not isinstance(box, dict) or any(float(v) <= 0 for v in box.get("size_m", [])):
            raise ValueError(f"{plan_row['endpoint_id']}: invalid finite {name} geometry")
    params = owner.get("parameters", {})
    for key in ("gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s"):
        if key not in params:
            raise ValueError(f"{plan_row['endpoint_id']}: missing physical parameter {key}")
    velocity = owner.get("initial_state", {}).get("velocities_m_per_s", {})
    speed = float(params["speed_m_per_s"])
    if velocity.get("mkfluid:1") != [0.0, 0.0, -speed] or velocity.get("mkfluid:0") != [0.0, 0.0, 0.0]:
        raise ValueError(f"{plan_row['endpoint_id']}: initial velocity/vertical-speed drift")
    recipe = owner.get("solver_recipe", {})
    if float(recipe.get("dp_m")) != 0.01 or float(recipe.get("time_max_s")) != 1.2 or float(recipe.get("time_out_s")) != 0.001 or int(recipe.get("native_frame_count")) != 1201:
        raise ValueError(f"{plan_row['endpoint_id']}: native recipe drift")
    if recipe.get("no_mdbc") is not True or recipe.get("no_forcing") is not True:
        raise ValueError(f"{plan_row['endpoint_id']}: forcing/mDBC policy drift")


def verify_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = load(FRESH092_MANIFEST)
    plan = load(FRESH092_PLAN)
    binding = load(FRESH092_BINDING)
    review = load(ROOT444_REVIEW)
    if manifest.get("actual_gencase_completed0") != 24 or manifest.get("case_count") != 24:
        raise ValueError("fresh092 actual GenCase manifest drift")
    if plan.get("actual_source_commit") != "ab2503d9" or plan.get("case_count") != 24:
        raise ValueError("fresh092 source provenance drift")
    if review.get("actual_source_commit") != "ab2503d9" or review.get("actual_strict_metadata_preflight24_pass") is not True or review.get("exact_finite_drop_physical_tuples") != 24:
        raise ValueError("Root444 review drift")
    rows = binding.get("per_case_actual_gencase_receipts")
    if not isinstance(rows, list) or len(rows) != 24:
        raise ValueError("fresh092 producer rows are not 24")
    return manifest, plan, binding, review, {str(row["endpoint_id"]): row for row in rows}


def build() -> dict[str, Any]:
    output = PACKAGE.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest, plan, binding, review, binding_rows = verify_sources()
    plan_rows = {str(row["endpoint_id"]): row for row in plan["cases"]}
    if set(plan_rows) != set(binding_rows) or len(plan_rows) != 24:
        raise ValueError("fresh092 plan/producer endpoint set drift")
    root230 = verify_root230()
    cases: list[dict[str, Any]] = []
    semantic_rows: list[dict[str, Any]] = []
    physical_tuples: set[tuple[Any, ...]] = set()
    for case_id in sorted(plan_rows):
        endpoint = plan_rows[case_id]
        row = binding_rows[case_id]
        owner_path = Path(str(endpoint["owner_path"]))
        owner = load(owner_path)
        verify_physical(owner, endpoint)
        receipt_path = Path(str(row["gencase_receipt"]["path"]))
        report_path = Path(str(row["prepared_input_report"]["path"]))
        xml_path = Path(str(row["generated_xml"]["path"]))
        bi4_path = Path(str(row["generated_bi4"]["path"]))
        receipt = load(receipt_path)
        report = load(report_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{case_id}: raw GenCase receipt is not completed/0")
        if receipt.get("solver_dimension_from_gencase") != 3 or not isinstance(receipt.get("total_particles"), int) or not isinstance(receipt.get("fluid_particles"), int) or receipt["total_particles"] <= 0 or receipt["fluid_particles"] <= 0 or receipt["fluid_particles"] >= receipt["total_particles"]:
            raise ValueError(f"{case_id}: raw GenCase semantic fields are invalid")
        if row.get("solver_dimension_from_gencase") != 3 or row.get("returncode") != 0:
            raise ValueError(f"{case_id}: producer binding semantic fields are invalid")
        if int(row["total_particles"]) != receipt["total_particles"] or int(row["fluid_particles"]) != receipt["fluid_particles"]:
            raise ValueError(f"{case_id}: producer/receipt count mismatch")
        if not valid_sha(row["generated_bi4"]["producer_sha256"]) or row["generated_bi4"].get("content_rehashed_by_source") is not False:
            raise ValueError(f"{case_id}: BI4 producer attestation invalid")
        if not bi4_path.is_file():
            raise FileNotFoundError(f"{case_id}: registered BI4 path missing")
        xml_sha = sha(xml_path)
        counts = xml_counts(xml_path)
        if xml_sha != row["generated_xml"].get("producer_sha256") or xml_sha != row["generated_xml"].get("observed_xml_sha256"):
            raise ValueError(f"{case_id}: generated XML digest drift")
        report_counts = report.get("generated_xml_particle_counts", {})
        if report.get("actual_total_particles") != receipt["total_particles"] or int(report_counts.get("fixed", -1)) != counts["fixed"] or int(report_counts.get("fluid", -1)) != counts["fluid"] or counts["total"] != receipt["total_particles"]:
            raise ValueError(f"{case_id}: prepared report/XML/receipt count closure")
        constants = report.get("actual_generated_constants", {})
        data2d = str(constants.get("data2d", {}).get("value", "")).lower()
        if data2d != "false":
            raise ValueError(f"{case_id}: actual prepared report is not data2d=false")
        if report.get("xml_sha256") != xml_sha or report.get("bi4_sha256") != row["generated_bi4"]["producer_sha256"]:
            raise ValueError(f"{case_id}: producer report digest closure")
        qa_request = FRESH092 / "requests" / f"{case_id}-initial-native-qa-disabled.request.json"
        if not qa_request.is_file():
            raise FileNotFoundError(qa_request)
        qa = load(qa_request)
        physical_tuples.add((owner["parameters"]["gap_m"], owner["parameters"]["x_offset_m"], owner["parameters"]["y_offset_m"], owner["parameters"]["speed_m_per_s"]))
        semantic_rows.append({"case_id": case_id, "raw_receipt": {"path": str(receipt_path), "sha256": sha(receipt_path), "status": receipt["status"], "returncode": receipt["returncode"], "solver_dimension_from_gencase": receipt["solver_dimension_from_gencase"], "total_particles": receipt["total_particles"], "fluid_particles": receipt["fluid_particles"]}, "prepared_report": {"path": str(report_path), "sha256": sha(report_path), "actual_total_particles": report["actual_total_particles"], "generated_xml_particle_counts": report_counts, "data2d": False, "data2d_source": "prepared_report.actual_generated_constants.data2d", "bi4_sha256": report["bi4_sha256"]}, "generated_xml": {"path": str(xml_path), "sha256": xml_sha, "counts": counts}, "generated_bi4": {"path": str(bi4_path), "producer_sha256": row["generated_bi4"]["producer_sha256"], "source_read_or_hashed": False}, "semantic_adapter_needed": False, "raw_receipt_unchanged": True, "semantic_claim": "Raw receipt supplies actual 3D/total/fluid; prepared report supplies actual data2d=false and fixed partition. No raw receipt patch or fabricated count is emitted."})
        cases.append({"case_id": case_id, "endpoint": endpoint, "owner": owner, "owner_path": owner_path, "receipt": receipt, "receipt_path": receipt_path, "report": report, "report_path": report_path, "xml_path": xml_path, "xml_sha": xml_sha, "bi4_path": bi4_path, "bi4_sha": row["generated_bi4"]["producer_sha256"], "counts": counts, "qa_request": qa_request, "qa": qa})
    if len(physical_tuples) != 24:
        raise ValueError("physical condition tuples are not 24 distinct cases")
    root230_path = output / "metadata/root230-contract.json"
    semantic_path = output / "metadata/gencase-semantic-evidence.json"
    native_plan_path = output / "metadata/fresh093-native-plan.json"
    preserved_path = output / "evidence/preserved-source092-and-visual-anchors.json"
    qa_gate_path = output / "metadata/fresh092-qa-consumer-gate.json"
    dump(root230_path, {"schema": "ds02.f4.fresh093.root230-contract.v1", "root230": root230, "cpu142_policy_included": False, "source_only": True, "claim_boundary": "Root230 dispatch contract only; no native launch or qualification claim."})
    dump(semantic_path, {"schema": "ds02.f4.fresh093.gencase-semantic-evidence.v1", "source_only": True, "case_count": 24, "raw_receipts_unchanged": True, "semantic_adapter_needed": False, "rows": semantic_rows, "scientific_payloads_opened_or_hashed": False, "claim_boundary": "Actual Root444 GenCase semantic evidence only; no native QA or solver result."})
    dump(preserved_path, {"schema": "ds02.f4.fresh093.lineage-preservation.v1", "fresh092_package_commit": FRESH092_COMMIT, "fresh092_manifest": ref(FRESH092_MANIFEST), "fresh092_plan": ref(FRESH092_PLAN), "root444_review": ref(ROOT444_REVIEW), "root444_old_visual_anchors_not_relabelled": review.get("old_visual_anchors_not_relabelled", True), "first24_physical_case_count": 24, "independent_case_count_increment": 0, "source_only": True})
    dump(qa_gate_path, {"schema": "ds02.f4.fresh093.fresh092-qa-consumer-gate.v1", "source_package": str(FRESH092), "source_package_manifest": ref(FRESH092_MANIFEST), "source_package_binding": ref(FRESH092_BINDING), "worker": ref(FRESH092_WORKER), "source_immutable": True, "case_selection": {"per_case_worker": True, "selected_case_row_count": 1, "one_row_binding_view_required": True, "forbid_passing_the_24_row_binding_to_a_case_scoped_worker": True, "reason": "fresh092 rows_from_binding validates the selected case set; a --case-id invocation must receive a one-row binding view or it rejects the other 23 endpoints."}, "strict_diagnostic_boundary": {"root237_strict_centered_reference_checks_are_diagnostic_only": True, "native_mass_matches_continuum": "reported separately; never rescale", "exact_center_lattice": "reported separately; no threshold relaxation", "strict_continuum_center_bounds": "reported separately", "precision_status": "not_accepted", "q_n_status": "not_assessed", "fallback_stage1_gate": str(FRESH094_MANIFEST), "fallback_stage1_gate_sha256": None}, "source_only": True})
    future_native_rows = [{"case_id": row["case_id"], "physical_condition_sha256": row["endpoint"]["physical_condition_sha256"], "status": "future_disabled_until_fresh094_stage1_native_input_qa_pass_and_frame0_velocity_audit", "qa_attempt": row["qa"]["attempt_id"], "root237_strict_diagnostic": {"request": ref(row["qa_request"]), "pass": None, "precision_status": "not_accepted", "q_n_status": "not_assessed"}, "fresh094_stage1_qa": {"manifest": str(FRESH094_MANIFEST), "sha256": None, "case_id": row["case_id"], "pass": None}, "native_receipt": None, "frame0_velocity_report": None, "typed_receipt": None, "native_output_hashes": None} for row in cases]
    dump(native_plan_path, {"schema": "ds02.f4.fresh093.native-plan.v1", "scope_id": SCOPE_ID, "family_id": "F4", "case_count": 24, "solver_recipe": {"dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_mdbc": True, "no_forcing": True}, "stage1_gate": {"required_manifest": str(FRESH094_MANIFEST), "required_manifest_sha256": None, "required_result": "per_case actual native-input structural QA pass", "strict_root237_result_is_not_a_substitute": True, "frame0_velocity_audit_separate": True}, "cases": future_native_rows, "launches_by_source": 0, "all_future_hashes_null": True, "claim_boundary": "Full native 1201-frame execution is future and remains disabled until fresh094 stage-1 native-input QA and a separate saved frame-0 velocity audit pass. Root237 strict continuum mass/center/lattice results remain diagnostic evidence and do not grant precision or Q-N."})
    common = [root230_path, semantic_path, native_plan_path, preserved_path, qa_gate_path, FRESH092_MANIFEST, FRESH092_PLAN, FRESH092_BINDING, FRESH092_INTERFACE, FRESH092_WORKER, ROOT444_REVIEW, ROOT230_ENTRY, ROOT230_HOME, ROOT230_GPU, ROOT230_CONTRACT, RUNTIME, STRICT, RESOURCE, SOLVER]
    for row in cases:
        common.extend([row["owner_path"], row["qa_request"], row["receipt_path"], row["report_path"], row["xml_path"], Path(str(row["owner"]["source_definition"]["path"])), FRESH091 / "source-plan.json", F4_FAMILY / "case_registry.jsonl"])
    closure_paths = unique(common)
    closure_path = output / "evidence/source-static-closure.json"
    dump(closure_path, {"schema": "ds02.f4.fresh093.source-static-closure.v1", "files": {str(path): sha(path) for path in closure_paths}, "scientific_payloads": [], "bi4_producer_digests_bound": 24, "bi4_read_or_hashed_by_source": False, "root230_cpu142_policy_included": False})
    rows_out: list[dict[str, Any]] = []
    for row in cases:
        case_id = row["case_id"]
        owner = row["owner"]
        manifest_entries = []
        for role, path, digest, producer in [("owner", row["owner_path"], sha(row["owner_path"]), None), ("source_definition", Path(str(owner["source_definition"]["path"])), sha(Path(str(owner["source_definition"]["path"]))), None), ("gencase_receipt", row["receipt_path"], sha(row["receipt_path"]), None), ("prepared_input_report", row["report_path"], sha(row["report_path"]), None), ("generated_xml", row["xml_path"], row["xml_sha"], None), ("generated_bi4", row["bi4_path"], None, row["bi4_sha"]), ("fresh092_qa_request", row["qa_request"], sha(row["qa_request"]), None), ("root230_entry", ROOT230_ENTRY, sha(ROOT230_ENTRY), None), ("root230_home_policy", ROOT230_HOME, sha(ROOT230_HOME), None), ("root230_gpu_policy", ROOT230_GPU, sha(ROOT230_GPU), None), ("root230_contract", ROOT230_CONTRACT, sha(ROOT230_CONTRACT), None), ("runtime", RUNTIME, sha(RUNTIME), None), ("strict_dispatch", STRICT, sha(STRICT), None), ("resource_window", RESOURCE, sha(RESOURCE), None), ("solver_binary", SOLVER, sha(SOLVER), None)]:
            entry = {"role": role, "path": str(path), "required": True, "expected_sha256": digest, "producer_sha256": producer, "read_by_source": False}
            if role == "generated_bi4": entry["read_policy"] = "deferred_stat_or_solver_read_only_producer_digest_no_source_open"
            manifest_entries.append(entry)
        manifest_path = output / "manifests" / f"{case_id}.json"
        dump(manifest_path, {"schema": "ds02.f4.fresh093.native-input-manifest.v1", "scope_id": SCOPE_ID, "family_id": "F4", "case_id": case_id, "entries": manifest_entries, "arrays_read_by_source": False, "jobs_started_by_source": False, "gencase_semantics": {"raw_receipt_actual": True, "data2d": False, "total": row["counts"]["total"], "fluid": row["counts"]["fluid"], "fixed": row["counts"]["fixed"]}, "qa_future": True, "native_future": True, "claim_boundary": "Actual GenCase evidence plus disabled Root230 child input provenance only."})
        case_static = unique(closure_paths + [closure_path, manifest_path])
        input_sha = {str(path): sha(path) for path in case_static}
        prefix = row["xml_path"].with_suffix("")
        native_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-native-root230-fresh093"
        qa_ref = {"status": "future_disabled", "provider_attempt_id": row["qa"]["attempt_id"], "request": ref(row["qa_request"]), "pass": None, "execution_receipt": None, "index": None, "binding": None, "output_hashes": None, "independent_case_count_increment": 0}
        request = {"schema": "ds02.runner-request.v2", "family_id": "F4", "scope_id": SCOPE_ID, "case_id": case_id, "attempt_id": native_attempt, "kind": "qualification", "cpu_task_kind": "native_solver", "command": [str(SOLVER), str(prefix), "{attempt_root}/solver_output", "-tmax:1.2", "-tout:0.001"], "cwd": str(prefix.parent), "worktree_root": str(INFRA), "max_wall_seconds": 14400, "cpu_threads": 2, "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 214748364800, "launch": False, "launch_allowed": False, "execution_allowed": False, "disabled": True, "launch_owner": "root", "root_only": True, "root_review_required": True, "source_only": True, "status": "source_only_disabled", "independent_case_count_increment": 0, "disabled_reason": "Enable only after the matching fresh094 stage-1 native-input QA passes and Root verifies the separately saved native frame-0 vertical/horizontal velocity audit. Root237 centered-reference output is retained as a strict diagnostic and cannot substitute for fresh094, grant precision/Q-N, or trigger mass rescaling; no full solver, visual, precision, Q-N, production or independent-case credit is granted here.", "input_files": [str(path) for path in case_static], "input_sha256": input_sha, "deferred_input_files": [str(row["xml_path"]), str(row["bi4_path"])], "deferred_input_sha256": {str(row["xml_path"]): row["xml_sha"], str(row["bi4_path"]): None}, "deferred_bi4_producer_sha256": {str(row["bi4_path"]): row["bi4_sha"]}, "gencase_receipt": str(row["receipt_path"]), "gencase_receipt_sha256": sha(row["receipt_path"]), "gencase_actual_evidence": {"per_case_receipt": str(row["receipt_path"]), "per_case_receipt_sha256": sha(row["receipt_path"]), "prepared_input_report": str(row["report_path"]), "prepared_input_report_sha256": sha(row["report_path"]), "generated_xml": {"path": str(row["xml_path"]), "producer_sha256": row["xml_sha"]}, "generated_bi4": {"path": str(row["bi4_path"]), "producer_sha256": row["bi4_sha"], "content_rehashed_by_source": False}, "total_particles": row["counts"]["total"], "fluid_particles": row["counts"]["fluid"], "fixed_particles": row["counts"]["fixed"], "moving_particles": row["counts"]["moving"], "floating_particles": row["counts"]["floating"], "solver_dimension_from_gencase": 3, "data2d": False, "data2d_source": str(semantic_path), "raw_receipt_immutable": True}, "physical_case_id": owner["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "source_plan_condition_sha256": row["endpoint"]["source_plan_condition_sha256"], "physical_binding": {"path": str(row["owner_path"]), "sha256": sha(row["owner_path"])}, "source_definition": {"path": str(owner["source_definition"]["path"]), "sha256": sha(Path(str(owner["source_definition"]["path"])))}, "native_initial_qa": {**qa_ref, "strict_precision_result_is_not_stage1_gate": True, "fresh094_stage1_gate": {"manifest": str(FRESH094_MANIFEST), "sha256": None, "pass": None, "required": True}}, "frame0_velocity_audit": {"status": "future_required_after_native_saved_frame0_before_typed", "expected_initial_velocity_from_owner": owner["initial_state"]["velocities_m_per_s"], "report": None, "report_sha256": None, "pass": None, "arrays_read_by_source": False}, "solver_recipe": {"dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_mdbc": True, "no_forcing": True, "native_types": {"fixed": [0], "moving": [], "floating": [], "fluid": [3]}}, "qualification_scope": {"recipe_id": "F4_finite_drop_pool_native_dbc_verlet_wendland_v1", "resolution": "native_dp010", "expected_frames": 1201, "time_window_s": 1.2, "output_interval_s": 0.001, "mechanism_id": owner.get("mechanism_id"), "status": "disabled_pending_fresh094_stage1_qa_and_frame0_velocity_audit"}, "root230": {"entry": root230["references"]["entry"], "profile": root230["profile"], "dataset_inventory_profile": root230["dataset_inventory_profile"], "home_policy": root230["references"]["home_policy"], "gpu_policy": root230["references"]["gpu_policy"], "effective_reservation_function_sha256": root230["effective_reservation_function_sha256"], "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "solver_concurrency_cap": 8}, "root_actual_launch_source": str(ROOT230_ENTRY), "root_gpu_selection_profile": ROOT230_PROFILE, "root_solver_concurrency_cap": 8, "root_inventory_policy_source": str(ROOT230_HOME), "root_inventory_policy_source_sha256": sha(ROOT230_HOME), "root_dataset_inventory_profile": ROOT230_DATASET_PROFILE, "root_home_free_gib_floor": 500, "root_nvme_free_gib_floor": 100, "root_effective_reservation_function_sha256": ROOT230_EFFECTIVE_RESERVATION_SHA, "resource_contract": {"native_concurrency": 8, "conversion_concurrency": 2, "cpu_threads": 2, "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "parent_budget_gpu_hours": 512, "parent_budget_cpu_core_hours": 3840, "qualification_slots": 1024, "production_slots": 720, "resource_window_approval": str(RESOURCE), "gpu_policy_entry": str(ROOT230_ENTRY), "deadline": "2026-10-14T07:23:48Z"}, "expected_outputs": {"output_root": "{attempt_root}", "data_root": "{attempt_root}/solver_output/data", "execution_receipt": "{attempt_root}/execution-receipt.json", "execution_receipt_sha256": None, "full_native_frames": 1201, "frame0_velocity_audit": None, "typed_receipt": None, "all_future_sha256": None}, "arrays_read_by_source": False, "bi4_read_by_source": False, "no_jobs_started_by_source": True, "no_shared_registry_write": True, "read_policy": {"source_arrays": False, "native_bi4": "deferred Root230 solver input", "csv": False, "h5": False, "typed": "future after native and frame0 audit"}, "q_n_status": "not_assessed", "precision_status": "not_accepted", "production_approval": "none", "root235_root236_failures_preserved": str(FRESH092 / "metadata/root237-source-contract-repair.json"), "root470_strict_diagnostic": "preserved separately; no promotion or relabeling", "claim_boundary": "Actual Root444 GenCase and semantic 3D/count evidence are bound. Fresh094 stage-1 native-input QA, Root230 full1201 native execution, saved-frame0 velocity audit, typed conversion and visual results remain future and disabled."}
        request_path = output / "requests" / f"{case_id}-full1201-native-root230-disabled.request.json"
        dump(request_path, request)
        rows_out.append({"case_id": case_id, "request": ref(request_path), "manifest": ref(manifest_path), "actual_gencase_status": "completed/0", "actual_qa_status": "future_disabled", "native_status": "future_disabled", "future_native_receipt_sha256": None})
    dump(output / "evidence/request-index.json", {"schema": "ds02.f4.fresh093.request-index.v1", "scope_id": SCOPE_ID, "family_id": "F4", "case_count": 24, "rows": rows_out, "launch_allowed": False, "all_future_hashes_null": True, "arrays_read_by_source": False, "jobs_started_by_source": False, "root230": root230, "semantic_adapter_needed": False})
    dump(output / "metadata/fresh093-native-binding.json", {"schema": "ds02.f4.fresh093.native-binding.v1", "scope_id": SCOPE_ID, "family_id": "F4", "source_commit": None, "source_commit_policy": "Reported by the scoped git commit accompanying this package; no self-referential commit is embedded.", "fresh092": {"manifest": ref(FRESH092_MANIFEST), "plan": ref(FRESH092_PLAN), "binding": ref(FRESH092_BINDING)}, "root444_review": ref(ROOT444_REVIEW), "actual_gencase_case_count": 24, "actual_gencase_completed0": 24, "actual_counts": {"total": 83233, "fixed": 24161, "fluid": 59072, "moving": 0, "floating": 0, "dimension": 3}, "actual_qa_status": "future_disabled", "native_request_count": 24, "native_receipt_hashes": None, "typed_hashes": None, "independent_case_count_increment": 0, "claim_boundary": "Source-only Root230 native handoff; no QA/native/typed/render completion or credit."})
    dump(output / "metadata/fresh093-actual-gencase-semantic-contract.json", {"schema": "ds02.f4.fresh093.actual-gencase-semantic-contract.v1", "raw_receipt_required_fields": ["status", "returncode", "solver_dimension_from_gencase", "total_particles", "fluid_particles"], "prepared_report_required_fields": ["actual_total_particles", "actual_generated_constants.data2d", "generated_xml_particle_counts", "xml_sha256", "bi4_sha256"], "missing_raw_field_policy": "If a future producer lacks a runtime-required field, register a separate semantic adapter receipt from prepared metadata; never patch or relabel the raw receipt.", "current_semantic_adapter_needed": False, "source_only": True})
    dump(output / "F4_STAGE1_FRESH093_FUTURE_ROOT237_QA_TO_ROOT230_NATIVE_BIND_MANIFEST.json", {"schema": "ds02.f4.fresh093.manifest.v1", "scope_id": SCOPE_ID, "family_id": "F4", "case_count": 24, "actual_gencase_completed0": 24, "initial_qa_status": "future_disabled", "native_requests": 24, "all_requests_disabled": True, "future_hashes": None, "source_only": True, "independent_case_count_increment": 0, "actual_counts": {"total": 83233, "fixed": 24161, "fluid": 59072, "moving": 0, "floating": 0, "dimension": 3}, "semantic_adapter_needed": False, "preserved_source092": ref(FRESH092_MANIFEST), "claim_boundary": "Actual GenCase evidence only; matching Root237 QA, Root230 full1201 native, frame0 velocity audit, typed and visual outcomes remain future."})
    (output / "README.md").write_text("""# F4 fresh093 Root237-QA to Root230 native handoff\n\nFresh093 binds the 24 Root444 individual GenCase completed/0 receipts already\nrecorded by fresh092. Every raw receipt supplies actual 3D, total and fluid\nfields; its prepared report supplies data2d=false and the XML partition\n(24,161 fixed plus 59,072 fluid = 83,233 total). Raw receipt JSON remains\nimmutable. A future semantic adapter is required only if a later producer\ndrops a runtime-required field; this source package does not fabricate one.\n\nThere are 24 disabled Root230 qualification requests using the approved\nsolver, exact dp=.01, tmax=1.2 s, tout=.001 s, and 1,201 native frames. Each\nrequest is gated on its matching fresh092 Root237 initial QA and a saved\nnative frame-0 velocity audit before typed conversion. Root230 Home-floor and\neight-UUID policy digests are bound; the old CPU142 inventory policy is not\nincluded. Future receipts, frame-0 reports, typed outputs and hashes remain\nnull. No job, solver, array read, shared registry write, or scientific payload\ncopy was performed by this package.\n""", encoding="utf-8")
    return {"schema": "ds02.f4.fresh093.build-result.v1", "package": str(output), "actual_gencase_completed0": 24, "initial_qa_status": "future_disabled", "native_requests": 24, "future_hashes_null": True, "semantic_adapter_needed": False, "bi4_read_or_hashed_by_source": False, "source_only": True}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
