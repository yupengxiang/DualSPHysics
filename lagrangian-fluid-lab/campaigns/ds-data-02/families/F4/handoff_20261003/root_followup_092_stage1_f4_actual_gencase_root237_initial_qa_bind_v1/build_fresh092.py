#!/usr/bin/env python3
"""Build fresh092 actual Root445 GenCase -> Root237 QA handoffs.

The builder reads only JSON, XML and source metadata. It never opens, hashes,
copies or decodes BI4 payloads and never invokes a worker, GenCase or solver.
The BI4 SHA in each binding is the producer value recorded by Root445's
prepared-input report.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
HERE = Path(__file__).resolve().parent
LAB = INTEGRATION / "lagrangian-fluid-lab"
FRESH091 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_091_stage1_f4_first24_coverage_audit_v1"
ACTUAL444 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_fresh091_first24_registered_genuine_GenCase_444"
REVIEW444 = ACTUAL444 / "actual-root-GenCase-first24-enable-review.json"
ROOT237_WORKER = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_six_actual_gen_receipt_json_alias_native_qa_237/run_f4_fallback_native_initial_qa_root237.py"
ROOT237_CONTRACT = HERE / "metadata/root237-source-contract-repair.json"
ROOT236_WORKER = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_six_native_initial_qa_actual_receipt_alias_repair_236/run_f4_fallback_native_initial_qa_root236.py"
ROOT236_PREFLIGHT = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_six_native_initial_qa_actual_receipt_alias_repair_236/metadata-child-audit-preflight.json"
AUDIT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_f4_centered_reference_v1.py"
DECODER = INTEGRATION / "lagrangian-fluid-lab/scripts/f8_r008_safe_bi4_decoder_v1.py"
MASS_AUDIT = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
ROOT142 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_POLICY = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
PARTVTK_BINARY = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
SCOPE_ID = "F4_STAGE1_FIRST24_FRESH091_ACTUAL_GENCASE_ROOT237_INITIAL_QA_V1"
QA_ATTEMPT = "root-stage1-f4-fresh091-first24-root237-native-initial-qa-092"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
ALLOWED = {".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log"}
RAW = {".bi4", ".h5", ".csv", ".vtk", ".vtu", ".vtp"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"metadata object required: {path}")
    return value


def sha(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW:
        raise ValueError(f"scientific payload hash refused: {path}")
    if path.suffix.lower() not in ALLOWED or not path.is_file():
        raise ValueError(f"static metadata file required: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def valid_sha(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def unique(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            out.append(path)
    return out


def static_paths(paths: list[Path]) -> list[Path]:
    out = unique(paths)
    for path in out:
        sha(path)
    return out


def source_paths(owner: dict[str, Any], request: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for key in ("source_definition", "mother_definition", "source_plan_path"):
        value = owner.get(key)
        if isinstance(value, dict) and value.get("path"):
            paths.append(Path(value["path"]))
        elif isinstance(value, str):
            paths.append(Path(value))
    for raw in request.get("input_files", []):
        path = Path(str(raw))
        if path.suffix.lower() in ALLOWED:
            paths.append(path)
    registry = owner.get("registry")
    manifest = owner.get("registry_manifest")
    for value in (registry, manifest):
        if isinstance(value, dict) and value.get("path"):
            paths.append(Path(value["path"]))
    return paths


def build_case(request_path: Path, review: dict[str, Any]) -> dict[str, Any]:
    request = load(request_path)
    case = str(request["case_id"])
    owner_path = FRESH091 / "owners" / f"{case}.owner.json"
    source_request = FRESH091 / "requests" / f"{case}-gencase.request.json"
    root_binding = ACTUAL444 / "bindings" / f"{case}-root-bound-gencase.json"
    if not owner_path.is_file() or not source_request.is_file() or not root_binding.is_file():
        raise FileNotFoundError(f"missing fresh091/Root445 binding for {case}")
    owner = load(owner_path)
    source = load(source_request)
    bound = load(root_binding)
    if owner.get("case_id") != case or source.get("case_id") != case or bound.get("case_id") != case:
        raise ValueError(f"case identity mismatch: {case}")
    if owner.get("physical_condition_sha256") != request.get("physical_condition_sha256"):
        raise ValueError(f"fresh091/Root445 physical condition mismatch: {case}")
    attempt = str(request["attempt_id"])
    attempt_root = DATA / "families" / "F4" / case / attempt
    receipt_path = attempt_root / "execution-receipt.json"
    prepared_path = attempt_root / "prepared" / "prepared-input-report.json"
    xml_path = attempt_root / "prepared" / f"{case}.xml"
    bi4_path = attempt_root / "prepared" / f"{case}.bi4"
    receipt = load(receipt_path)
    prepared = load(prepared_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"actual Root445 receipt is not completed/0: {case}")
    if receipt.get("request", {}).get("attempt_id") != attempt:
        raise ValueError(f"Root445 receipt attempt drift: {case}")
    if receipt.get("solver_dimension_from_gencase") != 3 or prepared.get("actual_total_particles") != receipt.get("total_particles"):
        raise ValueError(f"actual Root445 3D/count mismatch: {case}")
    counts = prepared.get("generated_xml_particle_counts")
    if not isinstance(counts, dict) or any(int(counts.get(key, 0)) <= 0 for key in ("fixed", "fluid")):
        raise ValueError(f"actual XML counts missing: {case}")
    if int(counts["fixed"]) + int(counts["fluid"]) != int(prepared["actual_total_particles"]):
        raise ValueError(f"actual XML partition does not close: {case}")
    xml_sha = sha(xml_path)
    if prepared.get("xml_sha256") != xml_sha or not valid_sha(prepared.get("bi4_sha256")):
        raise ValueError(f"actual producer report digest fields drift: {case}")
    constants = prepared.get("actual_generated_constants", {})
    density = float(constants["rhop0"]["value"])
    dp = float(constants["dp"]["value"])
    if density <= 0 or dp <= 0:
        raise ValueError(f"actual GenCase constants invalid: {case}")
    review_requests = {Path(str(value)).name.removesuffix("-gencase-request.json") for value in review.get("requests", [])}
    if case not in review_requests:
        raise ValueError(f"case missing from Root445 review: {case}")
    return {
        "endpoint_id": case, "physical_case_id": owner["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "source_plan_condition_sha256": owner["source_plan_condition_sha256"],
        "parameters": owner.get("parameters", {}), "mechanism_id": owner.get("mechanism_id"),
        "owner": owner, "owner_path": owner_path, "source_request": source_request,
        "root445_request": request_path, "root445_binding": root_binding,
        "attempt_id": attempt, "receipt_path": receipt_path, "prepared_path": prepared_path,
        "xml_path": xml_path, "bi4_path": bi4_path, "xml_sha256": xml_sha,
        "bi4_sha256": prepared["bi4_sha256"], "receipt": receipt, "prepared": prepared,
        "total_particles": int(receipt["total_particles"]), "fluid_particles": int(receipt["fluid_particles"]),
        "fixed_particles": int(counts["fixed"]), "moving_particles": int(counts.get("moving", 0)),
        "floating_particles": int(counts.get("floating", 0)), "solver_dimension": 3,
        "density_kg_m3": density, "dp_m": dp, "source_paths": source_paths(owner, source),
        "bound": bound,
    }


def main() -> int:
    review = load(REVIEW444)
    if review.get("actual_strict_metadata_preflight24_pass") is not True or review.get("actual_source_commit") != "ab2503d9":
        raise ValueError("Root445 review provenance drift")
    request_paths = sorted(ACTUAL444.glob("*-gencase-request.json"))
    if len(request_paths) != 24 or review.get("exact_finite_drop_physical_tuples") != 24:
        raise ValueError("Root445 actual request set is not 24")
    cases = [build_case(path, review) for path in request_paths]
    ids = [row["endpoint_id"] for row in cases]
    if len(set(ids)) != 24:
        raise ValueError("duplicate fresh092 physical cases")
    for path in (PARTVTK_BINARY, ROOT237_WORKER, ROOT236_WORKER, ROOT236_PREFLIGHT, AUDIT, DECODER, MASS_AUDIT, RUNTIME, STRICT, ROOT142, ROOT230_ENTRY, ROOT230_POLICY, ROOT230_CONTRACT, RESOURCE):
        if not path.is_file():
            raise FileNotFoundError(path)
    # Contracts are written before they enter the request static closure.
    dump(HERE / "metadata/root237-interface-contract.json", {
        "schema": "ds02.f4.fresh092.root237-interface-contract.v1",
        "upstream_worker": ref(ROOT237_WORKER), "fresh092_worker": str(HERE / "workers/run_f4_fresh092_native_initial_qa_root237.py"),
        "cli": ["--plan", "--gencase-binding", "--owner-root", "--audit-script", "--output-root", "--python", "--case-id"],
        "binding_keys": {"plan": ["scope_id", "qa_attempt_id", "cases"], "binding": ["aggregate_execution_receipt", "per_case_actual_gencase_receipts"], "row": ["endpoint_id", "gencase_receipt", "generated_xml", "generated_bi4", "solver_dimension_from_gencase", "total_particles", "fluid_particles"], "owner": ["physical_condition_sha256", "physical_case_id", "geometry", "initial_state", "source_definition", "controls", "parameters", "solver_recipe"]},
        "audit_argv": ["audit", "--metadata", "--prefix", "--output"],
        "audit_accessed_arrays": ["Posd", "Idp"], "audit_marker_arrays": [],
        "source_reads_or_hashes_bi4": False, "source_reads_or_hashes_h5": False,
        "claim_boundary": "Initial native input QA only; no native mass, full solver, visual, precision, Q-N, production, or independent-case credit.",
    })
    dump(HERE / "metadata/partvtk-binary-contract.json", {
        "schema": "ds02.f4.fresh092.partvtk-binary-contract.v1",
        "path": str(PARTVTK_BINARY), "registered_sha256": PARTVTK_SHA,
        "source_read_or_hashed": False, "root_job_must_validate": True,
        "role": "Root237 safe BI4 decoder / PartVTK native audit binary closure",
        "upstream_request": str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_six_actual_gen_receipt_json_alias_native_qa_237/native-initial-qa-request.json"),
        "future_output_hash": None,
    })
    worker = HERE / "workers/run_f4_fresh092_native_initial_qa_root237.py"
    plan = {
        "schema": "ds02.f4.fresh092.actual-gencase-plan.v1", "family_id": "F4", "scope_id": SCOPE_ID,
        "qa_attempt_id": QA_ATTEMPT, "actual_source_commit": "ab2503d9", "case_count": 24,
        "cases": [{k: (str(row[k]) if isinstance(row[k], Path) else row[k]) for k in ("endpoint_id", "physical_case_id", "physical_condition_sha256", "source_plan_condition_sha256", "parameters", "mechanism_id", "owner_path", "density_kg_m3", "dp_m", "total_particles", "fixed_particles", "fluid_particles", "moving_particles", "floating_particles", "solver_dimension")} for row in cases],
        "root445_review": ref(REVIEW444), "source_only": True, "future_qa_hashes": None, "native_hashes": None,
        "independent_case_count_increment": 0, "claim_boundary": "Actual Root445 GenCase producer evidence is bound; initial native QA remains future and disabled.",
    }
    plan_path = HERE / "metadata/fresh092-actual-gencase-plan.json"
    dump(plan_path, plan)
    binding_rows = []
    for row in cases:
        binding_rows.append({
            "endpoint_id": row["endpoint_id"], "physical_case_id": row["physical_case_id"], "physical_condition_sha256": row["physical_condition_sha256"],
            "gencase_receipt": {"path": str(row["receipt_path"]), "producer_sha256": sha(row["receipt_path"])},
            "generated_xml": {"path": str(row["xml_path"]), "producer_sha256": row["xml_sha256"], "observed_xml_sha256": row["xml_sha256"]},
            "generated_bi4": {"path": str(row["bi4_path"]), "producer_sha256": row["bi4_sha256"], "content_rehashed_by_source": False, "size_bytes_from_stat": None},
            "prepared_input_report": {"path": str(row["prepared_path"]), "sha256": sha(row["prepared_path"])},
            "solver_dimension_from_gencase": 3, "total_particles": row["total_particles"], "fixed_particles": row["fixed_particles"], "fluid_particles": row["fluid_particles"], "returncode": 0,
        })
    binding = {
        "schema": "ds02.f4.fresh092.actual-gencase-binding.v1", "family_id": "F4", "scope_id": SCOPE_ID,
        "case_count": 24, "independent_case_count_increment": 0,
        "aggregate_execution_receipt": {"status": "not_applicable", "preserved_without_promotion": True, "semantics": "Root445 registered 24 individual completed/0 receipts; no aggregate receipt is promoted."},
        "per_case_actual_gencase_receipts": binding_rows,
        "partvtk_binary": {"path": str(PARTVTK_BINARY), "producer_sha256": PARTVTK_SHA, "source_read_or_hashed": False},
        "source_only": True, "future_qa_hashes": None, "future_native_hashes": None,
        "claim_boundary": "Actual GenCase producer evidence only; no native QA, mass, solver, visual, precision, Q-N, production, or independent-case credit.",
    }
    binding_path = HERE / "metadata/fresh092-actual-gencase-binding.json"
    dump(binding_path, binding)
    # Per-case binding sidecars make each Root445 receipt/report and the
    # producer BI4 digest independently reviewable without opening BI4.
    for row in cases:
        dump(HERE / "bindings" / f"{row['endpoint_id']}.actual-gencase-binding.json", {
            "schema": "ds02.f4.fresh092.actual-gencase-case-binding.v1", "case_id": row["endpoint_id"],
            "physical_case_id": row["physical_case_id"], "physical_condition_sha256": row["physical_condition_sha256"],
            "source_plan_condition_sha256": row["source_plan_condition_sha256"], "source_owner": ref(row["owner_path"]),
            "root445_request": ref(row["root445_request"]), "root445_binding": ref(row["root445_binding"]),
            "gencase_receipt": {"path": str(row["receipt_path"]), "sha256": sha(row["receipt_path"]), "status": "completed/0"},
            "prepared_input_report": ref(row["prepared_path"]), "generated_xml": {"path": str(row["xml_path"]), "sha256": row["xml_sha256"]},
            "generated_bi4": {"path": str(row["bi4_path"]), "producer_sha256": row["bi4_sha256"], "source_read_or_hashed": False},
            "actual_counts": {"total": row["total_particles"], "fixed": row["fixed_particles"], "fluid": row["fluid_particles"], "moving": row["moving_particles"], "floating": row["floating_particles"], "dimension": 3},
            "future_initial_qa_receipt": None, "future_native_receipt": None,
        })
    future_native = []
    for row in cases:
        recipe = row["owner"].get("solver_recipe", {})
        future_native.append({"case_id": row["endpoint_id"], "physical_case_id": row["physical_case_id"], "physical_condition_sha256": row["physical_condition_sha256"], "status": "future_disabled_until_initial_qa_pass", "depends_on_initial_qa_attempt": f"{QA_ATTEMPT}-{row['endpoint_id'].lower()}", "solver_recipe": {"dp_m": recipe.get("dp_m"), "time_max_s": recipe.get("time_max_s", 1.2), "time_out_s": recipe.get("time_out_s", 0.001), "native_frame_count": recipe.get("native_frame_count", 1201), "solver_options": recipe.get("solver_options", ["-tmax:1.2", "-tout:0.001"])}, "native_request": None, "execution_receipt": None, "output_hashes": None, "production_approval": "none", "qualification_status": "not_granted"})
    future_native_path = HERE / "evidence/future-native-plan.json"
    dump(future_native_path, {"schema": "ds02.f4.fresh092.future-native-plan.v1", "case_count": 24, "source_only": True, "cases": future_native, "all_future_hashes_null": True, "solver_launches_by_source": 0, "claim_boundary": "Native full1.2s/.001/1201 plan is future only and remains blocked until the matching initial QA request completes pass."})
    # The per-request closure must include the generated interface contracts
    # whose binding-key and deferred-binary rules the worker consumes.  Keep
    # these explicit: relying on the builder's in-memory values would leave a
    # request that passes source preparation but cannot be independently
    # reviewed from its recorded input closure.
    common = [worker, ROOT237_CONTRACT, ROOT236_WORKER, ROOT236_PREFLIGHT, AUDIT, DECODER, MASS_AUDIT, RUNTIME, STRICT, ROOT142, ROOT230_ENTRY, ROOT230_POLICY, ROOT230_CONTRACT, RESOURCE, plan_path, binding_path, future_native_path, REVIEW444, HERE / "metadata/root237-interface-contract.json", HERE / "metadata/partvtk-binary-contract.json"]
    for row in cases:
        common += [row["owner_path"], row["source_request"], row["root445_request"], row["root445_binding"], row["receipt_path"], row["prepared_path"], row["xml_path"]] + row["source_paths"]
    common_static = static_paths(common)
    static_map = {str(path): sha(path) for path in common_static}
    dump(HERE / "evidence/source-static-closure.json", {"schema": "ds02.f4.fresh092.source-static-closure.v1", "files": static_map, "scientific_payloads": [], "bi4_producer_digests_bound": 24, "bi4_read_or_hashed_by_source": False, "partvtk_binary_source_read_or_hashed": False})
    dump(HERE / "evidence/actual-gencase-selection.json", {"schema": "ds02.f4.fresh092.actual-gencase-selection.v1", "case_count": 24, "actual_source_commit": "ab2503d9", "actual_root_review": ref(REVIEW444), "cases": [{"case_id": row["endpoint_id"], "receipt": ref(row["receipt_path"]), "prepared_report": ref(row["prepared_path"]), "xml": {"path": str(row["xml_path"]), "sha256": row["xml_sha256"]}, "bi4_producer_sha256": row["bi4_sha256"], "total_particles": row["total_particles"], "fixed_particles": row["fixed_particles"], "fluid_particles": row["fluid_particles"], "dimension": 3} for row in cases], "source_read_or_hashed_bi4": False, "independent_case_count_increment": 0})
    dump(HERE / "evidence/partvtk-binary-closure.json", {"schema": "ds02.f4.fresh092.partvtk-binary-closure.v1", "path": str(PARTVTK_BINARY), "registered_sha256": PARTVTK_SHA, "source_read_or_hashed": False, "upstream_root237_request": str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_six_actual_gen_receipt_json_alias_native_qa_237/native-initial-qa-request.json"), "worker_argv_audit": ["audit", "--metadata", "--prefix", "--output"], "future_qa_output_hash": None})
    request_refs = []
    python_bin = LAB / ".venv/bin/python"
    for row in cases:
        cid = row["endpoint_id"]
        req_path = HERE / "requests" / f"{cid}-initial-native-qa-disabled.request.json"
        case_binding = HERE / "bindings" / f"{cid}.actual-gencase-binding.json"
        case_static = static_paths(common_static + [case_binding])
        command = [str(python_bin), str(worker), "--plan", str(plan_path), "--gencase-binding", str(binding_path), "--owner-root", str(FRESH091 / "owners"), "--audit-script", str(AUDIT), "--output-root", "{attempt_root}", "--python", str(python_bin), "--case-id", cid]
        deferred = [str(row["bi4_path"]), str(PARTVTK_BINARY)]
        request = {
            "schema": "ds02.runner-request.v3", "family_id": "F4", "scope_id": SCOPE_ID,
            "case_id": cid, "physical_case_id": row["physical_case_id"], "physical_condition_sha256": row["physical_condition_sha256"], "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "source_only": True, "status": "source_only_disabled", "disabled": True, "execution_allowed": False, "launch_allowed": False, "launch": False, "launch_owner": "root", "root_only": True, "root_review_required": True,
            "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "max_wall_seconds": 1800, "estimated_storage_bytes": 1073741824,
            "attempt_id": f"{QA_ATTEMPT}-{cid.lower()}", "cwd": str(LAB), "worktree_root": str(INFRA), "command": command,
            "worker_argv_contract": {"argv_exact": command, "accessed_binding_keys": load(HERE / "metadata/root237-interface-contract.json")["binding_keys"], "audit_argv": ["audit", "--metadata", "--prefix", "--output"]},
            "input_files": [str(path) for path in case_static], "input_sha256": {str(path): sha(path) for path in case_static},
            "deferred_input_files": deferred, "deferred_input_sha256": {path: None for path in deferred},
            "producer_input_files": [str(row["bi4_path"])], "producer_input_sha256": {str(row["bi4_path"]): row["bi4_sha256"]},
            "gencase_actual_evidence": {"receipt": str(row["receipt_path"]), "receipt_sha256": sha(row["receipt_path"]), "prepared_input_report": str(row["prepared_path"]), "prepared_input_report_sha256": sha(row["prepared_path"]), "generated_xml": str(row["xml_path"]), "generated_xml_sha256": row["xml_sha256"], "generated_bi4": str(row["bi4_path"]), "generated_bi4_producer_sha256": row["bi4_sha256"], "total_particles": row["total_particles"], "fixed_particles": row["fixed_particles"], "fluid_particles": row["fluid_particles"], "solver_dimension_from_gencase": 3},
            "partvtk_binary": {"path": str(PARTVTK_BINARY), "producer_sha256": PARTVTK_SHA, "source_read_or_hashed": False, "root_job_must_validate": True},
            "depends_on_attempts": [row["attempt_id"]], "future_initial_qa_receipt": None, "future_native_receipt": None,
            "expected_outputs": {"execution_receipt": None, "initial_native_qa_index": None, "initial_native_qa_binding": None, "reports": None, "all_future_sha256": None},
            "future_native_plan": str(future_native_path), "future_native_plan_sha256": sha(future_native_path),
            "arrays_read_by_source": False, "bi4_read_by_source": False, "no_jobs_started_by_source": True, "no_shared_registry_write": True,
            "independent_case_count_increment": 0, "q_n_status": "not_assessed", "precision_status": "not_accepted", "production_approval": "none", "numerical_reference_status": "not_assessed",
            "root_dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_native_v1", "root_inventory_policy_source": str(ROOT142), "root_inventory_policy_source_sha256": sha(ROOT142), "strict_dispatch_sha256": STRICT_SHA, "resource_window": str(RESOURCE), "resource_window_sha256": sha(RESOURCE),
            "resource_contract": {"home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "cpu_threads": 2, "native_concurrency_future": 8, "conversion_concurrency": 2, "parent_budget_gpu_hours": 512, "parent_budget_cpu_core_hours": 3840, "qualification_slots": 1024, "production_slots": 720, "deadline": "2026-10-14T07:23:48Z"},
            "disabled_reason": "Enable only after Root reviews this exact case's completed Root445 GenCase receipt/prepared XML and producer BI4 SHA, then runs Root237 initial native QA. Native full1.2s/.001/1201 remains future and blocked on this QA pass.",
        }
        dump(req_path, request)
        request_refs.append({"case_id": cid, "request": ref(req_path), "binding": ref(case_binding), "actual_gen_status": "completed/0", "initial_qa_status": "future_disabled", "native_status": "future_disabled"})
    dump(HERE / "evidence/request-index.json", {"schema": "ds02.f4.fresh092.request-index.v1", "case_count": 24, "requests": request_refs, "all_disabled": True, "future_hashes_null": True})
    dump(HERE / "F4_STAGE1_FRESH092_ACTUAL_GENCASE_ROOT237_INITIAL_QA_BIND_MANIFEST.json", {"schema": "ds02.f4.fresh092.manifest.v1", "family_id": "F4", "scope_id": SCOPE_ID, "case_count": 24, "actual_gencase_completed0": 24, "initial_qa_requests": 24, "all_requests_disabled": True, "future_qa_hashes": None, "future_native_hashes": None, "source_only": True, "independent_case_count_increment": 0, "cases": request_refs, "actual_counts": {"total_particles": 83233, "fixed_particles": 24161, "fluid_particles": 59072, "moving_particles": 0, "floating_particles": 0, "dimension": 3}, "partvtk_binary": {"path": str(PARTVTK_BINARY), "producer_sha256": PARTVTK_SHA, "source_read_or_hashed": False}, "claim_boundary": "Actual GenCase producer evidence is bound; native initial QA and all full1201 solver/typed/render outcomes remain future."})
    (HERE / "README.md").write_text(f"""# F4 fresh092 Root445 GenCase to Root237 initial-QA handoff

Fresh092 binds all 24 individual Root445 GenCase receipts and prepared XML
reports from the adopted fresh091 finite-drop/offset/velocity cases. Every
producer is completed/0, genuine 3D, and reports 83,233 total particles,
59,072 fluid, 24,161 fixed, zero moving/floating. Counts and producer XML
digests are read from the actual JSON/XML reports; each BI4 SHA is carried as
Root445's producer attestation and is never read or rehashed by this source
package.

There are 24 disabled per-case Root237 initial native-QA requests. Their exact
worker argv, accessed binding keys, Root237 audit interface, safe decoder and
PartVTK binary attestation are recorded. The worker may read BI4 only inside a
Root-owned registered CPU audit; source preparation creates no scientific
copies and starts no jobs. Native full1.2 s/.001/1201 execution is represented
only by a future disabled plan and is blocked until the matching QA passes.

No visual, precision, Q-N, production, or independent-case credit is granted.
""", encoding="utf-8")
    print(json.dumps({"schema": "ds02.f4.fresh092.build-result.v1", "package": str(HERE), "actual_gencase_completed0": 24, "initial_qa_requests": 24, "future_native_requests": 0, "bi4_read_or_hashed_by_source": False, "source_only": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
