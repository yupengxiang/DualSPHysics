#!/usr/bin/env python3
"""Build disabled F4 stage-1 native-input QA requests.

This builder reads only JSON/XML/source metadata and the already registered
Root444 GenCase receipts.  It never opens, hashes, copies or decodes BI4/H5/
VTK/CSV data and never launches a job.  The emitted worker is enabled only by
Root after each fresh093 Root230 native receipt and frame-0 BI4 producer SHA
exist.  Root470's strict centered-reference negative is preserved as a
diagnostic and is never promoted to, or used as, the stage-1 gate.
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
FRESH093 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_093_stage1_f4_future_root237_qa_to_root230_full1201_native_bind_v1"
FRESH093_MANIFEST = FRESH093 / "F4_STAGE1_FRESH093_FUTURE_ROOT237_QA_TO_ROOT230_NATIVE_BIND_MANIFEST.json"
FRESH093_PLAN = FRESH093 / "metadata/fresh093-native-plan.json"
FRESH093_BINDING = FRESH093 / "metadata/fresh093-native-binding.json"
FRESH093_REQUEST_DIR = FRESH093 / "requests"
FRESH092 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_092_stage1_f4_actual_gencase_root237_initial_qa_bind_v1"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_GPU = ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
DECODER_CONTRACT = FRESH092 / "metadata/partvtk-binary-contract.json"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump").resolve()
DECODER_REGISTERED_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
SAFE_SCANNER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f8_r008_safe_bi4_decoder_v1.py").resolve()
SAFE_SCANNER_REGISTERED_SHA = "affbbb6c04a4d21d03037e74d0023112c60c7d8e5972cc6dfc882e1c7c5dc319"
SCANNER_ADAPTER = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py"
ROOT470_REPORT = DATA / "families/F4/F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p40000/root-stage1-f4-fresh091-first24-root237-native-initial-qa-092-f4_drop_gap0p18000_xoff0p08000_yoff0p04000_uz0p40000-root470/native-audit/cases/F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p40000/native-preflight-audit.json"
WORKER = PACKAGE / "workers/run_f4_fresh094_stage1_native_input_qa.py"
SCOPE_ID = "F4_STAGE1_FIRST24_BASIC_NATIVE_INPUT_QA_V1"
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
STATIC_SUFFIXES = {".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log", ""}
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
    if path != DECODER and path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"static input required: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def ref(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def unique(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result = []
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def xml_meta(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//execution/particles")
    if particles is None:
        raise ValueError(f"generated XML lacks particles: {path}")
    blocks = [{"mkfluid": int(node.attrib["mkfluid"]), "mk": int(node.attrib["mk"]), "begin": int(node.attrib["begin"]), "count": int(node.attrib["count"])} for node in particles.findall("fluid")]
    total = int(particles.attrib["np"])
    fixed = int(particles.attrib["nb"])
    fluid = sum(row["count"] for row in blocks)
    if total != fixed + fluid or total != 83233 or fixed != 24161 or fluid != 59072:
        raise ValueError(f"actual XML count contract drift: {path}")
    data2d = root.find(".//execution/constants/data2d")
    if data2d is None or str(data2d.attrib.get("value", "")).lower() != "false":
        raise ValueError(f"actual XML is not 3-D: {path}")
    definition = root.find(".//geometry/definition")
    if definition is None or abs(float(definition.attrib.get("dp", "0")) - .01) > 1e-12:
        raise ValueError(f"actual XML dp drift: {path}")
    params = {node.attrib.get("key"): node.attrib.get("value") for node in root.findall(".//execution/parameters/parameter")}
    if params.get("TimeMax") != "1.2" or params.get("TimeOut") != "0.001":
        raise ValueError(f"actual XML time recipe drift: {path}")
    return {"total": total, "fixed": fixed, "fluid": fluid, "blocks": blocks, "data2d": False, "dp_m": .01, "time_max_s": 1.2, "time_out_s": .001}


def verify_root230() -> dict[str, Any]:
    for path in (ROOT230_ENTRY, ROOT230_HOME, ROOT230_GPU, ROOT230_CONTRACT, RUNTIME, STRICT, RESOURCE, DECODER_CONTRACT, DECODER, SAFE_SCANNER, SCANNER_ADAPTER):
        if not path.is_file():
            raise FileNotFoundError(path)
    contract = load(ROOT230_CONTRACT)
    if contract.get("schema") != "ds02.root.native-home-floor-policy.v1" or contract.get("runtime_file_unchanged") is not True or contract.get("source_only_no_jobs_started") is not True:
        raise ValueError("Root230 contract drift")
    decoder_contract = load(DECODER_CONTRACT)
    if decoder_contract.get("registered_sha256") != DECODER_REGISTERED_SHA or decoder_contract.get("path") != str(DECODER) or decoder_contract.get("root_job_must_validate") is not True:
        raise ValueError("registered safe BI4 decoder contract drift")
    if sha(DECODER) != DECODER_REGISTERED_SHA:
        raise ValueError("registered safe BI4 decoder bytes drift")
    return {"profile": "root_live_all_idle_uuid_leased_eight_solver_v2", "dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_native_v1", "references": {"entry": ref(ROOT230_ENTRY), "home_policy": ref(ROOT230_HOME), "gpu_policy": ref(ROOT230_GPU), "contract": ref(ROOT230_CONTRACT), "runtime": ref(RUNTIME), "strict": ref(STRICT), "resource_window": ref(RESOURCE), "decoder_contract": ref(DECODER_CONTRACT), "safe_scanner_source": {"path": str(SAFE_SCANNER), "registered_sha256": SAFE_SCANNER_REGISTERED_SHA}, "scanner_adapter": ref(SCANNER_ADAPTER)}, "decoder": {"path": str(DECODER), "registered_sha256": DECODER_REGISTERED_SHA, "source_read_or_hashed": False}, "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "native_solver_concurrency_cap": 8, "conversion_concurrency_cap": 2}


def root470_negative() -> dict[str, Any]:
    report = load(ROOT470_REPORT)
    if report.get("case_id") != "F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p40000" or report.get("pass") is not False or report.get("native_audit_returncode") != 1:
        raise ValueError("Root470 strict diagnostic is not the preserved failed report")
    checks = report.get("checks", {})
    if checks.get("all_source_population_checks") is not False:
        raise ValueError("Root470 strict diagnostic no longer records source-population failure")
    return {"schema": "ds02.f4.fresh094.root470-strict-diagnostic-negative.v1", "report": {"path": str(ROOT470_REPORT), "sha256": sha(ROOT470_REPORT)}, "case_id": report["case_id"], "status": "completed-but-strict-failed", "returncode": report["native_audit_returncode"], "pass": False, "checks": checks, "source_rows": [{"source": row.get("source"), "fluid_count": row.get("fluid_count"), "native_mass_kg": row.get("native_mass_kg"), "bounds_m": row.get("bounds_m"), "checks": row.get("checks")} for row in report.get("source_rows", [])], "raw_native_arrays_observed": report.get("raw_native_arrays_observed"), "strict_precision_status": "negative_diagnostic_only", "mass_rescaled": False, "q_n_status": "not_assessed", "production_approval": "none", "claim_boundary": "Root470 strict centered-reference result is preserved verbatim as a negative diagnostic. It is not relabelled as stage-1 failure/success, not used to rescale mass, and cannot substitute for fresh094."}


def build() -> dict[str, Any]:
    output = PACKAGE.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root230 = verify_root230()
    strict_negative = root470_negative()
    strict_path = output / "metadata/root470-strict-diagnostic-negative.json"
    dump(strict_path, strict_negative)
    strict_path_sha = sha(strict_path)
    manifest = load(FRESH093_MANIFEST)
    plan = load(FRESH093_PLAN)
    binding = load(FRESH093_BINDING)
    if manifest.get("actual_gencase_completed0") != 24 or manifest.get("case_count") != 24 or plan.get("case_count") != 24 or binding.get("actual_gencase_completed0") != 24:
        raise ValueError("fresh093 upstream actual GenCase count drift")
    request_paths = sorted(FRESH093_REQUEST_DIR.glob("*-full1201-native-root230-disabled.request.json"))
    if len(request_paths) != 24:
        raise ValueError("fresh093 does not contain exactly 24 native requests")
    package_plan: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    static_common = [WORKER, FRESH093_MANIFEST, FRESH093_PLAN, FRESH093_BINDING, FRESH093 / "metadata/fresh093-native-binding.json", ROOT230_ENTRY, ROOT230_HOME, ROOT230_GPU, ROOT230_CONTRACT, RUNTIME, STRICT, RESOURCE, DECODER_CONTRACT, DECODER, SAFE_SCANNER, SCANNER_ADAPTER, strict_path]
    for request_path in request_paths:
        request = load(request_path)
        case_id = str(request["case_id"])
        if request.get("disabled") is not True or request.get("launch") is not False or request.get("cpu_task_kind") != "native_solver":
            raise ValueError(f"{case_id}: fresh093 native request is not disabled")
        evidence = request["gencase_actual_evidence"]
        owner_ref = request["physical_binding"]
        owner_path = Path(owner_ref["path"])
        receipt_path = Path(evidence["per_case_receipt"])
        report_path = Path(evidence["prepared_input_report"])
        xml_path = Path(evidence["generated_xml"]["path"])
        bi4_path = Path(evidence["generated_bi4"]["path"])
        owner = load(owner_path)
        receipt = load(receipt_path)
        report = load(report_path)
        if sha(owner_path) != owner_ref["sha256"] or sha(receipt_path) != evidence["per_case_receipt_sha256"] or sha(report_path) != evidence["prepared_input_report_sha256"] or sha(xml_path) != evidence["generated_xml"]["producer_sha256"]:
            raise ValueError(f"{case_id}: fresh093 static input digest closure failed")
        if not bi4_path.is_file() or not valid_sha(evidence["generated_bi4"]["producer_sha256"]):
            raise ValueError(f"{case_id}: registered GenCase BI4 producer attestation missing")
        if receipt.get("status") not in {"completed", "completed/0"} or receipt.get("returncode") != 0 or receipt.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{case_id}: raw GenCase receipt is not completed 3-D")
        xml_info = xml_meta(xml_path)
        geometry = owner.get("geometry", {})
        if not all(isinstance(geometry.get(name), dict) for name in ("tank", "drop", "pool")):
            raise ValueError(f"{case_id}: owner geometry incomplete")
        by_mkfluid = {row["mkfluid"]: row for row in xml_info["blocks"]}
        source_rows = {}
        for source_name in ("drop", "pool"):
            region = geometry[source_name]
            block = by_mkfluid.get(int(region["mkfluid"]))
            if block is None:
                raise ValueError(f"{case_id}: XML lacks {source_name} mkfluid block")
            source_rows[source_name] = {"mkfluid": int(region["mkfluid"]), "mk": int(block["mk"]), "begin": int(block["begin"]), "count": int(block["count"]), "low_m": region["low_m"], "size_m": region["size_m"]}
        binding_path = output / "metadata/bindings" / f"{case_id}.stage1-native-input-binding.json"
        binding_value = {"schema": "ds02.f4.fresh094.stage1-native-input-binding.v1", "family_id": "F4", "scope_id": SCOPE_ID, "case_id": case_id, "physical_case_id": owner["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "source_only": True, "execution_allowed": False, "owner": {"path": str(owner_path), "sha256": sha(owner_path)}, "source_definition": {"path": str(Path(owner["source_definition"]["path"])), "sha256": sha(Path(owner["source_definition"]["path"]))}, "gencase_receipt": {"path": str(receipt_path), "sha256": sha(receipt_path)}, "prepared_report": {"path": str(report_path), "sha256": sha(report_path)}, "generated_xml": {"path": str(xml_path), "sha256": sha(xml_path)}, "generated_bi4": {"path": str(bi4_path), "producer_sha256": evidence["generated_bi4"]["producer_sha256"], "content_rehashed_by_source": False}, "native_upstream_request": {"path": str(request_path), "sha256": sha(request_path), "attempt_id": request["attempt_id"]}, "native_attempt_id": request["attempt_id"], "decoder": {"path": str(DECODER), "registered_sha256": DECODER_REGISTERED_SHA, "contract": str(DECODER_CONTRACT), "source_read_or_hashed": False}, "scanner_source": {"path": str(SAFE_SCANNER), "registered_sha256": SAFE_SCANNER_REGISTERED_SHA}, "expected": {"total_particles": int(request["gencase_actual_evidence"]["total_particles"]), "fixed_particles": int(request["gencase_actual_evidence"]["fixed_particles"]), "fluid_particles": int(request["gencase_actual_evidence"]["fluid_particles"]), "moving_particles": int(request["gencase_actual_evidence"]["moving_particles"]), "floating_particles": int(request["gencase_actual_evidence"]["floating_particles"]), "solver_dimension": 3, "density_kg_m3": float(owner.get("density_kg_m3", 1000.0)), "parameters": owner["parameters"], "tank": geometry["tank"], "sources": source_rows}, "strict_root237_diagnostic": {"manifest": str(strict_path), "manifest_sha256": strict_path_sha, "status": "diagnostic_only", "never_substitute_for_stage1": True}, "claim_boundary": "Fresh094 stage-1 native structural QA only; strict center/lattice/mass/precision and saved-frame0 velocity remain separate diagnostics."}
        dump(binding_path, binding_value)
        source_def = Path(owner["source_definition"]["path"])
        case_static = unique(static_common + [request_path, owner_path, source_def, receipt_path, report_path, xml_path])
        case_input_sha = {str(path): sha(path) for path in case_static}
        request_out = output / "requests" / f"{case_id}-stage1-native-input-qa-disabled.request.json"
        native_root_placeholder = "{native_attempt_root}"
        worker_command = ["/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(WORKER), "--binding", str(binding_path), "--native-receipt", f"{native_root_placeholder}/execution-receipt.json", "--native-frame0", f"{native_root_placeholder}/solver_output/data/Part_0000.bi4", "--native-frame0-sha256", "{native_frame0_sha256}", "--output", "{attempt_root}"]
        request_out_value = {"schema": "ds02.runner-request.v2", "family_id": "F4", "scope_id": SCOPE_ID, "case_id": case_id, "attempt_id": f"root-stage1-f4-{case_id.lower()}-stage1-native-input-qa-094", "kind": "cpu", "cpu_task_kind": "audit", "command": worker_command, "cwd": str(WORKER.parent), "worktree_root": str(INFRA), "max_wall_seconds": 1800, "cpu_threads": 4, "estimated_peak_gpu_mib": 0, "estimated_storage_bytes": 2147483648, "launch": False, "launch_allowed": False, "execution_allowed": False, "disabled": True, "launch_owner": "root", "root_only": True, "root_review_required": True, "source_only": True, "status": "source_only_disabled", "independent_case_count_increment": 0, "disabled_reason": "Enable only after the matching Root230 native receipt is completed/0 and Root supplies the actual frame-0 BI4 producer SHA. The stage-1 worker validates measured structure/UID/domain invariants; saved frame-0 velocity is a separate downstream audit. Root470 strict centered-reference mass/center/lattice negatives remain diagnostics and do not grant or deny precision/Q-N here.", "input_files": [str(path) for path in case_static], "input_sha256": {**case_input_sha, str(DECODER): DECODER_REGISTERED_SHA}, "deferred_input_files": [str(bi4_path), f"{native_root_placeholder}/execution-receipt.json", f"{native_root_placeholder}/solver_output/data/Part_0000.bi4"], "deferred_input_sha256": {str(bi4_path): None, f"{native_root_placeholder}/execution-receipt.json": None, f"{native_root_placeholder}/solver_output/data/Part_0000.bi4": None}, "deferred_bi4_producer_sha256": {str(bi4_path): evidence["generated_bi4"]["producer_sha256"], f"{native_root_placeholder}/solver_output/data/Part_0000.bi4": None}, "gencase_receipt": str(receipt_path), "gencase_receipt_sha256": sha(receipt_path), "generated_xml": {"path": str(xml_path), "sha256": sha(xml_path)}, "gencase_actual_evidence": {"total_particles": request["gencase_actual_evidence"]["total_particles"], "fixed_particles": request["gencase_actual_evidence"]["fixed_particles"], "fluid_particles": request["gencase_actual_evidence"]["fluid_particles"], "moving_particles": request["gencase_actual_evidence"]["moving_particles"], "floating_particles": request["gencase_actual_evidence"]["floating_particles"], "solver_dimension_from_gencase": 3, "data2d": False, "raw_receipt_immutable": True}, "owner_binding": {"path": str(owner_path), "sha256": sha(owner_path)}, "physical_case_id": owner["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "native_upstream_request": {"path": str(request_path), "sha256": sha(request_path), "attempt_id": request["attempt_id"]}, "root230": root230, "stage1_qa_contract": {"binding": str(binding_path), "binding_sha256": sha(binding_path), "pass": None, "actual_native_frame0_report": None, "actual_native_frame0_report_sha256": None, "saved_frame0_velocity_audit": {"status": "future_separate_audit", "pass": None}, "native_mass_vs_nominal_continuum": "report_separately_without_rescale", "strict_precision": "diagnostic_only", "root470_strict_diagnostic": {"manifest": str(strict_path), "manifest_sha256": strict_path_sha}, "q_n_status": "not_assessed", "production_approval": "none"}, "expected_outputs": {"output_root": "{attempt_root}", "native_input_qa": "{attempt_root}/native-input-qa.json", "index": None, "future_report_sha256": None}, "arrays_read_by_source": False, "no_jobs_started_by_source": True, "no_shared_registry_write": True, "claim_boundary": "Measured native frame-0 structure only after Root enables this CPU audit; no native solver/visual/typed/precision/production credit is assigned by this request."}
        dump(request_out, request_out_value)
        cases.append({"case_id": case_id, "binding": binding_path, "binding_value": binding_value, "request": request_out, "request_value": request_out_value, "owner": owner, "owner_path": owner_path, "source_definition": source_def, "receipt_path": receipt_path, "report_path": report_path, "xml_path": xml_path, "bi4_path": bi4_path, "request_upstream": request_path, "xml_info": xml_info})
        package_plan.append({"case_id": case_id, "physical_case_id": owner["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "request": str(request_out), "request_sha256": sha(request_out), "binding": str(binding_path), "binding_sha256": sha(binding_path), "status": "future_disabled", "native_frame0_sha256": None, "qa_report_sha256": None})
    closure_paths = unique(static_common + [strict_path, ROOT470_REPORT] + [path for case in cases for path in (case["binding"], case["request"], case["owner_path"], case["source_definition"], case["receipt_path"], case["report_path"], case["xml_path"], case["request_upstream"])])
    closure = {str(path): sha(path) for path in closure_paths if path != ROOT470_REPORT}
    closure[str(ROOT470_REPORT)] = sha(ROOT470_REPORT)
    dump(output / "evidence/source-static-closure.json", {"schema": "ds02.f4.fresh094.source-static-closure.v1", "files": closure, "scientific_payloads_opened_or_hashed_by_source": [], "registered_gencase_bi4_producer_digests_bound": 24, "native_frame0_hashes": None, "strict_root470": {"path": str(strict_path), "sha256": strict_path_sha}, "source_only": True})
    dump(output / "metadata/fresh094-stage1-contract.json", {"schema": "ds02.f4.fresh094.stage1-contract.v1", "scope_id": SCOPE_ID, "family_id": "F4", "case_count": 24, "upstream_fresh093": {"manifest": ref(FRESH093_MANIFEST), "plan": ref(FRESH093_PLAN), "binding": ref(FRESH093_BINDING)}, "root230": root230, "root470_strict_diagnostic": {"path": str(strict_path), "sha256": strict_path_sha, "status": "negative_diagnostic_only", "not_a_stage1_substitute": True}, "worker": {"path": str(WORKER), "sha256": sha(WORKER)}, "stage1_checks": ["native receipt completed/0", "native Data2d false and Posd double3", "finite positions", "unique complete Idp", "exact CaseNp/CaseNfixed/CaseNfluid", "source UID block counts", "all fluid axes have multiple levels", "declared source drawbox inclusive extrema", "drop/pool non-overlap", "native gap inside tank", "source XML/Definition invariants", "native frame bytes unchanged"], "not_stage1_gates": ["native mass equals nominal continuum", "exact continuum center/lattice", "strict continuum center bounds", "saved frame-0 velocity", "precision", "Q-N", "production", "visual"], "mass_policy": "Report native and nominal continuum mass separately; mass_rescaled=false; no threshold loosening.", "future_hashes_null": True, "source_only": True})
    dump(output / "metadata/root230-upstream-contract.json", {"schema": "ds02.f4.fresh094.root230-upstream-contract.v1", "root230": root230, "fresh093_native_request_count": 24, "root470_strict_diagnostic": {"path": str(strict_path), "sha256": strict_path_sha, "not_a_stage1_substitute": True}, "source_only": True})
    dump(output / "evidence/request-index.json", {"schema": "ds02.f4.fresh094.request-index.v1", "scope_id": SCOPE_ID, "family_id": "F4", "case_count": 24, "rows": package_plan, "all_disabled": True, "launch_allowed": False, "future_native_frame0_hashes": None, "future_qa_hashes": None, "arrays_read_by_source": False, "jobs_started_by_source": False, "strict_precision_status": "diagnostic_only", "q_n_status": "not_assessed"})
    dump(output / "F4_STAGE1_FRESH094_BASIC_NATIVE_INPUT_QA_MANIFEST.json", {"schema": "ds02.f4.fresh094.manifest.v1", "scope_id": SCOPE_ID, "family_id": "F4", "case_count": 24, "requests": 24, "all_requests_disabled": True, "upstream_native": "fresh093 Root230 requests; all native receipts future/null", "strict_root237_diagnostic_preserved": True, "root470_strict_diagnostic": {"path": str(strict_path), "sha256": strict_path_sha, "status": "negative_diagnostic_only"}, "stage1_pass_status": "future_until_registered_native_frame0_audit", "actual_native_frame0_hashes": None, "future_qa_report_hashes": None, "precision_status": "not_accepted", "q_n_status": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0, "arrays_read_by_source": False, "source_only": True})
    (output / "README.md").write_text("""# F4 fresh094 stage-1 native input QA\n\nFresh094 is a separate Root-owned CPU audit for the 24 F4 native cases. It\nconsumes one completed Root230 native receipt and one producer-attested\nsolver-saved `Part_0000.bi4` per disabled request. The worker checks measured\n3-D finite positions, complete unique `Idp`, exact actual counts, XML-derived\nsource UID blocks, inclusive source drawbox extrema, drop/pool separation, the\nnative gap inside the tank, and source XML/Definition invariants.\n\nThe worker reports native mass beside nominal continuum mass without rescaling.\nExact continuum center/lattice checks and the Root470 centered-reference\nresult remain diagnostics; they cannot be used as a precision, Q-N, visual or\nproduction claim. Saved frame-0 velocity is a separate downstream audit.\n\nThe source package reads only JSON/XML/Python metadata and producer SHA\nattestations. BI4/Posd/Idp are opened only if Root enables the disabled CPU\nrequest with actual receipt/frame path/SHA. No solver, conversion, rendering,\narray copy, shared registry write or case credit is produced here.\n""", encoding="utf-8")
    return {"schema": "ds02.f4.fresh094.build-result.v1", "package": str(output), "case_count": 24, "requests": 24, "all_disabled": True, "root470_strict_preserved": True, "future_hashes_null": True, "arrays_read_by_source": False, "source_only": True}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
